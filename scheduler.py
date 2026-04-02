"""
scheduler.py
Background jobs:
  1. check_and_send_reminders   — sends WhatsApp reminder 10 min before booking
  2. check_and_auto_noshow      — marks Pending/Confirmed bookings as No-show if
                                   customer hasn't arrived 20 min after slot start
"""

from datetime import timedelta
import sqlite3

from notifier import send_whatsapp_message
from utils import get_active_booking_statuses, get_cafe_time, parse_slot_time, normalize_slot_label

DATABASE = "cafebot.db"

# Grace period after slot start before marking a booking No-show (minutes)
NOSHOW_GRACE_MINUTES = 20


def _has_column(conn, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


def check_and_send_reminders():
    """
    Scan active bookings and send a reminder if the booking starts within 10 minutes.
    Only sends once per booking (tracks via `reminder_sent` flag).
    """
    now = get_cafe_time()  # timezone-aware (CAFE_TIMEZONE)
    reminder_window = now + timedelta(minutes=10)

    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        statuses = get_active_booking_statuses()
        placeholders = ",".join("?" * len(statuses))
        has_twilio_last_response = _has_column(conn, "bookings", "twilio_last_response")
        bookings = cursor.execute(
            f"""
            SELECT * FROM bookings
            WHERE status IN ({placeholders}) AND reminder_sent = 0
            """,
            statuses,
        ).fetchall()

        for booking in bookings:
            booking_date_str = booking["date"]
            slot_time_str = booking["slot_time"].strip() if booking["slot_time"] else ""

            # parse_slot_time returns timezone-aware datetimes — compare directly with now
            booking_start, _ = parse_slot_time(slot_time_str, booking_date_str)
            if booking_start is None:
                continue

            # Send reminder if booking is within the next 10 minutes
            if now <= booking_start <= reminder_window:
                display_slot = normalize_slot_label(slot_time_str) or slot_time_str
                message = (
                    f"⏰ Reminder!\n\n"
                    f"Hello {booking['name']},\n"
                    f"Your table booking at CoziCafe is scheduled at {display_slot}.\n"
                    f"📅 Date: {booking_date_str}\n"
                    f"👥 Guests: {booking['seats']}\n\n"
                    f"We look forward to seeing you! ☕✨"
                )

                success, msg = send_whatsapp_message(booking["phone"], message)

                if has_twilio_last_response:
                    cursor.execute(
                        "UPDATE bookings SET twilio_last_response = ? WHERE id = ?",
                        (msg, booking["id"]),
                    )

                if success:
                    cursor.execute(
                        "UPDATE bookings SET reminder_sent = 1 WHERE id = ?",
                        (booking["id"],),
                    )
                    conn.commit()
                    print(f"✅ Reminder sent for booking #{booking['id']}")
                else:
                    conn.commit()
                    print(f"⚠️ Reminder failed for booking #{booking['id']}: {msg}")

    except Exception as e:
        print(f"❌ Reminder check error: {e}")
    finally:
        conn.close()


def check_and_auto_noshow():
    """
    Mark bookings as No-show if:
    - The booking is for today
    - Status is still Pending or Confirmed (not Arrived, Completed, cancelled)
    - Slot start time was more than NOSHOW_GRACE_MINUTES minutes ago
    - Table is freed so it can be reused
    """
    from utils import get_cafe_date
    now = get_cafe_time()  # timezone-aware
    today_str = str(get_cafe_date())

    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        rows = cursor.execute(
            """
            SELECT * FROM bookings
            WHERE date = ? AND status IN ('Pending', 'Confirmed')
            """,
            (today_str,),
        ).fetchall()

        for booking in rows:
            slot_time_str = booking["slot_time"].strip() if booking["slot_time"] else ""
            booking_start, _ = parse_slot_time(slot_time_str, today_str)
            if booking_start is None:
                continue

            # Only mark no-show after the grace period has elapsed
            cutoff = booking_start + timedelta(minutes=NOSHOW_GRACE_MINUTES)
            if now < cutoff:
                continue

            # Mark as No-show
            cursor.execute(
                "UPDATE bookings SET status = 'No-show' WHERE id = ?",
                (booking["id"],),
            )
            # Free the table if it was assigned
            if booking["table_number"]:
                cursor.execute(
                    "UPDATE tables SET status = 'Vacant' WHERE table_number = ?",
                    (booking["table_number"],),
                )
            conn.commit()
            print(f"⚠️ Booking #{booking['id']} marked No-show (slot: {slot_time_str})")

            # Notify customer if within 24h Twilio window
            phone = booking["phone"] or ""
            if phone and not phone.startswith("walkin:"):
                try:
                    display_slot = normalize_slot_label(slot_time_str) or slot_time_str
                    send_whatsapp_message(
                        phone,
                        f"⚠️ Your CoziCafe booking for {booking['date']} at {display_slot} "
                        f"has been marked as No-show as we couldn't seat you.\n\n"
                        f"Please contact us if this is a mistake: ☕ CoziCafe"
                    )
                except Exception:
                    pass

    except Exception as e:
        print(f"❌ No-show check error: {e}")
    finally:
        conn.close()
