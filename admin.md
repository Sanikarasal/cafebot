# admin.py README

This document explains the logic in `admin.py`, which defines the Flask admin panel for CafeBot.

## 1. What `admin.py` is responsible for

`admin.py` creates the admin blueprint:

- Blueprint name: `admin`
- URL prefix: `/admin`

That means every route in this file is mounted under `/admin/...`.

The file is registered in `app.py`, so once the Flask app starts, these routes become part of the application.

Main responsibilities:

- Show the admin dashboard
- Manage bookings and booking status changes
- Manage slot generation and slot configuration
- Manage tables
- Show reports
- Manage staff accounts
- Let the logged-in admin change their own password

## 2. Core dependencies used by `admin.py`

`admin.py` depends on a few important modules:

- `auth.admin_required`
  Protects every admin route. If the user is not logged in, it redirects to login. If the user is logged in but is not an admin, it blocks access.
- `db`
  Handles almost all database reads and writes used by the admin panel.
- `utils.normalize_booking_status`
  Converts legacy or inconsistent status values into the canonical status set used by the UI and business logic.
- `werkzeug.security.generate_password_hash`
  Hashes passwords before saving them to the `users` table.
- `flask` helpers like `render_template`, `request`, `redirect`, `url_for`, `session`, `flash`, and `jsonify`
  These power form handling, redirects, sessions, flash messages, and JSON APIs.

## 3. How access control works

Every route in this file uses `@admin_required`.

That decorator lives in `auth.py` and does this:

1. Checks `session['logged_in']`
2. If missing, redirects to `/login`
3. Checks `session['user_role']`
4. If the role is not `admin`, it flashes `Admin access required.`
5. Staff users are redirected to the staff dashboard
6. Other users are redirected to login

So `admin.py` assumes that once execution reaches a route function, the current user is a valid admin.

## 4. The blueprint setup

At the top of the file:

```python
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')
```

Code line in `admin.py`:

- `admin_bp` is defined at line 9

This gives route names such as:

- `admin.dashboard`
- `admin.all_bookings`
- `admin.manage_slots`
- `admin.manage_tables`

Those endpoint names are later used with `url_for(...)`.

## 5. Shared helper: `_augment_booking`

`_augment_booking(b_dict)` is a small helper used before sending booking data to templates or JSON responses.

Code lines in `admin.py`:

- `_augment_booking(...)`: lines 13-18

It does two things:

1. Normalizes the booking status
   Example:
   - `active` becomes `Confirmed`
   - `noshow` becomes `No-show`
   - `canceled` becomes `cancelled`
2. Ensures the booking dict always has `is_messageable`
   If the DB query did not include that field, it defaults to `False`

Why this exists:

- Templates should not need to understand legacy statuses
- UI logic becomes more predictable
- JSON responses stay consistent

## 6. Route-by-route explanation

### 6.1 Dashboard: `GET /admin/dashboard`

Function: `dashboard()`

Code lines in `admin.py`:

- Route decorator and function: lines 25-46

Purpose:

- Show the main admin dashboard page

Flow:

1. Reads the current cafe-local date using `get_cafe_date()`
2. Calls `db.get_dashboard_metrics(today_date)` for high-level counts
3. Ensures `metrics['revenue_today']` exists
4. Calls `db.get_recent_bookings(5)` for the latest 5 bookings
5. Converts those DB rows into dicts and normalizes them with `_augment_booking`
6. Loads chart data:
   - `db.get_bookings_by_slot_today(today_date)`
   - `db.get_weekly_booking_trend()`
7. Renders `dashboard.html`

Template data passed in:

- `bookings`
- `metrics`
- `slot_chart_data`
- `weekly_trend`

Important DB logic behind it:

- `get_dashboard_metrics()` calculates:
  - total tables
  - today's booking count
  - available tables
  - today's guests
  - waitlist count
  - revenue today
