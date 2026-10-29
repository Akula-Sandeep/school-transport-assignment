"""Step 3c: daily operations -> route disruptions, attendance events and guardian
notifications. Everything is derived from the persisted assignment_event history
(via rules.build_segments), not from the planner's in-memory state.

Disruptions: traffic delays, breakdowns (spare bus of matching type and enough seats,
else cancelled), driver absence (spare driver, accessible-trained for accessible
routes, else cancelled) and network-wide weather days; on the first weather day
routes touching the rural ring are cancelled (flooded roads).

Attendance rules (per assigned student, per school day):
  absent & guardian reported         -> absent_reported (bus does not wait)
  route cancelled (no spare)         -> missed_pickup
  bus later than schedule + 15 min   -> missed_pickup (student has left)
  absent & not reported              -> no_show
  bus later than schedule + 5 min    -> boarded_late
  otherwise                          -> boarded
Buses never leave a stop before the scheduled time.

Notification rules: one notice per triggering record, sent to the highest-priority
contact that is active, consented, effective on the date and well-formed for its
channel; if none qualifies the notice is logged as 'suppressed'.
"""
from . import config as C
from . import geo, ids, rules

TEMPLATES = {
    "ASSIGNMENT_CONFIRMED": "Transport confirmed from {date} for {sid}: {route}, stop {stop}, pickup {time}.",
    "WINDOW_EXCEPTION": "Pickup for {sid} at {stop} ({route}) is {time}, outside the requested window. "
                        "Please contact the transport office.",
    "WAITLIST_NOTICE": "{sid} is on the transport waitlist from {date} ({reason}).",
    "REASSIGNMENT_NOTICE": "From {date} {sid} rides {route}, stop {stop}, pickup {time}.",
    "SERVICE_ENDED": "Transport for {sid} ends on {date}.",
    "ROUTE_DELAY": "{route} is running about {delay} min late on {date}; expected at {stop} near {time}.",
    "SERVICE_CANCELLED": "{route} is cancelled on {date}; please arrange alternate transport for {sid}.",
    "MISSED_PICKUP": "Bus reached {stop} at {time} on {date} ({delay} min late); {sid} was not picked up.",
    "NO_SHOW": "{sid} was not at {stop} when the bus arrived at {time} on {date}.",
}


class Notifier:
    def __init__(self, contacts):
        self.by_student = {}
        for c in contacts:
            self.by_student.setdefault(c["student_id"], []).append(c)
        self.rows = []

    def send(self, sid, ntype, trigger_entity, trigger_id, date, minute, **fmt):
        c = rules.pick_contact(self.by_student.get(sid, []), sid, date)
        msg = TEMPLATES[ntype].format(sid=sid, date=date, **fmt)
        self.rows.append({
            "notification_id": None, "student_id": sid,
            "contact_id": c["contact_id"] if c else None, "notification_type": ntype,
            "channel": c["preferred_channel"] if c else None, "trigger_entity": trigger_entity,
            "trigger_id": trigger_id, "service_date": date, "sent_at": geo.stamp(date, minute),
            "delivery_status": "delivered" if c else "suppressed",
            "failure_reason": None if c else "NO_VALID_CONTACT", "message_preview": msg,
        })


def assignment_notifications(notifier, events, plan, students):
    prev = {}
    for e in sorted(events, key=lambda e: (e["event_date"], e["event_id"])):
        sid = e["student_id"]
        before = prev.get(e["assignment_id"])
        prev[e["assignment_id"]] = e["event_type"]
        minute = 18 * 60 if e["event_date"] < C.FIRST_SCHOOL_DAY else 6 * 60
        t = e["event_type"]
        if t in ("ASSIGNED", "REASSIGNED"):
            pickup = plan.pickup_min(e["route_id"], e["stop_id"])
            if t == "REASSIGNED":
                ntype = "REASSIGNMENT_NOTICE"
            else:
                ntype = ("ASSIGNMENT_CONFIRMED" if rules.window_ok(students[sid], pickup)
                         else "WINDOW_EXCEPTION")
            notifier.send(sid, ntype, "assignment_event", e["event_id"], e["event_date"], minute,
                          route=e["route_id"], stop=e["stop_id"], time=geo.hhmm(pickup))
        elif t == "WAITLISTED":
            notifier.send(sid, "WAITLIST_NOTICE", "assignment_event", e["event_id"], e["event_date"],
                          minute, reason=e["reason_code"])
        elif t == "ENDED" and before in ("ASSIGNED", "REASSIGNED", "WAITLISTED"):
            notifier.send(sid, "SERVICE_ENDED", "assignment_event", e["event_id"], e["event_date"], minute)


