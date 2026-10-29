# Validation summary

Overall: **PASS** (21/21 checks passed)

| Check | Category | Status | Records checked | Violations | Examples |
|---|---|---|---|---|---|
| csv_header_and_types | schema | PASS | 4559 | 0 |  |
| unique_constraints | keys | PASS | 4559 | 0 |  |
| date_ordering_and_effective_dating | dates | PASS | 4559 | 0 |  |
| derived_values_reconcile | arithmetic | PASS | 652 | 0 |  |
| route_structure_and_candidates | keys | PASS | 40 | 0 |  |
| assignment_lifecycle_transitions | lifecycle | PASS | 647 | 0 |  |
| disruption_consistency | operations | PASS | 17 | 0 |  |
| attendance_one_per_student_day | lifecycle | PASS | 11497 | 0 |  |
| attendance_reflects_assignment_history | lifecycle | PASS | 11497 | 0 |  |
| attendance_derived_fields | arithmetic | PASS | 11497 | 0 |  |
| attendance_status_rules | operations | PASS | 11497 | 0 |  |
| notification_per_exception_event | operations | PASS | 11497 | 0 |  |
| notification_triggers_and_delivery | operations | PASS | 1346 | 0 |  |
| required_fields_present | schema | PASS | 16056 | 0 |  |
| enum_values_allowed | schema | PASS | 16056 | 0 |  |
| id_and_format_patterns | schema | PASS | 16056 | 0 |  |
| foreign_key_integrity | keys | PASS | 16056 | 0 |  |
| primary_key_unique | keys | PASS | 16056 | 0 |  |
| synthetic_and_minimised_contact_data | privacy | PASS | 2492 | 0 |  |
| ground_truth_separate_and_resolvable | ground_truth | PASS | 15 | 0 |  |
| csv_header_and_types_attendance | schema | PASS | 11497 | 0 |  |

## Row counts

| Table | Rows |
|---|---|
| school_day | 30 |
| address_zone | 11 |
| stop | 45 |
| bus | 14 |
| driver | 15 |
| student | 600 |
| guardian_contact | 1146 |
| route | 10 |
| route_candidate | 30 |
| route_stop | 42 |
| assignment | 600 |
| assignment_event | 647 |
| bus_capacity_event | 6 |
| route_disruption | 17 |
| notification | 1346 |
| attendance_event | 11497 |
