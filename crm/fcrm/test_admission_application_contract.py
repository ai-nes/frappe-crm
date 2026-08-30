from crm.fcrm.admission_application_migration import application_backfill_decision
from crm.fcrm.admissions_application_contract import application_projection


def test_application_projection_does_not_write_human_owned_fields():
	assert application_projection(
		{
			"major": "M-1",
			"campus": "HN",
			"admission_year": "2026",
			"status": "Enrolled",
			"owner_staff": "STAFF-1",
			"consent_status": "Granted",
		}
	) == {"major": "M-1", "campus": "HN", "admission_year": "2026"}


def test_application_backfill_never_invents_missing_admission_year():
	assert application_backfill_decision({"name": "STU-1", "major": "M-1"})["outcome"] == "review"


def test_application_backfill_is_idempotent_by_provenance_fingerprint():
	student = {"name": "STU-1", "admission_year": "2026", "major": "M-1", "branch": "HN"}
	first = application_backfill_decision(student)
	second = application_backfill_decision(student, {first["idempotency_fingerprint"]})
	assert first["outcome"] == "migrated"
	assert second["outcome"] == "existing"


def test_canonical_application_backfill_requires_one_exact_offering_and_case_key():
	student = {
		"name": "STU-1",
		"case_key": "CK-ID-1-2026",
		"admission_year": "2026",
		"major": "M-1",
		"branch": "HN",
		"admission_method": "exam",
		"enrollment_status": "Mới",
	}
	offerings = [
		{
			"name": "OFF-1",
			"admission_year": "2026",
			"campus": "HN",
			"major": "M-1",
			"admission_method": "exam",
			"status": "Active",
		}
	]
	decision = application_backfill_decision(student, offerings=offerings)

	assert decision["outcome"] == "migrated"
	assert decision["values"]["offering"] == "OFF-1"
	assert decision["values"]["case_key"] == "CK-ID-1-2026"
	assert (
		application_backfill_decision({**student, "case_key": ""}, offerings=offerings)["outcome"] == "review"
	)
	assert (
		application_backfill_decision(student, offerings=[*offerings, {**offerings[0], "name": "OFF-2"}])[
			"reason"
		]
		== "ambiguous_offering"
	)
