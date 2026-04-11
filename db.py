import sqlite3
import json
import threading
from datetime import datetime, date, timedelta, timezone
from utils import (
    CAFE_TIMEZONE,
    get_active_booking_statuses,
    get_cafe_time,
    normalize_booking_status,
    normalize_slot_label,
    parse_slot_time,
    slots_equal,
    sort_slot_labels,
)

DATABASE = "cafebot.db"
_RUNTIME_SCHEMA_READY = False
_PENDING_TABLE_RELEASES = {}
_PENDING_TABLE_RELEASES_LOCK = threading.Lock()


def get_db_connection():
    conn = sqlite3.connect(DATABASE, timeout=20)
    conn.row_factory = lambda cursor, row: dict(
        (col[0], row[idx]) for idx, col in enumerate(cursor.description)
    )
    _ensure_runtime_schema(conn)
    return conn

def _has_column(conn, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r['name'] == column for r in rows)

def _has_table(conn, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None

def _ensure_runtime_schema(conn):
    global _RUNTIME_SCHEMA_READY
    if _RUNTIME_SCHEMA_READY or not _has_table(conn, "bookings"):
        return

    changed = False
    if not _has_column(conn, "bookings", "seated_at"):
        conn.execute("ALTER TABLE bookings ADD COLUMN seated_at TEXT")
        changed = True

    if _has_column(conn, "bookings", "seated_at"):
        conn.execute(
            """
            UPDATE bookings
            SET seated_at = COALESCE(NULLIF(seated_at, ''), NULLIF(updated_at, ''), NULLIF(created_at, ''))
            WHERE LOWER(TRIM(status)) = 'arrived' AND (seated_at IS NULL OR TRIM(seated_at) = '')
            """
        )
        changed = True

    if changed:
        conn.commit()

    _RUNTIME_SCHEMA_READY = True

def _active_status_params():
    statuses = get_active_booking_statuses()
    placeholders = ",".join("?" * len(statuses))
    return statuses, placeholders

def _now_iso():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

def _now_cafe_iso():
    return get_cafe_time().isoformat()

def _cancel_scheduled_table_release(table_number):
    if table_number is None:
        return
    with _PENDING_TABLE_RELEASES_LOCK:
        timer = _PENDING_TABLE_RELEASES.pop(int(table_number), None)
    if timer:
        timer.cancel()

def _schedule_table_release(table_number, delay_seconds=300):
    if table_number is None:
        return

    table_number = int(table_number)

    def _release():
        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT status FROM tables WHERE table_number = ?",
                (table_number,),
            ).fetchone()
            if row and row.get("status") == "Needs Cleaning":
                conn.execute(
                    "UPDATE tables SET status = 'Vacant' WHERE table_number = ?",
                    (table_number,),
                )
                conn.commit()
        except Exception as exc:
            print(f"[Cleaner] Failed to auto-release table {table_number}: {exc}")
        finally:
            conn.close()
            with _PENDING_TABLE_RELEASES_LOCK:
                _PENDING_TABLE_RELEASES.pop(table_number, None)

    timer = threading.Timer(delay_seconds, _release)
    timer.daemon = True
    with _PENDING_TABLE_RELEASES_LOCK:
        existing = _PENDING_TABLE_RELEASES.pop(table_number, None)
        if existing:
            existing.cancel()
        _PENDING_TABLE_RELEASES[table_number] = timer
    timer.start()

def force_release_table(table_number: int):
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT table_number, status FROM tables WHERE table_number = ?",
            (table_number,),
        ).fetchone()
        if not row:
            return False
        conn.execute(
            "UPDATE tables SET status = 'Vacant' WHERE table_number = ?",
            (table_number,),
        )
        conn.commit()
        _cancel_scheduled_table_release(table_number)
        return True
    except Exception as exc:
        print(f"Error force releasing table {table_number}: {exc}")
        return False
    finally:
        conn.close()

def parse_booking_datetime(dt_value):
    if not dt_value:
        return None
    if isinstance(dt_value, datetime):
        parsed = dt_value
    else:
        raw = str(dt_value).strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc).astimezone(CAFE_TIMEZONE)
    return parsed.astimezone(CAFE_TIMEZONE)

def get_seated_elapsed_minutes(seated_at_value, now=None):
    seated_at = parse_booking_datetime(seated_at_value)
    if seated_at is None:
        return 0

    if now is None:
        now = get_cafe_time()
    elif now.tzinfo is None:
        now = CAFE_TIMEZONE.localize(now)
    else:
        now = now.astimezone(CAFE_TIMEZONE)

    elapsed_seconds = (now - seated_at).total_seconds()
    return max(int(elapsed_seconds // 60), 0)

def format_service_timer(seated_at_value, now=None):
    minutes = get_seated_elapsed_minutes(seated_at_value, now=now)
    if minutes <= 0:
        return "Just seated"
    if minutes > 60:
        hours, remainder = divmod(minutes, 60)
        return f"Overdue: {hours}h {remainder}m"
    return f"{minutes} min"

def _normalize_slot_value(slot_time):
    if slot_time is None:
        return ""
    normalized = normalize_slot_label(slot_time)
    if normalized:
        return normalized
    return str(slot_time).strip()

def _booking_group_totals(conn, combo_groups, rows=None):
    totals = {}
    if not combo_groups:
        return totals
    combo_groups = list(dict.fromkeys(combo_groups))
    if _has_table(conn, "booking_groups"):
        placeholders = ",".join("?" * len(combo_groups))
        group_rows = conn.execute(
            f"SELECT id, total_guests FROM booking_groups WHERE id IN ({placeholders})",
            combo_groups,
        ).fetchall()
        for r in group_rows:
            if r["total_guests"] is not None:
                totals[r["id"]] = int(r["total_guests"])
    missing = [cg for cg in combo_groups if cg not in totals]
    if missing:
        if rows is not None:
            max_map = {}
            for r in rows:
                cg = r["combo_group"]
                if cg in missing:
                    seats_val = int(r["seats"] or 0)
                    max_map[cg] = max(seats_val, max_map.get(cg, 0))
            for cg in missing:
                if cg in max_map:
                    totals[cg] = max_map[cg]
        else:
            placeholders = ",".join("?" * len(missing))
            max_rows = conn.execute(
                f"SELECT combo_group, MAX(seats) as max_seats FROM bookings WHERE combo_group IN ({placeholders}) GROUP BY combo_group",
                missing,
            ).fetchall()
            for r in max_rows:
                totals[r["combo_group"]] = int(r["max_seats"] or 0)
    return totals

def _aggregate_booking_rows(rows, conn):
    combo_groups = [r["combo_group"] for r in rows if r["combo_group"]]
    totals = _booking_group_totals(conn, combo_groups, rows=rows)
    seen = set()
    booking_count = 0
    guest_total = 0
    for r in rows:
        cg = r["combo_group"]
        if cg:
            if cg in seen:
                continue
            seen.add(cg)
            booking_count += 1
            guest_total += totals.get(cg, int(r["seats"] or 0))
        else:
            booking_count += 1
            guest_total += int(r["seats"] or 0)
    return booking_count, guest_total

def get_combo_group_totals(combo_groups):
    """Public helper to fetch total guests for combo groups."""
    if not combo_groups:
        return {}
    conn = get_db_connection()
    try:
        return _booking_group_totals(conn, combo_groups)
    finally:
        conn.close()


#
# Twilio Session Management
#

def update_customer_session(phone):
    """Update or insert the last message timestamp for a user."""
    conn = get_db_connection()
    now = datetime.now().isoformat()
    conn.execute(
        """
        INSERT INTO customers (phone, last_message_timestamp)
        VALUES (?, ?)
        ON CONFLICT(phone) DO UPDATE SET last_message_timestamp = ?
        """, (phone, now, now)
    )
    conn.commit()
    conn.close()


def get_messageability(phone):
    """Check if the user is within the 24-hour Twilio Trial window."""
    conn = get_db_connection()
    customer = conn.execute(
        "SELECT last_message_timestamp FROM customers WHERE phone = ?", 
        (phone,)
    ).fetchone()
    conn.close()
    
    if not customer:
        return False
        
    last_msg_time = datetime.fromisoformat(customer["last_message_timestamp"])
    is_messageable = (datetime.now() - last_msg_time).total_seconds() <= (24 * 3600)
    return is_messageable

#
# WhatsApp Conversation Persistence
#

def get_conversation(phone):
    """Return conversation state/data for the given phone, or defaults."""
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT phone, state, data_json, updated_at FROM conversations WHERE phone = ?",
            (phone,),
        ).fetchone()
    except sqlite3.OperationalError:
        return {"phone": phone, "state": "idle", "data": {}, "updated_at": None}
    finally:
        conn.close()

    if not row:
        return {"phone": phone, "state": "idle", "data": {}, "updated_at": None}

    data = {}
    raw_json = row["data_json"]
    if raw_json:
        try:
            parsed = json.loads(raw_json)
            if isinstance(parsed, dict):
                data = parsed
        except Exception as e:
            # FIX 6: Log silent exception
            print(f"[ERROR] db.get_conversation: json.loads failed: {e}", flush=True)
            data = {}
    return {
        "phone": row["phone"],
        "state": row["state"] or "idle",
        "data": data,
        "updated_at": row["updated_at"],
    }


def save_conversation(phone, state, data=None):
    """Upsert conversation state/data for a phone."""
    payload = json.dumps(data or {})
    now = _now_iso()
    conn = get_db_connection()
    try:
        try:
            conn.execute(
                """
                INSERT INTO conversations (phone, state, data_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(phone) DO UPDATE SET
                    state = excluded.state,
                    data_json = excluded.data_json,
                    updated_at = excluded.updated_at
                """,
                (phone, state, payload, now),
            )
            conn.commit()
        except sqlite3.OperationalError:
            cur = conn.execute(
                "UPDATE conversations SET state = ?, data_json = ?, updated_at = ? WHERE phone = ?",
                (state, payload, now, phone),
            )
            if cur.rowcount == 0:
                conn.execute(
                    "INSERT INTO conversations (phone, state, data_json, updated_at) VALUES (?, ?, ?, ?)",
                    (phone, state, payload, now),
                )
            conn.commit()
    finally:
        conn.close()


def clear_conversation(phone):
    """Delete conversation row for a phone."""
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM conversations WHERE phone = ?", (phone,))
        conn.commit()
    finally:
        conn.close()


def update_conversation_data(phone, **kwargs):
    """Merge keys into existing conversation data and save."""
    convo = get_conversation(phone)
    data = convo.get("data", {}) or {}
    data.update(kwargs)
    save_conversation(phone, convo.get("state", "idle"), data)

#
# Admin Authentication
#

def get_user_by_username(username: str):
    """Fetch an admin row by username."""
    conn = get_db_connection()
    admin = conn.execute(
        "SELECT * FROM users WHERE username = ?", (username,)
    ).fetchone()
    conn.close()
    return admin


def create_user(username: str, password: str):
    """Create a new admin with a hashed password."""
    from werkzeug.security import generate_password_hash

    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'admin')",
            (username, generate_password_hash(password)),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def get_all_users():
    """Return all user rows (for staff management)."""
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM users ORDER BY role, username").fetchall()
    conn.close()
    return rows


