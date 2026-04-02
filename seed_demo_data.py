"""
seed_demo_data.py
=================
Inserts realistic demo customer data into cafebot.db for demo purposes.
Run ONCE after init_db.py (and all migrations) have been applied.

Safe to run multiple times — existing bookings for demo phones are skipped.

Usage:
    python seed_demo_data.py
"""

import sqlite3
import os
from datetime import date, timedelta

DATABASE = "cafebot.db"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_conn():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def has_column(conn, table, column):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)


def has_table(conn, table):
    r = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?", (table,)
    ).fetchone()
    return r is not None


def today_plus(n):
    return str(date.today() + timedelta(days=n))


def today_minus(n):
    return str(date.today() - timedelta(days=n))


NOW_ISO = "2026-04-01 08:00:00"

# ---------------------------------------------------------------------------
# Demo data
# ---------------------------------------------------------------------------

# 10 realistic Indian customer profiles
CUSTOMERS = [
    {"phone": "+919876543210", "name": "Arjun Mehta"},
    {"phone": "+919812345678", "name": "Priya Sharma"},
    {"phone": "+919823456789", "name": "Rahul Verma"},
    {"phone": "+919834567890", "name": "Sneha Patel"},
    {"phone": "+919845678901", "name": "Vikram Nair"},
    {"phone": "+919856789012", "name": "Kavya Reddy"},
    {"phone": "+919867890123", "name": "Amit Joshi"},
    {"phone": "+919878901234", "name": "Divya Menon"},
    {"phone": "+919889012345", "name": "Suresh Gupta"},
    {"phone": "+919890123456", "name": "Ananya Singh"},
]

# Slot labels must match what is already in time_slots (or use a past-date booking freely)
SLOTS = [
    "10:00 AM - 11:00 AM",
    "11:15 AM - 12:15 PM",
    "4:00 PM - 5:00 PM",
    "7:00 PM - 8:00 PM",
    "1:00 PM - 2:00 PM",
    "6:00 PM - 7:00 PM",
]

# Tables available: 1-6 (capacities 2,2,4,4,6,8)
# Bookings: (customer_index, date_offset_days_ago, slot_index, seats, table_number, status)
# Negative offset = past date. Positive = upcoming.
BOOKING_SPECS = [
    # Arjun Mehta — 3 past visits + 1 upcoming
    (0, -14, 0, 2, 1, "Completed"),
    (0, -7,  1, 2, 2, "Completed"),
    (0, -2,  3, 2, 1, "Completed"),
    (0,  2,  2, 2, 2, "Confirmed"),

    # Priya Sharma — 2 past visits, 1 upcoming
    (1, -10, 2, 4, 3, "Completed"),
    (1, -3,  4, 4, 4, "Completed"),
    (1,  1,  0, 4, 3, "Confirmed"),

    # Rahul Verma — 2 past visits
    (2, -21, 5, 2, 1, "Completed"),
    (2, -5,  1, 2, 2, "Completed"),

    # Sneha Patel — 1 past visit, 1 upcoming
    (3, -6,  3, 6, 5, "Completed"),
    (3,  3,  4, 6, 5, "Confirmed"),

    # Vikram Nair — 2 past visits
    (4, -9,  0, 4, 3, "Completed"),
    (4, -4,  2, 4, 4, "Completed"),

    # Kavya Reddy — 1 past + 1 upcoming
    (5, -15, 4, 2, 2, "Completed"),
    (5,  1,  5, 2, 1, "Confirmed"),

    # Amit Joshi — 1 past cancelled, 1 past completed
    (6, -8,  0, 2, 1, "Cancelled"),
    (6, -3,  1, 2, 2, "Completed"),

    # Divya Menon — group of 8 (2 past visits)
    (7, -12, 5, 8, 6, "Completed"),
    (7, -6,  3, 8, 6, "Completed"),

    # Suresh Gupta — walk-in style (no-show once, completed once)
    (8, -20, 0, 4, 3, "No-show"),
    (8, -2,  2, 4, 4, "Completed"),

    # Ananya Singh — fresh customer, 1 upcoming booking
    (9,  2,  0, 2, 1, "Confirmed"),
]

# ---------------------------------------------------------------------------
# Time slot seeding for past and future dates
# ---------------------------------------------------------------------------

SLOT_LABELS_TO_SEED = [
    ("10:00 AM - 11:00 AM", 30, 30, 30),
    ("11:15 AM - 12:15 PM", 30, 30, 30),
    ("1:00 PM - 2:00 PM",   30, 30, 30),
    ("4:00 PM - 5:00 PM",   30, 30, 30),
    ("6:00 PM - 7:00 PM",   30, 30, 30),
    ("7:00 PM - 8:00 PM",   30, 30, 30),
]


