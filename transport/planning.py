"""Step 3a: annual plan -> stop choice, route candidates, route selection,
initial assignment and pickup-window repair.

Decision order (each step is persisted so it can be audited):
 1. eligibility (walk zone, guardian opt-in, verified address)
 2. nearest usable stop within the student's walk limit (approved; accessible if needed)
 3. sweep stops by angle into routes per network (regular / accessible), respecting
    90% plan load, wheelchair positions and the 60-minute route limit
 4. for each route evaluate 3 stop orderings (route_candidate) and keep the fastest feasible
 5. shift each route's school arrival within 07:35-07:50 to satisfy most pickup windows,
    then move remaining window violators to an alternative compatible stop/route with a
    free seat; anyone left keeps the seat with a documented window exception
"""
import math

from . import config as C
from . import geo, ids, rules


def pt(stop):
    return (stop["x_km"], stop["y_km"])


class Plan:
    def __init__(self):
        self.routes = []              # route rows
        self.route_by_id = {}
        self.seq = {}                 # route_id -> [stop_id, ...] operative visiting order
        self.legs = {}                # route_id -> [(km, min) per stop], first = (0, 0)
        self.final = {}               # route_id -> (km, min)
        self.candidates = []
        self.cand_stops = {}          # student_id -> [(walk_m, stop_id)]
        self.initial = {}             # student_id -> (route_id, stop_id) assigned at plan
        self.moved_for_window = set()
        self.outcome = {}             # student_id -> (decision, reason) for not-assigned at plan
        self.route_stops = []
        self.rs_by_key = {}           # (route_id, stop_id) -> route_stop row
        self.stop_routes = {}         # stop_id -> [route_id]

    # -------------------------------------------------- timing
    def timing(self, rid):
        """Per-stop cumulative minutes and arrival clock minute (float)."""
        r = self.route_by_id[rid]
        dwell = C.DWELL_MIN[r["service_type"]]
        cum, out, prev_dwell = 0.0, {}, 0.0
        for i, (sid, (km, mins)) in enumerate(zip(self.seq[rid], self.legs[rid])):
            if i > 0:
                cum = round(cum + prev_dwell + mins, 1)
            out[sid] = cum
            prev_dwell = dwell
        total = round(cum + dwell + self.final[rid][1], 1)
        departure = r["_arrival_min"] - total
        return {sid: (c, departure + c) for sid, c in out.items()}, total, departure

    def pickup_min(self, rid, stop_id):
        t, _, _ = self.timing(rid)
        return int(round(t[stop_id][1]))


# ------------------------------------------------------------------ geometry of a sequence
def evaluate(seq, stop_by_id, dwell):
    legs = [(0.0, 0.0)]
    for a, b in zip(seq, seq[1:]):
        pa, pb = pt(stop_by_id[a]), pt(stop_by_id[b])
        legs.append((geo.road_km(pa, pb), geo.travel_min(pa, pb)))
    last = pt(stop_by_id[seq[-1]])
    final = (geo.road_km(last, C.SCHOOL_XY), geo.travel_min(last, C.SCHOOL_XY))
    total = round(sum(m for _, m in legs) + dwell * len(seq) + final[1], 1)
    dist = round(sum(k for k, _ in legs) + final[0], 3)
    speeds = [geo.implied_speed_kmph(k, m) for k, m in legs[1:] + [final]]
    return {"legs": legs, "final": final, "total": total, "distance": dist,
            "max_speed": round(max(speeds) if speeds else 0.0, 1)}


def order_radial(stop_ids, stop_by_id):
    return sorted(stop_ids, key=lambda s: (-geo.radius(pt(stop_by_id[s])), s))


def order_nearest(stop_ids, stop_by_id):
    remaining = order_radial(stop_ids, stop_by_id)
    seq = [remaining.pop(0)]
    while remaining:
        cur = pt(stop_by_id[seq[-1]])
        nxt = min(remaining, key=lambda s: (geo.straight_km(cur, pt(stop_by_id[s])), s))
        remaining.remove(nxt)
        seq.append(nxt)
    return seq


