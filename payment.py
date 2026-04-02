"""
payment.py — Razorpay Payment Link integration for CafeBot.

Provides:
  create_payment_link(amount_paise, booking_id, customer_name, phone)
      → (link_url: str, link_id: str) or raises RuntimeError

  check_payment_link_status(link_id)
      → "paid" | "created" | "cancelled" | "expired" | "error"
"""

import os
import razorpay
from dotenv import load_dotenv

load_dotenv()

_KEY_ID     = os.getenv("RAZORPAY_KEY_ID", "")
_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")

# Amount in paise (100 paise = ₹1). Defaults to 10000 (₹100).
PAYMENT_AMOUNT_PAISE = int(os.getenv("PAYMENT_AMOUNT_PAISE", "10000"))
AMOUNT_DISPLAY = f"₹{PAYMENT_AMOUNT_PAISE // 100}"


def _client() -> razorpay.Client:
    if not _KEY_ID or not _KEY_SECRET:
        raise RuntimeError(
            "Razorpay keys not configured. Add RAZORPAY_KEY_ID and "
            "RAZORPAY_KEY_SECRET to your .env file."
        )
    return razorpay.Client(auth=(_KEY_ID, _KEY_SECRET))


def create_payment_link(
    booking_id: int,
    customer_name: str,
    phone: str,
    amount_paise: int = None,
) -> tuple:
    """
    Create a Razorpay Payment Link for the given booking.

    Parameters
    ----------
    booking_id    : DB booking id (used as reference in Razorpay)
    customer_name : Customer name shown on payment page
    phone         : Customer phone (digits only, no whatsapp: prefix)
    amount_paise  : Amount in paise; defaults to PAYMENT_AMOUNT_PAISE

    Returns
    -------
    (short_url: str, link_id: str)
    Raises RuntimeError on API failure.
    """
    if amount_paise is None:
        amount_paise = PAYMENT_AMOUNT_PAISE

    # Strip whatsapp: prefix and leading +
    clean_phone = phone.replace("whatsapp:", "").lstrip("+")

    client = _client()
    payload = {
        "amount": amount_paise,
        "currency": "INR",
        "accept_partial": False,
        "description": f"CoziCafe table booking #{booking_id}",
        "customer": {
            "name": customer_name,
            "contact": f"+{clean_phone}",
        },
        "notify": {
            "sms": False,   # We send via WhatsApp ourselves
            "email": False,
        },
        "reminder_enable": False,
        "notes": {
            "booking_id": str(booking_id),
            "source": "cafebot",
        },
        "callback_url": "",      # Polling — no callback needed
        "callback_method": "",
    }

    try:
        response = client.payment_link.create(payload)
        link_url = response.get("short_url") or response.get("id")
        link_id  = response.get("id")
        if not link_url or not link_id:
            raise RuntimeError(f"Unexpected Razorpay response: {response}")
        return link_url, link_id
    except razorpay.errors.BadRequestError as exc:
        raise RuntimeError(f"Razorpay API error: {exc}") from exc


def check_payment_link_status(link_id: str) -> str:
    """
    Fetch the current status of a Payment Link.

    Returns one of:
      "paid"       — at least one payment captured
      "created"    — link exists but not yet paid
      "cancelled"  — link was cancelled
      "expired"    — link expired
      "error"      — API call failed
    """
    try:
        client = _client()
        response = client.payment_link.fetch(link_id)
        status = (response.get("status") or "").lower()
        # Razorpay statuses: created, paid, cancelled, expired
        if status == "paid":
            return "paid"
        if status in ("cancelled", "expired"):
            return status
        return "created"   # treat anything else as not yet paid
    except Exception:
        return "error"
