"""End-to-end orchestration: generate -> export -> validate -> detect -> report."""
import os
import platform
import shutil
import sys
import tempfile
import time

from . import anomalies, config as C, detect, geo, ids, lifecycle, master, metrics, operations, planning, rules
from . import storage
from .schema import TABLES, TABLE_BY_NAME, data_dictionary_md

GT_COLUMNS = ["issue_id", "issue_type", "subtype", "entity_table", "entity_id", "related_ids", "first_date",
              "expected_decision", "rule_violated", "description", "injected"]
EXC_COLUMNS = ["event_id", "event_date", "student_id", "assignment_id", "event_type", "reason_code",
               "route_id", "stop_id", "triggered_by", "actor_role"]


def build(scale_name, seed, log=print):
    """Generate all tables in memory. Returns (tables, ground_truth_rows, extras)."""
    scale = C.SCALES[scale_name]
    geo.configure(scale.geo_scale)
    rng = lambda stage: ids.stage_rng(seed, stage)  # noqa: E731
    k = scale.anomalies_per_type
    t0 = time.time()

    # Step 2a: master data, parents first
    days = master.school_days(scale.school_days)
    first, last = days[0]["service_date"], days[-1]["service_date"]
    zones, zone_w = master.build_zones(scale, rng("zones"))
    n_home = 3 * k
    stops = master.build_stops(scale.stops - n_home, zones, zone_w, rng("stops"))
    buses = master.build_buses(scale, zones, rng("buses"))
    drivers = master.build_drivers(scale, buses, rng("drivers"), last)
    students = master.build_students(scale, zones, zone_w, stops, days, rng("students"))
    master.add_home_requests(stops, students, zones, n_home, rng("home_requests"))
    master.number_stops(stops)
    contacts = master.build_contacts(students, days, rng("contacts"))
    log(f"  master data      {time.time() - t0:5.1f}s  students={len(students)} stops={len(stops)} "
        f"buses={len(buses)} contacts={len(contacts)}")

    # Step 3a: plan (stop choice, candidates, routes, window repair)
    plan = planning.build_plan(students, stops, buses, drivers, days, rng("plan"))
    rostered = {r["bus_id"] for r in plan.routes}
    for b in buses:                      # buses the plan did not need become spares
        if b["fleet_role"] == "route" and b["bus_id"] not in rostered:
            b["fleet_role"] = "spare"
    gt = anomalies.GroundTruth()
    cap_specs = lifecycle.baseline_capacity_specs(plan, scale, days, rng("capacity"))
    busy_buses = {s["bus_id"] for s in cap_specs}
    protected = {r["route_id"] for r in plan.routes if r["bus_id"] in busy_buses}
    touched = anomalies.inject_plan(plan, students, k, rng("anomaly_plan"), gt, protected)
    planning.derive_routes(plan, plan.initial, first, last)
    log(f"  route plan       {time.time() - t0:5.1f}s  routes={len(plan.routes)} assigned_at_plan={len(plan.initial)}")

    # Step 3b: year lifecycle (capacity changes, joiners, leavers, overrides)
    book = rules.CapacityBook(buses, [])
    lc = lifecycle.Lifecycle(plan, students, buses, days, book, rng("lifecycle"))
    anomalies.register_lifecycle(lc, k, rng("anomaly_lifecycle"), gt, set(busy_buses), touched)
    lc.run(cap_specs, n_overrides=max(1, round(scale.students * 0.004)))
    cap_events = sorted(lc.capacity_events, key=lambda e: (e["effective_from"], e["bus_id"]))
    for i, e in enumerate(cap_events, start=1):
        e["capacity_event_id"] = ids.capacity_event(i)
    order = {id(e): i for i, e in enumerate(lc.events)}
    events = sorted(lc.events, key=lambda e: (e["event_date"], order[id(e)]))
    for i, e in enumerate(events, start=1):
        e["event_id"] = ids.assignment_event(i)
        if isinstance(e["triggered_by"], dict):
            e["triggered_by"] = e["triggered_by"]["capacity_event_id"]
    by_asn = {}
    for e in events:
        by_asn.setdefault(e["assignment_id"], []).append(e)
    assignments = sorted(lc.assignments.values(), key=lambda a: a["assignment_id"])
    for a in assignments:
        a["current_status"] = rules.final_status(sorted(by_asn[a["assignment_id"]], key=lambda e: e["event_seq"]))
        a["status_as_of"] = last
    log(f"  lifecycle        {time.time() - t0:5.1f}s  assignment_events={len(events)} capacity_events={len(cap_events)}")

    # Step 3c: daily operations
    disruptions, attendance, notifications, _ = operations.run(
        plan, students, contacts, buses, drivers, days, events, assignments, scale, seed)
    anomalies.inject_notifications(notifications, contacts, students, k, rng("anomaly_notify"), gt)
    operations.number_notifications(notifications)
    log(f"  operations       {time.time() - t0:5.1f}s  attendance={len(attendance)} notifications={len(notifications)}")

    def resolve(table, ref):
        if isinstance(ref, str):
            return ref
        if table == "route_stop":
            return plan.rs_by_key[ref]["route_stop_id"]
        return ref[{"assignment_event": "event_id", "notification": "notification_id",
                    "capacity_event": "capacity_event_id"}[table]]

    gt_rows = gt.rows(resolve)
    tables = {
        "school_day": days, "address_zone": zones, "stop": stops, "bus": buses, "driver": drivers,
        "student": students, "guardian_contact": contacts, "route": plan.routes,
        "route_candidate": plan.candidates, "route_stop": plan.route_stops, "assignment": assignments,
        "assignment_event": events, "bus_capacity_event": cap_events, "route_disruption": disruptions,
        "attendance_event": attendance, "notification": notifications,
    }
    exceptions = [e for e in events if e["reason_code"] not in ("ASSIGNED_NEAREST_STOP", "MIDYEAR_ASSIGNED")]
    return tables, gt_rows, {"exceptions": exceptions, "scale": scale}


