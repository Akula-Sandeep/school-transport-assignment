# Validation summary

Overall: **PASS** (21/21 checks passed)

| Check | Category | Status | Records checked | Violations | Examples |
|---|---|---|---|---|---|
| csv_header_and_types | schema | PASS | 81261 | 0 |  |
| unique_constraints | keys | PASS | 81261 | 0 |  |
| date_ordering_and_effective_dating | dates | PASS | 81261 | 0 |  |
| derived_values_reconcile | arithmetic | PASS | 5441 | 0 |  |
| route_structure_and_candidates | keys | PASS | 304 | 0 |  |
| assignment_lifecycle_transitions | lifecycle | PASS | 5233 | 0 |  |
| disruption_consistency | operations | PASS | 816 | 0 |  |
| attendance_one_per_student_day | lifecycle | PASS | 758642 | 0 |  |
| attendance_reflects_assignment_history | lifecycle | PASS | 758642 | 0 |  |
| attendance_derived_fields | arithmetic | PASS | 758642 | 0 |  |
| attendance_status_rules | operations | PASS | 758642 | 0 |  |
| notification_per_exception_event | operations | PASS | 758642 | 0 |  |
| notification_triggers_and_delivery | operations | PASS | 54231 | 0 |  |
| required_fields_present | schema | PASS | 839903 | 0 |  |
| enum_values_allowed | schema | PASS | 839903 | 0 |  |
| id_and_format_patterns | schema | PASS | 839903 | 0 |  |
| foreign_key_integrity | keys | PASS | 839903 | 0 |  |
| primary_key_unique | keys | PASS | 839903 | 0 |  |
| synthetic_and_minimised_contact_data | privacy | PASS | 63795 | 0 |  |
| ground_truth_separate_and_resolvable | ground_truth | PASS | 40 | 0 |  |
| csv_header_and_types_attendance | schema | PASS | 758642 | 0 |  |

## Row counts

| Table | Rows |
|---|---|
| school_day | 200 |
| address_zone | 24 |
| stop | 300 |
| bus | 100 |
| driver | 106 |
| student | 5000 |
| guardian_contact | 9564 |
| route | 76 |
| route_candidate | 228 |
| route_stop | 365 |
| assignment | 5000 |
| assignment_event | 5233 |
| bus_capacity_event | 18 |
| route_disruption | 816 |
| notification | 54231 |
| attendance_event | 758642 |
