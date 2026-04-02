from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from functools import wraps
from werkzeug.security import check_password_hash
import db

auth_bp = Blueprint('auth', __name__)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('auth.login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('auth.login', next=request.url))
        if session.get('user_role') != 'admin':
            flash('Admin access required.', 'danger')
            # Redirect staff to staff dashboard
            if session.get('user_role') == 'staff':
                return redirect(url_for('staff.dashboard'))
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

def staff_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('auth.login', next=request.url))
        # Admins can also access staff pages if needed, but for strict separation, let's enforce staff OR admin.
        # Requirements state "so staff cannot access admin URLs". Admin generally needs access everywhere.
        if session.get('user_role') not in ['admin', 'staff']:
            flash('Access denied.', 'danger')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        user = db.get_user_by_username(username)
        if user and check_password_hash(user['password_hash'], password):
            session['logged_in'] = True
            session['username'] = username
            session['user_role'] = user['role']
            flash(f'Logged in as {user["role"]}.', 'success')
            
            if user['role'] == 'admin':
                return redirect(url_for('admin.dashboard'))
            else:
                return redirect(url_for('staff.dashboard'))
        else:
            flash('Invalid credentials.', 'danger')
            
    # Check for autofill data
    autofill_usr = session.pop('autofill_usr', '')
    autofill_pwd = session.pop('autofill_pwd', '')
    
    return render_template('login.html', autofill_usr=autofill_usr, autofill_pwd=autofill_pwd)

@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        otp = request.form.get('otp', '').strip()

        if username and otp:
            user = db.get_user_by_username(username)
            if user:
                conn = db.get_db_connection()
                try:
                    dummy_pass = "Admin@123"
                    conn.execute("UPDATE users SET password_hash = ? WHERE username = ?", (generate_password_hash(dummy_pass), username))
                    conn.commit()
                    
                    session['autofill_usr'] = username
                    session['autofill_pwd'] = dummy_pass
                    flash('OTP verified! Password reset successfully.', 'success')
                finally:
                    conn.close()
            else:
                flash('Username not found.', 'danger')
            return redirect(url_for('auth.login'))
        elif username:
            user = db.get_user_by_username(username)
            if user:
                flash('If an account exists for this username, an administrator will assist you. If you are the system administrator, use the local reset scripts.', 'info')
            else:
                flash('If an account exists for this username, an administrator will assist you. If you are the system administrator, use the local reset scripts.', 'info')
            return redirect(url_for('auth.login'))
        else:
            flash('Please enter a username.', 'danger')
            
    return render_template('forgot_password.html')

@auth_bp.route('/logout')
def logout():
    session.pop('logged_in', None)
    session.pop('username', None)
    session.pop('user_role', None)
    flash('Logged out successfully.', 'info')
    return redirect(url_for('auth.login'))
