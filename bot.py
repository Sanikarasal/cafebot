import os
from datetime import datetime, timedelta
from datetime import timezone
# date import removed - unused (audit)

from flask import Blueprint, request, g
from werkzeug.local import LocalProxy
from twilio.twiml.messaging_response import MessagingResponse

import db
import payment
from utils import normalize_slot_label, slots_equal

# Contact number centralized
CAFE_CONTACT_NUMBER = os.getenv("CAFE_CONTACT_NUMBER", "77680388366")

bot_bp = Blueprint("bot", __name__)

# Twilio configuration (trial-compatible plain-text flow)
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")

# State machine constants
MAIN_MENU = "MAIN_MENU"
ASK_NAME = "ASK_NAME"
ASK_DATE = "ASK_DATE"
ASK_CUSTOM_DATE = "ASK_CUSTOM_DATE"
SELECT_SLOT = "SELECT_SLOT"
ASK_SEATS = "ASK_SEATS"
SELECT_TABLE = "SELECT_TABLE"
CONFIRM_BOOKING = "CONFIRM_BOOKING"
VIEW_BOOKINGS = "VIEW_BOOKINGS"
CANCEL_SELECT = "CANCEL_SELECT"
CANCEL_CONFIRM = "CANCEL_CONFIRM"
ASK_WAITLIST = "ASK_WAITLIST"
AWAITING_PAYMENT = "AWAITING_PAYMENT"

INVALID_CHOICE_PREFIX = "Invalid choice. Please try again.\n\n"
NAVIGATION_HINT = "Use:\n* to back or # to Reset"


def _append_hint(text, show=False):
    if show:
        return f"{text}\n\n{NAVIGATION_HINT}"
    return text


def _invalid_choice(text):
    return _append_hint(f"{INVALID_CHOICE_PREFIX}{text}", show=True)

#Wraps conversation data for one user.
class ConversationStore:
    def __init__(self, phone=None, state=None, data=None, updated_at=None):
        self.phone = phone
        self.state = state
        self.data = data or {}
        self.updated_at = updated_at
        self.cleared = False

    def get(self, key, default=None):
        if key == "state":
            return self.state if self.state is not None else default
        return self.data.get(key, default)

    def __getitem__(self, key):
        if key == "state":
            return self.state
        return self.data[key]

    def __setitem__(self, key, value):
        if key == "state":
            self.state = value
        else:
            self.data[key] = value

    def pop(self, key, default=None):
        if key == "state":
            value = self.state
            self.state = None
            return value if value is not None else default
        return self.data.pop(key, default)

    def setdefault(self, key, default=None):
        if key == "state":
            if self.state is None:
                self.state = default
            return self.state
        return self.data.setdefault(key, default)

    def __contains__(self, key):
        if key == "state":
            return self.state is not None
        return key in self.data


def _get_conversation_store():
    store = getattr(g, "_conv_store", None)
    if store is None:
        store = ConversationStore()
        g._conv_store = store
    return store


session = LocalProxy(_get_conversation_store)


def _load_conversation_store(phone):
    convo = db.get_conversation(phone)
    state = convo.get("state") if convo else None
    if not state or state == "idle":
        state = None
    store = ConversationStore(
        phone=phone,
        state=state,
        data=(convo.get("data") if convo else {}) or {},
        updated_at=convo.get("updated_at") if convo else None,
    )
    g._conv_store = store
    return store


def _persist_conversation():
    store = _get_conversation_store()
    if store.cleared or not store.phone:
        return
    state = store.state or "idle"
    db.save_conversation(store.phone, state, store.data)


def clear_conversation_state():
    store = _get_conversation_store()
    if store.phone:
        db.clear_conversation(store.phone)
    store.state = None
    store.data = {}
    store.cleared = True


def get_main_menu_message(show_hint=True):
    text = (
        "☕ Welcome to CoziCafe!\n\n"
        "1️⃣ Book Table\n"
        "2️⃣ View Booking\n"
        "3️⃣ Cancel Booking\n"
        "4️⃣ Contact Us\n\n"
        "Reply with number only.\n"
        "\nCafe Overview: https://cafepetermahabaleshwar.com/"
    )
    return _append_hint(text, show=show_hint)


def get_ask_name_prompt():
    return "Please enter your name:"


