"""Step 5: inject labelled edge cases into an otherwise valid baseline.

Each injection changes only the records that carry the defect (plus values that
are *derived* from them, which are recomputed so arithmetic still reconciles),
and appends one row to the ground truth. The ground truth is written to its own
folder and never joined back into the input tables.

  capacity_exceeded            capacity change recorded but not acted on -> route over capacity
  incompatible_route           admin override puts a student needing an accessible vehicle on a regular bus
  impossible_travel_time       a route leg is timed faster than any bus could drive
  notification_invalid_contact notice sent to a bounced/inactive/expired/malformed or other family's contact
  unapproved_address_exposed   a pending home-address stop used on a route, or an address leaked in a message
"""
import math

from . import config as C
from . import geo, rules
from .planning import evaluate

EXPECTED = {
    "capacity_exceeded": ("reassign_or_waitlist_overflow",
                          "active load <= effective bus capacity on every service date"),
    "incompatible_route": ("revert_to_accessible_route",
                           "students requiring an accessible vehicle ride accessible routes only"),
    "impossible_travel_time": ("reject_route_plan",
                               f"implied leg speed <= {C.MAX_FEASIBLE_SPEED_KMPH:.0f} km/h and leg >= "
                               f"{C.MIN_LEG_MIN} min"),
    "notification_invalid_contact": ("block_send_and_use_valid_contact",
                                     "recipient is an active, consented, effective, well-formed contact "
                                     "of the same student"),
    "unapproved_address_exposed": ("remove_stop_or_redact_message",
                                   "only approved stops on routes; no residential address in messages"),
}


class GroundTruth:
    def __init__(self):
        self.items = []

    def add(self, issue_type, subtype, entity_table, ref, related, first_date, description):
        decision, rule = EXPECTED[issue_type]
        self.items.append({"issue_type": issue_type, "subtype": subtype, "entity_table": entity_table,
                           "_ref": ref, "related": related, "first_date": first_date,
                           "expected_decision": decision, "rule_violated": rule,
                           "description": description})

    def rows(self, resolve):
        out = []
        for i, it in enumerate(self.items, start=1):
            out.append({
                "issue_id": f"GT-{i:04d}", "issue_type": it["issue_type"], "subtype": it["subtype"],
                "entity_table": it["entity_table"], "entity_id": resolve(it["entity_table"], it["_ref"]),
                "related_ids": "|".join(f"{k}={resolve(k, v) if not isinstance(v, str) else v}"
                                        for k, v in it["related"].items()),
                "first_date": it["first_date"], "expected_decision": it["expected_decision"],
                "rule_violated": it["rule_violated"], "description": it["description"],
                "injected": True,
            })
        return out


