# CafeBot Full Code Logic Guide

This file is the expanded version of the project guide. It is meant to explain the code in a much more complete way, file by file, function by function, page by page, and interaction by interaction.

It covers:

- `init_db.py`
- `app.py`
- `admin.py`
- `auth.py`
- `ops.py`
- `payment.py`
- `staff.py`
- every HTML file under `templates/`

The focus here is:

- what the code does
- where the code lives
- what conditions and branches it checks
- what data flows into and out of each function
- what template is rendered by which route
- what forms and JavaScript actions call which backend endpoints

## Project Structure At A Glance

The project is split into four main layers:

- Flask app startup and route registration
- route/controller logic in Python
- database and business rules in `db.py`
- UI rendering and live browser behavior in Jinja templates plus JavaScript

Even though this guide does not fully re-document `db.py` and `bot.py`, many files below depend on them heavily:

- `admin.py`, `ops.py`, `staff.py`, and `auth.py` all call into `db.py`
- `payment.py` is used from `bot.py`
- most templates depend on variables prepared in the route files above

## 1. `init_db.py`

### File role

`init_db.py` is the database bootstrap file. Its job is to create a brand-new `cafebot.db` from scratch, define the schema, and seed some starting records.

### Main line map

- Lines `1-4`: imports and database filename
- Lines `6-9`: database connection helper
- Lines `11-141`: `init_db()`
- Lines `144-145`: direct-run entry point

### Imports and constants

### Lines `1-4`

- Imports `sqlite3`
- Imports `os`
- Defines `DATABASE = 'cafebot.db'`

This tells the file which SQLite file to create and manipulate.

### `get_db_connection()`

### Lines `6-9`

This helper is intentionally small.

What it does:

- opens the SQLite file named by `DATABASE`
- sets `row_factory = sqlite3.Row`
- returns the open connection

Why `row_factory` matters:

- without it, SQL results come back like tuples
- with it, code can later do `row["username"]`, `row["status"]`, and similar field lookups

### `init_db()`

### Lines `11-141`

This is the real setup function.

Its first step:

- if `cafebot.db` already exists, delete it with `os.remove(DATABASE)`

That means this initializer is destructive. It resets everything.

After that it:

- opens a connection
- creates a cursor
- creates each required table
- seeds default users
- seeds default tables
- seeds sample time slots
- commits
- closes

### Schema created in `init_db()`

#### `users`

Purpose:

- login identities for admin and staff

Columns:

- `id`
- `username`
- `password_hash`
- `role`
- `created_at`

Important design point:

- role defaults to `staff`
- username must be unique

#### Seed users

The file immediately inserts:

- admin user with username `admin` and password `admin123`
- staff user with username `staff` and password `staff123`

Passwords are hashed with Werkzeug before insertion.

#### `bookings`

Purpose:

- all reservation records live here

Columns include:

- `phone`
- `name`
- `date`
- `slot_time`
- `seats`
- `table_number`
- `status`
- `combo_group`
- `reminder_sent`
- `seated_at`
- `is_auto_allocated`
- `payment_link_id`

Important meaning:

- `status` is the booking lifecycle state
- `combo_group` links multi-table bookings together
- `seated_at` supports service-duration tracking
- `is_auto_allocated` marks bookings created from waitlist upgrades
- `payment_link_id` connects a booking to Razorpay

#### `booking_groups`

Purpose:

- summary table for combo bookings

This stores one record for the logical booking while `bookings` stores one row per assigned table.

#### `time_slots`

Purpose:

- pre-generated booking windows by date

Columns include:

- `date`
- `slot_time`
- `total_capacity`
- `available_seats`
- `max_guests`

Important note:

- later code mainly uses `max_guests` and booking aggregation instead of trusting `available_seats` alone

#### `tables`

Purpose:

- physical cafe tables and their seating capacity

Columns include:

- `table_number`
- `table_name`
- `capacity`
- `location`
- `status`
- `image_url`

#### `waitlist`

Purpose:

- guests who want a future slot when full

Columns include:

- `phone`
- `name`
- `date`
- `slot_time`
- `guests`
- `status`
- `created_at`

### Seed tables

The initializer inserts six base tables.

These represent the cafe floor layout with capacities and locations such as:

- Window Side
- Near Entrance
- AC Zone
- Balcony
- Family Zone
- Private Hall

### Seed time slots

The initializer creates three demo slots for the current day.

This gives the app something to work with immediately after reset.

### End of file

### Lines `144-145`

- if the file is run directly, it calls `init_db()`

That makes it usable as a one-command reset tool.

## 2. `app.py`

### File role

`app.py` is the runtime entry point for the Flask application. It builds the app, loads configuration, registers blueprints, starts background jobs, and launches the server.

### Main line map

- Lines `1-10`: imports and blueprint imports
- Lines `12-25`: Flask setup
- Lines `30-33`: root redirect route
- Lines `35-90`: startup and background schedulers

### Imports

### Lines `1-10`

The file imports:

- `os`
- `sys`
- Flask objects
- `load_dotenv`
- all feature blueprints:
- `admin_bp`
- `bot_bp`
- `auth_bp`
- `staff_bp`
- `ops_bp`

This is the top-level place where those route modules become part of the app.

### Environment loading and app setup

### Lines `12-25`

This section:

- calls `load_dotenv()`
- creates `app = Flask(__name__)`
- sets `SECRET_KEY`
- sets `SESSION_COOKIE_SAMESITE = 'Lax'`
- registers all blueprints

Why this matters:

- `SECRET_KEY` is required for Flask sessions
- the blueprint registration is what activates the admin, auth, bot, staff, and ops routes

### `/` route

### Lines `30-33`