- `get_bookings_by_slot_today()` groups bookings by slot label
- `get_weekly_booking_trend()` builds a 7-day trend series

### 6.2 Dashboard auto-refresh API: `GET /admin/api/dashboard_data`

Function: `api_dashboard_data()`

Code lines in `admin.py`:

- Route decorator and function: lines 49-65

Purpose:

- Return dashboard metrics and recent bookings as JSON
- Likely used by frontend auto-refresh code such as AlpineJS

Flow:

1. Gets today's cafe-local date
2. Fetches dashboard metrics
3. Fetches the latest 5 bookings
4. Normalizes bookings using `_augment_booking`
5. Returns:

```json
{
  "metrics": {...},
  "recent_bookings": [...]
}
```

Difference from `dashboard()`:

- It does not render HTML
- It does not include chart data

### 6.3 All bookings page: `GET /admin/bookings`

Function: `all_bookings()`

Code lines in `admin.py`:

- Route decorator and function: lines 72-77

Purpose:

- Show every booking in the system to the admin

Flow:

1. Calls `db.get_all_bookings()`
2. Converts each DB row into a dict
3. Normalizes each booking via `_augment_booking`
4. Renders `bookings.html`

`db.get_all_bookings()` joins `bookings` with `customers` so that each row can include `is_messageable`.

### 6.4 Booking action handler: `POST /admin/booking_action/<booking_id>`

Function: `booking_action(booking_id)`

Code lines in `admin.py`:

- Route decorator and function: lines 80-126

Purpose:

- Perform admin actions on a booking:
  - cancel
  - confirm
  - mark arrived
  - mark completed
  - mark no-show

This is one of the most important functions in the file because it triggers status changes and external notifications.

#### Case A: `action == 'cancel'`

Flow:

1. Loads the booking using `db.get_booking_by_id_only(booking_id)`
2. Calls `db.admin_cancel_booking(booking_id)`
3. If cancel succeeds:
   - If the booking belongs to a real phone number and is not a walk-in:
     - Checks `db.get_messageability(phone)`
     - If messageable:
       - Imports `send_whatsapp_message` from `notifier`
       - Sends a cancellation WhatsApp
       - Flashes success or Twilio warning
     - If not messageable:
       - Flashes a warning saying no WhatsApp was sent
   - If walk-in or phone missing:
     - Flashes success only
4. If cancel fails:
   - Flashes danger message

What `db.admin_cancel_booking()` does internally:

- Finds the booking if it is still in an active status
- Marks it as `cancelled`
- If it belongs to a combo group, cancels the whole combo group
- Releases related tables by setting them to `Vacant`
- Commits the change
- Calls waitlist auto-allocation for that date and slot

So cancelling from the admin panel has deeper side effects than just changing one field.

#### Case B: action is one of `Confirmed`, `Arrived`, `Completed`, `No-show`

Flow:

1. Calls `db.update_booking_status(booking_id, action)`
2. If the new action is `Confirmed` and the booking has a real customer phone:
   - Checks messageability
   - Sends a WhatsApp confirmation message if possible
   - Flashes success or warning
3. For all other statuses:
   - Flashes `Booking status updated to ...`

What `db.update_booking_status()` does internally:

- Normalizes the new status first
- Updates the booking row
- If status becomes `Arrived`:
  - sets `seated_at` if available
  - marks table as `Occupied`
- If status becomes `Completed`:
  - marks table as `Needs Cleaning`
  - schedules automatic table release later
- If status becomes `cancelled` or `No-show`:
  - marks table as `Vacant`
  - cancels any release timer
  - tries auto-allocating the waitlist

#### Where the `No-show` logic lives

The `No-show` flow starts in `admin.py` and is completed in `db.py`.

- In `admin.py`, the booking action route accepts `No-show` in:
  - `booking_action(...)`: lines 107-108
- That route then calls:
  - `db.update_booking_status(booking_id, action)`
