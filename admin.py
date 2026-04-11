from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from functools import wraps
from datetime import date, timedelta
from werkzeug.security import generate_password_hash
from auth import admin_required
from utils import normalize_booking_status
import db

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


# normalize_booking_status used heavily in template logic
def _augment_booking(b_dict):
    """Normalize status for a booking dict in-place."""
    b_dict['status'] = normalize_booking_status(b_dict.get('status')) or b_dict.get('status')
    if 'is_messageable' not in b_dict:
        b_dict['is_messageable'] = False
    return b_dict


#
# Dashboard
#

@admin_bp.route('/dashboard')
@admin_required
def dashboard():
    from utils import get_cafe_date
    today_date = str(get_cafe_date())
    metrics = db.get_dashboard_metrics(today_date)
    metrics.setdefault('revenue_today', 0)
    recent_bookings_raw = db.get_recent_bookings(5)

    recent_bookings = [_augment_booking(dict(b)) for b in recent_bookings_raw]

    # Chart data
    slot_chart_data = db.get_bookings_by_slot_today(today_date)
    weekly_trend = db.get_weekly_booking_trend()

    return render_template(
        'dashboard.html',
        bookings=recent_bookings,
        metrics=metrics,
        slot_chart_data=slot_chart_data,
        weekly_trend=weekly_trend,
    )


@admin_bp.route('/api/dashboard_data')
@admin_required
def api_dashboard_data():
    """Returns JSON payload of dashboard metrics and recent bookings for AlpineJS auto-refresh."""
    from utils import get_cafe_date
    today_date = str(get_cafe_date())

    metrics = db.get_dashboard_metrics(today_date)
    metrics.setdefault('revenue_today', 0)

    bookings_raw = db.get_recent_bookings(5)
    recent_bookings = [_augment_booking(dict(b)) for b in bookings_raw]

    return jsonify({
        'metrics': metrics,
        'recent_bookings': recent_bookings,
    })


#
# Bookings
#

@admin_bp.route('/bookings')
@admin_required
def all_bookings():
    bookings_raw = db.get_all_bookings()
    bookings = [_augment_booking(dict(b)) for b in bookings_raw]
    return render_template('bookings.html', bookings=bookings)


@admin_bp.route('/booking_action/<int:booking_id>', methods=['POST'])
@admin_required
def booking_action(booking_id):
    action = request.form.get('action')
    booking = db.get_booking_by_id_only(booking_id)

    if action == 'cancel':
        success, message = db.admin_cancel_booking(booking_id)
        if success:
            if booking and booking['phone'] and not booking['phone'].startswith('walkin:'):
                if db.get_messageability(booking['phone']):
                    from notifier import send_whatsapp_message
                    t_success, t_msg = send_whatsapp_message(
                        booking['phone'],
                        f"❌ Your CoziCafe booking for {booking['date']} at {booking['slot_time']} has been cancelled."
                    )
                    if t_success:
                        flash(f"{message} (Customer notified)", 'success')
                    else:
                        flash(f"{message} (Twilio Error: {t_msg})", 'warning')
                else:
                    flash(f"{message} (Customer session expired, no WhatsApp sent)", 'warning')
            else:
                flash(message, 'success')
        else:
            flash(message, 'danger')

    elif action in ['Confirmed', 'Arrived', 'Completed', 'No-show']:
        db.update_booking_status(booking_id, action)

        if action == 'Confirmed' and booking and booking['phone'] and not booking['phone'].startswith('walkin:'):
            if db.get_messageability(booking['phone']):
                from notifier import send_whatsapp_message
                t_success, t_msg = send_whatsapp_message(
                    booking['phone'],
                    f"✅ Great news! Your CoziCafe booking for {booking['date']} at {booking['slot_time']} is confirmed."
                )
                if t_success:
                    flash('Booking confirmed and customer notified.', 'success')
                else:
                    flash(f'Booking confirmed locally. (Twilio Error: {t_msg})', 'warning')
            else:
                flash('Booking confirmed. (Customer session expired, no WhatsApp sent)', 'warning')
        else:
            flash(f'Booking status updated to {action}.', 'success')

    return redirect(request.referrer or url_for('admin.all_bookings'))