`index()` is intentionally simple.

It:

- redirects the root URL `/` to `auth.login`

This means the app does not expose a separate landing page. Login is the entry point.

### Startup code when run directly

### Lines `35-90`

This block runs only when executing `python app.py`.

It does several things.

#### Startup prints

- prints server URL
- prints webhook URL
- prints login panel URL

This is just operator-friendly console feedback.

#### Auto slot generation on startup

Inside the first `try` block:

- imports `db` lazily as `_db`
- calls `_db.auto_generate_slots()`
- prints how many new slots were inserted

This makes sure the system always has future slots when the server starts.

#### Scheduler setup

Inside the next `try` block:

- imports APScheduler
- imports reminder and no-show jobs
- imports `auto_generate_slots`

Then it schedules:

- `check_and_send_reminders` every 60 seconds
- `check_and_auto_noshow` every 60 seconds
- `auto_generate_slots` every 30 minutes

This is important because a lot of operational behavior depends on background maintenance, not just user clicks.

#### Error handling

- if APScheduler is missing, the app keeps running but prints that reminders are disabled
- if there is another scheduler failure, it prints the exception

#### Running Flask

At the end:

- runs `app.run(debug=True, port=5000, use_reloader=False)`

If port `5000` is already busy:

- catches `OSError`
- prints a helpful message
- suggests `Stop-Process -Name python -Force`
- exits with status `1`

## 3. `auth.py`

### File role

`auth.py` manages:

- login
- logout
- password recovery placeholder flow
- route access protection for admins and staff

### Main line map

- Lines `1-5`: imports and blueprint
- Lines `8-14`: `login_required`
- Lines `16-28`: `admin_required`
- Lines `30-40`: `staff_required`
- Lines `43-67`: `login()`
- Lines `69-102`: `forgot_password()`
- Lines `104-110`: `logout()`

### Blueprint setup

- `auth_bp = Blueprint('auth', __name__)`

All routes in this file are namespaced under the `auth` endpoint name.

### `login_required`

### Lines `8-14`

Logic:

- wraps a route
- checks `session.get('logged_in')`
- if false, redirects to login with `next=request.url`
- otherwise continues to the wrapped function

Use case:

- protects any page that requires a logged-in session

### `admin_required`

### Lines `16-28`

Logic:

- first checks logged-in status
- then checks `session['user_role']`
- if not admin:
- flashes `Admin access required.`
- if the current role is staff, redirects to `staff.dashboard`
- otherwise redirects to login

This decorator enforces separation between staff UI and admin UI.

### `staff_required`

### Lines `30-40`

Logic:

- requires the user to be logged in
- allows both `admin` and `staff`
- rejects anything else

Why admins are allowed:

- admins may need access to staff tools
- staff should not be able to access admin-only routes

### `/login`

### Lines `43-67`

This route supports both GET and POST.

#### POST behavior

- reads `username` and `password` from the form
- calls `db.get_user_by_username(username)`
- verifies the hashed password using `check_password_hash`

If valid:

- stores `logged_in = True`
- stores `username`
- stores `user_role`
- flashes success
- redirects:
- admin -> `admin.dashboard`
- staff -> `staff.dashboard`

If invalid:

- flashes `Invalid credentials.`

#### GET behavior

- pulls `autofill_usr` and `autofill_pwd` out of session
- removes them from session using `pop`
- renders `login.html`

Why autofill exists:

- the forgot-password flow can temporarily reset a password and then pass it to the login screen

### `/forgot-password`

### Lines `69-102`

This route is a placeholder recovery system, not a production-grade flow.

#### POST with both username and OTP

- loads the user
- opens a DB connection directly
- resets the account password to a hardcoded dummy password `Admin@123`
- hashes that password
- stores autofill credentials in session
- flashes a success message
- redirects to the login page

#### POST with only username

- checks whether the username exists
- flashes the same informational message either way

Why the same message:

- avoids revealing account existence too obviously

#### POST with no username

- flashes `Please enter a username.`

#### GET

- renders `forgot_password.html`

### `/logout`

### Lines `104-110`

Logic:

- removes login-related session keys
- flashes logout info
- redirects to login

## 4. `payment.py`

### File role

`payment.py` is a thin integration layer around Razorpay payment links.

### Main line map

- Lines `1-10`: module docstring
- Lines `12-23`: imports, env loading, key constants
- Lines `26-32`: `_client()`
- Lines `35-93`: `create_payment_link(...)`
- Lines `96-118`: `check_payment_link_status(...)`

### Top-level constants

This file loads:

- `RAZORPAY_KEY_ID`
- `RAZORPAY_KEY_SECRET`
- `PAYMENT_AMOUNT_PAISE`

And builds:

- `AMOUNT_DISPLAY`

Example:

- `10000` paise becomes `₹100`

### `_client()`

### Lines `26-32`

Logic:

- checks that both Razorpay keys exist
- if not, raises a `RuntimeError`
- otherwise returns a configured `razorpay.Client`

This centralizes credential validation.

### `create_payment_link(...)`

### Lines `35-93`

Inputs:

- `booking_id`
- `customer_name`
- `phone`
- optional `amount_paise`

Steps:

- if `amount_paise` is omitted, use the default constant
- strip `whatsapp:` and leading `+` from the phone
- construct the Razorpay payload

Payload details:

- `accept_partial` is disabled
- description includes booking ID
- customer name and contact are attached
- SMS and email notifications are disabled
- reminder is disabled
- notes include booking ID and source
- callback URL/method are blank because the app polls status instead of using a callback webhook

After calling Razorpay:

- extracts `short_url` or falls back to the link ID
- ensures both URL and ID exist
- returns `(link_url, link_id)`

