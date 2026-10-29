"""End-to-end acceptance tests on the 'tiny' scale (runs in a few seconds).

Run:  python -m unittest discover -s tests -v      (or: python -m pytest -q)
"""
import csv
import dataclasses
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from transport import config as C, detect, geo, pipeline, rules, storage  # noqa: E402
from transport.schema import TABLES  # noqa: E402
from transport.validate import validate  # noqa: E402

SEED = C.DEFAULT_SEED
OUT = None
OUT_CLEAN = None


def quiet(*_):
    pass


def setUpModule():
    global OUT, OUT_CLEAN
    base = tempfile.mkdtemp(prefix="transport_test_")
    OUT = os.path.join(base, "tiny")
    pipeline.generate("tiny", SEED, OUT, log=quiet)
    # same generator with zero injected anomalies = clean baseline
    C.SCALES["tiny_clean"] = dataclasses.replace(C.SCALES["tiny"], name="tiny_clean", anomalies_per_type=0)
    OUT_CLEAN = os.path.join(base, "tiny_clean")
    pipeline.generate("tiny_clean", SEED, OUT_CLEAN, log=quiet)


def tearDownModule():
    C.SCALES.pop("tiny_clean", None)
    shutil.rmtree(os.path.dirname(OUT), ignore_errors=True)


def load(out, name):
    return storage.load_table(os.path.join(out, "data", "csv"), name)


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class TestIntegrity(unittest.TestCase):
    def test_all_validation_checks_pass(self):
        res = read_json(os.path.join(OUT, "reports", "validation_summary.json"))
        failed = [c for c in res["checks"] if c["status"] != "PASS"]
        self.assertEqual(failed, [], failed)
        self.assertGreaterEqual(res["checks_total"], 20)

    def test_every_entity_exported_in_every_format(self):
        for t in TABLES:
            csv_rows = len(load(OUT, t.name))
            js = read_json(os.path.join(OUT, "data", "json", f"{t.name}.json"))
            self.assertEqual(len(js), csv_rows, t.name)
            self.assertGreater(csv_rows, 0, f"{t.name} is empty")

    def test_sql_seed_loads_with_foreign_keys(self):
        con = sqlite3.connect(":memory:")
        with open(os.path.join(OUT, "data", "sql", "schema.sql"), encoding="utf-8") as fh:
            con.executescript(fh.read())
        with open(os.path.join(OUT, "data", "sql", "seed.sql"), encoding="utf-8") as fh:
            con.executescript(fh.read())
        self.assertEqual(con.execute("PRAGMA foreign_key_check").fetchall(), [])
        n = con.execute("SELECT COUNT(*) FROM attendance_event").fetchone()[0]
        self.assertEqual(n, len(load(OUT, "attendance_event")))

    def test_id_conventions(self):
        for s in load(OUT, "student"):
            self.assertRegex(s["student_id"], r"^STU-\d{6}$")
        for a in load(OUT, "assignment"):
            self.assertEqual(a["assignment_id"], f"ASN-{a['student_id']}-2026")
        for r in load(OUT, "route"):
            self.assertRegex(r["route_id"], r"^ROUTE-2026-\d{6}$")
        for n in load(OUT, "notification"):
            self.assertRegex(n["notification_id"], r"^NOT-2026-\d{6}$")
        for b in load(OUT, "bus"):
            self.assertRegex(b["bus_id"], r"^BUS-\d{6}$")
        for s in load(OUT, "stop"):
            self.assertRegex(s["stop_id"], r"^STOP-\d{6}$")


class TestBusinessRules(unittest.TestCase):
    """Acceptance criteria on the clean baseline (no injected anomalies)."""

    @classmethod
    def setUpClass(cls):
        cls.t = {t.name: load(OUT_CLEAN, t.name) for t in TABLES if t.name != "attendance_event"}

    def test_clean_baseline_has_no_rule_violations(self):
        self.assertEqual(detect.detect(self.t), [])

    def test_assignments_respect_capacity_safety_and_walk(self):
        students = {s["student_id"]: s for s in self.t["student"]}
        for a in self.t["assignment"]:
            if a["decision"] != "assigned":
                continue
            self.assertTrue(a["capacity_ok"] and a["accessibility_ok"], a)
            self.assertLessEqual(a["walk_distance_m"], students[a["student_id"]]["max_walk_m"])
            self.assertLessEqual(a["ride_time_min"], C.MAX_ROUTE_MIN)

    def test_routes_are_feasible(self):
        for r in self.t["route"]:
            self.assertLessEqual(r["total_travel_min"], C.MAX_ROUTE_MIN)
            self.assertLessEqual(r["planned_load"], r["capacity_at_plan"])
        stops = {s["stop_id"]: s for s in self.t["stop"]}
        for rs in self.t["route_stop"]:
            self.assertEqual(stops[rs["stop_id"]]["approval_status"], "approved")
            if rs["stop_sequence"] > 1:
                self.assertLessEqual(geo.implied_speed_kmph(rs["leg_distance_km"], rs["leg_travel_min"]),
                                     C.MAX_FEASIBLE_SPEED_KMPH)

    def test_accessible_needs_only_on_accessible_routes(self):
        routes = {r["route_id"]: r for r in self.t["route"]}
        students = {s["student_id"]: s for s in self.t["student"]}
        for e in self.t["assignment_event"]:
            if e["route_id"] and students[e["student_id"]]["requires_accessible_vehicle"]:
                self.assertEqual(routes[e["route_id"]]["service_type"], "accessible")

    def test_notifications_only_to_valid_contacts_and_no_addresses(self):
        contacts = {c["contact_id"]: c for c in self.t["guardian_contact"]}
        for n in self.t["notification"]:
            self.assertIsNone(rules.ADDRESS_RE.search(n["message_preview"]))
            if n["contact_id"]:
                c = contacts[n["contact_id"]]
                self.assertEqual(rules.contact_problems(c, n["student_id"], n["service_date"], n["channel"]), [])
            else:
                self.assertEqual(n["delivery_status"], "suppressed")


