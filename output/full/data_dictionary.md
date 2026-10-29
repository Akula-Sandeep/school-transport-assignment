# Data dictionary

Generated from `transport/schema.py` (the same definitions drive validation and SQL DDL).
Types: `date` = YYYY-MM-DD, `time` = HH:MM (local school time), `datetime` = YYYY-MM-DDTHH:MM, `bool` = true/false in CSV/JSON, 0/1 in SQL. Coordinates are on a synthetic plane in km with the school at (0, 0). `Req` = N marks an optional field (nullable FK = optional relationship). Lifecycle states/transitions and effective-dating rules are described in `design.md`.

## Relationships

| Parent | Child | Cardinality | Meaning |
|---|---|---|---|
| address_zone | stop | 1:N | zone contains stops |
| address_zone | student | 1:N | zone contains student homes |
| address_zone | bus | 1:N | depot zone |
| student | guardian_contact | 1:N | 1-3 contacts per student, effective-dated |
| student | assignment | 1:1 | one assignment per student per school year |
| assignment | assignment_event | 1:N | append-only state history |
| bus | route | 1:0..1 | a scheduled bus runs at most one AM route |
| driver | route | 1:0..1 | a scheduled driver runs at most one AM route |
| route | route_candidate | 1:N | evaluated stop orderings |
| route | stop | N:M | via route_stop bridge |
| route_stop | assignment | 1:N | students boarding at a route stop |
| bus | bus_capacity_event | 1:N | effective-dated capacity changes |
| route | route_disruption | 1:N | daily disruptions |
| school_day | attendance_event | 1:N | daily outcomes |
| student | attendance_event | 1:N | one per active school day |
| route_disruption | attendance_event | 1:N (optional) | disruption affecting pickups |
| student | notification | 1:N | notices about the student |
| guardian_contact | notification | 1:N (optional) | recipient |

## school_day (SchoolDay, reference)

Operating calendar: one row per school day with service.  
Primary key: `service_date`

| Field | Type | Req | Unique | Allowed values / pattern | Unit | FK | Description | Validation rule |
|---|---|---|---|---|---|---|---|---|
| service_date | date | Y | Y | `^\d{4}-\d{2}-\d{2}$` |  |  | Calendar date with bus service |  |
| day_index | int | Y | Y |  |  |  | 1-based sequence number of the school day | contiguous 1..N in date order |
| weekday | str | Y |  | Mon, Tue, Wed, Thu, Fri |  |  | Day of week |  |
| term | str | Y |  | T1, T2, T3 |  |  | Academic term |  |

## address_zone (AddressZone, master)

Synthetic service-area zones: rings (urban/suburban/rural) x angular sectors around the school.  
Primary key: `zone_id`

| Field | Type | Req | Unique | Allowed values / pattern | Unit | FK | Description | Validation rule |
|---|---|---|---|---|---|---|---|---|
| zone_id | str | Y | Y | `^ZONE-\d{4}$` |  |  | Zone identifier |  |
| zone_name | str | Y | Y |  |  |  | Human-readable zone name |  |
| zone_type | str | Y |  | urban, suburban, rural |  |  | Ring the zone belongs to |  |
| ring_index | int | Y |  | 0, 1, 2 |  |  | 0=urban,1=suburban,2=rural |  |
| sector_index | int | Y |  |  |  |  | Angular sector within the ring (0-based) |  |
| inner_radius_km | float | Y |  |  | km |  | Inner radius from school |  |
| outer_radius_km | float | Y |  |  | km |  | Outer radius from school | outer_radius_km > inner_radius_km |
| start_angle_deg | float | Y |  |  | deg |  | Sector start angle |  |
| end_angle_deg | float | Y |  |  | deg |  | Sector end angle |  |
| centroid_x_km | float | Y |  |  | km |  | Sector centroid x |  |
| centroid_y_km | float | Y |  |  | km |  | Sector centroid y |  |
| avg_bus_speed_kmph | float | Y |  |  | km/h |  | Average bus speed in the zone |  |
| max_walk_m | int | Y |  |  | m |  | Maximum walk to a stop allowed in this zone |  |