Error path:

- if Razorpay sends a bad request, the function wraps it in `RuntimeError`

### `check_payment_link_status(link_id)`

### Lines `96-118`

Logic:

- fetches the payment link from Razorpay
- lowercases the returned status
- maps statuses into app-friendly output

Mappings:

- `paid` -> `paid`
- `cancelled` -> `cancelled`
- `expired` -> `expired`
- everything else -> `created`
- unexpected exceptions -> `error`

This function is used by the bot payment confirmation flow.

## 5. `admin.py`

### File role

`admin.py` is the controller for the admin panel. It contains:

- dashboard rendering
- booking actions
- slot management
- table management
- reports
- staff management
- admin profile settings

### Blueprint

- `admin_bp = Blueprint('admin', __name__, url_prefix='/admin')`

All routes here live under `/admin/...`.

### Route-to-template map

- `/admin/dashboard` -> `dashboard.html`
- `/admin/bookings` -> `bookings.html`
- `/admin/slots` -> `slots.html`
- `/admin/tables` -> `tables.html`
- `/admin/reports` -> `reports.html`
- `/admin/staff_management` -> `staff_management.html`
- `/admin/settings` -> `admin_settings.html`

### Main line map

- Lines `1-10`: imports and blueprint
- Lines `13-18`: booking normalization helper
- Lines `25-46`: dashboard route
- Lines `49-64`: dashboard JSON API
- Lines `72-77`: all bookings page
- Lines `80-126`: booking action route
- Lines `133-168`: slots page and bulk slot actions
- Lines `171-180`: manual slot regeneration
- Lines `183-231`: save slot schedule
- Lines `234-247`: inline slot capacity API
- Lines `250-272`: CSV export
- Lines `275-279`: slot stats API
- Lines `287-333`: table management page
- Lines `340-356`: reports page
- Lines `363-424`: staff management page
- Lines `431-468`: admin account settings

### `_augment_booking(b_dict)`

### Lines `13-18`

Purpose:

- normalize booking data before templates use it

What it changes:

- runs `normalize_booking_status(...)`
- ensures `is_messageable` exists even if DB query did not include it

This helper keeps the templates simpler because they can assume consistent keys.

### `dashboard()`

### Lines `25-46`

Flow:

- gets today’s date using cafe timezone
- loads metrics from `db.get_dashboard_metrics`
- ensures `revenue_today` exists
- loads recent bookings
- normalizes each booking with `_augment_booking`
- loads:
- `slot_chart_data`
- `weekly_trend`
- renders `dashboard.html`

Important output variables:

- `bookings`
- `metrics`
- `slot_chart_data`
- `weekly_trend`

### `api_dashboard_data()`

### Lines `49-64`

This is the live-data endpoint for the dashboard page.

It returns JSON containing:

- current metrics
- recent bookings

The frontend in `dashboard.html` polls this every 15 seconds.

### `all_bookings()`

### Lines `72-77`

Flow:

- loads every booking with `db.get_all_bookings()`
- normalizes them
- renders `bookings.html`

### `booking_action(booking_id)`

### Lines `80-126`

This is one of the most important admin routes.

Inputs:

- route parameter: `booking_id`
- form field: `action`

The code first loads the booking using `db.get_booking_by_id_only(booking_id)`.

#### Branch 1: `action == 'cancel'`

The route:

- calls `db.admin_cancel_booking(booking_id)`
- if cancellation succeeds:
- checks if the booking belongs to a real customer and not a walk-in
- checks whether the customer is still messageable via Twilio
- if yes, sends a WhatsApp cancellation notice
- flashes one of:
- success with customer notified
- success but Twilio error
- success but session expired

If cancellation fails:

- flashes the returned error message

#### Branch 2: status action in `['Confirmed', 'Arrived', 'Completed', 'No-show']`

The route:

- updates booking status in the DB

Special handling for `Confirmed`:

- if the booking belongs to a real customer
- and the customer is messageable
- sends a WhatsApp confirmation message

For non-confirm statuses:

- just flashes a local success message

Final behavior:

- always redirects back to the referring page or admin bookings page

### `manage_slots()`

### Lines `133-168`

This route handles both slot display and destructive slot actions.

#### POST branch

Supported actions:

- `delete`
- `delete_day`
- `clear_week`

Action details:

- `delete` -> remove one slot by ID
- `delete_day` -> remove all slots for a selected date
- `clear_week` -> remove all future slots

Each action:

- calls a DB helper
- flashes a result
- redirects back to `/admin/slots`

#### GET branch

Loads:

- slot rows with booking numbers via `db.get_slots_with_bookings()`
- slot schedule config via `db.load_slot_config()`
- today’s date string

Then renders `slots.html`.

### `regenerate_slots()`

### Lines `171-180`

This route manually calls `db.auto_generate_slots()`.

Behavior:

- if new rows were added -> success flash
- if nothing new was needed -> info flash
- redirects back to the slots page

### `update_slot_schedule()`

### Lines `183-231`

This route saves the schedule edited inside the slots modal.

Data read from form:

- repeated `slot_times`
- `capacity`
- `days_ahead`

Validation steps:

- capacity must be numeric
- days ahead must be numeric
- capacity must be `1-500`
- days ahead must be `1-90`
- every time string must match `H:MM AM - H:MM AM`
- duplicates are removed
- at least one time row must remain

After validation:

- calls `db.save_slot_config(cleaned, capacity, days_ahead)`
- writes an audit log message
- flashes success

This route does not regenerate slots automatically. It only saves the config.

### `update_slot_capacity(slot_id)`

### Lines `234-247`

AJAX endpoint used by the inline capacity widget in `slots.html`.

