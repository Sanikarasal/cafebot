# CafeBot — Complete Code Walkthrough

This document explains **every Python file** in the project in detail — what it does, why it exists, how each function works, and how files talk to each other.

---

## Table of Contents

1. [app.py — The Entry Point](#1-apppy--the-entry-point)
2. [auth.py — Authentication & Access Control](#2-authpy--authentication--access-control)
3. [bot.py — The WhatsApp State Machine](#3-botpy--the-whatsapp-state-machine)
4. [payment.py — Razorpay Integration](#4-paymentpy--razorpay-integration)
5. [notifier.py — Twilio Message Sender](#5-notifierpy--twilio-message-sender)
6. [db.py — The Database Layer](#6-dbpy--the-database-layer)
7. [utils.py — Shared Utility Functions](#7-utilspy--shared-utility-functions)
8. [scheduler.py — Background Jobs](#8-schedulerpy--background-jobs)
9. [admin.py — Admin Web Dashboard](#9-adminpy--admin-web-dashboard)
10. [staff.py — Staff POS Dashboard](#10-staffpy--staff-pos-dashboard)
11. [ops.py — Operations API Layer](#11-opspy--operations-api-layer)
12. [init_db.py — Fresh Database Setup](#12-init_dbpy--fresh-database-setup)
13. [How All Files Connect](#13-how-all-files-connect)

---

## 1. `app.py` — The Entry Point

**Role**: The master file you run to start the entire server. It wires all parts together.

```
python app.py
```

### What It Does Step-By-Step

**Step 1 — Load secrets from `.env`**
```python
load_dotenv()
```
This reads your `.env` file and populates `os.getenv()` calls across all files with keys like `TWILIO_ACCOUNT_SID`, `RAZORPAY_KEY_ID`, etc.

**Step 2 — Create the Flask app**
```python
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'super-secret-cafebot-key-2024!')
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
```
- `SECRET_KEY` is used to sign and encrypt the session cookie. Every time a staff member logs in, Flask stores their username and role in a cryptographically signed cookie. Without this key, nobody can forge a session.
- `SESSION_COOKIE_SAMESITE = 'Lax'` prevents the session cookie from being dropped when following redirect links, which is critical for the multi-step booking and payment flows.

**Step 3 — Register Blueprints (route modules)**
```python
app.register_blueprint(admin_bp)   # /admin/...
app.register_blueprint(bot_bp)     # /webhook
app.register_blueprint(auth_bp)    # /login, /logout
app.register_blueprint(staff_bp)   # /staff/...
app.register_blueprint(ops_bp)     # /ops/...
```
Each blueprint is an independent Flask routing module. The `url_prefix` defined in each file (e.g., `url_prefix='/admin'`) is prepended to all routes in that file.

**Step 4 — Auto-generate time slots**
```python
n = _db.auto_generate_slots()
```
Immediately on startup, the app calls `db.py` to generate time slots for the **next 7 days** based on `slot_config.json`. This ensures the bot always has slots to offer customers even if the server was restarted.

**Step 5 — Mount background jobs (APScheduler)**
```python
reminder_scheduler = BackgroundScheduler()
reminder_scheduler.add_job(check_and_send_reminders, 'interval', seconds=60)
reminder_scheduler.add_job(check_and_auto_noshow, 'interval', seconds=60)
reminder_scheduler.add_job(auto_generate_slots, 'interval', minutes=30)
reminder_scheduler.start()
```
APScheduler runs **in a background thread** alongside Flask. Three jobs run:
- Every 60s: Check if any booking is starting in ~10 minutes → send WhatsApp reminder.
- Every 60s: Check if any customer never showed up → mark No-show and release table.
- Every 30m: Generate new time slots so the system never runs out.

**Step 6 — Run the Flask server**
```python
app.run(debug=True, port=5000, use_reloader=False)
```
`use_reloader=False` is important! Flask's hot-reload would start APScheduler twice (two processes), causing duplicate reminder messages. Disabling it prevents that.

---

## 2. `auth.py` — Authentication & Access Control

**Role**: Manages login, logout, forgot-password, and provides security decorators that protect all other routes.

### The Auth Blueprint
```python
auth_bp = Blueprint('auth', __name__)
```
No `url_prefix` here — routes are at the root level (`/login`, `/logout`).

### Decorator: `@admin_required`
```python
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
```
This uses Python's **decorator pattern**. Any route decorated with `@admin_required` (like all routes in `admin.py`) will **first** run this wrapper before the actual route function. It checks:
1. Is the user logged in at all? If not → redirect to login.
2. Do they have `admin` role? If not → redirect them based on their actual role.

This means a staff member cannot manually navigate to `/admin/dashboard` — they'll be bounced back to their own dashboard.

### Decorator: `@staff_required`
Same pattern but allows **both** `admin` and `staff` roles. Admins can access staff pages; staff cannot access admin pages.

### Login Route
```python
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
            if user['role'] == 'admin':
                return redirect(url_for('admin.dashboard'))
            else:
                return redirect(url_for('staff.dashboard'))
```
- It fetches the user row from the `users` table in the database.
- Uses `werkzeug.security.check_password_hash` to compare the submitted password against the stored bcrypt hash. **Passwords are never stored in plain text.**
- On success, it writes three values into the encrypted Flask session — these persist across requests until logout.

### Logout Route
```python
@auth_bp.route('/logout')
def logout():
    session.pop('logged_in', None)
    session.pop('username', None)
    session.pop('user_role', None)
```
Simply removes the session keys. The next request from that browser will find no session and get bounced to login.

---

## 3. `bot.py` — The WhatsApp State Machine

**Role**: This is the largest and most complex file. It is the entire customer-facing WhatsApp booking experience, implemented as a deterministic **State Machine**.

### How Twilio Delivers Messages

When a user sends a WhatsApp message to the Twilio Sandbox number, Twilio makes an **HTTP POST request** to `/webhook` with `From` (user's phone) and `Body` (message text) as form fields.

The Flask route receives this, processes it, and returns a **TwiML** (Twilio Markup Language) XML response. Twilio reads that XML and sends the text in `<Message><Body>` back to the user's WhatsApp.

### The `ConversationStore` Class

The bot uses a completely custom in-memory object called `ConversationStore` (not Flask's built-in session) to track each user's multi-step booking progress:
```python
class ConversationStore:
    def __init__(self, phone=None, state=None, data=None, updated_at=None):
        self.phone = phone
        self.state = state      # Current state string e.g. "ASK_NAME"
        self.data = data or {}  # Dict e.g. {"b_name": "Sanik", "b_date": "2026-03-31"}
        self.cleared = False
```
This object is loaded from the database at the start of each webhook request, modified during processing, then saved back to the database at the end. This means if the server restarts mid-booking, the user does not lose their progress.

```python
# Loading the store from DB
def _load_conversation_store(phone):
    convo = db.get_conversation(phone)     # Reads `conversations` table
    ...
    g._conv_store = store                  # Attaches it to Flask's request context (g)

# Saving back to DB after request
def _persist_conversation():
    store = _get_conversation_store()
    db.save_conversation(store.phone, state, store.data)   # UPSERT to DB
```

The `session` variable in `bot.py` is a `LocalProxy` that points to the `ConversationStore` stored in Flask's request context `g`. This trick lets the rest of the bot code use `session["b_name"] = "Sanik"` as if it were a regular dict, but the data actually lives in the `ConversationStore`.

### State Constants
```python
MAIN_MENU = "MAIN_MENU"
ASK_NAME = "ASK_NAME"
ASK_DATE = "ASK_DATE"
SELECT_SLOT = "SELECT_SLOT"
ASK_SEATS = "ASK_SEATS"
SELECT_TABLE = "SELECT_TABLE"
CONFIRM_BOOKING = "CONFIRM_BOOKING"
AWAITING_PAYMENT = "AWAITING_PAYMENT"
CANCEL_SELECT = "CANCEL_SELECT"
CANCEL_CONFIRM = "CANCEL_CONFIRM"
ASK_WAITLIST = "ASK_WAITLIST"
```
Every state is just a string. The user's current state is stored in the `conversations` table and loaded on every webhook call.

### The Dispatch Table
```python
STATE_HANDLERS = {
    MAIN_MENU: handle_main_menu,
    ASK_NAME: handle_ask_name,
    ASK_DATE: handle_ask_date,
    SELECT_SLOT: handle_select_slot,
    ASK_SEATS: handle_ask_seats,
    SELECT_TABLE: handle_select_table,
    CONFIRM_BOOKING: handle_confirm_booking,
    AWAITING_PAYMENT: handle_awaiting_payment,
    CANCEL_SELECT: handle_cancel_select,
    CANCEL_CONFIRM: handle_cancel_confirm,
    ASK_WAITLIST: handle_ask_waitlist,
}
```
This dictionary maps each state string to its handler function. The webhook does a single lookup: `handler = STATE_HANDLERS.get(current_state)` and calls `handler(user_input, phone, message)`. Clean and extensible.

### The Webhook Route
```python
@bot_bp.route("/webhook", methods=["POST"])
def webhook():
    user_input = request.values.get("Body", "").strip()
    sender_phone = request.values.get("From", "").strip()
    response = MessagingResponse()
    message = response.message()

    db.update_customer_session(sender_phone)   # Track 24hr Twilio session
    _load_conversation_store(sender_phone)     # Load state from DB

    try:
        if "state" not in session:
            reset_navigation(MAIN_MENU)

        # Global reset commands — always work regardless of state
        if user_input.lower() in {"*", "#", "reset"}:
            # If awaiting payment, also delete the pending (unconfirmed) booking
            if current_state == AWAITING_PAYMENT:
                db.delete_pending_booking(session.get("payment_booking_id"))
            clear_booking_context()
            reset_navigation(MAIN_MENU)
            clear_conversation_state()
            message.body(get_main_menu_message())
            return str(response)

        # Route to the correct handler
        handler = STATE_HANDLERS.get(current_state)
        handler(user_input, sender_phone, message)
        return str(response)
    finally:
        _persist_conversation()   # Always save state back to DB, even on error
```

### The Booking Flow Step-By-Step

**MAIN_MENU → User types "1"**
```python
def handle_main_menu(user_input, phone, msg):
    if user_input == "1":
        clear_booking_context()    # Clean any previous booking data
        transition_to(ASK_NAME)    # Push MAIN_MENU to history stack
        msg.body(get_ask_name_prompt())
```

**ASK_NAME → User types their name**
```python
def handle_ask_name(user_input, phone, msg):
    session["b_name"] = user_input.strip()
    transition_to(ASK_DATE)
    msg.body(get_ask_date_prompt())
```
Books data is stored in `session.data` under the `b_` prefix (for "booking"). All booking context keys are: `b_name`, `b_date`, `b_slot_time`, `b_seats`, `b_table_number`, `b_is_combo`, etc.

**SELECT_SLOT → Show available slots**
```python
def get_slot_prompt_for_date(selected_date):
    from utils import get_cafe_date
    is_today = (str(selected_date) == str(get_cafe_date()))
    # filter_past=True removes time slots that have already started for today
    slots = db.get_available_slots(selected_date, filter_past=is_today)
    ...
    session["slot_options"] = slot_options   # Saves the options list for later validation
```

**ASK_SEATS → Validate guest count and slot capacity**
```python
def handle_ask_seats(user_input, phone, msg):
    seats_requested = int(user_input)
    # Check 1: Does the slot physically have remaining seats?
    if seats_requested > int(available):
        msg.body(f"⚠️ Only {available} seats available.")
        return
    # Check 2: Does the slot's max_guest cap allow this many more?
    allowed, remaining = db.check_slot_capacity(b_date, b_slot_time, seats_requested)
    if not allowed:
        msg.body(f"⚠️ This slot can only accommodate {remaining} more guests.")
        return
    # All good — proceed to table selection
    session["b_seats"] = seats_requested
    transition_to(SELECT_TABLE)
```

**SELECT_TABLE → Find available tables**
```python
def get_select_table_prompt():
    available_tables = db.get_available_tables(b_date, b_slot_time, b_seats)

    if available_tables:
        if len(available_tables) == 1:
            # Only one option — auto-assign it, no question needed
            session["b_table_number"] = available_tables[0]["table_number"]
            return "...", "AUTO"
        else:
            # Multiple options — let user pick
            session["b_table_options"] = available_tables
            return "...", "CHOOSE"

    # No single table works — try combining
    combo = db.get_combined_tables(b_date, b_slot_time, b_seats)
    if combo:
        session["b_combo_tables"] = combo
        session["b_is_combo"] = True
        return "...", "COMBO"

    # Nothing available at all
    return "...", "NO_TABLES"   # → goes to waitlist
```

**CONFIRM_BOOKING → Create booking in DB**
```python
def handle_confirm_booking(user_input, phone, msg):
    if user_input == "1":
        # Create the booking in DB (status = "Pending")
        success, message, booking_id = db.create_booking(...)

        if success:
            # Immediately create Razorpay payment link
            link_url, link_id = payment.create_payment_link(
                booking_id=booking_id, customer_name=..., phone=phone
            )
            db.set_booking_payment_link(booking_id, link_id)
            session["payment_link_id"] = link_id
            session["payment_booking_id"] = booking_id

            # Pause here — wait for payment
            transition_to(AWAITING_PAYMENT)
            msg.body(f"Pay here: {link_url}\n\nReply 'paid' once done.")
```

**AWAITING_PAYMENT → Polls Razorpay**
```python
def handle_awaiting_payment(user_input, phone, msg):
    if user_input.lower() in ["paid", "done", "check", "yes", "confirmed"]:
        status = payment.check_payment_link_status(link_id)
        if status == "paid":
            # Finalize — complete the booking confirmation message
            confirmed_message = build_booking_confirmed_message(booking_id, phone)
            clear_conversation_state()
            msg.body(f"Payment received ✅.\n\n{confirmed_message}")
        elif status in ("cancelled", "expired"):
            db.delete_pending_booking(booking_id)
            msg.body("Payment link expired. Please try again.")
        else:
            msg.body("Payment not yet received. Please complete payment.")
```

### Navigation History Stack
```python
def transition_to(new_state):
    history = session.get("state_history", [])
    history.append(current_state)   # Push current state onto stack
    session["state_history"] = history
    session["state"] = new_state

def go_back(phone, msg):
    history = session.get("state_history", [])
    previous = history.pop()
    session["state"] = previous
    send_state_prompt(previous, phone, msg)  # Re-render the previous screen
```
When a user types `*` (back), the bot pops the last state from the history stack and re-renders that screen — like a browser back button.

---

## 4. `payment.py` — Razorpay Integration

**Role**: The only file that talks to the Razorpay API. Completely self-contained.

### Client Initialization
```python
_KEY_ID     = os.getenv("RAZORPAY_KEY_ID", "")
_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")
PAYMENT_AMOUNT_PAISE = int(os.getenv("PAYMENT_AMOUNT_PAISE", "10000"))  # default ₹100

def _client() -> razorpay.Client:
    if not _KEY_ID or not _KEY_SECRET:
        raise RuntimeError("Razorpay keys not configured.")
    return razorpay.Client(auth=(_KEY_ID, _KEY_SECRET))
```
The client is created fresh for each request (not cached globally) which is the safest approach. The keys are read from `.env`. If missing, it raises a clear error so the calling code can gracefully fall back.

### `create_payment_link()`
```python
def create_payment_link(booking_id, customer_name, phone, amount_paise=None):
    clean_phone = phone.replace("whatsapp:", "").lstrip("+")
    payload = {
        "amount": amount_paise,        # Amount in paise (10000 = ₹100)
        "currency": "INR",
        "description": f"CoziCafe table booking #{booking_id}",
        "customer": {"name": customer_name, "contact": f"+{clean_phone}"},
        "notify": {"sms": False, "email": False},  # We send via WhatsApp ourselves
        "notes": {"booking_id": str(booking_id), "source": "cafebot"},
        "callback_url": "",            # We poll instead of using webhooks
    }
    response = client.payment_link.create(payload)
    link_url = response.get("short_url")
    link_id  = response.get("id")
    return link_url, link_id
```
- `notify: sms/email = False` — Razorpay will not send SMS or email. We handle notification via WhatsApp ourselves.
- `callback_url = ""` — No webhook. The system **polls** via `check_payment_link_status()` instead.
- Returns `(short_url, id)`. The `short_url` is the clickable payment link shown to the customer. The `id` is stored in the DB and used later to poll status.

### `check_payment_link_status()`
```python
def check_payment_link_status(link_id: str) -> str:
    response = client.payment_link.fetch(link_id)
    status = (response.get("status") or "").lower()
    if status == "paid":
        return "paid"
    if status in ("cancelled", "expired"):
        return status
    return "created"   # Anything else = not yet paid
```
Fetches the live status from Razorpay. Called by `bot.py` every time the customer says "paid". Returns one of four strings: `"paid"`, `"created"`, `"cancelled"`, or `"expired"`.

---

## 5. `notifier.py` — Twilio Message Sender

**Role**: The single function used by the entire app to send WhatsApp messages. Never calls Twilio directly from any other file.

```python
def send_whatsapp_message(to_phone: str, body: str) -> tuple[bool, str]:
    client = get_twilio_client()
    if not client:
        return False, "Twilio client not configured."

    # Skip pseudo-numbers used for walk-in bookings
    if "walkin:staff" in to_phone or not to_phone.startswith('whatsapp:'):
        return True, "Skipped pseudo-number"

    from_number = os.getenv("TWILIO_WHATSAPP_NUMBER")
    message = client.messages.create(body=body, from_=from_number, to=to_phone)
    return True, f"Sent successfully! (SID: {message.sid})"
```

**Key design decisions:**
- Walk-in bookings use a **fake phone number** (`walkin:staff`) in the database since they don't come via WhatsApp. The guard `if "walkin:staff" in to_phone` prevents sending a Twilio message to a non-real phone number.
- Returns `(bool, str)` — a success flag plus either a SID or error message. The caller (`admin.py`, `scheduler.py`) decides how to surface the result.
- All Twilio-specific formatting (the `whatsapp:` prefix on the sender and recipient numbers) is handled inside this one function.

---

## 6. `db.py` — The Database Layer

**Role**: The largest file (2000+ lines). All SQL queries go through this file. No other file writes raw SQL except for a few admin operations in `admin.py` via the raw `get_db_connection()` helper.

### Connection Handling
```python
DATABASE = "cafebot.db"

def get_db_connection():
    conn = sqlite3.connect(DATABASE, timeout=20)
    conn.row_factory = lambda cursor, row: dict(
        (col[0], row[idx]) for idx, col in enumerate(cursor.description)
    )
    _ensure_runtime_schema(conn)
    return conn
```
- `timeout=20` means SQLite will wait up to 20 seconds if another connection is writing. This prevents "database is locked" errors during concurrent requests.
- The `row_factory` converts every row from a plain tuple into a **Python dict**. So instead of `row[0]`, you write `row["phone"]`. This makes the code self-documenting.
- `_ensure_runtime_schema(conn)` is called on every connection to add any missing columns (like `seated_at` or `created_at`) without breaking existing data.

### `_ensure_runtime_schema()`
```python
def _ensure_runtime_schema(conn):
    global _RUNTIME_SCHEMA_READY
    if _RUNTIME_SCHEMA_READY:   # Only run once per server start
        return
    if not _has_column(conn, "bookings", "seated_at"):
        conn.execute("ALTER TABLE bookings ADD COLUMN seated_at TEXT")
    # Also backfill seated_at for existing 'Arrived' bookings
    conn.execute("""
        UPDATE bookings SET seated_at = COALESCE(updated_at, created_at)
        WHERE LOWER(TRIM(status)) = 'arrived' AND seated_at IS NULL
    """)
    conn.commit()
    _RUNTIME_SCHEMA_READY = True
```
This is a **safe migration** that runs automatically. If you deploy a new version of the app that needs a new column, it adds it without you needing to run a separate script. The global flag `_RUNTIME_SCHEMA_READY` ensures it only checks once (not on every request, which would be slow).

### Slot Availability: `get_available_slots()`
```python
def get_available_slots(date, filter_past=False):
    slots = conn.execute("SELECT * FROM time_slots WHERE date = ? ORDER BY slot_time ASC", (date,)).fetchall()
    bookings = conn.execute(
        f"SELECT slot_time, seats, combo_group FROM bookings WHERE date = ? AND status IN ({placeholders})", ...
    ).fetchall()

    result = []
    for slot in slots:
        # Skip slots that have already started (if viewing today)
        if filter_past:
            slot_start, _ = parse_slot_time(slot["slot_time"], date)
            if slot_start <= now:
                continue

        # Count booked guests for this slot (handles combo bookings correctly)
        slot_rows = [b for b in bookings if slots_equal(b["slot_time"], slot["slot_time"])]
        _, booked_guests = _aggregate_booking_rows(slot_rows, conn)

        remaining = max_guests - booked_guests
        if remaining <= 0:
            continue    # Slot is full — don't offer it

        slot_dict["available_seats"] = remaining
        result.append(slot_dict)
    return result
```
Why `_aggregate_booking_rows()`? Because a combo booking (two tables combined for one group) has **two rows** in the `bookings` table but should only count as **one booking** with **one guest count**. This function deduplicates by `combo_group` correctly.

### Table Assignment: `get_available_tables()`
```python
def get_available_tables(date, slot_time, guests):
    # Fetch all tables with enough capacity, smallest-first
    tables = conn.execute(
        "SELECT * FROM tables WHERE capacity >= ? ORDER BY capacity ASC, table_number ASC",
        (guests,)
    ).fetchall()

    # Find which tables are already booked for this slot
    bookings = conn.execute(
        f"SELECT table_number, slot_time FROM bookings WHERE date = ? AND status IN ({placeholders})", ...
    ).fetchall()
    booked_tables = {b["table_number"] for b in bookings if slots_equal(b["slot_time"], slot_time)}

    # Return only the tables that are NOT booked
    return [t for t in tables if t["table_number"] not in booked_tables]
```
This is a two-step query: first get candidate tables (capacity >= guests), then subtract the ones already taken. The `capacity >= guests` and `ORDER BY capacity ASC` together ensure the **smallest fitting table** is offered first, optimizing space.

### Table Combination: `get_combined_tables()`
```python
def get_combined_tables(date, slot_time, guests):
    all_available = [tables not already booked for slot]

    # Greedy algorithm: pick smallest tables first until total capacity >= guests
    combo = []
    total_capacity = 0
    for table in all_available:   # all_available is sorted capacity ASC
        combo.append(table)
        total_capacity += table["capacity"]
        if total_capacity >= guests:
            return combo   # Found a valid combination!

    return []  # Even all tables combined can't fit — truly full
```
This is a **greedy bin-packing** approach. Since tables are sorted smallest-first, the algorithm naturally minimizes the number of tables used.

### Booking Creation: `create_booking()`
```python
def create_booking(phone, name, date, slot_time, seats, table_number=None, ...):
    cursor.execute("BEGIN IMMEDIATE")   # Lock the DB for writing

    # 1. Check for duplicate booking (same phone + same slot)
    if any(slots_equal(row["slot_time"], slot_time) for row in duplicate_rows):
        return False, "You already have a booking for this slot.", None

    # 2. Check if the specific table was just taken by someone else (race condition)
    if any(slots_equal(row["slot_time"], slot_time) for row in conflict_rows):
        return False, "That table has just been booked.", None

    # 3. Final slot capacity check (in case someone else just booked)
    if current_booked + seats > max_guests:
        return False, f"Slot capacity exceeded.", None

    # 4. All checks passed — INSERT the booking with status = "Pending"
    cursor.execute("INSERT INTO bookings (...) VALUES (...)", ...)
    conn.commit()
    return True, "Booking successful.", booking_id
```
`BEGIN IMMEDIATE` is critical. SQLite's default is "deferred" locking, which can lead to race conditions where two users book the same table simultaneously. `IMMEDIATE` acquires a write lock upfront, making the check-then-insert operation **atomic**.

### Auto-Waitlist Allocation: `_auto_allocate_waitlist()`
This function is called automatically whenever a booking is cancelled:
```python
def _auto_allocate_waitlist(date, slot_time):
    # Get the OLDEST waiting person for this slot (FIFO = fair)
    next_in_line = conn.execute(
        "SELECT * FROM waitlist WHERE date=? AND slot_time=? AND status='Waiting' ORDER BY created_at ASC LIMIT 1",
        (date, slot_time)
    ).fetchone()

    if not next_in_line:
        return   # Nobody waiting

    # Re-check if a table is now available for them
    tables = get_available_tables(date, slot_time, next_in_line["guests"])
    if not tables:
        return   # Still no table — do nothing

    # Assign the smallest fitting table
    table = tables[0]

    # Create the booking and update waitlist status
    conn.execute("INSERT INTO bookings (...) VALUES (...)")
    conn.execute("UPDATE waitlist SET status='Allocated' WHERE id=?", (next_in_line["id"],))
    conn.commit()

    # Notify them via WhatsApp (after commit so message is only sent for real allocations)
    send_whatsapp_message(next_in_line["phone"], "✅ Great news! A table is available...")
```
The `ORDER BY created_at ASC` implements **FIFO fairness** — the person who waited longest gets priority.

---

## 7. `utils.py` — Shared Utility Functions

**Role**: Pure helper functions with no side effects. Used by `bot.py`, `db.py`, `scheduler.py`, `staff.py`, and more.

### Timezone Handling
```python
CAFE_TIMEZONE = pytz.timezone('Asia/Kolkata')

def get_cafe_time():
    return datetime.now(pytz.utc).astimezone(CAFE_TIMEZONE)

def get_cafe_date():
    return get_cafe_time().date()
```
All time comparisons in the app (reminder sending, no-show detection, slot filtering) use these functions to work in IST. This prevents confusion when the server runs in UTC (common on cloud servers).

### Slot String Parsing: `parse_slot_time()`
```python
def parse_slot_time(slot_str, base_date=None):
    # Input: "10:00 AM - 11:00 AM"
    # Splits on " - " or " – " (handles both dash types)
    parts = _SLOT_SPLIT_RE.split(slot_str.strip())
    start_time = _parse_time_part(parts[0])   # → time(10, 0)
    end_time = _parse_time_part(parts[1])     # → time(11, 0)

    if base_date:
        # Converts to timezone-aware datetime
        start_dt = CAFE_TIMEZONE.localize(datetime.combine(base_date, start_time))
        return start_dt, end_dt

    return start_time, end_time   # Just time objects if no date given
```
The scheduler needs full `datetime` objects to compare with `now` (uses `base_date`). The bot just needs ordering (uses raw `time` objects). This one function handles both cases.

### Slot Normalization: `normalize_slot_label()`
```python
def normalize_slot_label(slot_str):
    # Input can be: "10:00AM-11:00AM", "10 AM - 11 AM", "10:00 AM - 11:00 AM"
    start_time, end_time = parse_slot_time(slot_str)
    start_label = t.strftime("%I:%M %p").lstrip("0")  # "10:00 AM"
    return f"{start_label} - {end_label}"              # "10:00 AM - 11:00 AM"
```
Slot strings in the database can have various formats (entered by admins or generated). This function always produces a **canonical display format** for templates.

### Slot Equality: `slots_equal()`
```python
def slots_equal(slot_a, slot_b):
    a_start, a_end = parse_slot_time(slot_a)
    b_start, b_end = parse_slot_time(slot_b)
    if a_start and b_start:
        return a_start == b_start   # Compare by parsed time, not string
    return normalize_slot_label(slot_a).lower() == normalize_slot_label(slot_b).lower()
```
"10:00 AM - 11:00 AM" and "10 AM - 11 AM" are the **same slot**. String comparison would fail; this function correctly identifies them as equal by comparing parsed `time` objects.

---

## 8. `scheduler.py` — Background Jobs

**Role**: Two job functions that run on a timer inside `app.py`'s APScheduler. They open their own SQLite connection directly (don't use Flask's request context).

### Job 1: `check_and_send_reminders()`
```python
def check_and_send_reminders():
    now = get_cafe_time()
    reminder_window = now + timedelta(minutes=10)

    # Fetch all active bookings that haven't had a reminder sent yet
    bookings = cursor.execute(
        "SELECT * FROM bookings WHERE status IN (?) AND reminder_sent = 0", ...
    ).fetchall()

    for booking in bookings:
        # Parse the booking's slot start time into a real datetime
        booking_start, _ = parse_slot_time(slot_time_str, booking_date_str)

        # Only send if the booking starts within the next 10 minutes
        if now <= booking_start <= reminder_window:
            send_whatsapp_message(booking["phone"], f"⏰ Reminder! Your table booking is at {display_slot}...")

            # Mark as sent so we never send twice
            cursor.execute("UPDATE bookings SET reminder_sent = 1 WHERE id = ?", (booking["id"],))
            conn.commit()
```
The `now <= booking_start <= reminder_window` check is the key. It only hits when:
- Current time has not yet passed the booking start (it's still upcoming).
- AND the booking is within 10 minutes.

The `reminder_sent = 1` flag prevents duplicate messages even though this job runs every 60 seconds.

### Job 2: `check_and_auto_noshow()`
```python
NOSHOW_GRACE_MINUTES = 20

def check_and_auto_noshow():
    # Only look at today's bookings that are still "Pending" or "Confirmed"
    rows = cursor.execute(
        "SELECT * FROM bookings WHERE date = ? AND status IN ('Pending', 'Confirmed')", (today_str,)
    ).fetchall()

    for booking in rows:
        booking_start, _ = parse_slot_time(slot_time_str, today_str)
        cutoff = booking_start + timedelta(minutes=NOSHOW_GRACE_MINUTES)

        # If current time is past the cutoff → no-show
        if now >= cutoff:
            cursor.execute("UPDATE bookings SET status = 'No-show' WHERE id = ?", (booking["id"],))
            # Free the table physically
            cursor.execute("UPDATE tables SET status = 'Vacant' WHERE table_number = ?", (booking["table_number"],))
            conn.commit()

            # Notify the customer (if still within Twilio 24hr window)
            send_whatsapp_message(booking["phone"], "⚠️ Your booking has been marked as No-show...")
```
The `cutoff = booking_start + 20 minutes` logic means a customer has a 20-minute grace window after their slot starts. After that, the table is automatically freed and the next person on the waitlist can get it.

---

## 9. `admin.py` — Admin Web Dashboard

**Role**: All routes behind `/admin/` (owner-level access). Handles CRUD for bookings, tables, time slots, reports analytics, and staff account management.

### Blueprint Setup
```python
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')
```
All routes in this file are automatically prefixed with `/admin/`.

### Dashboard: `/admin/dashboard`
```python
@admin_bp.route('/dashboard')
@admin_required
def dashboard():
    today_date = str(get_cafe_date())
    metrics = db.get_dashboard_metrics(today_date)   # Total bookings, revenue, waitlist count
    slot_chart_data = db.get_bookings_by_slot_today(today_date)   # For the bar chart
    weekly_trend = db.get_weekly_booking_trend()                  # For the line chart
    return render_template('dashboard.html', metrics=metrics, slot_chart_data=slot_chart_data, ...)
```
The `slot_chart_data` is a list like `[{"slot": "10:00 AM", "bookings": 5}, ...]` which gets directly serialized into a Chart.js bar chart's `data.labels` and `data.datasets` in the template.

### Booking Actions: `/admin/booking_action/<id>`
```python
@admin_bp.route('/booking_action/<int:booking_id>', methods=['POST'])
@admin_required
def booking_action(booking_id):
    action = request.form.get('action')

    if action == 'cancel':
        success, message = db.admin_cancel_booking(booking_id)
        # If cancelled, attempt to notify customer via WhatsApp
        if success and booking['phone'] and db.get_messageability(booking['phone']):
            send_whatsapp_message(booking['phone'], "❌ Your booking has been cancelled.")

    elif action in ['Confirmed', 'Arrived', 'Completed', 'No-show']:
        db.update_booking_status(booking_id, action)
        # If Confirmed, send a WhatsApp confirmation to the customer
        if action == 'Confirmed':
            send_whatsapp_message(booking['phone'], "✅ Your booking is confirmed!")
```
`db.get_messageability(phone)` checks if the customer messaged within the last 24 hours. This is a Twilio trial account constraint — you can only send outbound messages to users who initiated a conversation within that window.

### Slot Management: `/admin/slots`
```python
@admin_bp.route('/slots', methods=['GET', 'POST'])
@admin_required
def manage_slots():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'delete':
            db.delete_time_slot(slot_id)
        elif action == 'delete_day':
            db.delete_slots_for_date(target_date)
        elif action == 'clear_week':
            db.clear_all_future_slots()
        return redirect(url_for('admin.manage_slots'))

    slots = db.get_slots_with_bookings()   # Slots with computed fill %
    cfg = db.load_slot_config()            # The slot schedule template
    return render_template('slots.html', slots=slots, schedule=cfg['schedule'], ...)
```
The key insight: **slot rows in the database are what the bot shows to customers**. If an admin deletes a slot, the bot immediately stops offering it. If they add one, it appears in the next customer request.

### Staff Management: `/admin/staff_management`
Allows admin to add/remove staff user accounts. Staff users can log in but can only access `/staff/*` routes. The `role = 'staff'` column in the `users` table controls this.

---

## 10. `staff.py` — Staff POS Dashboard

**Role**: Routes for the front-of-house crew at `/staff/*`. Provides a live floor map, walk-in seating, check-in, and checkout.

### Live Table API: `/staff/api/live_tables`
This is the most technically complex route in `staff.py`:
```python
@staff_bp.route('/api/live_tables')
@staff_required
def api_live_tables():
    now = get_cafe_time()
    bookings = db.get_today_bookings(today_date)
    tables_db = db.get_all_tables()

    for t_row in tables_db:
        # For each table, find its active booking (highest-priority status)
        active_booking = None
        for b in bookings:
            if b['table_number'] != t['table_number']:
                continue
            status = normalize_booking_status(b.get('status'))
            if status in active_statuses:
                # Prefer "Arrived" status over "Confirmed" or "Pending"
                if not active_booking or status == 'Arrived':
                    active_booking = dict(b)

        # Compute elapsed seated time for occupied tables
        if active_booking and status == 'Arrived':
            elapsed_minutes = db.get_seated_elapsed_minutes(active_booking.get('seated_at'), now=now)

        # Compute "Reserved (Impending)" — a table is vacant but a booking starts within 60 min
        if display_status == 'Vacant':
            for b in bookings:
                b_dt, _ = parse_slot_time(b['slot_time'], now.date())
                if b_dt and now <= b_dt <= now + timedelta(minutes=60):
                    display_status = 'Reserved (Impending)'

    return jsonify({"tables": result})   # Returned as JSON every 15 seconds
```
The template's Alpine.js polls this endpoint every 15 seconds and re-renders the table grid. This gives the dashboard a **real-time feel** without WebSockets.

### Walk-In Seating: `/staff/action`
```python
@staff_bp.route('/action', methods=['POST'])
@staff_required
def action():
    conn.execute("BEGIN IMMEDIATE")   # Lock DB to prevent double-seating
    table = conn.execute("SELECT ... FROM tables WHERE id = ?", (table_id,)).fetchone()

    if table['status'] != 'Vacant':
        return "Table is not vacant."

    # Create an instant booking in 'Arrived' state (already seated)
    conn.execute(
        "INSERT INTO bookings (phone, name, date, slot_time, seats, table_number, status, seated_at) VALUES (...)",
        ('walkin:staff', 'Walk-In Guest', now.date(), slot_label, guests, table_number, 'Arrived', now.isoformat())
    )
    conn.execute("UPDATE tables SET status = 'Occupied' WHERE id = ?", (table_id,))
    conn.commit()
```
Walk-ins bypass the WhatsApp flow entirely. They use the phone number `walkin:staff` (a fake value the app knows to skip when trying to send WhatsApp messages).

---

## 11. `ops.py` — Operations API Layer

**Role**: A separate set of AJAX endpoints used by the floor/operations views. Returns JSON for dynamic UI updates. This is where table status changes, customer check-outs, and quick-seat actions land.

Key routes include:
- `/ops/api/tables/status` → JSON table grid for the floor view.
- `/ops/action/seat_booking` → Mark a booking as "Arrived" with timestamp.
- `/ops/action/checkout` → Mark "Completed", move table to "Needs Cleaning", schedule 5-min auto-release timer.
- `/ops/customers` → Customer history and contact data.

The separation between `staff.py` (which renders HTML pages) and `ops.py` (which returns JSON) keeps the codebase organized. Staff pages load HTML once; all dynamic updates after that come from `ops.py` API calls.

---

## 12. `init_db.py` — Fresh Database Setup

**Role**: Run once to create the SQLite database from scratch. Seeds default data.

```python
python init_db.py
```

Creates all tables:
- `users` — Admin and staff accounts
- `tables` — Physical table inventory (T1-T6 with capacities and locations)
- `time_slots` — Available booking slots per date
- `bookings` — All reservations
- `waitlist` — Waitlist entries
- `conversations` — WhatsApp bot state storage per phone number
- `customers` — Tracks last WhatsApp interaction per phone (for 24hr Twilio window)

Seeds:
- One default `admin` user (username: `admin`, password: `admin123`)
- Six default tables: two 2-seaters, two 4-seaters, one 6-seater, one 8-seater

---

## 13. How All Files Connect

```
User on WhatsApp
      │
      ▼
[Twilio] ──POST──► /webhook
                      │
                    bot.py
                   │      │
            db.py       payment.py
                         │
                       Razorpay API
                   │
               notifier.py
                   │
             Twilio REST API

Staff at counter
      │
      ▼
Browser ──GET/POST──► /staff/*
                          │
                       staff.py
                       ops.py
                          │
                        db.py

Cafe Owner
      │
      ▼
Browser ──GET/POST──► /admin/*
                          │
                       admin.py
                          │
                        db.py

Background (every 60s)
      │
      ▼
 scheduler.py
   │        │
db.py    notifier.py
```

### The Flow for a Single Booking
1. Customer sends "1" on WhatsApp → **Twilio** → **bot.py `/webhook`**
2. **bot.py** loads conversation state from **db.py** (`conversations` table)
3. Bot walks customer through name → date → slot → guests → table
4. **bot.py** calls **db.py** `create_booking()` → `Pending` status in `bookings`
5. **bot.py** calls **payment.py** `create_payment_link()` → **Razorpay API**
6. Customer pays → replies "paid" → **bot.py** calls **payment.py** `check_payment_link_status()`
7. Razorpay confirms → booking finalized → confirmation sent via **notifier.py**
8. **scheduler.py** runs every 60s → 10 min before slot → **notifier.py** sends reminder
9. If no-show: **scheduler.py** marks cancelled → frees table → **db.py** auto-allocates waitlist
10. Staff sees live table status via **staff.py** → Alpine.js polls `/api/live_tables` every 15s