# ------------------------------------------------------------------ plan-time
def inject_plan(plan, students, k, rng, gt, protected_routes):
    """Unapproved home stop on a route + impossible leg timings. Returns routes touched."""
    sb = {s["student_id"]: s for s in students}
    touched = set()
    n_stop = math.ceil(k / 2)
    requests = sorted((s for s in plan.stop_by_id.values() if s.get("_requested_by")),
                      key=lambda s: s["stop_id"])
    rng.shuffle(requests)
    for req in requests:
        if n_stop == 0:
            break
        sid = req["_requested_by"]
        if sid not in plan.initial:
            continue
        rid, old_stop = plan.initial[sid]
        r = plan.route_by_id[rid]
        if r["service_type"] != "regular" or rid in touched or rid in protected_routes:
            continue
        dwell = C.DWELL_MIN["regular"]
        best = None
        for pos in range(len(plan.seq[rid]) + 1):
            seq = plan.seq[rid][:pos] + [req["stop_id"]] + plan.seq[rid][pos:]
            ev = evaluate(seq, plan.stop_by_id, dwell)
            if ev["total"] <= C.MAX_ROUTE_MIN - 1 and (best is None or ev["total"] < best[0]["total"]):
                best = (ev, seq)
        if best is None:
            continue
        ev, seq = best
        plan.seq[rid], plan.legs[rid], plan.final[rid] = seq, ev["legs"], ev["final"]
        plan.initial[sid] = (rid, req["stop_id"])
        touched.add(rid)
        n_stop -= 1
        gt.add("unapproved_address_exposed", "unapproved_home_stop_on_route", "route_stop",
               (rid, req["stop_id"]), {"route": rid, "stop": req["stop_id"], "student": sid},
               C.FIRST_SCHOOL_DAY,
               f"Pending guardian-request stop at {sid}'s home placed on {rid}; residential location "
               f"published on a route roster before safety approval.")
    # impossible travel time: a long leg timed at 250-600 km/h
    routes = sorted(r["route_id"] for r in plan.routes)
    rng.shuffle(routes)
    n_tt = k
    for rid in routes:
        if n_tt == 0:
            break
        if rid in touched or rid in protected_routes:
            continue
        legs = plan.legs[rid]
        cand = [i for i in range(1, len(legs)) if legs[i][0] >= 1.5]
        if not cand:
            continue
        i = rng.choice(cand)
        km = legs[i][0]
        mins = max(0.1, round(km / rng.uniform(250, 600) * 60, 1))
        legs[i] = (km, mins)
        touched.add(rid)
        n_tt -= 1
        stop = plan.seq[rid][i]
        gt.add("impossible_travel_time", "leg_faster_than_feasible", "route_stop", (rid, stop),
               {"route": rid, "stop": stop}, C.FIRST_SCHOOL_DAY,
               f"Leg into {stop} on {rid}: {km} km timed at {mins} min "
               f"({geo.implied_speed_kmph(km, mins):.0f} km/h).")
    return touched


# ------------------------------------------------------------------ lifecycle hooks
def register_lifecycle(lc, k, rng, gt, busy_buses, plan_touched):
    dates = lc.dates
    n = len(dates)
    lo, hi = max(1, int(n * 0.2)), max(2, int(n * 0.8))
    cap_routes = set()

    def cap_hook(lc, date):
        idx = dates.index(date)
        for r in sorted(lc.plan.routes, key=lambda r: r["route_id"]):
            rid = r["route_id"]
            if (r["service_type"] != "regular" or rid in cap_routes or r["bus_id"] in busy_buses
                    or lc.cap.has_events(r["bus_id"]) or lc.load(rid) < 15):
                continue
            new_cap = lc.load(rid) - rng.randint(3, 8)
            spec = {"bus_id": r["bus_id"], "type": rng.choice(["SEATS_OUT_OF_SERVICE", "REPLACED_SMALLER"]),
                    "duration": rng.randint(5, 15)}
            ev = lc.make_capacity_event(spec, date, idx, new_capacity=new_cap)
            lc.cap.add(ev)          # recorded, but the engine never re-balances the route
            cap_routes.add(rid)
            gt.add("capacity_exceeded", "capacity_change_not_rebalanced", "route", rid,
                   {"bus": r["bus_id"], "capacity_event": ev}, date,
                   f"{r['bus_id']} capacity cut to {new_cap} on {date} while {lc.load(rid)} students "
                   f"were assigned to {rid}; overflow never reassigned.")
            return

    def incompat_hook(lc, date):
        cands = sorted(s for s, st in lc.state.items() if st["status"] == "active"
                       and lc.students[s]["requires_accessible_vehicle"]
                       and s not in done)
        rng.shuffle(cands)
        for sid in cands:
            st = lc.students[sid]
            home = (st["home_x_km"], st["home_y_km"])
            options = []
            for r in lc.plan.routes:
                rid = r["route_id"]
                # busy buses get an engine-handled capacity cut later, which could silently undo the override
                if (r["service_type"] != "regular" or r["bus_id"] in busy_buses
                        or lc.load(rid) >= lc.cap.capacity(r["bus_id"], date) - 1):
                    continue
                for stop in lc.plan.seq[rid]:
                    s = lc.plan.stop_by_id[stop]
                    options.append((geo.walk_m(home, (s["x_km"], s["y_km"])), rid, stop))
            if not options:
                continue
            walk, rid, stop = min(options)
            ev = lc.emit(sid, "REASSIGNED", date, (rid, stop), "MANUAL_OVERRIDE",
                         actor="academic_administrator")
            done.add(sid)
            gt.add("incompatible_route", f"{st['mobility_aid']}_user_on_regular_bus", "assignment_event", ev,
                   {"student": sid, "route": rid}, date,
                   f"{sid} ({st['mobility_aid']}) moved to non-accessible {rid} by manual override.")
            return

    done = set()
    days_cap = sorted(rng.sample(range(lo, hi), min(k, hi - lo)))
    days_inc = sorted(rng.sample(range(lo, hi), min(k, hi - lo)))
    for i in days_cap:
        lc.hooks.setdefault(dates[i], []).append(cap_hook)
    for i in days_inc:
        lc.hooks.setdefault(dates[i], []).append(incompat_hook)