Flow:

- read `capacity`
- validate integer and allowed range
- call `db.update_slot_capacity(slot_id, new_cap)`
- return JSON success or error

### `export_slots_csv()`

### Lines `250-272`

Flow:

- loads slot rows with booking stats
- writes a CSV in memory using `csv.writer`
- returns it as a Flask `Response`

Columns exported:

- Date
- Time
- Capacity
- Booked
- Available
- Fill %

### `slot_stats_api()`

### Lines `275-279`

Simple JSON endpoint used by the slot insights strip.

It returns:

- booking fill stats grouped by slot label

### `manage_tables()`

### Lines `287-333`

This is the admin version of table management.

#### POST actions

- `add`
- `edit`
- `delete`

The route opens a DB connection directly and performs SQL statements.

Add flow:

- collect table number, name, capacity, location
- insert row into `tables`

Edit flow:

- collect table ID, new values
- update row by `id`

Delete flow:

- delete row by `id`

Error behavior:

- any exception rolls back and flashes the stringified error

#### GET

- loads all tables with `db.get_all_tables()`
- renders `tables.html`

### `reports()`

### Lines `340-356`

Flow:

- reads `start` and `end` query args
- defaults to the last 7 days
- calls `db.get_report_data(start, end)`
- renders `reports.html`

### `manage_staff()`

### Lines `363-424`

This route manages staff user accounts.

#### POST branch: `add`

- validate username length >= 3
- validate password length >= 6
- insert a new `users` row with role `staff`
- flash success or duplicate error

#### POST branch: `delete`

- delete a staff user by `id`

#### POST branch: `reset`

- validate new password length
- update `password_hash` for that staff account

#### GET branch

- loads all users
- filters to users where `role == 'staff'`
- renders `staff_management.html`

### `admin_settings()`

### Lines `431-468`

This route is for the currently logged-in admin.

GET behavior:

- loads the current user from the session username
- renders `admin_settings.html`

POST behavior:

- only action currently supported is `change_password`
- validates current password against the stored hash
- validates new password minimum length
- validates confirmation match
- updates the hash in the `users` table

## 6. `ops.py`

### File role

`ops.py` is the operations control layer. It is designed for fast floor work rather than the broader admin dashboard.

This file powers:

- the floor board
- reservation list for operations staff
- waitlist assignment
- customer summary view
- operations-side table config
- multiple JSON APIs used directly by JavaScript

### Blueprint

- `ops_bp = Blueprint('ops', __name__)`

Routes here are plain paths like `/floor` and `/bookings`, not `/ops/...`.

### Main line map

- Lines `1-17`: imports and blueprint
- Lines `20-28`: `_format_time`
- Lines `31-32`: `_parse_iso`
- Lines `35-114`: `_build_table_cards`
- Lines `117-145`: `_get_upcoming_reservations`
- Lines `148-181`: `floor`
- Lines `184-200`: `bookings_page`
- Lines `203-207`: `customers_page`
- Lines `210-215`: `waitlist_page`
- Lines `218-315`: `tables_page`
- Lines `318-327`: `api_table_status`
- Lines `330-365`: `api_seat_guest`
- Lines `368-379`: `api_table_suggest`
- Lines `382-390`: `api_checkout`
- Lines `393-401`: `api_mark_clean`
- Lines `404-420`: `api_waitlist_add`
- Lines `423-449`: `api_waitlist_assign`
- Lines `452-469`: `api_booking_status`
- Lines `472-515`: `api_booking_update`

### `_format_time(dt_value)`

### Lines `20-28`

Purpose:

- convert datetime-like input into display text such as `6:30 PM`

Behavior:

- blank input returns `""`
- string input is parsed with `%Y-%m-%d %H:%M:%S`
- parse failure returns `""`
- otherwise formats as 12-hour time without leading zero

### `_parse_iso(dt_value)`

### Lines `31-32`

- delegates parsing to `db.parse_booking_datetime(...)`

This keeps parsing rules consistent with the database layer.

### `_build_table_cards(tables, bookings, now)`

### Lines `35-114`

This is the most important preparation helper for the floor page.

Input:

- raw table rows
- raw booking rows
- current datetime

Main work:

- gets all active statuses from `utils`
- computes combo booking totals from `db.get_combo_group_totals(...)`
- groups bookings by table number
- normalizes status and slot labels

For each table it calculates:

- current active booking
- next upcoming booking
- guest name
- guest count
- seated-since value
- next reservation time

Special logic:

- if an `Arrived` booking exists, it is treated as the current live booking
- otherwise the most recently started active booking can become the current one
- combo group bookings show total guests instead of per-table seat fragment

Output:

- list of dictionaries suitable for `floor.html`

### `_get_upcoming_reservations(bookings, now, window_minutes=120)`

### Lines `117-145`

Purpose:

- produce the “Next 2 Hours” sidebar list for the floor page

Logic:

- keep only `Pending` and `Confirmed`
- parse slot start time
- keep bookings between now and `now + 120 minutes`
- sort by start time
- strip internal `slot_start` field before returning

### `floor()`

### Lines `148-181`

This route assembles the entire floor-board page.

Steps:

- determine today’s date
- get current time
- load all tables
- load today’s bookings
- load today’s pending waitlist entries
- compute wait minutes from `created_at`
- build table cards
- build upcoming reservation list
- collect available slot labels for quick booking
- collect all today slot labels for waitlist form
- render `floor.html`

Template variables supplied:

- `tables`
- `upcoming`
- `waitlist`
- `today_date`
- `slot_labels`
- `waitlist_slot_labels`

### `bookings_page()`

### Lines `184-200`

Purpose:

