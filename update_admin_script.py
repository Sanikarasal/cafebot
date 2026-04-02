import os

def update_admin():
    with open('admin.py', 'r', encoding='utf-8') as f:
        lines = f.readlines()

    new_lines = []
    skip = False
    for i, line in enumerate(lines):
        # Lines 10-47 define login_required and auth routes. We remove them.
        if 9 <= i <= 46:
            continue
        
        # We start skipping when we encounter Staff Mode banner
        if "# Staff Mode" in line or "@admin_bp.route('/staff')" in line:
            skip = True
            
        if skip:
            continue
            
        line = line.replace('@login_required', '@admin_required')
        
        # Replace checking hash with generation hash for staff management
        if "from werkzeug.security import check_password_hash" in line:
            line = "from werkzeug.security import generate_password_hash\nfrom auth import admin_required\n"
            
        new_lines.append(line)

    staff_management = """
# ---------------------------------------------------------------------------
# Staff Management
# ---------------------------------------------------------------------------

@admin_bp.route('/staff_management', methods=['GET', 'POST'])
@admin_required
def manage_staff():
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add':
            username = request.form.get('username')
            password = request.form.get('password')
            if username and password:
                conn = db.get_db_connection()
                try:
                    conn.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'staff')", 
                        (username, generate_password_hash(password)))
                    conn.commit()
                    flash('Staff member added.', 'success')
                except Exception as e:
                    flash('Error adding staff member. Username may exist.', 'danger')
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
            if user_id and new_password:
                conn = db.get_db_connection()
                try:
                    conn.execute("UPDATE users SET password_hash = ? WHERE id = ? AND role = 'staff'", 
                        (generate_password_hash(new_password), user_id))
                    conn.commit()
                    flash('Staff password reset.', 'success')
                finally:
                    conn.close()
                    
        return redirect(url_for('admin.manage_staff'))
        
    users = db.get_all_users()
    staff_users = [u for u in users if u['role'] == 'staff']
    return render_template('staff_management.html', staff=staff_users)
"""

    content = "".join(new_lines) + staff_management

    with open('admin.py', 'w', encoding='utf-8') as f:
        f.write(content)
        print("Updated admin.py")

if __name__ == '__main__':
    update_admin()
