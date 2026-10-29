# Run summary - scale `full`, seed `20261022`

Validation: **PASS** (21/21 integrity checks)

## Key metrics

| Metric | Value |
|---|---|
| Students | 5000 |
| Assignment rate (of eligible) | 92.97% |
| Pickup-window compliance | 96.05% |
| Accessible-need students on accessible routes | 100.0% |
| Ride time mean / p95 / max (min) | 30.11 / 55 / 60 |
| Walk to stop mean / p95 (m) | 271.9 / 560 |
| Routes (regular / accessible) | 63 / 13 |
| Bus utilisation at plan mean / max | 76.61% / 91.7% |
| Route duration mean / max (min) | 48.85 / 59.7 |
| Attendance events | 758642 |
| Absence rate | 5.86% |
| On-time / late / missed pickup (of present) | 95.76% / 2.45% / 1.79% |
| Disruptions | 816 (5.37% of route-days) |
| Notifications (suppressed: no valid contact) | 54231 (0.58%) |

## Decision mix

| Reason | Count |
|---|---|
| ASSIGNED_NEAREST_STOP | 3592 |
| INELIGIBLE_WALK_ZONE | 496 |
| OPTED_OUT_GUARDIAN | 310 |
| WAITLIST_NO_STOP_IN_RANGE | 221 |
| ASSIGNED_WINDOW_EXCEPTION | 154 |
| MIDYEAR_ASSIGNED | 143 |
| WAITLIST_ADDRESS_PENDING | 45 |
| WAITLIST_NO_ACCESSIBLE_STOP | 26 |
| ASSIGNED_ALT_STOP_FOR_WINDOW | 10 |
| WAITLIST_NO_CAPACITY | 3 |

## Anomaly detection vs ground truth

| Issue type | Labelled | Detected | TP | FP | FN | Precision | Recall |
|---|---|---|---|---|---|---|---|
| capacity_exceeded | 8 | 8 | 8 | 0 | 0 | 1.0 | 1.0 |
| incompatible_route | 8 | 8 | 8 | 0 | 0 | 1.0 | 1.0 |
| impossible_travel_time | 8 | 8 | 8 | 0 | 0 | 1.0 | 1.0 |
| notification_invalid_contact | 8 | 8 | 8 | 0 | 0 | 1.0 | 1.0 |
| unapproved_address_exposed | 8 | 8 | 8 | 0 | 0 | 1.0 | 1.0 |
| overall | 40 | 40 | 40 | 0 | 0 | 1.0 | 1.0 |
