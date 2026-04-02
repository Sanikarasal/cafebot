# CafeBot Technical Demo Guide

This file is a teacher-facing explanation of the project based on the current source code in this repository. I used the code as the source of truth, not the older README files.

## 1. Project Architecture

### Tech stack

- Backend: Python + Flask
- Database: SQLite (`cafebot.db`)
- Frontend: Server-rendered Jinja templates, Tailwind CSS, Alpine.js, and some fetch-based AJAX
- Messaging: Twilio WhatsApp webhook
- Payments: Razorpay payment links
- Background jobs: APScheduler

### High-level architecture

```text
Teacher/Admin/Staff browser
    -> Flask routes in app.py + blueprints
    -> business logic in admin.py / auth.py / staff.py / ops.py / bot.py
    -> database helpers in db.py
    -> SQLite database cafebot.db

WhatsApp customer
    -> Twilio webhook /webhook
    -> bot.py state machine
    -> db.py booking + waitlist + payment storage
    -> Razorpay payment link
    -> notifier.py for WhatsApp notifications
```

### How frontend communicates with backend and database

- Most admin/staff pages are rendered on the server using Jinja templates.
- Interactive screens use `fetch()` or standard HTML forms to call Flask routes.
- Flask route handlers call `db.py` functions.
- `db.py` opens SQLite connections, runs SQL, and returns dictionaries/rows.
- Some pages poll JSON APIs every 15 seconds for live updates:
  - `/admin/api/dashboard_data`
  - `/staff/api/live_tables`
  - `/admin/slots/api/stats`
- The WhatsApp side does not use browser UI. Its "frontend" is the Twilio WhatsApp conversation handled in `bot.py`.

## 2. Demo Flow For Your Teacher

Use this as the order for your live demo.

### Screen 1: Login

- UI file: `templates/login.html`
- Backend route: `auth.py -> login()`
- Data flow:
  - User submits username/password.
  - `db.get_user_by_username()` fetches the user.
  - `check_password_hash()` validates password.
  - Flask session stores `logged_in`, `username`, `user_role`.
- Demo point:
  - Show that admin users go to `/admin/dashboard` and staff users go to `/staff/dashboard`.

### Screen 2: Admin Dashboard

- UI file: `templates/dashboard.html`
- Backend route: `admin.py -> dashboard()`
- Background API: `admin.py -> api_dashboard_data()`
- Data received:
  - total tables
  - today's bookings
  - guests today
  - available tables
  - waitlist count
  - revenue estimate
  - recent bookings
- DB functions:
  - `db.get_dashboard_metrics()`
  - `db.get_recent_bookings()`
  - `db.get_bookings_by_slot_today()`
  - `db.get_weekly_booking_trend()`
- Demo point:
  - Mention the page auto-refreshes every 15 seconds using Alpine.js + `fetch()`.

### Screen 3: All Bookings

- UI file: `templates/bookings.html`
- Backend routes:
  - `admin.py -> all_bookings()`
  - `admin.py -> booking_action(booking_id)`
- Data sent:
  - Form post with `action=Confirmed`, `Arrived`, `Completed`, `No-show`, or `cancel`.
- DB logic:
  - `db.get_all_bookings()`
  - `db.update_booking_status()`
  - `db.admin_cancel_booking()`
- Background side effects:
  - If customer is still "messageable", `notifier.send_whatsapp_message()` sends confirmation/cancellation updates.
- Demo point:
  - Show filters, then confirm or cancel a booking and explain that table status changes in the database too.

### Screen 4: Time Slot Management

- UI file: `templates/slots.html`
- Backend routes:
  - `admin.py -> manage_slots()`
  - `admin.py -> regenerate_slots()`
  - `admin.py -> update_slot_schedule()`
  - `admin.py -> update_slot_capacity(slot_id)`
  - `admin.py -> slot_stats_api()`
- Data sent:
  - Schedule list
  - capacity
  - days ahead
  - inline slot capacity updates
- DB/config logic:
  - `db.load_slot_config()`
  - `db.save_slot_config()`
  - `db.auto_generate_slots()`
  - `db.update_slot_capacity()`
  - `db.get_slots_with_bookings()`
  - `db.get_slot_booking_stats()`
