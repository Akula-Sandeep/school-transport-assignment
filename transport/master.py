"""Step 2a: master / reference data (generated first, parents before children).

school_day -> address_zone -> stop -> bus -> driver -> student -> guardian_contact
"""
import datetime as dt
import math

from . import config as C
from . import geo, ids

GIVEN = ["Aarav", "Diya", "Ishaan", "Meera", "Kabir", "Anaya", "Vihaan", "Saanvi", "Arjun", "Myra",
         "Reyansh", "Kiara", "Advik", "Aditi", "Rohan", "Zara", "Dev", "Tara", "Nikhil", "Riya",
         "Leo", "Maya", "Omar", "Nora", "Ethan", "Lina", "Samir", "Isha", "Yusuf", "Anika"]
SURNAME_INITIALS = list("ABCDEFGHIJKLMNPRSTVWY")
DRIVER_SURNAMES = ["Rao", "Singh", "Menon", "Das", "Iyer", "Khan", "Patel", "Nair", "Joshi", "Bose",
                   "Kumar", "Pillai", "Reddy", "Shah", "Varma", "Gill", "Sen", "Naidu", "Mehta", "Roy"]
STREETS = ["Banyan Rd", "Lotus Ave", "Canal Rd", "Market Rd", "Temple St", "Mill Ln", "Park Ave",
           "Lake View Rd", "Station Rd", "Orchard Ln", "Ridge Rd", "Garden St", "River Rd", "Hill St"]
GRADE_WEIGHTS = [1.0, 1.0, 1.0, 1.0, 0.98, 0.97, 0.95, 0.93, 0.9, 0.88, 0.85, 0.8, 0.75]


def weighted_choice(rng, items, weights):
    total = sum(weights)
    x = rng.random() * total
    acc = 0.0
    for it, w in zip(items, weights):
        acc += w
        if x < acc:
            return it
    return items[-1]


def rand_date(rng, start, end):
    a, b = geo.d(start), geo.d(end)
    return (a + dt.timedelta(days=rng.randint(0, (b - a).days))).isoformat()


# ------------------------------------------------------------------ calendar
def school_days(n):
    out, cur = [], geo.d(C.FIRST_SCHOOL_DAY)
    while len(out) < n:
        iso = cur.isoformat()
        if cur.weekday() < 5 and iso not in C.HOLIDAYS:
            term = "T1" if cur.month in (6, 7, 8, 9) and cur.year == 2026 else (
                "T2" if cur.year == 2026 else "T3")
            out.append({"service_date": iso, "day_index": len(out) + 1,
                        "weekday": C.WEEKDAYS[cur.weekday()], "term": term})
        cur += dt.timedelta(days=1)
    return out


# ------------------------------------------------------------------ zones
def ring_offset_deg(ring_index):
    return ring_index * 17.0


def build_zones(scale, rng):
    zones = []
    n = 0
    for ri, (rname, inner, outer, speed, walk) in enumerate(geo.rings()):
        k = scale.ring_sectors[ri]
        width = 360.0 / k
        for s in range(k):
            n += 1
            a0 = (ring_offset_deg(ri) + s * width) % 360
            mid = math.radians(a0 + width / 2)
            rm = ((inner if inner > 0 else C.STOP_MIN_RADIUS_KM) + outer) / 2
            zones.append({
                "zone_id": ids.zone(n),
                "zone_name": f"{rname.title()} Sector {s + 1:02d}",
                "zone_type": rname, "ring_index": ri, "sector_index": s,
                "inner_radius_km": inner, "outer_radius_km": outer,
                "start_angle_deg": round(a0, 2), "end_angle_deg": round(a0 + width, 2),
                "centroid_x_km": round(rm * math.cos(mid), 3),
                "centroid_y_km": round(rm * math.sin(mid), 3),
                "avg_bus_speed_kmph": speed, "max_walk_m": walk,
            })
    # relative student density per zone (meaningful variation, not uniform)
    weights = {}
    for z in zones:
        k = scale.ring_sectors[z["ring_index"]]
        weights[z["zone_id"]] = C.RING_STUDENT_SHARE[z["zone_type"]] / k * math.exp(rng.gauss(0, 0.35))
    total = sum(weights.values())
    return zones, {k: v / total for k, v in weights.items()}