## stop (Stop, master)

Candidate and approved bus stops. Only approved stops may appear on a route.  
Primary key: `stop_id`

| Field | Type | Req | Unique | Allowed values / pattern | Unit | FK | Description | Validation rule |
|---|---|---|---|---|---|---|---|---|
| stop_id | str | Y | Y | `^STOP-\d{6}$` |  |  | Stop identifier |  |
| zone_id | str | Y |  |  |  | address_zone.zone_id | Zone containing the stop |  |
| stop_name | str | Y |  |  |  |  | Public stop name (no residential address) |  |
| x_km | float | Y |  |  | km |  | Stop x coordinate |  |
| y_km | float | Y |  |  | km |  | Stop y coordinate |  |
| approval_status | str | Y |  | approved, pending, rejected |  |  | Safety/approval state | route_stop may only reference approved stops |
| approval_date | date | N |  | `^\d{4}-\d{2}-\d{2}$` |  |  | Decision date (null while pending) | required unless pending |
| is_accessible | bool | Y |  |  |  |  | Kerb/ramp suitable for lift boarding |  |
| safety_rating | str | Y |  | A, B, C |  |  | A best .. C unsafe |  |
| stop_source | str | Y |  | planned, guardian_request |  |  | How the stop was proposed |  |
| effective_from | date | Y |  | `^\d{4}-\d{2}-\d{2}$` |  |  | First date the stop record is valid |  |
| effective_to | date | N |  | `^\d{4}-\d{2}-\d{2}$` |  |  | Last valid date (null = open) | effective_to >= effective_from |

## bus (Bus, master)

Fleet vehicles. Effective capacity on a date = latest bus_capacity_event covering that date, else base_seated_capacity.  
Primary key: `bus_id`

| Field | Type | Req | Unique | Allowed values / pattern | Unit | FK | Description | Validation rule |
|---|---|---|---|---|---|---|---|---|
| bus_id | str | Y | Y | `^BUS-\d{6}$` |  |  | Bus identifier |  |
| registration_code | str | Y | Y |  |  |  | Synthetic plate |  |
| bus_type | str | Y |  | large, standard, midi, accessible |  |  | Vehicle class |  |
| base_seated_capacity | int | Y |  |  | seats |  | Certified seats | 20 <= value <= 80 |
| wheelchair_positions | int | Y |  |  | positions |  | Secured wheelchair positions | >0 iff is_accessible |
| is_accessible | bool | Y |  |  |  |  | Has lift and wheelchair positions |  |
| fleet_role | str | Y |  | route, spare |  |  | Scheduled on a route or kept spare |  |
| status | str | Y |  | in_service, maintenance |  |  | Operational status |  |
| depot_zone_id | str | Y |  |  |  | address_zone.zone_id | Overnight depot zone |  |
| commissioned_on | date | Y |  | `^\d{4}-\d{2}-\d{2}$` |  |  | Entered fleet |  |

## driver (Driver, master)

Licensed drivers (synthetic).  
Primary key: `driver_id`

| Field | Type | Req | Unique | Allowed values / pattern | Unit | FK | Description | Validation rule |
|---|---|---|---|---|---|---|---|---|
| driver_id | str | Y | Y | `^DRV-\d{6}$` |  |  | Driver identifier |  |
| display_name | str | Y |  |  |  |  | Synthetic display name |  |
| license_class | str | Y |  | PSV-HEAVY |  |  | Licence class |  |
| license_expiry | date | Y |  | `^\d{4}-\d{2}-\d{2}$` |  |  | Licence expiry | must be after last school day |
| accessible_trained | bool | Y |  |  |  |  | Trained to operate lifts / secure wheelchairs | required for accessible routes |
| employment_status | str | Y |  | active, on_leave |  |  | Employment state |  |
| hired_on | date | Y |  | `^\d{4}-\d{2}-\d{2}$` |  |  | Hire date |  |

## student (Student, master)

Learners. Home location coarsened to a 50 m grid; the address line is synthetic and sensitive (never shown on stops or notifications).  
Primary key: `student_id`

