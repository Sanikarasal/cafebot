"""
notifier.py
Twilio WhatsApp message sender — used by waitlist notifications and booking reminders.
Compatible with Twilio Sandbox (trial account).
"""

import os
from twilio.rest import Client


def get_twilio_client():
    """Create and return a Twilio REST client."""
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    if not account_sid or not auth_token:
        print("⚠️  Twilio credentials not set. Notifications disabled.")
        return None
    return Client(account_sid, auth_token)


def send_whatsapp_message(to_phone: str, body: str) -> tuple[bool, str]:
    """
    Send a plain-text WhatsApp message via Twilio Sandbox.
    `to_phone` can be in the format '+91XXXXXXXXXX' or 'whatsapp:+91XXXXXXXXXX'.
    Returns (True, message_or_sid) on success, (False, error_reason) on failure.
    """
    client = get_twilio_client()
    if not client:
        return False, "Twilio client not configured. Missing credentials."

    # Skip pseudo-numbers (walk-in, staff, etc.)
    if to_phone and ("walkin:" in to_phone.lower() or "staff:" in to_phone.lower()):
        print(f"⏩ Skipped Twilio send for pseudo-number: {to_phone}")
        return True, "Skipped pseudo-number"

    # Ensure phone has 'whatsapp:' prefix
    formatted_phone = to_phone
    if to_phone and not to_phone.startswith('whatsapp:'):
        # Handle raw phone numbers (e.g., '+91XXXXXXXXXX')
        if to_phone.startswith('+') or to_phone.isdigit():
            formatted_phone = f'whatsapp:{to_phone}'
        else:
            print(f"⚠️  Invalid phone format: {to_phone}")
            return False, f"Invalid phone format: {to_phone}"

    from_number = os.getenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886")

    try:
        message = client.messages.create(
            body=body,
            from_=from_number,
            to=formatted_phone,
        )
        print(f"📤 Sent WhatsApp to {formatted_phone} | SID: {message.sid}")
        return True, f"Sent successfully! (SID: {message.sid})"
    except Exception as e:
        print(f"❌ Failed to send WhatsApp to {formatted_phone}: {e}")
        return False, str(e)