def set_reset_otp(username: str, otp: str, expiry_iso: str) -> bool:
    """Store a 6-digit OTP and its expiry timestamp for a user."""
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE users SET reset_otp = ?, reset_otp_expiry = ? WHERE username = ?",
            (otp, expiry_iso, username),
        )
        conn.commit()
        return True
    except Exception as exc:
        print(f"[OTP] set_reset_otp error: {exc}")
        return False
    finally:
        conn.close()


def verify_and_clear_otp(username: str, otp: str) -> tuple[bool, str]:
    """
    Check that `otp` matches the stored OTP for `username` and has not expired.
    Clears the OTP from the DB on success.
    Returns (True, "") on success, (False, reason) on failure.
    """
    from datetime import datetime, timezone

    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT reset_otp, reset_otp_expiry FROM users WHERE username = ?",
            (username,),
        ).fetchone()

        if not row:
            return False, "User not found."

        stored_otp = row.get("reset_otp") or ""
        expiry_str = row.get("reset_otp_expiry") or ""

        if not stored_otp:
            return False, "No OTP was requested for this account."

        if stored_otp != otp.strip():
            return False, "Incorrect OTP. Please try again."

        if expiry_str:
            try:
                expiry = datetime.fromisoformat(expiry_str)
                now = datetime.now(timezone.utc)
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
                if now > expiry:
                    # Clear expired OTP
                    conn.execute(
                        "UPDATE users SET reset_otp = NULL, reset_otp_expiry = NULL WHERE username = ?",
                        (username,),
                    )
                    conn.commit()
                    return False, "OTP has expired. Please request a new one."
            except Exception as e:
                # FIX 6: Log silent exception
                print(f"[ERROR] db.verify_and_clear_otp: datetime parsing failed: {e}", flush=True)
                pass  # If we can't parse expiry, allow it through

        # OTP is valid — clear it
        conn.execute(
            "UPDATE users SET reset_otp = NULL, reset_otp_expiry = NULL WHERE username = ?",
            (username,),
        )
        conn.commit()
        return True, ""
    except Exception as exc:
        return False, str(exc)
    finally:
        conn.close()


def update_user_password(username: str, new_password: str) -> bool:
    """Update a user's password hash."""
    from werkzeug.security import generate_password_hash

    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?",
            (generate_password_hash(new_password), username),
        )
        conn.commit()
        return True
    except Exception as exc:
        print(f"[Auth] update_user_password error: {exc}")
        return False
    finally:
        conn.close()


def update_user_phone(username: str, phone: str) -> bool:
    """Update the recovery phone number for a user."""
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE users SET phone = ? WHERE username = ?",
            (phone.strip(), username),
        )
        conn.commit()
        return True
    except Exception as exc:
        print(f"[Auth] update_user_phone error: {exc}")
        return False
    finally:
        conn.close()


def update_user_email(username: str, email: str) -> bool:
    """Update the recovery email address for a user."""
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE users SET email = ? WHERE username = ?",
            (email.strip().lower(), username),
        )
        conn.commit()
        return True
    except Exception as exc:
        print(f"[Auth] update_user_email error: {exc}")
        return False
    finally:
        conn.close()


#
# Slots
#

def get_available_slots(date, filter_past=False):
    """Fetch slots for a specific date and compute remaining seats from bookings.

    If filter_past=True, slots whose start time has already passed (for today)
    are excluded so customers only see future slots.
    """
    from utils import get_cafe_time
    conn = get_db_connection()
    slots = conn.execute(
        """
        SELECT * FROM time_slots
        WHERE date = ?
        ORDER BY slot_time ASC
        """,
        (date,),
    ).fetchall()
    statuses, placeholders = _active_status_params()
    bookings = conn.execute(
        f"SELECT slot_time, seats, combo_group FROM bookings WHERE date = ? AND status IN ({placeholders})",
        (date, *statuses),
    ).fetchall()

    now = get_cafe_time() if filter_past else None

    result = []
    for slot in slots:
        slot_label = slot["slot_time"]

        # Skip past slots when filter_past is enabled
        if filter_past and now is not None:
            slot_start, _ = parse_slot_time(slot_label, date)
            if slot_start is not None and slot_start <= now:
                continue

        slot_rows = [b for b in bookings if slots_equal(b["slot_time"], slot_label)]
        _, booked_guests = _aggregate_booking_rows(slot_rows, conn)
        max_guests = DEFAULT_MAX_GUESTS_PER_SLOT
        if slot["max_guests"] is not None:
            max_guests = int(slot["max_guests"])
        elif slot["total_capacity"] is not None:
            max_guests = int(slot["total_capacity"])
        remaining = max_guests - booked_guests
        if remaining <= 0:
            continue
        slot_dict = dict(slot)
        slot_dict["available_seats"] = remaining
        result.append(slot_dict)
    conn.close()
    return result


def get_slot(date, slot_time):
    """Get a specific slot to check capacity."""
    conn = get_db_connection()
    slots = conn.execute(
        "SELECT * FROM time_slots WHERE date = ?",
        (date,),
    ).fetchall()
    conn.close()
    if not slots:
        return None
    for slot in slots:
        if slots_equal(slot["slot_time"], slot_time):
            return slot
    return None


#
# Slot Capacity Control
#

DEFAULT_MAX_GUESTS_PER_SLOT = 30


def get_slot_booked_guests(date: str, slot_time: str) -> int:
    """Return total guests currently booked for this slot."""
    conn = get_db_connection()
    statuses, placeholders = _active_status_params()
    rows = conn.execute(
        f"SELECT slot_time, seats, combo_group FROM bookings WHERE date = ? AND status IN ({placeholders})",
        (date, *statuses),
    ).fetchall()
    slot_rows = [r for r in rows if slots_equal(r["slot_time"], slot_time)]
    _, guest_total = _aggregate_booking_rows(slot_rows, conn)
    conn.close()
    return guest_total


def check_slot_capacity(date: str, slot_time: str, new_guests: int):
    """
    Check if adding `new_guests` would exceed the slot's max capacity.
    Returns (allowed: bool, remaining: int).
    """
    slot = get_slot(date, slot_time)

    max_guests = DEFAULT_MAX_GUESTS_PER_SLOT
    if slot and slot["max_guests"] is not None:
        max_guests = int(slot["max_guests"])

    current_booked = get_slot_booked_guests(date, slot_time)
    remaining = max_guests - current_booked

    return (new_guests <= remaining), remaining


#
# Capacity helpers
#

def get_required_capacity(guests: int) -> int:
    """Return the smallest table capacity that fits the guest count."""
    if guests <= 2:
        return 2
    elif guests <= 4:
        return 4
    elif guests <= 6:
        return 6
    else:
        return 8


