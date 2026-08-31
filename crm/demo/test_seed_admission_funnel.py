from datetime import datetime

from crm.demo import seed_admission_funnel


def test_application_status_is_deterministic_for_supported_funnel_stages():
	assert seed_admission_funnel.application_status_for_stage("Enrolled", 0) == "Enrolled"
	assert seed_admission_funnel.application_status_for_stage("Applicant", 0) == "Accepted"
	assert seed_admission_funnel.application_status_for_stage("Applicant", 1) == "Under Review"
	assert seed_admission_funnel.application_status_for_stage("MQL", 0) == "Submitted"
	assert seed_admission_funnel.application_status_for_stage("Lead", 0) is None


def test_snapshot_date_is_stable_and_progresses_by_week():
	as_of = datetime(2026, 8, 31, 10, 0)
	first = seed_admission_funnel.snapshot_datetime(as_of, 0)
	second = seed_admission_funnel.snapshot_datetime(as_of, 10)

	assert first == datetime(2026, 6, 15, 10, 0)
	assert second == datetime(2026, 6, 22, 10, 0)


def test_source_reference_is_idempotent_and_private():
	first = seed_admission_funnel.application_source_reference("STU-1")
	second = seed_admission_funnel.application_source_reference("STU-1")

	assert first == second
	assert first.startswith(seed_admission_funnel.NAMESPACE)
	assert "@" not in first