| Field | Type | Req | Unique | Allowed values / pattern | Unit | FK | Description | Validation rule |
|---|---|---|---|---|---|---|---|---|
| student_id | str | Y | Y | `^STU-\d{6}$` |  |  | Student identifier |  |
| display_name | str | Y |  |  |  |  | Synthetic first name + initial |  |
| grade | str | Y |  | KG, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12 |  |  | Grade level |  |
| home_zone_id | str | Y |  |  |  | address_zone.zone_id | Zone of home location |  |
| home_x_km | float | Y |  |  | km |  | Home x (50 m grid) |  |
| home_y_km | float | Y |  |  | km |  | Home y (50 m grid) |  |
| address_line | str | Y |  |  |  |  | Synthetic street address (SENSITIVE) |  |
| address_status | str | Y |  | verified, pending |  |  | Guardian address verification |  |
| distance_to_school_km | float | Y |  |  | km |  | Derived straight-line distance |  |
| transport_eligible | bool | Y |  |  |  |  | Derived: distance_to_school_km >= 1.6 |  |
| transport_opt_in | bool | Y |  |  |  |  | Guardian requested transport |  |
| mobility_aid | str | Y |  | none, wheelchair, walker, other |  |  | Mobility aid used |  |
| requires_accessible_vehicle | bool | Y |  |  |  |  | Must ride an accessible route | true when mobility_aid != none |
| max_walk_m | int | Y |  |  | m |  | Derived: min(zone, grade, mobility caps) |  |
| pickup_window_start | time | Y |  | `^\d{2}:\d{2}$` |  |  | Earliest acceptable pickup (HH:MM) |  |
| pickup_window_end | time | Y |  | `^\d{2}:\d{2}$` |  |  | Latest acceptable pickup (HH:MM) | end - start >= 15 min |
| enrollment_status | str | Y |  | active, withdrawn |  |  | Lifecycle state |  |
| enrolled_on | date | Y |  | `^\d{4}-\d{2}-\d{2}$` |  |  | Enrollment date (mid-year joiners after first school day) |  |
| withdrawn_on | date | N |  | `^\d{4}-\d{2}-\d{2}$` |  |  | First day no longer enrolled | withdrawn_on > enrolled_on; required iff withdrawn |

## guardian_contact (GuardianContact, master)

Guardian contacts, effective-dated (a replaced contact keeps its row; valid_to + superseded_by).  
Primary key: `contact_id`

| Field | Type | Req | Unique | Allowed values / pattern | Unit | FK | Description | Validation rule |
|---|---|---|---|---|---|---|---|---|
| contact_id | str | Y | Y | `^GC-\d{6}$` |  |  | Contact identifier |  |
| student_id | str | Y |  |  |  | student.student_id | Student this contact is for |  |
| relationship | str | Y |  | mother, father, guardian, grandparent, other |  |  | Relationship to student |  |
| contact_label | str | Y |  |  |  |  | Minimal label, e.g. 'Guardian 1 (mother)' |  |
| phone | str | Y |  |  |  |  | Synthetic unroutable phone | valid iff matches ^\+999-555-\d{7}$ |
| email | str | Y |  |  |  |  | Synthetic email on example.org | valid iff @example.org |
| preferred_channel | str | Y |  | sms, email, app_push |  |  | Preferred channel |  |
| priority | int | Y |  |  |  |  | 1 = primary contact | >= 1 |
| consent_to_notify | bool | Y |  |  |  |  | Guardian consent for transport messages |  |
| contact_status | str | Y |  | active, bounced, inactive |  |  | Deliverability state |  |
| valid_from | date | Y |  | `^\d{4}-\d{2}-\d{2}$` |  |  | Effective from |  |
| valid_to | date | N |  | `^\d{4}-\d{2}-\d{2}$` |  |  | Effective to (null = open) | valid_to >= valid_from |
| superseded_by | str | N |  |  |  | guardian_contact.contact_id | Replacement contact when this one was retired |  |

## route (Route, transaction)

AM routes for the school year. Schedule fields are derived from route_stop legs.  
Primary key: `route_id`