def ensure_time_slot(conn, date_str, slot_time, total_capacity, available_seats, max_guests):
    """Insert a time slot row only if it doesn't already exist for that date+slot."""
    existing = conn.execute(
        "SELECT id FROM time_slots WHERE date = ? AND slot_time = ?",
        (date_str, slot_time),
    ).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO time_slots (date, slot_time, total_capacity, available_seats, max_guests) VALUES (?, ?, ?, ?, ?)",
            (date_str, slot_time, total_capacity, available_seats, max_guests),
        )


def seed_slots(conn):
    """Ensure time slot rows exist for all dates referenced in our bookings."""
    needed_dates = set()
    for spec in BOOKING_SPECS:
        _, offset, slot_idx, _, _, _ = spec
        d = today_plus(offset) if offset >= 0 else today_minus(-offset)
        needed_dates.add(d)

    for d in needed_dates:
        for slot_time, total_cap, avail, max_g in SLOT_LABELS_TO_SEED:
            ensure_time_slot(conn, d, slot_time, total_cap, avail, max_g)

    conn.commit()
    print(f"  ✅ Time slots ensured for {len(needed_dates)} dates.")


# ---------------------------------------------------------------------------
# Main seeding logic
# ---------------------------------------------------------------------------

def seed_bookings(conn):
    """Insert demo bookings, skipping any that already exist for the same phone+date+slot."""
    inserted = 0
    skipped = 0

    for spec in BOOKING_SPECS:
        cust_idx, offset, slot_idx, seats, table_num, status = spec
        customer = CUSTOMERS[cust_idx]
        phone = customer["phone"]
        name = customer["name"]
        slot_time = SLOTS[slot_idx]
        d = today_plus(offset) if offset >= 0 else today_minus(-offset)

        # Check for duplicate
        existing = conn.execute(
            "SELECT id FROM bookings WHERE phone = ? AND date = ? AND slot_time = ?",
            (phone, d, slot_time),
        ).fetchone()
        if existing:
            skipped += 1
            continue

        # Build insert dynamically based on existing columns
        columns = ["phone", "name", "date", "slot_time", "seats", "table_number", "status"]
        values  = [phone, name, d, slot_time, seats, table_num, status]

        if has_column(conn, "bookings", "is_auto_allocated"):
            columns.append("is_auto_allocated")
            values.append(0)

        if has_column(conn, "bookings", "reminder_sent"):
            columns.append("reminder_sent")
            values.append(1)

        if has_column(conn, "bookings", "created_at"):
            columns.append("created_at")
            values.append(NOW_ISO)

        if has_column(conn, "bookings", "updated_at"):
            columns.append("updated_at")
            values.append(NOW_ISO)

        if has_column(conn, "bookings", "seated_at") and status == "Arrived":
            columns.append("seated_at")
            values.append(NOW_ISO)

        placeholders = ", ".join("?" * len(columns))
        conn.execute(
            f"INSERT INTO bookings ({', '.join(columns)}) VALUES ({placeholders})",
            values,
        )
        inserted += 1

    conn.commit()
    print(f"  ✅ Bookings: {inserted} inserted, {skipped} skipped (already existed).")
    return inserted


def seed_customers_table(conn):
    """Optionally populate the customers session table for messageability checks."""
    if not has_table(conn, "customers"):
        print("  ⚠️  customers table not found — skipping.")
        return

    from datetime import datetime
    now_str = datetime.now().isoformat()
    inserted = 0
    for c in CUSTOMERS:
        existing = conn.execute(
            "SELECT phone FROM customers WHERE phone = ?", (c["phone"],)
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO customers (phone, last_message_timestamp) VALUES (?, ?)",
                (c["phone"], now_str),
            )
            inserted += 1
    conn.commit()
    print(f"  ✅ Customers session rows: {inserted} inserted.")


def main():
    if not os.path.exists(DATABASE):
        print(f"❌ {DATABASE} not found. Run init_db.py first.")
        return

    print(f"\n🌱 Seeding demo data into {DATABASE} …\n")

    conn = get_conn()
    try:
        print("→ Ensuring time slots for demo dates …")
        seed_slots(conn)

        print("→ Inserting demo bookings …")
        seed_bookings(conn)

        print("→ Seeding customer session rows …")
        seed_customers_table(conn)
    finally:
        conn.close()

    print("\n✅ Done! The demo database is ready.\n")
    print("   Customers seeded:")
    for c in CUSTOMERS:
        print(f"   • {c['name']} ({c['phone']})")


if __name__ == "__main__":
    main()