def get_ask_date_prompt():
    return (
        "Select booking date:\n\n"
        "1️⃣ Today\n"
        "2️⃣ Tomorrow\n"
        "3️⃣ Choose Date"
    )


def get_ask_custom_date_prompt():
    return "Enter date in YYYY-MM-DD format:"


def get_ask_seats_prompt():
    return "Enter number of guests (1–8):"


def clear_payment_context():
    for key in ("payment_link_id", "payment_booking_id", "payment_link_url"):
        session.pop(key, None)


def clear_booking_context():
    for key in (
        "b_name", "b_date", "slot_options", "b_slot_time", "b_slot_available",
        "b_seats", "b_table_number", "b_table_location", "b_table_options",
        "b_combo_tables", "b_is_combo",
    ):
        session.pop(key, None)
    clear_payment_context()


def clear_cancel_context():
    for key in ("cancel_options", "cancel_booking_id"):
        session.pop(key, None)


def reset_navigation(state=MAIN_MENU):
    session.pop("state_history", None)
    session.pop("previous_state", None)
    session.pop("state", None)
    session["state_history"] = []
    session["previous_state"] = None
    session["state"] = state


def transition_to(new_state):
    current_state = session.get("state")
    history = session.get("state_history", [])
    if current_state:
        history.append(current_state)
    session["state_history"] = history
    session["previous_state"] = current_state
    session["state"] = new_state


def go_back(phone, msg):
    history = session.get("state_history", [])
    if not history:
        reset_navigation(MAIN_MENU)
        msg.body(get_main_menu_message())
        return

    previous = history.pop()
    session["state_history"] = history
    session["state"] = previous
    session["previous_state"] = history[-1] if history else None
    send_state_prompt(previous, phone, msg)


def get_slot_prompt_for_date(selected_date):
    from utils import get_cafe_date
    today_str = str(get_cafe_date())
    is_today = (str(selected_date) == today_str)
    slots = db.get_available_slots(selected_date, filter_past=is_today)
    if not slots:
        session["slot_options"] = []
        return (
            f"No available slots found for {selected_date}.\n"
            "Please choose another date."
        )

    slot_options = []
    lines = [f"Available slots for {selected_date}:"]

    for idx, slot in enumerate(slots, start=1):
        slot_time_raw = slot["slot_time"]
        slot_time = normalize_slot_label(slot_time_raw) or slot_time_raw
        available = int(slot["available_seats"])
        slot_options.append({"slot_time": slot_time, "available_seats": available})
        lines.append(f"{idx}. {slot_time} ({available} seats left)")

    session["slot_options"] = slot_options
    lines.extend(["", "Select slot number:"])
    return "\n".join(lines)


def get_select_table_prompt():
    """
    Build the table selection message.
    Returns (message_text, mode).
    Modes: NO_TABLES, AUTO, CHOOSE, COMBO
    """
    b_date = session.get("b_date", "")
    b_slot_time = session.get("b_slot_time", "")
    b_seats = int(session.get("b_seats", 1))

    available_tables = db.get_available_tables(b_date, b_slot_time, b_seats)
    required_cap = db.get_required_capacity(b_seats)

    if available_tables:
        # Auto-assign if only one option
        if len(available_tables) == 1:
            t = available_tables[0]
            session["b_table_number"] = int(t["table_number"])
            session["b_table_location"] = t["location"]
            session["b_table_options"] = []
            session["b_is_combo"] = False
            lines = [
                "Table auto-assigned:",
                f"Table {t['table_number']} - {t['capacity']} Seater - {t['location']}",
                "",
                "Proceeding to confirmation...",
            ]
            return "\n".join(lines), "AUTO"

        # Multiple options - let user choose
        table_options = []
        lines = ["Available Tables:"]
        for idx, t in enumerate(available_tables, start=1):
            table_options.append({
                "table_number": int(t["table_number"]),
                "capacity": int(t["capacity"]),
                "location": t["location"],
            })
            lines.append(f"Table {t['table_number']} - {t['capacity']} Seater - {t['location']}")

        session["b_table_options"] = table_options
        session["b_is_combo"] = False

        lines.append("")
        for idx, t in enumerate(table_options, start=1):
            lines.append(f"{idx}. Select Table {t['table_number']}")
        lines.extend(["", "Reply with option number:"])
        return "\n".join(lines), "CHOOSE"

    # No single table fits - try table combination
    combo = db.get_combined_tables(b_date, b_slot_time, b_seats)
    if combo:
        total_cap = sum(t["capacity"] for t in combo)
        table_nums = [str(t["table_number"]) for t in combo]
        table_desc = " + ".join(
            f"T{t['table_number']}({t['capacity']})" for t in combo
        )

        session["b_combo_tables"] = combo
        session["b_is_combo"] = True
        session["b_table_options"] = []

        lines = [
            f"No single table can seat {b_seats} guests.",
            "",
            "We can combine tables for you:",
            f"{table_desc} = {total_cap} seats",
            f"Tables: {', '.join(table_nums)}",
            "",
            "1️⃣ Accept combined tables",
            "2️⃣ Choose different date/time",
            "",
            "Reply with option number:",
        ]
        return "\n".join(lines), "COMBO"

    # No tables at all - offer waitlist
    slot_label = normalize_slot_label(b_slot_time) or b_slot_time
    lines = [
        f"Sorry, no tables are available for {b_date} at {slot_label}.",
    ]
    return "\n".join(lines), "NO_TABLES"


