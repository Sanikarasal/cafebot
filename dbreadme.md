# db.py Logic and Explanation

This document explains the purpose, structure, and logic of `db.py` without changing any code.

## Overall Purpose

`db.py` is the data-access and booking-logic layer for the cafe system. It does much more than simple database CRUD. It is responsible for:

- opening SQLite connections
- adapting rows into Python dictionaries
- applying small runtime schema fixes
- managing Twilio conversation persistence
- checking slot and table availability
- creating normal bookings, combo bookings, and walk-in seatings
- cancelling bookings and triggering waitlist auto-allocation
- managing table state transitions such as `Vacant`, `Occupied`, and `Needs Cleaning`
- generating and editing future time slots
- powering admin dashboard, reporting, and customer summary screens

In short, `db.py` is the operational core of the application.

## Main Logic Quick Map With Code Lines

If you want to understand the most important business logic in `db.py`, start with these blocks first.

- `get_db_connection()` and `_ensure_runtime_schema(conn)`: `db.py` lines 22-63
  Opens SQLite, converts rows to dictionaries, and applies the runtime schema safety check before any other logic runs.
- `_aggregate_booking_rows(rows, conn)`: `db.py` lines 228-245
  This is the core combo-booking aggregation helper. It prevents multi-table reservations from being double-counted in capacity, dashboards, and reports.
- `get_available_slots(date, filter_past=False)`: `db.py` lines 417-466
  Builds the customer-visible slot list by checking current bookings, combo totals, capacity, and optionally filtering out past slots for today.
- `check_slot_capacity(date, slot_time, new_guests)`: `db.py` lines 505-519
  Central slot-capacity guard used before new bookings are accepted.
- `get_available_tables(date, slot_time, guests)`: `db.py` lines 542-568
  Finds free tables that can fit the party size for a given slot.
- `get_combined_tables(date, slot_time, guests)`: `db.py` lines 570-615
  Handles the multi-table selection path for larger parties using a greedy capacity-first approach.
- `create_booking(...)`: `db.py` lines 676-757
  Main single-table booking write path. It prevents duplicates, prevents table conflicts, re-checks slot existence, re-checks slot capacity, and inserts a `Pending` booking inside a transaction.
- `atomic_quick_seat(...)`: `db.py` lines 759-842
  Fast staff seating flow. It creates an `Arrived` booking immediately and marks the table `Occupied`.
- `instant_walk_in_seat(...)`: `db.py` lines 844-924
  Walk-in seating logic. It seats a guest without needing a pre-generated slot and marks the table `Occupied` right away.
- `create_combo_booking(...)`: `db.py` lines 926-1040
  Main multi-table booking path. It creates one logical reservation across several tables using a shared `combo_group`.
- `cancel_booking_by_id(phone, booking_id)`: `db.py` lines 1143-1202
  Customer cancellation path. It blocks past-start cancellations, frees the table, cancels combo siblings, and triggers waitlist upgrade logic.
- `_auto_allocate_waitlist(date, slot_time)`: `db.py` lines 1204-1332
  One of the most critical automation flows. It re-checks capacity and table availability inside a transaction, allocates a free table, inserts a confirmed booking, updates the waitlist row, and sends WhatsApp only after commit.
- `auto_generate_slots(days_ahead=None)`: `db.py` lines 1617-1664
  Future slot generation logic. It reads `slot_config.json`, normalizes slot labels, and inserts only missing future slots.
- `admin_cancel_booking(booking_id)`: `db.py` lines 1846-1892
  Admin-side cancellation flow. It does not require phone ownership, but it still frees tables and triggers waitlist auto-allocation.
- `get_dashboard_metrics(today_date)`: `db.py` lines 1894-1943
  Builds the headline numbers used by the admin dashboard.
- `get_report_data(start_date, end_date)`: `db.py` lines 1999-2072
  Builds the reporting payload for date-range analytics, using combo-aware counting for accurate totals.
- `update_booking_status(booking_id, new_status)`: `db.py` lines 2078-2132
  Main floor-operations lifecycle function. It maps booking status changes to table-state changes:
  `Arrived -> Occupied`, `Completed -> Needs Cleaning`, `cancelled/No-show -> Vacant`, and it also triggers waitlist auto-allocation when needed.

## Main Logic Reading Order

If you are reading `db.py` for the first time, this order gives the clearest picture of the system:

