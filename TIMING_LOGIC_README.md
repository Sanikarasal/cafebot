# CafeBot Logic Architecture: Timing, Slots & Automation

This document outlines the core libraries, built-in APIs, and internal modules that drive the automated logic for Live Timing, Auto Slot Generation, Reminders, and No-Show releases in the CafeBot system. **Note: This strictly documents the logical flow and dependencies, excluding code implementations.**

---

## 1. Live Timing & Timezone Management
The core timing engine ensures that every database entry, notification, and scheduler check operates uniformly according to the local timezone of the cafe, regardless of where the server is hosted.

* **Core Python Libraries:** `datetime`, `re` (Regular Expressions)
* **Third-Party Libraries:** `pytz` (Timezone Management)
* **Resident Modules:** `utils.py`
* **Logic Flow:**
  * **Absolute Time Truth:** The system forces a designated localized timezone (e.g., `Asia/Kolkata`) via `pytz`. It queries UTC time first, then casts it to the local timezone.
  * **Format Parsing:** The standard `re` library handles varied, unstructured slot time text inputs (e.g., from WhatsApp) and standardizes them.
  * **Time Mapping:** Uses boundary mapping (`timedelta`) to match simple strings to exact, timezone-aware internal chronological periods.

---

## 2. Background Task Automation (The Heartbeat)
A standalone scheduler attaches itself to the Flask web server to ensure that background tasks process predictably without blocking customer requests.

* **Third-Party Libraries:** `APScheduler` (specifically `BackgroundScheduler`)
* **Resident Modules:** `app.py`
* **Logic Flow:**
  * Upon system initialization, the `BackgroundScheduler` mounts parallel threaded background jobs.
  * Each job (Reminders, Slot Generation) is configured to observe a strict `interval` sequence (e.g., every 60 seconds, or 30 minutes).

---

## 3. Auto Slot Generation
Maintains the upcoming booking capacity automatically so that administration does not have to manually input time slots per day.

* **Core Python Libraries:** `os`, `json`, `datetime`
* **Resident Modules:** `db.py`, `app.py`
* **Logic Flow:**
  * **Configuration:** System thresholds (max guests, default schedules, days ahead to buffer) are maintained in a persistent JSON document (`slot_config.json`).
  * **Extrapolation Cycle:** Triggered by the Background Scheduler every 30 minutes.
  * **Conflict Avoidance:** Utilizes the `sqlite3` driver to fetch existing slots for future dates. Uses `datetime` arithmetic to identify missing days ahead, mapping out and injecting only non-duplicative rows for the cafe's opening times.

---

## 4. Automated Booking Reminders
Ensures customers receive a timely WhatsApp push notification shortly before their scheduled arrival.

* **External APIs:** Twilio Messaging API (`twilio` library) for WhatsApp
* **Core Python Libraries:** `sqlite3`
* **Resident Modules:** `scheduler.py`, `notifier.py`
* **Logic Flow:**
  * **Polling:** Scans every 60 seconds.
  * **Window Calculation:** Calculates a future 10-minute boundary window based on the current synchronized local time.
  * **Filtration:** Queries the database for pending bookings where the `reminder_sent` boolean is false.
  * **Dispatching:** If the active localized time overlaps with the computed notification window, the pipeline triggers the Twilio API payload via `notifier.py` and subsequently locks the database row to prevent duplicated alerts.

---

## 5. Auto No-Show Reclamations
Protects the restaurant's operational capacity by reclaiming tables when a party does not arrive on schedule.

* **Core Python Libraries:** `sqlite3`, `datetime`
* **Resident Modules:** `scheduler.py`, `utils.py`, `notifier.py`
* **Logic Flow:**
  * **Polling:** Runs concurrently every 60 seconds.
  * **Grace Period Check:** Acquires all pending and confirmed bookings for the present day. Adds an internal fixed integer (Grace Minutes) to the parsed slot start time.
  * **State Mutation:** If the live local time exceeds the expanded grace boundary limit, the logic transitions the entry to a "No-show" status via SQLite.
  * **Table Release:** Frees the associated physical seating layout coordinate (`table_number`), returning status to "Vacant" so floor operations can seat walk-in traffic.
  * **Notice:** Optionally pings the customer utilizing the Twilio API that their table is forfeit.