def run(plan, students, contacts, buses, drivers, days, events, assignments, scale, seed):
    rng_dis = ids.stage_rng(seed, "disruptions")
    rng_noise = ids.stage_rng(seed, "arrival_noise")
    rng_abs = ids.stage_rng(seed, "absence")
    student_by_id = {s["student_id"]: s for s in students}
    dates = [d["service_date"] for d in days]
    n = len(dates)
    notifier = Notifier(contacts)
    assignment_notifications(notifier, events, plan, student_by_id)

    # ---- who is on which route each day (from persisted events only)
    segments = rules.build_segments(events, dates)
    asn_student = {a["assignment_id"]: a["student_id"] for a in assignments}
    day_routes = [dict() for _ in range(n)]
    for asn in sorted(segments):
        sid = asn_student[asn]
        for a, b, rid, stop, _ev in segments[asn]:
            for i in range(a, b + 1):
                day_routes[i].setdefault(rid, []).append((stop, sid, asn))

    timing = {}
    for r in plan.routes:
        t, total, dep = plan.timing(r["route_id"])
        for k, stop in enumerate(plan.seq[r["route_id"]], start=1):
            timing[(r["route_id"], stop)] = (int(round(t[stop][1])), k)
        timing[(r["route_id"], None)] = (int(round(dep)), 0)

    # ---- per-student absence propensity (heterogeneous), per-day multipliers
    propensity = {}
    for s in sorted(student_by_id):
        u = rng_abs.random()
        propensity[s] = (rng_abs.uniform(0.015, 0.05) if u < 0.70 else
                         rng_abs.uniform(0.05, 0.12) if u < 0.95 else rng_abs.uniform(0.12, 0.25))
    weather = set(rng_dis.sample(range(min(2, n - 1), n), min(scale.weather_days, max(0, n - 2))))
    severe_day = min(weather) if weather else None
    rural_ring = len(geo.rings()) - 1

    def rural(rid):
        return any(geo.ring_of(geo.radius((plan.stop_by_id[s]["x_km"], plan.stop_by_id[s]["y_km"]))) == rural_ring
                   for s in plan.seq[rid])

    flu = set(range(int(n * 0.25), int(n * 0.25) + 10)) | set(range(int(n * 0.6), int(n * 0.6) + 10))

    spare_buses = sorted([b for b in buses if b["fleet_role"] == "spare"],
                         key=lambda b: (b["base_seated_capacity"], b["bus_id"]))
    rostered = {r["driver_id"] for r in plan.routes}
    spare_drivers = sorted([d for d in drivers if d["employment_status"] == "active"
                            and d["driver_id"] not in rostered], key=lambda d: d["driver_id"])

    disruptions, attendance = [], []
    att_n = 0
    for idx, date in enumerate(dates):
        wd = geo.d(date).weekday()
        factor = (1.15 if wd in (0, 4) else 1.0) * (1.6 if idx in flu else 1.0) * (1.3 if idx in weather else 1.0)
        used_buses, used_drivers = set(), set()
        for rid in sorted(day_routes[idx]):
            r = plan.route_by_id[rid]
            members = sorted(day_routes[idx][rid], key=lambda m: (timing[(rid, m[0])][1], m[1]))
            dep = timing[(rid, None)][0]
            dis = None
            u = rng_dis.random()
            if idx in weather and idx == severe_day and rural(rid):
                # severe weather: flooded rural roads, route cannot run safely
                dis = {"disruption_type": "weather", "from_stop_sequence": 1, "delay_min": 0,
                       "resolution": "cancelled", "_minute": dep - 30}
            elif idx in weather:
                dis = {"disruption_type": "weather", "from_stop_sequence": 1,
                       "delay_min": rng_dis.randint(5, 14), "resolution": "delayed_service",
                       "_minute": dep - 10}
            elif u < 0.004:
                need_acc = r["service_type"] == "accessible"
                spare = next((b for b in spare_buses if b["is_accessible"] == need_acc
                              and b["bus_id"] not in used_buses
                              and b["base_seated_capacity"] >= len(members)), None)
                dis = {"disruption_type": "breakdown", "from_stop_sequence": 1, "_minute": dep - 10}
                if spare:
                    used_buses.add(spare["bus_id"])
                    dis.update(delay_min=rng_dis.randint(20, 45), resolution="replacement_bus",
                               replacement_bus_id=spare["bus_id"])
                else:
                    dis.update(delay_min=0, resolution="cancelled")
            elif u < 0.009:
                need_tr = r["service_type"] == "accessible"
                spare = next((d for d in spare_drivers if d["driver_id"] not in used_drivers
                              and (d["accessible_trained"] or not need_tr)), None)
                dis = {"disruption_type": "driver_absence", "from_stop_sequence": 1, "_minute": dep - 10}
                if spare:
                    used_drivers.add(spare["driver_id"])
                    dis.update(delay_min=rng_dis.randint(10, 20), resolution="spare_driver",
                               replacement_driver_id=spare["driver_id"])
                else:
                    dis.update(delay_min=0, resolution="cancelled")
            elif u < 0.034:
                k = rng_dis.randint(1, len(plan.seq[rid]))
                stop_k = plan.seq[rid][k - 1]
                dis = {"disruption_type": "traffic_delay", "from_stop_sequence": k,
                       "delay_min": rng_dis.randint(5, 25), "resolution": "delayed_service",
                       "_minute": timing[(rid, stop_k)][0] - 5}
            if dis:
                dis = {"disruption_id": ids.disruption(len(disruptions) + 1), "route_id": rid,
                       "service_date": date, "replacement_bus_id": None, "replacement_driver_id": None,
                       "service_cancelled": dis["resolution"] == "cancelled",
                       "reported_at": geo.stamp(date, dis["_minute"]), **dis}
                disruptions.append(dis)
            cancelled = bool(dis and dis["service_cancelled"])
            # bus arrival per stop: shared route noise + stop noise + disruption delay, never early
            route_noise = rng_noise.gauss(0, 1.5)
            arrival = {}
            for k, stop in enumerate(plan.seq[rid], start=1):
                sched = timing[(rid, stop)][0]
                extra = dis["delay_min"] if dis and not cancelled and k >= dis["from_stop_sequence"] else 0
                arrival[stop] = sched + max(0, int(round(route_noise + rng_noise.gauss(0, 0.8) + extra)))
            for stop, sid, asn in members:
                sched, k = timing[(rid, stop)]
                affected = dis is not None and (cancelled or k >= dis["from_stop_sequence"])
                dis_id = dis["disruption_id"] if affected else None
                absent = rng_abs.random() < propensity[sid] * factor
                reported = absent and rng_abs.random() < 0.65
                att_n += 1
                aid = ids.attendance(att_n)
                arr = None if (reported or cancelled) else arrival[stop]
                delay = None if arr is None else arr - sched
                if reported:
                    status, by = "absent_reported", "guardian_portal"
                elif cancelled:
                    status, by = "missed_pickup", "system"
                elif delay > C.MAX_WAIT_MIN:
                    status, by = "missed_pickup", "driver_app"
                elif absent:
                    status, by = "no_show", "driver_app"
                elif delay > C.LATE_THRESHOLD_MIN:
                    status, by = "boarded_late", "driver_app"
                else:
                    status, by = "boarded", "driver_app"
                attendance.append((aid, date, sid, asn, rid, stop, geo.hhmm(sched),
                                   geo.hhmm(arr) if arr is not None else None, delay, status, dis_id, by))
                # notifications driven by this day's records
                if (dis and not cancelled and affected and dis["delay_min"] >= C.DELAY_NOTIFY_MIN
                        and not reported):
                    notifier.send(sid, "ROUTE_DELAY", "route_disruption", dis["disruption_id"], date,
                                  dis["_minute"] + 2, route=rid, stop=stop, delay=dis["delay_min"],
                                  time=geo.hhmm(sched + dis["delay_min"]))
                if status == "missed_pickup" and cancelled:
                    notifier.send(sid, "SERVICE_CANCELLED", "attendance_event", aid, date,
                                  dis["_minute"] + 2, route=rid)
                elif status == "missed_pickup":
                    notifier.send(sid, "MISSED_PICKUP", "attendance_event", aid, date,
                                  sched + C.MAX_WAIT_MIN + 1, stop=stop, time=geo.hhmm(arr), delay=delay)
                elif status == "no_show":
                    notifier.send(sid, "NO_SHOW", "attendance_event", aid, date, arr + 2,
                                  stop=stop, time=geo.hhmm(arr))
    for d in disruptions:
        d.pop("_minute", None)
    return disruptions, attendance, notifier.rows, segments


def number_notifications(rows):
    order = {t: i for i, t in enumerate(C.NOTIFICATION_TYPES)}
    rows.sort(key=lambda r: (r["sent_at"], order[r["notification_type"]], r["student_id"], r["trigger_id"]))
    for i, r in enumerate(rows, start=1):
        r["notification_id"] = ids.notification(i)