1. `get_db_connection()` and `_ensure_runtime_schema(conn)`
2. `_aggregate_booking_rows(rows, conn)`
3. `get_available_slots(...)`, `check_slot_capacity(...)`, `get_available_tables(...)`, `get_combined_tables(...)`
4. `create_booking(...)` and `create_combo_booking(...)`
5. `cancel_booking_by_id(...)` and `_auto_allocate_waitlist(...)`
6. `auto_generate_slots(...)`
7. `admin_cancel_booking(...)`, `get_dashboard_metrics(...)`, `get_report_data(...)`
8. `update_booking_status(...)`

## Main Design Pattern

The file is organized into logical groups of helper functions. Most functions follow the same pattern:

- open a database connection with `get_db_connection()`
- run SQL queries
- convert or enrich the result in Python
- commit if data changed
- close the connection in `finally` or just before return

The more important workflow functions also contain business rules, not just SQL. Examples:

- preventing duplicate bookings
- preventing concurrent booking races with `BEGIN IMMEDIATE`
- deduplicating combo-table bookings when counting guests
- releasing tables after service completion
- auto-promoting users from the waitlist when capacity opens up

## Database Connection and Runtime Schema

### `get_db_connection()`

- Opens the SQLite database `cafebot.db`.
- Sets `row_factory` so every row is returned as a dictionary instead of a tuple.
- Calls `_ensure_runtime_schema(conn)` before returning.

This means every caller gets a ready-to-use connection and can refer to columns by name like `row["status"]`.

### `_has_column(conn, table, column)` and `_has_table(conn, table)`

- Small schema-inspection helpers.
- Used to make the code tolerant of evolving schemas and older databases.

### `_ensure_runtime_schema(conn)`

- Applies a runtime schema check focused on the `bookings` table.
- Adds the `seated_at` column if it does not exist.
- Backfills `seated_at` for rows already marked `Arrived` by copying from `updated_at` or `created_at`.
- Uses the `_RUNTIME_SCHEMA_READY` flag so the migration logic only runs once per process.

This is a safety layer so the app can still run even if the database was created from an older schema version.

## Common Internal Helpers

### `_active_status_params()`

- Gets the list of statuses considered “active” from `utils.get_active_booking_statuses()`.
- Also returns a SQL placeholder string like `"?,?,?"`.

This is reused everywhere the app needs to query current reservations while excluding cancelled or inactive rows.

### `_now_iso()` and `_now_cafe_iso()`

- `_now_iso()` returns a UTC timestamp string.
- `_now_cafe_iso()` returns the cafe-local timestamp using `get_cafe_time()`.

The file uses both because some fields are stored as generic timestamps while others care about local service timing.

### `_normalize_slot_value(slot_time)`

- Normalizes slot labels so comparisons are consistent.
- Falls back to the raw trimmed string if normalization fails.

This matters because slot strings are used in both display and matching logic.

## Table Release Scheduling and Service Timer Helpers

### `_cancel_scheduled_table_release(table_number)`

- Cancels a pending delayed table-release timer if one exists.

### `_schedule_table_release(table_number, delay_seconds=300)`

- Starts a background timer using `threading.Timer`.
- After the delay, it checks whether the table is still in `Needs Cleaning`.
- If yes, it automatically marks the table `Vacant`.

This is the automatic “cleaning finished” release flow.

### `force_release_table(table_number)`

- Immediately marks a table `Vacant`.
- Cancels any pending auto-release timer.

### `parse_booking_datetime(dt_value)`, `get_seated_elapsed_minutes(...)`, and `format_service_timer(...)`

- These functions support staff-facing time-tracking logic.
- They parse stored timestamps, convert them into cafe timezone, compute elapsed service minutes, and format that into strings like `Just seated`, `15 min`, or `Overdue: 1h 10m`.

## Combo Booking Aggregation Logic

One of the most important design ideas in `db.py` is combo booking support.

When a party spans multiple tables:

- the system stores one booking row per table
- all related rows share the same `combo_group`
- guest totals must not be double-counted when reading analytics or slot capacity

### `_booking_group_totals(conn, combo_groups, rows=None)`

- Computes total guest counts for combo groups.
- Prefers reading totals from the `booking_groups` table when available.
- Falls back to deriving totals from booking rows when needed.

### `_aggregate_booking_rows(rows, conn)`

- Walks booking rows and returns:
- total logical booking count
- total guest count

For normal bookings, each row counts normally. For combo bookings, it counts only the first row per `combo_group`, then uses the total guest count for that group.

### `get_combo_group_totals(combo_groups)`

- Public wrapper around `_booking_group_totals(...)`.

This aggregation layer is what keeps reports and slot-capacity checks accurate even when one reservation uses multiple tables.

## Twilio Session Management

### `update_customer_session(phone)`