FORMATS = ("csv", "json", "json.gz", "sql", "sql.gz")


def export(tables, gt_rows, out_dir, formats):
    bad = [f for f in formats if f not in FORMATS]
    if bad:
        raise ValueError(f"unknown format(s) {bad}; choose from {FORMATS}")
    data = os.path.join(out_dir, "data")
    os.makedirs(os.path.join(data, "csv"), exist_ok=True)   # CSV is always written (validation reads it)
    json_ext = "json.gz" if "json.gz" in formats else ("json" if "json" in formats else None)
    sql_ext = "sql.gz" if "sql.gz" in formats else ("sql" if "sql" in formats else None)
    for sub, ext in (("json", json_ext), ("sql", sql_ext)):
        if ext:
            os.makedirs(os.path.join(data, sub), exist_ok=True)
    for t in TABLES:
        rows = tables[t.name]
        storage.write_csv(os.path.join(data, "csv", f"{t.name}.csv"), t, rows)
        if json_ext:
            storage.write_json(os.path.join(data, "json", f"{t.name}.{json_ext}"), t, rows)
    if sql_ext:
        storage.write_sql(os.path.join(data, "sql", "schema.sql"), os.path.join(data, "sql", f"seed.{sql_ext}"), tables)
    gdir = os.path.join(out_dir, "ground_truth")
    os.makedirs(gdir, exist_ok=True)
    storage.write_plain_csv(os.path.join(gdir, "ground_truth.csv"), gt_rows, GT_COLUMNS)
    storage.write_json_obj(os.path.join(gdir, "ground_truth.json"), gt_rows)


def default_formats(scale_name):
    """Full-scale JSON/SQL are gzip-compressed (~300 MB -> ~30 MB); CSV stays plain."""
    return ("csv", "json.gz", "sql.gz") if scale_name == "full" else ("csv", "json", "sql")


def generate(scale_name="starter", seed=C.DEFAULT_SEED, out_dir=None, formats=None, log=print, reports=True):
    formats = tuple(formats or default_formats(scale_name))
    out_dir = out_dir or os.path.join("output", scale_name)
    os.makedirs(out_dir, exist_ok=True)
    t0 = time.time()
    log(f"Generating scale={scale_name} seed={seed} -> {out_dir}")
    tables, gt_rows, extras = build(scale_name, seed, log)
    export(tables, gt_rows, out_dir, formats)
    log(f"  exported         {time.time() - t0:5.1f}s")
    if not reports:
        return out_dir, None
    rdir = os.path.join(out_dir, "reports")
    os.makedirs(rdir, exist_ok=True)
    storage.write_plain_csv(os.path.join(rdir, "decision_exceptions.csv"), extras["exceptions"], EXC_COLUMNS)
    m = metrics.compute(tables)
    del tables
    summary = run_checks(out_dir, log)
    m["anomaly_detection"] = summary["detection"]["evaluation"]
    storage.write_json_obj(os.path.join(rdir, "metrics.json"), m)
    write_summary_md(os.path.join(rdir, "summary.md"), scale_name, seed, m, summary)
    with open(os.path.join(out_dir, "data_dictionary.md"), "w", encoding="utf-8") as fh:
        fh.write(data_dictionary_md())
    write_manifest(out_dir, scale_name, seed, formats, time.time() - t0)
    log(f"  done             {time.time() - t0:5.1f}s  validation={'PASS' if summary['validation']['passed'] else 'FAIL'}"
        f"  detection P/R={summary['detection']['evaluation']['overall']['precision']}/"
        f"{summary['detection']['evaluation']['overall']['recall']}")
    return out_dir, summary