| Field | Type | Req | Unique | Allowed values / pattern | Unit | FK | Description | Validation rule |
|---|---|---|---|---|---|---|---|---|
| route_id | str | Y | Y | `^ROUTE-\d{4}-\d{6}$` |  |  | Route identifier |  |
| route_name | str | Y | Y |  |  |  | Route name |  |
| school_year | int | Y |  |  |  |  | School year label |  |
| session | str | Y |  | AM |  |  | Service session |  |
| service_type | str | Y |  | regular, accessible |  |  | regular or accessible network |  |
| bus_id | str | Y | Y |  |  | bus.bus_id | Scheduled bus |  |
| driver_id | str | Y | Y |  |  | driver.driver_id | Scheduled driver |  |
| selected_candidate_id | str | Y |  |  |  | route_candidate.candidate_id | Engine-selected candidate |  |
| stop_count | int | Y |  |  |  |  | Derived: number of route_stop rows |  |
| final_leg_distance_km | float | Y |  |  | km |  | Last stop -> school road distance |  |
| final_leg_min | float | Y |  |  | min |  | Last stop -> school travel time |  |
| total_distance_km | float | Y |  |  | km |  | Derived: sum of legs + final leg |  |
| total_travel_min | float | Y |  |  | min |  | Derived: first pickup -> school arrival incl. dwell | <= 60 |
| departure_time | time | Y |  | `^\d{2}:\d{2}$` |  |  | Derived: first pickup time |  |
| school_arrival_time | time | Y |  | `^\d{2}:\d{2}$` |  |  | Planned arrival (07:35..07:50) |  |
| capacity_at_plan | int | Y |  |  | seats |  | Bus capacity on planning date |  |
| planned_load | int | Y |  |  | students |  | Derived: students assigned at plan |  |
| utilization_pct | float | Y |  |  | % |  | Derived: planned_load / capacity_at_plan |  |
| status | str | Y |  | active, suspended |  |  | Route lifecycle state |  |
| effective_from | date | Y |  | `^\d{4}-\d{2}-\d{2}$` |  |  | First service date |  |
| effective_to | date | Y |  | `^\d{4}-\d{2}-\d{2}$` |  |  | Last service date |  |

## route_candidate (RouteCandidate, transaction)

Every stop ordering the planner evaluated, with travel time and feasibility (decision trace).  
Primary key: `candidate_id`

| Field | Type | Req | Unique | Allowed values / pattern | Unit | FK | Description | Validation rule |
|---|---|---|---|---|---|---|---|---|
| candidate_id | str | Y | Y | `^RC-\d{4}-\d{6}$` |  |  | Candidate identifier |  |
| route_id | str | Y |  |  |  | route.route_id | Route the candidate was built for |  |
| method | str | Y |  | radial_inbound, nearest_neighbor, two_opt |  |  | Ordering heuristic |  |
| stop_sequence | str | Y |  |  |  |  | Pipe-separated stop_ids in visiting order |  |
| total_distance_km | float | Y |  |  | km |  | Candidate distance |  |
| total_travel_min | float | Y |  |  | min |  | Candidate duration |  |
| max_leg_speed_kmph | float | Y |  |  | km/h |  | Fastest implied leg speed |  |
| feasible | bool | Y |  |  |  |  | Duration and speed limits satisfied |  |
| rejection_reason | str | N |  |  |  |  | Why infeasible / not selected |  |
| rank | int | Y |  |  |  |  | 1 = best by travel time |  |
| selected | bool | Y |  |  |  |  | Chosen for the route | exactly one per route |

## route_stop (RouteStop, bridge)

Bridge Route N:M Stop with sequence and leg timings (a stop can be served by several routes).  
Primary key: `route_stop_id`