- Demo point:
  - Show that slots are generated ahead of time and can be edited without touching code.

### Screen 5: Table Management

- Admin UI file: `templates/tables.html`
- Admin backend route: `admin.py -> manage_tables()`
- Ops UI file: `templates/tables_ops.html`
- Ops backend route: `ops.py -> tables_page()`
- Data sent:
  - Add/edit/delete table details
  - In ops view: block/unblock/merge tables
- DB activity:
  - direct SQL through `db.get_db_connection()`
  - `db.update_table_status()`
- Demo point:
  - Explain that admin view is clean CRUD management, while ops view is more operational and includes merge/block actions.

### Screen 6: Staff POS Dashboard

- UI file: `templates/staff_dashboard.html`
- Backend routes:
  - `staff.py -> dashboard()`
  - `staff.py -> api_live_tables()`
  - `staff.py -> action()`
  - `staff.py -> checkin()`
  - `staff.py -> booking_action()`
  - `staff.py -> force_release()`
- Data received:
  - live table list
  - booking on each table
  - next booking warning
  - walk-in eligibility
- DB logic:
  - `db.get_today_bookings()`
  - `db.get_all_tables()`
  - `db.update_booking_status()`
  - `db.force_release_table()`
- Demo point:
  - This is the strongest "real-time operations" screen.
  - Show:
    - seat walk-in
    - check in a reserved guest
    - checkout a table
    - auto-cleaning state before release

### Screen 7: Floor Board / Ops View

- UI file: `templates/floor.html`
- Backend route: `ops.py -> floor()`
- AJAX routes:
  - `/api/seat_guest`
  - `/api/checkout`
  - `/api/table/status`
  - `/api/mark_clean`
  - `/api/waitlist/add`
  - `/api/waitlist/assign`
  - `/api/booking/status`
  - `/api/table/suggest`
- Data shown:
  - table cards
  - upcoming reservations
  - waitlist
  - quick booking modal
- Demo point:
  - Show how a walk-in can be seated quickly and how waitlist entries can be assigned to newly free tables.

### Screen 8: Bookings Ops / Waitlist / Customers

- UI files:
  - `templates/bookings_ops.html`
  - `templates/waitlist_ops.html`
  - `templates/customers.html`
- Backend routes:
  - `ops.py -> bookings_page()`
  - `ops.py -> waitlist_page()`
  - `ops.py -> customers_page()`
- Data flow:
  - bookings page can edit reservation date/time/table using `/api/booking/update`
  - waitlist page assigns a table using `/api/waitlist/assign`
  - customers page aggregates booking history with `db.get_customer_summaries()`
- Demo point:
  - Use these screens to show operational flexibility and customer analytics.

### Screen 9: WhatsApp Customer Booking Flow

- UI handler: no HTML screen; customer interacts in WhatsApp
- Backend route: `bot.py -> webhook()`
- Core states:
  - `MAIN_MENU`
  - `ASK_NAME`
  - `ASK_DATE`
  - `ASK_CUSTOM_DATE`
  - `SELECT_SLOT`
  - `ASK_SEATS`
  - `SELECT_TABLE`
  - `CONFIRM_BOOKING`
  - `ASK_WAITLIST`
  - `AWAITING_PAYMENT`
- Data flow:
  - Twilio sends message body + phone number to Flask webhook.
  - Bot loads conversation state from DB.
  - User picks date, slot, seats, and table.
  - `db.create_booking()` or `db.create_combo_booking()` writes booking.
  - `payment.create_payment_link()` creates Razorpay link.
  - User replies `paid`.
  - `payment.check_payment_link_status()` confirms payment.
- Demo point:
  - This is where the project becomes more than a normal CRUD app: it has a conversational booking engine with persistent state.

### Screen 10: Background automation

- Files:
  - `app.py`
  - `scheduler.py`
  - `db.py`
- Jobs:
  - send reminders every 60 seconds
  - auto-mark no-shows every 60 seconds
  - auto-generate slots every 30 minutes
