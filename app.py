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


# ---------------------------------------------------------------------------
# APScheduler startup — runs whether launched via `python app.py` OR Gunicorn.
# On Railway, Gunicorn *imports* this module; the `if __name__ == '__main__'`
# guard below never fires, so the scheduler MUST be initialised at import time.
#
# Multi-worker guard: Gunicorn forks N worker processes from the master.  We
# use a "scheduler lock" environment variable so only the first worker that
# raises the flag actually starts the scheduler thread (the others skip it).
# This prevents N identical reminder-jobs firing in parallel.
# ---------------------------------------------------------------------------
def _start_scheduler():
    """Initialise and start APScheduler background jobs."""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from scheduler import check_and_send_reminders, check_and_auto_noshow
        from db import auto_generate_slots

        sched = BackgroundScheduler(daemon=True)
        sched.add_job(
            check_and_send_reminders,
            'interval',
            seconds=60,
            id='booking_reminders',
        )
        sched.add_job(
            check_and_auto_noshow,
            'interval',
            seconds=60,
            id='noshow_autorelease',
        )
        sched.add_job(
            auto_generate_slots,
            'interval',
            minutes=30,
            id='slot_autogen',
        )
        sched.start()
        print("[Scheduler] Reminder scheduler started (every 60 s)", flush=True)
        print("[Scheduler] No-show auto-release started (every 60 s)", flush=True)
        print("[Scheduler] Slot auto-generation started (every 30 min)", flush=True)
    except ImportError:
        print("[Scheduler] APScheduler not installed — reminders disabled", flush=True)
    except Exception as exc:
        print(f"[Scheduler] ERROR: {exc}", flush=True)
        import traceback
        traceback.print_exc()


# Use an env-var flag so Gunicorn's multiple workers don't each start a
# duplicate scheduler thread.  The first worker to reach this block marks the
# flag and starts the scheduler; subsequent workers see the flag and skip it.
_SCHEDULER_STARTED_FLAG = "_CAFEBOT_SCHEDULER_STARTED"
if not os.environ.get(_SCHEDULER_STARTED_FLAG):
    os.environ[_SCHEDULER_STARTED_FLAG] = "1"
    # Auto-generate slots for the next 7 days on startup
    try:
        import db as _db
        _n = _db.auto_generate_slots()
        print(f"[Startup] Auto-generated {_n} new time slot(s)", flush=True)
    except Exception as _e:
        print(f"[Startup] Slot auto-generation error: {_e}", flush=True)
    _start_scheduler()


if __name__ == '__main__':
    print("[*] Starting Server...", flush=True)
    print("    Running on http://127.0.0.1:5000", flush=True)
    print("    Webhook URL: http://127.0.0.1:5000/webhook", flush=True)
    print("    Login Panel: http://127.0.0.1:5000/login", flush=True)
    sys.stdout.flush()

    try:
        app.run(debug=False, port=5000, use_reloader=False)
    except OSError as e:
        print(f"\n[X] Could not start server: {e}", flush=True)
        print("    Port 5000 may already be in use.", flush=True)
        print("    Run this to free it: Stop-Process -Name python -Force", flush=True)
        sys.exit(1)