def get_confirm_booking_prompt(phone):
    is_combo = session.get("b_is_combo", False)

    if is_combo:
        combo_tables = session.get("b_combo_tables", [])
        table_desc = ", ".join(f"T{t['table_number']}" for t in combo_tables)
        location_desc = ", ".join(t["location"] for t in combo_tables)
    else:
        table_desc = str(session.get("b_table_number", "-"))
        location_desc = session.get("b_table_location", "-")

    return (
        "Confirm booking details:\n\n"
        f"Name: {session.get('b_name', '-')}\n"
        f"Phone: {phone}\n"
        f"Date: {session.get('b_date', '-')}\n"
        f"Time: {normalize_slot_label(session.get('b_slot_time', '-')) or session.get('b_slot_time', '-')}\n"
        f"Guests: {session.get('b_seats', '-')}\n"
        f"Table: {table_desc}\n"
        f"Location: {location_desc}\n\n"
        "1️⃣ Confirm Booking\n"
        "2️⃣ Cancel"
    )


def get_view_bookings_prompt(phone):
    bookings = db.get_user_bookings(phone)
    if not bookings:
        return "You have no active bookings."

    lines = ["Your active bookings:\n"]
    for idx, booking in enumerate(bookings, start=1):
        # Check if this is a combo booking
        combo_group = booking["combo_group"]
        if combo_group:
            combo_tables = db.get_combo_tables(combo_group)
            table_info = " | 🪑 Tables " + ",".join(str(t) for t in combo_tables)
        elif booking["table_number"]:
            table_info = f" | 🪑 Table {booking['table_number']}"
        else:
            table_info = ""

        slot_label = normalize_slot_label(booking["slot_time"]) or booking["slot_time"]
        lines.append(
            f"{idx}. [{booking['date']} {slot_label}]\n"
            f"   ID #{booking['id']} | {booking['seats']} guests{table_info}"
        )
    return "\n".join(lines)


def get_cancel_select_prompt(phone):
    bookings = db.get_user_bookings(phone)
    if not bookings:
        session["cancel_options"] = []
        return "You have no active bookings to cancel."

    options = [
        {
            "id": int(booking["id"]),
            "date": booking["date"],
            "slot_time": normalize_slot_label(booking["slot_time"]) or booking["slot_time"],
            "seats": int(booking["seats"]),
        }
        for booking in bookings
    ]
    session["cancel_options"] = options

    lines = ["Select booking number to cancel:"]
    for idx, booking in enumerate(options, start=1):
        lines.append(
            f"{idx}. ID {booking['id']} | {booking['date']} | {booking['slot_time']} | {booking['seats']} seats"
        )
    return "\n".join(lines)


def get_cancel_confirm_prompt(phone):
    booking_id = session.get("cancel_booking_id")
    if not booking_id:
        return get_cancel_select_prompt(phone)

    booking = db.get_booking_for_user(phone, booking_id)
    if not booking:
        return "Booking not found."

    slot_label = normalize_slot_label(booking["slot_time"]) or booking["slot_time"]
    lines = [
        "Confirm cancellation:",
        "",
        f"ID {booking['id']} | {booking['date']} | {slot_label} | {booking['seats']} seats",
        "",
        "1️⃣ Yes",
        "2️⃣ No",
    ]
    return "\n".join(lines)


