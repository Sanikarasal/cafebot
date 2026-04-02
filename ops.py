from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for

from auth import staff_required, admin_required
from utils import (
    get_cafe_date,
    get_cafe_time,
    normalize_booking_status,
    normalize_slot_label,
    parse_slot_time,
    get_active_booking_statuses,
)
import db


ops_bp = Blueprint('ops', __name__)


# Helper utilities for formatting and floor/dashboard data preparation.
def _format_time(dt_value):
    if not dt_value:
        return ""
    if isinstance(dt_value, str):
        try:
            dt_value = datetime.strptime(dt_value, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return ""
    return dt_value.strftime("%I:%M %p").lstrip("0")


def _parse_iso(dt_value):
    return db.parse_booking_datetime(dt_value)


def _build_table_cards(tables, bookings, now):
    active_statuses = get_active_booking_statuses()
    combo_groups = [b["combo_group"] for b in bookings if b.get("combo_group")]
    combo_totals = db.get_combo_group_totals(combo_groups) if combo_groups else {}

    bookings_by_table = {}
    for b in bookings:
        if b.get("table_number") is None:
            continue
        b_status = normalize_booking_status(b.get("status")) or b.get("status")
        b["status"] = b_status
        b["slot_time"] = normalize_slot_label(b.get("slot_time")) or b.get("slot_time")
        bookings_by_table.setdefault(b["table_number"], []).append(b)

    cards = []
    for t in tables:
        t_dict = dict(t)
        table_number = t_dict.get("table_number")
        table_bookings = bookings_by_table.get(table_number, [])

        current_booking = None
        next_booking = None
        latest_started = None

        for b in table_bookings:
            if b.get("status") not in active_statuses:
                continue
            slot_start, slot_end = parse_slot_time(b.get("slot_time"), now.date())
            if b.get("status") == "Arrived":
                current_booking = b
                break
            if slot_start and slot_start <= now:
                if latest_started is None or slot_start > latest_started:
                    latest_started = slot_start
                    current_booking = b

        for b in table_bookings:
            if b.get("status") in ("Pending", "Confirmed"):
                slot_start, _ = parse_slot_time(b.get("slot_time"), now.date())
                if slot_start and slot_start > now:
                    if not next_booking or slot_start < next_booking["slot_start"]:
                        next_booking = {**b, "slot_start": slot_start}

        seats_value = ""
        guest_name = ""
        seated_since = ""
        booking_id = None
        booking_status = ""
        if current_booking:
            booking_id = current_booking.get("id")
            booking_status = current_booking.get("status")
            guest_name = current_booking.get("name") or ""
            seats_value = current_booking.get("seats") or ""
            if current_booking.get("combo_group") and current_booking["combo_group"] in combo_totals:
                seats_value = combo_totals[current_booking["combo_group"]]
            seated_since = _format_time(
                _parse_iso(
                    current_booking.get("seated_at")
                    or current_booking.get("updated_at")
                    or current_booking.get("created_at")
                )
            )

        next_reservation = ""
        if next_booking:
            next_reservation = _format_time(next_booking["slot_start"])

        cards.append({
            "table_number": table_number,
            "capacity": t_dict.get("capacity"),
            "status": t_dict.get("status") or "Vacant",
            "booking_id": booking_id,
            "booking_status": booking_status,
            "guest_name": guest_name,
            "guests": seats_value,
            "seated_since": seated_since,
            "next_reservation": next_reservation,
        })

    return cards


def _get_upcoming_reservations(bookings, now, window_minutes=120):
    upcoming = []
    combo_groups = [b["combo_group"] for b in bookings if b.get("combo_group")]
    combo_totals = db.get_combo_group_totals(combo_groups) if combo_groups else {}
    window_end = now + timedelta(minutes=window_minutes)

    for b in bookings:
        status = normalize_booking_status(b.get("status")) or b.get("status")
        if status not in ("Pending", "Confirmed"):
            continue
        slot_start, _ = parse_slot_time(b.get("slot_time"), now.date())
        if slot_start and now <= slot_start <= window_end:
            seats_value = b.get("seats") or ""
            if b.get("combo_group") and b["combo_group"] in combo_totals:
                seats_value = combo_totals[b["combo_group"]]
            upcoming.append({
                "id": b.get("id"),
                "time": _format_time(slot_start),
                "name": b.get("name"),
                "guests": seats_value,
                "table_number": b.get("table_number"),
                "status": status,
                "slot_start": slot_start,
            })

    upcoming.sort(key=lambda x: x["slot_start"])
    for item in upcoming:
        item.pop("slot_start", None)
    return upcoming


# Staff-facing page routes.
@ops_bp.route('/floor')
@staff_required
def floor():
    today_date = str(get_cafe_date())
    now = get_cafe_time().replace(tzinfo=None)

    tables = db.get_all_tables()
    bookings = [dict(b) for b in db.get_today_bookings(today_date)]
    waitlist_entries = [dict(w) for w in db.get_waitlist_entries(today_date, status="pending")]

    for w in waitlist_entries:
        created_at = _parse_iso(w.get("created_at"))
        if created_at:
            w["wait_minutes"] = int((now - created_at).total_seconds() / 60)
        else:
            w["wait_minutes"] = None

    table_cards = _build_table_cards(tables, bookings, now)
    upcoming = _get_upcoming_reservations(bookings, now)

    available_slots = db.get_available_slots(today_date, filter_past=True)
    slot_labels = [normalize_slot_label(s["slot_time"]) or s["slot_time"] for s in available_slots]
    all_slots = [s for s in db.get_all_slots() if s["date"] == today_date]
    waitlist_slot_labels = [normalize_slot_label(s["slot_time"]) or s["slot_time"] for s in all_slots]

    return render_template(
        'floor.html',
        tables=table_cards,
        upcoming=upcoming,
        waitlist=waitlist_entries,
        today_date=today_date,
        slot_labels=slot_labels,
        waitlist_slot_labels=waitlist_slot_labels,
    )


@ops_bp.route('/bookings')
@staff_required
def bookings_page():
    today_date = str(get_cafe_date())
    bookings = [dict(b) for b in db.get_all_bookings()]
    combo_groups = [b["combo_group"] for b in bookings if b.get("combo_group")]
    combo_totals = db.get_combo_group_totals(combo_groups) if combo_groups else {}

    for b in bookings:
        b["status"] = normalize_booking_status(b.get("status")) or b.get("status")
        b["slot_time"] = normalize_slot_label(b.get("slot_time")) or b.get("slot_time")
        if b.get("combo_group") and b["combo_group"] in combo_totals:
            b["seats_display"] = combo_totals[b["combo_group"]]
        else:
            b["seats_display"] = b.get("seats")

    return render_template('bookings_ops.html', bookings=bookings, today_date=today_date)


@ops_bp.route('/customers')
@staff_required
def customers_page():
    customers = db.get_customer_summaries()
    return render_template('customers.html', customers=customers)


@ops_bp.route('/waitlist')
@staff_required
def waitlist_page():
    today_date = str(get_cafe_date())
    waitlist_entries = [dict(w) for w in db.get_waitlist_entries(today_date, status="pending")]
    return render_template('waitlist_ops.html', waitlist=waitlist_entries, today_date=today_date)


# Admin table management page and form actions.
@ops_bp.route('/tables', methods=['GET', 'POST'])
@admin_required
def tables_page():
    if request.method == 'POST':
        action = request.form.get('action')
        table_number = request.form.get('table_number')
        table_name = request.form.get('table_name')
        capacity = request.form.get('capacity')
        location = request.form.get('location')
        merge_a = request.form.get('merge_table_a')
        merge_b = request.form.get('merge_table_b')

        if action == 'add':
            conn = db.get_db_connection()
            try:
                conn.execute(
                    "INSERT INTO tables (table_number, table_name, capacity, location) VALUES (?, ?, ?, ?)",
                    (table_number, table_name or f"Table {table_number}", capacity, location or ""),
                )
                conn.commit()
                flash("Table added.", "success")
            except Exception as exc:
                conn.rollback()
                flash(f"Add failed: {exc}", "danger")
            finally:
                conn.close()

        elif action == 'edit':
            conn = db.get_db_connection()
            try:
                conn.execute(
                    "UPDATE tables SET table_name = ?, capacity = ?, location = ? WHERE table_number = ?",
                    (table_name, capacity, location, table_number),
                )
                conn.commit()
                flash("Table updated.", "success")
            except Exception as exc:
                conn.rollback()
                flash(f"Update failed: {exc}", "danger")
            finally:
                conn.close()

        elif action == 'delete':
            conn = db.get_db_connection()
            try:
                conn.execute("DELETE FROM tables WHERE table_number = ?", (table_number,))
                conn.commit()
                flash("Table deleted.", "warning")
            except Exception as exc:
                conn.rollback()
                flash(f"Delete failed: {exc}", "danger")
            finally:
                conn.close()

        elif action == 'block':
            if table_number:
                db.update_table_status(int(table_number), "Blocked")
                flash("Table blocked.", "warning")

        elif action == 'unblock':
            if table_number:
                db.update_table_status(int(table_number), "Vacant")
                flash("Table unblocked.", "success")

        elif action == 'merge':
            if merge_a and merge_b:
                conn = db.get_db_connection()
                try:
                    a = conn.execute("SELECT * FROM tables WHERE table_number = ?", (merge_a,)).fetchone()
                    b = conn.execute("SELECT * FROM tables WHERE table_number = ?", (merge_b,)).fetchone()
                    if not a or not b:
                        flash("Merge failed: one of the tables was not found.", "danger")
                    else:
                        new_number = conn.execute("SELECT MAX(table_number) FROM tables").fetchone()[0] or 0
                        new_number = int(new_number) + 1
                        merged_capacity = int(a["capacity"]) + int(b["capacity"])
                        merged_name = f"Merged {a['table_number']}+{b['table_number']}"
                        merged_location = f"{a['location']} + {b['location']}"
                        conn.execute(
                            "INSERT INTO tables (table_number, table_name, capacity, location, status) VALUES (?, ?, ?, ?, 'Blocked')",
                            (new_number, merged_name, merged_capacity, merged_location),
                        )
                        conn.execute(
                            "UPDATE tables SET status = 'Blocked' WHERE table_number IN (?, ?)",
                            (merge_a, merge_b),
                        )
                        conn.commit()
                        flash(f"Merged tables into T{new_number}. Originals blocked.", "success")
                except Exception as exc:
                    conn.rollback()
                    flash(f"Merge failed: {exc}", "danger")
                finally:
                    conn.close()

        return redirect(url_for('ops.tables_page'))

    tables = db.get_all_tables()
    return render_template('tables_ops.html', tables=tables)


# Floor and booking actions exposed as JSON APIs.
@ops_bp.route('/api/table/status', methods=['POST'])
@staff_required
def api_table_status():
    payload = request.get_json(silent=True) or request.form
    table_number = payload.get('table_number')
    new_status = payload.get('status')
    if not table_number or not new_status:
        return jsonify({"ok": False, "error": "Missing table_number or status."}), 400
    success = db.update_table_status(int(table_number), new_status)
    return jsonify({"ok": success})


@ops_bp.route('/api/seat_guest', methods=['POST'])
@staff_required
def api_seat_guest():
    payload = request.get_json(silent=True) or request.form
    booking_id = payload.get('booking_id')
    table_number = payload.get('table_number')
    name = payload.get('name', 'Walk-In Guest')
    phone = payload.get('phone', 'walkin:staff')
    guests = payload.get('guests')
    date = payload.get('date') or str(get_cafe_date())
    slot_time = payload.get('slot_time')

    if booking_id:
        success = db.update_booking_status(int(booking_id), "Arrived")
        return jsonify({"ok": success})

    if not all([guests, slot_time]):
        return jsonify({"ok": False, "error": "Missing guests or slot_time."}), 400

    if not table_number:
        available = db.get_available_tables(date, slot_time, int(guests))
        if not available:
            return jsonify({"ok": False, "error": "No available tables for that slot."}), 400
        table_number = available[0]["table_number"]

    success, message, booking_id = db.atomic_quick_seat(
        phone=phone,
        name=name,
        date=date,
        slot_time=slot_time,
        seats=int(guests),
        table_number=int(table_number),
    )
    if not success:
        return jsonify({"ok": False, "error": message}), 400
    return jsonify({"ok": True, "booking_id": booking_id, "table_number": table_number})


@ops_bp.route('/api/table/suggest', methods=['POST'])
@staff_required
def api_table_suggest():
    payload = request.get_json(silent=True) or request.form
    date = payload.get('date') or str(get_cafe_date())
    slot_time = payload.get('slot_time')
    guests = payload.get('guests')
    if not slot_time or not guests:
        return jsonify({"ok": False, "error": "Missing slot_time or guests."}), 400
    available = db.get_available_tables(date, slot_time, int(guests))
    suggestions = [t["table_number"] for t in available]
    return jsonify({"ok": True, "tables": suggestions})


@ops_bp.route('/api/checkout', methods=['POST'])
@staff_required
def api_checkout():
    payload = request.get_json(silent=True) or request.form
    booking_id = payload.get('booking_id')
    if not booking_id:
        return jsonify({"ok": False, "error": "Missing booking_id."}), 400
    success = db.update_booking_status(int(booking_id), "Completed")
    return jsonify({"ok": success})


@ops_bp.route('/api/mark_clean', methods=['POST'])
@staff_required
def api_mark_clean():
    payload = request.get_json(silent=True) or request.form
    table_number = payload.get('table_number')
    if not table_number:
        return jsonify({"ok": False, "error": "Missing table_number."}), 400
    success = db.update_table_status(int(table_number), "Vacant")
    return jsonify({"ok": success})


@ops_bp.route('/api/waitlist/add', methods=['POST'])
@staff_required
def api_waitlist_add():
    payload = request.get_json(silent=True) or request.form
    name = payload.get('name')
    guests = payload.get('guests')
    phone = payload.get('phone', '').strip()
    date = payload.get('date') or str(get_cafe_date())
    slot_time = payload.get('slot_time')

    if not name or not guests or not slot_time:
        return jsonify({"ok": False, "error": "Missing name, guests, or slot_time."}), 400

    success, message = db.add_to_waitlist(phone or "walkin:waitlist", name, date, slot_time, int(guests))
    if not success:
        return jsonify({"ok": False, "error": message}), 400
    return jsonify({"ok": True})


@ops_bp.route('/api/waitlist/assign', methods=['POST'])
@staff_required
def api_waitlist_assign():
    payload = request.get_json(silent=True) or request.form
    waitlist_id = payload.get('waitlist_id')
    table_number = payload.get('table_number')

    if not waitlist_id or not table_number:
        return jsonify({"ok": False, "error": "Missing waitlist_id or table_number."}), 400

    entry = db.get_waitlist_entry(int(waitlist_id))
    if not entry:
        return jsonify({"ok": False, "error": "Waitlist entry not found."}), 404

    success, message, booking_id = db.atomic_quick_seat(
        phone=entry["phone"],
        name=entry["name"],
        date=entry["date"],
        slot_time=entry["slot_time"],
        seats=int(entry["guests"]),
        table_number=int(table_number),
    )
    if not success:
        return jsonify({"ok": False, "error": message}), 400

    db.update_waitlist_status(int(waitlist_id), "seated")
    return jsonify({"ok": True, "booking_id": booking_id})


@ops_bp.route('/api/booking/status', methods=['POST'])
@staff_required
def api_booking_status():
    payload = request.get_json(silent=True) or request.form
    booking_id = payload.get('booking_id')
    status = payload.get('status')
    if not booking_id or not status:
        return jsonify({"ok": False, "error": "Missing booking_id or status."}), 400

    normalized = normalize_booking_status(status) or status
    if normalized == "cancelled":
        success, message = db.admin_cancel_booking(int(booking_id))
        if not success:
            return jsonify({"ok": False, "error": message}), 400
        return jsonify({"ok": True})

    success = db.update_booking_status(int(booking_id), normalized)
    return jsonify({"ok": success})


@ops_bp.route('/api/booking/update', methods=['POST'])
@staff_required
def api_booking_update():
    payload = request.get_json(silent=True) or request.form
    booking_id = payload.get('booking_id')
    if not booking_id:
        return jsonify({"ok": False, "error": "Missing booking_id."}), 400

    booking = db.get_booking_by_id_only(int(booking_id))
    if not booking:
        return jsonify({"ok": False, "error": "Booking not found."}), 404

    new_date = payload.get('date') or booking["date"]
    new_slot = normalize_slot_label(payload.get('slot_time') or booking["slot_time"])
    new_seats = payload.get('seats') or booking["seats"]
    new_table = payload.get('table_number') or booking["table_number"]

    if new_table:
        try:
            new_table = int(new_table)
        except ValueError:
            return jsonify({"ok": False, "error": "Invalid table number."}), 400

    conn = db.get_db_connection()
    try:
        if new_table and (new_date != booking["date"] or new_slot != booking["slot_time"]):
            available = db.get_available_tables(new_date, new_slot, 1)
            available_numbers = {t["table_number"] for t in available}
            if new_table not in available_numbers and new_table != booking["table_number"]:
                return jsonify({"ok": False, "error": "Table not available for that slot."}), 400

        conn.execute(
            """
            UPDATE bookings
            SET date = ?, slot_time = ?, seats = ?, table_number = ?
            WHERE id = ?
            """,
            (new_date, new_slot, int(new_seats), new_table, booking_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify({"ok": True})
