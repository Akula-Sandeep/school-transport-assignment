"""Unit tests for the shared business rules (no data generation needed)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from transport import config as C, geo, ids, rules  # noqa: E402
from transport.planning import evaluate, order_radial  # noqa: E402


def student(**kw):
    s = {"student_id": "STU-000001", "transport_eligible": True, "transport_opt_in": True,
         "address_status": "verified", "requires_accessible_vehicle": False,
         "pickup_window_start": "07:00", "pickup_window_end": "07:30"}
    s.update(kw)
    return s


def contact(**kw):
    c = {"contact_id": "GC-000001", "student_id": "STU-000001", "contact_status": "active",
         "consent_to_notify": True, "valid_from": "2026-05-01", "valid_to": None,
         "preferred_channel": "sms", "phone": "+999-555-0000001", "email": "gc-000001@example.org",
         "priority": 1}
    c.update(kw)
    return c


class TestIds(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(ids.student(1), "STU-000001")
        self.assertEqual(ids.stop(12), "STOP-000012")
        self.assertEqual(ids.bus(100), "BUS-000100")
        self.assertEqual(ids.route(7), "ROUTE-2026-000007")
        self.assertEqual(ids.assignment("STU-000001"), "ASN-STU-000001-2026")
        self.assertEqual(ids.notification(3), "NOT-2026-000003")

    def test_stage_rng_is_stable_and_independent(self):
        a = [ids.stage_rng(1, "x").random() for _ in range(3)]
        b = [ids.stage_rng(1, "x").random() for _ in range(3)]
        c = ids.stage_rng(1, "y").random()
        self.assertEqual(a, b)
        self.assertNotEqual(a[0], c)


class TestEligibilityAndWindows(unittest.TestCase):
    def test_pre_assignment(self):
        self.assertIsNone(rules.pre_assignment_outcome(student()))
        self.assertEqual(rules.pre_assignment_outcome(student(transport_eligible=False))[1], "INELIGIBLE_WALK_ZONE")
        self.assertEqual(rules.pre_assignment_outcome(student(transport_opt_in=False))[0], "opted_out")
        self.assertEqual(rules.pre_assignment_outcome(student(address_status="pending"))[1],
                         "WAITLIST_ADDRESS_PENDING")

    def test_window_boundaries_inclusive(self):
        s = student()
        self.assertTrue(rules.window_ok(s, geo.to_min("07:00")))
        self.assertTrue(rules.window_ok(s, geo.to_min("07:30")))
        self.assertFalse(rules.window_ok(s, geo.to_min("06:59")))
        self.assertFalse(rules.window_ok(s, geo.to_min("07:31")))

    def test_accessible_student_needs_accessible_approved_stop(self):
        s = student(requires_accessible_vehicle=True)
        self.assertFalse(rules.stop_usable({"approval_status": "approved", "is_accessible": False}, s))
        self.assertFalse(rules.stop_usable({"approval_status": "pending", "is_accessible": True}, s))
        self.assertTrue(rules.stop_usable({"approval_status": "approved", "is_accessible": True}, s))


class TestCapacityBook(unittest.TestCase):
    def test_effective_dated_capacity(self):
        book = rules.CapacityBook([{"bus_id": "BUS-000001", "base_seated_capacity": 60}], [])
        book.add({"bus_id": "BUS-000001", "effective_from": "2026-07-01", "effective_to": "2026-07-10",
                  "new_capacity": 48})
        self.assertEqual(book.capacity("BUS-000001", "2026-06-30"), 60)
        self.assertEqual(book.capacity("BUS-000001", "2026-07-01"), 48)
        self.assertEqual(book.capacity("BUS-000001", "2026-07-10"), 48)
        self.assertEqual(book.capacity("BUS-000001", "2026-07-11"), 60)


class TestContacts(unittest.TestCase):
    def test_valid_contact(self):
        self.assertEqual(rules.contact_problems(contact(), "STU-000001", "2026-06-10"), [])

    def test_each_invalid_reason(self):
        d = "2026-06-10"
        self.assertIn("CONTACT_BOUNCED", rules.contact_problems(contact(contact_status="bounced"), "STU-000001", d))
        self.assertIn("NO_CONSENT", rules.contact_problems(contact(consent_to_notify=False), "STU-000001", d))
        self.assertIn("CONTACT_NOT_EFFECTIVE",
                      rules.contact_problems(contact(valid_to="2026-06-01"), "STU-000001", d))
        self.assertIn("MALFORMED_PHONE", rules.contact_problems(contact(phone="+999-555-12345"), "STU-000001", d))
        self.assertIn("CONTACT_BELONGS_TO_OTHER_STUDENT", rules.contact_problems(contact(), "STU-000002", d))

    def test_fallback_to_next_priority(self):
        cs = [contact(contact_status="bounced"), contact(contact_id="GC-000002", priority=2)]
        self.assertEqual(rules.pick_contact(cs, "STU-000001", "2026-06-10")["contact_id"], "GC-000002")
        self.assertIsNone(rules.pick_contact(cs[:1], "STU-000001", "2026-06-10"))


class TestSegments(unittest.TestCase):
    def test_events_become_service_segments(self):
        dates = ["2026-06-08", "2026-06-09", "2026-06-10", "2026-06-11", "2026-06-12"]
        ev = [
            {"assignment_id": "A", "event_seq": 1, "event_type": "ASSIGNED", "event_date": "2026-06-01",
             "route_id": "R1", "stop_id": "S1", "event_id": "E1"},
            {"assignment_id": "A", "event_seq": 2, "event_type": "REASSIGNED", "event_date": "2026-06-10",
             "route_id": "R2", "stop_id": "S2", "event_id": "E2"},
            {"assignment_id": "A", "event_seq": 3, "event_type": "ENDED", "event_date": "2026-06-12",
             "route_id": None, "stop_id": None, "event_id": "E3"},
        ]
        segs = rules.build_segments(ev, dates)["A"]
        self.assertEqual(segs, [(0, 1, "R1", "S1", "E1"), (2, 3, "R2", "S2", "E2")])
        self.assertEqual(rules.final_status(ev), "ended")

    def test_transition_table(self):
        self.assertIn("ASSIGNED", rules.ALLOWED_TRANSITIONS[None])
        self.assertNotIn("ASSIGNED", rules.ALLOWED_TRANSITIONS["ENDED"])


class TestTravelTimes(unittest.TestCase):
    def test_route_evaluation_speeds_are_feasible(self):
        geo.configure(1.0)
        stops = {"A": {"x_km": 12.0, "y_km": 0.0}, "B": {"x_km": 8.0, "y_km": 1.0}, "C": {"x_km": 3.0, "y_km": 0.5}}
        seq = order_radial(list(stops), stops)
        self.assertEqual(seq, ["A", "B", "C"])
        ev = evaluate(seq, stops, 1.0)
        self.assertLessEqual(ev["max_speed"], C.MAX_FEASIBLE_SPEED_KMPH)
        self.assertAlmostEqual(ev["total"], round(sum(m for _, m in ev["legs"]) + 3 * 1.0 + ev["final"][1], 1))

    def test_implied_speed(self):
        self.assertEqual(geo.implied_speed_kmph(10, 30), 20)
        self.assertGreater(geo.implied_speed_kmph(5, 0.5), C.MAX_FEASIBLE_SPEED_KMPH)


if __name__ == "__main__":
    unittest.main()