def run_checks(out_dir, log=print):
    """Validate exported files and run the detector against ground truth (from disk only)."""
    import csv
    from . import validate as V
    res, loaded = V.validate(out_dir)
    with open(os.path.join(out_dir, "ground_truth", "ground_truth.csv"), newline="", encoding="utf-8") as fh:
        gt = list(csv.DictReader(fh))
    findings = detect.detect(loaded)
    evaluation = detect.evaluate(findings, gt)
    rdir = os.path.join(out_dir, "reports")
    os.makedirs(rdir, exist_ok=True)
    storage.write_json_obj(os.path.join(rdir, "validation_summary.json"), res)
    write_validation_md(os.path.join(rdir, "validation_summary.md"), res)
    storage.write_json_obj(os.path.join(rdir, "detection_report.json"),
                           {"evaluation": evaluation, "findings": findings})
    failed = [c["check"] for c in res["checks"] if c["status"] == "FAIL"]
    log(f"  validation       {res['checks_total'] - len(failed)}/{res['checks_total']} checks passed"
        + (f"  FAILED: {failed}" if failed else ""))
    return {"validation": res, "detection": {"evaluation": evaluation, "findings": len(findings)}}


def data_files(out_dir):
    files = []
    for sub in ("data", "ground_truth"):
        base = os.path.join(out_dir, sub)
        for root, _, names in os.walk(base):
            for n in sorted(names):
                files.append(os.path.join(root, n))
    return sorted(files)


def write_manifest(out_dir, scale_name, seed, formats, seconds):
    files = []
    for p in data_files(out_dir):
        rel = os.path.relpath(p, out_dir).replace(os.sep, "/")
        rows = storage.count_lines(p) - 1 if p.endswith(".csv") else None
        files.append({"path": rel, "bytes": os.path.getsize(p), "rows": rows, "sha256": storage.sha256(p)})
    manifest = {
        "generator": "transport (school transport assignment workflow)",
        "generator_version": C.GENERATOR_VERSION,
        "command": f"python -m transport generate --scale {scale_name} --seed {seed} --out {out_dir.replace(os.sep, '/')}"
                   f" --formats {','.join(formats)}",
        "seed": seed, "scale": C.SCALES[scale_name].as_dict(),
        "school_year": C.SCHOOL_YEAR, "first_school_day": C.FIRST_SCHOOL_DAY,
        "provenance": {
            "external_data_used": False,
            "sources": [],
            "statement": "All records are synthetic and produced by this generator from a fixed seed. "
                         "No public or personal dataset was downloaded, copied or sampled. Coordinates are on "
                         "an abstract km plane, phone numbers use the unassigned +999 prefix, e-mail uses the "
                         "RFC 2606 reserved domain example.org, addresses contain the marker 'Synth Street'.",
            "license": "Generated data may be freely redistributed (no third-party rights).",
        },
        "runtime": {"python": platform.python_version(), "platform": platform.system(),
                    "seconds": round(seconds, 1)},
        "files": files,
    }
    storage.write_json_obj(os.path.join(out_dir, "manifest.json"), manifest)


