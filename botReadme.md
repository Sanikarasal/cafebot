# bot.py Section-by-Section Explanation

This document explains `bot.py` in order, covering the current file from line `1` through line `1001`.

## Overall Purpose

`bot.py` defines the WhatsApp/Twilio chatbot used by CoziCafe. It:

- receives incoming webhook messages from Twilio
- tracks a user's conversation state
- guides the user through booking, viewing, cancelling, waitlisting, and payment
- stores temporary conversation data in a request-local session wrapper backed by the database

## Line-by-Line Section Map

### Lines 1-12: Imports and Flask blueprint setup

- Imports Python standard modules like `os` and `datetime`.
- Imports Flask request tools, Twilio response builder, and the local app modules `db`, `payment`, and `utils`.
- Creates `bot_bp`, the Flask `Blueprint` that exposes the chatbot webhook route.

### Lines 14-17: Twilio environment configuration

- Reads Twilio-related environment variables with `os.getenv(...)`.
- These values are expected to be configured outside the code, usually in `.env` or deployment settings.

### Lines 19-35: State machine constants and shared text

- Defines all conversation states such as `MAIN_MENU`, `ASK_NAME`, `SELECT_SLOT`, `CANCEL_CONFIRM`, and `AWAITING_PAYMENT`.
- This file behaves like a state machine: each user reply is handled differently depending on the current state.
- Also defines reusable text fragments for invalid input and reset instructions.

### Lines 38-41: `_append_hint(text, show=False)`

- Adds the reset/help hint to a message only when `show=True`.
- Keeps prompt-building code cleaner by centralizing the hint logic.

### Lines 44-45: `_invalid_choice(text)`

- Prefixes a prompt with `"Invalid choice..."`.
- Always includes the navigation hint so the user knows how to recover.

### Lines 48-89: `ConversationStore` class

- Wraps conversation data for one user.
- Stores the phone number, current state, arbitrary state data, last update time, and a `cleared` flag.
- Implements dictionary-like methods such as `get`, `__getitem__`, `__setitem__`, `pop`, `setdefault`, and `__contains__`.
- Treats `"state"` specially so it lives as a top-level attribute instead of inside the generic `data` dictionary.

### Lines 92-97: `_get_conversation_store()`

- Reads the request-scoped store from Flask's `g`.
- If none exists yet, it creates a new `ConversationStore` and saves it into `g`.

### Line 100: `session = LocalProxy(_get_conversation_store)`

- Creates a proxy named `session`.
- Anywhere later in the file, `session[...]` refers to the current request's `ConversationStore`.
- This gives the code a session-like API without using Flask's built-in session object.

### Lines 103-115: `_load_conversation_store(phone)`

- Loads the saved conversation for a phone number from the database with `db.get_conversation(phone)`.
- Normalizes `"idle"` or missing state to `None`.
- Rebuilds a `ConversationStore` object and attaches it to `g`.

### Lines 118-123: `_persist_conversation()`

- Saves the current conversation back to the database at the end of the request.
- Skips saving if the store was cleared or if no phone number is attached.
- Uses `"idle"` when no active state exists.

### Lines 126-132: `clear_conversation_state()`

- Deletes the saved conversation from the database.
- Clears local in-memory state and marks the store as `cleared` so it will not be re-saved accidentally.

### Lines 135-145: `get_main_menu_message(show_hint=True)`

- Builds the chatbot home menu text.
- Shows the main actions: book, view, cancel, and contact.
- Optionally appends the navigation hint.

### Lines 148-149: `get_ask_name_prompt()`

- Returns the prompt asking the customer for their name.

### Lines 152-158: `get_ask_date_prompt()`

- Returns the prompt offering `Today`, `Tomorrow`, or `Choose Date`.

### Lines 161-162: `get_ask_custom_date_prompt()`

- Returns the prompt asking for a manual date in `YYYY-MM-DD` format.

### Lines 165-166: `get_ask_seats_prompt()`

- Returns the prompt asking for the guest count.

### Lines 169-171: `clear_payment_context()`

- Removes payment-related keys from the session.
- Used when a payment flow is cancelled, finished, or reset.

### Lines 174-181: `clear_booking_context()`

- Removes all temporary booking data from the session.
- This includes name, date, slot, seat count, table selection, and combo-table information.
- Also clears payment data by calling `clear_payment_context()`.

### Lines 184-186: `clear_cancel_context()`

- Removes temporary cancellation-related session fields.

