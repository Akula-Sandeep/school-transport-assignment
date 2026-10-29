"""Scale presets, business-rule constants and enumerations.

Every number that drives a business decision lives here so the rules are
documented in one place and can be cited from the README.
"""
from dataclasses import dataclass, asdict

GENERATOR_VERSION = "1.0.0"
DEFAULT_SEED = 20261022
SCHOOL_YEAR = 2026


@dataclass(frozen=True)
class Scale:
    name: str
    students: int
    buses: int
    stops: int
    school_days: int
    ring_sectors: tuple          # zones per ring: (urban, suburban, rural)
    accessible_buses: int        # buses with lift + wheelchair positions
    spare_regular: int           # regular buses held back as replacements
    spare_accessible: int        # accessible buses held back as replacements
    anomalies_per_type: int      # labelled edge cases injected per type
    capacity_events: int         # baseline (engine-handled) capacity changes
    weather_days: int            # network-wide weather disruption days
    geo_scale: float = 1.0       # shrinks the service area for smaller datasets

    def as_dict(self):
        d = asdict(self)
        d["ring_sectors"] = list(self.ring_sectors)
        return d


SCALES = {
    # Used by the unit tests: seconds to run.
    "tiny": Scale("tiny", 220, 8, 28, 15, (2, 3, 3), 2, 1, 0, 2, 2, 1, 0.6),
    # Quick-look dataset with every feature exercised.
    "starter": Scale("starter", 600, 14, 45, 30, (3, 4, 4), 3, 1, 1, 3, 3, 1, 0.65),
    # Baseline volume required by the brief.
    "full": Scale("full", 5000, 100, 300, 200, (6, 8, 10), 15, 5, 2, 8, 10, 4, 1.0),
}

# --------------------------------------------------------------------------
# Calendar
# --------------------------------------------------------------------------
FIRST_SCHOOL_DAY = "2026-06-08"   # Monday
PLANNING_DATE = "2026-06-01"      # date the annual route plan is decided
HOLIDAYS = {
    "2026-08-15", "2026-10-02", "2026-10-20",
    "2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13",
    "2026-12-25", "2026-12-28", "2026-12-29", "2026-12-30", "2026-12-31",
    "2027-01-01", "2027-01-26", "2027-03-04",
}

# --------------------------------------------------------------------------
# Geography (synthetic plane, school at the origin, units = km)
# --------------------------------------------------------------------------
SCHOOL_XY = (0.0, 0.0)
# ring name, inner radius km, outer radius km, avg bus speed km/h, zone max walk m
# (radii are multiplied by Scale.geo_scale; see geo.configure)
RINGS = [
    ("urban", 0.0, 5.0, 18.0, 600),
    ("suburban", 5.0, 11.0, 28.0, 800),
    ("rural", 11.0, 17.0, 38.0, 1200),
]
RING_STUDENT_SHARE = {"urban": 0.50, "suburban": 0.35, "rural": 0.15}
STOP_MIN_RADIUS_KM = 1.0
STOP_MIN_SEPARATION_KM = 0.35
ROAD_CIRCUITY = 1.3      # road km = straight-line km * 1.3
WALK_CIRCUITY = 1.2      # walking m = straight-line m * 1.2
COORD_PRECISION_KM = 0.05  # home coordinates are coarsened to a 50 m grid (data minimisation)

# --------------------------------------------------------------------------
# Business rules
# --------------------------------------------------------------------------
WALK_ZONE_KM = 1.6               # students living closer are not eligible for transport
GRADE_WALK_CAP_M = {"KG": 500, "1": 500, "2": 500, "3": 800, "4": 800, "5": 800}
DEFAULT_GRADE_WALK_CAP_M = 1200  # grades 6-12
MOBILITY_WALK_CAP_M = {"wheelchair": 300, "walker": 400, "other": 600}
TARGET_ARRIVAL_MIN = 7 * 60 + 45  # buses aim to reach school at 07:45 (bell 08:00)
ARRIVAL_SHIFT_RANGE = (-10, 5)     # engine may move a route's arrival 07:35..07:50
MAX_ROUTE_MIN = 60.0               # first pickup -> school arrival (also max ride time)
PLAN_LOAD_FACTOR = 0.90            # annual plan fills buses to 90% (headroom for joiners)
MAX_FEASIBLE_SPEED_KMPH = 70.0     # any leg implying a faster speed is impossible
MIN_LEG_MIN = 0.1                  # any non-zero leg must take at least 6 s (model resolution)
DWELL_MIN = {"regular": 1.0, "accessible": 2.0}  # accessible: lift deployment
DEFAULT_WINDOW = ("06:30", "07:45")
LATE_THRESHOLD_MIN = 5             # bus later than this vs schedule => boarded_late
MAX_WAIT_MIN = 15                  # student waits this long, then pickup is missed
DELAY_NOTIFY_MIN = 10              # route delays >= this trigger guardian notices