#
# Table queries
#

def get_available_tables(date: str, slot_time: str, guests: int):
    """
    Return tables with the correct capacity that are NOT already booked
    for the given date + slot_time.
    """
    conn = get_db_connection()
    statuses, placeholders = _active_status_params()
    tables = conn.execute(
        "SELECT * FROM tables WHERE capacity >= ? ORDER BY capacity ASC, table_number ASC",
        (guests,),
    ).fetchall()
    bookings = conn.execute(
        f"""
        SELECT table_number, slot_time FROM bookings
        WHERE date = ? AND status IN ({placeholders}) AND table_number IS NOT NULL
        """,
        (date, *statuses),
    ).fetchall()
    conn.close()

    booked_tables = {
        b["table_number"]
        for b in bookings
        if slots_equal(b["slot_time"], slot_time)
    }
    return [t for t in tables if t["table_number"] not in booked_tables]


def get_combined_tables(date: str, slot_time: str, guests: int):
    """
    Try to combine multiple smaller available tables to fit the guest count.
    Returns a list of table dicts if combination found, else empty list.
    Uses a greedy approach: pick smallest-first until capacity is met.
    """
    conn = get_db_connection()
    statuses, placeholders = _active_status_params()
    all_tables = conn.execute(
        "SELECT * FROM tables ORDER BY capacity ASC, table_number ASC"
    ).fetchall()
    bookings = conn.execute(
        f"""
        SELECT table_number, slot_time FROM bookings
        WHERE date = ? AND status IN ({placeholders}) AND table_number IS NOT NULL
        """,
        (date, *statuses),
    ).fetchall()
    conn.close()

    booked_tables = {
        b["table_number"]
        for b in bookings
        if slots_equal(b["slot_time"], slot_time)
    }
    all_available = [t for t in all_tables if t["table_number"] not in booked_tables]

    if not all_available:
        return []

    # Greedy: pick tables until cumulative capacity >= guests
    combo = []
    total_capacity = 0
    for table in all_available:
        combo.append({
            "table_number": int(table["table_number"]),
            "capacity": int(table["capacity"]),
            "location": table["location"],
        })
        total_capacity += int(table["capacity"])
        if total_capacity >= guests:
            return combo

    # Not enough even with all tables
    return []


def get_table_info(table_number: int):
    """Fetch a single table row by table_number."""
    conn = get_db_connection()
    table = conn.execute(
        "SELECT * FROM tables WHERE table_number = ?",
        (table_number,),
    ).fetchone()
    conn.close()
    return table


def get_all_tables():
    """Fetch every table (for admin use)."""
    conn = get_db_connection()
    tables = conn.execute(
        "SELECT * FROM tables ORDER BY table_number ASC"
    ).fetchall()
    conn.close()
    return tables


def get_table_status(date: str, slot_time: str):
    """
    Return all tables with an extra `is_booked` flag (1/0) for the
    given date + slot_time combination.  Used by the admin grid.
    """
    conn = get_db_connection()
    statuses, placeholders = _active_status_params()
    statuses = statuses + ("Completed",)
    placeholders = ",".join("?" * len(statuses))
    tables = conn.execute(
        "SELECT * FROM tables ORDER BY table_number ASC"
    ).fetchall()
    bookings = conn.execute(
        f"""
        SELECT table_number, slot_time FROM bookings
        WHERE date = ? AND status IN ({placeholders}) AND table_number IS NOT NULL
        """,
        (date, *statuses),
    ).fetchall()
    conn.close()

    booked_numbers = {
        b["table_number"]
        for b in bookings
        if slots_equal(b["slot_time"], slot_time)
    }
    rows = []
    for t in tables:
        row = dict(t)
        row["is_booked"] = 1 if t["table_number"] in booked_numbers else 0
        rows.append(row)
    return rows


#
# Bookings
#

def create_booking(phone, name, date, slot_time, seats, table_number=None, combo_group=None, source='bot'):
    """Create a new booking. Relies purely on table capacity rather than seat pooling."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        slot_time = _normalize_slot_value(slot_time)
        # Use IMMEDIATE to acquire a reserved lock and prevent concurrent insert race conditions
        cursor.execute("BEGIN IMMEDIATE")

        # Prevent duplicate booking for the same phone + slot
        statuses, status_placeholders = _active_status_params()
        duplicate_rows = cursor.execute(
            f"SELECT slot_time FROM bookings WHERE phone = ? AND date = ? AND status IN ({status_placeholders})",
            (phone, date, *statuses),
        ).fetchall()
        if any(slots_equal(row["slot_time"], slot_time) for row in duplicate_rows):
            conn.rollback()
            return False, "You already have a booking for this slot.", None

        # Prevent overbooking the same table
        if table_number is not None:
            statuses, placeholders = _active_status_params()
            conflict_rows = cursor.execute(
                f"""
                SELECT slot_time FROM bookings
                WHERE table_number = ? AND date = ? AND status IN ({placeholders})
                """,
                (table_number, date, *statuses),
            ).fetchall()
            if any(slots_equal(row["slot_time"], slot_time) for row in conflict_rows):
                return False, "That table has just been booked. Please choose another.", None

        slot_rows = cursor.execute(
            "SELECT * FROM time_slots WHERE date = ?",
            (date,),
        ).fetchall()
        slot = None
        for row in slot_rows:
            if slots_equal(row["slot_time"], slot_time):
                slot = row
                break
        if not slot:
            return False, "Selected time slot is not available.", None

        # Slot capacity check
        max_guests = DEFAULT_MAX_GUESTS_PER_SLOT
        if slot["max_guests"] is not None:
            max_guests = int(slot["max_guests"])
        current_booked = get_slot_booked_guests(date, slot_time)
        if current_booked + seats > max_guests:
            return False, f"Slot capacity exceeded. Only {max_guests - current_booked} seats remaining.", None

        columns = ["phone", "name", "date", "slot_time", "seats", "table_number", "combo_group", "status"]
        values = [phone, name, date, slot_time, seats, table_number, combo_group, "Pending"]
        if _has_column(conn, "bookings", "source"):
            columns.append("source")
            values.append(source)
        if _has_column(conn, "bookings", "created_at"):
            columns.append("created_at")
            values.append(_now_iso())
        if _has_column(conn, "bookings", "updated_at"):
            columns.append("updated_at")
            values.append(_now_iso())
        placeholders = ",".join("?" * len(columns))
        cursor.execute(
            f"INSERT INTO bookings ({', '.join(columns)}) VALUES ({placeholders})",
            values,
        )
        booking_id = cursor.lastrowid

        conn.commit()
        return True, "Booking successful.", booking_id
    except sqlite3.IntegrityError:
        conn.rollback()
        return False, "RACE_CONDITION: Table was just taken. Please try again.", None
    except Exception as exc:
        conn.rollback()
        return False, str(exc), None
    finally:
        conn.close()
# atomatic seat 

def atomic_quick_seat(phone, name, date, slot_time, seats, table_number):
    """
    Staff pos-style fast seating. Uses BEGIN IMMEDIATE to prevent race conditions
    without fully locking the database exclusively.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        slot_time = _normalize_slot_value(slot_time)
        # Use IMMEDIATE instead of EXCLUSIVE to allow shared reads
        cursor.execute("BEGIN IMMEDIATE")
        
        statuses, placeholders = _active_status_params()
        conflict_rows = cursor.execute(
            f"""
            SELECT slot_time FROM bookings 
            WHERE table_number = ? AND date = ? 
            AND status IN ({placeholders})
            """,
            (table_number, date, *statuses)
        ).fetchall()
        
        if any(slots_equal(row["slot_time"], slot_time) for row in conflict_rows):
            conn.rollback()
            return False, "Table already occupied!", None

        # Slot capacity check
        slot_rows = cursor.execute("SELECT * FROM time_slots WHERE date = ?", (date,)).fetchall()
        slot = None
        for row in slot_rows:
            if slots_equal(row["slot_time"], slot_time):
                slot = row
                break
        if not slot:
            conn.rollback()
            return False, "Selected time slot is not available.", None
            
        max_guests = 30
        if slot["max_guests"] is not None:
            max_guests = int(slot["max_guests"])
            
        slot_bookings = cursor.execute(
            f"SELECT seats FROM bookings WHERE date = ? AND status IN ({placeholders}) AND slot_time = ?",
            (date, *statuses, slot_time)
        ).fetchall()
        current_booked = sum(int(r['seats'] or 0) for r in slot_bookings)
        if current_booked + seats > max_guests:
            conn.rollback()
            return False, f"Slot capacity exceeded. Only {max_guests - current_booked} seats remaining.", None

        final_phone = phone if phone else "walkin:staff"
        
        columns = ["phone", "name", "date", "slot_time", "seats", "table_number", "status"]
        values = [final_phone, name, date, slot_time, seats, table_number, "Arrived"]
        if _has_column(conn, "bookings", "source"):
            columns.append("source")
            values.append("walkin")
        if _has_column(conn, "bookings", "created_at"):
            columns.append("created_at")
            values.append(_now_iso())
        if _has_column(conn, "bookings", "updated_at"):
            columns.append("updated_at")
            values.append(_now_iso())
        if _has_column(conn, "bookings", "seated_at"):
            columns.append("seated_at")
            values.append(_now_cafe_iso())
        insert_placeholders = ",".join("?" * len(columns))
        cursor.execute(
            f"INSERT INTO bookings ({', '.join(columns)}) VALUES ({insert_placeholders})",
            values
        )
        booking_id = cursor.lastrowid
        
        cursor.execute("UPDATE tables SET status = 'Occupied' WHERE table_number = ?", (table_number,))
        
        conn.commit()
        return True, "Booking successful.", booking_id
    except Exception as e:
        conn.rollback()
        return False, str(e), None
    finally:
        conn.close()