def build_booking_confirmed_message(booking_id, phone):
    is_combo = session.get("b_is_combo", False)

    if is_combo:
        combo_tables = session.get("b_combo_tables", [])
        table_desc = ", ".join(f"T{t['table_number']}" for t in combo_tables)
        location_desc = ", ".join(t["location"] for t in combo_tables)
    else:
        table_desc = str(session.get("b_table_number", "-"))
        location_desc = session.get("b_table_location", "-")

    slot_label = normalize_slot_label(session.get("b_slot_time")) or session.get("b_slot_time")

    lines = [
        "Booking Confirmed!",
        "",
        f"Booking ID: {booking_id}",
        f"Name: {session.get('b_name')}",
        f"Phone: {phone}",
        f"Guests: {session.get('b_seats')}",
        f"Table: {table_desc}",
        f"Location: {location_desc}",
        f"Date: {session.get('b_date')}",
        f"Time: {slot_label}",
        "",
        "Important Notice:",
        "Please arrive within 15 minutes of your booking time.",
        "If you do not arrive within 15 minutes, your table may be given to other guests.",
        "",
        "If you are running late or facing any issue, contact us at:",
        CAFE_CONTACT_NUMBER,
        "",
        "We look forward to serving you.",
    ]
    return "\n".join(lines)


def get_ask_waitlist_prompt():
    return (
        "All tables are fully booked for this slot.\n\n"
        "Would you like to join the waitlist?\n"
        "You'll be notified if a table becomes available.\n\n"
        "1️⃣ Yes, join waitlist\n"
        "2️⃣ No, go back\n"
    )


def send_state_prompt(state, phone, msg):
    if state == MAIN_MENU:
        msg.body(get_main_menu_message())
    elif state == ASK_NAME:
        msg.body(get_ask_name_prompt())
    elif state == ASK_DATE:
        msg.body(get_ask_date_prompt())
    elif state == ASK_CUSTOM_DATE:
        msg.body(get_ask_custom_date_prompt())
    elif state == SELECT_SLOT:
        selected_date = session.get("b_date")
        if not selected_date:
            msg.body(get_ask_date_prompt())
            return
        msg.body(get_slot_prompt_for_date(selected_date))
    elif state == ASK_SEATS:
        msg.body(get_ask_seats_prompt())
    elif state == SELECT_TABLE:
        prompt, mode = get_select_table_prompt()
        if mode == "NO_TABLES":
            # Offer waitlist
            transition_to(ASK_WAITLIST)
            msg.body(get_ask_waitlist_prompt())
        elif mode == "AUTO":
            transition_to(CONFIRM_BOOKING)
            msg.body(prompt + "\n\n" + get_confirm_booking_prompt(phone))
        elif mode == "COMBO":
            msg.body(prompt)
        else:
            msg.body(prompt)
    elif state == CONFIRM_BOOKING:
        msg.body(get_confirm_booking_prompt(phone))
    elif state == VIEW_BOOKINGS:
        msg.body(get_view_bookings_prompt(phone))
    elif state == CANCEL_SELECT:
        msg.body(get_cancel_select_prompt(phone))
    elif state == CANCEL_CONFIRM:
        msg.body(get_cancel_confirm_prompt(phone))
    elif state == ASK_WAITLIST:
        msg.body(get_ask_waitlist_prompt())
    elif state == AWAITING_PAYMENT:
        # Prompt user to pay if they somehow re-trigger this state without paying
        msg.body(
            f"Please complete your payment to confirm your booking.\n\n"
            f"Payment Link: {session.get('payment_link_url')}\n\n"
            f"Reply 'paid' once you have completed the payment."
        )
    else:
        reset_navigation(MAIN_MENU)
        msg.body(get_main_menu_message())


def handle_main_menu(user_input, phone, msg):
    if user_input == "1":
        clear_booking_context()
        clear_cancel_context()
        transition_to(ASK_NAME)
        msg.body(get_ask_name_prompt())
    elif user_input == "2":
        clear_cancel_context()
        transition_to(VIEW_BOOKINGS)
        msg.body(get_view_bookings_prompt(phone))
    elif user_input == "3":
        clear_booking_context()
        transition_to(CANCEL_SELECT)
        msg.body(get_cancel_select_prompt(phone))
    elif user_input == "4":
        msg.body(f"📞 Contact Us:\n{CAFE_CONTACT_NUMBER}")
    else:
        msg.body(_invalid_choice(get_main_menu_message(show_hint=False)))


