"""Seed one Student + School pair that is ready for the agent 360 worker.

Run with::

    bench --site crm.localhost execute crm.demo.seed_agent_360.execute

The Student fixture is delegated to ``seed_student_detail``.  This module only
adds the school-side facts that the School 360 evidence contract requires.
All source keys are stable so the command is safe to rerun on the local site.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import frappe

from crm.demo import seed_showcase, seed_staff, seed_student_detail
from crm.fcrm.admissions_migration import stable_fingerprint

LOCAL_SITE = "crm.localhost"
NAMESPACE = "crm-demo-agent-360"
ADMISSION_YEAR = "2026"
SNAPSHOT_DATE = "2026-09-01"
SNAPSHOT_SOURCE_RUN = f"{NAMESPACE}:school-snapshot"
STAKEHOLDER_EMAIL = "truong.tdn.agent360@example.test"
STAKEHOLDER_PHONE = "0901999360"
PROMOTER_EMAIL = seed_showcase.PROMOTER_EMAIL


def _assert_local_site() -> None:
	if getattr(frappe.local, "site", None) == LOCAL_SITE or frappe.conf.get("allow_demo_seed"):
		return
	frappe.throw(
		"The agent 360 seed only runs on crm.localhost. Set allow_demo_seed=1 "
		"to opt in a demo/staging site.",
		frappe.PermissionError,
	)


def _ensure_staff_context() -> tuple[str, str]:
	staff = frappe.db.get_value("CRM Staff", {"user": PROMOTER_EMAIL}, "name")
	if not staff:
		context = seed_staff._bootstrap()
		staff = seed_showcase._ensure_promoter_fixture(context)

	staff_doc = frappe.get_doc("CRM Staff", staff)
	team = next(
		(row.team for row in staff_doc.team_memberships if row.get("is_primary")),
		next((row.team for row in staff_doc.team_memberships if row.get("team")), None),
	)
	if not team:
		team = seed_staff._bootstrap()["team"]
	return staff, team


def _ensure_snapshot(school: str) -> str:
	fingerprint = stable_fingerprint(
		"agent-360-school-snapshot", school, ADMISSION_YEAR, SNAPSHOT_SOURCE_RUN
	)
	existing = frappe.db.get_value(
		"CRM High School Annual Snapshot", {"idempotency_fingerprint": fingerprint}, "name"
	)
	if existing:
		return existing

	return (
		frappe.get_doc(
			{
				"doctype": "CRM High School Annual Snapshot",
				"high_school": school,
				"admission_year": ADMISSION_YEAR,
				"measured_on": SNAPSHOT_DATE,
				"period_type": "Annual",
				"period": ADMISSION_YEAR,
				"revision": 1,
				"timezone": "Asia/Ho_Chi_Minh",
				"ne_target": 10,
				"ne_actual": 26,
				"ne_actual_semantics": "New Enter History",
				"adjusted_ne_threshold": 10,
				"applicant_count": 42,
				"enrolled_count": 12,
				"contact_count": 30,
				"student_count": 1,
				"conversion_count": 1,
				"average_score": 24.8,
				"conversion_rate": 28.57,
				"enrollment_rate": 28.57,
				"forecast_count": 16,
				"context_raw_counts": {"source": NAMESPACE, "verified_records": 1},
				"snapshot_date": SNAPSHOT_DATE,
				"recorded_at": datetime(2026, 9, 1, 9, 0, 0),
				"source_system": NAMESPACE,
				"source_run": SNAPSHOT_SOURCE_RUN,
				"verification_status": "Verified",
				"verified_by": "Administrator",
				"verified_at": datetime(2026, 9, 1, 9, 0, 0),
				"idempotency_fingerprint": fingerprint,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _ensure_person() -> str:
	person = frappe.db.get_value("CRM Person", {"email": STAKEHOLDER_EMAIL}, "name")
	if person:
		return person
	return (
		frappe.get_doc(
			{
				"doctype": "CRM Person",
				"full_name": "Cô Nguyễn Thu Hà",
				"phone": STAKEHOLDER_PHONE,
				"email": STAKEHOLDER_EMAIL,
				"notes": f"{NAMESPACE}: school 360 stakeholder fixture",
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _ensure_stakeholder(school: str, person: str, staff: str, team: str) -> str:
	role = seed_showcase._ensure_term("Đầu mối tuyển sinh", "stakeholder_role")
	association = frappe.db.get_value(
		"CRM School Stakeholder", {"high_school": school, "person": person}, "name"
	)
	if not association:
		association = (
			frappe.get_doc(
				{
					"doctype": "CRM School Stakeholder",
					"high_school": school,
					"person": person,
					"stakeholder_role": role,
					"position_title": "Đầu mối tuyển sinh",
					"relationship_status": "New",
					"relationship_revision": 1,
					"owner_staff": staff,
					"owning_team": team,
					"is_primary": 1,
					"relationship_score": 85,
					"last_touch_date": SNAPSHOT_DATE,
					"next_touch_date": "2026-09-15",
					"contact_preference": "Phone",
					"source_reference": f"{NAMESPACE}:stakeholder",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	doc = frappe.get_doc("CRM School Stakeholder", association)
	if doc.relationship_status != "Active":
		from crm.fcrm.school_intelligence import transition_school_relationship

		transition_school_relationship(
			association,
			"Active",
			f"{NAMESPACE}:relationship-active",
			f"{NAMESPACE}:verified-school-contact",
		)
	return association


def _ensure_activity(school: str, stakeholder: str, staff: str, team: str) -> str:
	key = f"{NAMESPACE}:school-visit"
	existing = frappe.db.get_value("CRM School Activity", {"import_idempotency_key": key}, "name")
	if existing:
		return existing
	activity_type = seed_showcase._ensure_term("Tư vấn hướng nghiệp tại trường", "activity_type")
	return (
		frappe.get_doc(
			{
				"doctype": "CRM School Activity",
				"high_school": school,
				"stakeholder": stakeholder,
				"admission_year": ADMISSION_YEAR,
				"activity_type": activity_type,
				"activity_date": SNAPSHOT_DATE,
				"scheduled_datetime": datetime(2026, 9, 1, 8, 0, 0),
				"owner_staff": staff,
				"owning_team": team,
				"status": "Completed",
				"outcome": "Positive",
				"attendance": 48,
				"prospect_count": 36,
				"contact_count": 24,
				"application_count": 9,
				"activity_cost": 12,
				"activity_cost_unit": "million_vnd",
				"next_action": "Theo dõi hồ sơ học sinh đủ điều kiện xét tuyển.",
				"evidence_reference": f"{NAMESPACE}:school-visit-evidence",
				"import_idempotency_key": key,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _quiesce_stale_runs(domain: str, target: str, current_revision: int) -> list[str]:
	"""Repair old local queued runs so the single-active-run fence can proceed."""
	run_type = "CRM Student Analysis Run" if domain == "student" else "CRM School Analysis Run"
	field = "student" if domain == "student" else "high_school"
	active = frappe.get_all(
		run_type,
		filters={field: target, "status": ["in", ["queued", "running"]]},
		fields=["name", "source_revision"],
		order_by="creation asc",
		limit_page_length=0,
	)
	stale = [
		row.name for row in active if int(row.source_revision or 0) != int(current_revision)
	]
	if not stale:
		return []

	for run_name in stale:
		frappe.db.sql(
			"""UPDATE `tabCRM Analysis Run Stage`
			SET status='abstained', claims='[]', terminal_reason=%s,
				lease_token=NULL, lease_expires_at=NULL
			WHERE parent_run_type=%s AND parent_run=%s AND status IN ('queued', 'running')""",
			[f"{NAMESPACE}:superseded-by-current-revision", run_type, run_name],
		)
		frappe.db.set_value(
			run_type,
			run_name,
			{"status": "abstained", "terminal_reason": f"{NAMESPACE}:superseded-by-current-revision"},
			update_modified=False,
		)
	return stale


def execute() -> dict[str, Any]:
	"""Create the bounded pair and return identifiers for the 360 run."""
	_assert_local_site()
	frappe.set_user("Administrator")

	# Source mutations should be complete before the explicit manual run is
	# requested. Avoid creating intermediate automatic runs from document hooks.
	previous_intelligence_flag = frappe.conf.get("crm_intelligence_runs_enabled")
	frappe.conf["crm_intelligence_runs_enabled"] = 0
	try:
		seed_showcase.ensure_local_integrity_keys()
		seed_showcase.ensure_demo_config()
		student = frappe.db.get_value(
			"CRM Student", {"email": seed_student_detail.STUDENT_EMAIL}, "name"
		)
		if not student:
			seed_student_detail.execute()
			student = frappe.db.get_value(
				"CRM Student", {"email": seed_student_detail.STUDENT_EMAIL}, "name"
			)
		if not student:
			frappe.throw("Student detail fixture did not resolve.", frappe.ValidationError)
		else:
			seed_student_detail.verify()
		school = frappe.db.get_value("CRM Student", student, "high_school")
		if not school:
			frappe.throw("Student detail fixture has no linked high school.", frappe.ValidationError)

		staff, team = _ensure_staff_context()
		snapshot = _ensure_snapshot(school)
		person = _ensure_person()
		stakeholder = _ensure_stakeholder(school, person, staff, team)
		activity = _ensure_activity(school, stakeholder, staff, team)
		frappe.db.commit()
	finally:
		if previous_intelligence_flag is None:
			frappe.conf.pop("crm_intelligence_runs_enabled", None)
		else:
			frappe.conf["crm_intelligence_runs_enabled"] = previous_intelligence_flag

	from crm.api.intelligence_runs import request_school_analysis_run, request_student_analysis_run

	student_revision = int(frappe.db.get_value("CRM Student", student, "student_context_revision") or 0)
	school_revision = int(frappe.db.get_value("CRM High School", school, "intelligence_revision") or 0)
	quiesced_student_runs = _quiesce_stale_runs("student", student, student_revision)
	quiesced_school_runs = _quiesce_stale_runs("school", school, school_revision)
	frappe.db.commit()

	student_request = request_student_analysis_run(
		student,
		idempotency_key=f"{NAMESPACE}:student-run:r{student_revision}",
	)
	school_request = request_school_analysis_run(
		school,
		idempotency_key=f"{NAMESPACE}:school-run:r{school_revision}",
		admission_year=int(ADMISSION_YEAR),
	)
	result = {
		"student": student,
		"school": school,
		"student_request": student_request,
		"school_request": school_request,
		"school_facts": {
			"snapshot": snapshot,
			"person": person,
			"stakeholder": stakeholder,
			"activity": activity,
		},
		"source_revisions": {"student": student_revision, "school": school_revision},
		"quiesced_stale_runs": {
			"student": quiesced_student_runs,
			"school": quiesced_school_runs,
		},
	}
	print(frappe.as_json(result))
	return result
