"""Seed one local Sale account with an immediately visible Recommendation.

Run from a Frappe bench::

    bench --site crm.localhost execute crm.demo.seed_local_demo.execute

This fixture is intentionally opt-in and idempotent. It creates or updates the
dedicated ``phase6.sales@example.test`` user, maps it to CRM Staff, assigns one
Student to that Staff row, and creates a ``new`` Recommendation in scope. A
subsequent run creates a fresh Recommendation only after the previous one has
left the inbox; it never rewrites decision history or deletes outbox rows.
"""

from __future__ import annotations

from datetime import timedelta

import frappe
from frappe.utils import get_datetime, now_datetime
from frappe.utils.password import update_password

from crm.api.user import set_canonical_crm_profile

USER_EMAIL = "phase6.sales@example.test"
USER_FIRST_NAME = "Phase 6"
USER_LAST_NAME = "Local Sales"
CREDENTIALS_CONFIG_KEY = "crm_phase6_fixture_password"
ENABLE_CONFIG_KEY = "crm_phase6_local_fixture_enabled"
CAMPUS_NAME = "Phase 6 Local Campus"
DEPARTMENT_NAME = "Phase 6 Local Admissions"
TEAM_NAME = "Phase 6 Local Sales Team"
STUDENT_EMAIL = "phase6.local.student@example.test"
RECOMMENDATION_RULE = "phase6_local_demo"
RECOMMENDATION_SOURCE = "phase6-local-intent-001"


def _ensure_user(password: str):
	if frappe.db.exists("User", USER_EMAIL):
		user = frappe.get_doc("User", USER_EMAIL)
		if user.first_name != USER_FIRST_NAME or user.last_name != USER_LAST_NAME:
			frappe.throw(
				f"Refusing to repurpose existing User {USER_EMAIL}; this is not the local recommendation fixture.",
				frappe.ValidationError,
			)
	else:
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": USER_EMAIL,
				"first_name": USER_FIRST_NAME,
				"last_name": USER_LAST_NAME,
				"user_type": "System User",
				"enabled": 1,
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
	set_canonical_crm_profile(user, "Sale")
	user.enabled = 1
	user.save(ignore_permissions=True)
	update_password(user=USER_EMAIL, pwd=password, logout_all_sessions=True)
	return user