def instant_walk_in_seat(table_number, seats, phone="walkin:staff", name="Walk-In Guest"):
    """Seat a walk-in immediately without requiring a reservation slot."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        seats = int(seats)
    except (TypeError, ValueError):
        return False, "Guest count must be a whole number.", None

    if seats < 1:
        return False, "Guest count must be at least 1.", None

    now = get_cafe_time()
    today_date = str(now.date())

    try:
        cursor.execute("BEGIN IMMEDIATE")

        table = cursor.execute(
            "SELECT table_number, capacity, status FROM tables WHERE table_number = ?",
            (table_number,),
        ).fetchone()
        if not table:
            conn.rollback()
            return False, "Table not found.", None

        capacity = int(table.get("capacity") or 0)
        if capacity and seats > capacity:
            conn.rollback()
            return False, f"Table T{table_number} only fits {capacity} guests.", None

        table_status = table.get("status") or "Vacant"
        if table_status != "Vacant":
            conn.rollback()
            return False, f"Table T{table_number} is currently {table_status}.", None

        statuses, placeholders = _active_status_params()
        active_rows = cursor.execute(
            f"""
            SELECT status FROM bookings
            WHERE table_number = ? AND date = ? AND status IN ({placeholders})
            """,
            (table_number, today_date, *statuses),
        ).fetchall()
        if any(normalize_booking_status(row["status"]) == "Arrived" for row in active_rows):
            conn.rollback()
            return False, f"Table T{table_number} is already occupied.", None

        slot_label = f"{now.strftime('%I:%M %p').lstrip('0')} (Walk-In)"
        columns = ["phone", "name", "date", "slot_time", "seats", "table_number", "status"]
        values = [phone or "walkin:staff", name, today_date, slot_label, seats, table_number, "Arrived"]
        if _has_column(conn, "bookings", "source"):
            columns.append("source")
            values.append("walkin")
        if _has_column(conn, "bookings", "created_at"):
            columns.append("created_at")
            values.append(_now_iso())
        if _has_column(conn, "bookings", "updated_at"):
            columns.append("updated_at")
            values.append(_now_iso())
        if _has_column(conn, "bookings", "seated_at"):
            columns.append("seated_at")
            values.append(_now_cafe_iso())

        insert_placeholders = ",".join("?" * len(columns))
        cursor.execute(
            f"INSERT INTO bookings ({', '.join(columns)}) VALUES ({insert_placeholders})",
            values,
        )
        booking_id = cursor.lastrowid

        cursor.execute("UPDATE tables SET status = 'Occupied' WHERE table_number = ?", (table_number,))
        conn.commit()
        return True, f"Table T{table_number} is now occupied.", booking_id
    except Exception as exc:
        conn.rollback()
        return False, str(exc), None
    finally:
        conn.close()


def create_combo_booking(phone, name, date, slot_time, seats, table_numbers, source='bot'):
    """
    Create linked bookings across multiple combined tables.
    All share the same combo_group ID.
    Returns (success, message, booking_ids).
    """
    import uuid
    combo_group = str(uuid.uuid4())[:8]

    conn = get_db_connection()
    cursor = conn.cursor()
    booking_ids = []

    try:
        slot_time = _normalize_slot_value(slot_time)
        # Use IMMEDIATE to acquire a reserved lock
        cursor.execute("BEGIN IMMEDIATE")

        # Prevent duplicate booking for the same phone + slot
        statuses, status_placeholders = _active_status_params()
        duplicate_rows = cursor.execute(
            f"SELECT slot_time FROM bookings WHERE phone = ? AND date = ? AND status IN ({status_placeholders})",
            (phone, date, *statuses),
        ).fetchall()
        if any(slots_equal(row["slot_time"], slot_time) for row in duplicate_rows):
            conn.rollback()
            return False, "You already have a booking for this slot.", []

        slot_rows = cursor.execute(
            "SELECT * FROM time_slots WHERE date = ?",
            (date,),
        ).fetchall()
        slot = None
        for row in slot_rows:
            if slots_equal(row["slot_time"], slot_time):
                slot = row
                break
        if not slot:
            return False, "Selected time slot is not available.", []

        # Slot capacity check
        max_guests = DEFAULT_MAX_GUESTS_PER_SLOT
        if slot["max_guests"] is not None:
            max_guests = int(slot["max_guests"])
        current_booked = get_slot_booked_guests(date, slot_time)
        if current_booked + seats > max_guests:
            return False, f"Slot capacity exceeded. Only {max_guests - current_booked} seats remaining.", []

        # Allocate seats across tables to avoid duplicate guest counts per row
        remaining = int(seats)
        table_allocations = []
        for tn in table_numbers:
            table_info = get_table_info(tn)
            if not table_info:
                conn.rollback()
                return False, f"Table {tn} not found.", []
            capacity = int(table_info["capacity"] or 0)
            assigned = min(capacity, remaining)
            if assigned <= 0:
                conn.rollback()
                return False, "Table allocation failed. Please try again.", []
            table_allocations.append((tn, assigned))
            remaining -= assigned
        if remaining > 0:
            conn.rollback()
            return False, "Not enough table capacity for this party size.", []

        if _has_table(conn, "booking_groups"):
            cursor.execute(
                """
                INSERT INTO booking_groups (id, phone, name, date, slot_time, total_guests, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (combo_group, phone, name, date, slot_time, int(seats), _now_iso()),
            )

        for tn, assigned_seats in table_allocations:
            # Check table not already booked
            conflict_rows = cursor.execute(
                f"SELECT slot_time FROM bookings WHERE table_number = ? AND date = ? AND status IN ({status_placeholders})",
                (tn, date, *statuses),
            ).fetchall()
            if any(slots_equal(row["slot_time"], slot_time) for row in conflict_rows):
                conn.rollback()
                return False, f"Table {tn} was just booked. Please try again.", []

            columns = ["phone", "name", "date", "slot_time", "seats", "table_number", "combo_group", "status"]
            values = [phone, name, date, slot_time, assigned_seats, tn, combo_group, "Pending"]
            if _has_column(conn, "bookings", "source"):
                columns.append("source")
                values.append(source)
            if _has_column(conn, "bookings", "created_at"):
                columns.append("created_at")
                values.append(_now_iso())
            if _has_column(conn, "bookings", "updated_at"):
                columns.append("updated_at")
                values.append(_now_iso())
            insert_placeholders = ",".join("?" * len(columns))
            cursor.execute(
                f"INSERT INTO bookings ({', '.join(columns)}) VALUES ({insert_placeholders})",
                values,
            )
            booking_ids.append(cursor.lastrowid)

        conn.commit()
        return True, "Booking successful.", booking_ids
    except sqlite3.IntegrityError:
        conn.rollback()
        return False, "RACE_CONDITION: Table was just taken. Please try again.", []
    except Exception as exc:
        conn.rollback()
        return False, str(exc), []
    finally:
        conn.close()


def get_user_bookings(phone):
    """Fetch all active bookings for a user (deduplicated by combo_group)."""
    conn = get_db_connection()
    statuses, placeholders = _active_status_params()
    bookings = conn.execute(
        f"""
        SELECT * FROM bookings
        WHERE phone = ? AND status IN ({placeholders})
        ORDER BY date ASC, slot_time ASC, id ASC
        """,
        (phone, *statuses),
    ).fetchall()
    combo_groups = [b["combo_group"] for b in bookings if b["combo_group"]]
    totals = _booking_group_totals(conn, combo_groups, rows=bookings)
    conn.close()

    # Deduplicate combo bookings; show only the first entry per combo group
    seen_combos = set()
    result = []
    for b in bookings:
        cg = b["combo_group"]
        if cg:
            if cg in seen_combos:
                continue
            seen_combos.add(cg)
        entry = dict(b)
        if cg and cg in totals:
            entry["seats"] = totals[cg]
        result.append(entry)
    return result


