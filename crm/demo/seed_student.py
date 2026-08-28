"""Idempotently seed one CRM Student for lifecycle and routing UI verification.

Run with::

    bench --site crm.localhost execute crm.demo.seed_student.execute

The fixture deliberately uses the public ownership, SLA, engagement and
lifecycle services where available.  Its email is a stable test-only key, so
rerunning it never creates a second Student.
"""

from __future__ import annotations

from datetime import timedelta
import json

import frappe
from frappe.utils import now_datetime

from crm.demo import seed_staff


EMAIL = "nguyen-minh-anh-admissions-demo@example.test"
STUDENT_NAME = "Nguyễn Minh Anh — Demo tuyển sinh"
OWNER_EMAIL = "tran-quoc-minh-admissions-demo@example.test"
POOL_NAME = "Tư vấn tuyển sinh — Demo"
ROUTING_POLICY_KEY = "admissions-demo-routing-v1"
SLA_POLICY_KEY = "admissions-demo-sla-v1"
OUTCOME_SOURCE_KEY = "admissions-demo-outcome-v1"
LIFECYCLE_COMMAND_KEY = "admissions-demo-lifecycle-v1"


def execute():
	"""Create (or return) the dedicated Student used to inspect lifecycle services."""
	frappe.set_user("Administrator")
	context = _ensure_context()
	pool = _ensure_pool(context["campus"], context["team"])
	_ensure_policies(context["campus"], pool)
	student = _ensure_student(context["campus"], context["admission_year"], pool)
	ownership = _ensure_routing_and_sla(student.name, pool)
	interaction = _ensure_interaction(student.name)
	outcome = _ensure_outcome(student.name, interaction.name, context["owner_user"])
	_ensure_next_action(student.name, interaction.name, context["owner_user"])
	lifecycle = _ensure_lifecycle(student.name, interaction.name)
	frappe.db.commit()
	result = {
		"student": student.name,
		"student_name": STUDENT_NAME,
		"email": EMAIL,
		"ownership_event": ownership.get("event"),
		"sla_attempt": ownership.get("sla_attempt"),
		"interaction": interaction.name,
		"outcome": outcome,
		"lifecycle": lifecycle,
	}
	verify(**result)
	return result


def verify(student: str, **_unused):
	"""Fail loudly if the fixture no longer exercises a required UI surface."""
	student_doc = frappe.get_doc("CRM Student", student)
	required = {
		"ownership": bool(student_doc.owner_staff and student_doc.ownership_revision),
		"SLA": bool(frappe.db.exists("CRM Student SLA Attempt", {"student": student})),
		"routing": bool(frappe.db.exists("CRM Student Routing Request", {"student": student, "status": "applied"})),
		"outcome": bool(frappe.db.exists("CRM Student Outcome", {"student": student})),
		"lifecycle": bool(frappe.db.exists("CRM Student Lifecycle Event", {"student": student})),
		"next action": bool(frappe.db.exists("Task", {"student": student})),
	}
	missing = [label for label, present in required.items() if not present]
	if missing:
		raise frappe.ValidationError(f"Lifecycle UI seed is incomplete: {', '.join(missing)}")
	return {"student": student, "verified": True, "checks": required}


def inspect():
	"""Return fixture links for local debugging without exposing unrelated records."""
	student = frappe.db.get_value("CRM Student", {"email": EMAIL}, "name")
	return {
		"student": student,
		"outcomes": frappe.get_all(
			"CRM Student Outcome", filters={"student": student}, fields=["name", "next_action", "next_action_assignee", "continuity_kind"]
		),
		"tasks": frappe.get_all(
			"Task", filters={"student": student}, fields=["name", "title", "assigned_to", "status", "reference_docname"]
		),
	}


def _ensure_context():
	seed_staff.execute()
	campus = frappe.db.get_value("CRM Student", {"email": EMAIL}, "branch")
	campus = campus or frappe.db.get_value("CRM Campus", {}, "name")
	staff = _ensure_demo_owner(campus) if campus else None
	if not campus or not staff:
		raise frappe.ValidationError("Lifecycle demo prerequisites could not be created.")
	team = _ensure_demo_team(campus, staff)
	admission_year = frappe.db.get_value("CRM Admission Year", {}, "name")
	if not admission_year:
		admission_year = frappe.get_doc(
			{"doctype": "CRM Admission Year", "year_name": "2026 UI Demo"}
		).insert(ignore_permissions=True).name
	_ensure_enrollment_status("Mới", 10, "open", "Lead")
	_ensure_enrollment_status("Có triển vọng", 20, "open", "MQL")
	return {"campus": campus, "team": team, "staff": staff, "owner_user": OWNER_EMAIL, "admission_year": admission_year}


