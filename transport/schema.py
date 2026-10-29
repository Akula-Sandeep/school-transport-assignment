"""Single source of truth for every table.

The same definitions generate the data dictionary (docs/data_dictionary.md),
the SQL DDL (schema.sql), drive CSV type parsing, and the generic integrity
checks in validate.py (required, enum, pattern, PK uniqueness, FK integrity).
"""
from dataclasses import dataclass, field
from typing import Optional, List

from . import config as C

ID = {
    "zone": r"^ZONE-\d{4}$",
    "stop": r"^STOP-\d{6}$",
    "bus": r"^BUS-\d{6}$",
    "driver": r"^DRV-\d{6}$",
    "student": r"^STU-\d{6}$",
    "contact": r"^GC-\d{6}$",
    "route": r"^ROUTE-\d{4}-\d{6}$",
    "candidate": r"^RC-\d{4}-\d{6}$",
    "route_stop": r"^RS-\d{4}-\d{6}$",
    "assignment": r"^ASN-STU-\d{6}-\d{4}$",
    "assignment_event": r"^AEV-\d{4}-\d{6}$",
    "capacity_event": r"^BCE-\d{4}-\d{6}$",
    "disruption": r"^DIS-\d{4}-\d{6}$",
    "attendance": r"^ATT-\d{4}-\d{7}$",
    "notification": r"^NOT-\d{4}-\d{6}$",
}
DATE = r"^\d{4}-\d{2}-\d{2}$"
TIME = r"^\d{2}:\d{2}$"
DATETIME = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$"


@dataclass
class Field:
    name: str
    type: str                      # str|int|float|bool|date|time|datetime
    required: bool = True
    desc: str = ""
    allowed: Optional[List] = None
    unit: Optional[str] = None
    unique: bool = False
    pattern: Optional[str] = None
    fk: Optional[str] = None       # "table.column"
    rule: Optional[str] = None     # human-readable validation rule

    def __post_init__(self):
        if self.pattern is None:
            self.pattern = {"date": DATE, "time": TIME, "datetime": DATETIME}.get(self.type)


@dataclass
class Table:
    name: str
    entity: str
    kind: str                      # master | transaction | event | bridge | reference
    desc: str
    pk: str
    fields: List[Field] = field(default_factory=list)

    @property
    def columns(self):
        return [f.name for f in self.fields]

    def field(self, name):
        for f in self.fields:
            if f.name == name:
                return f
        raise KeyError(name)


F = Field
TABLES: List[Table] = []


def table(name, entity, kind, desc, pk, fields):
    t = Table(name, entity, kind, desc, pk, fields)
    for f in t.fields:
        if f.name == pk:
            f.unique = True
    TABLES.append(t)
    return t


table("school_day", "SchoolDay", "reference",
      "Operating calendar: one row per school day with service.", "service_date", [
          F("service_date", "date", desc="Calendar date with bus service"),
          F("day_index", "int", desc="1-based sequence number of the school day", unique=True,
            rule="contiguous 1..N in date order"),
          F("weekday", "str", allowed=C.WEEKDAYS, desc="Day of week"),
          F("term", "str", allowed=C.TERMS, desc="Academic term"),
      ])

table("address_zone", "AddressZone", "master",
      "Synthetic service-area zones: rings (urban/suburban/rural) x angular sectors around the school.",
      "zone_id", [
          F("zone_id", "str", pattern=ID["zone"], desc="Zone identifier"),
          F("zone_name", "str", unique=True, desc="Human-readable zone name"),
          F("zone_type", "str", allowed=C.ZONE_TYPES, desc="Ring the zone belongs to"),
          F("ring_index", "int", allowed=[0, 1, 2], desc="0=urban,1=suburban,2=rural"),
          F("sector_index", "int", desc="Angular sector within the ring (0-based)"),
          F("inner_radius_km", "float", unit="km", desc="Inner radius from school"),
          F("outer_radius_km", "float", unit="km", desc="Outer radius from school",
            rule="outer_radius_km > inner_radius_km"),
          F("start_angle_deg", "float", unit="deg", desc="Sector start angle"),
          F("end_angle_deg", "float", unit="deg", desc="Sector end angle"),
          F("centroid_x_km", "float", unit="km", desc="Sector centroid x"),
          F("centroid_y_km", "float", unit="km", desc="Sector centroid y"),
          F("avg_bus_speed_kmph", "float", unit="km/h", desc="Average bus speed in the zone"),
          F("max_walk_m", "int", unit="m", desc="Maximum walk to a stop allowed in this zone"),
      ])

