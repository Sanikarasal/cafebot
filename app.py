import os
import sys
from flask import Flask, render_template, redirect, url_for
from dotenv import load_dotenv

from admin import admin_bp
from bot import bot_bp
from auth import auth_bp
from staff import staff_bp
from ops import ops_bp

load_dotenv()

app = Flask(__name__)

# Secret key signs the session cookie – change this in production
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'change-this-in-production!')

# Larger cookie limit so multi-step booking flow fits in session
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Register blueprints
app.register_blueprint(admin_bp)
app.register_blueprint(bot_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(staff_bp)
app.register_blueprint(ops_bp)


@app.route('/')
def index():
    """Redirect to login page."""
    return redirect(url_for('auth.login'))

if __name__ == '__main__':
    print("[*] Starting Server...", flush=True)
    print("    Running on http://127.0.0.1:5000", flush=True)
    print("    Webhook URL: http://127.0.0.1:5000/webhook", flush=True)
    print("    Login Panel: http://127.0.0.1:5000/login", flush=True)
    sys.stdout.flush()

    # Auto-generate slots for the next 7 days on startup
    try:
        import db as _db
        n = _db.auto_generate_slots()
        print(f"    [OK] Auto-generated {n} new time slot(s)", flush=True)
    except Exception as _e:
        print(f"    [!] Slot auto-generation error: {_e}", flush=True)

    # Start booking reminder scheduler
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from scheduler import check_and_send_reminders, check_and_auto_noshow
        from db import auto_generate_slots

        reminder_scheduler = BackgroundScheduler()
        reminder_scheduler.add_job(
            check_and_send_reminders,
            'interval',
            seconds=60,
            id='booking_reminders',
        )
        reminder_scheduler.add_job(
            check_and_auto_noshow,
            'interval',
            seconds=60,
            id='noshow_autorelease',
        )
        reminder_scheduler.add_job(
            auto_generate_slots,
            'interval',
            minutes=30,
            id='slot_autogen',
        )
        reminder_scheduler.start()
        print("    [OK] Reminder scheduler started (every 60s)", flush=True)
        print("    [OK] No-show auto-release started (every 60s)", flush=True)
        print("    [OK] Slot auto-generation started (every 30 min)", flush=True)
    except ImportError:
        print("    [!] APScheduler not installed -- reminders disabled", flush=True)
    except Exception as e:
        print(f"    [!] Scheduler error: {e}", flush=True)

    try:
        app.run(debug=False, port=5000, use_reloader=False)
    except OSError as e:
        print(f"\n[X] Could not start server: {e}", flush=True)
        print("    Port 5000 may already be in use.", flush=True)
        print("    Run this to free it: Stop-Process -Name python -Force", flush=True)
        sys.exit(1)