def _ensure_demo_owner(campus: str):
	from crm.api.user import set_canonical_crm_profile

	if frappe.db.exists("User", OWNER_EMAIL):
		user = frappe.get_doc("User", OWNER_EMAIL)
	else:
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": OWNER_EMAIL,
				"first_name": "Trần Quốc",
				"last_name": "Minh",
				"user_type": "System User",
				"enabled": 1,
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
	user.full_name = "Trần Quốc Minh — Tư vấn tuyển sinh"
	set_canonical_crm_profile(user, "Sale")
	user.save(ignore_permissions=True)
	department = frappe.db.exists("CRM Department", "Phòng Tư vấn tuyển sinh Demo")
	if not department:
		department = frappe.get_doc(
			{"doctype": "CRM Department", "department_name": "Phòng Tư vấn tuyển sinh Demo", "campus": campus}
		).insert(ignore_permissions=True).name
	staff = frappe.db.get_value("CRM Staff", {"user": OWNER_EMAIL}, "name")
	if staff:
		return staff
	return frappe.get_doc(
		{
			"doctype": "CRM Staff",
			"full_name": "Trần Quốc Minh — Tư vấn tuyển sinh",
			"user": OWNER_EMAIL,
			"department": department,
			"campus": campus,
			"is_active": 1,
		}
	).insert(ignore_permissions=True).name


def _ensure_demo_team(campus: str, staff_name: str):
	team_name = "Đội Tư vấn tuyển sinh Demo"
	if not frappe.db.exists("CRM Team", team_name):
		frappe.get_doc(
			{"doctype": "CRM Team", "team_name": team_name, "team_type": "Sales", "campus": campus, "is_active": 1}
		).insert(ignore_permissions=True)
	staff = frappe.get_doc("CRM Staff", staff_name)
	membership = next((row for row in staff.team_memberships if row.team == team_name), None)
	if membership is None:
		staff.append(
			"team_memberships",
			{"team": team_name, "function": "Sale", "is_primary": 0, "is_team_lead": 0},
		)
		staff.save(ignore_permissions=True)
	return team_name