- Demo point:
  - Mention that the app keeps running operational rules even when no one is clicking around.

## 3. Robustness, Edge Cases, and Good Engineering Points

These are strong talking points for your teacher.

### Where the app is robust

- Role protection:
  - `login_required`, `admin_required`, and `staff_required` block unauthorized access.
- Duplicate booking prevention:
  - `db.create_booking()` and `db.create_combo_booking()` use `BEGIN IMMEDIATE` and same-phone same-slot checks.
- Table conflict prevention:
  - booking logic checks if a table was already taken for the same slot.
- Slot capacity protection:
  - `db.check_slot_capacity()` and capacity checks inside booking/seating functions stop overbooking.
- Waitlist fairness:
  - `_auto_allocate_waitlist()` processes pending entries FIFO by `created_at`.
- Payment safety:
  - if payment-link creation fails, pending booking is deleted with `db.delete_pending_booking()`.
- Conversation persistence:
  - WhatsApp state is saved in the `conversations` table, so the flow can resume.
- Cleaning automation:
  - after checkout, table goes to `Needs Cleaning`, then auto-releases later.
- No-show automation:
  - scheduler marks stale `Pending`/`Confirmed` bookings as `No-show` after grace period.
- WhatsApp messaging safety:
  - app checks whether the Twilio 24-hour session is still valid before sending updates.
- Schedule validation:
  - slot schedule update validates capacity, days ahead, and time-string format.
- API error responses:
  - ops/staff APIs return proper `400`/`404` JSON when payloads are missing or invalid.

### Honest limitations / caveats to mention if asked

- `auth.py` forgot-password OTP flow is a demo stub, not a real OTP service.
- The OTP reset path references `generate_password_hash()` but does not import it, so that branch is likely incomplete.
- `staff_dashboard.html` has a dummy "Notify" button that currently shows an alert instead of sending a real message.
- Several ops templates use Bootstrap-style classes and `bootstrap.Modal(...)`, but `ops_base.html` does not load Bootstrap CSS/JS, so those legacy screens may depend on earlier styling assumptions.
- There are no automated tests in this repository right now; robustness comes mostly from validation, transactions, and runtime checks.

## 4. File-By-File Breakdown

### Core Flask entry and backend modules

#### `app.py`

- Purpose: Flask app bootstrapper and blueprint registration.
- Logic:
  - creates the Flask app
  - loads environment variables
  - registers `admin`, `bot`, `auth`, `staff`, and `ops` blueprints
  - auto-generates slots on startup
  - starts background schedulers for reminders, no-shows, and slot generation
- Key snippets:
  - `app.register_blueprint(...)`
  - `db.auto_generate_slots()`
  - `BackgroundScheduler().add_job(...)`

#### `auth.py`

- Purpose: login/logout and role-based access control.
- Logic:
  - decorators check session and redirect based on role
  - login validates password hash and sets Flask session data
  - forgot-password is a demo recovery flow with a dummy OTP modal
  - logout clears session keys
- Key snippets:
  - `login_required`, `admin_required`, `staff_required`
  - `check_password_hash(...)`
  - `session['user_role'] = user['role']`

#### `admin.py`

- Purpose: admin-side business logic and admin routes.
- Logic:
  - dashboard gathers metrics, recent bookings, and chart data
  - bookings page allows state transitions and customer notification
  - slots page manages schedule config, slot CRUD, export, and stats API
  - tables page supports add/edit/delete
  - reports page aggregates analytics for a date range
  - staff management creates, deletes, and resets staff users
  - settings page changes the admin password
- Why it matters:
  - This file acts like the main admin controller for the entire product.
- Key snippets:
  - `_augment_booking(...)`
  - `booking_action(...)`
  - `update_slot_schedule(...)`
  - `reports()`
  - `manage_staff()`

#### `staff.py`

- Purpose: fast staff POS behavior focused on table turnover.
- Logic:
  - `dashboard()` renders the live shell
  - `api_live_tables()` calculates table state, active booking, next booking, and walk-in eligibility
  - `action()` seats a walk-in with transaction safety
  - `checkin()`, `booking_action()`, and `force_release()` update operational status