def two_opt(seq, stop_by_id, dwell):
    best = list(seq)
    best_t = evaluate(best, stop_by_id, dwell)["total"]
    improved = True
    while improved:
        improved = False
        for i in range(len(best) - 1):
            for j in range(i + 1, len(best)):
                cand = best[:i] + best[i:j + 1][::-1] + best[j + 1:]
                t = evaluate(cand, stop_by_id, dwell)["total"]
                if t < best_t - 1e-9:
                    best, best_t, improved = cand, t, True
    return best


# ------------------------------------------------------------------ main entry
def build_plan(students, stops, buses, drivers, days, rng):
    plan = Plan()
    stop_by_id = {s["stop_id"]: s for s in stops}
    plan.stop_by_id = stop_by_id
    first_day, last_day = days[0]["service_date"], days[-1]["service_date"]

    # 1-2. eligibility + nearest usable stop (persisted for later decisions)
    approved = [s for s in stops if s["approval_status"] == "approved"]
    demand = {"regular": {}, "accessible": {}}
    for st in students:
        home = (st["home_x_km"], st["home_y_km"])
        cands = []
        for s in approved:
            if rules.stop_usable(s, st):
                w = geo.walk_m(home, pt(s))
                if w <= st["max_walk_m"]:
                    cands.append((w, s["stop_id"]))
        cands.sort()
        plan.cand_stops[st["student_id"]] = cands
        if st["enrolled_on"] >= first_day:        # mid-year joiners are decided on enrollment
            continue
        pre = rules.pre_assignment_outcome(st)
        if pre:
            plan.outcome[st["student_id"]] = pre
            continue
        if not cands:
            plan.outcome[st["student_id"]] = ("waitlisted", "WAITLIST_NO_ACCESSIBLE_STOP"
                                              if st["requires_accessible_vehicle"] else "WAITLIST_NO_STOP_IN_RANGE")
            continue
        demand[rules.network_for(st)].setdefault(cands[0][1], []).append(st["student_id"])

    # 3. sweep construction per network
    student_by_id = {s["student_id"]: s for s in students}
    built = []
    for network in ("regular", "accessible"):
        pool = sorted([b for b in buses if b["fleet_role"] == "route" and b["status"] == "in_service"
                       and b["is_accessible"] == (network == "accessible")],
                      key=lambda b: (-b["base_seated_capacity"], b["bus_id"]))
        built += sweep(network, demand[network], pool, stop_by_id, student_by_id, plan)

    # 4. candidates + selection; ids are assigned in sweep order
    drivers_active = [d for d in drivers if d["employment_status"] == "active"]
    trained = [d for d in drivers_active if d["accessible_trained"]]
    untrained = [d for d in drivers_active if not d["accessible_trained"]]
    cand_n = 0
    for n, r in enumerate(built, start=1):
        rid = ids.route(n)
        dwell = C.DWELL_MIN[r["network"]]
        stop_ids = list(r["members"])
        radial = order_radial(stop_ids, stop_by_id)
        nearest = order_nearest(stop_ids, stop_by_id)
        base = min((radial, nearest), key=lambda s: evaluate(s, stop_by_id, dwell)["total"])
        orders = [("radial_inbound", radial), ("nearest_neighbor", nearest),
                  ("two_opt", two_opt(base, stop_by_id, dwell))]
        evals = []
        for method, seq in orders:
            ev = evaluate(seq, stop_by_id, dwell)
            ev["feasible"] = ev["total"] <= C.MAX_ROUTE_MIN and ev["max_speed"] <= C.MAX_FEASIBLE_SPEED_KMPH
            evals.append((method, seq, ev))
        ranked = sorted(range(3), key=lambda i: (not evals[i][2]["feasible"], evals[i][2]["total"], i))
        chosen = ranked[0]
        rows = []
        for rank, i in enumerate(ranked, start=1):
            method, seq, ev = evals[i]
            cand_n += 1
            reason = None
            if not ev["feasible"]:
                reason = f"route duration {ev['total']} min exceeds {C.MAX_ROUTE_MIN:.0f}"
            elif i != chosen:
                gap = round(ev["total"] - evals[chosen][2]["total"], 1)
                reason = "same duration as selected candidate" if gap == 0 else f"{gap} min slower than selected"
            rows.append({
                "candidate_id": ids.candidate(cand_n), "route_id": rid, "method": method,
                "stop_sequence": "|".join(seq), "total_distance_km": ev["distance"],
                "total_travel_min": ev["total"], "max_leg_speed_kmph": ev["max_speed"],
                "feasible": ev["feasible"], "rejection_reason": reason, "rank": rank,
                "selected": i == chosen,
            })
        rows.sort(key=lambda x: x["candidate_id"])
        plan.candidates += rows
        sel = next(x for x in rows if x["selected"])
        method, seq, ev = evals[chosen]
        driver = (trained if r["network"] == "accessible" else untrained or trained).pop(0)
        route = {
            "route_id": rid, "route_name": f"{'ACC' if r['network'] == 'accessible' else 'AM'}-{n:03d}",
            "school_year": C.SCHOOL_YEAR, "session": "AM", "service_type": r["network"],
            "bus_id": r["bus"]["bus_id"], "driver_id": driver["driver_id"],
            "selected_candidate_id": sel["candidate_id"], "status": "active",
            "effective_from": first_day, "effective_to": last_day,
            "capacity_at_plan": r["bus"]["base_seated_capacity"], "_arrival_min": C.TARGET_ARRIVAL_MIN,
        }
        plan.routes.append(route)
        plan.route_by_id[rid] = route
        plan.seq[rid] = list(seq)
        plan.legs[rid] = list(ev["legs"])
        plan.final[rid] = ev["final"]
        for stop_id, sids in r["members"].items():
            for sid in sids:
                plan.initial[sid] = (rid, stop_id)
    rebuild_stop_index(plan)

    # 5. pickup-window repair
    repair_windows(plan, student_by_id, buses)
    return plan


