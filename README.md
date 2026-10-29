# School Transport Assignment - Synthetic Data, Rules Engine & Validation

Round 2 code challenge - *Associate AI Forward Deployed Engineer*.

An end-to-end, reproducible workflow that assigns students to stops and bus routes
while respecting **bus capacity, pickup windows, safety/accessibility rules and daily
attendance**, notifies guardians, and proves its own correctness:

1. generates synthetic master data (students, guardian contacts, zones, stops, buses, drivers),
2. plans routes (route candidates with travel times -> selected plan) and assigns students,
3. replays the school year (capacity changes, joiners, leavers, overrides, waitlist retries) as an
   append-only event history,
4. simulates 200 school days of disruptions, attendance and guardian notifications,
5. injects the five required edge cases with a **separate ground truth**,
6. exports CSV / JSON / SQL, then **re-reads the files** to run 21 integrity checks and an
   independent business-rule detector scored against the ground truth,
7. regenerates with the same seed and compares checksums.

Pure Python standard library - no packages to install.

---

## Quick start

Requires Python 3.9+ (tested on 3.10 and 3.13). Run every command from this folder.
On Windows use `py` (or `python`); on macOS/Linux use `python3`.

```bash
# 1. tests (30 tests, ~2 s)
python -m unittest discover -s tests -v          # or: python -m pytest -q

# 2. starter dataset (600 students, 30 days) - ~1 s
python -m transport generate --scale starter

# 3. full dataset required by the brief (5,000 students, 100 buses, 300 stops, 200 days) - ~1 min
python -m transport generate --scale full

# 4. reproducibility proof (regenerates twice + once with a different seed)
python -m transport repro --scale full

# everything above for starter + full in one go (~3 min)
python -m transport all
```

Other commands:

| Command | Purpose |
|---|---|
| `python -m transport generate --scale full --seed 20261022 --out output/full --formats csv,json.gz,sql.gz` | explicit form (all options) |
| `python -m transport validate --data output/full` | re-run validation + detection on existing files |
| `python -m transport docs` | regenerate `docs/data_dictionary.md` and `docs/schema.sql` from the schema |

Scales (`transport/config.py`, same generator for all): `tiny` (tests), `starter`, `full`.
Fixed default seed **20261022**. Full-scale JSON/SQL are gzip-compressed by default
(about 300 MB -> 20 MB); pass `--formats csv,json,sql` for plain files.

## What you get

```
output/<scale>/
  data/csv/<table>.csv            16 tables (always written; validation reads these)
  data/json/<table>.json[.gz]     same rows as JSON arrays
  data/sql/schema.sql             DDL with PK / FK / CHECK constraints
  data/sql/seed.sql[.gz]          INSERTs (loads into SQLite with zero FK violations)
  ground_truth/ground_truth.csv   labelled anomalies + expected decisions (+ .json)
  reports/summary.md              key metrics, decision mix, detection scores
  reports/metrics.json            all measurable outputs
  reports/validation_summary.*    21 integrity checks with counts and examples
  reports/detection_report.json   every detector finding + precision/recall vs ground truth
  reports/decision_exceptions.csv traceable log of every non-standard decision
  reports/reproducibility.json    per-file checksums of two same-seed runs
  manifest.json                   generator version, command, seed, scale, provenance, file checksums
  data_dictionary.md
docs/design.md                    workflow, ER diagram, lifecycles, rules, actors, edge cases
docs/data_dictionary.md           every field: type, required, enum/pattern, unit, unique, FK, rule
docs/schema.sql
```

Load the SQL: `sqlite3 transport.db < output/starter/data/sql/schema.sql` then `< seed.sql`
(for `.gz` files decompress first).

## Results (full scale, seed 20261022)

| Metric | Value |
|---|---|
| Rows | 5,000 students · 9,564 contacts · 300 stops · 100 buses · 106 drivers · 76 routes · 5,233 assignment events · 758,642 attendance events · 54,231 notifications |
| Integrity validation | **21 / 21 checks pass** (PK, FK, enums, patterns, date order, arithmetic, lifecycle, attendance-vs-history, privacy, ground-truth separation) |
| Anomaly detection vs ground truth | **40 labelled, 40 detected, precision 1.0, recall 1.0**; 0 findings on a clean baseline |
| Reproducibility | 36 / 36 output files byte-identical across two runs; 31 change with seed + 1; identical checksums on Python 3.10 and 3.13 |
| Assignment rate (eligible students) | 92.97 % (rest waitlisted with a reason: no stop in walking range, address pending, no accessible stop, capacity) |
| Pickup-window compliance | 96.05 % (154 documented `ASSIGNED_WINDOW_EXCEPTION`s, each with a guardian notice) |
| Accessibility | 100 % of accessible-need students placed on accessible routes |
| Ride time | mean 30 min, p95 55, max 60 (hard limit 60) |
| Bus utilisation at plan | mean 77 %, max 91.7 % (plan cap 90 % of seats + headroom) |
| Daily operations | 5.9 % absence, 95.8 % on-time pickups, 1.8 % missed pickups (all linked to a disruption), 816 disruptions incl. 53 cancellations |
| Notifications | 0.58 % suppressed because no valid guardian contact existed |

Run-specific numbers are regenerated in `output/<scale>/reports/summary.md`.