- Algorithm highlights:
  - determines whether a reserved table can still take a short-stay walk-in using time-gap rules
  - calculates elapsed service time and "up next" warnings
- Key snippets:
  - `WALKIN_LOCKOUT_MINS = 45`
  - `ARRIVED_ENABLE_MINS = 30`
  - `_build_next_booking(...)`
  - `api_live_tables()`

#### `ops.py`

- Purpose: operations dashboard routes and JSON APIs for floor management.
- Logic:
  - builds floor cards from tables + bookings + waitlist
  - exposes API endpoints to seat guests, checkout, clean tables, assign waitlist entries, and update bookings
  - includes a separate ops table-management screen
- Algorithm highlights:
  - `_build_table_cards(...)` maps bookings to physical tables
  - `_get_upcoming_reservations(...)` builds the next-2-hours panel
- Key snippets:
  - `api_seat_guest()`
  - `api_waitlist_assign()`
  - `api_booking_update()`

#### `bot.py`

- Purpose: WhatsApp booking engine and conversation state machine.
- Logic:
  - defines booking conversation states
  - stores session state in DB-backed conversation storage
  - validates date, slot, seats, and table selection
  - handles combo tables if one table is not enough
  - creates payment link and waits for payment confirmation
  - supports booking lookup and cancellation
- Algorithm highlights:
  - state machine dispatch via `STATE_HANDLERS`
  - slot lookup -> seat validation -> table choice -> payment -> confirmation
  - waitlist offer if no table is available
- Key snippets:
  - `ConversationStore`
  - `transition_to(...)`
  - `get_select_table_prompt()`
  - `handle_confirm_booking(...)`
  - `handle_awaiting_payment(...)`
  - `webhook()`

#### `db.py`

- Purpose: central data-access layer and most business rules.
- Logic:
  - opens SQLite connections
  - backfills runtime schema if needed
  - manages conversations, users, slots, tables, bookings, waitlist, reporting, and status changes
  - contains concurrency-safe booking creation and waitlist auto-allocation
- Algorithm highlights:
  - slot normalization so different time-string formats still match
  - combo-booking seat distribution across multiple tables
  - FIFO waitlist auto-allocation inside a transaction
  - automatic table-release scheduling after cleaning
- Most important functions:
  - `get_available_slots()`
  - `get_available_tables()`
  - `get_combined_tables()`
  - `create_booking()`
  - `create_combo_booking()`
  - `atomic_quick_seat()`
  - `cancel_booking_by_id()`
  - `_auto_allocate_waitlist()`
  - `update_booking_status()`
  - `auto_generate_slots()`
- Why this file is the heart of the project:
  - almost all major app rules eventually pass through here.

#### `utils.py`

- Purpose: shared time, slot, and status helper functions.
- Logic:
  - normalizes status strings
  - calculates cafe-local time in `Asia/Kolkata`
  - parses human-readable slot strings into comparable time values
  - sorts and compares slot labels safely
- Key snippets:
  - `normalize_booking_status(...)`
  - `get_cafe_time()`
  - `parse_slot_time(...)`
  - `normalize_slot_label(...)`
  - `slots_equal(...)`

#### `payment.py`

- Purpose: Razorpay payment-link integration.
- Logic:
  - loads keys from environment
  - creates a payment link using booking ID as reference
  - polls payment-link status instead of using a callback webhook
- Key snippets:
  - `_client()`
  - `create_payment_link(...)`
  - `check_payment_link_status(...)`

#### `notifier.py`

- Purpose: send WhatsApp notifications using Twilio REST API.
- Logic:
  - creates Twilio client if credentials exist
  - skips pseudo-numbers like walk-in entries
  - returns success/error tuples so callers can show warnings instead of crashing
- Key snippets:
  - `get_twilio_client()`
  - `send_whatsapp_message(...)`

#### `scheduler.py`

- Purpose: background operational jobs.
- Logic:
  - reminder job scans bookings and sends messages 10 minutes before slot start
  - no-show job marks stale bookings and frees tables