### Lines 189-195: `reset_navigation(state=MAIN_MENU)`

- Clears navigation history and sets a fresh current state.
- Used when starting over or jumping back to a clean state.

### Lines 198-205: `transition_to(new_state)`

- Moves the conversation to a new state.
- Pushes the current state into `state_history` so the previous path is preserved.

### Lines 208-219: `go_back(phone, msg)`

- Pops the last state from navigation history and sends the prompt for that earlier state.
- If no history exists, it falls back to the main menu.
- This helper exists for backward navigation, although the current webhook flow mainly uses reset commands instead.

### Lines 222-246: `get_slot_prompt_for_date(selected_date)`

- Fetches available slots for a chosen date from the database.
- If the chosen date is today, it filters out past slots.
- Stores the available slot choices in `session["slot_options"]`.
- Builds a numbered list like `1. 6:00 PM (4 seats left)`.

### Lines 249-330: `get_select_table_prompt()`

- Figures out what table options are available for the chosen date, slot, and party size.
- There are four possible outcomes:
- `AUTO`: exactly one matching table exists, so it is auto-assigned.
- `CHOOSE`: multiple valid tables exist, so the user must choose one.
- `COMBO`: no single table fits, but a combination of tables can fit the party.
- `NO_TABLES`: no valid table setup is available.
- The function also writes the chosen table options or combo metadata into the session for later handlers.

### Lines 333-355: `get_confirm_booking_prompt(phone)`

- Builds a booking summary before final confirmation.
- Shows name, phone, date, time, guest count, table, and location.
- Supports both normal single-table bookings and combo-table bookings.

### Lines 358-380: `get_view_bookings_prompt(phone)`

- Fetches active bookings for the phone number.
- Formats them as a readable list.
- If a booking belongs to a combo group, it loads and shows all combo table numbers.

### Lines 383-405: `get_cancel_select_prompt(phone)`

- Loads the user's active bookings and converts them into numbered cancellation options.
- Saves those choices into `session["cancel_options"]`.
- If no bookings exist, it returns a friendly message instead.

### Lines 408-426: `get_cancel_confirm_prompt(phone)`

- Builds the final "Are you sure?" message for a selected booking cancellation.
- Re-loads the booking from the database using the stored `cancel_booking_id`.

### Lines 429-463: `build_booking_confirmed_message(booking_id, phone)`

- Builds the final success message shown after a booking is confirmed and payment is complete.
- Includes booking details, table/location details, arrival instructions, and a contact number.
- Handles both single-table and combo-table bookings.

### Lines 466-473: `get_ask_waitlist_prompt()`

- Builds the yes/no prompt for joining the waitlist when no table is available.

### Lines 476-525: `send_state_prompt(state, phone, msg)`

- Central dispatcher for showing the correct prompt for a given state.
- Most states simply call one prompt builder, but some states include logic:
- `SELECT_TABLE` may automatically move to `ASK_WAITLIST` or `CONFIRM_BOOKING` depending on availability mode.
- `AWAITING_PAYMENT` re-shows the payment link if the user reaches that state again.
- If the state is unknown, the code safely resets back to the main menu.

### Lines 528-546: `handle_main_menu(user_input, phone, msg)`

- Interprets the user's main-menu selection.
- Starts a new booking flow, opens booking view, starts cancellation, or returns the cafe contact number.
- Invalid input redisplays the main menu with error text.

### Lines 549-557: `handle_ask_name(user_input, phone, msg)`

- Validates that the name is not blank.
- Stores the name in `session["b_name"]`.
- Advances the flow to date selection.

### Lines 560-577: `handle_ask_date(user_input, phone, msg)`

- Converts menu choice `1`, `2`, or `3` into a booking date.
- `1` means today, `2` means tomorrow, and `3` moves to manual date entry.
- On success, stores the selected date and moves to slot selection.

### Lines 580-594: `handle_ask_custom_date(user_input, phone, msg)`

- Parses a manually entered date using `datetime.strptime`.
- Rejects invalid formats and past dates.
- On success, stores the date and shows available slots.

### Lines 597-622: `handle_select_slot(user_input, phone, msg)`

- Reads the precomputed slot options from the session.
- Validates that the user sent a numeric option within range.
- Stores the selected slot time and how many seats are available in that slot.
- Advances to guest-count entry.

### Lines 625-672: `handle_ask_seats(user_input, phone, msg)`