- render the operations reservations page

Logic:

- load all bookings
- normalize status
- normalize slot label
- calculate `seats_display` for combo bookings
- render `bookings_ops.html`

### `customers_page()`

### Lines `203-207`

- loads customer summaries from `db`
- renders `customers.html`

### `waitlist_page()`

### Lines `210-215`

- loads today’s pending waitlist entries
- renders `waitlist_ops.html`

### `tables_page()`

### Lines `218-315`

This route is an operations/admin version of table configuration.

#### POST: `add`

- insert a table

#### POST: `edit`

- update table name, capacity, location by `table_number`

#### POST: `delete`

- delete table by `table_number`

#### POST: `block`

- call `db.update_table_status(..., "Blocked")`

#### POST: `unblock`

- call `db.update_table_status(..., "Vacant")`

#### POST: `merge`

This is the more interesting branch.

It:

- loads both selected tables
- ensures both exist
- finds the current max table number
- creates a brand-new merged table with:
- incremented table number
- combined capacity
- merged name
- merged location
- status `Blocked`
- blocks the original two tables

After any POST action:

- redirects back to the tables page

GET behavior:

- loads all tables
- renders `tables_ops.html`

### `api_table_status()`

### Lines `318-327`

Purpose:

- generic JSON endpoint to set table status

Validation:

- requires `table_number`
- requires `status`

Returns:

- `{"ok": success}` or validation error JSON

### `api_seat_guest()`

### Lines `330-365`

This endpoint has two modes.

#### Mode 1: `booking_id` provided

- treat it as existing reservation check-in
- call `db.update_booking_status(booking_id, "Arrived")`

#### Mode 2: quick seating

- requires `guests` and `slot_time`
- if no table number is provided:
- finds available tables
- auto-picks the first suggestion
- calls `db.atomic_quick_seat(...)`
- returns JSON with `booking_id` and `table_number`

This endpoint is heavily used by `floor.html` and `bookings_ops.html`.

### `api_table_suggest()`

### Lines `368-379`

- validates `slot_time` and `guests`
- gets matching available tables
- returns just the table numbers

Used by the quick booking modal in `floor.html`.

### `api_checkout()`

### Lines `382-390`

- validates booking ID
- updates booking status to `Completed`
- returns JSON result

### `api_mark_clean()`

### Lines `393-401`

- validates table number
- marks the table `Vacant`
- returns JSON result

### `api_waitlist_add()`

### Lines `404-420`

- validates `name`, `guests`, `slot_time`
- accepts optional phone
- defaults missing phone to `walkin:waitlist`
- adds the entry to the waitlist via `db.add_to_waitlist(...)`

### `api_waitlist_assign()`

### Lines `423-449`

- validates `waitlist_id` and `table_number`
- loads the waitlist row
- converts that row into a seated booking using `db.atomic_quick_seat(...)`
- marks the waitlist row `seated`
- returns the new booking ID

### `api_booking_status()`

### Lines `452-469`

- validates `booking_id` and `status`
- normalizes the incoming status label

Branch behavior:

- if status becomes `cancelled`, call `db.admin_cancel_booking(...)`
- otherwise call `db.update_booking_status(...)`

### `api_booking_update()`

### Lines `472-515`

Purpose:

- edit booking date, slot, seats, and table assignment

Steps:

- validate booking ID
- load current booking
- calculate new field values using payload or existing values
- validate `table_number` if present
- if the table/date/slot combination changed:
- ensure the requested table is actually available
- update the booking row directly in SQL
- return `{"ok": True}`

## 7. `staff.py`

### File role

`staff.py` powers the staff POS dashboard. It is focused on:

- quick walk-in seating
- live table visibility
- check-in
- checkout
- no-show and release operations

### Blueprint

- `staff_bp = Blueprint('staff', __name__, url_prefix='/staff')`

### Main line map

- Lines `1-13`: imports, constants, blueprint
- Lines `16-19`: `_get_booking_start`
- Lines `22-71`: `_build_next_booking`
- Lines `74-179`: `action`
- Lines `182-227`: `dashboard`
- Lines `234-391`: `api_live_tables`
- Lines `398-406`: `checkin`
- Lines `409-426`: `booking_action`
- Lines `429-439`: `force_release`

### Constants

### Lines `8-13`

- `WALKIN_LOCKOUT_MINS = 45`
- `ARRIVED_ENABLE_MINS = 30`

Meaning:

- do not allow a short-stay walk-in if a reservation is too close
- only show the `Arrived` action when the reservation is near enough

### `_get_booking_start(booking, base_date)`

### Lines `16-19`

- normalizes the slot label
- parses its start time
- returns both parsed start datetime and normalized label

### `_build_next_booking(...)`

### Lines `22-71`

Purpose:

- find the next future booking for a table

Logic:

- skip anything not `Pending` or `Confirmed`
- skip the currently active booking if one already exists
- skip bookings that already started when no active booking exists
- compute gap from now
- convert gap into:
- label
- tone

Possible output tone examples:

- `danger`
- `warning`
- `neutral`

The returned object is used to show “Up Next” details in the live staff dashboard.

### `action()`

### Lines `74-179`

This route seats a walk-in directly from the staff dashboard.

Input:

- `table_id`
- `guests`

Validation:

- guests must be an integer
- table ID must exist
- table must exist
- guests must not exceed table capacity
- table status must be `Vacant` or `Reserved`

Special reserved-table logic:

- if the table is reserved, the code checks the next reservation start
- if the booking is too close, it blocks the walk-in

If seating is allowed:

- begins transaction with `BEGIN IMMEDIATE`
- inserts a `bookings` row with:
- phone `walkin:staff`
- name `Walk-In Guest`
- slot label like current time plus `(Walk-In)`
- status `Arrived`
- `seated_at = now`
- updates the table status to `Occupied`
- commits

Response style:

- flashes HTML response for browser form submits
- returns JSON if `Accept: application/json` is present

### `dashboard()`

### Lines `182-227`

POST branch:

- supports table-status updates from forms

GET branch:

- gets today’s date
- loads bookings and tables
- calculates summary counts:
- total
- vacant
- reserved
- occupied
- cleaning
- renders `staff_dashboard.html`

This route supplies only the page shell and summary values. The table grid itself is populated via AJAX.

### `api_live_tables()`

### Lines `234-391`

This is the core live-status endpoint for staff.

What it loads:

- today’s bookings
- all tables
- active statuses
- today’s slots

What it computes:

- which slots are still valid for walk-ins
- booked guests by slot
- global slot availability
- active booking per table
- next booking per table
- whether a table should display `Reserved (Impending)`
- elapsed service time for arrived guests
- whether a reserved table can still accept a short-stay walk-in

Special details:

- walk-ins are allowed for slots that are within the last 30 minutes or later
- completed bookings are still considered when preventing invalid walk-in slot overlap
- a vacant table can be visually upgraded to `Reserved (Impending)` if a reservation is due within 60 minutes

Returned JSON structure per table includes:

- `table_number`
- `capacity`
- `status`
- `available_slots`
- `booking`
- `next_booking`

This is consumed directly by Alpine in `staff_dashboard.html`.

### `checkin(booking_id)`

### Lines `398-406`

- marks reservation `Arrived`
- flashes success
- returns JSON if requested

### `booking_action(booking_id)`

### Lines `409-426`

- reads a posted `action`
- updates booking status via `db.update_booking_status(...)`
- if action is `Completed`, flashes the special cleaning/auto-release message
- otherwise flashes a generic success/failure message

### `force_release(table_number)`

### Lines `429-439`

- calls `db.force_release_table(table_number)`
- flashes success or failure
- returns JSON if requested

## 8. Templates

This section documents every HTML file under `templates/`.

## 8.1 `templates/base.html`

### File role

Shared shell for the admin panel and the classic staff dashboard pages.

### Main line map

- Lines `1-45`: head assets, Tailwind config, utility CSS
- Lines `50-115`: sidebar
- Lines `116-195`: main header and profile dropdown
- Lines `200-223`: flash toasts
- Lines `227-236`: content and script blocks

### What it contains

- Tailwind CSS
- Google font `Inter`
- Bootstrap Icons
- Alpine.js
- the brand palette in `tailwind.config`
- `.nav-item` and `.cafe-card` shared utility classes

### Sidebar behavior

The sidebar is role-aware.

If `session['user_role'] == 'admin'`, it shows links for:

- Dashboard
- Bookings
- Tables
- Time Slots
- Reports
- Staff

If `session['user_role'] == 'staff'`, it shows:

- Dashboard

### Header/profile area

This part uses Alpine:

- `x-data="{ open: false }"`
- `@click.outside="open = false"`

It controls the user dropdown.

### Flash toasts

Each flashed message:

- gets a color style based on category
- auto-hides after 5 seconds
- can be dismissed manually

This layout exposes these Jinja blocks:

- `title`
- `head`
- `outer_wrap`
- `page_title`
- `content`
- `scripts`

## 8.2 `templates/ops_base.html`

### File role

Shared shell for operations pages.

### Main line map

- Lines `1-66`: head config and status styling
- Lines `68-107`: ops sidebar
- Lines `114-132`: top header
- Lines `136-157`: flash toasts
- Lines `161-168`: content and script blocks

### Important differences from `base.html`

- navigation is path-based, not endpoint-based
- title defaults to `CafeBot Ops`
- includes hardcoded CSS classes for status labels like:
- `.status-Vacant`
- `.status-Reserved`
- `.status-Occupied`
- `.status-NeedsCleaning`
- `.status-Blocked`

## 8.3 `templates/dashboard.html`

### Used by

- `admin.dashboard`

### Main line map

- Lines `1-175`: page body
- Lines `177-190`: embedded JSON payload
- Lines `191-230`: live JavaScript

### Server-rendered content

The page shows:

- live clock pill
- metric cards
- recent bookings table

The bookings table includes:

- phone
- messageability badge
- date and slot
- table badge
- status badge
- action buttons

Actions shown are status-dependent:

- `Pending` -> Confirm, Cancel
- `Confirmed` -> Arrived, Cancel
- `Arrived` -> Complete

### JavaScript logic

The page defines `adminDashboard()`.

It:

- reads initial JSON from `<script id="dashboard-data">`
- stores it into Alpine state
- polls `/admin/api/dashboard_data`
- replaces `metrics` and `recent_bookings`

There is also a live clock updater that refreshes every second.

## 8.4 `templates/bookings.html`

### Used by

- `admin.all_bookings`

### Main line map

- Lines `1-137`: admin bookings table
- Lines `138-179`: filter script

### Page behavior

The top filter bar contains:

- search box
- status dropdown
- date dropdown
- clear button
- visible row counter

Each booking row displays:

- booking ID
- customer name
- optional waitlist badge
- phone and messageability state
- date and time
- guests
- table number
- normalized status badge
- action buttons

### JavaScript behavior

The script defines:

- `_today`
- `filterTable()`
- `clearFilters()`

Filtering works using row `data-*` attributes:

- `data-date`
- `data-status`

It matches by:

- search text against row text content
- exact status
- date mode: today, upcoming, past

## 8.5 `templates/slots.html`

### Used by

- `admin.manage_slots`

### Main line map