- Inserts or updates the customer's `last_message_timestamp`.
- Used to track the 24-hour WhatsApp/Twilio reply window.

### `get_messageability(phone)`

- Checks whether the customer has messaged within the last 24 hours.
- Returns `True` only if outbound messaging is still allowed.

## WhatsApp Conversation Persistence

These functions back the chatbot’s stateful conversation flow.

### `get_conversation(phone)`

- Reads one conversation row from the `conversations` table.
- Safely handles missing table or malformed JSON.
- Returns a normalized dictionary with `phone`, `state`, `data`, and `updated_at`.

### `save_conversation(phone, state, data=None)`

- Upserts conversation state and data.
- Uses JSON for the dynamic `data` field.
- Falls back to manual `UPDATE` then `INSERT` if SQLite’s `ON CONFLICT` path is unavailable.

### `clear_conversation(phone)`

- Deletes the conversation row for that phone number.

### `update_conversation_data(phone, **kwargs)`

- Loads the current conversation data, merges new keys, then saves it back.

## Admin Authentication Helpers

### `get_user_by_username(username)`

- Looks up an admin user row by username.

### `create_user(username, password)`

- Hashes the password with Werkzeug and inserts a new admin user.
- Returns `False` if the username already exists.

## Slot Availability Logic

### `get_available_slots(date, filter_past=False)`

- Fetches all time slots for the given date.
- Loads active bookings for the same date.
- Uses `_aggregate_booking_rows(...)` to compute how many guests are already occupying each slot.
- Computes remaining seats from `max_guests` or `total_capacity`.
- If `filter_past=True`, it removes slots whose start time has already passed today.
- Returns only slots with remaining capacity.

This is the function the bot uses to show customers their date-specific time choices.

### `get_slot(date, slot_time)`

- Finds one slot row matching a given date and normalized slot label.

## Slot Capacity Control

### `DEFAULT_MAX_GUESTS_PER_SLOT`

- Fallback max guest capacity used when a slot does not define one explicitly.

### `get_slot_booked_guests(date, slot_time)`

- Returns the actual number of guests already occupying a slot.
- Uses combo-aware aggregation logic.

### `check_slot_capacity(date, slot_time, new_guests)`

- Checks whether adding a new party would exceed slot capacity.
- Returns `(allowed, remaining)`.

This gives the bot and admin tools a second safety check before creating bookings.

## Capacity and Table Selection Helpers

### `get_required_capacity(guests)`

- Maps party size to the smallest useful table size.
- Example: `1-2 -> 2`, `3-4 -> 4`, `5-6 -> 6`, `7-8 -> 8`.

### `get_available_tables(date, slot_time, guests)`

- Returns tables with sufficient capacity that are not already booked in that slot.
- Filters bookings using active statuses only.

### `get_combined_tables(date, slot_time, guests)`

- Tries to solve larger parties by combining multiple free tables.
- Uses a greedy algorithm: smallest tables first until capacity is enough.

This is practical and simple, though not globally optimal in the mathematical sense.

### `get_table_info(table_number)`, `get_all_tables()`, and `get_table_status(date, slot_time)`

- `get_table_info(...)` returns one table row.
- `get_all_tables()` returns the full table list.
- `get_table_status(...)` returns every table plus an `is_booked` flag for a specific date/slot, useful for admin views.

## Booking Creation Logic

### `create_booking(phone, name, date, slot_time, seats, table_number=None, combo_group=None, source='bot')`

- Creates a normal reservation row.
- Starts with `BEGIN IMMEDIATE` to reduce race conditions.
- Rejects duplicate bookings by the same phone for the same date/slot.
- Rejects conflicts where the selected table was just booked by someone else.
- Verifies the slot still exists.
- Re-checks slot capacity before inserting.
- Stores the booking as `Pending`.
- Dynamically includes optional columns like `source`, `created_at`, and `updated_at` if present in the schema.

This is the standard reservation write path used by the bot.

### `atomic_quick_seat(...)`

- Staff-facing fast seating helper.
- Also uses `BEGIN IMMEDIATE`.
- Creates an `Arrived` booking directly instead of a `Pending` one.
- Marks the table `Occupied`.
- Saves `seated_at` if the schema supports it.

This is essentially a faster walk-in or front-desk seating path.

### `instant_walk_in_seat(...)`

- Creates a walk-in booking immediately based on the current cafe time.
- Validates guest count and table capacity.
- Requires the table to be currently `Vacant`.
- Generates a special slot label like `6:25 PM (Walk-In)`.
- Inserts an `Arrived` booking and marks the table `Occupied`.

This path is independent from pre-generated reservation slots.

