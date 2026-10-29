"""Distance, travel-time and clock helpers (synthetic plane, km)."""
import datetime as dt
import math

from . import config as C


_RINGS = list(C.RINGS)


def configure(geo_scale=1.0):
    """Set the service-area scale for this run (radii shrink for small datasets)."""
    global _RINGS
    _RINGS = [(n, round(i * geo_scale, 3), round(o * geo_scale, 3), sp, w) for n, i, o, sp, w in C.RINGS]


def rings():
    return _RINGS


def max_radius():
    return _RINGS[-1][2]


def straight_km(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def radius(p):
    return math.hypot(p[0], p[1])


def ring_of(r):
    for i, (name, inner, outer, speed, walk) in enumerate(_RINGS):
        if r < outer:
            return i
    return len(_RINGS) - 1


def speed_at(p):
    return _RINGS[ring_of(radius(p))][3]


def road_km(a, b):
    return round(straight_km(a, b) * C.ROAD_CIRCUITY, 3)


def travel_min(a, b):
    """Bus travel minutes between two points (average of endpoint ring speeds)."""
    km = straight_km(a, b) * C.ROAD_CIRCUITY
    speed = (speed_at(a) + speed_at(b)) / 2.0
    if km <= 0:
        return 0.0
    return max(0.1, round(km / speed * 60.0, 1))


def walk_m(a, b):
    return int(round(straight_km(a, b) * 1000 * C.WALK_CIRCUITY))


def implied_speed_kmph(distance_km, minutes):
    if minutes <= 0:
        return float("inf") if distance_km > 0 else 0.0
    return distance_km / (minutes / 60.0)


def snap(v, step=C.COORD_PRECISION_KM):
    return round(round(v / step) * step, 3)


# ---------------------------------------------------------------- clock
def hhmm(minutes) -> str:
    m = int(round(minutes))
    return f"{m // 60:02d}:{m % 60:02d}"


def to_min(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def stamp(date: str, minutes) -> str:
    return f"{date}T{hhmm(minutes)}"


def d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def add_days(s: str, n: int) -> str:
    return (d(s) + dt.timedelta(days=n)).isoformat()