def handle_ask_name(user_input, phone, msg):
    name = user_input.strip()
    if not name:
        msg.body(_invalid_choice(get_ask_name_prompt()))
        return

    session["b_name"] = name
    transition_to(ASK_DATE)
    msg.body(get_ask_date_prompt())


def handle_ask_date(user_input, phone, msg):
    from utils import get_cafe_date
    today = get_cafe_date()
    if user_input == "1":
        selected_date = today
    elif user_input == "2":
        selected_date = today + timedelta(days=1)
    elif user_input == "3":
        transition_to(ASK_CUSTOM_DATE)
        msg.body(get_ask_custom_date_prompt())
        return
    else:
        msg.body(_invalid_choice(get_ask_date_prompt()))
        return

    session["b_date"] = selected_date.isoformat()
    transition_to(SELECT_SLOT)
    msg.body(get_slot_prompt_for_date(session["b_date"]))


def handle_ask_custom_date(user_input, phone, msg):
    try:
        parsed_date = datetime.strptime(user_input, "%Y-%m-%d").date()
    except ValueError:
        msg.body(_invalid_choice(get_ask_custom_date_prompt()))
        return

    from utils import get_cafe_date
    if parsed_date < get_cafe_date():
        msg.body(_invalid_choice(get_ask_custom_date_prompt()))
        return

    session["b_date"] = parsed_date.isoformat()
    transition_to(SELECT_SLOT)
    msg.body(get_slot_prompt_for_date(session["b_date"]))


def handle_select_slot(user_input, phone, msg):
    options = session.get("slot_options", [])
    if not options:
        selected_date = session.get("b_date")
        if not selected_date:
            transition_to(ASK_DATE)
            msg.body(_invalid_choice(get_ask_date_prompt()))
            return
        msg.body(_invalid_choice(get_slot_prompt_for_date(selected_date)))
        return

    if not user_input.isdigit():
        msg.body(_invalid_choice(get_slot_prompt_for_date(session['b_date'])))
        return

    option_index = int(user_input)
    if option_index < 1 or option_index > len(options):
        msg.body(_invalid_choice(get_slot_prompt_for_date(session['b_date'])))
        return

    selected_option = options[option_index - 1]
    session["b_slot_time"] = selected_option["slot_time"]
    session["b_slot_available"] = int(selected_option["available_seats"])

    transition_to(ASK_SEATS)
    msg.body(get_ask_seats_prompt())


def handle_ask_seats(user_input, phone, msg):
    if not user_input.isdigit() or int(user_input) <= 0 or int(user_input) > 8:
        msg.body(_invalid_choice(get_ask_seats_prompt()))
        return

    seats_requested = int(user_input)
    available = session.get("b_slot_available")
    if available is None:
        transition_to(SELECT_SLOT)
        msg.body(_invalid_choice(get_slot_prompt_for_date(session['b_date'])))
        return

    if seats_requested > int(available):
        msg.body(
            f"⚠️ Only {available} seats available in that slot.\n\n"
            f"{get_ask_seats_prompt()}"
        )
        return

    # Slot capacity check
    b_date = session.get("b_date", "")
    b_slot_time = session.get("b_slot_time", "")
    allowed, remaining = db.check_slot_capacity(b_date, b_slot_time, seats_requested)
    if not allowed:
        msg.body(
            f"⚠️ This slot can only accommodate {remaining} more guests.\n"
            f"You requested {seats_requested}.\n\n"
            f"{get_ask_seats_prompt()}"
        )
        return

    session["b_seats"] = seats_requested

    # Move to table selection
    transition_to(SELECT_TABLE)
    prompt, mode = get_select_table_prompt()

    if mode == "NO_TABLES":
        # No tables available at all — offer waitlist
        transition_to(ASK_WAITLIST)
        msg.body(get_ask_waitlist_prompt())
    elif mode == "AUTO":
        transition_to(CONFIRM_BOOKING)
        msg.body(prompt + "\n\n" + get_confirm_booking_prompt(phone))
    elif mode == "COMBO":
        msg.body(prompt)
    else:
        msg.body(prompt)


