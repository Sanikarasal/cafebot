# CafeBot ☕

CafeBot is a Python and Flask-based cafe reservation system that combines a WhatsApp booking bot with web dashboards for admins and staff. It lets customers book, view, and cancel table reservations through chat, while the cafe team manages tables, time slots, walk-ins, waitlists, reminders, and daily operations from one SQLite-backed app.

---

## 🌟 Key Features

### For Customers (WhatsApp Bot)

- **Interactive Booking Flow**: Step-by-step conversational interface to book a table.
- **Smart Table Matching**: Automatically assigns the smallest available table that comfortably fits the guest count.
- **Table Combination**: If no single table fits, the system can combine multiple smaller tables (e.g., 2-seater + 4-seater for 5 guests).
- **Slot Capacity Control**: Enforces a maximum guest limit per time slot (configurable, default 30).
- **Conflict Prevention**: Ensures no two bookings overlap for the same table, date, and time slot.
- **Waitlist System**: When all tables are full, users can join a waitlist and get notified automatically when a table opens up.
- **Booking Reminders**: Automated WhatsApp reminder sent 10 minutes before reservation time.
- **Booking Management**: Users can easily view their active bookings and cancel them if their plans change.
- **Mobile-First Simulator**: Includes a web-based WhatsApp simulator (`/`) to test the bot without a phone.

### For Cafe Owners (Admin Dashboard)

- **Secure Authentication**: Admin accounts stored in database with hashed passwords (no hardcoded credentials).
- **Real-Time Dashboard**: View today's metrics (total bookings, guests, available tables, waitlist count) at a glance.
- **Chart.js Analytics**: Visual bar and line charts showing bookings by slot and weekly trends.
- **Live Table Grid**: Visual representation of table availability (🟢 Available / 🔴 Booked).
- **Slot Management**: Dynamically add or remove time slots with configurable max guest capacity.
- **Booking Oversight**: View all upcoming and past bookings, and cancel reservations directly from the panel.
- **Reports & Analytics**: Dedicated reports page with daily statistics, most-used tables, peak booking slots, and cancellation rate.
- **Staff Walk-In Mode**: Dedicated panel for staff to manually create walk-in bookings and assign tables.

---

## 🛠️ Technology Stack

- **Backend**: Python 3, Flask framework
- **Database**: SQLite3 (Serverless, lightweight)
- **Messaging API**: Twilio WhatsApp API (Sandbox)
- **Frontend (Admin Panel)**: HTML5, CSS3, Bootstrap 5 (CDN), Jinja2 Templating
- **Charts**: Chart.js (CDN)
- **Scheduling**: APScheduler (background booking reminders)
- **Security**: Werkzeug password hashing
- **Local Tunnelling**: Ngrok (for local webhook development)

---

## 🚀 Setup & Installation

### 1. Prerequisites

- **Python 3.8+** installed on your machine.
- A **Twilio Account** (Free trial is sufficient for the Sandbox).
- **Ngrok** installed for exposing your local Flask server to the internet.

### 2. Clone & Environment Setup

```bash
# Clone the repository (if applicable)
git clone https://github.com/yourusername/cafebot.git
cd cafebot

# Create a virtual environment
python -m venv venv

# Activate the virtual environment
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# Install required packages
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Create a `.env` file in the root directory and add your Twilio credentials.

```env
SECRET_KEY=your_super_secret_key_here
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token_here
TWILIO_WHATSAPP_NUMBER=whatsapp:+14155238886
```

*(You can find your Account SID and Auth Token in the Twilio Console homepage).*

### 4. Initialize the Database

The system uses SQLite. You must initialize it before running the app.

> **📁 Database Location:** The database file (`cafebot.db`) is automatically created in the **project root directory** (i.e., the same folder as `app.py` and `db.py`). No separate database server is required — SQLite stores everything in this single file.

**For a fresh install** (Warning: Wipes existing database and seeds default tables/slots):

```bash
python init_db.py
```

**For an existing install** (Safe migration, preserves core data while updating schema):

```bash
python migrate_v2.py
```

### 5. Start the Server & Expose to the Internet

Run the Flask application:

```bash
python app.py
```

*Expected Server Output:*

```text
[*] Starting CafeBot Lite Server...
    Running on http://127.0.0.1:5000
    Webhook URL: http://127.0.0.1:5000/webhook
    Admin Panel: http://127.0.0.1:5000/admin/login
    [OK] Reminder scheduler started (every 60s)
