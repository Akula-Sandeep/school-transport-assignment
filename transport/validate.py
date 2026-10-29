"""Step 8: integrity validation of an exported dataset (reads the CSVs back).

Categories: schema (types, required, enums, patterns, unique), keys (PK, FK),
dates (ordering, effective dating), arithmetic (derived values reconcile),
lifecycle (event transitions, attendance reflects assignment history),
operations (attendance/notification consistency), privacy (synthetic, minimised
contact data) and ground-truth separation.

These checks must all PASS, including on data with injected anomalies: anomalies
are *business-rule* violations (found by detect.py), not broken records.
"""
import os
import re
from collections import Counter, defaultdict

from . import config as C
from . import geo, rules
from .schema import TABLES, TABLE_BY_NAME
from .storage import iter_rows, load_table

TOL = 0.051


class Checks:
    def __init__(self):
        self.results = []
        self._open = {}

    def check(self, name, category, checked, violations):
        violations = list(violations)
        self.results.append({"check": name, "category": category, "status": "PASS" if not violations else "FAIL",
                             "records_checked": checked, "violations": len(violations),
                             "examples": [str(v) for v in violations[:5]]})

    @property
    def passed(self):
        return all(r["status"] == "PASS" for r in self.results)


def generic_row_checks(table, row, viol, compiled):
    for f in table.fields:
        v = row.get(f.name)
        if v is None:
            if f.required:
                viol["required"].append(f"{table.name}.{f.name} null in {row.get(table.pk)}")
            continue
        if f.allowed is not None and v not in f.allowed:
            viol["enum"].append(f"{table.name}.{f.name}={v!r}")
        pat = compiled.get((table.name, f.name))
        if pat is not None and not pat.match(str(v)):
            viol["pattern"].append(f"{table.name}.{f.name}={v!r}")