@admin_bp.route('/bookings/bulk_delete', methods=['POST'])
@admin_required
def bulk_delete_bookings():
    data = request.get_json()
    if not data or 'ids' not in data:
        return jsonify({'ok': False, 'message': 'No IDs provided'}), 400
        
    ids = data['ids']
    if not isinstance(ids, list) or not ids:
        return jsonify({'ok': False, 'message': 'Invalid IDs provided'}), 400
        
    try:
        id_list = [int(i) for i in ids]
    except (ValueError, TypeError):
        return jsonify({'ok': False, 'message': 'Invalid ID format'}), 400
        
    conn = db.get_db_connection()
    try:
        placeholders = ', '.join(['?'] * len(id_list))
        query = f"DELETE FROM bookings WHERE id IN ({placeholders}) AND status IN ('Completed', 'No-show', 'cancelled')"
        
        cursor = conn.cursor()
        cursor.execute(query, id_list)
        conn.commit()
        deleted_count = cursor.rowcount
        
        return jsonify({'ok': True, 'deleted_count': deleted_count})
    except Exception as e:
        conn.rollback()
        return jsonify({'ok': False, 'message': str(e)}), 500
    finally:
        conn.close()



#
# Slots Management
#

@admin_bp.route('/slots', methods=['GET', 'POST'])
@admin_required
def manage_slots():
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'delete':
            slot_id = request.form.get('slot_id')
            if slot_id:
                db.delete_time_slot(slot_id)
                flash('Time slot deleted.', 'warning')

        elif action == 'delete_day':
            target_date = request.form.get('target_date')
            if target_date:
                count = db.delete_slots_for_date(target_date)
                flash(f'Deleted {count} slot(s) for {target_date}.', 'warning')

        elif action == 'clear_week':
            count = db.clear_all_future_slots()
            flash(f'Cleared {count} upcoming slot(s).', 'warning')

        return redirect(url_for('admin.manage_slots'))

    slots = db.get_slots_with_bookings()
    cfg = db.load_slot_config()
    from utils import get_cafe_date
    today_str = str(get_cafe_date())
    return render_template(
        'slots.html',
        slots=slots,
        schedule=cfg['schedule'],
        capacity=cfg['capacity'],
        days_ahead=cfg['days_ahead'],
        today_str=today_str,
    )


@admin_bp.route('/slots/regenerate', methods=['POST'])
@admin_required
def regenerate_slots():
    """Manually trigger slot auto-generation."""
    n = db.auto_generate_slots()
    if n:
        flash(f'Generated {n} new time slot(s) for the next 7 days.', 'success')
    else:
        flash('All slots for the coming days already exist — nothing new to generate.', 'info')
    return redirect(url_for('admin.manage_slots'))


@admin_bp.route('/slots/update_schedule', methods=['POST'])
@admin_required
def update_slot_schedule():
    """Save an updated slot schedule from the Edit Schedule modal."""
    import re
    raw_times = request.form.getlist('slot_times')  # list of time strings
    try:
        capacity = int(request.form.get('capacity', 30))
        days_ahead = int(request.form.get('days_ahead', 7))
    except (ValueError, TypeError):
        flash('Invalid capacity or days ahead value.', 'danger')
        return redirect(url_for('admin.manage_slots'))

    # Validate capacity
    if capacity < 1 or capacity > 500:
        flash('Capacity must be between 1 and 500.', 'danger')
        return redirect(url_for('admin.manage_slots'))

    if days_ahead < 1 or days_ahead > 90:
        flash('Days ahead must be between 1 and 90.', 'danger')
        return redirect(url_for('admin.manage_slots'))

    # Validate and deduplicate time strings
    time_pattern = re.compile(
        r'^\d{1,2}:\d{2}\s?[AP]M\s?-\s?\d{1,2}:\d{2}\s?[AP]M$', re.IGNORECASE
    )
    cleaned = []
    for t in raw_times:
        t = t.strip()
        if not t:
            continue
        if not time_pattern.match(t):
            flash(f'Invalid time format: "{t}". Use e.g. "10:00 AM - 11:00 AM".', 'danger')
            return redirect(url_for('admin.manage_slots'))
        if t not in cleaned:
            cleaned.append(t)

    if not cleaned:
        flash('Schedule must have at least one time slot.', 'danger')
        return redirect(url_for('admin.manage_slots'))

    db.save_slot_config(cleaned, capacity, days_ahead)
    import logging
    logging.getLogger(__name__).info(
        '[AUDIT] Schedule updated by %s: %d slots, cap=%d, days=%d',
        session.get('username'), len(cleaned), capacity, days_ahead
    )
    flash(f'Schedule saved ({len(cleaned)} slots). Re-generate to apply changes.', 'success')
    return redirect(url_for('admin.manage_slots'))