def _ensure_enrollment_status(name: str, order: int, category: str, lifecycle_stage: str):
	meta = {"stage_category": category, "lifecycle_stage": lifecycle_stage}
	term_name = frappe.db.get_value("CRM Term", {"term_name": name, "category": "enrollment_status"}, "name")
	if not term_name and frappe.db.exists("CRM Term", name):
		cat = frappe.db.get_value("CRM Term", name, "category")
		if cat == "enrollment_status":
			term_name = name
	if term_name:
		doc = frappe.get_doc("CRM Term", term_name)
		doc.sort_order = order
		doc.metadata = meta
		doc.save(ignore_permissions=True)
		return doc.name
	doc = frappe.get_doc(
		{
			"doctype": "CRM Term",
			"term_name": name,
			"category": "enrollment_status",
			"sort_order": order,
			"metadata": meta,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name




def _ensure_student(campus: str, admission_year: str, pool: str):
	name = frappe.db.get_value("CRM Student", {"email": EMAIL}, "name")
	if name:
		return frappe.get_doc("CRM Student", name)
	from crm.fcrm.student_intake import submit_intake

	result = submit_intake(
		{
			"student_name": STUDENT_NAME,
			"national_id": "900000000346",
			"email": EMAIL,
			"phone": "0900000346",
			"campus": campus,
			"owning_team": pool,
			"admission_year": admission_year,
			"enrollment_status": "Mới",
		},
		source_namespace="admissions-demo",
		source_record_id="nguyen-minh-anh-2026",
		idempotency_key="admissions-demo-intake-v1",
		correlation_id="admissions-demo-intake-v1",
	)
	student_name = result.get("student")
	if result.get("outcome") != "created" or not student_name:
		raise frappe.ValidationError(f"Demo intake did not create a Student: {result}")
	return frappe.get_doc("CRM Student", student_name)


def _ensure_pool(campus: str, team: str):
	name = frappe.db.exists("CRM Student Pool", POOL_NAME)
	if name:
		return name
	return frappe.get_doc(
		{"doctype": "CRM Student Pool", "pool_name": POOL_NAME, "team": team, "campus": campus, "is_active": 1}
	).insert(ignore_permissions=True).name


def _ensure_policies(campus: str, pool: str):
	now = now_datetime() - timedelta(minutes=5)
	if not frappe.db.exists("CRM Student Routing Policy", {"policy_key": ROUTING_POLICY_KEY}):
		_publish_demo_policy(
			{
				"doctype": "CRM Student Routing Policy",
				"policy_key": ROUTING_POLICY_KEY,
				"policy_version": 1,
				"status": "active",
				"campus": campus,
				"student_pool": pool,
				"strategy": "round_robin",
				"effective_from": now,
			}
		)
	if not frappe.db.exists("CRM Student SLA Policy", {"policy_key": SLA_POLICY_KEY}):
		_publish_demo_policy(
			{
				"doctype": "CRM Student SLA Policy",
				"policy_key": SLA_POLICY_KEY,
				"policy_version": 1,
				"status": "active",
				"campus": campus,
				"student_pool": pool,
				"warning_minutes": 60,
				"breach_minutes": 120,
				"escalation_minutes": 240,
				"pause_reasons": json.dumps(["awaiting_student", "approved_document_wait"]),
				"maximum_pause_minutes": 120,
				"recipient_strategy": "owner_warning_lead_breach_director_escalation",
				"effective_from": now,
			}
		)


def _publish_demo_policy(values: dict):
	"""Publish an explicit local-demo policy through the policy service guard."""
	from crm.api.student_policy import _service_save

	doc = frappe.get_doc(
		{
			**values,
			"status": "active",
			"authored_by": "Administrator",
			"approved_by": "Administrator",
			"approved_at": now_datetime(),
			"break_glass_reason": "Local lifecycle UI fixture: Administrator authors and approves the demo policy.",
		}
	)
	return _service_save(doc)


def _ensure_routing_and_sla(student: str, pool: str):
	"""Apply the real pool-routing service so the UI shows a successful route."""
	from crm.fcrm.student_routing import enqueue_student_routing, process_routing_request

	student_doc = frappe.get_doc("CRM Student", student)
	if not student_doc.owner_staff:
		request = frappe.db.get_value(
			"CRM Student Routing Request",
			{"student": student, "ownership_revision": int(student_doc.ownership_revision or 0)},
			"name",
		)
		request = request or enqueue_student_routing(student, trigger="pool_entry").name
		result = process_routing_request(request)
		if result.get("status") != "applied":
			raise frappe.ValidationError(f"Admissions demo routing did not complete: {result}")
	return {
		"event": frappe.db.get_value("CRM Student Ownership Event", {"student": student}, "name", order_by="event_at desc"),
		"sla_attempt": frappe.db.get_value("CRM Student SLA Attempt", {"student": student}, "name", order_by="creation desc"),
	}


def _ensure_interaction(student: str):
	interaction_type = frappe.db.get_value("CRM Term", {}, "name")
	if not interaction_type:
		interaction_type = frappe.get_doc(
			{"doctype": "CRM Term", "term_name": "Phone Consultation", "category": "interaction_type"}
		).insert(ignore_permissions=True).name
	name = frappe.db.get_value("CRM Interaction", {"student": student, "summary": "Tư vấn hồ sơ và điều kiện xét tuyển"}, "name")
	if name:
		return frappe.get_doc("CRM Interaction", name)
	return frappe.get_doc(
		{
			"doctype": "CRM Interaction",
			"student": student,
			"interaction_type": interaction_type,
			"interaction_datetime": now_datetime() - timedelta(minutes=15),
			"outcome": "Captured",
			"summary": "Tư vấn hồ sơ và điều kiện xét tuyển",
			"notes": "Minh Anh cần được gọi lại để xác nhận hồ sơ xét tuyển.",
		}
	).insert(ignore_permissions=True)


def _ensure_outcome(student: str, interaction: str, owner_user: str):
	existing = frappe.db.get_value("CRM Student Outcome", {"source_key": OUTCOME_SOURCE_KEY}, "name")
	if existing:
		return existing
	from crm.fcrm.student_engagement import record_outcome

	result = record_outcome(
		student=student,
		interaction=interaction,
		outcome_code="qualified",
		continuity_kind="task",
		next_action={"title": "Gọi xác nhận hồ sơ xét tuyển"},
		next_action_assignee=owner_user,
		next_action_due_at=now_datetime() + timedelta(days=1),
		continuity_reason="Cần gọi lại để xác nhận hồ sơ xét tuyển.",
		qualification_evidence=[],
		source_key=OUTCOME_SOURCE_KEY,
		expected_revision=int(frappe.db.get_value("CRM Student", student, "engagement_revision") or 0),
		idempotency_key="admissions-demo-outcome-v1",
		correlation_id="admissions-demo-outcome-v1",
	)
	return result["event"]


def _ensure_lifecycle(student: str, interaction: str):
	existing = frappe.db.get_value("CRM Student Lifecycle Event", {"idempotency_key": LIFECYCLE_COMMAND_KEY}, "name")
	if existing:
		return existing
	from crm.fcrm.student_lifecycle import request_transition

	result = request_transition(
		student=student,
		target_stage="MQL",
		reason="Đã xác nhận nhu cầu tư vấn và đủ điều kiện chuyển sang MQL.",
		evidence_refs=[{"category": "intent", "doctype": "CRM Interaction", "name": interaction}],
		outcome_code="qualified",
		expected_revision=int(frappe.db.get_value("CRM Student", student, "lifecycle_revision") or 0),
		idempotency_key=LIFECYCLE_COMMAND_KEY,
		correlation_id=LIFECYCLE_COMMAND_KEY,
	)
	return result["event"]


def _ensure_next_action(student: str, interaction: str, owner_user: str):
	existing = frappe.db.get_value("Task", {"student": student, "title": "Gọi xác nhận hồ sơ xét tuyển"}, "name")
	if existing:
		return existing
	return frappe.get_doc(
		{
			"doctype": "Task",
			"title": "Gọi xác nhận hồ sơ xét tuyển",
			"student": student,
			"linked_interaction": interaction,
			"reference_doctype": "CRM Student",
			"reference_docname": student,
			"assigned_to": owner_user,
			"status": "Todo",
			"due_date": now_datetime() + timedelta(days=1),
			"priority": "High",
		}
	).insert(ignore_permissions=True).name