```

In a **separate terminal**, start Ngrok to tunnel traffic to port 5000:

```bash
ngrok http 5000
```

*Copy the `Forwarding URL` from ngrok (e.g., `https://1234-abcd.ngrok-free.app`).*

### 6. Connect Twilio Sandbox

1. Log in to Twilio and navigate to **Messaging → Try it out → Send a WhatsApp message**.
2. Connect your personal WhatsApp to the Sandbox by sending the displayed code (e.g., `join purple-monkey`) to the Twilio number.
3. Scroll down to **Sandbox Settings**.
4. In the **"WHEN A MESSAGE COMES IN"** field, paste your Ngrok URL followed by `/webhook`.
   - *Example:* `https://1234-abcd.ngrok-free.app/webhook`
5. Save the settings.

---

## 📱 WhatsApp Booking Flow

Send any message (like "Hi" or "Menu") to your Twilio Sandbox number to start the interaction.

```text
Main Menu
 ├─ 1. Book a Table
 │   ├─ Enter your name
 │   ├─ Select date (Today / Tomorrow / Custom)
 │   ├─ Select time slot (e.g., 10 AM - 11 AM)
 │   ├─ Enter guest count (1–8)
 │   ├─ Choose table / Accept combined tables / Join waitlist
 │   └─ Confirm → ✅ Booking Confirmed (Receives Table #)
 ├─ 2. View Booking (Shows active upcoming reservations)
 ├─ 3. Cancel Booking (Cancels the selected reservation safely)
 └─ 4. Contact Us
```

*Tip: Users can type `*` at any time to go back or `#` to return to the Main Menu.*

---

## 🪑 Table & Capacity Logic

CafeBot smartly assigns tables based on the number of guests.

| Group Size  | Assigned Table Capacity | Table Options (Default Seed) |
| ----------- | ----------------------- | ---------------------------- |
| 1–2 Guests  | 2-Seater Table          | T1 (Window), T2 (Entrance)   |
| 3–4 Guests  | 4-Seater Table          | T3 (AC Zone), T4 (Balcony)   |
| 5–6 Guests  | 6-Seater Table          | T5 (Family Zone)             |
| 7–8 Guests  | 8-Seater Table          | T6 (Private Hall)            |

### Table Combination

If no single table fits the guest count, the system automatically tries to combine smaller available tables:

- **Example**: 5 guests, no 6-seater available → System offers T1 (2-seater) + T3 (4-seater) = 6 seats
- User can accept the combo or choose a different slot

### Slot Capacity Control

Each time slot has a configurable `max_guests` limit (default: 30). Before confirming any booking, the system checks:

- Total guests already booked for that slot
- If adding new guests would exceed the limit, the booking is rejected

### Waitlist System

When all tables are booked for a slot:

1. User is offered to join the waitlist
2. If a booking is cancelled, the next person on the waitlist is automatically notified via WhatsApp
3. The notified user can then rebook through the normal flow

---

## 💻 Admin Dashboard Guide

Manage your cafe from the web portal.

**Access URL:** `http://127.0.0.1:5000/admin/login`
**Default Credentials:** `admin` / `admin123`

| Section             | URL                   | Description                                                                                       |
| ------------------- | --------------------- | ------------------------------------------------------------------------------------------------- |
| **Dashboard**       | `/admin/dashboard`    | Key metrics + Chart.js charts (bookings by slot, weekly trend). Shows waitlist count.              |
| **Bookings**        | `/admin/bookings`     | Full list of all bookings with cancel option.                                                     |
| **Tables Layout**   | `/admin/tables`       | Visual grid showing which tables are booked/available for a given slot.                            |
| **Time Slots**      | `/admin/slots`        | Add/remove time slots with max guest capacity control.                                            |
| **Reports**         | `/admin/reports`      | Analytics: daily stats, most-used tables, peak slots, cancellation rate. Chart.js visualizations. |
| **Staff Walk-In**   | `/admin/staff`        | Manual walk-in booking form. Select date/slot, view availability, assign table.                   |

