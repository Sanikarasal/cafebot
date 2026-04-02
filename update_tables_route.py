import os

def update_tables_admin():
    with open('admin.py', 'r', encoding='utf-8') as f:
        content = f.read()

    tables_route_old = """@admin_bp.route('/tables')
@admin_required
def manage_tables():
    \"\"\"Admin table grid view with availability filter by date + time.\"\"\"
    from datetime import date as dt_date
    filter_date = request.args.get('date', str(dt_date.today()))
    filter_time = request.args.get('time', '')

    if filter_time:
        tables = db.get_table_status(filter_date, filter_time)
    else:
        raw_tables = db.get_all_tables()
        tables = [{**dict(t), 'is_booked': None} for t in raw_tables]

    all_slots = db.get_all_slots()

    seen_times = set()
    unique_slot_times = []
    for slot in all_slots:
        if slot['slot_time'] not in seen_times:
            seen_times.add(slot['slot_time'])
            unique_slot_times.append(slot['slot_time'])

    return render_template(
        'tables.html',
        tables=tables,
        filter_date=filter_date,
        filter_time=filter_time,
        unique_slot_times=unique_slot_times,
    )"""

    tables_route_new = """@admin_bp.route('/tables', methods=['GET', 'POST'])
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
    return render_template('tables.html', tables=tables)"""

    if tables_route_old in content:
        content = content.replace(tables_route_old, tables_route_new)
        with open('admin.py', 'w', encoding='utf-8') as f:
            f.write(content)
        print("Updated admin.py with new manage_tables")
    else:
        print("Could not find the old manage_tables route to replace. Look into it.")

if __name__ == '__main__':
    update_tables_admin()