@admin_bp.route('/slots/<int:slot_id>/capacity', methods=['POST'])
@admin_required
def update_slot_capacity(slot_id):
    """Inline capacity update for a single slot."""
    try:
        new_cap = int(request.form.get('capacity', 0))
    except (ValueError, TypeError):
        return jsonify({'ok': False, 'error': 'Invalid capacity'}), 400
    if new_cap < 1 or new_cap > 500:
        return jsonify({'ok': False, 'error': 'Capacity must be 1–500'}), 400
    updated = db.update_slot_capacity(slot_id, new_cap)
    if updated:
        return jsonify({'ok': True, 'capacity': new_cap})
    return jsonify({'ok': False, 'error': 'Slot not found'}), 404


@admin_bp.route('/slots/export')
@admin_required
def export_slots_csv():
    """Export all upcoming slots as a CSV file."""
    import csv, io
    from flask import Response
    slots = db.get_slots_with_bookings()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'Time', 'Capacity', 'Booked', 'Available', 'Fill %'])
    for s in slots:
        cap = s.get('max_cap', 30)
        booked = s.get('booked_guests', 0)
        writer.writerow([
            s['date'], s['slot_time'], cap, booked,
            cap - booked, f"{s.get('fill_pct', 0)}%"
        ])
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=slots_export.csv'}
    )


@admin_bp.route('/slots/api/stats')
@admin_required
def slot_stats_api():
    """JSON endpoint: booking fill stats per slot time label."""
    stats = db.get_slot_booking_stats()
    return jsonify(stats)


#
# Tables
#

@admin_bp.route('/tables', methods=['GET', 'POST'])
@admin_required
def manage_tables():
    if request.method == 'POST':
        action = request.form.get('action')
        conn = db.get_db_connection()
        try:
            if action == 'add':
                number = request.form.get('table_number')
                name = request.form.get('table_name', f'Table {number}')
                capacity = request.form.get('capacity')
                location = request.form.get('location')
                if number and capacity and location:
                    conn.execute(
                        "INSERT INTO tables (table_number, table_name, capacity, location) VALUES (?, ?, ?, ?)",
                        (number, name, capacity, location)
                    )
                    conn.commit()
                    flash('Table added successfully.', 'success')
            elif action == 'edit':
                tid = request.form.get('table_id')
                name = request.form.get('table_name')
                capacity = request.form.get('capacity')
                location = request.form.get('location')
                if tid and name and capacity and location:
                    conn.execute(
                        "UPDATE tables SET table_name = ?, capacity = ?, location = ? WHERE id = ?",
                        (name, capacity, location, tid)
                    )
                    conn.commit()
                    flash('Table updated successfully.', 'success')
            elif action == 'delete':
                tid = request.form.get('table_id')
                if tid:
                    conn.execute("DELETE FROM tables WHERE id = ?", (tid,))
                    conn.commit()
                    flash('Table deleted successfully.', 'warning')
        except Exception as e:
            conn.rollback()
            flash(f'Error: {str(e)}', 'danger')
        finally:
            conn.close()

        return redirect(url_for('admin.manage_tables'))

    tables = db.get_all_tables()
    return render_template('tables.html', tables=tables)