def get_booking_for_user(phone, booking_id):
    conn = get_db_connection()
    statuses, placeholders = _active_status_params()
    booking = conn.execute(
        f"SELECT * FROM bookings WHERE phone = ? AND id = ? AND status IN ({placeholders})",
        (phone, booking_id, *statuses),
    ).fetchone()
    if not booking:
        conn.close()
        return None
    entry = dict(booking)
    if entry.get("combo_group"):
        totals = _booking_group_totals(conn, [entry["combo_group"]])
        if entry["combo_group"] in totals:
            entry["seats"] = totals[entry["combo_group"]]
    conn.close()
    return entry


def get_combo_tables(combo_group: str):
    """Get all table numbers associated with a combo booking."""
    if not combo_group:
        return []
    conn = get_db_connection()
    statuses, placeholders = _active_status_params()
    rows = conn.execute(
        f"SELECT table_number FROM bookings WHERE combo_group = ? AND status IN ({placeholders})",
        (combo_group, *statuses),
    ).fetchall()
    conn.close()
    return [r["table_number"] for r in rows]


def set_booking_payment_link(booking_id, link_id):
    """Store the Razorpay payment link ID on a booking."""
    conn = get_db_connection()
    try:
        if _has_column(conn, "bookings", "payment_link_id"):
            conn.execute(
                "UPDATE bookings SET payment_link_id = ? WHERE id = ?",
                (link_id, booking_id),
            )
            # Also update combo group siblings if any
            combo_group = conn.execute("SELECT combo_group FROM bookings WHERE id = ?", (booking_id,)).fetchone()
            if combo_group and combo_group["combo_group"]:
                conn.execute(
                    "UPDATE bookings SET payment_link_id = ? WHERE combo_group = ?",
                    (link_id, combo_group["combo_group"]),
                )
            conn.commit()
    finally:
        conn.close()


def delete_pending_booking(booking_id):
    """Hard delete a booking and its combo siblings if payment failed/abandoned."""
    conn = get_db_connection()
    try:
        combo_group = conn.execute("SELECT combo_group FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        if combo_group and combo_group["combo_group"]:
            conn.execute("DELETE FROM bookings WHERE combo_group = ?", (combo_group["combo_group"],))
            conn.execute("DELETE FROM booking_groups WHERE id = ?", (combo_group["combo_group"],))
        else:
            conn.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
        conn.commit()
    finally:
        conn.close()


def cancel_booking_by_id(phone, booking_id):
    """Cancel a booking by id for the given phone. Also cancels combo-linked bookings."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        statuses, placeholders = _active_status_params()
        booking = cursor.execute(
            f"SELECT * FROM bookings WHERE phone = ? AND id = ? AND status IN ({placeholders})",
            (phone, booking_id, *statuses),
        ).fetchone()
        if not booking:
            return False, "Booking not found."

        booking_date = datetime.strptime(booking["date"], "%Y-%m-%d").date()
        slot_time = booking["slot_time"].strip() if booking["slot_time"] else ""

        from utils import get_cafe_time, get_cafe_date
        now = get_cafe_time()
        today = get_cafe_date()

        if booking_date < today:
            return False, "Cannot cancel past bookings."

        booking_start_dt, _ = parse_slot_time(slot_time, booking["date"])
        if booking_start_dt is not None:
            if booking_date == today and booking_start_dt <= now:
                return False, "Cannot cancel a booking that has already started."

        # Cancel the booking (and all combo-linked bookings)
        combo_group = booking["combo_group"]
        if combo_group:
            cursor.execute(
                "UPDATE bookings SET status = 'cancelled' WHERE combo_group = ?",
                (combo_group,),
            )
            cursor.execute(
                "UPDATE tables SET status = 'Vacant' WHERE table_number IN (SELECT table_number FROM bookings WHERE combo_group = ? AND table_number IS NOT NULL)",
                (combo_group,)
            )
        else:
            cursor.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (booking["id"],))
            if booking["table_number"]:
                cursor.execute(
                    "UPDATE tables SET status = 'Vacant' WHERE table_number = ?",
                    (booking["table_number"],)
                )

        conn.commit()

        # Auto-allocate waitlisted user (if any)
        _auto_allocate_waitlist(booking["date"], booking["slot_time"])

        return True, "Booking cancelled successfully."
    except Exception as exc:
        conn.rollback()
        return False, str(exc)
    finally:
        conn.close()


def _auto_allocate_waitlist(date: str, slot_time: str):
    """Check waitlist and auto-allocate the next person if a slot/table is free."""
    try:
        conn = get_db_connection()
        # ORDER BY created_at ASC for fairness (FIFO)
        pending_entries = conn.execute(
            "SELECT * FROM waitlist WHERE date = ? AND status = 'pending' ORDER BY created_at ASC",
            (date,)
        ).fetchall()
        
        for entry in pending_entries:
            if not slots_equal(entry["slot_time"], slot_time):
                continue

            seats = int(entry['guests'])
            
            cursor = conn.cursor()
            message_sent = False
            assigned_table_number = None
            assigned_location = None
            
            try:
                # ⚡ Double allocation protection: Check capacity and availability inside a transaction
                cursor.execute("BEGIN IMMEDIATE")
                
                # Re-check waitlist entry is still pending
                current_entry = cursor.execute(
                    "SELECT status FROM waitlist WHERE id = ?", (entry["id"],)
                ).fetchone()
                if not current_entry or current_entry["status"] != 'pending':
                    conn.rollback()
                    continue
                
                # FIX 2: Skip auto-allocation if user has pending payment booking
                existing_pending = cursor.execute(
                    "SELECT id FROM bookings WHERE phone = ? AND status = 'Pending'",
                    (entry["phone"],)
                ).fetchone()
                if existing_pending:
                    conn.rollback()
                    continue
                    
                statuses, placeholders = _active_status_params()
                all_date_bookings = cursor.execute(
                    f"SELECT slot_time, seats, table_number, combo_group FROM bookings WHERE date = ? AND status IN ({placeholders})",
                    (date, *statuses)
                ).fetchall()
                
                slot_bookings = [b for b in all_date_bookings if slots_equal(b["slot_time"], slot_time)]
                _, current_booked = _aggregate_booking_rows(slot_bookings, conn)
                
                slot = cursor.execute(
                    "SELECT max_guests, slot_time FROM time_slots WHERE date = ?",
                    (date,)
                ).fetchall()
                
                max_guests = DEFAULT_MAX_GUESTS_PER_SLOT
                for s in slot:
                    if slots_equal(s["slot_time"], slot_time):
                        if s["max_guests"] is not None:
                            max_guests = int(s["max_guests"])
                        break
                        
                if current_booked + seats > max_guests:
                    conn.rollback()
                    continue
                    
                booked_tables = {b["table_number"] for b in slot_bookings if b["table_number"] is not None}
                # Prefer smallest fitting table with ORDER BY capacity ASC
                all_tables = cursor.execute(
                    "SELECT * FROM tables WHERE capacity >= ? ORDER BY capacity ASC, table_number ASC",
                    (seats,)
                ).fetchall()
                
                available_tables = [t for t in all_tables if t["table_number"] not in booked_tables]
                if not available_tables:
                    conn.rollback()
                    continue
                    
                t = available_tables[0]
                assigned_table_number = t["table_number"]
                assigned_location = t["location"]
                
                columns = ["phone", "name", "date", "slot_time", "seats", "table_number", "status", "source"]
                values = [entry["phone"], entry["name"], date, slot_time, seats, assigned_table_number, "Confirmed", "waitlist_auto"]
                
                if _has_column(conn, "bookings", "is_auto_allocated"):
                    columns.append("is_auto_allocated")
                    values.append(1)
                if _has_column(conn, "bookings", "created_at"):
                    columns.append("created_at")
                    values.append(_now_iso())
                if _has_column(conn, "bookings", "updated_at"):
                    columns.append("updated_at")
                    values.append(_now_iso())
                    
                binds = ",".join("?" * len(columns))
                cursor.execute(
                    f"INSERT INTO bookings ({', '.join(columns)}) VALUES ({binds})",
                    values
                )
                
                cursor.execute("UPDATE tables SET status = 'Reserved' WHERE table_number = ?", (assigned_table_number,))
                # Already-notified users: Ensure waitlist entry is marked processed
                cursor.execute("UPDATE waitlist SET status = 'allocated' WHERE id = ?", (entry["id"],))
                
                conn.commit()
                message_sent = True
            except sqlite3.IntegrityError:
                conn.rollback()
                continue
            except Exception as e:
                conn.rollback()
                print(f"⚠️ Transaction error in waitlist auto-allocation: {e}")
                continue
                
            # WhatsApp timing: Message sent AFTER DB commit
            if message_sent:
                try:
                    from notifier import send_whatsapp_message
                    message = (
                        f"🎉 Great news, {entry['name']}!\n\n"
                        f"You have been auto-upgraded from the waitlist.\n"
                        f"Your booking for {date} at {slot_time} is now CONFIRMED!\n"
                        f"Assigned Table: {assigned_table_number} ({assigned_location})\n\n"
                        f"☕ CoziCafe"
                    )
                    send_whatsapp_message(entry['phone'], message)
                except Exception as e:
                    print(f"⚠️ Error sending waitlist notification: {e}")
                    
    except Exception as e:
        print(f"⚠️ Waitlist auto-allocation error: {e}")
    finally:
        if 'conn' in locals() and conn:
            conn.close()


# DEAD CODE [audit] - wrapper function never called; use cancel_booking_by_id() directly
# def cancel_user_booking(phone):
#     """Backward-compatible helper that cancels the latest booking for this phone."""
#     conn = get_db_connection()
#     latest = conn.execute(
#         "SELECT id FROM bookings WHERE phone = ? ORDER BY id DESC LIMIT 1",
#         (phone,),
#     ).fetchone()
#     conn.close()
# 
#     if not latest:
#         return False, "No active bookings found to cancel."
# 
#     return cancel_booking_by_id(phone, latest["id"])



# Waitlist

def add_to_waitlist(phone: str, name: str, date: str, slot_time: str, guests: int):
    """Add user to waitlist for a specific slot."""
    conn = get_db_connection()
    try:
        slot_time = _normalize_slot_value(slot_time)
        # Prevent duplicate waitlist entry
        existing_rows = conn.execute(
            "SELECT slot_time FROM waitlist WHERE phone = ? AND date = ? AND status = 'pending'",
            (phone, date),
        ).fetchall()
        if any(slots_equal(row["slot_time"], slot_time) for row in existing_rows):
            return False, "You are already on the waitlist for this slot."

        conn.execute(
            "INSERT INTO waitlist (phone, name, date, slot_time, guests) VALUES (?, ?, ?, ?, ?)",
            (phone, name, date, slot_time, guests),
        )
        conn.commit()
        return True, "Added to waitlist successfully."
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()


def get_next_waitlist(date: str, slot_time: str):
    """Fetch the oldest pending waitlist entry for this slot."""
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT * FROM waitlist WHERE date = ? AND status = 'pending' ORDER BY id ASC",
        (date,),
    ).fetchall()
    conn.close()
    for row in rows:
        if slots_equal(row["slot_time"], slot_time):
            return row
    return None


def mark_waitlist_notified(waitlist_id: int):
    """Mark a waitlist entry as notified."""
    conn = get_db_connection()
    try:
        conn.execute("UPDATE waitlist SET status = 'notified' WHERE id = ?", (waitlist_id,))
        conn.commit()
    finally:
        conn.close()


def get_user_waitlist(phone: str):
    """Fetch active waitlist entries for a user."""
    conn = get_db_connection()
    entries = conn.execute(
        "SELECT * FROM waitlist WHERE phone = ? AND status = 'pending' ORDER BY date ASC",
        (phone,),
    ).fetchall()
    conn.close()
    return entries

def get_waitlist_entries(date=None, status=None):
    """Fetch waitlist entries, optionally filtered by date and status."""
    conn = get_db_connection()
    try:
        clauses = []
        params = []
        if date:
            clauses.append("date = ?")
            params.append(date)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = conn.execute(
            f"SELECT * FROM waitlist {where_sql} ORDER BY created_at ASC",
            params,
        ).fetchall()
        return rows
    finally:
        conn.close()


def get_waitlist_entry(waitlist_id: int):
    """Fetch a single waitlist entry by ID."""
    conn = get_db_connection()
    row = conn.execute(
        "SELECT * FROM waitlist WHERE id = ?",
        (waitlist_id,),
    ).fetchone()
    conn.close()
    return row


def update_waitlist_status(waitlist_id: int, new_status: str):
    """Update waitlist entry status."""
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE waitlist SET status = ? WHERE id = ?",
            (new_status, waitlist_id),
        )
        conn.commit()
    finally:
        conn.close()


#
# Admin helpers
#

def get_all_bookings():
    conn = get_db_connection()
    bookings = conn.execute(
        """
        SELECT b.*, 
               CASE 
                 WHEN c.last_message_timestamp IS NOT NULL AND 
                      (julianday('now') - julianday(c.last_message_timestamp)) <= 1.0 
                 THEN 1 ELSE 0 
               END as is_messageable
        FROM bookings b
        LEFT JOIN customers c ON b.phone = c.phone
        ORDER BY b.date DESC, b.slot_time DESC
        """
    ).fetchall()
    conn.close()
    return bookings

def get_recent_bookings(limit=5):
    conn = get_db_connection()
    bookings = conn.execute(
        """
        SELECT b.*, 
               CASE 
                 WHEN c.last_message_timestamp IS NOT NULL AND 
                      (julianday('now') - julianday(c.last_message_timestamp)) <= 1.0 
                 THEN 1 ELSE 0 
               END as is_messageable
        FROM bookings b
        LEFT JOIN customers c ON b.phone = c.phone
        ORDER BY b.id DESC LIMIT ?
        """, (limit,)
    ).fetchall()
    conn.close()
    return bookings


def get_customer_summaries():
    """Return customer summary data derived from bookings."""
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT phone, name, date, seats, combo_group, status
        FROM bookings
        WHERE phone IS NOT NULL AND phone != '' AND phone NOT LIKE 'walkin:%'
        """
    ).fetchall()

    by_phone = {}
    for r in rows:
        phone = r["phone"]
        if phone not in by_phone:
            by_phone[phone] = []
        by_phone[phone].append(r)

    summaries = []
    for phone, bookings in by_phone.items():
        active_rows = [b for b in bookings if normalize_booking_status(b["status"]) not in ("cancelled", "No-show")]
        booking_count, total_guests = _aggregate_booking_rows(active_rows, conn)

        last_visit = None
        for b in active_rows:
            if not last_visit or b["date"] > last_visit:
                last_visit = b["date"]

        avg_party = round(total_guests / booking_count, 1) if booking_count else 0
        name = bookings[0]["name"] if bookings else ""
        summaries.append({
            "name": name,
            "phone": phone,
            "visit_count": booking_count,
            "last_visit": last_visit or "-",
            "avg_party_size": avg_party,
            "notes": "",
        })

    summaries.sort(key=lambda x: x["name"])
    conn.close()
    return summaries


