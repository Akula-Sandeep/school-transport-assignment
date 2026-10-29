"""Measurable outputs: assignment quality, routing efficiency, service reliability,
notification coverage and data distributions."""
from collections import Counter

from . import config as C
from . import geo, rules


def pct(a, b):
    return round(100.0 * a / b, 2) if b else 0.0


def quantile(values, q):
    if not values:
        return None
    v = sorted(values)
    k = min(len(v) - 1, max(0, int(round(q * (len(v) - 1)))))
    return v[k]


def stats(values):
    if not values:
        return {}
    return {"mean": round(sum(values) / len(values), 2), "p50": quantile(values, 0.5),
            "p95": quantile(values, 0.95), "max": max(values), "min": min(values)}


def compute(tables):
    st = tables["student"]
    asn = tables["assignment"]
    ev = tables["assignment_event"]
    routes = tables["route"]
    m = {}

    m["volumes"] = {k: len(v) for k, v in tables.items()}
    m["distributions"] = {
        "students_by_grade": dict(sorted(Counter(s["grade"] for s in st).items(),
                                         key=lambda kv: C.GRADES.index(kv[0]))),
        "students_by_zone_type": dict(Counter(_zone_type(tables, s) for s in st)),
        "mobility_aid": dict(Counter(s["mobility_aid"] for s in st)),
        "midyear_enrollments": sum(1 for s in st if s["enrolled_on"] >= C.FIRST_SCHOOL_DAY),
        "withdrawals": sum(1 for s in st if s["withdrawn_on"]),
        "stops_by_approval": dict(Counter(s["approval_status"] for s in tables["stop"])),
        "bus_types": dict(Counter(b["bus_type"] for b in tables["bus"])),
        "bus_fleet_roles": dict(Counter(b["fleet_role"] for b in tables["bus"])),
    }

    assigned = [a for a in asn if a["decision"] == "assigned"]
    eligible = [a for a in asn if a["decision"] in ("assigned", "waitlisted")]
    needs_access = [a for a in eligible if _student(tables, a["student_id"])["requires_accessible_vehicle"]]
    acc_routes = {r["route_id"] for r in routes if r["service_type"] == "accessible"}
    m["assignment"] = {
        "decisions": dict(Counter(a["decision"] for a in asn)),
        "decision_reasons": dict(Counter(a["decision_reason"] for a in asn)),
        "assignment_rate_pct_of_eligible": pct(len(assigned), len(eligible)),
        "final_status": dict(Counter(a["current_status"] for a in asn)),
        "pickup_window_compliance_pct": pct(sum(1 for a in assigned if a["window_ok"]), len(assigned)),
        "accessible_need_students": len(needs_access),
        "accessible_need_assigned": sum(1 for a in needs_access if a["decision"] == "assigned"),
        "accessible_need_assigned_on_accessible_route_pct": pct(
            sum(1 for a in needs_access if a["route_id"] in acc_routes),
            sum(1 for a in needs_access if a["decision"] == "assigned")),
        "ride_time_min": stats([a["ride_time_min"] for a in assigned]),
        "walk_distance_m": stats([a["walk_distance_m"] for a in assigned]),
        "events_by_type": dict(Counter(e["event_type"] for e in ev)),
        "events_by_reason": dict(Counter(e["reason_code"] for e in ev)),
    }
    m["routing"] = {
        "routes": len(routes),
        "routes_by_service_type": dict(Counter(r["service_type"] for r in routes)),
        "utilization_pct": stats([r["utilization_pct"] for r in routes]),
        "route_duration_min": stats([r["total_travel_min"] for r in routes]),
        "route_distance_km": stats([r["total_distance_km"] for r in routes]),
        "stops_per_route": stats([r["stop_count"] for r in routes]),
        "candidates_evaluated": len(tables["route_candidate"]),
        "selected_by_method": dict(Counter(c["method"] for c in tables["route_candidate"] if c["selected"])),
        "infeasible_candidates": sum(1 for c in tables["route_candidate"] if not c["feasible"]),
        "capacity_events": dict(Counter(e["event_type"] for e in tables["bus_capacity_event"])),
    }
    att = tables["attendance_event"]
    status_idx = 9  # attendance rows are tuples in schema column order
    sc = Counter(r[status_idx] for r in att)
    total = len(att)
    present = total - sc["absent_reported"] - sc["no_show"]
    by_dis = sum(1 for r in att if r[status_idx] == "missed_pickup" and r[10] is not None)
    m["attendance"] = {
        "events": total,
        "status_counts": dict(sorted(sc.items())),
        "absence_rate_pct": pct(sc["absent_reported"] + sc["no_show"], total),
        "reported_absence_share_pct": pct(sc["absent_reported"], sc["absent_reported"] + sc["no_show"]),
        "on_time_pickup_rate_pct": pct(sc["boarded"], present),
        "late_pickup_rate_pct": pct(sc["boarded_late"], present),
        "missed_pickup_rate_pct": pct(sc["missed_pickup"], present),
        "missed_pickups_with_disruption_pct": pct(by_dis, sc["missed_pickup"]),
        "delay_min_when_bus_ran": stats([r[8] for r in att if r[8] is not None]),
    }
    dis = tables["route_disruption"]
    m["disruptions"] = {
        "total": len(dis),
        "by_type": dict(Counter(d["disruption_type"] for d in dis)),
        "by_resolution": dict(Counter(d["resolution"] for d in dis)),
        "disruption_rate_pct_of_route_days": pct(len(dis), len({(r[4], r[1]) for r in att})),
    }
    nt = tables["notification"]
    m["notifications"] = {
        "total": len(nt),
        "by_type": dict(Counter(n["notification_type"] for n in nt)),
        "by_delivery_status": dict(Counter(n["delivery_status"] for n in nt)),
        "by_channel": dict(Counter(n["channel"] or "none" for n in nt)),
        "suppressed_no_valid_contact_pct": pct(sum(1 for n in nt if n["delivery_status"] == "suppressed"), len(nt)),
    }
    gc = tables["guardian_contact"]
    m["contacts"] = {
        "total": len(gc),
        "per_student": dict(Counter(Counter(c["student_id"] for c in gc).values())),
        "status": dict(Counter(c["contact_status"] for c in gc)),
        "unusable_on_first_day_pct": pct(sum(1 for c in gc if rules.contact_problems(
            c, c["student_id"], max(C.FIRST_SCHOOL_DAY, c["valid_from"]))), len(gc)),
    }
    return m


_cache = {}


def _student(tables, sid):
    key = id(tables["student"])
    if _cache.get("k") != key:
        _cache.clear()
        _cache["k"] = key
        _cache["s"] = {s["student_id"]: s for s in tables["student"]}
        _cache["z"] = {z["zone_id"]: z for z in tables["address_zone"]}
    return _cache["s"][sid]


def _zone_type(tables, s):
    _student(tables, s["student_id"])
    return _cache["z"][s["home_zone_id"]]["zone_type"]