- Key snippets:
  - `check_and_send_reminders()`
  - `check_and_auto_noshow()`
  - `NOSHOW_GRACE_MINUTES = 20`

#### `init_db.py`

- Purpose: creates a fresh database from scratch.
- Logic:
  - deletes old DB
  - creates core tables
  - seeds default admin/staff users
  - seeds initial cafe tables and example slots
- Key snippets:
  - `CREATE TABLE ...`
  - default users `admin/admin123` and `staff/staff123`

### HTML templates

#### `templates/base.html`

- Purpose: shared admin layout.
- Logic:
  - defines sidebar, header, flash toasts, and admin navigation
  - loads Tailwind, Alpine.js, and icon fonts
- Key snippets:
  - sidebar role checks using `session.get('user_role')`
  - flash-message toast container

#### `templates/ops_base.html`

- Purpose: shared ops/staff layout.
- Logic:
  - separate navigation for floor, bookings, waitlist, customers, and tables
  - used by ops-oriented pages
- Key snippets:
  - ops nav links
  - shared flash toasts

#### `templates/login.html`

- Purpose: login form UI.
- Logic:
  - posts to `/login`
  - supports autofill after the password-reset flow
  - password visibility toggle via Alpine.js
- Key snippets:
  - `value="{{ autofill_usr }}"`
  - Alpine `showPass`

#### `templates/forgot_password.html`

- Purpose: demo password-recovery UI.
- Logic:
  - shows a username form
  - opens a dummy OTP modal before submit
- Key snippets:
  - `x-data="{ showOtpModal: false }"`
  - OTP modal form fields

#### `templates/dashboard.html`

- Purpose: admin dashboard UI.
- Logic:
  - renders metrics cards
  - lists recent bookings
  - polls `/admin/api/dashboard_data`
- Key snippets:
  - `x-data="adminDashboard()"`
  - `fetch('/admin/api/dashboard_data')`

#### `templates/bookings.html`

- Purpose: full admin booking management screen.
- Logic:
  - shows booking table with status/date/search filters
  - action forms post to `/admin/booking_action/<id>`
- Key snippets:
  - client-side `filterTable()`
  - booking action buttons

#### `templates/tables.html`

- Purpose: admin CRUD UI for tables.
- Logic:
  - add form on the left
  - editable table list on the right
  - uses Alpine modal for inline editing
- Key snippets:
  - hidden `action=add/edit/delete`
  - `x-data="{ editModalOpen: false }"`

#### `templates/slots.html`

- Purpose: advanced admin slot-management page.
- Logic:
  - groups slots by date
  - supports filter chips, search, inline capacity edit, schedule modal, CSV export, and insight stats
  - polls slot stats for trend badges
- Key snippets:
  - `saveCapacity(slotId)`
  - `fetch('{{ url_for("admin.slot_stats_api") }}')`
  - schedule modal form posting to `admin.update_slot_schedule`

#### `templates/reports.html`

- Purpose: report visualization page.
- Logic:
  - filters by date range
  - prints metrics, peak slots, most-used tables, and daily breakdown
- Key snippets:
  - GET filter form with `start` and `end`
  - printable layout CSS

#### `templates/staff_management.html`

- Purpose: admin staff-account management UI.
- Logic:
  - add staff form
  - reset-password modal
  - deactivate action
- Key snippets:
  - hidden `action=add/delete/reset`
  - reset-password modal

#### `templates/admin_settings.html`

- Purpose: admin profile/settings screen.
- Logic:
  - shows account summary
  - changes password with current/new/confirm fields
  - exposes sign-out action
- Key snippets:
  - hidden `action=change_password`
  - Alpine visibility toggles for password fields

#### `templates/staff_dashboard.html`

- Purpose: live staff dashboard.
- Logic:
  - polls `/staff/api/live_tables`
  - shows table state and context-aware actions
  - includes walk-in seating modal
- Key snippets:
  - `liveTables()`
  - `submitAction(...)`
  - `fetch('/staff/api/live_tables')`

#### `templates/floor.html`