def rebuild_stop_index(plan):
    plan.stop_routes = {}
    for r in plan.routes:
        for s in plan.seq[r["route_id"]]:
            plan.stop_routes.setdefault(s, []).append(r["route_id"])


def sweep(network, demand, pool, stop_by_id, student_by_id, plan):
    """Angle sweep from the school; returns route drafts {'bus', 'network', 'members'}."""
    dwell = C.DWELL_MIN[network]
    order = sorted(demand, key=lambda s: (math.atan2(stop_by_id[s]["y_km"], stop_by_id[s]["x_km"]),
                                          geo.radius(pt(stop_by_id[s])), s))
    pool = list(pool)
    routes, cur = [], None

    def open_route():
        if not pool:
            return None
        return {"bus": pool.pop(0), "network": network, "members": {}, "load": 0, "wc": 0}

    for stop_id in order:
        queue = sorted(demand[stop_id])
        while queue:
            if cur is None:
                cur = open_route()
                if cur is None:
                    for sid in queue:
                        plan.outcome[sid] = ("waitlisted", "WAITLIST_NO_CAPACITY")
                    queue = []
                    break
            limit = int(cur["bus"]["base_seated_capacity"] * C.PLAN_LOAD_FACTOR)
            if stop_id not in cur["members"] and cur["members"]:
                trial = order_radial(list(cur["members"]) + [stop_id], stop_by_id)
                if evaluate(trial, stop_by_id, dwell)["total"] > C.MAX_ROUTE_MIN:
                    routes.append(cur)
                    cur = None
                    continue
            take = []
            for sid in queue:
                if cur["load"] + len(take) >= limit:
                    break
                if student_by_id[sid]["mobility_aid"] == "wheelchair":
                    if cur["wc"] >= cur["bus"]["wheelchair_positions"]:
                        continue
                    cur["wc"] += 1
                take.append(sid)
            if not take:
                routes.append(cur)
                cur = None
                continue
            cur["members"].setdefault(stop_id, []).extend(take)
            cur["load"] += len(take)
            taken = set(take)
            queue = [s for s in queue if s not in taken]
            if queue:
                routes.append(cur)
                cur = None
    if cur is not None and cur["members"]:
        routes.append(cur)
    return routes