## How the brief maps to the code

| Brief requirement | Where |
|---|---|
| Master data first, then dependent records with valid parent IDs | `transport/master.py` -> `planning.py` -> `lifecycle.py` -> `operations.py` (orchestrated in `pipeline.build`) |
| Addresses/zones, approved stops, capacities, accessible vehicles | `master.py` (ring x sector zones, approval workflow, fleet mix with lift buses) |
| Route candidates and travel times | `planning.py`: 3 orderings per route stored in `route_candidate` with duration, distance, max leg speed, feasibility, rank, rejection reason |
| Assign students to stops/routes (capacity, windows, safety) | `planning.py` + `lifecycle.py`; rules in `rules.py`, constants in `config.py`; table in `docs/design.md` §4 |
| Daily attendance, missed pickups | `operations.py` (per student per day, driven by persisted events) |
| Notify guardians (synthetic contacts) | `operations.Notifier` with contact fallback / suppression; `+999-555-…` phones, `@example.org` e-mail |
| State changes as events, no overwritten history | `assignment_event`, `bus_capacity_event`, `route_disruption`, `attendance_event`, effective-dated contacts/stops |
| Outcomes from rules, not random labels | attendance status, delivery status, window_ok, utilisation, current_status etc. are derived; the validator recomputes them |
| Data dictionary (type, required, enum, unit, unique, rule) | `transport/schema.py` -> `docs/data_dictionary.md` |
| PK/FK, cardinality, bridge tables, lifecycle, effective dates | `schema.py` (`RELATIONSHIPS`), `route_stop` bridge, `docs/design.md` §2-3 |
| ID conventions `STU-000001`, `STOP-000001`, `BUS-000001`, `ROUTE-2026-000001`, `ASN-<student-id>-2026`, `NOT-2026-000001` | `transport/ids.py`; enforced by patterns in the schema |
| 5,000 students / 100 buses / 300 stops / 200 days, parameterised scale, fixed seed | `config.SCALES`, `--scale`, `--seed` |
| Capacity changes, absences, disruptions, accessibility | capacity events (engine reassigns/waitlists), heterogeneous absence model, 4 disruption types + severe-weather cancellations, wheelchair/walker users |
| Edge cases: capacity exceeded, incompatible route, impossible travel time, invalid contact, unapproved address | `transport/anomalies.py` (+ `docs/design.md` §6) |
| Separate ground truth, not leaked | `ground_truth/` folder; validator checks no label columns in inputs |
| Validation: PK, FK, enums, date ordering, reconciliation, lifecycle, duplicates | `transport/validate.py` (reads the CSVs back) |
| Export CSV/JSON/SQL + README, schema, command, seed, manifest, validation summary | `storage.py`, `pipeline.py`, this README |
| Regenerate twice and compare checksums | `python -m transport repro` -> `reports/reproducibility.json` |
| Tests | `tests/test_rules.py` (unit), `tests/test_pipeline.py` (acceptance, negative and reproducibility tests) |

## Design highlights

* **One schema, three uses.** `schema.py` defines every table once; the data dictionary, SQL DDL,
  CSV type parsing and generic validation checks are all generated from it, so they cannot drift.
* **Decisions are explainable.** Every assignment has a reason code, every change an event with
  actor and trigger (`BCE-…` for capacity changes), and `decision_exceptions.csv` lists all
  non-standard decisions.
* **Detector is independent of the generator.** It only sees the exported CSVs; a clean baseline
  run (`anomalies_per_type=0`) produces zero findings, the anomaly run produces exactly the labelled set.
* **Anomalies do not break integrity.** Defects are business-rule violations inside otherwise valid
  records (derived values are recomputed), so integrity checks still pass and the detector has to
  reason about the business rules.
* **Privacy by construction.** Abstract km coordinates snapped to a 50 m grid, unroutable phone
  numbers, reserved e-mail domain, addresses marked `Synth Street`, messages carry IDs/times only,
  no birth dates or medical details (only the mobility aid needed to choose a vehicle).

## Data provenance and lawful use

No external data is used. Every value is produced by this generator from the fixed seed; no
public or personal dataset was downloaded or sampled (`manifest.json -> provenance`). Names are
drawn from a short list of common first names plus an initial and are not linked to real people.
The generated data can be redistributed freely.

## Project layout

```
transport/
  config.py      scales, business-rule constants, enums
  schema.py      tables, fields, relationships -> dictionary + DDL
  ids.py         ID formats + per-stage seeded RNG
  geo.py         distances, travel times, clock helpers
  rules.py       eligibility, capacity book, contact validity, event -> segment timelines
  master.py      master data generation
  planning.py    stop choice, sweep routing, candidates, window repair, derived route fields
  lifecycle.py   school-year replay -> assignment_event
  operations.py  disruptions, attendance, notifications
  anomalies.py   labelled edge-case injection + ground truth
  validate.py    integrity checks on exported CSVs
  detect.py      business-rule detector + precision/recall
  metrics.py     measurable outputs
  storage.py     CSV / JSON / SQL writers, typed CSV reader
  pipeline.py    orchestration, reports, manifest, reproducibility
tests/           unittest suite (pytest-compatible)
docs/            design notes, data dictionary, schema.sql
output/          generated starter + full datasets with reports
```
