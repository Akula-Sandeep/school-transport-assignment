"""Business rules shared by the decision engine, the anomaly detector and the
validator, so all three apply exactly the same definitions."""
import bisect
import re

from . import config as C
from . import geo

PHONE_RE = re.compile(C.PHONE_PATTERN)
EMAIL_RE = re.compile(C.EMAIL_PATTERN)
ADDRESS_RE = re.compile(r"House \d+, " + re.escape(C.ADDRESS_MARKER) + r" \d+")


# ------------------------------------------------------------ eligibility
def pre_assignment_outcome(student):
    """Return (decision, reason) when the student cannot enter assignment, else None."""
    if not student["transport_eligible"]:
        return "ineligible", "INELIGIBLE_WALK_ZONE"
    if not student["transport_opt_in"]:
        return "opted_out", "OPTED_OUT_GUARDIAN"
    if student["address_status"] != "verified":
        return "waitlisted", "WAITLIST_ADDRESS_PENDING"
    return None


def network_for(student):
    return "accessible" if student["requires_accessible_vehicle"] else "regular"


def stop_usable(stop, student):
    if stop["approval_status"] != "approved":
        return False
    if student["requires_accessible_vehicle"] and not stop["is_accessible"]:
        return False
    return True


def window_ok(student, pickup_min):
    return geo.to_min(student["pickup_window_start"]) <= pickup_min <= geo.to_min(student["pickup_window_end"])


# ------------------------------------------------------------ capacity
class CapacityBook:
    """Effective capacity of a bus on a date from base capacity + effective-dated events."""

    def __init__(self, buses, events):
        self.base = {b["bus_id"]: b["base_seated_capacity"] for b in buses}
        self.events = {}
        for e in events:
            self.events.setdefault(e["bus_id"], []).append(e)
        for lst in self.events.values():
            lst.sort(key=lambda e: e["effective_from"])

    def add(self, e):
        self.events.setdefault(e["bus_id"], []).append(e)
        self.events[e["bus_id"]].sort(key=lambda e: e["effective_from"])

    def capacity(self, bus_id, date):
        cap = self.base[bus_id]
        for e in self.events.get(bus_id, []):
            if e["effective_from"] <= date and (e["effective_to"] is None or date <= e["effective_to"]):
                cap = e["new_capacity"]
        return cap

    def has_events(self, bus_id):
        return bool(self.events.get(bus_id))


# ------------------------------------------------------------ contacts
def contact_problems(contact, student_id, date, channel=None):
    """List of reasons a contact may NOT be used for this student on this date
    (via `channel`, default the contact's preferred channel)."""
    probs = []
    if contact["student_id"] != student_id:
        probs.append("CONTACT_BELONGS_TO_OTHER_STUDENT")
    if contact["contact_status"] != "active":
        probs.append(f"CONTACT_{contact['contact_status'].upper()}")
    if not contact["consent_to_notify"]:
        probs.append("NO_CONSENT")
    if contact["valid_from"] > date or (contact["valid_to"] is not None and date > contact["valid_to"]):
        probs.append("CONTACT_NOT_EFFECTIVE")
    ch = channel or contact["preferred_channel"]
    if ch in ("sms", "app_push") and not PHONE_RE.match(contact["phone"] or ""):
        probs.append("MALFORMED_PHONE")
    if ch == "email" and not EMAIL_RE.match(contact["email"] or ""):
        probs.append("MALFORMED_EMAIL")
    return probs


def pick_contact(contacts_for_student, student_id, date):
    """Highest-priority contact usable on the date, else None (notification suppressed)."""
    for c in sorted(contacts_for_student, key=lambda c: (c["priority"], c["contact_id"])):
        if not contact_problems(c, student_id, date):
            return c
    return None


# ------------------------------------------------------------ timelines
ACTIVE_EVENTS = ("ASSIGNED", "REASSIGNED")


def build_segments(events, school_dates):
    """Turn append-only assignment events into active service segments.

    Returns {assignment_id: [(start_idx, end_idx, route_id, stop_id, event_id), ...]}
    with day indices into school_dates (inclusive). An event takes effect on the
    first school day on/after its event_date.
    """
    by_asn = {}
    for e in events:
        by_asn.setdefault(e["assignment_id"], []).append(e)
    n = len(school_dates)
    out = {}
    for asn, lst in by_asn.items():
        lst.sort(key=lambda e: e["event_seq"])
        segs = []
        for i, e in enumerate(lst):
            if e["event_type"] not in ACTIVE_EVENTS:
                continue
            start = bisect.bisect_left(school_dates, e["event_date"])
            end = n - 1
            if i + 1 < len(lst):
                end = bisect.bisect_left(school_dates, lst[i + 1]["event_date"]) - 1
            if start <= end:
                segs.append((start, end, e["route_id"], e["stop_id"], e["event_id"]))
        out[asn] = segs
    return out


def final_status(events_sorted):
    status = None
    for e in events_sorted:
        status = {"ASSIGNED": "active", "REASSIGNED": "active", "WAITLISTED": "waitlisted",
                  "INELIGIBLE": "ineligible", "OPTED_OUT": "opted_out", "ENDED": "ended"}[e["event_type"]]
    return status


ALLOWED_TRANSITIONS = {
    None: {"ASSIGNED", "WAITLISTED", "INELIGIBLE", "OPTED_OUT"},
    "ASSIGNED": {"REASSIGNED", "WAITLISTED", "ENDED"},
    "REASSIGNED": {"REASSIGNED", "WAITLISTED", "ENDED"},
    "WAITLISTED": {"ASSIGNED", "ENDED"},
    "INELIGIBLE": {"ENDED"},
    "OPTED_OUT": {"ENDED"},
    "ENDED": set(),
}