| Field | Type | Req | Unique | Allowed values / pattern | Unit | FK | Description | Validation rule |
|---|---|---|---|---|---|---|---|---|
| route_stop_id | str | Y | Y | `^RS-\d{4}-\d{6}$` |  |  | Route-stop identifier |  |
| route_id | str | Y |  |  |  | route.route_id | Route |  |
| stop_id | str | Y |  |  |  | stop.stop_id | Stop |  |
| stop_sequence | int | Y |  |  |  |  | 1..n visiting order | contiguous per route |
| leg_distance_km | float | Y |  |  | km |  | Road distance from previous stop (0 for first) |  |
| leg_travel_min | float | Y |  |  | min |  | Travel time from previous stop | implied speed <= 70 km/h |
| dwell_min | float | Y |  |  | min |  | Boarding dwell at this stop |  |
| cumulative_min | float | Y |  |  | min |  | Derived: minutes from departure to arrival here |  |
| planned_arrival_time | time | Y |  | `^\d{2}:\d{2}$` |  |  | Derived: departure_time + cumulative_min |  |
| boarding_planned | int | Y |  |  | students |  | Derived: students assigned here at plan |  |
| effective_from | date | Y |  | `^\d{4}-\d{2}-\d{2}$` |  |  | Effective from |  |
| effective_to | date | Y |  | `^\d{4}-\d{2}-\d{2}$` |  |  | Effective to |  |

## assignment (Assignment, transaction)

One record per student per school year: the initial decision (immutable) plus derived current status. All later changes live in assignment_event.  
Primary key: `assignment_id`

| Field | Type | Req | Unique | Allowed values / pattern | Unit | FK | Description | Validation rule |
|---|---|---|---|---|---|---|---|---|
| assignment_id | str | Y | Y | `^ASN-STU-\d{6}-\d{4}$` |  |  | ASN-<student_id>-<year> |  |
| student_id | str | Y | Y |  |  | student.student_id | Student |  |
| school_year | int | Y |  |  |  |  | School year |  |
| decision | str | Y |  | assigned, waitlisted, ineligible, opted_out |  |  | Initial decision |  |
| decision_reason | str | Y |  | ASSIGNED_NEAREST_STOP, ASSIGNED_ALT_STOP_FOR_WINDOW, ASSIGNED_WINDOW_EXCEPTION, ASSIGNED_FROM_WAITLIST, MIDYEAR_ASSIGNED, WAITLIST_NO_STOP_IN_RANGE, WAITLIST_NO_ACCESSIBLE_STOP, WAITLIST_NO_CAPACITY, WAITLIST_NO_ROUTE_SERVES_STOP, WAITLIST_ADDRESS_PENDING, WAITLIST_CAPACITY_REDUCED, INELIGIBLE_WALK_ZONE, OPTED_OUT_GUARDIAN, CAPACITY_REDUCED_REASSIGN, MANUAL_OVERRIDE, STUDENT_WITHDRAWN |  |  | Rule that produced the decision |  |
| route_id | str | N |  |  |  | route.route_id | Assigned route |  |
| stop_id | str | N |  |  |  | stop.stop_id | Assigned stop |  |
| route_stop_id | str | N |  |  |  | route_stop.route_stop_id | Route stop |  |
| walk_distance_m | int | N |  |  | m |  | Home -> stop walk | <= student.max_walk_m |
| scheduled_pickup_time | time | N |  | `^\d{2}:\d{2}$` |  |  | Derived from route_stop |  |
| ride_time_min | int | N |  |  | min |  | Pickup -> school arrival | <= 60 |
| window_ok | bool | N |  |  |  |  | Pickup inside guardian window |  |
| capacity_ok | bool | N |  |  |  |  | Route had a seat at decision time |  |
| accessibility_ok | bool | N |  |  |  |  | Route compatible with mobility needs |  |
| decided_on | date | Y |  | `^\d{4}-\d{2}-\d{2}$` |  |  | Decision date |  |
| effective_from | date | Y |  | `^\d{4}-\d{2}-\d{2}$` |  |  | First day the decision applies |  |
| current_status | str | Y |  | active, waitlisted, ineligible, opted_out, ended |  |  | Derived from the last assignment_event |  |
| status_as_of | date | Y |  | `^\d{4}-\d{2}-\d{2}$` |  |  | Date current_status refers to (last school day) |  |

## assignment_event (AssignmentEvent, event)

Append-only history of assignment state changes (never overwritten).  
Primary key: `event_id`