- In `db.py`, the real `No-show` side effects are handled inside `update_booking_status(...)`:
  - marks the related table as `Vacant`
  - cancels any pending table release timer
  - triggers waitlist auto-allocation for that date and slot

So if you are looking for `No-show` behavior in this README, the main explanation is in this section:

- `6.4 Booking action handler`: this section starts at line 200 in `admin.md`

Final behavior:

- After any action, the function redirects back to the referring page
- If no referrer exists, it falls back to the bookings page

### 6.5 Slot management page: `GET|POST /admin/slots`

Function: `manage_slots()`

Code lines in `admin.py`:

- Route decorator and function: lines 133-168

Purpose:

- Show upcoming slots
- Delete a single slot
- Delete all slots for a day
- Clear all future slots

#### GET behavior

Loads:

- `db.get_slots_with_bookings()`
- `db.load_slot_config()`
- today's cafe-local date

Then renders `slots.html` with:

- `slots`
- `schedule`
- `capacity`
- `days_ahead`
- `today_str`

`db.get_slots_with_bookings()` enriches each slot with:

- `booked_guests`
- `max_cap`
- `fill_pct`

#### POST behavior

Looks at `request.form['action']`.

Supported actions:

- `delete`
  Deletes one slot by `slot_id`
- `delete_day`
  Deletes all slots for `target_date`
- `clear_week`
  Deletes all future slots from today onward

Each action writes to the DB through `db.py`, flashes a message, and redirects back to the slot page.

### 6.6 Manual slot regeneration: `POST /admin/slots/regenerate`

Function: `regenerate_slots()`

Code lines in `admin.py`:

- Route decorator and function: lines 171-180

Purpose:

- Rebuild missing future slots using the saved slot schedule config

Flow:

1. Calls `db.auto_generate_slots()`
2. If new slots were inserted:
   - flashes success with inserted count
3. Otherwise:
   - flashes info saying nothing new was generated
4. Redirects back to `/admin/slots`

Important DB behavior:

- `auto_generate_slots()` reads `slot_config.json`
- It generates slots from today forward for `days_ahead`
- It skips duplicates using slot normalization logic

### 6.7 Update slot schedule config: `POST /admin/slots/update_schedule`

Function: `update_slot_schedule()`

Code lines in `admin.py`:

- Route decorator and function: lines 183-231

Purpose:

- Save the admin-edited slot schedule, default capacity, and generation window

This route does not create slot rows directly.
It only updates the config file. The admin must regenerate slots afterward to apply the new schedule to future records.

Flow:

1. Reads `slot_times` as a list
2. Reads `capacity` and `days_ahead`
3. Validates that both numeric fields are integers
4. Validates:
   - capacity is between `1` and `500`
   - days ahead is between `1` and `90`
5. Validates each slot string with this expected pattern:
   - `H:MM AM - H:MM PM`
6. Trims blank entries
7. Deduplicates repeated slot strings while preserving order
8. Rejects an empty final schedule
9. Saves the config with `db.save_slot_config(cleaned, capacity, days_ahead)`
10. Logs an audit message with the current session username
11. Flashes success and redirects back

Stored output:

- The configuration is written to `slot_config.json`

Why this design is useful:

- Admins can change the future slot schedule without directly editing code
- Existing slot rows are not silently rewritten
- Regeneration remains an explicit step

### 6.8 Inline slot capacity update API: `POST /admin/slots/<slot_id>/capacity`

Function: `update_slot_capacity(slot_id)`

Code lines in `admin.py`:

- Route decorator and function: lines 234-247

Purpose:

- Update capacity for one slot asynchronously from the UI

Flow:

1. Reads `capacity` from the form
2. Converts it to `int`
3. Rejects invalid values with JSON `400`
4. Enforces range `1` to `500`
5. Calls `db.update_slot_capacity(slot_id, new_cap)`
6. If updated:
   - returns `{"ok": true, "capacity": new_cap}`
7. If slot not found:
   - returns JSON `404`

