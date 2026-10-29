# Reasoning: problem, assumptions, decisions, trade-offs, testing, limits

This page makes the thinking behind the solution visible. Each claim points to code, a test or a generated
report, so a reviewer can check it.

## 1. The problem as I read it

The brief asks for a workflow that assigns students to bus stops and routes while respecting capacity,
pickup windows, safety/accessibility rules and daily attendance, notifies guardians, and demonstrates its
own correctness on synthetic data. Three things follow from that wording:

* There is **no input dataset**, so data generation is part of the deliverable, and it must be reproducible.
* Outcomes must come **from rules, not random labels**, so rules need to be explicit and testable.
* The checker must find known defects, so the **answer key must exist separately** from the data it grades.

So the project is a simulator plus an independent auditor, not just an assignment algorithm.

## 2. Assumptions (where the brief was silent)

| Assumption | Why | Where it lives |
|---|---|---|
| One campus, morning (AM) run only | Afternoon is symmetric and doubles volume without new rules | `docs/design.md` s.8 |
| Distance = straight line x 1.3 road circuity; walking x 1.2 | No road network is available; a constant factor is transparent | `config.ROAD_CIRCUITY`, `WALK_CIRCUITY` |
| Bus speed depends on ring (urban 18, suburban 28, rural 38 km/h) | City buses are slower; gives believable ride times | `config.RINGS` |
| Walk zone 1.6 km, walking caps by grade and mobility aid | Typical policy shape; all adjustable | `config.py` |
| Plan fills buses to 90% | Leaves headroom for mid-year joiners and capacity cuts | `PLAN_LOAD_FACTOR` |
| 60-minute maximum ride | Common safety limit; also bounds route length | `MAX_ROUTE_MIN` |
| Any leg above 70 km/h is infeasible | Needed to define "impossible travel time" | `MAX_FEASIBLE_SPEED_KMPH` |
| Routes are fixed for the year | Keeps the model explainable; changes happen to assignments, not routes | `docs/design.md` s.8 |
| Contacts use unroutable phones and the reserved `example.org` domain | Guarantees no real person can be contacted | `config.PHONE_PATTERN`, `EMAIL_PATTERN` |

All of these are constants in one file, so changing an assumption is one edit.

## 3. Key decisions and the reason for each

1. **Pure standard-library Python.** Reviewers can run it with no setup. Cost: no pandas/numpy convenience, so
   I wrote small helpers (`storage.iter_rows`, `metrics.quantile`).
2. **One schema file drives everything.** `schema.py` generates the data dictionary, SQL DDL, CSV parsing and
   generic validation. Reason: documentation that is generated from the validator cannot drift from it.
3. **Parents before children.** Generation order is master data -> plan -> lifecycle -> operations, because every
   child row needs a valid parent ID (a student needs a zone, an assignment a student and a route).
4. **State changes are append-only events.** `assignment_event`, `bus_capacity_event`, `route_disruption` are never
   edited. Reason: the brief forbids overwritten history, and events make "what was true on date X?" answerable.
5. **Business rules are shared code.** `rules.py` is imported by the generator and by the detector so they cannot
   hold different definitions of "capacity" or "valid contact".
6. **Defects are business violations inside valid rows.** If an injected defect were a corrupt field, the integrity
   checker would catch it and the detector would prove nothing. Keeping rows parse-valid forces the detector to
   reason about rules.
7. **Ground truth is a separate folder.** `validate.py` checks that no label columns appear in input tables.
8. **One random stream per stage.** `ids.stage_rng(seed, stage)` hashes the seed with the stage name, so editing
   one stage does not reshuffle the others.
9. **Validation reads the exported files.** It tests what a reviewer receives, not the generator's memory.
10. **Exceptions are explicit, not silent.** If a pickup window cannot be met the student is kept with the reason
    `ASSIGNED_WINDOW_EXCEPTION` and the guardian is notified, instead of dropping them or hiding the violation.