- Lines `1-210`: large custom CSS block
- Lines `212-661`: slot management UI
- Lines `663-849`: JavaScript

### Server-rendered structure

The page is intentionally rich and dense.

It includes:

- top action bar
- schedule summary card
- bulk actions card
- filter/search strip
- grouped slot tables by date
- booking insights strip
- edit schedule modal
- confirm overlay

### Important server-side logic visible in Jinja

The template:

- groups slot rows by date
- computes:
- total slots
- full slots
- available slots
- whether a day is past
- classifies each slot as:
- morning
- afternoon
- evening
- available
- full
- past

Each slot row renders:

- time label
- status badge
- inline editable capacity field
- fill progress bar
- trend badge placeholder
- delete button

### JavaScript functions in this template

#### Filter/search

- `activeFilter`
- click handler on `#filterChips`
- `applyFilter()`

This:

- filters slot rows by period or status
- filters by text search
- hides entire day groups if no child rows remain visible

#### Collapse behavior

- `toggleDay(header)`

This expands or collapses one day group.

#### Inline capacity save

- `saveCapacity(slotId)`

This:

- validates the numeric value
- sends `POST` to `/admin/slots/<slot_id>/capacity`
- updates button icon based on result

#### Schedule modal

- `openScheduleModal()`
- `closeScheduleModal()`
- escape-key close handling
- click-outside close handling

#### Dynamic time rows

- `addTimeRow()`
- `removeTimeRow(btn)`

This lets the admin build the schedule list in the modal.

#### Confirm overlay

- `confirmAction(action, msg)`
- `closeConfirm()`

Used for destructive bulk actions.

#### Stats and insights

- `fetchStats()`

This calls `/admin/slots/api/stats` and updates:

- slot trend labels
- busiest slot
- evening fill rate
- morning fill rate
- overall fill rate

## 8.6 `templates/tables.html`

### Used by

- `admin.manage_tables`

### Main line map

- Lines `1-56`: add-table form
- Lines `59-158`: active tables table and edit modal

### Page behavior

Left panel:

- add new table form

Fields:

- table number
- table name
- seat capacity
- location

Right panel:

- shows active tables
- each row has:
- edit
- delete

Edit uses Alpine modal state:

- `x-data="{ editModalOpen: false }"`

Modal fields:

- table name
- capacity
- location

Delete uses a normal form submit with confirmation.

## 8.7 `templates/reports.html`

### Used by

- `admin.reports`

### Main line map

- Lines `3-11`: print CSS
- Lines `13-205`: page body

### Page behavior

Top area:

- page title
- print button
- date-range filter form

Then:

- four metrics cards
- peak slots table
- most used tables table
- daily breakdown table

This template is mostly passive. It displays analytics already calculated by `db.get_report_data(...)`.

## 8.8 `templates/staff_management.html`

### Used by

- `admin.manage_staff`

### Main line map

- Lines `1-43`: add-staff form
- Lines `44-160`: staff list and reset modal

### Page behavior

Left column:

- add staff member form

Right column:

- list of current staff users
- each row provides:
- reset password button
- deactivate button

Reset uses Alpine modal state:

- `x-data="{ resetModalOpen: false }"`

The reset form posts:

- `action = reset`
- `user_id`
- `new_password`

## 8.9 `templates/admin_settings.html`

### Used by

- `admin.admin_settings`

### Main line map

- Lines `1-41`: profile card
- Lines `47-114`: password change card
- Lines `121-139`: sign-out/session card

### Page behavior

Profile card shows:

- avatar initial
- username
- role
- created timestamp
- active badge

Password form:

- posts `action = change_password`
- has three password fields
- uses Alpine state:
- `showCurrent`
- `showNew`
- `showConfirm`

Session card:

- provides a sign-out link

## 8.10 `templates/login.html`

### Used by

- `auth.login`

### Main line map

- Lines `1-9`: title and `outer_wrap` override
- Lines `10-100`: centered login card
- Lines `103`: end of custom wrapper

### Important design detail

This template does not use the standard sidebar layout. It overrides `outer_wrap`.

### Form behavior

Fields:

- username
- password

Features:

- displays flashed errors and success info
- autofills temporary reset credentials when provided
- uses Alpine to toggle password visibility
- links to forgot password page

## 8.11 `templates/forgot_password.html`

### Used by

- `auth.forgot_password`

### Main line map

- Lines `1-77`: main recovery card
- Lines `79-111`: OTP modal
- Lines `115`: end wrapper

### Page behavior

Like `login.html`, this template overrides `outer_wrap`.

The page:

- explains the recovery flow
- asks for username
- intercepts the submit button with Alpine:
- if username exists, opens a fake OTP modal
- otherwise focuses the username field

Inside the modal:

- there is an OTP input
- the final button submits the same form

This matches the placeholder recovery behavior in `auth.py`.

## 8.12 `templates/staff_dashboard.html`

### Used by

- `staff.dashboard`
- `staff.api_live_tables` for live data

### Main line map

- Lines `1-236`: dashboard layout and walk-in modal
- Lines `239-332`: Alpine live-data logic

### Server-rendered shell

This page renders:

- heading
- live clock placeholder
- today’s date
- summary badges
- empty initial table grid container
- walk-in modal container

The actual live table cards come from Alpine state populated by AJAX.

### Table card UI logic

Each card can visually switch between:

- `Vacant`
- `Reserved`
- `Reserved (Impending)`
- `Occupied`
- `Needs Cleaning`

Actions shown depend on state.

Examples:

- vacant -> `Seat Walk-In`
- reserved and still safely far away -> short-stay walk-in allowed
- reserved and close -> arrival preparation or `Arrived`
- occupied -> notify/call and checkout
- cleaning -> manual immediate release