def reproducibility(scale_name, seed, out_dir=None, log=print, formats=None):
    """Regenerate twice with the same seed (and once with seed+1) and compare checksums."""
    tmp = tempfile.mkdtemp(prefix="transport_repro_")
    try:
        runs = []
        for i, s in enumerate((seed, seed, seed + 1)):
            d = os.path.join(tmp, f"run{i + 1}")
            generate(scale_name, s, d, formats, log=lambda *_: None, reports=False)
            runs.append({os.path.relpath(p, d).replace(os.sep, "/"): (storage.sha256(p),
                         storage.count_lines(p) - 1 if p.endswith(".csv") else None) for p in data_files(d)})
        same = runs[0] == runs[1]
        diff_seed_changed = sum(1 for k in runs[0] if runs[0][k][0] != runs[2].get(k, (None,))[0])
        report = {
            "scale": scale_name, "seed": seed, "identical_runs": same,
            "files_compared": len(runs[0]),
            "mismatched_files": sorted(k for k in runs[0] if runs[0][k] != runs[1].get(k)),
            "files": [{"path": k, "rows": runs[0][k][1], "sha256_run1": runs[0][k][0],
                       "sha256_run2": runs[1][k][0], "match": runs[0][k] == runs[1][k]} for k in sorted(runs[0])],
            "control_seed": seed + 1, "files_changed_with_control_seed": diff_seed_changed,
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if out_dir:
        os.makedirs(os.path.join(out_dir, "reports"), exist_ok=True)
        storage.write_json_obj(os.path.join(out_dir, "reports", "reproducibility.json"), report)
    log(f"Reproducibility scale={scale_name} seed={seed}: identical={same} "
        f"({len(runs[0])} files); control seed changed {diff_seed_changed} files")
    return report


# ------------------------------------------------------------------ markdown reports
def write_validation_md(path, res):
    lines = ["# Validation summary", "",
             f"Overall: **{'PASS' if res['passed'] else 'FAIL'}** "
             f"({res['checks_total'] - res['checks_failed']}/{res['checks_total']} checks passed)", "",
             "| Check | Category | Status | Records checked | Violations | Examples |", "|---|---|---|---|---|---|"]
    for c in res["checks"]:
        ex = "; ".join(c["examples"]).replace("|", "\\|")
        lines.append(f"| {c['check']} | {c['category']} | {c['status']} | {c['records_checked']} | "
                     f"{c['violations']} | {ex} |")
    lines += ["", "## Row counts", "", "| Table | Rows |", "|---|---|"]
    for k, v in res["row_counts"].items():
        lines.append(f"| {k} | {v} |")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def write_summary_md(path, scale_name, seed, m, summary):
    a, r, at, n = m["assignment"], m["routing"], m["attendance"], m["notifications"]
    ev = summary["detection"]["evaluation"]
    lines = [f"# Run summary - scale `{scale_name}`, seed `{seed}`", "",
             f"Validation: **{'PASS' if summary['validation']['passed'] else 'FAIL'}** "
             f"({summary['validation']['checks_total'] - summary['validation']['checks_failed']}/"
             f"{summary['validation']['checks_total']} integrity checks)", "",
             "## Key metrics", "", "| Metric | Value |", "|---|---|",
             f"| Students | {m['volumes']['student']} |",
             f"| Assignment rate (of eligible) | {a['assignment_rate_pct_of_eligible']}% |",
             f"| Pickup-window compliance | {a['pickup_window_compliance_pct']}% |",
             f"| Accessible-need students on accessible routes | {a['accessible_need_assigned_on_accessible_route_pct']}% |",
             f"| Ride time mean / p95 / max (min) | {a['ride_time_min'].get('mean')} / {a['ride_time_min'].get('p95')} / {a['ride_time_min'].get('max')} |",
             f"| Walk to stop mean / p95 (m) | {a['walk_distance_m'].get('mean')} / {a['walk_distance_m'].get('p95')} |",
             f"| Routes (regular / accessible) | {r['routes_by_service_type'].get('regular', 0)} / {r['routes_by_service_type'].get('accessible', 0)} |",
             f"| Bus utilisation at plan mean / max | {r['utilization_pct'].get('mean')}% / {r['utilization_pct'].get('max')}% |",
             f"| Route duration mean / max (min) | {r['route_duration_min'].get('mean')} / {r['route_duration_min'].get('max')} |",
             f"| Attendance events | {at['events']} |",
             f"| Absence rate | {at['absence_rate_pct']}% |",
             f"| On-time / late / missed pickup (of present) | {at['on_time_pickup_rate_pct']}% / {at['late_pickup_rate_pct']}% / {at['missed_pickup_rate_pct']}% |",
             f"| Disruptions | {m['disruptions']['total']} ({m['disruptions']['disruption_rate_pct_of_route_days']}% of route-days) |",
             f"| Notifications (suppressed: no valid contact) | {n['total']} ({n['suppressed_no_valid_contact_pct']}%) |",
             "", "## Decision mix", "", "| Reason | Count |", "|---|---|"]
    for k, v in sorted(a["decision_reasons"].items(), key=lambda kv: -kv[1]):
        lines.append(f"| {k} | {v} |")
    lines += ["", "## Anomaly detection vs ground truth", "",
              "| Issue type | Labelled | Detected | TP | FP | FN | Precision | Recall |", "|---|---|---|---|---|---|---|---|"]
    for k, v in ev.items():
        lines.append(f"| {k} | {v['labelled']} | {v['detected']} | {v['true_positive']} | {v['false_positive']} | "
                     f"{v['false_negative']} | {v['precision']} | {v['recall']} |")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