def get_booking_by_id_only(booking_id: int):
    conn = get_db_connection()
    booking = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    conn.close()
    return booking


def get_all_slots():
    from utils import get_cafe_date
    conn = get_db_connection()
    try:
        today_str = str(get_cafe_date())
        conn.execute("DELETE FROM time_slots WHERE date < ?", (today_str,))
        conn.execute("DELETE FROM waitlist WHERE date < ?", (today_str,))
        conn.commit()
    except Exception as e:
        print(f"Error auto-clearing old data: {e}")
        
    slots = conn.execute("SELECT * FROM time_slots ORDER BY date ASC, slot_time ASC").fetchall()
    conn.close()
    return slots


#
# Auto Slot Generation
#

import os

# Default cafe slot schedule — edit via the admin panel "Edit Schedule" modal.
# Format: "H:MM AM - H:MM AM"  (used for both display and booking matching)
DEFAULT_SLOT_SCHEDULE = [
    "10:00 AM - 11:00 AM",
    "11:00 AM - 12:00 PM",
    "12:00 PM - 1:00 PM",
    "1:00 PM - 2:00 PM",
    "4:00 PM - 5:00 PM",
    "5:00 PM - 6:00 PM",
    "6:00 PM - 7:00 PM",
    "7:00 PM - 8:00 PM",
]
DEFAULT_SLOT_CAPACITY = 30   # max guests per slot
DEFAULT_GENERATE_DAYS = 7    # how many days ahead to pre-generate

_SLOT_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "slot_config.json")