Important DB behavior:

- `db.update_slot_capacity()` updates `max_guests` and `total_capacity`
- It does not render HTML; it is intended for inline frontend updates

### 6.9 Export slots CSV: `GET /admin/slots/export`

Function: `export_slots_csv()`

Code lines in `admin.py`:

- Route decorator and function: lines 250-272

Purpose:

- Download all upcoming slots as a CSV file

Flow:

1. Loads upcoming slot data using `db.get_slots_with_bookings()`
2. Builds an in-memory CSV using `csv.writer`
3. Writes columns:
   - Date
   - Time
   - Capacity
   - Booked
   - Available
   - Fill %
4. Returns a Flask `Response` with:
   - `mimetype='text/csv'`
   - attachment filename `slots_export.csv`

### 6.10 Slot stats API: `GET /admin/slots/api/stats`

Function: `slot_stats_api()`

Code lines in `admin.py`:

- Route decorator and function: lines 275-280

Purpose:

- Return aggregated slot fill data as JSON

Flow:

1. Calls `db.get_slot_booking_stats()`
2. Returns the result via `jsonify`

Returned stats are aggregated by slot label and include values like:

- `slot_time`
- `total_slots`
- `total_capacity`
- `total_booked`
- `fill_pct`

### 6.11 Table management: `GET|POST /admin/tables`

Function: `manage_tables()`

Code lines in `admin.py`:

- Route decorator and function: lines 287-333

Purpose:

- Add tables
- Edit tables
- Delete tables
- Show all tables

This route is different from many others because it performs SQL directly inside `admin.py` instead of delegating the whole operation to `db.py`.

#### POST behavior

Opens a DB connection and handles one of three actions:

- `add`
  - Reads `table_number`, `table_name`, `capacity`, `location`
  - Defaults the name to `Table {number}` if not provided
  - Inserts into `tables`
- `edit`
  - Reads `table_id`, `table_name`, `capacity`, `location`
  - Updates the target row
- `delete`
  - Reads `table_id`
  - Deletes that table

Error handling:

- Any exception triggers `rollback()`
- The error message is flashed to the UI
- The connection always closes in `finally`

#### GET behavior

1. Calls `db.get_all_tables()`
2. Renders `tables.html`

### 6.12 Reports page: `GET /admin/reports`

Function: `reports()`

Code lines in `admin.py`:

- Route decorator and function: lines 340-356

Purpose:

- Show booking analytics for a chosen date range

Flow:

1. Uses today's cafe-local date
2. Defaults:
   - `start = today - 7 days`
   - `end = today`
3. Allows both dates to be overridden through query parameters
4. Calls `db.get_report_data(start, end)`
5. Renders `reports.html`

What `db.get_report_data()` calculates:

- total bookings
- total cancelled bookings
- cancellation rate
- total guests
- most used tables
- peak slots
- daily statistics

This is read-only analytics logic. No writes happen here.

### 6.13 Staff management: `GET|POST /admin/staff_management`

Function: `manage_staff()`

Code lines in `admin.py`:

- Route decorator and function: lines 363-424

Purpose:

- Create staff users
- Delete staff users
- Reset staff passwords
- View all staff users

#### POST action: `add`

Flow:

1. Reads `username` and `password`
2. Validates:
   - username length >= 3
   - password length >= 6
3. Hashes the password with `generate_password_hash`
4. Inserts a new user with role `staff`
5. Handles duplicate/DB errors with a generic flash message

#### POST action: `delete`

Flow:

1. Reads `user_id`
2. Deletes the row only if `role = 'staff'`

This is an important safety check because it prevents the delete path from removing admin users by mistake.

#### POST action: `reset`

Flow:

1. Reads `user_id` and `new_password`
2. Validates new password length >= 6
3. Hashes the password
4. Updates only rows where `role = 'staff'`

#### GET behavior