def _ensure_campus():
	if frappe.db.exists("CRM Campus", CAMPUS_NAME):
		return CAMPUS_NAME
	return (
		frappe.get_doc(
			{
				"doctype": "CRM Campus",
				"campus_name": CAMPUS_NAME,
				"campus_code": "P6LOCAL",
				"is_default": 0,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _ensure_department(campus: str):
	if frappe.db.exists("CRM Department", DEPARTMENT_NAME):
		return DEPARTMENT_NAME
	return (
		frappe.get_doc(
			{
				"doctype": "CRM Department",
				"department_name": DEPARTMENT_NAME,
				"campus": campus,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _ensure_team(campus: str):
	if frappe.db.exists("CRM Team", TEAM_NAME):
		return TEAM_NAME
	return (
		frappe.get_doc(
			{
				"doctype": "CRM Team",
				"team_name": TEAM_NAME,
				"team_type": "Sales",
				"campus": campus,
				"is_active": 1,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _ensure_staff(user, campus: str, department: str, team: str):
	staff_name = frappe.db.get_value("CRM Staff", {"user": user.name}, "name")
	if staff_name:
		staff = frappe.get_doc("CRM Staff", staff_name)
		if staff.full_name != "Phase 6 Local Sales":
			frappe.throw(
				f"Refusing to repurpose existing CRM Staff {staff.name}; this is not the local recommendation fixture.",
				frappe.ValidationError,
			)
		staff.full_name = "Phase 6 Local Sales"
		staff.campus = campus
		staff.department = department
		staff.is_active = 1
	else:
		staff = frappe.get_doc(
			{
				"doctype": "CRM Staff",
				"full_name": "Phase 6 Local Sales",
				"user": user.name,
				"campus": campus,
				"department": department,
				"is_active": 1,
			}
		)
	membership = next((row for row in staff.team_memberships if row.team == team), None)
	if membership:
		membership.function = "Sale"
		membership.is_primary = 1
	else:
		staff.append(
			"team_memberships",
			{"team": team, "function": "Sale", "is_primary": 1, "is_team_lead": 0},
		)
	staff.save(ignore_permissions=True)
	return staff.name


def _ensure_student(staff: str, campus: str):
	student_name = frappe.db.get_value("CRM Student", {"email": STUDENT_EMAIL}, "name")
	if student_name:
		student = frappe.get_doc("CRM Student", student_name)
		if student.student_name != "Phase 6 Local Student":
			frappe.throw(
				f"Refusing to repurpose existing CRM Student {student.name}; this is not the local recommendation fixture.",
				frappe.ValidationError,
			)
		if (
			student.assigned_to != staff
			or student.owner_staff != staff
			or student.owning_team != TEAM_NAME
			or student.branch != campus
		):
			frappe.throw(
			"The local Student ownership changed; repair it through the ownership command or use a fresh fixture site.",
				frappe.ValidationError,
			)
		return student_name

	status = frappe.db.get_value("CRM Term", {}, "name") or "Mới"
	previous_flag = getattr(frappe.flags, "student_intake_service", False)
	frappe.flags.student_intake_service = True
	try:
		student = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"student_name": "Phase 6 Local Student",
				"email": STUDENT_EMAIL,
				"phone": "0900000001",
				"enrollment_status": status,
				"assigned_to": staff,
				"branch": campus,
				"notes": "Local recommendation fixture.",
			}
		).insert(ignore_permissions=True)
		return student.name
	finally:
		frappe.flags.student_intake_service = previous_flag


def _ensure_recommendation(student: str):
	rows = frappe.get_all(
		"CRM Recommendation",
		filters={"student": student, "rule_key": RECOMMENDATION_RULE},
		fields=["name", "status", "context_hash", "revisit_at"],
		order_by="creation desc",
	)
	now = now_datetime()
	active = next(
		(
			row
			for row in rows
			if row.status in {"new", "acknowledged"}
			or (row.status == "deferred" and row.revisit_at and get_datetime(row.revisit_at) <= now)
		),
		None,
	)
	if active:
		return active.name
	sequence = len(rows) + 1
	source_intent = f"{RECOMMENDATION_SOURCE}-{sequence:03d}"
	context_hash = f"phase6-local-demo-v{sequence}"

	recommendation = frappe.get_doc(
		{
			"doctype": "CRM Recommendation",
			"student": student,
			"rule_key": RECOMMENDATION_RULE,
			"source_intent_id": source_intent,
			"condition_version": 1,
			"context_hash": context_hash,
			"policy_version": "phase6-v1",
			"producer_id": "local-phase6-fixture",
			"producer_revision": 1,
			"priority": "high",
			"status": "new",
			"recommended_action": "CALL",
			"recommended_timing": now_datetime() + timedelta(hours=2),
			"reason": "Local fixture: học viên vừa thể hiện nhu cầu tư vấn và cần gọi lại.",
			"evidence": {"fixture": "phase6-local-demo", "student": student},
		}
	)
	recommendation.flags.from_phase6_command = True
	recommendation.insert(ignore_permissions=True)
	return recommendation.name


def execute(password: str | None = None):
	"""Create the local login fixture and return its identifiers."""
	site_name = str(getattr(frappe.local, "site", "") or "")
	if not site_name.endswith((".localhost", ".local", ".test")):
		frappe.throw(
			f"Refusing to seed the local recommendation fixture on site {site_name!r}; use a .localhost/.local/.test site.",
			frappe.ValidationError,
		)
	if frappe.conf.get(ENABLE_CONFIG_KEY) not in (1, "1", True):
		frappe.throw(
			f"Set {ENABLE_CONFIG_KEY}=1 on this local site before seeding the local recommendation fixture.",
			frappe.ValidationError,
		)
	if frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
		frappe.throw(
			"Only Administrator/System Manager may seed the local recommendation fixture.", frappe.PermissionError
		)
	password = password or frappe.conf.get(CREDENTIALS_CONFIG_KEY)
	if not password:
		frappe.throw(
			f"Set {CREDENTIALS_CONFIG_KEY} on this local site or pass password explicitly.",
			frappe.ValidationError,
		)
	campus = _ensure_campus()
	department = _ensure_department(campus)
	team = _ensure_team(campus)
	user = _ensure_user(password)
	staff = _ensure_staff(user, campus, department, team)
	student = _ensure_student(staff, campus)
	recommendation = _ensure_recommendation(student)
	frappe.db.commit()
	return {
		"user": USER_EMAIL,
		"password": password,
		"student": student,
		"recommendation": recommendation,
		"campus": campus,
		"staff": staff,
		"team": team,
	}
