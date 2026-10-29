"""Deterministic, zero-padded, immutable identifiers."""
import hashlib
import random

from .config import SCHOOL_YEAR


def zone(n): return f"ZONE-{n:04d}"
def stop(n): return f"STOP-{n:06d}"
def bus(n): return f"BUS-{n:06d}"
def driver(n): return f"DRV-{n:06d}"
def student(n): return f"STU-{n:06d}"
def contact(n): return f"GC-{n:06d}"
def route(n, year=SCHOOL_YEAR): return f"ROUTE-{year}-{n:06d}"
def candidate(n, year=SCHOOL_YEAR): return f"RC-{year}-{n:06d}"
def route_stop(n, year=SCHOOL_YEAR): return f"RS-{year}-{n:06d}"
def assignment(student_id, year=SCHOOL_YEAR): return f"ASN-{student_id}-{year}"
def assignment_event(n, year=SCHOOL_YEAR): return f"AEV-{year}-{n:06d}"
def capacity_event(n, year=SCHOOL_YEAR): return f"BCE-{year}-{n:06d}"
def disruption(n, year=SCHOOL_YEAR): return f"DIS-{year}-{n:06d}"
def attendance(n, year=SCHOOL_YEAR): return f"ATT-{year}-{n:07d}"
def notification(n, year=SCHOOL_YEAR): return f"NOT-{year}-{n:06d}"


def stage_rng(seed: int, stage: str) -> random.Random:
    """Independent, reproducible RNG per generation stage.

    Uses SHA-256 rather than hash() so results do not depend on PYTHONHASHSEED,
    and so adding draws in one stage never shifts the random stream of another.
    """
    digest = hashlib.sha256(f"{seed}:{stage}".encode()).hexdigest()
    return random.Random(int(digest[:16], 16))
