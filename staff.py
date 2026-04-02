from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from datetime import timedelta
from utils import get_active_booking_statuses, normalize_booking_status, parse_slot_time, normalize_slot_label, slots_equal, sort_slot_labels
from auth import staff_required
import db

#
# Table turnover constants
#
WALKIN_LOCKOUT_MINS = 45   # Walk-in accepted if reservation is >45 min away
ARRIVED_ENABLE_MINS = 30   # "Arrived" button appears only when ≤30 min to slot

staff_bp = Blueprint('staff', __name__, url_prefix='/staff')


def _get_booking_start(booking, base_date):
    slot_label = normalize_slot_label(booking.get('slot_time')) if booking.get('slot_time') else ''
    start_dt, _ = parse_slot_time(slot_label, base_date)
    return start_dt, slot_label


def _build_next_booking(table_bookings, active_booking, now):
    current_start = None
    if active_booking:
        current_start, _ = _get_booking_start(active_booking, now.date())

    candidates = []
    for booking in table_bookings:
        status = normalize_booking_status(booking.get('status'))
        if status not in ('Pending', 'Confirmed'):
            continue
        if active_booking and booking.get('id') == active_booking.get('id'):
            continue

        start_dt, slot_label = _get_booking_start(booking, now.date())
        if not start_dt:
            continue
        if current_start:
            if start_dt <= current_start:
                continue
        elif start_dt <= now:
            continue

        candidates.append((start_dt, slot_label, booking))

    if not candidates:
        return None

    start_dt, slot_label, booking = min(candidates, key=lambda item: item[0])
    gap_minutes = max(int((start_dt - now).total_seconds() // 60), 0)
    if gap_minutes <= 0:
        gap_label = "Arriving now"
        badge_tone = "danger"
    elif gap_minutes <= 15:
        gap_label = f"Arriving in {gap_minutes}m"
        badge_tone = "danger"
    elif gap_minutes <= 30:
        gap_label = f"In {gap_minutes}m"
        badge_tone = "warning"
    else:
        gap_label = f"In {gap_minutes}m"
        badge_tone = "neutral"

    return {
        "name": booking.get("name"),
        "guests": booking.get("seats"),
        "slot_time": slot_label or booking.get("slot_time"),
        "gap_minutes": gap_minutes,
        "gap_label": gap_label,
        "badge_tone": badge_tone,
    }


@staff_bp.route('/action', methods=['POST'])
@staff_required
def action():
    from utils import get_cafe_time

    table_id = request.form.get('table_id')
    guests_raw = request.form.get('guests', '1')
    booking_id = None
    success = False
    message = 'Unable to seat walk-in.'

    try:
        guests = int(guests_raw)
    except (TypeError, ValueError):
        message = 'Guest count must be a whole number.'
        flash(message, 'danger')
        if request.headers.get('Accept') == 'application/json':
            return jsonify({'ok': False, 'message': message}), 400
        return redirect(url_for('staff.dashboard'))

    if not table_id:
        message = 'Table is required.'
        flash(message, 'danger')
        if request.headers.get('Accept') == 'application/json':
            return jsonify({'ok': False, 'message': message}), 400
        return redirect(url_for('staff.dashboard'))

    conn = db.get_db_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")

        table = conn.execute(
            "SELECT id, table_number, capacity, status FROM tables WHERE id = ?",
            (table_id,),
        ).fetchone()

        if not table:
            conn.rollback()
            message = 'Table not found.'
        elif guests < 1 or guests > int(table['capacity']):
            conn.rollback()
            message = f"Guest count must be between 1 and {table['capacity']}."
        elif str(table.get('status') or 'Vacant').strip().lower() not in ('vacant', 'reserved'):
            conn.rollback()
            message = f"Table {table['table_number']} is currently {table.get('status', 'unavailable')} and cannot accept a walk-in."
        else:
            now = get_cafe_time()
            # For reserved tables, verify the reservation is still far enough away
            if str(table.get('status') or '').strip().lower() == 'reserved':
                from utils import get_cafe_date, parse_slot_time, normalize_slot_label
                today_date = str(get_cafe_date())
                upcoming = conn.execute(
                    """
                    SELECT slot_time FROM bookings
                    WHERE table_number = ? AND date = ? AND status IN ('Pending','Confirmed')
                    ORDER BY slot_time ASC LIMIT 1
                    """,
                    (table['table_number'], today_date),
                ).fetchone()
                if upcoming:
                    slot_label = normalize_slot_label(upcoming['slot_time'])
                    start_dt, _ = parse_slot_time(slot_label, now.date())
                    if start_dt:
                        gap = int((start_dt - now).total_seconds() / 60)
                        if gap < WALKIN_LOCKOUT_MINS:
                            conn.rollback()
                            message = f"Cannot seat walk-in — reservation starts in {gap} minutes (minimum {WALKIN_LOCKOUT_MINS} min buffer required)."
                            flash(message, 'danger')
                            if request.headers.get('Accept') == 'application/json':
                                return jsonify({'ok': False, 'message': message}), 400
                            return redirect(url_for('staff.dashboard'))
            slot_label = f"{now.strftime('%I:%M %p').lstrip('0')} (Walk-In)"
            cursor = conn.execute(
                """
                INSERT INTO bookings
                    (phone, name, date, slot_time, seats, table_number, status, seated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'Arrived', ?)
                """,
                (
                    'walkin:staff',
                    'Walk-In Guest',
                    now.date().isoformat(),
                    slot_label,
                    guests,
                    table['table_number'],
                    now.isoformat(),
                ),
            )
            booking_id = cursor.lastrowid
            conn.execute(
                "UPDATE tables SET status = 'Occupied' WHERE id = ?",
                (table['id'],),
            )
            conn.commit()
            success = True
            message = f"Table {table['table_number']} is now occupied - {guests} guest(s) seated."
    except Exception as exc:
        conn.rollback()
        message = f"Booking failed: {exc}"
    finally:
        conn.close()

    flash(message, 'success' if success else 'danger')
    if request.headers.get('Accept') == 'application/json':
        return jsonify({'ok': success, 'message': message, 'booking_id': booking_id}), (200 if success else 400)
    return redirect(url_for('staff.dashboard'))


@staff_bp.route('/dashboard', methods=['GET', 'POST'])
@staff_required
def dashboard():
    from utils import get_cafe_date
    today_date = str(get_cafe_date())

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'update_table':
            table_number = request.form.get('table_number')
            new_status = request.form.get('status')
            success = False
            if table_number and new_status:
                success = db.update_table_status(int(table_number), new_status)
                if success:
                    flash(f'Table status updated to {new_status}.', 'success')
                else:
                    flash('Unable to update table status.', 'danger')
            if request.headers.get('Accept') == 'application/json':
                return jsonify({'ok': success})
            return redirect(url_for('staff.dashboard'))

    # ------- GET logic -------
    from utils import get_cafe_time
    now = get_cafe_time()

    bookings = db.get_today_bookings(today_date)
    tables_db = db.get_all_tables()

    # Compute summary stats for the header badges
    stats = {
        'total': len(tables_db),
        'vacant': sum(1 for t in tables_db if t['status'] == 'Vacant'),
        'reserved': sum(
            1 for t in tables_db if t['status'] in ('Reserved', 'Reserved (Impending)')
        ),
        'occupied': sum(1 for t in tables_db if t['status'] == 'Occupied'),
        'cleaning': sum(1 for t in tables_db if t['status'] == 'Needs Cleaning'),
    }

    return render_template(
        'staff_dashboard.html',
        stats=stats,
        today_date=today_date,
    )


#
# Live Table API (polled every 15 s by Alpine.js on the staff dashboard)
#

@staff_bp.route('/api/live_tables')
@staff_required
def api_live_tables():
    from utils import get_cafe_date, get_cafe_time
    today_date = str(get_cafe_date())
    now = get_cafe_time()

    bookings = db.get_today_bookings(today_date)
    tables_db = db.get_all_tables()
    active_statuses = get_active_booking_statuses()

    # Build the list of still-available walk-in slots (within last 30 min window)
    all_slots = db.get_all_slots()
    today_all_slots = [s['slot_time'] for s in all_slots if s['date'] == today_date]
    future_slots = []
    seen_slots = set()
    for slot_t in today_all_slots:
        start_dt, _ = parse_slot_time(slot_t, now.date())
        if not start_dt:
            continue
        # allow walk-in up to 30 mins after slot starts
        if (start_dt - now).total_seconds() > -1800:
            label = normalize_slot_label(slot_t) or slot_t
            if label not in seen_slots:
                seen_slots.add(label)
                future_slots.append(label)
    future_slots = sort_slot_labels(future_slots)

    # Calculate capacities per slot globally
    slot_capacity = {}
    for s in all_slots:
        if s['date'] == today_date:
            max_g = int(s['max_guests']) if s['max_guests'] is not None else 30
            slot_capacity[s['slot_time']] = max_g

    # Calculate booked guests per slot
    slot_booked = {s: 0 for s in slot_capacity}
    for b in bookings:
        status = normalize_booking_status(b.get('status'))
        if status in active_statuses:
            s_time = b.get('slot_time')
            if s_time in slot_booked:
                slot_booked[s_time] += int(b.get('seats', 0) or 0)

    globally_available_slots = []
    for s in future_slots:
        cap = slot_capacity.get(s, 30)
        booked = slot_booked.get(s, 0)
        if cap - booked >= 1: # Require at least 1 seat available globally
            globally_available_slots.append(s)

    impending_threshold = now + timedelta(minutes=60)
    result = []

    for t_row in tables_db:
        t = dict(t_row)
        active_booking = None
        table_booked_slots = set()
        table_bookings = []

        for b in bookings:
            status = normalize_booking_status(b.get('status'))
            if b['table_number'] != t['table_number']:
                continue
            table_bookings.append(b)
            # Track all booked slots for this table (so we can exclude from walk-in options)
            if status in active_statuses + ('Completed',):
                slot_label = normalize_slot_label(b['slot_time']) if b.get('slot_time') else ''
                if slot_label:
                    table_booked_slots.add(slot_label)

            # Determine active booking for this table
            if status in active_statuses:
                if not active_booking:
                    active_booking = dict(b)
                elif status == 'Arrived' and normalize_booking_status(active_booking.get('status')) != 'Arrived':
                    active_booking = dict(b)

        available_slots = [s for s in globally_available_slots if s not in table_booked_slots]
        next_booking = _build_next_booking(table_bookings, active_booking, now)

        # Determine the display status (may upgrade Vacant → Reserved (Impending))
        display_status = t['status']
        if display_status == 'Vacant':
            for b in bookings:
                b_status = normalize_booking_status(b.get('status'))
                if b['table_number'] == t['table_number'] and b_status in ('Confirmed', 'Pending'):
                    slot_t = normalize_slot_label(b['slot_time']) if b.get('slot_time') else ''
                    b_dt, _ = parse_slot_time(slot_t, now.date())
                    if b_dt and now <= b_dt <= impending_threshold:
                        display_status = 'Reserved (Impending)'
                        break

        table_data = {
            "id": t['id'],
            "table_number": t['table_number'],
            "capacity": t['capacity'],
            "status": display_status,
            "available_slots": available_slots,
            "booking": None,
            "next_booking": next_booking,
        }

        if active_booking:
            active_status = normalize_booking_status(active_booking.get('status'))
            slot_t = active_booking["slot_time"].strip() if active_booking.get("slot_time") else ""
            elapsed_minutes = 0
            if active_status == 'Arrived':
                seated_at_value = (
                    active_booking.get('seated_at')
                    or active_booking.get('updated_at')
                    or active_booking.get('created_at')
                )
                elapsed_minutes = db.get_seated_elapsed_minutes(seated_at_value, now=now)
                time_remaining_str = db.format_service_timer(seated_at_value, now=now)
                gap_mins = 0
                allow_walkin_short = False
            else:
                start_dt, _ = parse_slot_time(slot_t, now.date())
                if start_dt:
                    gap_mins = int((start_dt - now).total_seconds() / 60.0)
                    abs_time = start_dt.strftime('%I:%M %p').lstrip('0')
                    if gap_mins <= 0:
                        time_remaining_str = f"Arriving now @ {abs_time}"
                    elif gap_mins < 60:
                        time_remaining_str = f"Reserved @ {abs_time} ({gap_mins}m)"
                    else:
                        h, m = divmod(gap_mins, 60)
                        dur = f"{h}h {m}m" if m else f"{h}h"
                        time_remaining_str = f"Reserved @ {abs_time} ({dur})"
                    allow_walkin_short = gap_mins > WALKIN_LOCKOUT_MINS
                else:
                    gap_mins = 0
                    time_remaining_str = "Reserved"
                    allow_walkin_short = False
            phone = active_booking.get('phone')
            is_messageable = bool(active_booking.get('is_messageable'))

            table_data["booking"] = {
                "id": active_booking["id"],
                "name": active_booking["name"],
                "guests": active_booking["seats"],
                "status": active_status or active_booking.get('status'),
                "elapsed_minutes": elapsed_minutes,
                "time_remaining": time_remaining_str,
                "phone": phone,
                "is_messageable": is_messageable,
                "gap_minutes": gap_mins,
                "allow_walkin_short": allow_walkin_short,
            }
            if active_status == 'Arrived':
                table_data['status'] = 'Occupied'
            elif active_status in ('Confirmed', 'Pending'):
                table_data['status'] = 'Reserved'

        result.append(table_data)

    return jsonify({"tables": result})


#
# Check-in / Status-action routes (called by forms in the table grid)
#

@staff_bp.route('/checkin/<int:booking_id>', methods=['POST'])
@staff_required
def checkin(booking_id):
    """Mark a reservation as Arrived (guest has shown up)."""
    db.update_booking_status(booking_id, 'Arrived')
    flash('Guest checked in successfully.', 'success')
    if request.headers.get('Accept') == 'application/json':
        return jsonify({'status': 'ok'})
    return redirect(url_for('staff.dashboard'))


@staff_bp.route('/action/<int:booking_id>', methods=['POST'])
@staff_required
def booking_action(booking_id):
    """Generic booking status update (e.g. Completed, No-show)."""
    new_status = request.form.get('action')
    success = False
    if new_status:
        success = db.update_booking_status(booking_id, new_status)
        if success:
            if new_status == 'Completed':
                flash('Checkout complete. Table moved to cleaning and will auto-release in 5 minutes.', 'success')
            else:
                flash(f'Booking status updated to {new_status}.', 'success')
        else:
            flash('Unable to update booking status.', 'danger')
    if request.headers.get('Accept') == 'application/json':
        return jsonify({'ok': success}), (200 if success else 400)
    return redirect(url_for('staff.dashboard'))


@staff_bp.route('/force-release/<int:table_number>', methods=['POST'])
@staff_required
def force_release(table_number):
    success = db.force_release_table(table_number)
    if success:
        flash(f'Table {table_number} is now vacant.', 'success')
    else:
        flash('Table not found.', 'danger')
    if request.headers.get('Accept') == 'application/json':
        return jsonify({'ok': success}), (200 if success else 400)
    return redirect(url_for('staff.dashboard'))