### Walk-in modal

The modal:

- is opened by `openWalkinModal(table)`
- binds selected table and guest count
- submits to `/staff/action`

### JavaScript logic

The Alpine component `liveTables()` holds:

- `tables`
- `isRefreshing`
- `isWalkinModalOpen`
- `selectedTableForWalkin`
- `walkinGuests`

Functions:

- `countTables(statuses)`
- `openWalkinModal(table)`
- `closeWalkinModal()`
- `submitAction(url, formData)`
- `fetchLiveTables()`
- `startPolling()`

Polling:

- calls `/staff/api/live_tables` every 15 seconds

There is also a live clock updater.

## 8.13 `templates/floor.html`

### Used by

- `ops.floor`

### Main line map

- Lines `1-192`: live floor board layout
- Lines `195-375`: JavaScript action handlers

### Layout sections

Main area:

- table cards

Sidebar:

- next 2 hours reservations
- walk-in waitlist form
- waitlist list

Bottom modal:

- quick booking modal

### Table card actions

Buttons include:

- Seat Guest
- Checkout Guest
- Needs Cleaning
- Mark Clean
- Mark Occupied
- Block Table
- Unblock

### Sidebar actions

Upcoming reservation rows include:

- Seat
- Edit
- Cancel
- No-show

Waitlist includes:

- add form
- assign-table buttons

### Quick booking modal

Fields:

- name
- phone
- guests
- date
- slot time
- optional table number

Includes a suggest button that calls the table suggestion API.

### JavaScript functions

This template defines `postJson(url, data)` and then attaches listeners for:

- seat action
- checkout action
- needs cleaning
- mark clean
- mark occupied
- block
- unblock
- cancel reservation
- no-show
- waitlist assign
- waitlist form submit
- quick booking form submit
- suggest table click

Almost every action ends with `location.reload()` on success.

## 8.14 `templates/bookings_ops.html`

### Used by

- `ops.bookings_page`

### Main line map

- Lines `1-87`: reservations table and modal
- Lines `90-160`: action scripts

### Layout

- table of bookings
- edit modal with fields:
- date
- slot time
- guests
- table number

### Buttons per row

- Seat
- Edit
- Cancel
- No-show

### JavaScript

Defines:

- `postJson`
- seat handler
- cancel handler
- no-show handler
- edit button modal filler
- edit form submit handler

Edit data is pulled from row `data-*` attributes and written into modal inputs.

## 8.15 `templates/customers.html`

### Used by

- `ops.customers_page`

### Main line map

- Lines `1-49`: full page

### Behavior

This is a display-only page.

It renders a customer summary table with:

- name
- phone
- visit count
- last visit
- average party size
- notes placeholder

If there are no customers, it shows an empty-state row.

## 8.16 `templates/tables_ops.html`

### Used by

- `ops.tables_page`

### Main line map

- Lines `1-31`: add table form
- Lines `35-60`: merge table form
- Lines `67-138`: table list and inline edit rows

### Behavior

Left side:

- add new table
- merge two tables

Right side:

- list of current tables
- actions:
- block
- unblock
- edit
- delete

Edit is implemented as a collapsible inline row rather than a modal.

## 8.17 `templates/waitlist_ops.html`

### Used by

- `ops.waitlist_page`

### Main line map

- Lines `1-38`: waitlist table
- Lines `41-68`: assign-table script

### Behavior

- shows pending waitlist entries
- each row has `Assign Table`

The script:

- prompts for a table number
- posts to `/api/waitlist/assign`
- reloads on success

## 9. Final Wiring Summary

### Backend routes and pages

- `auth.py`
- login and recovery pages

- `admin.py`
- admin dashboard
- admin booking control
- admin slot control
- admin table control
- reports
- staff account management
- admin settings

- `ops.py`
- floor board
- operational reservations
- waitlist
- customers
- operations table management
- fast JSON APIs for actions

- `staff.py`
- staff dashboard shell
- live table API
- check-in
- checkout/status changes
- force release

### Templates extending `base.html`

- `dashboard.html`
- `bookings.html`
- `slots.html`
- `tables.html`
- `reports.html`
- `staff_management.html`
- `admin_settings.html`
- `login.html`
- `forgot_password.html`
- `staff_dashboard.html`

### Templates extending `ops_base.html`

- `floor.html`
- `bookings_ops.html`
- `customers.html`
- `tables_ops.html`
- `waitlist_ops.html`

## 10. Big Picture Logic Flow

### Startup

- `app.py` starts Flask
- blueprints are registered
- slots are auto-generated
- schedulers start

### Authentication

- `auth.py` logs users in
- session stores username and role
- decorators enforce access control

### Admin control flow

- `admin.py` loads data from `db.py`
- templates under `base.html` render management pages
- some pages poll JSON endpoints for live updates

### Operations control flow

- `ops.py` renders action-focused pages under `ops_base.html`
- buttons call JSON APIs
- APIs update bookings, tables, and waitlist state through `db.py`

### Staff live flow

- `staff.dashboard` renders the shell
- Alpine polls `/staff/api/live_tables`
- the browser updates live table cards without a full reload
- actions submit forms or fetch requests back to `staff.py`

### Payment flow

- `payment.py` creates Razorpay links
- the bot later checks payment status
- DB rows store the payment-link ID

## 11. What To Read Next If You Want Even Deeper Detail

If you want absolute full-project logic, the next two files matter the most:

- `db.py`
- `bot.py`

Why:

- `db.py` contains the deepest business rules
- `bot.py` contains the end-user WhatsApp booking conversation

This file focuses on the remaining app and UI layers around them.