---

## 🗄️ Database Architecture (`cafebot.db`)

### 📍 Storage Location

CafeBot uses **SQLite** as its database engine — no external database server needed.

| Detail | Value |
| --- | --- |
| **File name** | `cafebot.db` |
| **Location** | Project root directory (e.g., `c:/Users/sanik/dev/cafebot/cafebot.db`) |
| **Created by** | `python init_db.py` (first-time setup) or `python migrate_v2.py` (upgrade) |
| **Managed in** | `db.py` — the `DATABASE = "cafebot.db"` constant at the top of the file |
| **Backup** | Simply copy the `cafebot.db` file to back up all data |

> **⚠️ Note:** The `cafebot.db` file is excluded from version control via `.gitignore`. Do **not** delete it while the server is running — this will corrupt active sessions and bookings.

### Tables

The SQLite database consists of five tables:

1. **`admins`**: Admin accounts with hashed passwords (`username`, `password_hash`).
2. **`tables`**: Permanent table inventory (`table_number`, `capacity`, `location`).
3. **`time_slots`**: Available time slots per date (`date`, `slot_time`, `total_capacity`, `max_guests`).
4. **`bookings`**: Customer reservations (`phone`, `name`, `date`, `slot_time`, `seats`, `table_number`, `status`, `combo_group`, `reminder_sent`).
5. **`waitlist`**: Waitlist entries (`phone`, `name`, `date`, `slot_time`, `guests`, `status`).

---

## 📂 Project Structure

```text
cafebot/
├── app.py
├── auth.py
├── admin.py
├── staff.py
├── ops.py
├── bot.py
├── db.py
├── utils.py
├── notifier.py
├── scheduler.py
├── payment.py
├── init_db.py
├── migrate_tables.py
├── migrate_soft_cancel.py
├── migrate_v2.py
├── migrate_v3_roles.py
├── migrate_v4_customers.py
├── migrate_v5_schema_fix.py
├── migrate_v6_conversations.py
├── migrate_v7_booking_groups.py
├── migrate_v8_is_auto_allocated.py
├── migrate_v9_payment.py
├── migrate_v10_seated_at.py
├── diagnostic.py
├── update_admin_script.py
├── update_db_script.py
├── update_tables_route.py
├── slot_config.json
├── requirements.txt
├── .env
├── cafebot.db
└── templates/
    ├── base.html
    ├── login.html
    ├── forgot_password.html
    ├── dashboard.html
    ├── bookings.html
    ├── slots.html
    ├── tables.html
    ├── reports.html
    ├── staff_dashboard.html
    ├── staff_management.html
    ├── ops_base.html
    ├── floor.html
    ├── bookings_ops.html
    ├── tables_ops.html
    ├── waitlist_ops.html
    └── customers.html
```

### How Each Main File Works

#### App bootstrap

- **`app.py`**: Main Flask entry point. Loads environment variables, creates the app, registers all blueprints, starts scheduler jobs, and runs the server.
- **`requirements.txt`**: Python dependencies required by the project.
- **`.env`**: Stores secrets and local configuration such as Flask, Twilio, and payment credentials.

#### Authentication and shared helpers

- **`auth.py`**: Login, logout, forgot-password flow, and route protection with admin/staff access decorators.
- **`utils.py`**: Shared helpers for timezone handling, booking status normalization, slot parsing, slot comparison, and slot sorting.

#### Customer booking flow

- **`bot.py`**: WhatsApp booking state machine. Handles user conversation flow, booking creation, viewing bookings, cancellation, waitlist prompts, payment state, and the `/webhook` endpoint.
- **`notifier.py`**: Sends WhatsApp messages through the Twilio client.
- **`payment.py`**: Creates Razorpay payment links and checks payment status.