# ------------------------------------------------------------------ notifications
def inject_notifications(notifications, contacts, students, k, rng, gt):
    by_student = {}
    for c in contacts:
        by_student.setdefault(c["student_id"], []).append(c)
    sb = {s["student_id"]: s for s in students}
    delivered = [n for n in notifications if n["delivery_status"] == "delivered"]
    delivered.sort(key=lambda n: (n["sent_at"], n["student_id"], n["trigger_id"], n["notification_type"]))
    rng.shuffle(delivered)
    used = set()

    def bad_contact(n, kind):
        for c in sorted(by_student.get(n["student_id"], []), key=lambda c: c["contact_id"]):
            probs = rules.contact_problems(c, n["student_id"], n["service_date"])
            if kind == "bounced" and c["contact_status"] == "bounced":
                return c
            if kind == "inactive" and c["contact_status"] == "inactive" and c["superseded_by"] is None:
                return c
            if kind == "expired" and "CONTACT_NOT_EFFECTIVE" in probs and c["valid_to"]:
                return c
            if kind == "malformed_phone" and "MALFORMED_PHONE" in probs:
                return c
        return None

    kinds = ["bounced", "inactive", "other_student", "malformed_phone", "expired"]
    all_contacts = sorted((c for c in contacts if c["contact_status"] == "active"), key=lambda c: c["contact_id"])
    for j in range(k):
        kind = kinds[j % len(kinds)]
        for n in delivered:
            if id(n) in used:
                continue
            if kind == "other_student":
                c = all_contacts[rng.randrange(len(all_contacts))]
                if c["student_id"] == n["student_id"]:
                    continue
            else:
                c = bad_contact(n, kind)
                if c is None:
                    continue
            used.add(id(n))
            status, reason = {"bounced": ("bounced", "CONTACT_BOUNCED"),
                              "inactive": ("failed", "CONTACT_INACTIVE"),
                              "expired": ("failed", "CONTACT_INACTIVE"),
                              "malformed_phone": ("failed", "MALFORMED_PHONE"),
                              "other_student": ("delivered", None)}[kind]
            n.update(contact_id=c["contact_id"], channel=c["preferred_channel"],
                     delivery_status=status, failure_reason=reason)
            if kind == "malformed_phone" and c["preferred_channel"] == "email":
                n["channel"] = "sms"
            gt.add("notification_invalid_contact", kind, "notification", n,
                   {"student": n["student_id"], "contact": c["contact_id"]}, n["service_date"],
                   f"{n['notification_type']} for {n['student_id']} sent to {c['contact_id']} ({kind}).")
            break
    # address leaked in message text
    for _ in range(k - math.ceil(k / 2)):
        for n in delivered:
            if id(n) in used or n["notification_type"] not in ("ROUTE_DELAY", "ASSIGNMENT_CONFIRMED"):
                continue
            used.add(id(n))
            n["message_preview"] += f" Pickup point: {sb[n['student_id']]['address_line']}."
            gt.add("unapproved_address_exposed", "address_in_message", "notification", n,
                   {"student": n["student_id"]}, n["service_date"],
                   f"Home address of {n['student_id']} included in a {n['notification_type']} message.")
            break
