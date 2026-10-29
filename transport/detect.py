"""Independent business-rule detector.

Runs on the exported CSVs only (never on ground truth) and reports every
violation of the acceptance rules. Comparing its findings with ground_truth.csv
gives precision / recall per anomaly type; on the clean baseline it must report
nothing.
"""
from . import config as C
from . import geo, rules


def detect(t):
    """t: dict table_name -> list[dict] (attendance not required)."""
    dates = [d["service_date"] for d in sorted(t["school_day"], key=lambda d: d["day_index"])]
    n = len(dates)
    students = {s["student_id"]: s for s in t["student"]}
    routes = {r["route_id"]: r for r in t["route"]}
    buses = {b["bus_id"]: b for b in t["bus"]}
    stops = {s["stop_id"]: s for s in t["stop"]}
    contacts = {c["contact_id"]: c for c in t["guardian_contact"]}
    cap = rules.CapacityBook(t["bus"], t["bus_capacity_event"])
    segments = rules.build_segments(t["assignment_event"], dates)
    asn_student = {a["assignment_id"]: a["student_id"] for a in t["assignment"]}
    findings = []

    # D1 capacity: daily active load vs effective seats (and wheelchair positions on accessible buses)
    load = {rid: [0] * (n + 1) for rid in routes}
    wc = {rid: [0] * (n + 1) for rid in routes}
    for asn, segs in segments.items():
        st = students[asn_student[asn]]
        for a, b, rid, stop, ev in segs:
            load[rid][a] += 1
            load[rid][b + 1] -= 1
            if st["mobility_aid"] == "wheelchair":
                wc[rid][a] += 1
                wc[rid][b + 1] -= 1
    for rid in sorted(routes):
        r = routes[rid]
        bus = buses[r["bus_id"]]
        cur = cur_wc = 0
        bad = []
        for i in range(n):
            cur += load[rid][i]
            cur_wc += wc[rid][i]
            seats = cap.capacity(bus["bus_id"], dates[i])
            if cur > seats or (bus["is_accessible"] and cur_wc > bus["wheelchair_positions"]):
                bad.append((dates[i], cur, seats))
        if bad:
            findings.append({"issue_type": "capacity_exceeded", "entity_table": "route", "entity_id": rid,
                             "first_date": bad[0][0],
                             "evidence": f"{len(bad)} service days over capacity; first {bad[0][0]} "
                                         f"load {bad[0][1]} > {bad[0][2]} seats on {bus['bus_id']}"})

    # D2 accessibility compatibility of every active segment
    for asn in sorted(segments):
        st = students[asn_student[asn]]
        if not st["requires_accessible_vehicle"]:
            continue
        for a, b, rid, stop, ev in segments[asn]:
            r = routes[rid]
            if r["service_type"] != "accessible" or not buses[r["bus_id"]]["is_accessible"]:
                findings.append({"issue_type": "incompatible_route", "entity_table": "assignment_event",
                                 "entity_id": ev, "first_date": dates[a],
                                 "evidence": f"{st['student_id']} ({st['mobility_aid']}) on {rid} "
                                             f"({r['service_type']}) {dates[a]}..{dates[b]}"})

    # D3 feasible travel times on every leg (and the final leg to school)
    for rs in sorted(t["route_stop"], key=lambda x: x["route_stop_id"]):
        if rs["stop_sequence"] == 1:
            continue
        km, mins = rs["leg_distance_km"], rs["leg_travel_min"]
        speed = geo.implied_speed_kmph(km, mins)
        if speed > C.MAX_FEASIBLE_SPEED_KMPH or (km > 0 and mins < C.MIN_LEG_MIN):
            findings.append({"issue_type": "impossible_travel_time", "entity_table": "route_stop",
                             "entity_id": rs["route_stop_id"], "first_date": rs["effective_from"],
                             "evidence": f"{km} km in {mins} min = {speed:.0f} km/h"})
    for r in routes.values():
        if geo.implied_speed_kmph(r["final_leg_distance_km"], r["final_leg_min"]) > C.MAX_FEASIBLE_SPEED_KMPH:
            findings.append({"issue_type": "impossible_travel_time", "entity_table": "route",
                             "entity_id": r["route_id"], "first_date": r["effective_from"],
                             "evidence": "final leg to school faster than feasible"})

    # D4 notification recipient validity
    for nrow in t["notification"]:
        if nrow["contact_id"] is None:
            continue
        c = contacts[nrow["contact_id"]]
        probs = rules.contact_problems(c, nrow["student_id"], nrow["service_date"], channel=nrow["channel"])
        if probs:
            findings.append({"issue_type": "notification_invalid_contact", "entity_table": "notification",
                             "entity_id": nrow["notification_id"], "first_date": nrow["service_date"],
                             "evidence": f"{c['contact_id']}: {', '.join(probs)}"})

    # D5 exposure of unapproved / residential locations
    for rs in t["route_stop"]:
        s = stops[rs["stop_id"]]
        if s["approval_status"] != "approved":
            findings.append({"issue_type": "unapproved_address_exposed", "entity_table": "route_stop",
                             "entity_id": rs["route_stop_id"], "first_date": rs["effective_from"],
                             "evidence": f"{s['stop_id']} is {s['approval_status']} on {rs['route_id']}"})
    for nrow in t["notification"]:
        if rules.ADDRESS_RE.search(nrow["message_preview"] or ""):
            findings.append({"issue_type": "unapproved_address_exposed", "entity_table": "notification",
                             "entity_id": nrow["notification_id"], "first_date": nrow["service_date"],
                             "evidence": "residential address text in message"})
    findings.sort(key=lambda f: (f["issue_type"], f["entity_id"]))
    return findings


def evaluate(findings, ground_truth):
    """Precision / recall of the detector against the labelled anomalies."""
    found = {(f["issue_type"], f["entity_id"]) for f in findings}
    truth = {(g["issue_type"], g["entity_id"]) for g in ground_truth}
    out = {}
    for it in C.ANOMALY_TYPES:
        f = {k for k in found if k[0] == it}
        g = {k for k in truth if k[0] == it}
        tp, fp, fn = len(f & g), len(f - g), len(g - f)
        out[it] = {"labelled": len(g), "detected": len(f), "true_positive": tp, "false_positive": fp,
                   "false_negative": fn,
                   "precision": round(tp / (tp + fp), 4) if tp + fp else 1.0,
                   "recall": round(tp / (tp + fn), 4) if tp + fn else 1.0}
    tp = sum(v["true_positive"] for v in out.values())
    fp = sum(v["false_positive"] for v in out.values())
    fn = sum(v["false_negative"] for v in out.values())
    out["overall"] = {"labelled": len(truth), "detected": len(found), "true_positive": tp,
                      "false_positive": fp, "false_negative": fn,
                      "precision": round(tp / (tp + fp), 4) if tp + fp else 1.0,
                      "recall": round(tp / (tp + fn), 4) if tp + fn else 1.0}
    return out
