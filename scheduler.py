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
    from utils import get_cafe_date
    now = get_cafe_time()  # timezone-aware (CAFE_TIMEZONE)
    today_str = str(get_cafe_date())
    reminder_window = now + timedelta(minutes=10)

    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        statuses = get_active_booking_statuses()
        placeholders = ",".join("?" * len(statuses))
        has_twilio_last_response = _has_column(conn, "bookings", "twilio_last_response")
        
        # Only check today's bookings to avoid timezone issues with stored dates
        bookings = cursor.execute(
            f"""
            SELECT * FROM bookings
            WHERE date = ? AND status IN ({placeholders}) AND reminder_sent = 0
            """,
            (today_str, *statuses),
        ).fetchall()

        if not bookings:
            # print(f"[Reminders] No pending reminders for {today_str}")  # DEAD CODE [audit] - removed debug print
            return

        print(f"[Reminders] Checking {len(bookings)} bookings for date {today_str}...")

        for booking in bookings:
            try:
                booking_date_str = booking["date"]
                slot_time_str = booking["slot_time"].strip() if booking["slot_time"] else ""
                phone = booking["phone"] or ""

                if not slot_time_str:
                    print(f"⚠️  Booking #{booking['id']}: No slot_time found")
                    continue

                # parse_slot_time returns timezone-aware datetimes — compare directly with now
                booking_start, _ = parse_slot_time(slot_time_str, booking_date_str)
                if booking_start is None:
                    print(f"⚠️  Booking #{booking['id']}: Could not parse slot time '{slot_time_str}'")
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

                    success, msg = send_whatsapp_message(phone, message)

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
                        print(f"✅ Reminder sent for booking #{booking['id']} to {phone}")
                    else:
                        conn.commit()
                        print(f"⚠️ Reminder failed for booking #{booking['id']}: {msg}")
            except Exception as e:
                print(f"❌ Error processing booking #{booking['id']}: {e}")
                continue

    except Exception as e:
        print(f"❌ Reminder check error: {e}")
        import traceback
        traceback.print_exc()
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

        if not rows:
            # print(f"[No-show] No pending bookings to check for {today_str}")
            return

        print(f"[No-show] Checking {len(rows)} pending bookings for date {today_str}...")

        for booking in rows:
            try:
                slot_time_str = booking["slot_time"].strip() if booking["slot_time"] else ""
                phone = booking["phone"] or ""

                if not slot_time_str:
                    print(f"⚠️  Booking #{booking['id']}: No slot_time found")
                    continue

                booking_start, _ = parse_slot_time(slot_time_str, today_str)
                if booking_start is None:
                    print(f"⚠️  Booking #{booking['id']}: Could not parse slot time '{slot_time_str}'")
                    continue

                # Only mark no-show after the grace period has elapsed
                cutoff = booking_start + timedelta(minutes=NOSHOW_GRACE_MINUTES)
                if now < cutoff:
                    # Not yet time to mark as no-show
                    continue

                # FIX 3: Send WhatsApp notification BEFORE committing no-show status
                # If notification succeeds, THEN update and commit
                # If notification fails or user is walkin:, update without notification
                if phone and not phone.startswith("walkin:"):
                    try:
                        display_slot = normalize_slot_label(slot_time_str) or slot_time_str
                        success, msg = send_whatsapp_message(
                            phone,
                            f"⚠️ Your CoziCafe booking for {booking['date']} at {display_slot} "
                            f"has been marked as No-show as we couldn't seat you.\n\n"
                            f"Please contact us if this is a mistake: ☕ CoziCafe"
                        )
                        if not success:
                            # Notification failed; don't update status yet
                            print(f"⚠️ No-show notification failed for booking #{booking['id']}: {msg}")
                            conn.rollback()
                            continue
                    except Exception as e:
                        print(f"⚠️ Error sending no-show notification for booking #{booking['id']}: {e}")
                        conn.rollback()
                        continue

                # Mark as No-show (after successful notification for real phones, no check for walkin:)
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
                print(f"⚠️  Booking #{booking['id']} marked No-show (slot: {slot_time_str}, grace mins: {NOSHOW_GRACE_MINUTES})")
            except Exception as e:
                print(f"❌ Error processing no-show for booking #{booking['id']}: {e}")
                continue

    except Exception as e:
        print(f"❌ No-show check error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        conn.close()