#
# Reports
#

@admin_bp.route('/reports')
@admin_required
def reports():
    """Reports page with booking analytics."""
    from utils import get_cafe_date
    today = get_cafe_date()
    start = request.args.get('start', (today - timedelta(days=7)).isoformat())
    end = request.args.get('end', today.isoformat())

    report_data = db.get_report_data(start, end)

    return render_template(
        'reports.html',
        report=report_data,
        start_date=start,
        end_date=end,
    )


#
# Staff Management
#

@admin_bp.route('/staff_management', methods=['GET', 'POST'])
@admin_required
def manage_staff():
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'add':
            username = request.form.get('username')
            password = request.form.get('password')

            if not username or len(username) < 3:
                flash('Username must be at least 3 characters.', 'danger')
            elif not password or len(password) < 6:
                flash('Password must be at least 6 characters.', 'danger')
            else:
                conn = db.get_db_connection()
                try:
                    conn.execute(
                        "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'staff')",
                        (username, generate_password_hash(password))
                    )
                    conn.commit()
                    flash('Staff member added.', 'success')
                except Exception:
                    flash('Error adding staff member. Username may already exist.', 'danger')
                finally:
                    conn.close()

        elif action == 'delete':
            user_id = request.form.get('user_id')
            if user_id:
                conn = db.get_db_connection()
                try:
                    conn.execute("DELETE FROM users WHERE id = ? AND role = 'staff'", (user_id,))
                    conn.commit()
                    flash('Staff member deleted.', 'warning')
                finally:
                    conn.close()

        elif action == 'reset':
            user_id = request.form.get('user_id')
            new_password = request.form.get('new_password')

            if not new_password or len(new_password) < 6:
                flash('Password must be at least 6 characters.', 'danger')
            elif user_id:
                conn = db.get_db_connection()
                try:
                    conn.execute(
                        "UPDATE users SET password_hash = ? WHERE id = ? AND role = 'staff'",
                        (generate_password_hash(new_password), user_id)
                    )
                    conn.commit()
                    flash('Staff password reset.', 'success')
                finally:
                    conn.close()

        return redirect(url_for('admin.manage_staff'))

    users = db.get_all_users()
    staff_users = [u for u in users if u['role'] == 'staff']
    return render_template('staff_management.html', staff=staff_users)


#
# Admin Profile Settings
#

@admin_bp.route('/settings', methods=['GET', 'POST'])
@admin_required
def admin_settings():
    username = session.get('username')
    user = db.get_user_by_username(username)

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'change_password':
            current_password = request.form.get('current_password', '')
            new_password = request.form.get('new_password', '')
            confirm_password = request.form.get('confirm_password', '')

            from werkzeug.security import check_password_hash
            if not check_password_hash(user['password_hash'], current_password):
                flash('Current password is incorrect.', 'danger')
            elif len(new_password) < 6:
                flash('New password must be at least 6 characters.', 'danger')
            elif new_password != confirm_password:
                flash('New passwords do not match.', 'danger')
            else:
                conn = db.get_db_connection()
                try:
                    conn.execute(
                        "UPDATE users SET password_hash = ? WHERE username = ?",
                        (generate_password_hash(new_password), username)
                    )
                    conn.commit()
                    flash('Password changed successfully.', 'success')
                except Exception as e:
                    flash(f'Error updating password: {e}', 'danger')
                finally:
                    conn.close()

        elif action == 'update_email':
            email = request.form.get('recovery_email', '').strip().lower()
            if email and ('@' not in email or '.' not in email.split('@')[-1]):
                flash('Invalid email address.', 'danger')
            else:
                db.update_user_email(username, email)
                if email:
                    flash('✅ Recovery email address saved.', 'success')
                else:
                    flash('Recovery email address cleared.', 'info')

        return redirect(url_for('admin.admin_settings'))

    return render_template('admin_settings.html', user=user)