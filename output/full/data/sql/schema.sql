-- Generated from transport/schema.py. Tested with SQLite (foreign keys are DEFERRABLE, so table order is free).
PRAGMA foreign_keys = ON;

CREATE TABLE school_day (
  service_date TEXT PRIMARY KEY,
  day_index INTEGER NOT NULL UNIQUE,
  weekday TEXT NOT NULL CHECK (weekday IN ('Mon', 'Tue', 'Wed', 'Thu', 'Fri')),
  term TEXT NOT NULL CHECK (term IN ('T1', 'T2', 'T3'))
);

CREATE TABLE address_zone (
  zone_id TEXT PRIMARY KEY,
  zone_name TEXT NOT NULL UNIQUE,
  zone_type TEXT NOT NULL CHECK (zone_type IN ('urban', 'suburban', 'rural')),
  ring_index INTEGER NOT NULL CHECK (ring_index IN (0, 1, 2)),
  sector_index INTEGER NOT NULL,
  inner_radius_km REAL NOT NULL,
  outer_radius_km REAL NOT NULL,
  start_angle_deg REAL NOT NULL,
  end_angle_deg REAL NOT NULL,
  centroid_x_km REAL NOT NULL,
  centroid_y_km REAL NOT NULL,
  avg_bus_speed_kmph REAL NOT NULL,
  max_walk_m INTEGER NOT NULL
);