- Purpose: broader operations floor-board UI.
- Logic:
  - shows live table cards, upcoming reservations, waitlist, and quick-booking modal
  - uses JSON APIs for all actions
- Key snippets:
  - `postJson(...)`
  - `/api/seat_guest`
  - `/api/waitlist/add`
  - `/api/waitlist/assign`

#### `templates/bookings_ops.html`

- Purpose: operations booking list.
- Logic:
  - seat, cancel, no-show, and edit bookings via JSON APIs
  - edit modal updates date, slot, seats, and table
- Key snippets:
  - `/api/booking/update`
  - modal population from `data-*` attributes

#### `templates/waitlist_ops.html`

- Purpose: operations waitlist screen.
- Logic:
  - lists pending waitlist entries
  - prompts for a table number and assigns entry through API
- Key snippets:
  - `/api/waitlist/assign`

#### `templates/customers.html`

- Purpose: customer summary/reporting page.
- Logic:
  - renders aggregated booking history per phone number
- Key snippets:
  - `visit_count`
  - `avg_party_size`
  - empty-state row

#### `templates/tables_ops.html`

- Purpose: operations-side table configuration screen.
- Logic:
  - supports add/edit/delete/block/unblock/merge
  - more operational than the admin CRUD version
- Key snippets:
  - hidden `action=merge`
  - per-row block/unblock buttons

### Migration and maintenance scripts

#### `migrate_tables.py`

- Purpose: older migration to add `table_number` and create/seed `tables`.
- Logic: safe, re-runnable schema patch.
- Key snippets: `ALTER TABLE bookings ADD COLUMN table_number`.

#### `migrate_soft_cancel.py`

- Purpose: older migration adding booking `status`.
- Logic: checks `PRAGMA table_info(bookings)` before altering.
- Key snippets: default status `'active'`.

#### `migrate_v2.py`

- Purpose: v2 schema upgrade.
- Logic:
  - creates `admins` and `waitlist`
  - adds `combo_group`, `reminder_sent`, `max_guests`, and `table_number`
- Key snippets:
  - `CREATE TABLE IF NOT EXISTS waitlist`
  - safe `ALTER TABLE` blocks

#### `migrate_v3_roles.py`

- Purpose: migrates from `admins` to unified `users` with roles.
- Logic:
  - creates `users`
  - copies admin hashes
  - adds table metadata columns
  - normalizes booking status from `active` to `Confirmed`
- Key snippets:
  - insert users with role
  - `DROP TABLE IF EXISTS admins`

#### `migrate_v4_customers.py`

- Purpose: creates `customers` table for Twilio-session tracking.
- Logic: one-table migration.
- Key snippets:
  - `customers (phone PRIMARY KEY, last_message_timestamp)`

#### `migrate_v5_schema_fix.py`

- Purpose: hotfix for schema drift.
- Logic:
  - adds `source`, `twilio_last_response`, `created_at`, `updated_at`
  - normalizes legacy/null statuses
  - backfills timestamps
- Key snippets:
  - `column_exists(...)`
  - status backfill updates

#### `migrate_v6_conversations.py`

- Purpose: creates persistent WhatsApp `conversations` table.
- Logic: safe `CREATE TABLE IF NOT EXISTS`.
- Key snippets:
  - `phone`, `state`, `data_json`, `updated_at`

#### `migrate_v7_booking_groups.py`

- Purpose: creates `booking_groups` for combo bookings.
- Logic: stores the total guest count separate from per-table booking rows.
- Key snippets:
  - `total_guests`

#### `migrate_v8_is_auto_allocated.py`

- Purpose: adds `is_auto_allocated` flag to bookings.
- Logic: marks waitlist auto-upgrades.
- Key snippets:
  - `ALTER TABLE bookings ADD COLUMN is_auto_allocated`

#### `migrate_v9_payment.py`

- Purpose: adds `payment_link_id` column.
- Logic: tiny idempotent payment migration.
- Key snippets:
  - `ALTER TABLE bookings ADD COLUMN payment_link_id TEXT`

#### `migrate_v10_seated_at.py`

- Purpose: adds `seated_at` for service timers.
- Logic:
  - adds column if needed
  - backfills arrived bookings from timestamp history