class TestAttendanceReflectsChanges(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events = load(OUT, "assignment_event")
        cls.att = load(OUT, "attendance_event")
        cls.students = {s["student_id"]: s for s in load(OUT, "student")}

    def test_no_attendance_after_withdrawal_or_before_enrollment(self):
        for a in self.att:
            s = self.students[a["student_id"]]
            self.assertGreaterEqual(a["service_date"], s["enrolled_on"])
            if s["withdrawn_on"]:
                self.assertLess(a["service_date"], s["withdrawn_on"])

    def test_route_changes_take_effect_on_event_date(self):
        by_student = defaultdict(list)
        for a in self.att:
            by_student[a["student_id"]].append(a)
        checked = 0
        for e in self.events:
            if e["event_type"] == "REASSIGNED":
                after = [a for a in by_student[e["student_id"]] if a["service_date"] >= e["event_date"]]
                later = [x for x in self.events if x["assignment_id"] == e["assignment_id"]
                         and x["event_seq"] > e["event_seq"]]
                if later:
                    after = [a for a in after if a["service_date"] < later[0]["event_date"]]
                for a in after:
                    self.assertEqual((a["route_id"], a["stop_id"]), (e["route_id"], e["stop_id"]))
                checked += 1
        self.assertGreater(checked, 0, "no reassignment in dataset")

    def test_waitlisted_students_have_no_attendance(self):
        last = {}
        for e in sorted(self.events, key=lambda e: (e["assignment_id"], e["event_seq"])):
            last[e["student_id"]] = e
        riding = {a["student_id"] for a in self.att}
        never_active = {sid for sid in last if not any(
            x["route_id"] for x in self.events if x["student_id"] == sid)}
        self.assertFalse(riding & never_active)

    def test_status_rules(self):
        for a in self.att:
            if a["attendance_status"] in ("boarded", "boarded_late"):
                limit = C.LATE_THRESHOLD_MIN if a["attendance_status"] == "boarded" else C.MAX_WAIT_MIN
                self.assertLessEqual(a["delay_min"], limit)


class TestAnomaliesAndGroundTruth(unittest.TestCase):
    def test_each_required_edge_case_is_labelled_and_detected(self):
        ev = read_json(os.path.join(OUT, "reports", "detection_report.json"))["evaluation"]
        for it in C.ANOMALY_TYPES:
            self.assertGreaterEqual(ev[it]["labelled"], 1, it)
            self.assertEqual(ev[it]["recall"], 1.0, it)
            self.assertEqual(ev[it]["precision"], 1.0, it)

    def test_ground_truth_not_leaked_into_inputs(self):
        with open(os.path.join(OUT, "ground_truth", "ground_truth.csv"), newline="", encoding="utf-8") as fh:
            gt = list(csv.DictReader(fh))
        self.assertTrue(gt)
        for t in TABLES:
            with open(os.path.join(OUT, "data", "csv", f"{t.name}.csv"), encoding="utf-8") as fh:
                header = fh.readline().strip().split(",")
            for col in ("issue_type", "ground_truth", "is_anomaly", "label", "injected", "expected_decision"):
                self.assertNotIn(col, header, t.name)
        self.assertFalse(os.path.exists(os.path.join(OUT, "data", "csv", "ground_truth.csv")))


class TestValidatorCatchesCorruption(unittest.TestCase):
    def test_broken_foreign_key_and_duplicate_pk_fail(self):
        tmp = tempfile.mkdtemp(prefix="transport_corrupt_")
        try:
            bad = os.path.join(tmp, "bad")
            shutil.copytree(OUT, bad)
            p = os.path.join(bad, "data", "csv", "stop.csv")
            with open(p, encoding="utf-8") as fh:
                lines = fh.read().splitlines()
            lines[1] = lines[1].replace("ZONE-", "ZONE-9", 1)      # dangling FK
            lines.append(lines[2])                                  # duplicate PK
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
            res, _ = validate(bad)
            status = {c["check"]: c["status"] for c in res["checks"]}
            self.assertFalse(res["passed"])
            self.assertEqual(status["foreign_key_integrity"], "FAIL")
            self.assertEqual(status["primary_key_unique"], "FAIL")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestReproducibility(unittest.TestCase):
    def test_same_seed_identical_other_seed_differs(self):
        rep = pipeline.reproducibility("tiny", SEED, out_dir=None, log=quiet)
        self.assertTrue(rep["identical_runs"], rep["mismatched_files"])
        self.assertGreater(rep["files_changed_with_control_seed"], 0)


if __name__ == "__main__":
    unittest.main()
