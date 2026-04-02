from datetime import datetime, time as dt_time, date as dt_date
import re
import pytz

# Configurable Cafe Timezone
CAFE_TIMEZONE = pytz.timezone('Asia/Kolkata') # Change this to your local timezone

BOOKING_STATUS_CANONICAL = {
    'active': 'Confirmed',
    'pending': 'Pending',
    'confirmed': 'Confirmed',
    'arrived': 'Arrived',
    'completed': 'Completed',
    'no-show': 'No-show',
    'noshow': 'No-show',
    'cancelled': 'cancelled',
    'canceled': 'cancelled',
}

def normalize_booking_status(status):
    """Normalize booking status to the canonical set used by the system."""
    if status is None:
        return None
    raw = str(status).strip()
    if not raw:
        return None
    key = raw.lower()
    return BOOKING_STATUS_CANONICAL.get(key, raw)

def get_active_booking_statuses(include_legacy=True):
    """Return statuses considered 'active' for operational logic."""
    statuses = ("Pending", "Confirmed", "Arrived")
    if include_legacy:
        statuses = statuses + ("active",)
    return statuses

def get_cafe_time():
    """Returns the current aware datetime in the configured Cafe timezone."""
    return datetime.now(pytz.utc).astimezone(CAFE_TIMEZONE)

def get_cafe_date():
    """Returns the current date in the configured Cafe timezone."""
    return get_cafe_time().date()

#
# Slot normalization helpers
#

_SLOT_SPLIT_RE = re.compile(r"\s*[–-]\s*")

def _parse_time_part(part):
    if not part:
        return None
    raw = str(part).strip()
    if not raw:
        return None
    candidates = [
        raw,
        raw.replace(" ", ""),
        raw.replace(".", ""),
        raw.replace(" ", "").replace(".", ""),
    ]
    formats = ("%I:%M%p", "%I%p", "%I:%M %p", "%I %p", "%H:%M", "%H")
    for cand in candidates:
        for fmt in formats:
            try:
                return datetime.strptime(cand.upper(), fmt).time()
            except ValueError:
                continue
    return None

def parse_slot_time(slot_str, base_date=None):
    """
    Parse slot string into (start, end).
    If base_date provided, returns (start_dt, end_dt).
    If base_date is None, returns (start_time, end_time).
    Returns (None, None) on failure.
    """
    if not slot_str:
        return (None, None)
    parts = _SLOT_SPLIT_RE.split(str(slot_str).strip(), maxsplit=1)
    if not parts:
        return (None, None)
    start_raw = parts[0].strip()
    end_raw = parts[1].strip() if len(parts) > 1 else None

    start_time = _parse_time_part(start_raw)
    end_time = _parse_time_part(end_raw) if end_raw else None

    if start_time is None:
        return (None, None)

    if base_date is not None:
        if isinstance(base_date, str):
            try:
                base_date = datetime.strptime(base_date, "%Y-%m-%d").date()
            except ValueError:
                return (None, None)
        if not isinstance(base_date, dt_date):
            return (None, None)
        start_dt = CAFE_TIMEZONE.localize(datetime.combine(base_date, start_time))
        end_dt = CAFE_TIMEZONE.localize(datetime.combine(base_date, end_time)) if end_time else None
        return (start_dt, end_dt)

    return (start_time, end_time)

def _format_time(t):
    if not isinstance(t, dt_time):
        return None
    return t.strftime("%I:%M %p").lstrip("0")

def normalize_slot_label(slot_str):
    """
    Normalize slot label to canonical display format: "H:MM AM - H:MM AM".
    Returns original trimmed string if parsing fails.
    """
    if not slot_str:
        return ""
    start_time, end_time = parse_slot_time(slot_str)
    if start_time is None:
        return str(slot_str).strip()
    start_label = _format_time(start_time)
    if end_time:
        end_label = _format_time(end_time)
        return f"{start_label} - {end_label}"
    return start_label

def slots_equal(slot_a, slot_b):
    """Return True if two slot strings represent the same time range."""
    if not slot_a or not slot_b:
        return False
    a_start, a_end = parse_slot_time(slot_a)
    b_start, b_end = parse_slot_time(slot_b)
    if a_start and b_start:
        if a_start != b_start:
            return False
        if a_end and b_end:
            return a_end == b_end
        return True
    return normalize_slot_label(slot_a).lower() == normalize_slot_label(slot_b).lower()

def sort_slot_labels(slot_labels):
    """Sort slot labels by start time; unparseable labels go last."""
    def _key(label):
        start, end = parse_slot_time(label)
        if start is None:
            return (1, normalize_slot_label(label))
        end_key = end if end else dt_time.max
        return (0, start, end_key)
    return sorted(slot_labels, key=_key)