- Key snippets:
  - `COALESCE(NULLIF(seated_at,''), NULLIF(updated_at,''), NULLIF(created_at,''))`

#### `update_db_script.py`

- Purpose: one-off script that rewrites `db.py`.
- Logic: text replacement helper from an older refactor stage.
- Important note: this is not runtime code; it is a developer migration helper.

#### `update_admin_script.py`

- Purpose: one-off refactor helper for `admin.py`.
- Logic: removes older auth pieces and appends staff-management code.
- Important note: maintenance script, not production runtime logic.

#### `update_tables_route.py`

- Purpose: one-off helper to replace an older `manage_tables` route implementation.
- Logic: string-based source rewrite.
- Important note: migration helper, not part of request handling.

#### `diagnostic.py`

- Purpose: startup troubleshooting tool.
- Logic:
  - checks Python/module imports
  - checks DB existence/tables
  - checks whether port 5000 is already in use
- Key snippets:
  - import checks
  - socket port probe

### Config, data, docs, and repository support files

#### `requirements.txt`

- Purpose: Python dependency list.
- Logic: pins Flask, Twilio, APScheduler, Razorpay, etc.
- Key snippets:
  - `Flask==3.0.0`
  - `APScheduler==3.10.4`
  - `razorpay==1.4.2`

#### `slot_config.json`

- Purpose: editable slot schedule configuration.
- Logic:
  - stores schedule list, slot capacity, and days-ahead generation window
  - read by `db.load_slot_config()`
- Key snippets:
  - `"schedule"`
  - `"capacity"`
  - `"days_ahead"`

#### `cafebot.db`

- Purpose: live SQLite database file.
- Logic: stores all operational data.
- Tables confirmed by `diagnostic.py`:
  - `bookings`
  - `time_slots`
  - `tables`
  - `waitlist`
  - `users`
  - `customers`
  - `conversations`

#### `README.md`

- Purpose: project documentation.
- Logic: documentation only, not executed.

#### `DETAILED_README.md`

- Purpose: extended project documentation.
- Logic: documentation only, not executed.

#### `dbreadme.md`

- Purpose: database-focused documentation.
- Logic: documentation only, not executed.

#### `botReadme.md`

- Purpose: chatbot-focused documentation.
- Logic: documentation only, not executed.

#### `zinkaChika.md`

- Purpose: another documentation/narrative file already present in the repo.
- Logic: documentation only, not executed.

#### `server.stdout.log`

- Purpose: captured server standard output.
- Logic: runtime artifact useful for debugging.

#### `server.stderr.log`

- Purpose: captured server error output.
- Logic: runtime artifact useful for debugging.

#### `.env`

- Purpose: environment secrets/config like Flask key, Twilio, and Razorpay credentials.
- Logic: loaded by `load_dotenv()`.
- Important note: do not show its secret values in a demo document.

### Generated/runtime artifacts

#### `flask_session_data/`

- Purpose: Flask session/cache storage.
- Logic: generated at runtime.

#### `__pycache__/`

- Purpose: Python bytecode cache.
- Logic: generated automatically by Python.

#### `.vscode/`

- Purpose: editor configuration.
- Logic: development environment support, not application logic.

## 5. Best "Technical Lead" Summary To Say Out Loud

If your teacher asks for a 30-second summary, say this:

> "This project is a full-stack cafe reservation system built with Flask and SQLite. It has two major user interfaces: a web panel for admin/staff operations and a WhatsApp chatbot for customer bookings. The interesting engineering parts are the stateful WhatsApp flow, transactional booking protection, dynamic table allocation, waitlist auto-allocation, Razorpay payment-link confirmation, and scheduler-driven reminders/no-show handling."

## 6. Final Notes

- Strongest showcase areas:
  - live staff dashboard
  - WhatsApp booking state machine
  - slot generation and reporting
  - transactional conflict prevention in `db.py`
- Best honesty points:
  - some recovery/notify features are still demo stubs
  - legacy ops templates mix older Bootstrap patterns with the newer Tailwind base
  - no automated test suite is present yet