1. Loads all users via `db.get_all_users()`
2. Filters them in Python to only staff users
3. Renders `staff_management.html`

### 6.14 Admin settings: `GET|POST /admin/settings`

Function: `admin_settings()`

Code lines in `admin.py`:

- Route decorator and function: lines 431-468

Purpose:

- Let the currently logged-in admin change their own password
- Show their user record in the settings page

Flow:

1. Reads the current username from `session['username']`
2. Loads the full user row using `db.get_user_by_username(username)`

#### POST action: `change_password`

Validation sequence:

1. Check current password using `check_password_hash`
2. Require new password length >= 6
3. Require `new_password == confirm_password`

If validation passes:

1. Hash the new password
2. Update the user row by username
3. Commit
4. Flash success

Errors:

- DB exceptions are caught and flashed

On both success and failure, the route redirects back to settings.

GET behavior:

- Renders `admin_settings.html` with `user`

## 7. Booking status rules used throughout the file

`admin.py` relies on `utils.normalize_booking_status()` so the system uses a stable canonical set:

- `Pending`
- `Confirmed`
- `Arrived`
- `Completed`
- `No-show`
- `cancelled`

Examples of normalization:

- `active` -> `Confirmed`
- `noshow` -> `No-show`
- `canceled` -> `cancelled`

This matters because:

- templates may branch on status
- DB helper functions treat some statuses as active
- UI messages should use a consistent vocabulary

## 8. Timezone behavior

Several admin routes use `get_cafe_date()` instead of plain `date.today()`.

That means the admin panel is aligned to the configured cafe timezone in `utils.py`:

- `Asia/Kolkata`

This affects:

- today's dashboard numbers
- slot display and deletion logic
- report defaults
- slot generation windows

## 9. Common UI pattern used across the file

Most admin actions follow the same pattern:

1. Read form data from `request.form`
2. Validate inputs
3. Call `db.py` or execute SQL
4. `flash(...)` a success, warning, or error message
5. `redirect(...)` back to a page

This is the classic Flask Post/Redirect/Get pattern. It avoids duplicate form submissions on refresh.

## 10. Templates used by `admin.py`

This file renders the following templates:

- `dashboard.html`
- `bookings.html`
- `slots.html`
- `tables.html`
- `reports.html`
- `staff_management.html`
- `admin_settings.html`

So `admin.py` acts as the controller layer for the admin-side HTML pages.

## 11. JSON endpoints provided by `admin.py`

These routes return JSON instead of HTML:

- `/admin/api/dashboard_data`
- `/admin/slots/<slot_id>/capacity`
- `/admin/slots/api/stats`

These are used for dynamic frontend behavior such as auto-refresh, inline edits, and chart/stat loading.

## 12. Design observations about the current implementation

A few implementation details are useful to know when maintaining this file:

- Most business logic is delegated to `db.py`, which keeps route handlers fairly thin.
- `manage_tables()` is an exception; it performs SQL directly in `admin.py`.
- Booking cancellation and status updates have important side effects:
  - table state changes
  - waitlist auto-allocation
  - possible WhatsApp notifications
- Slot schedule updates are config-only changes until slot regeneration is triggered.
- Flash messages are the main feedback mechanism for admin actions.

## 13. High-level mental model

If you want to understand `admin.py` quickly, think of it like this:

- `dashboard` and `reports` are read-heavy analytics pages
- `bookings`, `slots`, `tables`, and `staff_management` are control panels
- `booking_action` is the operational core for booking lifecycle changes
- `admin_settings` is the self-service account area
- `db.py` contains most of the real data logic, while `admin.py` translates HTTP requests into those operations

## 14. Summary

`admin.py` is the main admin controller for CafeBot. It secures admin-only routes, loads data for templates, handles admin form submissions, triggers booking and slot operations, manages staff accounts, and exposes a few JSON endpoints for live UI behavior. Its overall role is to sit between the admin frontend and the deeper business/database logic stored mostly in `db.py`.