table("stop", "Stop", "master",
      "Candidate and approved bus stops. Only approved stops may appear on a route.", "stop_id", [
          F("stop_id", "str", pattern=ID["stop"], desc="Stop identifier"),
          F("zone_id", "str", fk="address_zone.zone_id", desc="Zone containing the stop"),
          F("stop_name", "str", desc="Public stop name (no residential address)"),
          F("x_km", "float", unit="km", desc="Stop x coordinate"),
          F("y_km", "float", unit="km", desc="Stop y coordinate"),
          F("approval_status", "str", allowed=C.STOP_APPROVAL,
            desc="Safety/approval state", rule="route_stop may only reference approved stops"),
          F("approval_date", "date", required=False,
            desc="Decision date (null while pending)", rule="required unless pending"),
          F("is_accessible", "bool", desc="Kerb/ramp suitable for lift boarding"),
          F("safety_rating", "str", allowed=C.SAFETY_RATINGS, desc="A best .. C unsafe"),
          F("stop_source", "str", allowed=C.STOP_SOURCES, desc="How the stop was proposed"),
          F("effective_from", "date", desc="First date the stop record is valid"),
          F("effective_to", "date", required=False, desc="Last valid date (null = open)",
            rule="effective_to >= effective_from"),
      ])

table("bus", "Bus", "master", "Fleet vehicles. Effective capacity on a date = latest bus_capacity_event "
      "covering that date, else base_seated_capacity.", "bus_id", [
          F("bus_id", "str", pattern=ID["bus"], desc="Bus identifier"),
          F("registration_code", "str", unique=True, desc="Synthetic plate"),
          F("bus_type", "str", allowed=C.BUS_TYPES, desc="Vehicle class"),
          F("base_seated_capacity", "int", unit="seats", desc="Certified seats",
            rule="20 <= value <= 80"),
          F("wheelchair_positions", "int", unit="positions", desc="Secured wheelchair positions",
            rule=">0 iff is_accessible"),
          F("is_accessible", "bool", desc="Has lift and wheelchair positions"),
          F("fleet_role", "str", allowed=C.FLEET_ROLES, desc="Scheduled on a route or kept spare"),
          F("status", "str", allowed=C.BUS_STATUS, desc="Operational status"),
          F("depot_zone_id", "str", fk="address_zone.zone_id", desc="Overnight depot zone"),
          F("commissioned_on", "date", desc="Entered fleet"),
      ])

table("driver", "Driver", "master", "Licensed drivers (synthetic).", "driver_id", [
    F("driver_id", "str", pattern=ID["driver"], desc="Driver identifier"),
    F("display_name", "str", desc="Synthetic display name"),
    F("license_class", "str", allowed=["PSV-HEAVY"], desc="Licence class"),
    F("license_expiry", "date", desc="Licence expiry", rule="must be after last school day"),
    F("accessible_trained", "bool", desc="Trained to operate lifts / secure wheelchairs",
      rule="required for accessible routes"),
    F("employment_status", "str", allowed=C.EMPLOYMENT_STATUS, desc="Employment state"),
    F("hired_on", "date", desc="Hire date"),
])

