# Run summary - scale `starter`, seed `20261022`

Validation: **PASS** (21/21 integrity checks)

## Key metrics

| Metric | Value |
|---|---|
| Students | 600 |
| Assignment rate (of eligible) | 87.03% |
| Pickup-window compliance | 96.46% |
| Accessible-need students on accessible routes | 100.0% |
| Ride time mean / p95 / max (min) | 24.69 / 40 / 52 |
| Walk to stop mean / p95 (m) | 273.7 / 576 |
| Routes (regular / accessible) | 8 / 2 |
| Bus utilisation at plan mean / max | 62.2% / 91.7% |
| Route duration mean / max (min) | 38.22 / 52.4 |
| Attendance events | 11497 |
| Absence rate | 7.98% |
| On-time / late / missed pickup (of present) | 95.49% / 1.43% / 3.08% |
| Disruptions | 17 (5.94% of route-days) |
| Notifications (suppressed: no valid contact) | 1346 (0.45%) |

## Decision mix

| Reason | Count |
|---|---|
| ASSIGNED_NEAREST_STOP | 371 |
| INELIGIBLE_WALK_ZONE | 112 |
| WAITLIST_NO_STOP_IN_RANGE | 46 |
| OPTED_OUT_GUARDIAN | 33 |
| ASSIGNED_WINDOW_EXCEPTION | 14 |
| MIDYEAR_ASSIGNED | 9 |
| WAITLIST_NO_CAPACITY | 7 |
| WAITLIST_ADDRESS_PENDING | 5 |
| ASSIGNED_ALT_STOP_FOR_WINDOW | 2 |
| WAITLIST_NO_ACCESSIBLE_STOP | 1 |

## Anomaly detection vs ground truth

| Issue type | Labelled | Detected | TP | FP | FN | Precision | Recall |
|---|---|---|---|---|---|---|---|
| capacity_exceeded | 3 | 3 | 3 | 0 | 0 | 1.0 | 1.0 |
| incompatible_route | 3 | 3 | 3 | 0 | 0 | 1.0 | 1.0 |
| impossible_travel_time | 3 | 3 | 3 | 0 | 0 | 1.0 | 1.0 |
| notification_invalid_contact | 3 | 3 | 3 | 0 | 0 | 1.0 | 1.0 |
| unapproved_address_exposed | 3 | 3 | 3 | 0 | 0 | 1.0 | 1.0 |
| overall | 15 | 15 | 15 | 0 | 0 | 1.0 | 1.0 |