### `create_combo_booking(...)`

- Creates one logical booking across multiple tables.
- Generates a short `combo_group` ID.
- Prevents duplicates for the same phone/date/slot.
- Re-checks slot availability and slot capacity.
- Splits the guest count across the selected tables so each row stores only the seats assigned to that table.
- Optionally inserts a summary row into `booking_groups`.
- Inserts one `Pending` booking row per table.

This function is a core reason the aggregation helpers exist.

## Booking Read Helpers

### `get_user_bookings(phone)`

- Returns active bookings for a user.
- Deduplicates combo bookings so the user sees one logical booking instead of one row per table.
- Replaces per-row seat counts with the combo total when needed.

### `get_booking_for_user(phone, booking_id)`

- Fetches a specific active booking for a user.
- If it belongs to a combo group, it rewrites the `seats` field to the true total guests.

### `get_combo_tables(combo_group)`

- Returns all table numbers linked to a combo booking.

## Payment Link and Pending Booking Cleanup

### `set_booking_payment_link(booking_id, link_id)`

- Saves a payment-link ID to the booking.
- If the booking is part of a combo group, it updates all sibling rows too.

### `delete_pending_booking(booking_id)`

- Hard-deletes a pending booking after abandoned or failed payment.
- If it is a combo booking, it deletes all sibling booking rows and the `booking_groups` record.

## Cancellation and Waitlist Upgrade Logic

### `cancel_booking_by_id(phone, booking_id)`

- Lets a customer cancel their own booking.
- Ensures the booking belongs to that user and is still active.
- Blocks cancellation for past bookings or bookings whose slot already started today.
- Cancels all rows in a combo booking when needed.
- Frees the table status back to `Vacant`.
- Calls `_auto_allocate_waitlist(...)` after successful cancellation.

### `_auto_allocate_waitlist(date, slot_time)`

- Looks for pending waitlist entries in FIFO order.
- Re-checks capacity and table availability inside a transaction.
- Finds the smallest fitting free table.
- Inserts a confirmed booking for the waitlisted guest.
- Marks the table `Reserved`.
- Marks the waitlist row as `allocated`.
- Sends a WhatsApp confirmation only after the transaction is committed.

This is one of the most business-critical automation functions in the file.

### `cancel_user_booking(phone)`

- Legacy compatibility helper.
- Cancels the latest booking for a user by delegating to `cancel_booking_by_id(...)`.

## Waitlist Functions

### `add_to_waitlist(phone, name, date, slot_time, guests)`

- Inserts a new waitlist request.
- Prevents duplicate pending entries for the same phone/date/slot.

### `get_next_waitlist(date, slot_time)`

- Returns the oldest pending waitlist entry for a specific slot.

### `mark_waitlist_notified(waitlist_id)`

- Updates a waitlist entry to `notified`.

### `get_user_waitlist(phone)`

- Returns pending waitlist entries for one user.

### `get_waitlist_entries(date=None, status=None)`

- Flexible admin query for waitlist rows, with optional filters.

### `get_waitlist_entry(waitlist_id)` and `update_waitlist_status(waitlist_id, new_status)`

- Read one waitlist row or update its status.

## Admin Booking and Customer Helpers

### `get_all_bookings()` and `get_recent_bookings(limit=5)`

- Return booking rows for admin screens.
- Join against `customers` so each row includes an `is_messageable` flag.

### `get_customer_summaries()`

- Builds customer-level summary cards from booking history.
- Excludes walk-ins from customer summaries.
- Calculates:
- visit count
- last visit date
- average party size

It also uses combo-aware aggregation so multi-table bookings do not inflate counts.

### `get_booking_by_id_only(booking_id)`

- Simple direct booking lookup by ID.

### `get_all_slots()`

- Removes old `time_slots` and stale `waitlist` rows before reading.
- Returns all remaining slots ordered by date and time.

This function mixes cleanup with retrieval, so it acts like a lightweight maintenance step.

## Auto Slot Generation and Slot Config

The lower middle of the file handles slot generation from `slot_config.json`.

### Constants

- `DEFAULT_SLOT_SCHEDULE` defines the fallback daily schedule.
- `DEFAULT_SLOT_CAPACITY` defines default slot capacity.
- `DEFAULT_GENERATE_DAYS` defines how far ahead slots should be generated.
- `_SLOT_CONFIG_PATH` points to `slot_config.json`.

### `load_slot_config()`

- Reads `slot_config.json`.
- Falls back to defaults if the file is missing or invalid.

### `save_slot_config(schedule, capacity, days_ahead)`

- Saves updated slot-generation settings back to JSON.