table("student", "Student", "master", "Learners. Home location coarsened to a 50 m grid; the address "
      "line is synthetic and sensitive (never shown on stops or notifications).", "student_id", [
          F("student_id", "str", pattern=ID["student"], desc="Student identifier"),
          F("display_name", "str", desc="Synthetic first name + initial"),
          F("grade", "str", allowed=C.GRADES, desc="Grade level"),
          F("home_zone_id", "str", fk="address_zone.zone_id", desc="Zone of home location"),
          F("home_x_km", "float", unit="km", desc="Home x (50 m grid)"),
          F("home_y_km", "float", unit="km", desc="Home y (50 m grid)"),
          F("address_line", "str", desc="Synthetic street address (SENSITIVE)"),
          F("address_status", "str", allowed=C.ADDRESS_STATUS, desc="Guardian address verification"),
          F("distance_to_school_km", "float", unit="km", desc="Derived straight-line distance"),
          F("transport_eligible", "bool", desc="Derived: distance_to_school_km >= 1.6"),
          F("transport_opt_in", "bool", desc="Guardian requested transport"),
          F("mobility_aid", "str", allowed=C.MOBILITY_AIDS, desc="Mobility aid used"),
          F("requires_accessible_vehicle", "bool", desc="Must ride an accessible route",
            rule="true when mobility_aid != none"),
          F("max_walk_m", "int", unit="m", desc="Derived: min(zone, grade, mobility caps)"),
          F("pickup_window_start", "time", desc="Earliest acceptable pickup (HH:MM)"),
          F("pickup_window_end", "time", desc="Latest acceptable pickup (HH:MM)",
            rule="end - start >= 15 min"),
          F("enrollment_status", "str", allowed=C.ENROLLMENT_STATUS, desc="Lifecycle state"),
          F("enrolled_on", "date", desc="Enrollment date (mid-year joiners after first school day)"),
          F("withdrawn_on", "date", required=False, desc="First day no longer enrolled",
            rule="withdrawn_on > enrolled_on; required iff withdrawn"),
      ])

table("guardian_contact", "GuardianContact", "master",
      "Guardian contacts, effective-dated (a replaced contact keeps its row; valid_to + superseded_by).",
      "contact_id", [
          F("contact_id", "str", pattern=ID["contact"], desc="Contact identifier"),
          F("student_id", "str", fk="student.student_id", desc="Student this contact is for"),
          F("relationship", "str", allowed=C.RELATIONSHIPS, desc="Relationship to student"),
          F("contact_label", "str", desc="Minimal label, e.g. 'Guardian 1 (mother)'"),
          F("phone", "str", desc="Synthetic unroutable phone",
            rule="valid iff matches ^\\+999-555-\\d{7}$"),
          F("email", "str", desc="Synthetic email on example.org", rule="valid iff @example.org"),
          F("preferred_channel", "str", allowed=C.CHANNELS, desc="Preferred channel"),
          F("priority", "int", desc="1 = primary contact", rule=">= 1"),
          F("consent_to_notify", "bool", desc="Guardian consent for transport messages"),
          F("contact_status", "str", allowed=C.CONTACT_STATUS, desc="Deliverability state"),
          F("valid_from", "date", desc="Effective from"),
          F("valid_to", "date", required=False, desc="Effective to (null = open)",
            rule="valid_to >= valid_from"),
          F("superseded_by", "str", required=False, fk="guardian_contact.contact_id",
            desc="Replacement contact when this one was retired"),
      ])

