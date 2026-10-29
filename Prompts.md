## Stage 1 - Foundations: config, IDs, geography

**Prompt**
> I'm building a reproducible synthetic school-transport dataset in pure Python 3.9+ (stdlib only). Start
> with the foundations. Create `transport/config.py` with scale presets (tiny for tests, starter, full =
> 5,000 students / 100 buses / 300 stops / 200 school days), a fixed default seed, and every business-rule
> constant in one place: walk-zone 1.6 km, grade and mobility walking caps, 60-minute route limit, 90%
> plan load, 70 km/h feasibility limit, pickup windows, late/missed thresholds. Create `transport/ids.py`
> with ID builders (`STU-000001`, `STOP-000001`, `BUS-000001`, `ROUTE-2026-000001`,
> `ASN-<student-id>-2026`, `NOT-2026-000001`) and `stage_rng(seed, stage)` that derives an independent
> random stream per pipeline stage from SHA-256. Create `transport/geo.py` for distances, ring-based
> travel times, 50 m coordinate snapping and clock helpers. Add unit tests for ID formats and RNG stability.

**Verify:** tests pass; `stage_rng(1,"a")` is stable across runs and differs from `stage_rng(1,"b")`.
**Learn:** why one RNG per stage keeps results reproducible when you edit one stage.

## Stage 2 - Schema as the single source of truth

**Prompt**
> Create `transport/schema.py` defining all 16 tables once: school_day, address_zone, stop, bus, driver,
> student, guardian_contact, route, route_candidate, route_stop (N:M bridge), assignment,
> assignment_event (append-only), bus_capacity_event, route_disruption, attendance_event, notification.
> Each field needs type, required, enum or regex pattern, unit, unique, foreign key and a rule note. Add
> effective-dating fields where history matters. From this one definition generate the data dictionary
> markdown and SQL DDL with PK/FK/CHECK constraints.

**Verify:** `python -m transport docs` writes `docs/data_dictionary.md` and `docs/schema.sql`; load the SQL into SQLite.
**Learn:** one definition feeding dictionary, DDL, parsing and validation cannot drift.

## Stage 3 - Master data

**Prompt**
> Create `transport/master.py` that builds, in dependency order: school calendar (skip weekends and
> holidays), urban/suburban/rural zones, stops with an approval workflow (approved/pending/rejected, some
> guardian-requested), a bus fleet including wheelchair-lift buses and spares, drivers (some
> accessible-trained), students with grades, mobility aids and pickup windows, and 1-3 effective-dated
> guardian contacts per student. Use only synthetic values: phones `+999-555-nnnnnnn`, e-mails
> `@example.org`, addresses containing "Synth Street".

**Verify:** row counts match the scale; every foreign key resolves; no phone or email outside the patterns.
**Learn:** why parents must exist before children.

## Stage 4 - Rules shared by generator and checker

**Prompt**
> Create `transport/rules.py` holding business logic that both the generator and the later detector must
> share: eligibility (`pre_assignment_outcome`), which network a student needs, whether a stop is usable
> for a student (approved, within the smallest applicable walking cap, accessible if needed), pickup-window
> check, a `CapacityBook` giving a bus's effective seats on a date from base capacity plus effective-dated
> events, contact validity with reasons, highest-priority valid contact selection, conversion of assignment
> events to dated route segments, and the allowed assignment state transitions.

**Verify:** unit tests for window boundaries (inclusive), each invalid-contact reason, capacity before/after an event.
**Learn:** sharing rules prevents generator and detector from disagreeing.

## Stage 5 - Annual planning

**Prompt**
> Create `transport/planning.py`. For eligible students pick the nearest usable stop. Build routes by
> angle sweep around the school, closing a bus when 90% of seats, wheelchair positions or the 60-minute
> limit would be exceeded; when buses run out, waitlist with a reason. For every route evaluate three stop
> orderings (radial inbound, nearest-neighbour, 2-opt), store all in `route_candidate` with duration,
> distance, max leg speed, feasibility and rejection reason, and pick the best feasible. Then repair pickup
> windows: shift the route arrival between 07:35 and 07:50, then move violators to another stop with a free
> seat, else keep them with a documented window exception.

**Verify:** no route over 60 minutes; no leg over 70 km/h; accessible-need students only on accessible routes.
**Learn:** sweep clustering, candidate comparison, and the exception path.

## Stage 6 - Year replay with events

**Prompt**
> Create `transport/lifecycle.py` that replays the school year day by day and records every change as an
> append-only `assignment_event` with reason code, actor and trigger: withdrawals, mid-year joiners, bus
> capacity reductions (move the overflow to another route with a seat or waitlist), administrator
> overrides, and weekly waitlist retries. Never overwrite history, and enforce the allowed state transitions.

**Verify:** replaying events reproduces each assignment's final status; no illegal transition exists.
**Learn:** event sourcing versus updating rows in place.

## Stage 7 - Daily operations

**Prompt**
> Create `transport/operations.py`. From the persisted events only, work out who rides which route each
> school day. Generate disruptions (traffic delay, breakdown with spare bus, driver absence with spare
> driver, weather including cancellations), then per-student attendance where status is derived from
> arrival time versus schedule (on time, boarded late, missed pickup, no-show, absent). Add guardian
> notifications that use the first valid contact or are suppressed with a reason, and never contain home
> addresses.

**Verify:** no attendance before enrolment, after withdrawal, or for waitlisted students; missed pickups link to disruptions.
**Learn:** randomness drives causes, rules drive outcomes.

## Stage 8 - Planting edge cases with separate ground truth

**Prompt**
> Create `transport/anomalies.py` that injects exactly the five required defects with a count per type:
> capacity exceeded, incompatible route (wheelchair student on a regular bus), impossible travel time,
> notification to an invalid contact, and an unapproved address exposed. Keep the records parse-valid so
> integrity checks still pass. Write labels, expected decisions and violated rules to a separate
> `ground_truth/` folder that no input table references.

**Verify:** the validator still passes after injection; ground-truth columns appear in no input table.
**Learn:** why business defects, not corrupted fields, make a meaningful test.

## Stage 9 - Storage, validation, detection

**Prompt**
> Create `transport/storage.py` (CSV, JSON, SQL writers, typed CSV reader, SHA-256), `validate.py` that
> re-reads the exported CSVs and runs 21 integrity checks (PK, FK, enums, patterns, uniqueness, date order,
> arithmetic, lifecycle, attendance versus history, duplicates, privacy, no ground-truth leakage), and
> `detect.py`, an independent detector for the five defect types that sees only exported tables, plus an
> `evaluate` function computing precision and recall against ground truth.

**Verify:** 21/21 checks pass; recall and precision 1.0; a clean run (no injected defects) yields zero findings.
**Learn:** why the validator reads files, not memory.

## Stage 10 - Orchestration, CLI, reproducibility, tests, docs

**Prompt**
> Create `transport/pipeline.py` and `__main__.py` with commands `generate`, `validate`, `repro`, `docs`,
> `all`. Write a manifest (version, seed, scale, command, provenance, file checksums), a summary report,
> metrics, a decision-exceptions log, and a reproducibility check that regenerates twice with the same seed
> (identical checksums) and once with seed+1 (different). Finish with unit and end-to-end tests (including
> negative tests with broken FKs and duplicate PKs), a README with run instructions, and `docs/design.md`
> with workflow, ER and state diagrams.

**Verify:** `python -m unittest discover -s tests -v` shows 30 tests OK; `python -m transport repro --scale full` reports identical checksums.
**Learn:** reproducibility as a testable property.