def repair_windows(plan, student_by_id, buses):
    cap = {b["bus_id"]: b["base_seated_capacity"] for b in buses}
    members = {}
    for sid, (rid, stop) in sorted(plan.initial.items()):
        members.setdefault(rid, []).append(sid)
    # (a) shift each route's arrival to satisfy the most windows (prefer smallest shift)
    for r in plan.routes:
        rid = r["route_id"]
        t, _, _ = plan.timing(rid)
        best = None
        for s in range(C.ARRIVAL_SHIFT_RANGE[0], C.ARRIVAL_SHIFT_RANGE[1] + 1):
            ok = sum(1 for sid in members.get(rid, [])
                     if rules.window_ok(student_by_id[sid], int(round(t[plan.initial[sid][1]][1] + s))))
            key = (-ok, abs(s), s)
            if best is None or key < best[0]:
                best = (key, s)
        r["_arrival_min"] = C.TARGET_ARRIVAL_MIN + best[1]
    # (b) move remaining violators to a compatible alternative with a free seat
    load = {rid: len(v) for rid, v in members.items()}
    for sid in sorted(plan.initial):
        st = student_by_id[sid]
        rid, stop = plan.initial[sid]
        if rules.window_ok(st, plan.pickup_min(rid, stop)):
            continue
        net = rules.network_for(st)
        for walk, alt_stop in plan.cand_stops[sid]:
            done = False
            for alt_rid in plan.stop_routes.get(alt_stop, []):
                ar = plan.route_by_id[alt_rid]
                if (alt_rid, alt_stop) == (rid, stop) or ar["service_type"] != net:
                    continue
                if load.get(alt_rid, 0) >= cap[ar["bus_id"]]:
                    continue
                if st["mobility_aid"] == "wheelchair":
                    continue  # wheelchair positions were packed by the sweep; keep them stable
                if rules.window_ok(st, plan.pickup_min(alt_rid, alt_stop)):
                    load[rid] -= 1
                    load[alt_rid] = load.get(alt_rid, 0) + 1
                    plan.initial[sid] = (alt_rid, alt_stop)
                    plan.moved_for_window.add(sid)
                    done = True
                    break
            if done:
                break


# ------------------------------------------------------------------ derived route tables
def derive_routes(plan, membership_at_plan, effective_from, effective_to):
    """(Re)compute every derived route/route_stop field from legs and membership.

    Called after planning and again after any plan edit, so derived values always
    reconcile with their sources."""
    boarding = {}
    for sid, (rid, stop) in membership_at_plan.items():
        boarding[(rid, stop)] = boarding.get((rid, stop), 0) + 1
    plan.route_stops, plan.rs_by_key = [], {}
    n = 0
    for r in plan.routes:
        rid = r["route_id"]
        t, total, departure = plan.timing(rid)
        dwell = C.DWELL_MIN[r["service_type"]]
        for i, (stop, (km, mins)) in enumerate(zip(plan.seq[rid], plan.legs[rid]), start=1):
            n += 1
            row = {
                "route_stop_id": ids.route_stop(n), "route_id": rid, "stop_id": stop,
                "stop_sequence": i, "leg_distance_km": km, "leg_travel_min": mins, "dwell_min": dwell,
                "cumulative_min": t[stop][0], "planned_arrival_time": geo.hhmm(t[stop][1]),
                "boarding_planned": boarding.get((rid, stop), 0),
                "effective_from": effective_from, "effective_to": effective_to,
            }
            plan.route_stops.append(row)
            plan.rs_by_key[(rid, stop)] = row
        load = sum(boarding.get((rid, s), 0) for s in plan.seq[rid])
        r.update({
            "stop_count": len(plan.seq[rid]),
            "final_leg_distance_km": plan.final[rid][0], "final_leg_min": plan.final[rid][1],
            "total_distance_km": round(sum(k for k, _ in plan.legs[rid]) + plan.final[rid][0], 3),
            "total_travel_min": total, "departure_time": geo.hhmm(departure),
            "school_arrival_time": geo.hhmm(r["_arrival_min"]),
            "planned_load": load,
            "utilization_pct": round(100.0 * load / r["capacity_at_plan"], 1),
        })
    rebuild_stop_index(plan)