table("route", "Route", "transaction", "AM routes for the school year. Schedule fields are derived from "
      "route_stop legs.", "route_id", [
          F("route_id", "str", pattern=ID["route"], desc="Route identifier"),
          F("route_name", "str", unique=True, desc="Route name"),
          F("school_year", "int", desc="School year label"),
          F("session", "str", allowed=["AM"], desc="Service session"),
          F("service_type", "str", allowed=C.SERVICE_TYPES, desc="regular or accessible network"),
          F("bus_id", "str", fk="bus.bus_id", unique=True, desc="Scheduled bus"),
          F("driver_id", "str", fk="driver.driver_id", unique=True, desc="Scheduled driver"),
          F("selected_candidate_id", "str", fk="route_candidate.candidate_id",
            desc="Engine-selected candidate"),
          F("stop_count", "int", desc="Derived: number of route_stop rows"),
          F("final_leg_distance_km", "float", unit="km", desc="Last stop -> school road distance"),
          F("final_leg_min", "float", unit="min", desc="Last stop -> school travel time"),
          F("total_distance_km", "float", unit="km", desc="Derived: sum of legs + final leg"),
          F("total_travel_min", "float", unit="min",
            desc="Derived: first pickup -> school arrival incl. dwell", rule="<= 60"),
          F("departure_time", "time", desc="Derived: first pickup time"),
          F("school_arrival_time", "time", desc="Planned arrival (07:35..07:50)"),
          F("capacity_at_plan", "int", unit="seats", desc="Bus capacity on planning date"),
          F("planned_load", "int", unit="students", desc="Derived: students assigned at plan"),
          F("utilization_pct", "float", unit="%", desc="Derived: planned_load / capacity_at_plan"),
          F("status", "str", allowed=C.ROUTE_STATUS, desc="Route lifecycle state"),
          F("effective_from", "date", desc="First service date"),
          F("effective_to", "date", desc="Last service date"),
      ])

table("route_candidate", "RouteCandidate", "transaction",
      "Every stop ordering the planner evaluated, with travel time and feasibility (decision trace).",
      "candidate_id", [
          F("candidate_id", "str", pattern=ID["candidate"], desc="Candidate identifier"),
          F("route_id", "str", fk="route.route_id", desc="Route the candidate was built for"),
          F("method", "str", allowed=C.CANDIDATE_METHODS, desc="Ordering heuristic"),
          F("stop_sequence", "str", desc="Pipe-separated stop_ids in visiting order"),
          F("total_distance_km", "float", unit="km", desc="Candidate distance"),
          F("total_travel_min", "float", unit="min", desc="Candidate duration"),
          F("max_leg_speed_kmph", "float", unit="km/h", desc="Fastest implied leg speed"),
          F("feasible", "bool", desc="Duration and speed limits satisfied"),
          F("rejection_reason", "str", required=False, desc="Why infeasible / not selected"),
          F("rank", "int", desc="1 = best by travel time"),
          F("selected", "bool", desc="Chosen for the route", rule="exactly one per route"),
      ])

table("route_stop", "RouteStop", "bridge",
      "Bridge Route N:M Stop with sequence and leg timings (a stop can be served by several routes).",
      "route_stop_id", [
          F("route_stop_id", "str", pattern=ID["route_stop"], desc="Route-stop identifier"),
          F("route_id", "str", fk="route.route_id", desc="Route"),
          F("stop_id", "str", fk="stop.stop_id", desc="Stop"),
          F("stop_sequence", "int", desc="1..n visiting order", rule="contiguous per route"),
          F("leg_distance_km", "float", unit="km", desc="Road distance from previous stop (0 for first)"),
          F("leg_travel_min", "float", unit="min", desc="Travel time from previous stop",
            rule="implied speed <= 70 km/h"),
          F("dwell_min", "float", unit="min", desc="Boarding dwell at this stop"),
          F("cumulative_min", "float", unit="min", desc="Derived: minutes from departure to arrival here"),
          F("planned_arrival_time", "time", desc="Derived: departure_time + cumulative_min"),
          F("boarding_planned", "int", unit="students", desc="Derived: students assigned here at plan"),
          F("effective_from", "date", desc="Effective from"),
          F("effective_to", "date", desc="Effective to"),
      ])