# --------------------------------------------------------------------------
# Synthetic contact conventions (unroutable by design)
# --------------------------------------------------------------------------
PHONE_PATTERN = r"^\+999-555-\d{7}$"      # +999 is not an assigned country code
EMAIL_PATTERN = r"^[a-z0-9.\-]+@example\.org$"  # RFC 2606 reserved domain
ADDRESS_MARKER = "Synth Street"            # every synthetic address contains this

# --------------------------------------------------------------------------
# Enumerations (single source of truth, also used by schema + validation)
# --------------------------------------------------------------------------
GRADES = ["KG"] + [str(g) for g in range(1, 13)]
ZONE_TYPES = ["urban", "suburban", "rural"]
STOP_APPROVAL = ["approved", "pending", "rejected"]
SAFETY_RATINGS = ["A", "B", "C"]
STOP_SOURCES = ["planned", "guardian_request"]
BUS_TYPES = ["large", "standard", "midi", "accessible"]
FLEET_ROLES = ["route", "spare"]
BUS_STATUS = ["in_service", "maintenance"]
EMPLOYMENT_STATUS = ["active", "on_leave"]
MOBILITY_AIDS = ["none", "wheelchair", "walker", "other"]
ADDRESS_STATUS = ["verified", "pending"]
ENROLLMENT_STATUS = ["active", "withdrawn"]
RELATIONSHIPS = ["mother", "father", "guardian", "grandparent", "other"]
CHANNELS = ["sms", "email", "app_push"]
CONTACT_STATUS = ["active", "bounced", "inactive"]
SERVICE_TYPES = ["regular", "accessible"]
ROUTE_STATUS = ["active", "suspended"]
CANDIDATE_METHODS = ["radial_inbound", "nearest_neighbor", "two_opt"]
DECISIONS = ["assigned", "waitlisted", "ineligible", "opted_out"]
DECISION_REASONS = [
    "ASSIGNED_NEAREST_STOP", "ASSIGNED_ALT_STOP_FOR_WINDOW", "ASSIGNED_WINDOW_EXCEPTION",
    "ASSIGNED_FROM_WAITLIST", "MIDYEAR_ASSIGNED",
    "WAITLIST_NO_STOP_IN_RANGE", "WAITLIST_NO_ACCESSIBLE_STOP", "WAITLIST_NO_CAPACITY",
    "WAITLIST_NO_ROUTE_SERVES_STOP", "WAITLIST_ADDRESS_PENDING", "WAITLIST_CAPACITY_REDUCED",
    "INELIGIBLE_WALK_ZONE", "OPTED_OUT_GUARDIAN",
    "CAPACITY_REDUCED_REASSIGN", "MANUAL_OVERRIDE", "STUDENT_WITHDRAWN",
]
CURRENT_STATUS = ["active", "waitlisted", "ineligible", "opted_out", "ended"]
EVENT_TYPES = ["ASSIGNED", "WAITLISTED", "INELIGIBLE", "OPTED_OUT", "REASSIGNED", "ENDED"]
ACTOR_ROLES = ["system", "academic_administrator", "support_staff", "platform_administrator"]
CAPACITY_EVENT_TYPES = ["SEATS_OUT_OF_SERVICE", "REPLACED_SMALLER", "REPLACED_LARGER"]
DISRUPTION_TYPES = ["traffic_delay", "breakdown", "weather", "driver_absence"]
DISRUPTION_RESOLUTIONS = ["delayed_service", "replacement_bus", "spare_driver", "cancelled"]
ATTENDANCE_STATUS = ["boarded", "boarded_late", "absent_reported", "no_show", "missed_pickup"]
RECORDED_BY = ["driver_app", "guardian_portal", "system"]
NOTIFICATION_TYPES = [
    "ASSIGNMENT_CONFIRMED", "WINDOW_EXCEPTION", "WAITLIST_NOTICE", "REASSIGNMENT_NOTICE",
    "SERVICE_ENDED", "ROUTE_DELAY", "SERVICE_CANCELLED", "MISSED_PICKUP", "NO_SHOW",
]
DELIVERY_STATUS = ["delivered", "bounced", "failed", "suppressed"]
TRIGGER_ENTITIES = ["assignment_event", "route_disruption", "attendance_event"]
TERMS = ["T1", "T2", "T3"]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]

ANOMALY_TYPES = [
    "capacity_exceeded",
    "incompatible_route",
    "impossible_travel_time",
    "notification_invalid_contact",
    "unapproved_address_exposed",
]