def validate(out_dir):
    csv_dir = os.path.join(out_dir, "data", "csv")
    ck = Checks()
    parse_errors = []
    big = {"attendance_event"}
    t = {tb.name: load_table(csv_dir, tb.name, parse_errors) for tb in TABLES if tb.name not in big}
    compiled = {(tb.name, f.name): re.compile(f.pattern) for tb in TABLES for f in tb.fields if f.pattern}
    ck.check("csv_header_and_types", "schema", sum(len(v) for v in t.values()), parse_errors)

    # ---------------------------------------------------------- schema + keys (small tables)
    keysets = {tb.name: set() for tb in TABLES}
    viol = defaultdict(list)
    dup = []
    uniq_viol = []
    for tb in TABLES:
        if tb.name in big:
            continue
        seen_unique = defaultdict(set)
        for row in t[tb.name]:
            generic_row_checks(tb, row, viol, compiled)
            pk = row[tb.pk]
            if pk in keysets[tb.name]:
                dup.append(f"{tb.name}:{pk}")
            keysets[tb.name].add(pk)
            for f in tb.fields:
                if f.unique and f.name != tb.pk and row.get(f.name) is not None:
                    if row[f.name] in seen_unique[f.name]:
                        uniq_viol.append(f"{tb.name}.{f.name}={row[f.name]}")
                    seen_unique[f.name].add(row[f.name])
    n_small = sum(len(t[k]) for k in t)
    ck.check("unique_constraints", "keys", n_small, uniq_viol)
    fk_viol = []
    for tb in TABLES:
        if tb.name in big:
            continue
        for f in tb.fields:
            if f.fk:
                rt, _ = f.fk.split(".")
                for row in t[tb.name]:
                    v = row.get(f.name)
                    if v is not None and v not in keysets[rt]:
                        fk_viol.append(f"{tb.name}.{f.name}={v}")

    # lookups
    dates = [d["service_date"] for d in sorted(t["school_day"], key=lambda d: d["day_index"])]
    date_idx = {d: i for i, d in enumerate(dates)}
    students = {s["student_id"]: s for s in t["student"]}
    zones = {z["zone_id"]: z for z in t["address_zone"]}
    stops = {s["stop_id"]: s for s in t["stop"]}
    buses = {b["bus_id"]: b for b in t["bus"]}
    drivers = {d["driver_id"]: d for d in t["driver"]}
    routes = {r["route_id"]: r for r in t["route"]}
    contacts = {c["contact_id"]: c for c in t["guardian_contact"]}
    rs_by_route = defaultdict(list)
    for rs in t["route_stop"]:
        rs_by_route[rs["route_id"]].append(rs)
    for v in rs_by_route.values():
        v.sort(key=lambda x: x["stop_sequence"])
    rs_by_id = {rs["route_stop_id"]: rs for rs in t["route_stop"]}
    rs_by_key = {(rs["route_id"], rs["stop_id"]): rs for rs in t["route_stop"]}
    events_by_asn = defaultdict(list)
    for e in t["assignment_event"]:
        events_by_asn[e["assignment_id"]].append(e)
    for v in events_by_asn.values():
        v.sort(key=lambda e: e["event_seq"])
    first, last = dates[0], dates[-1]

    # ---------------------------------------------------------- dates
    dv = []
    for i, d in enumerate(sorted(t["school_day"], key=lambda d: d["day_index"])):
        wd = geo.d(d["service_date"]).weekday()
        if (d["day_index"] != i + 1 or (i and d["service_date"] <= dates[i - 1]) or wd > 4
                or C.WEEKDAYS[wd] != d["weekday"] or d["service_date"] in C.HOLIDAYS):
            dv.append(f"school_day {d['service_date']}")
    for s in t["stop"]:
        if s["effective_to"] and s["effective_to"] < s["effective_from"]:
            dv.append(f"stop {s['stop_id']} effective range")
        if (s["approval_status"] == "pending") != (s["approval_date"] is None):
            dv.append(f"stop {s['stop_id']} approval_date vs status")
    for s in t["student"]:
        if (s["enrollment_status"] == "withdrawn") != (s["withdrawn_on"] is not None):
            dv.append(f"student {s['student_id']} withdrawn_on vs status")
        if s["withdrawn_on"] and s["withdrawn_on"] <= s["enrolled_on"]:
            dv.append(f"student {s['student_id']} withdrawn before enrolled")
    for c in t["guardian_contact"]:
        if c["valid_to"] and c["valid_to"] < c["valid_from"]:
            dv.append(f"contact {c['contact_id']} validity")
        if c["superseded_by"]:
            n = contacts[c["superseded_by"]]
            if n["student_id"] != c["student_id"] or n["valid_from"] != geo.add_days(c["valid_to"], 1):
                dv.append(f"contact {c['contact_id']} supersession chain")
    for e in t["bus_capacity_event"]:
        if e["effective_to"] and e["effective_to"] < e["effective_from"]:
            dv.append(f"capacity event {e['capacity_event_id']}")
    for r in t["route"]:
        if not (r["effective_from"] == first and r["effective_to"] == last):
            dv.append(f"route {r['route_id']} effective range")
    for d in t["driver"]:
        if d["license_expiry"] <= last:
            dv.append(f"driver {d['driver_id']} licence expires in-year")
    for nrow in t["notification"]:
        if nrow["sent_at"][:10] < nrow["service_date"] and nrow["service_date"] > C.PLANNING_DATE:
            dv.append(f"notification {nrow['notification_id']} sent before its date")
    ck.check("date_ordering_and_effective_dating", "dates", n_small, dv)

    # ---------------------------------------------------------- arithmetic / derived values
    av = []
    for sid, s in students.items():
        z = zones[s["home_zone_id"]]
        dist = round(geo.radius((s["home_x_km"], s["home_y_km"])), 2)
        if abs(dist - s["distance_to_school_km"]) > 0.011:
            av.append(f"{sid} distance_to_school")
        if s["transport_eligible"] != (s["distance_to_school_km"] >= C.WALK_ZONE_KM):
            av.append(f"{sid} transport_eligible")
        if s["requires_accessible_vehicle"] != (s["mobility_aid"] != "none"):
            av.append(f"{sid} requires_accessible_vehicle")
        cap = min(z["max_walk_m"], C.GRADE_WALK_CAP_M.get(s["grade"], C.DEFAULT_GRADE_WALK_CAP_M),
                  C.MOBILITY_WALK_CAP_M.get(s["mobility_aid"], 10 ** 6))
        if cap != s["max_walk_m"]:
            av.append(f"{sid} max_walk_m")
        if geo.to_min(s["pickup_window_end"]) - geo.to_min(s["pickup_window_start"]) < 15:
            av.append(f"{sid} window too narrow")
    for b in t["bus"]:
        if b["is_accessible"] != (b["wheelchair_positions"] > 0) or b["is_accessible"] != (b["bus_type"] == "accessible"):
            av.append(f"{b['bus_id']} accessibility fields")
    plan_members = Counter()
    for asn, evs in events_by_asn.items():
        e = evs[0]
        if e["event_type"] == "ASSIGNED" and e["event_date"] == C.PLANNING_DATE:
            plan_members[(e["route_id"], e["stop_id"])] += 1
    for rid, r in routes.items():
        lst = rs_by_route[rid]
        if [x["stop_sequence"] for x in lst] != list(range(1, len(lst) + 1)):
            av.append(f"{rid} stop_sequence not contiguous")
        cum, prev_dwell = 0.0, 0.0
        for i, x in enumerate(lst):
            if i:
                cum = round(cum + prev_dwell + x["leg_travel_min"], 1)
            elif x["leg_distance_km"] != 0 or x["leg_travel_min"] != 0:
                av.append(f"{x['route_stop_id']} first leg not zero")
            prev_dwell = x["dwell_min"]
            if abs(cum - x["cumulative_min"]) > TOL:
                av.append(f"{x['route_stop_id']} cumulative_min")
            if abs(geo.to_min(x["planned_arrival_time"]) - (geo.to_min(r["departure_time"]) + cum)) > 1.01:
                av.append(f"{x['route_stop_id']} planned_arrival_time")
            if x["boarding_planned"] != plan_members[(rid, x["stop_id"])]:
                av.append(f"{x['route_stop_id']} boarding_planned")
            if x["dwell_min"] != C.DWELL_MIN[r["service_type"]]:
                av.append(f"{x['route_stop_id']} dwell")
        total = round(cum + lst[-1]["dwell_min"] + r["final_leg_min"], 1)
        if r["stop_count"] != len(lst):
            av.append(f"{rid} stop_count")
        if abs(total - r["total_travel_min"]) > TOL:
            av.append(f"{rid} total_travel_min {total} vs {r['total_travel_min']}")
        dist = round(sum(x["leg_distance_km"] for x in lst) + r["final_leg_distance_km"], 3)
        if abs(dist - r["total_distance_km"]) > 0.002:
            av.append(f"{rid} total_distance_km")
        if abs(geo.to_min(r["school_arrival_time"]) - geo.to_min(r["departure_time"]) - r["total_travel_min"]) > 1.01:
            av.append(f"{rid} departure/arrival vs total")
        if r["planned_load"] != sum(x["boarding_planned"] for x in lst):
            av.append(f"{rid} planned_load")
        if r["capacity_at_plan"] != buses[r["bus_id"]]["base_seated_capacity"]:
            av.append(f"{rid} capacity_at_plan")
        if abs(r["utilization_pct"] - round(100.0 * r["planned_load"] / r["capacity_at_plan"], 1)) > 0.051:
            av.append(f"{rid} utilization_pct")
    ck.check("derived_values_reconcile", "arithmetic", len(students) + len(routes) + len(t["route_stop"]), av)

    # ---------------------------------------------------------- route / candidate structure
    sv = []
    by_route_cand = defaultdict(list)
    for c in t["route_candidate"]:
        by_route_cand[c["route_id"]].append(c)
        for s in c["stop_sequence"].split("|"):
            if s not in stops:
                sv.append(f"{c['candidate_id']} unknown stop {s}")
    for rid, r in routes.items():
        sel = [c for c in by_route_cand[rid] if c["selected"]]
        if len(sel) != 1 or sel[0]["candidate_id"] != r["selected_candidate_id"] or sel[0]["rank"] != 1:
            sv.append(f"{rid} selected candidate")
        if not rs_by_route[rid]:
            sv.append(f"{rid} has no stops")
        bus, drv = buses[r["bus_id"]], drivers[r["driver_id"]]
        if r["service_type"] == "accessible" and not (bus["is_accessible"] and drv["accessible_trained"]):
            sv.append(f"{rid} accessible route without accessible bus/trained driver")
        if drv["employment_status"] != "active" or bus["fleet_role"] != "route":
            sv.append(f"{rid} rostered inactive driver or spare bus")
    if len(rs_by_key) != len(t["route_stop"]):
        sv.append("duplicate (route_id, stop_id) in route_stop")
    ck.check("route_structure_and_candidates", "keys", len(routes) + len(t["route_candidate"]), sv)

    # ---------------------------------------------------------- assignment lifecycle
    lv = []
    for a in t["assignment"]:
        asn, sid = a["assignment_id"], a["student_id"]
        s = students[sid]
        if asn != f"ASN-{sid}-{a['school_year']}":
            lv.append(f"{asn} id convention")
        evs = events_by_asn.get(asn, [])
        if not evs:
            lv.append(f"{asn} has no events")
            continue
        if [e["event_seq"] for e in evs] != list(range(1, len(evs) + 1)):
            lv.append(f"{asn} event_seq")
        prev = None
        for e in evs:
            if e["event_type"] not in rules.ALLOWED_TRANSITIONS[prev]:
                lv.append(f"{e['event_id']} illegal {prev}->{e['event_type']}")
            prev = e["event_type"]
            if e["student_id"] != sid:
                lv.append(f"{e['event_id']} student mismatch")
            active = e["event_type"] in rules.ACTIVE_EVENTS
            if active != (e["route_id"] is not None):
                lv.append(f"{e['event_id']} route presence")
            if active:
                rs = rs_by_id.get(e["route_stop_id"])
                if rs is None or (rs["route_id"], rs["stop_id"]) != (e["route_id"], e["stop_id"]):
                    lv.append(f"{e['event_id']} route_stop mismatch")
        if [e["event_date"] for e in evs] != sorted(e["event_date"] for e in evs):
            lv.append(f"{asn} event dates not ordered")
        if evs[0]["event_type"] != a["decision"].upper():
            lv.append(f"{asn} first event vs decision")
        if evs[0]["reason_code"] != a["decision_reason"] or evs[0]["event_date"] != a["decided_on"]:
            lv.append(f"{asn} first event reason/date")
        if rules.final_status(evs) != a["current_status"]:
            lv.append(f"{asn} current_status")
        if s["withdrawn_on"] and (evs[-1]["event_type"] != "ENDED" or evs[-1]["event_date"] != s["withdrawn_on"]):
            lv.append(f"{asn} withdrawal not ended")
        pre = rules.pre_assignment_outcome(s)
        if pre and pre[0] in ("ineligible", "opted_out") and a["decision"] != pre[0]:
            lv.append(f"{asn} eligibility decision")
        if a["decided_on"] != (C.PLANNING_DATE if s["enrolled_on"] < first else s["enrolled_on"]):
            lv.append(f"{asn} decided_on vs enrollment")
        if a["decision"] == "assigned":
            rs = rs_by_id[a["route_stop_id"]]
            r = routes[a["route_id"]]
            if (rs["route_id"], rs["stop_id"]) != (a["route_id"], a["stop_id"]):
                lv.append(f"{asn} route_stop mismatch")
            if a["scheduled_pickup_time"] != rs["planned_arrival_time"]:
                lv.append(f"{asn} pickup time")
            pick = geo.to_min(a["scheduled_pickup_time"])
            if a["ride_time_min"] != geo.to_min(r["school_arrival_time"]) - pick:
                lv.append(f"{asn} ride_time")
            if a["window_ok"] != rules.window_ok(s, pick):
                lv.append(f"{asn} window_ok")
            st = stops[a["stop_id"]]
            if a["walk_distance_m"] != geo.walk_m((s["home_x_km"], s["home_y_km"]), (st["x_km"], st["y_km"])):
                lv.append(f"{asn} walk distance")
        elif a["route_id"] is not None:
            lv.append(f"{asn} non-assigned decision with route")
    for asn in events_by_asn:
        if asn not in keysets["assignment"]:
            lv.append(f"orphan events {asn}")
    ck.check("assignment_lifecycle_transitions", "lifecycle", len(t["assignment_event"]), lv)

    # ---------------------------------------------------------- disruptions
    xv = []
    seen = set()
    for d in t["route_disruption"]:
        k = (d["route_id"], d["service_date"])
        if k in seen:
            xv.append(f"duplicate disruption {k}")
        seen.add(k)
        if d["service_cancelled"] != (d["resolution"] == "cancelled") or (d["service_cancelled"] and d["delay_min"]):
            xv.append(f"{d['disruption_id']} cancellation fields")
        if d["replacement_bus_id"]:
            rb, rr = buses[d["replacement_bus_id"]], routes[d["route_id"]]
            if rb["fleet_role"] != "spare" or rb["is_accessible"] != (rr["service_type"] == "accessible"):
                xv.append(f"{d['disruption_id']} replacement bus not a compatible spare")
        if (d["resolution"] == "replacement_bus") != (d["replacement_bus_id"] is not None):
            xv.append(f"{d['disruption_id']} replacement bus vs resolution")
        if (d["resolution"] == "spare_driver") != (d["replacement_driver_id"] is not None):
            xv.append(f"{d['disruption_id']} spare driver vs resolution")
        if not 1 <= d["from_stop_sequence"] <= routes[d["route_id"]]["stop_count"]:
            xv.append(f"{d['disruption_id']} from_stop_sequence")
    ck.check("disruption_consistency", "operations", len(t["route_disruption"]), xv)
    dis_by_id = {d["disruption_id"]: d for d in t["route_disruption"]}

    # ---------------------------------------------------------- attendance (streamed)
    segments = rules.build_segments(t["assignment_event"], dates)
    notif_triggers = Counter((n["trigger_entity"], n["trigger_id"], n["notification_type"], n["student_id"])
                             for n in t["notification"])
    att_trig = Counter(n["trigger_id"] for n in t["notification"] if n["trigger_entity"] == "attendance_event")
    att_tb = TABLE_BY_NAME["attendance_event"]
    av2 = defaultdict(list)
    att_ids = set()
    per_asn = Counter()
    student_day = set()
    status_counts = Counter()
    n_att = 0
    for row in iter_rows(csv_dir, "attendance_event", parse_errors):
        n_att += 1
        generic_row_checks(att_tb, row, viol, compiled)
        aid = row["attendance_id"]
        if aid in att_ids:
            dup.append(f"attendance_event:{aid}")
        att_ids.add(aid)
        for f in att_tb.fields:
            if f.fk and row[f.name] is not None:
                rt = f.fk.split(".")[0]
                ref = keysets[rt] if rt != "school_day" else date_idx
                if row[f.name] not in ref:
                    fk_viol.append(f"attendance_event.{f.name}={row[f.name]}")
        key = (row["student_id"], row["service_date"])
        if key in student_day:
            av2["duplicate"].append(key)
        student_day.add(key)
        idx = date_idx.get(row["service_date"])
        seg = next((sg for sg in segments.get(row["assignment_id"], []) if idx is not None and sg[0] <= idx <= sg[1]), None)
        if seg is None or (seg[2], seg[3]) != (row["route_id"], row["stop_id"]):
            av2["not_in_active_assignment"].append(aid)
        per_asn[row["assignment_id"]] += 1
        s = students[row["student_id"]]
        if not (s["enrolled_on"] <= row["service_date"] and (s["withdrawn_on"] is None or row["service_date"] < s["withdrawn_on"])):
            av2["outside_enrollment"].append(aid)
        rs = rs_by_key.get((row["route_id"], row["stop_id"]))
        if rs is None or rs["planned_arrival_time"] != row["scheduled_pickup_time"]:
            av2["scheduled_time"].append(aid)
        st = row["attendance_status"]
        status_counts[st] += 1
        dis = dis_by_id.get(row["disruption_id"]) if row["disruption_id"] else None
        if dis and (dis["route_id"], dis["service_date"]) != (row["route_id"], row["service_date"]):
            av2["disruption_mismatch"].append(aid)
        cancelled = bool(dis and dis["service_cancelled"])
        arr = row["bus_arrival_time"]
        if (arr is None) != (st == "absent_reported" or cancelled):
            av2["arrival_presence"].append(aid)
        if arr is not None:
            delay = geo.to_min(arr) - geo.to_min(row["scheduled_pickup_time"])
            if delay != row["delay_min"] or delay < 0:
                av2["delay_arithmetic"].append(aid)
            expect = ("missed_pickup" if delay > C.MAX_WAIT_MIN else
                      None if st == "no_show" else
                      "boarded_late" if delay > C.LATE_THRESHOLD_MIN else "boarded")
            if expect is not None and st != expect:
                av2["status_rule"].append(f"{aid} {st} vs {expect}")
        elif st not in ("absent_reported", "missed_pickup"):
            av2["status_rule"].append(aid)
        want = 1 if st in ("no_show", "missed_pickup") else 0
        if att_trig.get(aid, 0) != want:
            av2["notification_reconciliation"].append(f"{aid} {st} has {att_trig.get(aid, 0)} notices")
    expected_days = Counter({asn: sum(b - a + 1 for a, b, *_ in segs) for asn, segs in segments.items()})
    for asn in set(expected_days) | set(per_asn):
        if expected_days.get(asn, 0) != per_asn.get(asn, 0):
            av2["daily_coverage"].append(f"{asn} expected {expected_days.get(asn, 0)} got {per_asn.get(asn, 0)}")
    ck.check("attendance_one_per_student_day", "lifecycle", n_att, av2["duplicate"])
    ck.check("attendance_reflects_assignment_history", "lifecycle", n_att,
             av2["not_in_active_assignment"] + av2["daily_coverage"] + av2["outside_enrollment"])
    ck.check("attendance_derived_fields", "arithmetic", n_att,
             av2["scheduled_time"] + av2["delay_arithmetic"] + av2["arrival_presence"] + av2["disruption_mismatch"])
    ck.check("attendance_status_rules", "operations", n_att, av2["status_rule"])
    ck.check("notification_per_exception_event", "operations", n_att, av2["notification_reconciliation"])

    # ---------------------------------------------------------- notifications
    nv = []
    trig_tables = {"assignment_event": keysets["assignment_event"], "route_disruption": keysets["route_disruption"],
                   "attendance_event": att_ids}
    for nrow in t["notification"]:
        if nrow["trigger_id"] not in trig_tables[nrow["trigger_entity"]]:
            nv.append(f"{nrow['notification_id']} trigger missing")
        if (nrow["contact_id"] is None) != (nrow["delivery_status"] == "suppressed"):
            nv.append(f"{nrow['notification_id']} suppression vs contact")
        if (nrow["contact_id"] is None) != (nrow["channel"] is None):
            nv.append(f"{nrow['notification_id']} channel presence")
    dups = [k for k, v in notif_triggers.items() if v > 1]
    nv += [f"duplicate notice {k}" for k in dups[:5]]
    ck.check("notification_triggers_and_delivery", "operations", len(t["notification"]), nv)

    # ---------------------------------------------------------- generic results incl. attendance
    ck.check("required_fields_present", "schema", n_small + n_att, viol["required"])
    ck.check("enum_values_allowed", "schema", n_small + n_att, viol["enum"])
    ck.check("id_and_format_patterns", "schema", n_small + n_att, viol["pattern"])
    ck.check("foreign_key_integrity", "keys", n_small + n_att, fk_viol)
    ck.check("primary_key_unique", "keys", n_small + n_att, dup)

    # ---------------------------------------------------------- privacy / synthetic data
    pv = []
    phone_re = re.compile(r"\+999-555-\d+")
    for c in t["guardian_contact"]:
        if not c["phone"].startswith("+999-555-") or not c["email"].endswith("@example.org"):
            pv.append(f"{c['contact_id']} non-synthetic contact")
    for nrow in t["notification"]:
        if phone_re.search(nrow["message_preview"]) or "@" in nrow["message_preview"]:
            pv.append(f"{nrow['notification_id']} contact details in message")
    for s in t["stop"]:
        if C.ADDRESS_MARKER in s["stop_name"]:
            pv.append(f"{s['stop_id']} address in stop name")
    per_student = Counter(c["student_id"] for c in t["guardian_contact"] if c["valid_to"] is None)
    if any(v > 3 for v in per_student.values()):
        pv.append("more than 3 open contacts for a student")
    banned_cols = {"date_of_birth", "dob", "national_id", "photo", "medical_condition"}
    for tb in TABLES:
        if banned_cols & set(tb.columns):
            pv.append(f"{tb.name} holds unnecessary personal data")
    ck.check("synthetic_and_minimised_contact_data", "privacy", len(t["guardian_contact"]) + len(t["notification"]), pv)

    # ---------------------------------------------------------- ground-truth separation
    gv = []
    label_cols = {"issue_type", "ground_truth", "is_anomaly", "anomaly", "label", "injected"}
    for tb in TABLES:
        if label_cols & set(tb.columns):
            gv.append(f"{tb.name} carries a label column")
    gt_path = os.path.join(out_dir, "ground_truth", "ground_truth.csv")
    gt_rows = []
    if os.path.exists(gt_path):
        import csv
        with open(gt_path, newline="", encoding="utf-8") as fh:
            gt_rows = list(csv.DictReader(fh))
        for g in gt_rows:
            ref = att_ids if g["entity_table"] == "attendance_event" else keysets.get(g["entity_table"], set())
            if g["entity_id"] not in ref:
                gv.append(f"{g['issue_id']} references missing {g['entity_table']} {g['entity_id']}")
    else:
        gv.append("ground_truth.csv missing")
    ck.check("ground_truth_separate_and_resolvable", "ground_truth", len(gt_rows), gv)

    ck.check("csv_header_and_types_attendance", "schema", n_att, [e for e in parse_errors if e.startswith("attendance")])
    summary = {
        "passed": ck.passed,
        "checks_total": len(ck.results),
        "checks_failed": sum(1 for r in ck.results if r["status"] == "FAIL"),
        "row_counts": {**{k: len(v) for k, v in t.items()}, "attendance_event": n_att},
        "attendance_status_counts": dict(sorted(status_counts.items())),
        "checks": ck.results,
    }
    return summary, t