def handle_select_table(user_input, phone, msg):
    is_combo = session.get("b_is_combo", False)

    if is_combo:
        # Combo table prompt: 1 = Accept, 2 = Go back
        if user_input == "1":
            transition_to(CONFIRM_BOOKING)
            msg.body(get_confirm_booking_prompt(phone))
        elif user_input == "2":
            session.pop("b_date", None)
            session.pop("b_slot_time", None)
            session.pop("b_slot_available", None)
            session.pop("slot_options", None)
            session.pop("b_combo_tables", None)
            session.pop("b_is_combo", None)
            reset_navigation(ASK_DATE)
            msg.body(get_ask_date_prompt())
        else:
            prompt, _ = get_select_table_prompt()
            msg.body(_invalid_choice(prompt))
        return

    table_options = session.get("b_table_options", [])
    if not table_options:
        prompt, mode = get_select_table_prompt()
        if mode in ("NO_TABLES", "AUTO", "COMBO"):
            send_state_prompt(SELECT_TABLE, phone, msg)
        else:
            msg.body(_invalid_choice(prompt))
        return

    if not user_input.isdigit():
        prompt, _ = get_select_table_prompt()
        msg.body(_invalid_choice(prompt))
        return

    option_index = int(user_input)
    if option_index < 1 or option_index > len(table_options):
        prompt, _ = get_select_table_prompt()
        msg.body(_invalid_choice(prompt))
        return

    chosen = table_options[option_index - 1]
    session["b_table_number"] = chosen["table_number"]
    session["b_table_location"] = chosen["location"]

    transition_to(CONFIRM_BOOKING)
    msg.body(get_confirm_booking_prompt(phone))


def handle_confirm_booking(user_input, phone, msg):
    if user_input == "2":
        clear_booking_context()
        reset_navigation(MAIN_MENU)
        clear_conversation_state()
        msg.body(get_main_menu_message())
        return

    if user_input != "1":
        msg.body(_invalid_choice(get_confirm_booking_prompt(phone)))
        return

    # FIX 1: Pre-flight check that payment system is reachable
    try:
        # Test payment link creation (will fail immediately if system down)
        test_link_url, test_link_id = payment.create_payment_link(
            booking_id=0,
            customer_name="SystemCheck",
            phone=phone
        )
        # Discard the test link ID since we're not using it
    except Exception as e:
        # Payment system unreachable
        clear_booking_context()
        clear_cancel_context()
        reset_navigation(MAIN_MENU)
        msg.body(
            f"⚠️ Payment system is temporarily unavailable. Please try again later.\n\n"
            f"{get_main_menu_message(show_hint=False)}"
        )
        return

    is_combo = session.get("b_is_combo", False)

    booking_id = None
    if is_combo:
        combo_tables = session.get("b_combo_tables", [])
        table_numbers = [t["table_number"] for t in combo_tables]
        success, message, booking_ids = db.create_combo_booking(
            phone=phone,
            name=session.get("b_name", ""),
            date=session.get("b_date", ""),
            slot_time=session.get("b_slot_time", ""),
            seats=int(session.get("b_seats", 0)),
            table_numbers=table_numbers,
        )
        if success:
            booking_id = booking_ids[0]
    else:
        # Standard single-table booking
        success, message, booking_id = db.create_booking(
            phone=phone,
            name=session.get("b_name", ""),
            date=session.get("b_date", ""),
            slot_time=session.get("b_slot_time", ""),
            seats=int(session.get("b_seats", 0)),
            table_number=session.get("b_table_number"),
        )

    if success:
        # Payment Step
        try:
            link_url, link_id = payment.create_payment_link(
                booking_id=booking_id,
                customer_name=session.get("b_name", ""),
                phone=phone
            )
            db.set_booking_payment_link(booking_id, link_id)
            session["payment_link_id"] = link_id
            session["payment_booking_id"] = booking_id
            session["payment_link_url"] = link_url
            # FIX 4: Record payment start time for timeout check
            session['payment_start_time'] = datetime.now(timezone.utc).timestamp()
            
            transition_to(AWAITING_PAYMENT)
            msg.body(
                f"To reserve your seat, please make an advance payment of {payment.AMOUNT_DISPLAY}.\n"
                f"Click the payment link below to proceed:\n{link_url}\n\n"
                "Once you have completed the payment, reply *paid* to confirm your booking."
            )
        except Exception as e:
            # Payment failed to initialize, discard pending booking
            db.delete_pending_booking(booking_id)
            clear_booking_context()
            clear_cancel_context()
            reset_navigation(MAIN_MENU)
            msg.body(f"⚠️ Payment system is temporarily unavailable. Please try again later.\n\n{get_main_menu_message(show_hint=False)}")
        return

    DUPLICATE_MSG = "You already have a booking for this slot."
    if message == DUPLICATE_MSG:
        clear_booking_context()
        clear_cancel_context()
        reset_navigation(VIEW_BOOKINGS)
        bookings_text = get_view_bookings_prompt(phone)
        msg.body(
            "ℹ️ You already have an active booking for that date and time.\n\n"
            + bookings_text
            + "\n\nTo make a new booking for the same slot, first cancel "
            "your existing one (# → Main Menu → 3️⃣ Cancel Booking)."
        )
        return

    clear_booking_context()
    clear_cancel_context()
    reset_navigation(MAIN_MENU)
    msg.body(f"⚠️ {message}\n\nPlease try again.\n\n{get_main_menu_message(show_hint=False)}")