def load_slot_config() -> dict:
    """
    Load slot schedule config from slot_config.json.
    Falls back to DEFAULT_* constants if the file is missing or invalid.
    """
    if os.path.exists(_SLOT_CONFIG_PATH):
        try:
            with open(_SLOT_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            schedule = cfg.get("schedule", DEFAULT_SLOT_SCHEDULE)
            capacity = int(cfg.get("capacity", DEFAULT_SLOT_CAPACITY))
            days = int(cfg.get("days_ahead", DEFAULT_GENERATE_DAYS))
            return {"schedule": schedule, "capacity": capacity, "days_ahead": days}
        except Exception as e:
            print(f"[load_slot_config] Could not read slot_config.json: {e}")
    return {
        "schedule": DEFAULT_SLOT_SCHEDULE,
        "capacity": DEFAULT_SLOT_CAPACITY,
        "days_ahead": DEFAULT_GENERATE_DAYS,
    }


def save_slot_config(schedule: list, capacity: int, days_ahead: int) -> None:
    """Persist an updated slot config to slot_config.json."""
    cfg = {"schedule": schedule, "capacity": capacity, "days_ahead": days_ahead}
    with open(_SLOT_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def auto_generate_slots(days_ahead=None):
    """
    Automatically create time_slot rows for the next `days_ahead` days
    (including today) based on the saved schedule config.
    Already-existing slots are skipped — no duplicates are created.
    Returns the number of new slots inserted.
    """
    from utils import get_cafe_date
    cfg = load_slot_config()
    schedule = cfg["schedule"]
    capacity = cfg["capacity"]
    if days_ahead is None:
        days_ahead = cfg["days_ahead"]

    today = get_cafe_date()
    conn = get_db_connection()
    inserted = 0
    try:
        for delta in range(days_ahead):
            target_date = (today + timedelta(days=delta)).isoformat()
            existing_rows = conn.execute(
                "SELECT slot_time FROM time_slots WHERE date = ?", (target_date,)
            ).fetchall()
            existing_times = {r["slot_time"] for r in existing_rows}

            for slot_time in schedule:
                normalized = _normalize_slot_value(slot_time)
                # Skip if an equivalent slot already exists
                if any(slots_equal(normalized, ex) for ex in existing_times):
                    continue
                conn.execute(
                    """
                    INSERT INTO time_slots (date, slot_time, total_capacity, available_seats, max_guests)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (target_date, normalized, capacity, capacity, capacity),
                )
                existing_times.add(normalized)
                inserted += 1

        conn.commit()
    except Exception as exc:
        conn.rollback()
        print(f"[auto_generate_slots] error: {exc}")
    finally:
        conn.close()
    return inserted


def add_time_slot(date, slot_time, capacity, max_guests=30):
    conn = get_db_connection()
    try:
        slot_time = _normalize_slot_value(slot_time)
        existing_rows = conn.execute(
            "SELECT slot_time FROM time_slots WHERE date = ?",
            (date,),
        ).fetchall()
        if any(slots_equal(row["slot_time"], slot_time) for row in existing_rows):
            return False, "Time slot already exists for that time and date."

        conn.execute(
            """
            INSERT INTO time_slots (date, slot_time, total_capacity, available_seats, max_guests)
            VALUES (?, ?, ?, ?, ?)
            """,
            (date, slot_time, capacity, capacity, max_guests),
        )
        conn.commit()
        return True, "Success"
    finally:
        conn.close()


def delete_time_slot(slot_id):
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM time_slots WHERE id = ?", (slot_id,))
        conn.commit()
        print(f"[AUDIT] Deleted time_slot id={slot_id}")
    finally:
        conn.close()


def delete_slots_for_date(target_date: str) -> int:
    """Delete all time slots for a specific date. Returns count removed."""
    conn = get_db_connection()
    try:
        cur = conn.execute("DELETE FROM time_slots WHERE date = ?", (target_date,))
        conn.commit()
        count = cur.rowcount
        print(f"[AUDIT] Deleted {count} slot(s) for date={target_date}")
        return count
    finally:
        conn.close()


def clear_all_future_slots() -> int:
    """Delete all future (>= today) time slots. Returns count removed."""
    from utils import get_cafe_date
    today_str = str(get_cafe_date())
    conn = get_db_connection()
    try:
        cur = conn.execute("DELETE FROM time_slots WHERE date >= ?", (today_str,))
        conn.commit()
        count = cur.rowcount
        print(f"[AUDIT] Cleared {count} future slot(s) from date={today_str}")
        return count
    finally:
        conn.close()


def update_slot_capacity(slot_id: int, new_capacity: int) -> bool:
    """Update max_guests and total_capacity for a specific slot."""
    conn = get_db_connection()
    try:
        cur = conn.execute(
            "UPDATE time_slots SET max_guests = ?, total_capacity = ? WHERE id = ?",
            (new_capacity, new_capacity, slot_id),
        )
        conn.commit()
        updated = cur.rowcount > 0
        if updated:
            print(f"[AUDIT] Updated slot id={slot_id} capacity to {new_capacity}")
        return updated
    finally:
        conn.close()


def get_slot_booking_stats() -> list:
    """
    Return booking fill statistics per slot_time label across all future slots.
    Each entry: {slot_time, total_slots, total_capacity, total_booked, fill_pct}
    """
    from utils import get_cafe_date
    today_str = str(get_cafe_date())
    conn = get_db_connection()
    try:
        statuses, placeholders = _active_status_params()
        # Get future slots aggregated by slot_time label
        slot_rows = conn.execute(
            """
            SELECT slot_time,
                   COUNT(*) as total_slots,
                   SUM(COALESCE(max_guests, total_capacity, 30)) as total_capacity
            FROM time_slots
            WHERE date >= ?
            GROUP BY slot_time
            ORDER BY slot_time ASC
            """,
            (today_str,),
        ).fetchall()

        booking_rows = conn.execute(
            f"""
            SELECT slot_time, SUM(seats) as booked
            FROM bookings
            WHERE date >= ? AND status IN ({placeholders})
            GROUP BY slot_time
            """,
            (today_str, *statuses),
        ).fetchall()

        booked_map = {r["slot_time"]: int(r["booked"] or 0) for r in booking_rows}

        result = []
        for s in slot_rows:
            label = s["slot_time"]
            cap = int(s["total_capacity"] or 0)
            booked = sum(v for k, v in booked_map.items() if slots_equal(k, label))
            pct = round((booked / cap * 100), 1) if cap > 0 else 0.0
            result.append({
                "slot_time": label,
                "total_slots": s["total_slots"],
                "total_capacity": cap,
                "total_booked": booked,
                "fill_pct": pct,
            })
        return result
    finally:
        conn.close()


def get_slots_with_bookings() -> list:
    """
    Return all future slots with their current booked guest counts.
    Each dict: slot row fields + booked_guests + fill_pct
    """
    from utils import get_cafe_date
    today_str = str(get_cafe_date())
    conn = get_db_connection()
    try:
        statuses, placeholders = _active_status_params()
        slots = conn.execute(
            "SELECT * FROM time_slots WHERE date >= ? ORDER BY date ASC, slot_time ASC",
            (today_str,),
        ).fetchall()

        bookings = conn.execute(
            f"""
            SELECT date, slot_time, SUM(seats) as booked
            FROM bookings
            WHERE date >= ? AND status IN ({placeholders})
            GROUP BY date, slot_time
            """,
            (today_str, *statuses),
        ).fetchall()

        booked_map = {}
        for b in bookings:
            booked_map[(b["date"], b["slot_time"])] = int(b["booked"] or 0)

        result = []
        for slot in slots:
            s = dict(slot)
            cap = int(s.get("max_guests") or s.get("total_capacity") or 30)
            booked = 0
            for (bd, bt), bv in booked_map.items():
                if bd == s["date"] and slots_equal(bt, s["slot_time"]):
                    booked = bv
                    break
            s["booked_guests"] = booked
            s["max_cap"] = cap
            s["fill_pct"] = round((booked / cap * 100), 1) if cap > 0 else 0.0
            result.append(s)
        return result
    finally:
        conn.close()


def admin_cancel_booking(booking_id: int):
    """Admin soft-cancels a booking by ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        statuses, placeholders = _active_status_params()
        booking = cursor.execute(
            f"SELECT * FROM bookings WHERE id = ? AND status IN ({placeholders})",
            (booking_id, *statuses),
        ).fetchone()
        if not booking:
            return False, "Booking not found or already cancelled."

        # Cancel the booking and any combo-linked bookings
        combo_group = booking["combo_group"]
        if combo_group:
            cursor.execute(
                "UPDATE bookings SET status = 'cancelled' WHERE combo_group = ?",
                (combo_group,),
            )
            cursor.execute(
                "UPDATE tables SET status = 'Vacant' WHERE table_number IN (SELECT table_number FROM bookings WHERE combo_group = ? AND table_number IS NOT NULL)",
                (combo_group,)
            )
        else:
            cursor.execute(
                "UPDATE bookings SET status = 'cancelled' WHERE id = ?",
                (booking_id,),
            )
            if booking["table_number"]:
                cursor.execute(
                    "UPDATE tables SET status = 'Vacant' WHERE table_number = ?",
                    (booking["table_number"],)
                )

        conn.commit()

        # Auto-allocate waitlisted user
        _auto_allocate_waitlist(booking["date"], booking["slot_time"])

        return True, "Booking cancelled successfully."
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def get_dashboard_metrics(today_date: str):
    """Fetch total tables, today's bookings, available tables, and today's guests."""
    conn = get_db_connection()
    statuses, placeholders = _active_status_params()

    total_tables = conn.execute("SELECT COUNT(*) as cnt FROM tables").fetchone()["cnt"]

    booking_rows = conn.execute(
        f"SELECT seats, combo_group FROM bookings WHERE date = ? AND status IN ({placeholders})",
        (today_date, *statuses),
    ).fetchall()
    todays_bookings, todays_guests = _aggregate_booking_rows(booking_rows, conn)

    available_tables = conn.execute(
        f"""
        SELECT COUNT(*) as cnt FROM tables
        WHERE table_number NOT IN (
            SELECT table_number FROM bookings
            WHERE date = ? AND status IN ({placeholders}) AND table_number IS NOT NULL
        )
        """,
        (today_date, *statuses),
    ).fetchone()["cnt"]

    # Waitlist count
    waitlist_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM waitlist WHERE date = ? AND status = 'pending'",
        (today_date,),
    ).fetchone()["cnt"]

    revenue_today = conn.execute(
        """
        SELECT COUNT(*) * 100 as total FROM bookings
        WHERE date = ?
        AND status IN ('Completed', 'Arrived', 'Confirmed')
        AND phone NOT LIKE 'walkin:%'
        """,
        (today_date,),
    ).fetchone()["total"] or 0

    conn.close()
    return {
        "total_tables": total_tables,
        "todays_bookings": todays_bookings,
        "available_tables": available_tables,
        "todays_guests": todays_guests,
        "waitlist_count": waitlist_count,
        "revenue_today": revenue_today,
    }


#
# Dashboard Chart Data

def get_bookings_by_slot_today(today_date: str):
    """Group today's active bookings by slot time for chart display."""
    conn = get_db_connection()
    statuses, placeholders = _active_status_params()
    rows = conn.execute(
        f"""
        SELECT slot_time, seats, combo_group
        FROM bookings
        WHERE date = ? AND status IN ({placeholders})
        """,
        (today_date, *statuses),
    ).fetchall()
    slot_map = {}
    for r in rows:
        label = normalize_slot_label(r["slot_time"]) or r["slot_time"]
        slot_map.setdefault(label, []).append(r)
    result = []
    for label, slot_rows in slot_map.items():
        count, guests = _aggregate_booking_rows(slot_rows, conn)
        result.append({"slot_time": label, "count": count, "guests": guests})
    conn.close()
    if not result:
        return []
    order = sort_slot_labels([r["slot_time"] for r in result])
    ordered = {label: i for i, label in enumerate(order)}
    result.sort(key=lambda r: ordered.get(r["slot_time"], len(order)))
    return result


def get_weekly_booking_trend():
    """Get booking counts for the last 7 days."""
    conn = get_db_connection()
    today = date.today()
    statuses, placeholders = _active_status_params()
    results = []
    for i in range(6, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        rows = conn.execute(
            f"SELECT seats, combo_group FROM bookings WHERE date = ? AND status IN ({placeholders})",
            (d, *statuses),
        ).fetchall()
        count, _ = _aggregate_booking_rows(rows, conn)
        results.append({"date": d, "count": count})
    conn.close()
    return results


#
# Reports
#

def get_report_data(start_date: str, end_date: str):
    """Generate reporting metrics for a date range."""
    conn = get_db_connection()

    rows = conn.execute(
        """
        SELECT date, status, seats, combo_group, slot_time, table_number
        FROM bookings
        WHERE date BETWEEN ? AND ?
        """,
        (start_date, end_date),
    ).fetchall()

    total_bookings, _ = _aggregate_booking_rows(rows, conn)

    cancelled_rows = [r for r in rows if (r["status"] == "cancelled")]
    total_cancelled, _ = _aggregate_booking_rows(cancelled_rows, conn)

    # Cancellation rate
    cancel_rate = round((total_cancelled / total_bookings * 100), 1) if total_bookings > 0 else 0

    # Most used tables
    most_used_tables = conn.execute(
        """
        SELECT table_number, COUNT(*) as usage_count
        FROM bookings
        WHERE date BETWEEN ? AND ? AND status IN ('Pending', 'Confirmed', 'Arrived', 'Completed') AND table_number IS NOT NULL
        GROUP BY table_number
        ORDER BY usage_count DESC
        LIMIT 5
        """,
        (start_date, end_date),
    ).fetchall()

    active_statuses = ("Pending", "Confirmed", "Arrived", "Completed")
    active_rows = [r for r in rows if r["status"] in active_statuses]
    slot_map = {}
    for r in active_rows:
        label = normalize_slot_label(r["slot_time"]) or r["slot_time"]
        slot_map.setdefault(label, []).append(r)
    peak_slots = []
    for label, slot_rows in slot_map.items():
        count, _ = _aggregate_booking_rows(slot_rows, conn)
        peak_slots.append({"slot_time": label, "count": count})
    peak_slots.sort(key=lambda x: x["count"], reverse=True)
    peak_slots = peak_slots[:5]

    # Daily breakdown
    daily_stats = []
    rows_by_date = {}
    for r in rows:
        rows_by_date.setdefault(r["date"], []).append(r)
    for d in sorted(rows_by_date.keys()):
        day_rows = rows_by_date[d]
        total_count, _ = _aggregate_booking_rows(day_rows, conn)
        day_active = [r for r in day_rows if r["status"] in active_statuses]
        active_count, _ = _aggregate_booking_rows(day_active, conn)
        day_cancelled = [r for r in day_rows if r["status"] == "cancelled"]
        cancelled_count, _ = _aggregate_booking_rows(day_cancelled, conn)
        daily_stats.append({"date": d, "total": total_count, "active": active_count, "cancelled": cancelled_count})

    # Total guests
    _, total_guests = _aggregate_booking_rows(active_rows, conn)

    conn.close()

    return {
        "total_bookings": total_bookings,
        "total_cancelled": total_cancelled,
        "cancel_rate": cancel_rate,
        "total_guests": total_guests,
        "most_used_tables": [{"table_number": r["table_number"], "count": r["usage_count"]} for r in most_used_tables],
        "peak_slots": peak_slots,
        "daily_stats": daily_stats,
    }
#
# Staff / Additional status helpers
#

def update_booking_status(booking_id: int, new_status: str):
    conn = get_db_connection()
    try:
        normalized = normalize_booking_status(new_status) or new_status
        cancel_release_for_table = None
        schedule_release_for_table = None
        booking = conn.execute(
            "SELECT table_number, date, slot_time, status, seated_at FROM bookings WHERE id = ?",
            (booking_id,),
        ).fetchone()
        if not booking:
            return False

        update_clauses = ["status = ?"]
        update_params = [normalized]
        if normalized == "Arrived" and _has_column(conn, "bookings", "seated_at") and not booking.get("seated_at"):
            update_clauses.append("seated_at = ?")
            update_params.append(_now_cafe_iso())
        if _has_column(conn, "bookings", "updated_at"):
            update_clauses.append("updated_at = CURRENT_TIMESTAMP")
        update_params.append(booking_id)
        conn.execute(
            f"UPDATE bookings SET {', '.join(update_clauses)} WHERE id = ?",
            update_params,
        )
        
        if booking and booking["table_number"]:
            table_row = conn.execute("SELECT id FROM tables WHERE table_number = ?", (booking["table_number"],)).fetchone()
            if table_row:
                table_id = table_row["id"]
                if normalized == 'Arrived':
                    conn.execute("UPDATE tables SET status = 'Occupied' WHERE id = ?", (table_id,))
                    cancel_release_for_table = booking["table_number"]
                elif normalized == 'Completed':
                    conn.execute("UPDATE tables SET status = 'Needs Cleaning' WHERE id = ?", (table_id,))
                    schedule_release_for_table = booking["table_number"]
                elif normalized in ['cancelled', 'No-show']:
                    conn.execute("UPDATE tables SET status = 'Vacant' WHERE id = ?", (table_id,))
                    cancel_release_for_table = booking["table_number"]
                    
        conn.commit()
        if cancel_release_for_table is not None:
            _cancel_scheduled_table_release(cancel_release_for_table)
        if schedule_release_for_table is not None:
            _schedule_table_release(schedule_release_for_table, delay_seconds=300)
        
        if normalized in ['cancelled', 'No-show'] and booking:
            _auto_allocate_waitlist(booking["date"], booking["slot_time"])
            
        return True
    except Exception as e:
        print(f"Error updating booking status: {e}")
        return False
    finally:
        conn.close()

def update_table_status(table_number: int, new_status: str):
    conn = get_db_connection()
    try:
        normalized = str(new_status or "").strip()
        conn.execute("UPDATE tables SET status = ? WHERE table_number = ?", (new_status, table_number))
        conn.commit()
        if normalized == "Vacant":
            _cancel_scheduled_table_release(table_number)
        elif normalized in ("Occupied", "Blocked", "Reserved", "Reserved (Impending)"):
            _cancel_scheduled_table_release(table_number)
        return True
    except Exception as e:
        print(f"Error updating table status: {e}")
        return False
    finally:
        conn.close()

def get_all_users():
    conn = get_db_connection()
    users = conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
    conn.close()
    return users

def get_today_bookings(today_date: str):
    conn = get_db_connection()
    bookings = conn.execute(
        """
        SELECT b.*, 
               CASE 
                 WHEN c.last_message_timestamp IS NOT NULL AND 
                      (julianday('now') - julianday(c.last_message_timestamp)) <= 1.0 
                 THEN 1 ELSE 0 
               END as is_messageable
        FROM bookings b
        LEFT JOIN customers c ON b.phone = c.phone
        WHERE b.date = ? ORDER BY b.slot_time ASC
        """,
        (today_date,)
    ).fetchall()
    conn.close()
    return bookings