#### Web dashboards

- **`admin.py`**: Admin routes for dashboard metrics, booking management, slot management, reports, table management, and staff account management.
- **`staff.py`**: Staff POS dashboard routes for live table status, walk-in seating, check-in, and checkout.
- **`ops.py`**: Operations dashboard routes and JSON APIs for floor control, bookings, customers, waitlist handling, table updates, and quick seat/checkout actions.

#### Data layer

- **`db.py`**: Central SQLite data layer. Contains booking logic, waitlist logic, user queries, table availability checks, report queries, runtime schema helpers, and formatting helpers.
- **`cafebot.db`**: SQLite database file that stores all application data.
- **`slot_config.json`**: Stores slot-generation configuration used for future slot creation.

#### Background jobs

- **`scheduler.py`**: Runs recurring jobs like booking reminders and automatic no-show handling.

#### Setup and migrations

- **`init_db.py`**: Creates a fresh database and seeds default users, tables, and starter slots.
- **`migrate_tables.py`**: Legacy migration for older table schema changes.
- **`migrate_soft_cancel.py`**: Migration/helper related to cancellation behavior.
- **`migrate_v2.py`**: Early non-destructive schema migration.
- **`migrate_v3_roles.py`**: Adds role support for users.
- **`migrate_v4_customers.py`**: Adds customer/session tracking support.
- **`migrate_v5_schema_fix.py`**: Repairs schema drift and backfills missing booking columns.
- **`migrate_v6_conversations.py`**: Adds persistent conversation state storage.
- **`migrate_v7_booking_groups.py`**: Adds grouped/combo booking support.
- **`migrate_v8_is_auto_allocated.py`**: Adds auto-allocation tracking for waitlist-driven bookings.
- **`migrate_v9_payment.py`**: Adds payment-related schema support.
- **`migrate_v10_seated_at.py`**: Adds seated timestamp support for accurate occupied/overdue timing.

#### Maintenance scripts

- **`diagnostic.py`**: Local debugging and diagnostics helper.
- **`update_admin_script.py`**: Development helper for admin-side updates.
- **`update_db_script.py`**: Development helper for database updates.
- **`update_tables_route.py`**: Development helper for table-route updates.

### Templates Guide

- **`templates/base.html`**: Shared shell for the main admin and staff UI.
- **`templates/login.html`** and **`templates/forgot_password.html`**: Authentication screens.
- **`templates/dashboard.html`**: Admin dashboard with metrics and charts.
- **`templates/bookings.html`**: Admin booking list and booking actions.
- **`templates/slots.html`**: Slot management UI and capacity controls.
- **`templates/tables.html`**: Admin table layout and table management page.
- **`templates/reports.html`**: Reporting and analytics page.
- **`templates/staff_dashboard.html`**: Staff POS dashboard for live seating and checkout.
- **`templates/staff_management.html`**: Admin page for managing staff accounts.
- **`templates/ops_base.html`**: Shared layout for operations pages.
- **`templates/floor.html`**: Floor-control page for live tables and quick actions.
- **`templates/bookings_ops.html`**: Operations-side booking management page.
- **`templates/tables_ops.html`**: Operations-side table management page.
- **`templates/waitlist_ops.html`**: Waitlist management page.
- **`templates/customers.html`**: Customer summaries and history page.

---

## 🛠️ Troubleshooting

- **Twilio Bot Not Responding?** Ensure Ngrok is running and your Sandbox Webhook URL matches exactly (including `https` and `/webhook`).
- **`Port 5000 already in use` error?** Kill the existing Python process running on port 5000. On Windows: `Stop-Process -Name python -Force`.
- **Database Locked Error?** SQLite handles one writer at a time. If testing heavily concurrently, you may see this. Restarting the server usually clears stalled locks.
- **Bot gets stuck in a loop?** User sessions are stored server-side. Restarting the Flask app clears all active chat states.
- **Reminder not sending?** Ensure APScheduler is installed (`pip install APScheduler==3.10.4`) and your Twilio credentials are set in `.env`.