def handle_view_bookings(user_input, phone, msg):
    """Any input in VIEW_BOOKINGS state re-displays the bookings list with nav hint."""
    msg.body(get_view_bookings_prompt(phone))


def handle_cancel_select(user_input, phone, msg):
    options = session.get("cancel_options", [])
    if not options:
        msg.body(get_cancel_select_prompt(phone))
        return

    if not user_input.isdigit():
        msg.body(_invalid_choice(get_cancel_select_prompt(phone)))
        return

    option_index = int(user_input)
    if option_index < 1 or option_index > len(options):
        msg.body(_invalid_choice(get_cancel_select_prompt(phone)))
        return

    selected_booking = options[option_index - 1]
    session["cancel_booking_id"] = selected_booking["id"]
    transition_to(CANCEL_CONFIRM)
    msg.body(get_cancel_confirm_prompt(phone))


def handle_cancel_confirm(user_input, phone, msg):
    if user_input == "2":
        clear_cancel_context()
        reset_navigation(MAIN_MENU)
        clear_conversation_state()
        msg.body(get_main_menu_message())
        return

    if user_input != "1":
        msg.body(_invalid_choice(get_cancel_confirm_prompt(phone)))
        return

    booking_id = session.get("cancel_booking_id")
    if not booking_id:
        transition_to(CANCEL_SELECT)
        msg.body(_invalid_choice(get_cancel_select_prompt(phone)))
        return

    success, message = db.cancel_booking_by_id(phone, booking_id)
    if success:
        clear_cancel_context()
        reset_navigation(MAIN_MENU)
        msg.body(f"✅ {message}\n\n{get_main_menu_message(show_hint=False)}")
    else:
        transition_to(CANCEL_SELECT)
        msg.body(f"⚠️ {message}\n\n{get_cancel_select_prompt(phone)}")


def handle_ask_waitlist(user_input, phone, msg):
    """Handle waitlist join prompt."""
    if user_input == "1":
        b_name = session.get("b_name", "Guest")
        b_date = session.get("b_date", "")
        b_slot_time = session.get("b_slot_time", "")
        b_seats = int(session.get("b_seats", 1))
        slot_label = normalize_slot_label(b_slot_time) or b_slot_time

        success, message = db.add_to_waitlist(phone, b_name, b_date, b_slot_time, b_seats)
        clear_booking_context()
        reset_navigation(MAIN_MENU)
        clear_conversation_state()

        if success:
            msg.body(
                "✅ You've been added to the waitlist!\n\n"
                f"Date: {b_date}\n"
                f"Time: {slot_label}\n"
                f"Guests: {b_seats}\n\n"
                "We'll notify you if a table becomes available.\n\n"
                f"{get_main_menu_message(show_hint=False)}"
            )
        else:
            msg.body(f"ℹ️ {message}\n\n{get_main_menu_message(show_hint=False)}")
    elif user_input == "2":
        clear_booking_context()
        reset_navigation(MAIN_MENU)
        clear_conversation_state()
        msg.body(get_main_menu_message())
    else:
        msg.body(_invalid_choice(get_ask_waitlist_prompt()))


