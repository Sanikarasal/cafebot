import os
import random
import string
from datetime import datetime, timedelta, timezone

from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from functools import wraps
from werkzeug.security import check_password_hash
import db

auth_bp = Blueprint('auth', __name__)

# How long the OTP is valid (minutes)
OTP_EXPIRY_MINUTES = 10


# ──────────────────────────────────────────────
# Access decorators
# ──────────────────────────────────────────────

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
        if session.get('user_role') not in ['admin', 'staff']:
            flash('Access denied.', 'danger')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


# ──────────────────────────────────────────────
# Login / Logout
# ──────────────────────────────────────────────

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

    autofill_usr = session.pop('autofill_usr', '')
    autofill_pwd = session.pop('autofill_pwd', '')
    return render_template('login.html', autofill_usr=autofill_usr, autofill_pwd=autofill_pwd)


@auth_bp.route('/logout')
def logout():
    session.pop('logged_in', None)
    session.pop('username', None)
    session.pop('user_role', None)
    flash('Logged out successfully.', 'info')
    return redirect(url_for('auth.login'))


# ──────────────────────────────────────────────
# Forgot Password — real WhatsApp OTP flow
# ──────────────────────────────────────────────

def _generate_otp(length: int = 6) -> str:
    return ''.join(random.choices(string.digits, k=length))


def _send_otp_whatsapp(phone: str, otp: str, username: str) -> tuple[bool, str]:
    """Send the OTP via WhatsApp using Twilio."""
    from notifier import send_whatsapp_message
    message = (
        f"🔐 CoziCafe Password Reset\n\n"
        f"Hello {username},\n"
        f"Your one-time password (OTP) for account recovery is:\n\n"
        f"*{otp}*\n\n"
        f"⏰ This OTP is valid for {OTP_EXPIRY_MINUTES} minutes.\n"
        f"If you did not request this, please ignore this message."
    )
    return send_whatsapp_message(phone, message)


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    """
    Two-stage forgot-password flow:

    Stage 1 — POST with `username` only:
        • Look up user, check a recovery phone exists.
        • Generate 6-digit OTP, store it + expiry in DB.
        • Send OTP via WhatsApp.
        • Store `otp_pending_for` in session to show Stage 2 on the same page.

    Stage 2 — POST with `username` + `otp` + `new_password` + `confirm_password`:
        • Verify OTP (match + not expired).
        • Update password.
        • Clear session flag, redirect to login.
    """
    # Read session flag — if set, we're on Stage 2
    otp_pending_for = session.get('otp_pending_for', '')

    if request.method == 'POST':
        username    = request.form.get('username', '').strip()
        otp         = request.form.get('otp', '').strip()
        new_password     = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        # ── Stage 2: verify OTP + set new password ──────────────────────────
        if otp:
            if not username:
                flash('Session expired. Please start over.', 'danger')
                session.pop('otp_pending_for', None)
                return redirect(url_for('auth.forgot_password'))

            if not new_password or not confirm_password:
                flash('Please enter and confirm your new password.', 'danger')
                return render_template('forgot_password.html',
                                       stage=2, otp_username=username)

            if new_password != confirm_password:
                flash('Passwords do not match.', 'danger')
                return render_template('forgot_password.html',
                                       stage=2, otp_username=username)

            if len(new_password) < 6:
                flash('Password must be at least 6 characters.', 'danger')
                return render_template('forgot_password.html',
                                       stage=2, otp_username=username)

            ok, reason = db.verify_and_clear_otp(username, otp)
            if not ok:
                flash(f'❌ {reason}', 'danger')
                return render_template('forgot_password.html',
                                       stage=2, otp_username=username)

            # OTP is valid — update password
            db.update_user_password(username, new_password)
            session.pop('otp_pending_for', None)
            flash('✅ Password reset successfully! Please sign in with your new password.', 'success')
            return redirect(url_for('auth.login'))

        # ── Stage 1: send OTP ────────────────────────────────────────────────
        if not username:
            flash('Please enter your username.', 'danger')
            return render_template('forgot_password.html', stage=1)

        user = db.get_user_by_username(username)

        # Generic message — don't reveal whether username exists
        _generic_msg = (
            'If this account exists and has a recovery phone set, '
            f'a WhatsApp OTP has been sent. It expires in {OTP_EXPIRY_MINUTES} minutes.'
        )

        if not user:
            flash(_generic_msg, 'info')
            return render_template('forgot_password.html', stage=1)

        phone = user.get('phone', '') or ''
        if not phone:
            flash(
                '⚠️ No recovery phone number is set for this account. '
                'Please contact your system administrator to set one in Admin Settings.',
                'warning',
            )
            return render_template('forgot_password.html', stage=1)

        otp_code = _generate_otp()
        expiry   = datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRY_MINUTES)
        db.set_reset_otp(username, otp_code, expiry.isoformat())

        ok, msg = _send_otp_whatsapp(phone, otp_code, username)
        if not ok:
            print(f"[ForgotPassword] Twilio error for {username}: {msg}")
            flash(
                '⚠️ Could not send WhatsApp OTP. '
                'Check that Twilio credentials are configured correctly.',
                'danger',
            )
            return render_template('forgot_password.html', stage=1)

        # Mark stage 2 in session so a page refresh stays on Stage 2
        session['otp_pending_for'] = username
        flash(_generic_msg, 'info')
        return render_template('forgot_password.html', stage=2, otp_username=username)

    # ── GET ──────────────────────────────────────────────────────────────────
    if otp_pending_for:
        return render_template('forgot_password.html', stage=2, otp_username=otp_pending_for)
    return render_template('forgot_password.html', stage=1)