| Field | Type | Req | Unique | Allowed values / pattern | Unit | FK | Description | Validation rule |
|---|---|---|---|---|---|---|---|---|
| event_id | str | Y | Y | `^AEV-\d{4}-\d{6}$` |  |  | Event identifier |  |
| assignment_id | str | Y |  |  |  | assignment.assignment_id | Assignment |  |
| student_id | str | Y |  |  |  | student.student_id | Student (denormalised for joins) |  |
| event_seq | int | Y |  |  |  |  | 1..n per assignment | contiguous |
| event_type | str | Y |  | ASSIGNED, WAITLISTED, INELIGIBLE, OPTED_OUT, REASSIGNED, ENDED |  |  | State transition | see lifecycle transitions in docs/design.md |
| event_date | date | Y |  | `^\d{4}-\d{2}-\d{2}$` |  |  | Date the new state takes effect | non-decreasing per assignment |
| route_id | str | N |  |  |  | route.route_id | Route after event |  |
| stop_id | str | N |  |  |  | stop.stop_id | Stop after event |  |
| route_stop_id | str | N |  |  |  | route_stop.route_stop_id | Route stop after event |  |
| reason_code | str | Y |  | ASSIGNED_NEAREST_STOP, ASSIGNED_ALT_STOP_FOR_WINDOW, ASSIGNED_WINDOW_EXCEPTION, ASSIGNED_FROM_WAITLIST, MIDYEAR_ASSIGNED, WAITLIST_NO_STOP_IN_RANGE, WAITLIST_NO_ACCESSIBLE_STOP, WAITLIST_NO_CAPACITY, WAITLIST_NO_ROUTE_SERVES_STOP, WAITLIST_ADDRESS_PENDING, WAITLIST_CAPACITY_REDUCED, INELIGIBLE_WALK_ZONE, OPTED_OUT_GUARDIAN, CAPACITY_REDUCED_REASSIGN, MANUAL_OVERRIDE, STUDENT_WITHDRAWN |  |  | Rule / reason |  |
| triggered_by | str | N |  |  |  |  | Upstream record id (e.g. BCE-...) |  |
| actor_role | str | Y |  | system, academic_administrator, support_staff, platform_administrator |  |  | Who/what made the change |  |

## bus_capacity_event (BusCapacityEvent, event)

Effective-dated capacity changes (seat banks out of service, vehicle swaps).  
Primary key: `capacity_event_id`

| Field | Type | Req | Unique | Allowed values / pattern | Unit | FK | Description | Validation rule |
|---|---|---|---|---|---|---|---|---|
| capacity_event_id | str | Y | Y | `^BCE-\d{4}-\d{6}$` |  |  | Event identifier |  |
| bus_id | str | Y |  |  |  | bus.bus_id | Bus |  |
| event_type | str | Y |  | SEATS_OUT_OF_SERVICE, REPLACED_SMALLER, REPLACED_LARGER |  |  | Change type |  |
| previous_capacity | int | Y |  |  | seats |  | Capacity before |  |
| new_capacity | int | Y |  |  | seats |  | Capacity while effective |  |
| effective_from | date | Y |  | `^\d{4}-\d{2}-\d{2}$` |  | school_day.service_date | First affected day |  |
| effective_to | date | N |  | `^\d{4}-\d{2}-\d{2}$` |  |  | Last affected day (null = permanent) | effective_to >= effective_from |
| recorded_by | str | Y |  | system, academic_administrator, support_staff, platform_administrator |  |  | Who recorded the change |  |

## route_disruption (RouteDisruption, event)

Daily operational disruptions and how they were resolved.  
Primary key: `disruption_id`

