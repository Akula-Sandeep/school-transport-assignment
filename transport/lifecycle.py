"""Step 3b: replay the school year day by day and persist every assignment state
change as an append-only assignment_event.

Per school day, in this order:
 1. withdrawals            -> ENDED
 2. bus capacity changes   -> overflow students REASSIGNED (compatible route with a free
                              seat and a pickup inside their window) or WAITLISTED
 3. scheduled hooks        -> labelled anomaly injections (see anomalies.py)
 4. admin overrides        -> REASSIGNED (MANUAL_OVERRIDE, guardian requests)
 5. mid-year enrollments   -> decision (ASSIGNED / WAITLISTED / INELIGIBLE / OPTED_OUT)
 6. Mondays                -> retry capacity-waitlisted students (ASSIGNED_FROM_WAITLIST)
"""
from . import config as C
from . import geo, rules


class Lifecycle:
    def __init__(self, plan, students, buses, days, cap_book, rng):
        self.plan = plan
        self.students = {s["student_id"]: s for s in students}
        self.bus = {b["bus_id"]: b for b in buses}
        self.dates = [d["service_date"] for d in days]
        self.cap = cap_book
        self.rng = rng
        self.events = []
        self.assignments = {}
        self.state = {}                 # sid -> dict(status, rid, stop, reason, since)
        self.members = {r["route_id"]: {} for r in plan.routes}
        self.hooks = {}                 # date -> [callable(lc, date)]
        self.capacity_events = []       # all events (baseline + injected), ids assigned later
        self.handled = set()            # id(event) of events the engine reacts to
        self.log = []                   # engine decisions for the exceptions report

    # ---------------------------------------------------------------- helpers
    def load(self, rid):
        return len(self.members[rid])

    def wheelchairs(self, rid):
        return sum(1 for s in self.members[rid] if self.students[s]["mobility_aid"] == "wheelchair")

    def route(self, rid):
        return self.plan.route_by_id[rid]

    def has_seat(self, rid, sid, date):
        r = self.route(rid)
        if self.load(rid) >= self.cap.capacity(r["bus_id"], date):
            return False
        if self.students[sid]["mobility_aid"] == "wheelchair":
            return self.wheelchairs(rid) < self.bus[r["bus_id"]]["wheelchair_positions"]
        return True

    def find_seat(self, sid, date, exclude=None, allow_window_exception=True):
        """Return ((rid, stop), window_ok) or (None, waitlist_reason)."""
        st = self.students[sid]
        cands = self.plan.cand_stops[sid]
        if not cands:
            return None, ("WAITLIST_NO_ACCESSIBLE_STOP" if st["requires_accessible_vehicle"]
                          else "WAITLIST_NO_STOP_IN_RANGE")
        net = rules.network_for(st)
        served, fallback = False, None
        for walk, stop in cands:
            for rid in sorted(self.plan.stop_routes.get(stop, [])):
                if self.route(rid)["service_type"] != net or (rid, stop) == exclude:
                    continue
                served = True
                if not self.has_seat(rid, sid, date):
                    continue
                ok = rules.window_ok(st, self.plan.pickup_min(rid, stop))
                if ok:
                    return ((rid, stop), True), None
                if fallback is None:
                    fallback = (rid, stop)
        if fallback is not None and allow_window_exception:
            return (fallback, False), None
        return None, ("WAITLIST_NO_CAPACITY" if served else "WAITLIST_NO_ROUTE_SERVES_STOP")

    def emit(self, sid, etype, date, key, reason, actor="system", trigger=None):
        st = self.state.setdefault(sid, {"status": None, "rid": None, "stop": None, "reason": None,
                                         "since": None, "seq": 0})
        if st["rid"] is not None:
            self.members[st["rid"]].pop(sid, None)
        rid, stop = key if key else (None, None)
        st["seq"] += 1
        rs = self.plan.rs_by_key[(rid, stop)]["route_stop_id"] if rid else None
        ev = {"event_id": None, "assignment_id": self.assignments[sid]["assignment_id"], "student_id": sid,
              "event_seq": st["seq"], "event_type": etype, "event_date": date, "route_id": rid,
              "stop_id": stop, "route_stop_id": rs, "reason_code": reason, "triggered_by": trigger,
              "actor_role": actor}
        self.events.append(ev)
        status = {"ASSIGNED": "active", "REASSIGNED": "active", "WAITLISTED": "waitlisted",
                  "INELIGIBLE": "ineligible", "OPTED_OUT": "opted_out", "ENDED": "ended"}[etype]
        st.update(status=status, rid=rid, stop=stop, reason=reason, since=date)
        if rid:
            self.members[rid][sid] = True
        return ev

    def header(self, sid, decision, reason, date, effective, key=None, window_ok=None):
        st = self.students[sid]
        h = {"assignment_id": f"ASN-{sid}-{C.SCHOOL_YEAR}", "student_id": sid, "school_year": C.SCHOOL_YEAR,
             "decision": decision, "decision_reason": reason, "route_id": None, "stop_id": None,
             "route_stop_id": None, "walk_distance_m": None, "scheduled_pickup_time": None,
             "ride_time_min": None, "window_ok": None, "capacity_ok": None, "accessibility_ok": None,
             "decided_on": date, "effective_from": effective, "current_status": None, "status_as_of": None}
        if key:
            rid, stop = key
            s = self.plan.rs_by_key[(rid, stop)]
            stop_row = self.plan.stop_by_id[stop]
            pickup = self.plan.pickup_min(rid, stop)
            r = self.route(rid)
            h.update(route_id=rid, stop_id=stop, route_stop_id=s["route_stop_id"],
                     walk_distance_m=geo.walk_m((st["home_x_km"], st["home_y_km"]),
                                                (stop_row["x_km"], stop_row["y_km"])),
                     scheduled_pickup_time=geo.hhmm(pickup), ride_time_min=r["_arrival_min"] - pickup,
                     window_ok=window_ok, capacity_ok=self.load(rid) <= self.cap.capacity(r["bus_id"], date),
                     accessibility_ok=(r["service_type"] == "accessible") == st["requires_accessible_vehicle"])
        self.assignments[sid] = h
        return h

    # ---------------------------------------------------------------- decisions
    def decide_at_plan(self, sid):
        p = self.plan
        if sid in p.initial:
            rid, stop = p.initial[sid]
            ok = rules.window_ok(self.students[sid], p.pickup_min(rid, stop))
            reason = ("ASSIGNED_WINDOW_EXCEPTION" if not ok else
                      "ASSIGNED_ALT_STOP_FOR_WINDOW" if sid in p.moved_for_window else "ASSIGNED_NEAREST_STOP")
            self.header(sid, "assigned", reason, C.PLANNING_DATE, self.dates[0], (rid, stop), ok)
            self.emit(sid, "ASSIGNED", C.PLANNING_DATE, (rid, stop), reason)
        else:
            decision, reason = p.outcome[sid]
            self.header(sid, decision, reason, C.PLANNING_DATE, self.dates[0])
            self.emit(sid, decision.upper() if decision != "opted_out" else "OPTED_OUT",
                      C.PLANNING_DATE, None, reason)

    def decide_midyear(self, sid, date):
        pre = rules.pre_assignment_outcome(self.students[sid])
        if pre:
            decision, reason = pre
            self.header(sid, decision, reason, date, date)
            self.emit(sid, {"ineligible": "INELIGIBLE", "opted_out": "OPTED_OUT",
                            "waitlisted": "WAITLISTED"}[decision], date, None, reason)
            return
        found, why = self.find_seat(sid, date)
        if found:
            key, ok = found
            reason = "MIDYEAR_ASSIGNED" if ok else "ASSIGNED_WINDOW_EXCEPTION"
            self.header(sid, "assigned", reason, date, date, key, ok)
            self.emit(sid, "ASSIGNED", date, key, reason)
        else:
            self.header(sid, "waitlisted", why, date, date)
            self.emit(sid, "WAITLISTED", date, None, why)

    def apply_capacity_event(self, ev, date):
        rid = next((r["route_id"] for r in self.plan.routes if r["bus_id"] == ev["bus_id"]), None)
        if rid is None:
            return
        overflow = self.load(rid) - ev["new_capacity"]
        if overflow <= 0:
            return
        victims = sorted(self.members[rid], key=lambda s: (self.state[s]["since"], s), reverse=True)
        for sid in victims[:overflow]:
            # free the seat first so the student is not counted on the overloaded route
            key_now = (rid, self.state[sid]["stop"])
            self.members[rid].pop(sid, None)
            found, why = self.find_seat(sid, date, exclude=key_now, allow_window_exception=False)
            if found:
                self.emit(sid, "REASSIGNED", date, found[0], "CAPACITY_REDUCED_REASSIGN",
                          trigger=ev, actor="system")
            else:
                self.emit(sid, "WAITLISTED", date, None, "WAITLIST_CAPACITY_REDUCED", trigger=ev)

    def retry_waitlist(self, date):
        for sid in sorted(self.state):
            st = self.state[sid]
            if st["status"] == "waitlisted" and st["reason"] in ("WAITLIST_NO_CAPACITY",
                                                                  "WAITLIST_CAPACITY_REDUCED"):
                found, _ = self.find_seat(sid, date)
                if found:
                    self.emit(sid, "ASSIGNED", date, found[0], "ASSIGNED_FROM_WAITLIST")

    def manual_override(self, date):
        """Benign admin change (e.g. guardian asks for a different compatible stop)."""
        active = sorted(s for s, st in self.state.items() if st["status"] == "active")
        self.rng.shuffle(active)
        for sid in active[:20]:
            st = self.state[sid]
            found, _ = self.find_seat(sid, date, exclude=(st["rid"], st["stop"]), allow_window_exception=False)
            if found:
                self.emit(sid, "REASSIGNED", date, found[0], "MANUAL_OVERRIDE", actor="academic_administrator")
                return

    # ---------------------------------------------------------------- run
    def run(self, baseline_capacity_specs, n_overrides):
        students = sorted(self.students.values(), key=lambda s: s["student_id"])
        first = self.dates[0]
        for s in students:
            if s["enrolled_on"] < first:
                self.decide_at_plan(s["student_id"])
        enroll = {}
        withdraw = {}
        for s in students:
            if s["enrolled_on"] >= first:
                enroll.setdefault(s["enrolled_on"], []).append(s["student_id"])
            if s["withdrawn_on"]:
                withdraw.setdefault(s["withdrawn_on"], []).append(s["student_id"])
        cap_specs = {}
        for spec in baseline_capacity_specs:
            cap_specs.setdefault(spec["date"], []).append(spec)
        n = len(self.dates)
        override_days = set()
        if n > 4:
            for _ in range(n_overrides):
                override_days.add(self.dates[self.rng.randint(2, n - 2)])
        for idx, date in enumerate(self.dates):
            for sid in withdraw.get(date, []):
                if sid in self.assignments:
                    self.emit(sid, "ENDED", date, None, "STUDENT_WITHDRAWN",
                              actor="academic_administrator")
            for spec in sorted(cap_specs.get(date, []), key=lambda x: x["bus_id"]):
                ev = self.make_capacity_event(spec, date, idx)
                self.cap.add(ev)
                self.handled.add(id(ev))
                self.apply_capacity_event(ev, date)
            for hook in self.hooks.get(date, []):
                hook(self, date)
            if date in override_days:
                self.manual_override(date)
            for sid in enroll.get(date, []):
                self.decide_midyear(sid, date)
            if idx > 0 and geo.d(date).weekday() == 0:
                self.retry_waitlist(date)

    def make_capacity_event(self, spec, date, idx, new_capacity=None):
        bus = self.bus[spec["bus_id"]]
        base = self.cap.capacity(bus["bus_id"], date)
        if new_capacity is None:
            if spec["type"] == "SEATS_OUT_OF_SERVICE":
                new_capacity = base - self.rng.randint(4, 8)
            elif spec["type"] == "REPLACED_SMALLER":
                new_capacity = 48 if base >= 60 else base - 12
            else:
                new_capacity = base + 12
        end = None
        if spec["type"] != "REPLACED_LARGER":
            end = self.dates[min(len(self.dates) - 1, idx + spec["duration"] - 1)]
        ev = {"capacity_event_id": None, "bus_id": bus["bus_id"], "event_type": spec["type"],
              "previous_capacity": base, "new_capacity": new_capacity, "effective_from": date,
              "effective_to": end, "recorded_by": "support_staff"}
        self.capacity_events.append(ev)
        return ev


def baseline_capacity_specs(plan, scale, days, rng):
    """Choose which route buses get an engine-handled capacity change, and when."""
    buses = sorted(r["bus_id"] for r in plan.routes if r["service_type"] == "regular")
    picks = rng.sample(buses, min(scale.capacity_events, len(buses)))
    n = len(days)
    specs = []
    types = ["REPLACED_SMALLER", "SEATS_OUT_OF_SERVICE", "REPLACED_LARGER"]
    for i, b in enumerate(sorted(picks)):
        idx = rng.randint(min(3, n - 1), max(3, n - 4))
        specs.append({"bus_id": b, "date": days[idx]["service_date"], "type": types[i % 3],
                      "duration": rng.randint(5, 20)})
    return specs