table("assignment", "Assignment", "transaction",
      "One record per student per school year: the initial decision (immutable) plus derived current "
      "status. All later changes live in assignment_event.", "assignment_id", [
          F("assignment_id", "str", pattern=ID["assignment"], desc="ASN-<student_id>-<year>"),
          F("student_id", "str", fk="student.student_id", unique=True, desc="Student"),
          F("school_year", "int", desc="School year"),
          F("decision", "str", allowed=C.DECISIONS, desc="Initial decision"),
          F("decision_reason", "str", allowed=C.DECISION_REASONS, desc="Rule that produced the decision"),
          F("route_id", "str", required=False, fk="route.route_id", desc="Assigned route"),
          F("stop_id", "str", required=False, fk="stop.stop_id", desc="Assigned stop"),
          F("route_stop_id", "str", required=False, fk="route_stop.route_stop_id", desc="Route stop"),
          F("walk_distance_m", "int", required=False, unit="m", desc="Home -> stop walk",
            rule="<= student.max_walk_m"),
          F("scheduled_pickup_time", "time", required=False, desc="Derived from route_stop"),
          F("ride_time_min", "int", required=False, unit="min", desc="Pickup -> school arrival",
            rule="<= 60"),
          F("window_ok", "bool", required=False, desc="Pickup inside guardian window"),
          F("capacity_ok", "bool", required=False, desc="Route had a seat at decision time"),
          F("accessibility_ok", "bool", required=False, desc="Route compatible with mobility needs"),
          F("decided_on", "date", desc="Decision date"),
          F("effective_from", "date", desc="First day the decision applies"),
          F("current_status", "str", allowed=C.CURRENT_STATUS,
            desc="Derived from the last assignment_event"),
          F("status_as_of", "date", desc="Date current_status refers to (last school day)"),
      ])

table("assignment_event", "AssignmentEvent", "event",
      "Append-only history of assignment state changes (never overwritten).", "event_id", [
          F("event_id", "str", pattern=ID["assignment_event"], desc="Event identifier"),
          F("assignment_id", "str", fk="assignment.assignment_id", desc="Assignment"),
          F("student_id", "str", fk="student.student_id", desc="Student (denormalised for joins)"),
          F("event_seq", "int", desc="1..n per assignment", rule="contiguous"),
          F("event_type", "str", allowed=C.EVENT_TYPES, desc="State transition",
            rule="see lifecycle transitions in docs/design.md"),
          F("event_date", "date", desc="Date the new state takes effect", rule="non-decreasing per assignment"),
          F("route_id", "str", required=False, fk="route.route_id", desc="Route after event"),
          F("stop_id", "str", required=False, fk="stop.stop_id", desc="Stop after event"),
          F("route_stop_id", "str", required=False, fk="route_stop.route_stop_id", desc="Route stop after event"),
          F("reason_code", "str", allowed=C.DECISION_REASONS, desc="Rule / reason"),
          F("triggered_by", "str", required=False, desc="Upstream record id (e.g. BCE-...)"),
          F("actor_role", "str", allowed=C.ACTOR_ROLES, desc="Who/what made the change"),
      ])

table("bus_capacity_event", "BusCapacityEvent", "event",
      "Effective-dated capacity changes (seat banks out of service, vehicle swaps).", "capacity_event_id", [
          F("capacity_event_id", "str", pattern=ID["capacity_event"], desc="Event identifier"),
          F("bus_id", "str", fk="bus.bus_id", desc="Bus"),
          F("event_type", "str", allowed=C.CAPACITY_EVENT_TYPES, desc="Change type"),
          F("previous_capacity", "int", unit="seats", desc="Capacity before"),
          F("new_capacity", "int", unit="seats", desc="Capacity while effective"),
          F("effective_from", "date", fk="school_day.service_date", desc="First affected day"),
          F("effective_to", "date", required=False, desc="Last affected day (null = permanent)",
            rule="effective_to >= effective_from"),
          F("recorded_by", "str", allowed=C.ACTOR_ROLES, desc="Who recorded the change"),
      ])