| Field | Type | Req | Unique | Allowed values / pattern | Unit | FK | Description | Validation rule |
|---|---|---|---|---|---|---|---|---|
| disruption_id | str | Y | Y | `^DIS-\d{4}-\d{6}$` |  |  | Disruption identifier |  |
| route_id | str | Y |  |  |  | route.route_id | Affected route |  |
| service_date | date | Y |  | `^\d{4}-\d{2}-\d{2}$` |  | school_day.service_date | Day |  |
| disruption_type | str | Y |  | traffic_delay, breakdown, weather, driver_absence |  |  | Cause |  |
| from_stop_sequence | int | Y |  |  |  |  | Delay applies from this stop onwards |  |
| delay_min | int | Y |  |  | min |  | Added delay (0 if cancelled) |  |
| service_cancelled | bool | Y |  |  |  |  | No service on this day |  |
| replacement_bus_id | str | N |  |  |  | bus.bus_id | Spare bus used |  |
| replacement_driver_id | str | N |  |  |  | driver.driver_id | Spare driver used |  |
| resolution | str | Y |  | delayed_service, replacement_bus, spare_driver, cancelled |  |  | How it was handled |  |
| reported_at | datetime | Y |  | `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$` |  |  | When dispatch logged it |  |

## attendance_event (AttendanceEvent, event)

One record per assigned student per school day (boarding outcome).  
Primary key: `attendance_id`

| Field | Type | Req | Unique | Allowed values / pattern | Unit | FK | Description | Validation rule |
|---|---|---|---|---|---|---|---|---|
| attendance_id | str | Y | Y | `^ATT-\d{4}-\d{7}$` |  |  | Event identifier |  |
| service_date | date | Y |  | `^\d{4}-\d{2}-\d{2}$` |  | school_day.service_date | Day |  |
| student_id | str | Y |  |  |  | student.student_id | Student |  |
| assignment_id | str | Y |  |  |  | assignment.assignment_id | Assignment |  |
| route_id | str | Y |  |  |  | route.route_id | Route active for the student that day |  |
| stop_id | str | Y |  |  |  | stop.stop_id | Stop active that day |  |
| scheduled_pickup_time | time | Y |  | `^\d{2}:\d{2}$` |  |  | From route_stop |  |
| bus_arrival_time | time | N |  | `^\d{2}:\d{2}$` |  |  | Actual bus arrival (null if not run/skipped) |  |
| delay_min | int | N |  |  | min |  | Arrival - scheduled |  |
| attendance_status | str | Y |  | boarded, boarded_late, absent_reported, no_show, missed_pickup |  |  | Outcome |  |
| disruption_id | str | N |  |  |  | route_disruption.disruption_id | Disruption affecting this pickup |  |
| recorded_by | str | Y |  | driver_app, guardian_portal, system |  |  | Source of the record |  |

## notification (Notification, event)

Guardian notifications; payloads carry ids and times only (no addresses or names).  
Primary key: `notification_id`

| Field | Type | Req | Unique | Allowed values / pattern | Unit | FK | Description | Validation rule |
|---|---|---|---|---|---|---|---|---|
| notification_id | str | Y | Y | `^NOT-\d{4}-\d{6}$` |  |  | NOT-<year>-<n> |  |
| student_id | str | Y |  |  |  | student.student_id | Student concerned |  |
| contact_id | str | N |  |  |  | guardian_contact.contact_id | Recipient (null when suppressed) |  |
| notification_type | str | Y |  | ASSIGNMENT_CONFIRMED, WINDOW_EXCEPTION, WAITLIST_NOTICE, REASSIGNMENT_NOTICE, SERVICE_ENDED, ROUTE_DELAY, SERVICE_CANCELLED, MISSED_PICKUP, NO_SHOW |  |  | Template family |  |
| channel | str | N |  | sms, email, app_push |  |  | Delivery channel |  |
| trigger_entity | str | Y |  | assignment_event, route_disruption, attendance_event |  |  | Table of the triggering record |  |
| trigger_id | str | Y |  |  |  |  | Triggering record id |  |
| service_date | date | Y |  | `^\d{4}-\d{2}-\d{2}$` |  |  | Date the notice relates to |  |
| sent_at | datetime | Y |  | `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$` |  |  | Send timestamp (local school time) |  |
| delivery_status | str | Y |  | delivered, bounced, failed, suppressed |  |  | Derived from contact state |  |
| failure_reason | str | N |  |  |  |  | Why not delivered / suppressed |  |
| message_preview | str | Y |  |  |  |  | Rendered message (must not contain addresses) |  |