- Validates guest count input and limits it to `1-8`.
- Checks whether the selected slot still has enough available capacity.
- Calls `db.check_slot_capacity(...)` for a deeper capacity validation.
- If the request is valid, stores the seat count and moves to table selection.
- Depending on the table-selection mode, it may:
- show a table list
- auto-assign a table and move to confirmation
- offer combo tables
- redirect to waitlist

### Lines 675-722: `handle_select_table(user_input, phone, msg)`

- Handles the user's reply when table selection is required.
- If combo mode is active:
- `1` accepts the combined tables and moves to confirmation
- `2` clears date/slot info and restarts from date selection
- In normal mode, it validates the chosen table option, stores the selected table number and location, and moves to confirmation.

### Lines 725-809: `handle_confirm_booking(user_input, phone, msg)`

- Finalizes booking after the user confirms.
- If the user chooses `2`, it cancels the flow and resets back to the main menu.
- If combo tables are being used, it calls `db.create_combo_booking(...)`.
- Otherwise, it calls `db.create_booking(...)`.
- On successful booking creation, it starts payment by calling `payment.create_payment_link(...)`.
- It stores payment IDs/URL in the session and moves the state to `AWAITING_PAYMENT`.
- If payment-link creation fails, it deletes the pending booking and resets safely.
- If the database reports a duplicate booking for the same slot, it redirects the user to their current bookings list instead of creating another one.

### Lines 812-814: `handle_view_bookings(user_input, phone, msg)`

- Simple handler for the booking-view state.
- Any input just re-shows the active bookings list.

### Lines 817-835: `handle_cancel_select(user_input, phone, msg)`

- Validates the booking number chosen for cancellation.
- Stores the selected booking ID in the session.
- Moves to the confirmation step.

### Lines 838-863: `handle_cancel_confirm(user_input, phone, msg)`

- Handles the final yes/no answer for cancellation.
- `2` means cancel the cancellation flow and return to the main menu.
- `1` calls `db.cancel_booking_by_id(...)`.
- On success, it clears cancellation state and returns a success message.
- On failure, it moves the user back to booking selection.

### Lines 866-897: `handle_ask_waitlist(user_input, phone, msg)`

- Handles the waitlist decision when no booking can be placed.
- If the user says yes, it stores the request with `db.add_to_waitlist(...)`.
- Then it clears booking state and returns to the main menu with a confirmation message.
- If the user says no, it simply resets to the main menu.

### Lines 900-936: `handle_awaiting_payment(user_input, phone, msg)`

- Manages the stage after a booking exists but before payment is confirmed.
- If the stored payment context is missing, it falls back to the main menu.
- If the user replies with words like `paid`, `done`, or `confirmed`, it checks payment status with `payment.check_payment_link_status(...)`.
- If payment is successful, it sends the final confirmation message and clears the conversation.
- If payment is expired or cancelled, it deletes the pending booking.
- Otherwise, it reminds the user to complete payment using the same link.

### Lines 939-953: `STATE_HANDLERS`

- Maps each state constant to its corresponding handler function.
- This lets the webhook dispatch incoming messages dynamically based on current state.

### Lines 956-1000: `webhook()`

- Defines the Flask route `"/webhook"` that Twilio calls for incoming WhatsApp messages.
- Reads `Body` and `From` from the incoming request.
- Creates a `MessagingResponse` object, which Twilio expects as the response format.
- Updates the customer's session activity in the database.
- Loads the saved conversation for the sender's phone number.
- Ensures the user always has a valid state, defaulting to `MAIN_MENU`.
- Supports global reset commands: `*`, `#`, and `reset`.
- If reset happens during pending payment, it deletes the pending booking first.
- If the incoming message body is empty, it simply re-sends the current state's prompt.
- Otherwise, it finds the correct handler from `STATE_HANDLERS` and lets that handler process the reply.
- The `finally` block always persists the updated conversation back to the database.

### Line 1001: trailing blank line

- The file ends with a blank line after `_persist_conversation()`.
- It has no runtime effect, but it is normal in source files.

## End-to-End Flow Summary

The typical booking flow in `bot.py` is:

1. Main menu
2. Ask name
3. Ask date
4. Show available slots
5. Ask guest count
6. Choose table, auto-assign table, or offer combo tables
7. Confirm booking
8. Generate payment link
9. Wait for user to reply `paid`
10. Verify payment and send final booking confirmation

Alternative flows in the same file let the user:

- view active bookings
- cancel an existing booking
- join a waitlist when no tables are available
- reset the entire conversation at almost any point