def zone_of(point, zones, scale):
    r = geo.radius(point)
    ri = geo.ring_of(r)
    k = scale.ring_sectors[ri]
    ang = math.degrees(math.atan2(point[1], point[0])) % 360
    s = int(((ang - ring_offset_deg(ri)) % 360) // (360.0 / k))
    s = min(s, k - 1)
    for z in zones:
        if z["ring_index"] == ri and z["sector_index"] == s:
            return z
    raise ValueError("no zone")


def sample_in_zone(rng, z, min_r=0.0):
    inner = max(z["inner_radius_km"], min_r)
    outer = z["outer_radius_km"]
    r = math.sqrt(rng.uniform(inner ** 2, outer ** 2))
    width = z["end_angle_deg"] - z["start_angle_deg"]
    a = math.radians(z["start_angle_deg"] + rng.uniform(0.04, 0.96) * width)
    return (r * math.cos(a), r * math.sin(a))


# ------------------------------------------------------------------ stops
def allocate(total, weights, minimum):
    keys = list(weights)
    base = {k: minimum for k in keys}
    remaining = total - minimum * len(keys)
    raw = {k: weights[k] * remaining for k in keys}
    for k in keys:
        base[k] += int(raw[k])
    left = total - sum(base.values())
    order = sorted(keys, key=lambda k: (-(raw[k] - int(raw[k])), k))
    for k in order[:left]:
        base[k] += 1
    return base


def build_stops(n_public, zones, zone_weights, rng):
    counts = allocate(n_public, zone_weights, 2)
    stops = []
    n = 0
    for z in zones:
        placed = []
        for j in range(counts[z["zone_id"]]):
            for _attempt in range(60):
                p = sample_in_zone(rng, z, C.STOP_MIN_RADIUS_KM)
                if all(geo.straight_km(p, q) >= C.STOP_MIN_SEPARATION_KM for q in placed):
                    break
            placed.append(p)
            n += 1
            u = rng.random()
            status = "approved" if u < 0.92 else ("pending" if u < 0.97 else "rejected")
            source = "planned" if status == "approved" or rng.random() < 0.4 else "guardian_request"
            proposed = rand_date(rng, "2026-01-05", "2026-03-31")
            approval_date = rand_date(rng, "2026-04-01", "2026-05-25") if status != "pending" else None
            rating = ("A" if rng.random() < 0.6 else "B") if status == "approved" else (
                "C" if status == "rejected" else rng.choice(["A", "B"]))
            stops.append({
                "stop_id": None, "zone_id": z["zone_id"],
                "stop_name": f"{z['zone_name']} Stop {j + 1:02d} - {rng.choice(STREETS)}",
                "x_km": round(p[0], 3), "y_km": round(p[1], 3),
                "approval_status": status, "approval_date": approval_date,
                "is_accessible": status == "approved" and rng.random() < 0.40,
                "safety_rating": rating, "stop_source": source,
                "effective_from": proposed, "effective_to": None,
            })
    # coverage guarantee: every zone keeps >=1 approved and >=1 approved accessible stop
    by_zone = {}
    for s in stops:
        by_zone.setdefault(s["zone_id"], []).append(s)
    for zid, lst in by_zone.items():
        if not any(s["approval_status"] == "approved" for s in lst):
            s = lst[0]
            s.update(approval_status="approved", safety_rating="A", stop_source="planned",
                     approval_date="2026-05-20")
        if not any(s["approval_status"] == "approved" and s["is_accessible"] for s in lst):
            next(s for s in lst if s["approval_status"] == "approved")["is_accessible"] = True
    return stops


# ------------------------------------------------------------------ fleet
def build_buses(scale, zones, rng):
    n_acc = scale.accessible_buses
    n_reg = scale.buses - n_acc
    n_large = round(n_reg * 0.4)
    n_midi = round(n_reg * 0.2)
    specs = ([("large", 72)] * n_large + [("midi", 48)] * n_midi +
             [("standard", 60)] * (n_reg - n_large - n_midi) + [("accessible", 28)] * n_acc)
    rng.shuffle(specs)
    depots = [z["zone_id"] for z in zones if z["zone_type"] == "suburban"]
    buses = []
    for i, (btype, cap) in enumerate(specs, start=1):
        acc = btype == "accessible"
        buses.append({
            "bus_id": ids.bus(i), "registration_code": f"SYN-{1000 + i}-{chr(65 + i % 26)}{chr(65 + (i * 7) % 26)}",
            "bus_type": btype, "base_seated_capacity": cap,
            "wheelchair_positions": 4 if acc else 0, "is_accessible": acc,
            "fleet_role": "route", "status": "in_service",
            "depot_zone_id": depots[i % len(depots)],
            "commissioned_on": rand_date(rng, "2016-01-01", "2025-12-31"),
        })
    # spares: a mix of sizes so a replacement can match the route it covers
    pref = ["large", "standard", "midi", "large", "standard", "large", "standard"]
    need = scale.spare_regular
    for btype in pref:
        if need == 0:
            break
        cand = [b for b in buses if b["bus_type"] == btype and b["fleet_role"] == "route"]
        if cand:
            cand[-1]["fleet_role"] = "spare"
            need -= 1
    acc_buses = [b for b in buses if b["is_accessible"]]
    for b in acc_buses[len(acc_buses) - scale.spare_accessible:] if scale.spare_accessible else []:
        b["fleet_role"] = "spare"
    return buses


def build_drivers(scale, buses, rng, last_day):
    n = scale.buses + max(1, math.ceil(0.06 * scale.buses))
    n_trained = scale.accessible_buses + 1
    drivers = []
    order = list(range(n))
    rng.shuffle(order)
    trained = set(order[:n_trained])
    extra_trained = set(i for i in order[n_trained:] if rng.random() < 0.08)
    for i in range(n):
        drivers.append({
            "driver_id": ids.driver(i + 1),
            "display_name": f"Driver {rng.choice(DRIVER_SURNAMES)} {chr(65 + i % 26)}.",
            "license_class": "PSV-HEAVY",
            "license_expiry": rand_date(rng, geo.add_days(last_day, 30), "2031-12-31"),
            "accessible_trained": i in trained or i in extra_trained,
            "employment_status": "active", "hired_on": rand_date(rng, "2010-01-01", "2025-12-31"),
        })
    # a couple of untrained surplus drivers are on leave (excluded from rostering)
    surplus = n - scale.buses
    untrained = [d for d in drivers if not d["accessible_trained"]]
    for d in untrained[-max(0, surplus - 2):] if surplus > 2 else []:
        d["employment_status"] = "on_leave"
    return drivers


# ------------------------------------------------------------------ students
def build_students(scale, zones, zone_weights, stops, days, rng):
    zone_ids = [z["zone_id"] for z in zones]
    zone_by_id = {z["zone_id"]: z for z in zones}
    approved = [s for s in stops if s["approval_status"] == "approved"]
    by_zone = {zid: [s for s in approved if s["zone_id"] == zid] for zid in zone_ids}
    n_days = len(days)
    students = []
    for i in range(1, scale.students + 1):
        sid = ids.student(i)
        grade = weighted_choice(rng, C.GRADES, GRADE_WEIGHTS)
        u = rng.random()
        aid = "wheelchair" if u < 0.010 else ("walker" if u < 0.018 else ("other" if u < 0.025 else "none"))
        needs_access = aid != "none"
        if rng.random() < 0.07 and not needs_access:
            r, a = rng.uniform(0.4, 1.55), rng.uniform(0, 2 * math.pi)
            p = (r * math.cos(a), r * math.sin(a))
        else:
            zid = weighted_choice(rng, zone_ids, [zone_weights[z] for z in zone_ids])
            pool = by_zone[zid]
            if needs_access and rng.random() < 0.9:
                pool = [s for s in pool if s["is_accessible"]] or pool
            anchor = rng.choice(pool)
            dist = min(2.5, math.exp(rng.gauss(math.log(0.22), 0.7)))
            a = rng.uniform(0, 2 * math.pi)
            p = (anchor["x_km"] + dist * math.cos(a), anchor["y_km"] + dist * math.sin(a))
            r = geo.radius(p)
            rmax = geo.max_radius() * 0.995
            if r > rmax:
                p = (p[0] * rmax / r, p[1] * rmax / r)
            elif r < 0.3:
                p = (0.3, p[1])
        p = (geo.snap(p[0]), geo.snap(p[1]))
        z = zone_of(p, zones, scale)
        dist_school = round(geo.radius(p), 2)
        cap = min(z["max_walk_m"], C.GRADE_WALK_CAP_M.get(grade, C.DEFAULT_GRADE_WALK_CAP_M),
                  C.MOBILITY_WALK_CAP_M.get(aid, 10 ** 6))
        young = grade in ("KG", "1", "2")
        mid = grade in ("3", "4", "5")
        ws, we = C.DEFAULT_WINDOW
        if rng.random() < (0.35 if young else 0.2 if mid else 0.1):
            ws = rng.choice(["06:50", "07:00", "07:10"])
        if rng.random() < 0.06:
            we = rng.choice(["07:15", "07:25"])
        if geo.to_min(we) - geo.to_min(ws) < 15:
            we = geo.hhmm(geo.to_min(ws) + 25)
        # enrollment lifecycle
        if rng.random() < 0.04 and n_days > 8:
            enrolled = days[rng.randint(4, max(5, int(n_days * 0.75)))]["service_date"]
        else:
            enrolled = rand_date(rng, "2026-03-01", "2026-06-05")
        withdrawn = None
        if rng.random() < 0.03:
            first_idx = next((k for k, dd in enumerate(days) if dd["service_date"] > enrolled), 0)
            lo = first_idx + 5
            if lo < n_days - 1:
                withdrawn = days[rng.randint(lo, n_days - 1)]["service_date"]
        students.append({
            "student_id": sid,
            "display_name": f"{rng.choice(GIVEN)} {rng.choice(SURNAME_INITIALS)}.",
            "grade": grade, "home_zone_id": z["zone_id"],
            "home_x_km": p[0], "home_y_km": p[1],
            "address_line": f"House {rng.randint(1, 899)}, {C.ADDRESS_MARKER} {rng.randint(1, 60)}, "
                            f"{zone_by_id[z['zone_id']]['zone_name']}",
            "address_status": "verified" if rng.random() < 0.988 else "pending",
            "distance_to_school_km": dist_school,
            "transport_eligible": dist_school >= C.WALK_ZONE_KM,
            "transport_opt_in": rng.random() < 0.93,
            "mobility_aid": aid, "requires_accessible_vehicle": needs_access,
            "max_walk_m": cap, "pickup_window_start": ws, "pickup_window_end": we,
            "enrollment_status": "withdrawn" if withdrawn else "active",
            "enrolled_on": enrolled, "withdrawn_on": withdrawn,
        })
    return students


def add_home_requests(stops, students, zones, n, rng):
    """Guardian requests for a stop at the home address. They stay *pending*:
    approving a residence as a public stop needs a safety review, and the
    planner never uses unapproved stops (the anomaly injector later breaks this
    rule on purpose for a labelled subset)."""
    zone_name = {z["zone_id"]: z["zone_name"] for z in zones}
    pool = [s for s in students if s["transport_eligible"] and s["transport_opt_in"]
            and not s["requires_accessible_vehicle"] and s["address_status"] == "verified"]
    picks = rng.sample(pool, min(n, len(pool)))
    picks.sort(key=lambda s: s["student_id"])
    for j, s in enumerate(picks, start=1):
        stops.append({
            "stop_id": None, "zone_id": s["home_zone_id"],
            "stop_name": f"{zone_name[s['home_zone_id']]} Request Point {j:02d}",
            "x_km": s["home_x_km"], "y_km": s["home_y_km"],
            "approval_status": "pending", "approval_date": None, "is_accessible": False,
            "safety_rating": "B", "stop_source": "guardian_request",
            "effective_from": rand_date(rng, "2026-04-01", "2026-05-28"), "effective_to": None,
            "_requested_by": s["student_id"],
        })


def number_stops(stops):
    """Assign immutable STOP ids once the full stop set exists (zone, then angle order)."""
    def key(s):
        ang = math.degrees(math.atan2(s["y_km"], s["x_km"])) % 360
        return (s["zone_id"], round(ang, 4), round(geo.radius((s["x_km"], s["y_km"])), 4))
    stops.sort(key=key)
    for i, s in enumerate(stops, start=1):
        s["stop_id"] = ids.stop(i)
    return stops


def build_contacts(students, days, rng):
    contacts = []
    n = 0
    n_days = len(days)
    for s in students:
        k = 1 if rng.random() < 0.25 else (2 if rng.random() < 0.85 else 3)
        rels = ["mother", "father"] if rng.random() < 0.8 else ["guardian", "grandparent"]
        rels += ["grandparent", "other"]
        for p in range(1, k + 1):
            n += 1
            cid = ids.contact(n)
            rel = rels[p - 1]
            status, consent, phone = "active", True, f"+999-555-{n:07d}"
            u = rng.random()
            bad_rate = 0.008 if p == 1 else 0.06
            if u < bad_rate * 0.35:
                status = "bounced"
            elif u < bad_rate * 0.65:
                status = "inactive"
            elif u < bad_rate * 0.85:
                phone = f"+999-555-{n % 100000:05d}"          # malformed: 5 digits
            elif u < bad_rate:
                consent = False
            row = {
                "contact_id": cid, "student_id": s["student_id"], "relationship": rel,
                "contact_label": f"Guardian {p} ({rel})", "phone": phone,
                "email": f"{cid.lower()}@example.org",
                "preferred_channel": weighted_choice(rng, C.CHANNELS, [0.55, 0.15, 0.30]),
                "priority": p, "consent_to_notify": consent, "contact_status": status,
                "valid_from": min(s["enrolled_on"], "2026-05-01"), "valid_to": None, "superseded_by": None,
            }
            contacts.append(row)
            # effective-dated replacement (old row kept, never overwritten in place)
            if status == "active" and phone.count("-") == 2 and rng.random() < 0.02 and n_days > 12:
                cut = days[rng.randint(5, n_days - 5)]["service_date"]
                n += 1
                new_id = ids.contact(n)
                row.update(valid_to=cut, contact_status="inactive", superseded_by=new_id)
                contacts.append(dict(row, contact_id=new_id, phone=f"+999-555-{n:07d}",
                                     email=f"{new_id.lower()}@example.org",
                                     contact_status="active", valid_from=geo.add_days(cut, 1),
                                     valid_to=None, superseded_by=None))
    return contacts