CREATE TABLE stop (
  stop_id TEXT PRIMARY KEY,
  zone_id TEXT NOT NULL,
  stop_name TEXT NOT NULL,
  x_km REAL NOT NULL,
  y_km REAL NOT NULL,
  approval_status TEXT NOT NULL CHECK (approval_status IN ('approved', 'pending', 'rejected')),
  approval_date TEXT,
  is_accessible INTEGER NOT NULL CHECK (is_accessible IN (0, 1)),
  safety_rating TEXT NOT NULL CHECK (safety_rating IN ('A', 'B', 'C')),
  stop_source TEXT NOT NULL CHECK (stop_source IN ('planned', 'guardian_request')),
  effective_from TEXT NOT NULL,
  effective_to TEXT,
  FOREIGN KEY (zone_id) REFERENCES address_zone(zone_id) DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE bus (
  bus_id TEXT PRIMARY KEY,
  registration_code TEXT NOT NULL UNIQUE,
  bus_type TEXT NOT NULL CHECK (bus_type IN ('large', 'standard', 'midi', 'accessible')),
  base_seated_capacity INTEGER NOT NULL,
  wheelchair_positions INTEGER NOT NULL,
  is_accessible INTEGER NOT NULL CHECK (is_accessible IN (0, 1)),
  fleet_role TEXT NOT NULL CHECK (fleet_role IN ('route', 'spare')),
  status TEXT NOT NULL CHECK (status IN ('in_service', 'maintenance')),
  depot_zone_id TEXT NOT NULL,
  commissioned_on TEXT NOT NULL,
  FOREIGN KEY (depot_zone_id) REFERENCES address_zone(zone_id) DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE driver (
  driver_id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  license_class TEXT NOT NULL CHECK (license_class IN ('PSV-HEAVY')),
  license_expiry TEXT NOT NULL,
  accessible_trained INTEGER NOT NULL CHECK (accessible_trained IN (0, 1)),
  employment_status TEXT NOT NULL CHECK (employment_status IN ('active', 'on_leave')),
  hired_on TEXT NOT NULL
);

CREATE TABLE student (
  student_id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  grade TEXT NOT NULL CHECK (grade IN ('KG', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12')),
  home_zone_id TEXT NOT NULL,
  home_x_km REAL NOT NULL,
  home_y_km REAL NOT NULL,
  address_line TEXT NOT NULL,
  address_status TEXT NOT NULL CHECK (address_status IN ('verified', 'pending')),
  distance_to_school_km REAL NOT NULL,
  transport_eligible INTEGER NOT NULL CHECK (transport_eligible IN (0, 1)),
  transport_opt_in INTEGER NOT NULL CHECK (transport_opt_in IN (0, 1)),
  mobility_aid TEXT NOT NULL CHECK (mobility_aid IN ('none', 'wheelchair', 'walker', 'other')),
  requires_accessible_vehicle INTEGER NOT NULL CHECK (requires_accessible_vehicle IN (0, 1)),
  max_walk_m INTEGER NOT NULL,
  pickup_window_start TEXT NOT NULL,
  pickup_window_end TEXT NOT NULL,
  enrollment_status TEXT NOT NULL CHECK (enrollment_status IN ('active', 'withdrawn')),
  enrolled_on TEXT NOT NULL,
  withdrawn_on TEXT,
  FOREIGN KEY (home_zone_id) REFERENCES address_zone(zone_id) DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE guardian_contact (
  contact_id TEXT PRIMARY KEY,
  student_id TEXT NOT NULL,
  relationship TEXT NOT NULL CHECK (relationship IN ('mother', 'father', 'guardian', 'grandparent', 'other')),
  contact_label TEXT NOT NULL,
  phone TEXT NOT NULL,
  email TEXT NOT NULL,
  preferred_channel TEXT NOT NULL CHECK (preferred_channel IN ('sms', 'email', 'app_push')),
  priority INTEGER NOT NULL,
  consent_to_notify INTEGER NOT NULL CHECK (consent_to_notify IN (0, 1)),
  contact_status TEXT NOT NULL CHECK (contact_status IN ('active', 'bounced', 'inactive')),
  valid_from TEXT NOT NULL,
  valid_to TEXT,
  superseded_by TEXT,
  FOREIGN KEY (student_id) REFERENCES student(student_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (superseded_by) REFERENCES guardian_contact(contact_id) DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE route (
  route_id TEXT PRIMARY KEY,
  route_name TEXT NOT NULL UNIQUE,
  school_year INTEGER NOT NULL,
  session TEXT NOT NULL CHECK (session IN ('AM')),
  service_type TEXT NOT NULL CHECK (service_type IN ('regular', 'accessible')),
  bus_id TEXT NOT NULL UNIQUE,
  driver_id TEXT NOT NULL UNIQUE,
  selected_candidate_id TEXT NOT NULL,
  stop_count INTEGER NOT NULL,
  final_leg_distance_km REAL NOT NULL,
  final_leg_min REAL NOT NULL,
  total_distance_km REAL NOT NULL,
  total_travel_min REAL NOT NULL,
  departure_time TEXT NOT NULL,
  school_arrival_time TEXT NOT NULL,
  capacity_at_plan INTEGER NOT NULL,
  planned_load INTEGER NOT NULL,
  utilization_pct REAL NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('active', 'suspended')),
  effective_from TEXT NOT NULL,
  effective_to TEXT NOT NULL,
  FOREIGN KEY (bus_id) REFERENCES bus(bus_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (driver_id) REFERENCES driver(driver_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (selected_candidate_id) REFERENCES route_candidate(candidate_id) DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE route_candidate (
  candidate_id TEXT PRIMARY KEY,
  route_id TEXT NOT NULL,
  method TEXT NOT NULL CHECK (method IN ('radial_inbound', 'nearest_neighbor', 'two_opt')),
  stop_sequence TEXT NOT NULL,
  total_distance_km REAL NOT NULL,
  total_travel_min REAL NOT NULL,
  max_leg_speed_kmph REAL NOT NULL,
  feasible INTEGER NOT NULL CHECK (feasible IN (0, 1)),
  rejection_reason TEXT,
  rank INTEGER NOT NULL,
  selected INTEGER NOT NULL CHECK (selected IN (0, 1)),
  FOREIGN KEY (route_id) REFERENCES route(route_id) DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE route_stop (
  route_stop_id TEXT PRIMARY KEY,
  route_id TEXT NOT NULL,
  stop_id TEXT NOT NULL,
  stop_sequence INTEGER NOT NULL,
  leg_distance_km REAL NOT NULL,
  leg_travel_min REAL NOT NULL,
  dwell_min REAL NOT NULL,
  cumulative_min REAL NOT NULL,
  planned_arrival_time TEXT NOT NULL,
  boarding_planned INTEGER NOT NULL,
  effective_from TEXT NOT NULL,
  effective_to TEXT NOT NULL,
  FOREIGN KEY (route_id) REFERENCES route(route_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (stop_id) REFERENCES stop(stop_id) DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE assignment (
  assignment_id TEXT PRIMARY KEY,
  student_id TEXT NOT NULL UNIQUE,
  school_year INTEGER NOT NULL,
  decision TEXT NOT NULL CHECK (decision IN ('assigned', 'waitlisted', 'ineligible', 'opted_out')),
  decision_reason TEXT NOT NULL CHECK (decision_reason IN ('ASSIGNED_NEAREST_STOP', 'ASSIGNED_ALT_STOP_FOR_WINDOW', 'ASSIGNED_WINDOW_EXCEPTION', 'ASSIGNED_FROM_WAITLIST', 'MIDYEAR_ASSIGNED', 'WAITLIST_NO_STOP_IN_RANGE', 'WAITLIST_NO_ACCESSIBLE_STOP', 'WAITLIST_NO_CAPACITY', 'WAITLIST_NO_ROUTE_SERVES_STOP', 'WAITLIST_ADDRESS_PENDING', 'WAITLIST_CAPACITY_REDUCED', 'INELIGIBLE_WALK_ZONE', 'OPTED_OUT_GUARDIAN', 'CAPACITY_REDUCED_REASSIGN', 'MANUAL_OVERRIDE', 'STUDENT_WITHDRAWN')),
  route_id TEXT,
  stop_id TEXT,
  route_stop_id TEXT,
  walk_distance_m INTEGER,
  scheduled_pickup_time TEXT,
  ride_time_min INTEGER,
  window_ok INTEGER CHECK (window_ok IN (0, 1)),
  capacity_ok INTEGER CHECK (capacity_ok IN (0, 1)),
  accessibility_ok INTEGER CHECK (accessibility_ok IN (0, 1)),
  decided_on TEXT NOT NULL,
  effective_from TEXT NOT NULL,
  current_status TEXT NOT NULL CHECK (current_status IN ('active', 'waitlisted', 'ineligible', 'opted_out', 'ended')),
  status_as_of TEXT NOT NULL,
  FOREIGN KEY (student_id) REFERENCES student(student_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (route_id) REFERENCES route(route_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (stop_id) REFERENCES stop(stop_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (route_stop_id) REFERENCES route_stop(route_stop_id) DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE assignment_event (
  event_id TEXT PRIMARY KEY,
  assignment_id TEXT NOT NULL,
  student_id TEXT NOT NULL,
  event_seq INTEGER NOT NULL,
  event_type TEXT NOT NULL CHECK (event_type IN ('ASSIGNED', 'WAITLISTED', 'INELIGIBLE', 'OPTED_OUT', 'REASSIGNED', 'ENDED')),
  event_date TEXT NOT NULL,
  route_id TEXT,
  stop_id TEXT,
  route_stop_id TEXT,
  reason_code TEXT NOT NULL CHECK (reason_code IN ('ASSIGNED_NEAREST_STOP', 'ASSIGNED_ALT_STOP_FOR_WINDOW', 'ASSIGNED_WINDOW_EXCEPTION', 'ASSIGNED_FROM_WAITLIST', 'MIDYEAR_ASSIGNED', 'WAITLIST_NO_STOP_IN_RANGE', 'WAITLIST_NO_ACCESSIBLE_STOP', 'WAITLIST_NO_CAPACITY', 'WAITLIST_NO_ROUTE_SERVES_STOP', 'WAITLIST_ADDRESS_PENDING', 'WAITLIST_CAPACITY_REDUCED', 'INELIGIBLE_WALK_ZONE', 'OPTED_OUT_GUARDIAN', 'CAPACITY_REDUCED_REASSIGN', 'MANUAL_OVERRIDE', 'STUDENT_WITHDRAWN')),
  triggered_by TEXT,
  actor_role TEXT NOT NULL CHECK (actor_role IN ('system', 'academic_administrator', 'support_staff', 'platform_administrator')),
  FOREIGN KEY (assignment_id) REFERENCES assignment(assignment_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (student_id) REFERENCES student(student_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (route_id) REFERENCES route(route_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (stop_id) REFERENCES stop(stop_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (route_stop_id) REFERENCES route_stop(route_stop_id) DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE bus_capacity_event (
  capacity_event_id TEXT PRIMARY KEY,
  bus_id TEXT NOT NULL,
  event_type TEXT NOT NULL CHECK (event_type IN ('SEATS_OUT_OF_SERVICE', 'REPLACED_SMALLER', 'REPLACED_LARGER')),
  previous_capacity INTEGER NOT NULL,
  new_capacity INTEGER NOT NULL,
  effective_from TEXT NOT NULL,
  effective_to TEXT,
  recorded_by TEXT NOT NULL CHECK (recorded_by IN ('system', 'academic_administrator', 'support_staff', 'platform_administrator')),
  FOREIGN KEY (bus_id) REFERENCES bus(bus_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (effective_from) REFERENCES school_day(service_date) DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE route_disruption (
  disruption_id TEXT PRIMARY KEY,
  route_id TEXT NOT NULL,
  service_date TEXT NOT NULL,
  disruption_type TEXT NOT NULL CHECK (disruption_type IN ('traffic_delay', 'breakdown', 'weather', 'driver_absence')),
  from_stop_sequence INTEGER NOT NULL,
  delay_min INTEGER NOT NULL,
  service_cancelled INTEGER NOT NULL CHECK (service_cancelled IN (0, 1)),
  replacement_bus_id TEXT,
  replacement_driver_id TEXT,
  resolution TEXT NOT NULL CHECK (resolution IN ('delayed_service', 'replacement_bus', 'spare_driver', 'cancelled')),
  reported_at TEXT NOT NULL,
  FOREIGN KEY (route_id) REFERENCES route(route_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (service_date) REFERENCES school_day(service_date) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (replacement_bus_id) REFERENCES bus(bus_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (replacement_driver_id) REFERENCES driver(driver_id) DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE attendance_event (
  attendance_id TEXT PRIMARY KEY,
  service_date TEXT NOT NULL,
  student_id TEXT NOT NULL,
  assignment_id TEXT NOT NULL,
  route_id TEXT NOT NULL,
  stop_id TEXT NOT NULL,
  scheduled_pickup_time TEXT NOT NULL,
  bus_arrival_time TEXT,
  delay_min INTEGER,
  attendance_status TEXT NOT NULL CHECK (attendance_status IN ('boarded', 'boarded_late', 'absent_reported', 'no_show', 'missed_pickup')),
  disruption_id TEXT,
  recorded_by TEXT NOT NULL CHECK (recorded_by IN ('driver_app', 'guardian_portal', 'system')),
  FOREIGN KEY (service_date) REFERENCES school_day(service_date) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (student_id) REFERENCES student(student_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (assignment_id) REFERENCES assignment(assignment_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (route_id) REFERENCES route(route_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (stop_id) REFERENCES stop(stop_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (disruption_id) REFERENCES route_disruption(disruption_id) DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE notification (
  notification_id TEXT PRIMARY KEY,
  student_id TEXT NOT NULL,
  contact_id TEXT,
  notification_type TEXT NOT NULL CHECK (notification_type IN ('ASSIGNMENT_CONFIRMED', 'WINDOW_EXCEPTION', 'WAITLIST_NOTICE', 'REASSIGNMENT_NOTICE', 'SERVICE_ENDED', 'ROUTE_DELAY', 'SERVICE_CANCELLED', 'MISSED_PICKUP', 'NO_SHOW')),
  channel TEXT CHECK (channel IN ('sms', 'email', 'app_push')),
  trigger_entity TEXT NOT NULL CHECK (trigger_entity IN ('assignment_event', 'route_disruption', 'attendance_event')),
  trigger_id TEXT NOT NULL,
  service_date TEXT NOT NULL,
  sent_at TEXT NOT NULL,
  delivery_status TEXT NOT NULL CHECK (delivery_status IN ('delivered', 'bounced', 'failed', 'suppressed')),
  failure_reason TEXT,
  message_preview TEXT NOT NULL,
  FOREIGN KEY (student_id) REFERENCES student(student_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (contact_id) REFERENCES guardian_contact(contact_id) DEFERRABLE INITIALLY DEFERRED
);