def handle_awaiting_payment(user_input, phone, msg):
    link_id = session.get("payment_link_id")
    booking_id = session.get("payment_booking_id")
    
    if not link_id or not booking_id:
        reset_navigation(MAIN_MENU)
        msg.body(get_main_menu_message())
        return

    # FIX 4: Check if payment timeout exceeded (30 minutes)
    payment_start = session.get('payment_start_time')
    if payment_start:
        elapsed = (datetime.now(timezone.utc).timestamp() - payment_start)
        if elapsed > 1800:  # 30 minutes
            db.delete_pending_booking(booking_id)
            clear_booking_context()
            reset_navigation(MAIN_MENU)
            msg.body(
                "Payment link expired after 30 minutes. Your reservation was released. "
                "Please try booking again.\n\n"
                f"{get_main_menu_message(show_hint=False)}"
            )
            return

    # Triggered by checking payment
    if user_input.lower() in ["paid", "done", "check", "yes", "confirmed"]:
        status = payment.check_payment_link_status(link_id)
        if status == "paid":
            db.update_booking_status(booking_id, "Confirmed")
            confirmed_message = build_booking_confirmed_message(booking_id, phone)
            clear_booking_context()
            clear_cancel_context()
            reset_navigation(MAIN_MENU)
            clear_conversation_state()
            msg.body(f"Payment received ✅.\n\n{confirmed_message}")
        elif status in ("cancelled", "expired"):
            db.delete_pending_booking(booking_id)
            clear_booking_context()
            reset_navigation(MAIN_MENU)
            msg.body(f"Payment link expired or cancelled ❌. Your booking was not confirmed.\n\nPlease try again.\n\n{get_main_menu_message(show_hint=False)}")
        else:
            msg.body(
                f"Payment not received ❌. Your booking is not confirmed.\n"
                f"Please try again using the payment link below or reply 'paid' when done:\n"
                f"{session.get('payment_link_url')}\n\n"
                f"(Reply '#' to cancel and start over.)"
            )
    else:
        msg.body(
            f"Please reply 'paid' when you have completed your payment.\n\n"
            f"Payment Link: {session.get('payment_link_url')}\n\n"
            f"If you prefer to cancel and start over, reply '#'."
        )


STATE_HANDLERS = {
    MAIN_MENU: handle_main_menu,
    ASK_NAME: handle_ask_name,
    ASK_DATE: handle_ask_date,
    ASK_CUSTOM_DATE: handle_ask_custom_date,
    SELECT_SLOT: handle_select_slot,
    ASK_SEATS: handle_ask_seats,
    SELECT_TABLE: handle_select_table,
    CONFIRM_BOOKING: handle_confirm_booking,
    VIEW_BOOKINGS: handle_view_bookings,
    CANCEL_SELECT: handle_cancel_select,
    CANCEL_CONFIRM: handle_cancel_confirm,
    ASK_WAITLIST: handle_ask_waitlist,
    AWAITING_PAYMENT: handle_awaiting_payment,
}


@bot_bp.route("/webhook", methods=["POST"])
def webhook():
    user_input = request.values.get("Body", "").strip()
    sender_phone = request.values.get("From", "").strip()

    response = MessagingResponse()
    message = response.message()

    # Track Twilio session for 24hr limit
    db.update_customer_session(sender_phone)

    _load_conversation_store(sender_phone)

    try:
        if "state" not in session:
            reset_navigation(MAIN_MENU)

        current_state = session.get("state", MAIN_MENU)
        handler = STATE_HANDLERS.get(current_state)
        if not handler:
            reset_navigation(MAIN_MENU)
            message.body(get_main_menu_message())
            return str(response)

        reset_commands = {"*", "#", "reset"}
        if user_input.lower() in reset_commands:
            if current_state == AWAITING_PAYMENT:
                booking_id = session.get("payment_booking_id")
                if booking_id:
                    db.delete_pending_booking(booking_id)
            clear_booking_context()
            clear_cancel_context()
            reset_navigation(MAIN_MENU)
            clear_conversation_state()
            message.body(get_main_menu_message())
            return str(response)

        if not user_input:
            send_state_prompt(current_state, sender_phone, message)
            return str(response)

        handler(user_input, sender_phone, message)
        return str(response)
    finally:
        _persist_conversation()