## 4. Trade-offs

| Choice | Benefit | Cost |
|---|---|---|
| Heuristic routing (angle sweep + 3 orderings) instead of an optimal solver | Fast, deterministic, explainable | Routes are good, not minimal; no proof of optimality |
| Shared rules between generator and detector | Consistent definitions | A rule misunderstanding would affect both (see limitations) |
| Flat plane geometry | No external map data, fully synthetic | Not realistic road distances |
| 90% load cap | Absorbs changes without constant waitlisting | About 10% of seats unused at plan time (mean utilisation 77%) |
| Gzip JSON/SQL at full scale | 300 MB becomes about 20 MB | Need to decompress to read |
| Moving window violators to alternative stops | Higher compliance | Some students walk slightly farther |

## 5. How the solution is tested

Three layers, run with `python -m unittest discover -s tests -v` (30 tests, about 2 seconds).

1. **Unit tests (`tests/test_rules.py`).** Each rule in isolation: ID formats, RNG stability and independence,
   eligibility, inclusive window boundaries, accessible-stop requirement, capacity before/after an event, each
   invalid-contact reason, event-to-timeline conversion, the transition table, route speed feasibility.
2. **End-to-end tests (`tests/test_pipeline.py`).** Generate a small dataset and assert business properties:
   capacity and walk limits respected, accessible-need students only on accessible routes, notices only to valid
   contacts, no attendance outside enrolment or for waitlisted students, status rules hold, SQL loads into SQLite
   with foreign keys enforced.
3. **Negative tests.** Deliberately break a foreign key and duplicate a primary key and assert the validator
   fails. A checker that cannot fail proves nothing.

Plus a **clean-baseline test**: with zero injected defects the detector returns zero findings, which shows it does
not invent problems.

## 6. How I know the solution works

| Claim | Evidence | Where |
|---|---|---|
| Data is internally consistent | 21 of 21 integrity checks pass on the exported CSVs | `reports/validation_summary.md` |
| Rules were applied | Window compliance 96.05% with 154 documented exceptions; 100% of accessible-need students on accessible routes; max ride 60 min | `reports/summary.md` |
| The detector finds real defects | 40 labelled, 40 detected, precision 1.0, recall 1.0 | `reports/detection_report.json` |
| The detector does not hallucinate | 0 findings on a clean baseline | `test_clean_baseline_has_no_rule_violations` |
| Output is reproducible | 36 of 36 files byte-identical across two runs with the same seed; 31 files differ with seed+1 | `reports/reproducibility.json` |
| Works across Python versions | Same fingerprint on Python 3.10 and 3.13 | verified manually |
| Privacy by construction | Pattern checks on phones, emails and addresses, no addresses in messages | validation check `synthetic_and_minimised_contact_data` |

Bugs found by this testing and fixed: a duplicate-notice false positive in the validator, a false impossible-travel
finding on very short legs, and injected defects interfering with each other and with engine-handled capacity cuts.

## 7. Limitations and what they mean

* **Precision and recall of 1.0 shows self-consistency, not real-world accuracy.** The injector and detector were
  written against the same rule definitions. It proves the detector implements the rules; it does not prove the
  rules are the right ones for a real district.
* **Heuristic routes are not optimal.** Sweep plus 2-opt can be beaten by an exact or metaheuristic solver.
* **Synthetic geography.** Ride times are plausible, not real. Real deployment needs a routing engine.
* **AM session only, one campus, fixed routes for the year.**
* **Replacement-bus days are not re-checked for capacity by the detector**; the dispatcher only picks spares with
  enough seats, so this is assumed rather than verified.
* **Absence and delay models are simple distributions**, not fitted to real attendance data.

## 8. What I would do next

Add the PM run, replace circuity with a road graph, calibrate absence rates from real (consented) data, add a
solver-based route optimiser to compare against the heuristic, and extend the detector with rules that were not
used to generate the defects, to test it more independently.