table("route_disruption", "RouteDisruption", "event",
      "Daily operational disruptions and how they were resolved.", "disruption_id", [
          F("disruption_id", "str", pattern=ID["disruption"], desc="Disruption identifier"),
          F("route_id", "str", fk="route.route_id", desc="Affected route"),
          F("service_date", "date", fk="school_day.service_date", desc="Day"),
          F("disruption_type", "str", allowed=C.DISRUPTION_TYPES, desc="Cause"),
          F("from_stop_sequence", "int", desc="Delay applies from this stop onwards"),
          F("delay_min", "int", unit="min", desc="Added delay (0 if cancelled)"),
          F("service_cancelled", "bool", desc="No service on this day"),
          F("replacement_bus_id", "str", required=False, fk="bus.bus_id", desc="Spare bus used"),
          F("replacement_driver_id", "str", required=False, fk="driver.driver_id", desc="Spare driver used"),
          F("resolution", "str", allowed=C.DISRUPTION_RESOLUTIONS, desc="How it was handled"),
          F("reported_at", "datetime", desc="When dispatch logged it"),
      ])

table("attendance_event", "AttendanceEvent", "event",
      "One record per assigned student per school day (boarding outcome).", "attendance_id", [
          F("attendance_id", "str", pattern=ID["attendance"], desc="Event identifier"),
          F("service_date", "date", fk="school_day.service_date", desc="Day"),
          F("student_id", "str", fk="student.student_id", desc="Student"),
          F("assignment_id", "str", fk="assignment.assignment_id", desc="Assignment"),
          F("route_id", "str", fk="route.route_id", desc="Route active for the student that day"),
          F("stop_id", "str", fk="stop.stop_id", desc="Stop active that day"),
          F("scheduled_pickup_time", "time", desc="From route_stop"),
          F("bus_arrival_time", "time", required=False, desc="Actual bus arrival (null if not run/skipped)"),
          F("delay_min", "int", required=False, unit="min", desc="Arrival - scheduled"),
          F("attendance_status", "str", allowed=C.ATTENDANCE_STATUS, desc="Outcome"),
          F("disruption_id", "str", required=False, fk="route_disruption.disruption_id",
            desc="Disruption affecting this pickup"),
          F("recorded_by", "str", allowed=C.RECORDED_BY, desc="Source of the record"),
      ])

table("notification", "Notification", "event",
      "Guardian notifications; payloads carry ids and times only (no addresses or names).",
      "notification_id", [
          F("notification_id", "str", pattern=ID["notification"], desc="NOT-<year>-<n>"),
          F("student_id", "str", fk="student.student_id", desc="Student concerned"),
          F("contact_id", "str", required=False, fk="guardian_contact.contact_id",
            desc="Recipient (null when suppressed)"),
          F("notification_type", "str", allowed=C.NOTIFICATION_TYPES, desc="Template family"),
          F("channel", "str", required=False, allowed=C.CHANNELS, desc="Delivery channel"),
          F("trigger_entity", "str", allowed=C.TRIGGER_ENTITIES, desc="Table of the triggering record"),
          F("trigger_id", "str", desc="Triggering record id"),
          F("service_date", "date", desc="Date the notice relates to"),
          F("sent_at", "datetime", desc="Send timestamp (local school time)"),
          F("delivery_status", "str", allowed=C.DELIVERY_STATUS, desc="Derived from contact state"),
          F("failure_reason", "str", required=False, desc="Why not delivered / suppressed"),
          F("message_preview", "str", desc="Rendered message (must not contain addresses)"),
      ])

TABLE_BY_NAME = {t.name: t for t in TABLES}
TABLE_ORDER = [t.name for t in TABLES]

# Relationship catalogue (documented cardinality).
RELATIONSHIPS = [
    ("address_zone", "stop", "1:N", "zone contains stops"),
    ("address_zone", "student", "1:N", "zone contains student homes"),
    ("address_zone", "bus", "1:N", "depot zone"),
    ("student", "guardian_contact", "1:N", "1-3 contacts per student, effective-dated"),
    ("student", "assignment", "1:1", "one assignment per student per school year"),
    ("assignment", "assignment_event", "1:N", "append-only state history"),
    ("bus", "route", "1:0..1", "a scheduled bus runs at most one AM route"),
    ("driver", "route", "1:0..1", "a scheduled driver runs at most one AM route"),
    ("route", "route_candidate", "1:N", "evaluated stop orderings"),
    ("route", "stop", "N:M", "via route_stop bridge"),
    ("route_stop", "assignment", "1:N", "students boarding at a route stop"),
    ("bus", "bus_capacity_event", "1:N", "effective-dated capacity changes"),
    ("route", "route_disruption", "1:N", "daily disruptions"),
    ("school_day", "attendance_event", "1:N", "daily outcomes"),
    ("student", "attendance_event", "1:N", "one per active school day"),
    ("route_disruption", "attendance_event", "1:N (optional)", "disruption affecting pickups"),
    ("student", "notification", "1:N", "notices about the student"),
    ("guardian_contact", "notification", "1:N (optional)", "recipient"),
]