### `auto_generate_slots(days_ahead=None)`

- Generates future `time_slots` using the configured schedule.
- Skips duplicates by comparing normalized slot labels.
- Inserts capacity fields into each new slot row.

### `add_time_slot(...)`, `delete_time_slot(...)`, `delete_slots_for_date(...)`, `clear_all_future_slots()`, and `update_slot_capacity(...)`

- These are admin maintenance functions for manual slot control.
- They let staff add, delete, bulk-delete, wipe future slots, or change slot capacity.
- Several of them also print audit-style log messages.

## Slot Analytics

### `get_slot_booking_stats()`

- Aggregates future slots by slot label.
- Computes total slot count, total capacity, booked guests, and fill percentage.

### `get_slots_with_bookings()`

- Returns each future slot row enriched with:
- `booked_guests`
- `max_cap`
- `fill_pct`

This is useful for admin dashboards and planning views.

## Admin Cancellation and Dashboard Metrics

### `admin_cancel_booking(booking_id)`

- Admin version of cancellation.
- Does not require a matching phone number.
- Cancels combo siblings too.
- Frees tables.
- Triggers waitlist auto-allocation afterward.

### `get_dashboard_metrics(today_date)`

- Computes headline numbers for the dashboard:
- total tables
- today’s booking count
- available tables
- today’s guest count
- pending waitlist count
- estimated revenue for the day

Revenue is currently calculated as `booking count * 100` for qualifying non-walk-in rows.

## Charts and Reports

### `get_bookings_by_slot_today(today_date)`

- Groups today’s active bookings by normalized slot label.
- Returns both booking count and guest count per slot.
- Sorts labels using `sort_slot_labels(...)`.

### `get_weekly_booking_trend()`

- Returns booking counts for the last seven days.

### `get_report_data(start_date, end_date)`

- Builds a date-range reporting payload.
- Computes:
- total bookings
- total cancellations
- cancellation rate
- total guests
- most used tables
- peak slots
- per-day totals

It uses combo-aware aggregation so reporting reflects logical bookings rather than raw rows.

## Staff Status and Table State Helpers

### `update_booking_status(booking_id, new_status)`

- Normalizes the new booking status first.
- Updates the booking row.
- Sets `seated_at` when a booking becomes `Arrived`.
- Updates the linked table state:
- `Arrived -> Occupied`
- `Completed -> Needs Cleaning`
- `cancelled` or `No-show -> Vacant`
- Cancels pending release timers when appropriate.
- Schedules a delayed auto-release when a booking becomes `Completed`.
- Triggers waitlist auto-allocation when a booking becomes `cancelled` or `No-show`.

This function connects booking lifecycle changes directly to floor operations.

### `update_table_status(table_number, new_status)`

- Direct manual table-status update helper.
- Cancels any pending auto-release timer for statuses that imply manual control.

### `get_all_users()`

- Returns all admin users ordered by creation time.

### `get_today_bookings(today_date)`

- Returns all bookings for one day.
- Includes the `is_messageable` flag from the `customers` table.

## Important Business Rules in db.py

The most important application rules enforced in this file are:

- a customer cannot hold two active bookings for the same slot
- a table cannot be double-booked for the same slot
- slot capacity cannot be exceeded
- combo-table bookings must count as one logical reservation
- waitlist auto-allocation must happen only after safe transactional re-checks
- tables move through operational statuses based on booking status
- completed tables are automatically released after a cleaning delay

## High-Level Flow Examples

### Reservation flow

- bot asks for date, slot, seats, and table
- `db.py` validates slot capacity and table availability
- booking is created as `Pending`
- payment link is attached
- later the booking status can move to `Confirmed`, `Arrived`, then `Completed`

### Combo booking flow

- no single table fits
- multiple tables are selected
- one row per table is created with a shared `combo_group`
- read/report functions merge those rows back into one logical booking

### Waitlist upgrade flow

- customer joins waitlist for a full slot
- another booking gets cancelled or marked no-show
- `_auto_allocate_waitlist(...)` finds capacity and a matching table
- the system inserts a confirmed booking and notifies the customer

### Floor operations flow

- staff marks booking `Arrived`
- table becomes `Occupied`
- staff marks booking `Completed`
- table becomes `Needs Cleaning`
- delayed timer later moves table back to `Vacant`

## Final Summary

`db.py` is not just a utility file. It is the system’s business-rules engine. It combines:

- persistence
- concurrency protection
- booking validation
- table allocation
- waitlist automation
- slot generation
- dashboard analytics
- operational status handling

That is why so many parts of the app depend on it directly.