def sql_type(f: Field) -> str:
    return {"int": "INTEGER", "float": "REAL", "bool": "INTEGER"}.get(f.type, "TEXT")


def ddl() -> str:
    """CREATE TABLE statements in dependency-safe order (FKs deferred)."""
    out = ["-- Generated from transport/schema.py. Tested with SQLite (foreign keys are DEFERRABLE, so table order is free).",
           "PRAGMA foreign_keys = ON;", ""]
    for t in TABLES:
        cols = []
        for f in t.fields:
            parts = [f"  {f.name} {sql_type(f)}"]
            if f.name == t.pk:
                parts.append("PRIMARY KEY")
            elif f.required:
                parts.append("NOT NULL")
            if f.unique and f.name != t.pk:
                parts.append("UNIQUE")
            if f.allowed is not None:
                vals = ", ".join(repr(v) if isinstance(v, str) else str(v) for v in f.allowed)
                parts.append(f"CHECK ({f.name} IN ({vals}))")
            if f.type == "bool":
                parts.append(f"CHECK ({f.name} IN (0, 1))")
            cols.append(" ".join(parts))
        for f in t.fields:
            if f.fk:
                rt, rc = f.fk.split(".")
                cols.append(f"  FOREIGN KEY ({f.name}) REFERENCES {rt}({rc}) DEFERRABLE INITIALLY DEFERRED")
        out.append(f"CREATE TABLE {t.name} (\n" + ",\n".join(cols) + "\n);\n")
    return "\n".join(out)


def data_dictionary_md() -> str:
    lines = ["# Data dictionary", "",
             "Generated from `transport/schema.py` (the same definitions drive validation and SQL DDL).",
             "Types: `date` = YYYY-MM-DD, `time` = HH:MM (local school time), `datetime` = YYYY-MM-DDTHH:MM, "
             "`bool` = true/false in CSV/JSON, 0/1 in SQL. Coordinates are on a synthetic plane in km with the "
             "school at (0, 0). `Req` = N marks an optional field (nullable FK = optional relationship). "
             "Lifecycle states/transitions and effective-dating rules are described in `design.md`.", ""]
    lines.append("## Relationships\n")
    lines.append("| Parent | Child | Cardinality | Meaning |")
    lines.append("|---|---|---|---|")
    for p, c, card, m in RELATIONSHIPS:
        lines.append(f"| {p} | {c} | {card} | {m} |")
    lines.append("")
    for t in TABLES:
        lines.append(f"## {t.name} ({t.entity}, {t.kind})\n")
        lines.append(f"{t.desc}  \nPrimary key: `{t.pk}`\n")
        lines.append("| Field | Type | Req | Unique | Allowed values / pattern | Unit | FK | Description | Validation rule |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for f in t.fields:
            allowed = ", ".join(str(a) for a in f.allowed) if f.allowed else (
                f"`{f.pattern}`" if f.pattern else "")
            allowed = allowed.replace("|", "\\|")
            rule = (f.rule or "").replace("|", "\\|")
            lines.append(f"| {f.name} | {f.type} | {'Y' if f.required else 'N'} | "
                         f"{'Y' if f.unique else ''} | {allowed} | {f.unit or ''} | {f.fk or ''} | "
                         f"{f.desc} | {rule} |")
        lines.append("")
    return "\n".join(lines)
