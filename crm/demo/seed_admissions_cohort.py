"""Seed the small, realistic local admissions cohort used by ``task seed``.

The cohort is intentionally local-only and idempotent.  It creates Student
state through the intake, ownership, engagement, SLA and lifecycle services;
it never writes their projections or append-only audit rows directly.
"""

from __future__ import annotations

import json
from datetime import timedelta

import frappe
from frappe.utils import now_datetime

from crm.demo import seed_demo, seed_staff

NAMESPACE = "local-admissions-cohort-2026"
SALE_EMAIL = "nguyen-minh-khoi.sale@example.test"

# The first cohort Student is the deterministic Student Detail walkthrough.
# Keep these as ordinary Task rows so the real Task tab, activity feed and
# status controls exercise the same records as production work.
ADMISSIONS_TASK_TEMPLATES = (
	{"key": "first-call", "title": "Gọi lần đầu", "priority": "High", "days": 0, "description": "Gọi lần đầu để xác nhận nhu cầu và khung giờ tư vấn phù hợp."},
	{"key": "scholarship-info", "title": "Gửi thông tin học bổng", "priority": "High", "days": 1, "description": "Gửi điều kiện, mốc thời gian và checklist thông tin học bổng."},
	{"key": "campus-tour-reminder", "title": "Nhắc tham dự Campus Tour", "priority": "Medium", "days": 2, "description": "Nhắc học sinh và phụ huynh xác nhận lịch tham dự Campus Tour."},
	{"key": "parent-call", "title": "Gọi phụ huynh", "priority": "Medium", "days": 3, "description": "Gọi phụ huynh để trao đổi ảnh hưởng, tài chính và phương án phù hợp."},
	{"key": "application-follow-up", "title": "Follow-up hồ sơ", "priority": "High", "days": 5, "description": "Theo dõi hồ sơ, bảng điểm và giấy tờ còn thiếu trước hạn xét tuyển."},
)

SCENARIOS = (
	{
		"key": "thao-an",
		"student_name": "Nguyễn Thảo An",
		"email": "nguyen-thao-an.2026@example.test",
		"phone": "0901803101",
		"target_stage": "Lead",
		"owner": False,
		"summary": "Đăng ký tư vấn ngành Kỹ thuật phần mềm sau Campus Tour",
		"notes": "Học sinh lớp 12, phụ huynh đề nghị liên hệ sau 18:30 để trao đổi lộ trình xét tuyển.",
	},
	{
		"key": "gia-han",
		"student_name": "Võ Gia Hân",
		"email": "vo-gia-han.2026@example.test",
		"phone": "0901803102",
		"target_stage": "MQL",
		"owner": True,
		"summary": "Trao đổi học bổng và phương án học phí ngành Kỹ thuật phần mềm",
		"notes": "Gia Hân xác nhận sẽ chuẩn bị bảng điểm và chứng chỉ tiếng Anh để tư vấn học bổng.",
		"next_action": "Gửi checklist hồ sơ học bổng",
	},
	{
		"key": "minh-khang",
		"student_name": "Bùi Minh Khang",
		"email": "bui-minh-khang.2026@example.test",
		"phone": "0901803103",
		"target_stage": "Applicant",
		"owner": True,
		"summary": "Rà soát hồ sơ xét tuyển còn thiếu bảng điểm có xác nhận",
		"notes": "Hồ sơ đã tiếp nhận, cần gia đình bổ sung bảng điểm học kỳ II có xác nhận của trường.",
		"next_action": "Lead Sales rà soát hồ sơ thiếu và hỗ trợ gia đình",
	},
	{
		"key": "khanh-linh",
		"student_name": "Trần Khánh Linh",
		"email": "tran-khanh-linh.2026@example.test",
		"phone": "0901803104",
		"target_stage": "Lost",
		"owner": False,
		"summary": "Gia đình xác nhận chọn chương trình khác phù hợp hơn",
		"notes": "Gia đình đề nghị dừng tư vấn trong đợt tuyển sinh này.",
	},
	{
		"key": "nhat-minh",
		"student_name": "Đỗ Nhật Minh",
		"email": "do-nhat-minh.2026@example.test",
		"phone": "0901803105",
		"target_stage": "Enrolled",
		"owner": False,
		"summary": "Hoàn tất hồ sơ nhập học ngành Kỹ thuật phần mềm",
		"notes": "Đã xác nhận thông tin nhập học; chuyển đổi Contact là thao tác vận hành ngoài cohort này.",
	},
)


def execute() -> dict:
	"""Create the local workday cohort and return its Desk-facing manifest."""
	frappe.set_user("Administrator")
	context = seed_demo.execute()
	staff_context = seed_staff.execute()
	_ensure_lifecycle_statuses()
	_ensure_policies(staff_context["campus"], staff_context["pool"])

	manifest = []
	for scenario in SCENARIOS:
		student = _ensure_student(scenario, context, staff_context["pool"])
		if scenario["owner"]:
			_ensure_assigned(student.name)
		interaction = _ensure_engagement(student.name, scenario)
		outcome = _ensure_outcome(student.name, interaction, scenario)
		_ensure_lifecycle(student.name, scenario, outcome)
		_ensure_attribution(student.name, scenario, context)
		_ensure_potential_score(student.name, scenario)
		task_names = _ensure_admissions_tasks(student.name, scenario)
		if scenario["key"] == "minh-khang":
			_ensure_escalated_sla(student.name)
		manifest.append(_manifest_row(student.name, scenario, task_names=task_names))

	frappe.db.commit()
	return {"namespace": NAMESPACE, "accounts": seed_staff.CANONICAL_FIXTURE_USERS, "students": manifest}


def _ensure_lifecycle_statuses():
	from crm.demo.seed_student import _ensure_enrollment_status

	for name, order, category, stage in (
		("Mới", 10, "open", "Lead"),
		("Có triển vọng", 20, "open", "MQL"),
		("Đã xác nhận", 30, "open", "Applicant"),
		("Đã nhập học", 40, "enrolled", "Enrolled"),
		("Từ chối", 50, "lost", "Lost"),
	):
		_ensure_enrollment_status(name, order, category, stage)


def _ensure_policies(campus: str, pool: str):
	from crm.api.student_policy import _service_save

	now = now_datetime() - timedelta(minutes=1)
	policies = (
		{
			"doctype": "CRM Student Routing Policy",
			"policy_key": f"{NAMESPACE}-routing-v1",
			"policy_version": 1,
			"campus": campus,
			"student_pool": pool,
			"strategy": "round_robin",
			"effective_from": now,
		},
		{
			"doctype": "CRM Student SLA Policy",
			"policy_key": f"{NAMESPACE}-sla-v1",
			"policy_version": 1,
			"campus": campus,
			"student_pool": pool,
			"warning_minutes": 15,
			"breach_minutes": 30,
			"escalation_minutes": 45,
			"pause_reasons": json.dumps([]),
			"maximum_pause_minutes": 0,
			"recipient_strategy": "owner_warning_lead_breach_director_escalation",
			"effective_from": now,
		},
	)
	for values in policies:
		if frappe.db.exists(values["doctype"], {"policy_key": values["policy_key"]}):
			continue
		doc = frappe.get_doc(
			{
				**values,
				"status": "active",
				"authored_by": "Administrator",
				"approved_by": "Administrator",
				"approved_at": now_datetime(),
				"break_glass_reason": "Local-only admissions cohort requires one approved operational policy.",
			}
		)
		_service_save(doc)


def _ensure_student(scenario: dict, context: dict, pool: str):
	from crm.fcrm.student_intake import submit_intake

	result = submit_intake(
		{
			"student_name": scenario["student_name"],
			"email": scenario["email"],
			"phone": scenario["phone"],
			"campus": context["campus"],
			"owning_team": pool,
			"admission_year": context["admission_year"],
			"enrollment_status": "Mới",
			"high_school": context["high_school"],
			"major": context["major"],
			"source": context["source"],
		},
		source_namespace=NAMESPACE,
		source_record_id=scenario["key"],
		idempotency_key=f"{NAMESPACE}:intake:{scenario['key']}",
		correlation_id=f"{NAMESPACE}:{scenario['key']}",
	)
	student_name = result.get("student")
	if result.get("outcome") not in {"created", "attached"} or not student_name:
		raise frappe.ValidationError(f"Could not create local admissions Student {scenario['key']}: {result}")
	return frappe.get_doc("CRM Student", student_name)


def _ensure_assigned(student: str):
	from crm.fcrm.student_routing import enqueue_student_routing, process_routing_request

	doc = frappe.get_doc("CRM Student", student)
	if doc.owner_staff:
		return doc.owner_staff
	request = enqueue_student_routing(student, trigger="pool_entry", correlation_id=f"{NAMESPACE}:{student}")
	result = process_routing_request(request.name)
	if result.get("status") != "applied":
		raise frappe.ValidationError(f"Could not route local admissions Student {student}: {result}")
	return result.get("owner_staff")


def _ensure_engagement(student: str, scenario: dict) -> str:
	if scenario["key"] == "gia-han":
		_ensure_responded_sla(student, _ensure_verified_call_interaction(student, scenario))
	return _ensure_manual_interaction(student, scenario)


def _ensure_verified_call_interaction(student: str, scenario: dict) -> str:
	from crm.fcrm.interaction_log import create_interaction

	_ensure_interaction_type("Connected")
	call_id = f"{NAMESPACE}-{scenario['key']}-sla-response"
	call_name = frappe.db.get_value("Call Log", {"id": call_id}, "name")
	if not call_name:
		student_doc = frappe.get_doc("CRM Student", student)
		call_name = frappe.get_doc(
			{
				"doctype": "Call Log",
				"id": call_id,
				"from": student_doc.phone,
				"to": "02873005588",
				"type": "Outgoing",
				"status": "Completed",
				"duration": 420,
				"start_time": now_datetime(),
				"reference_doctype": "CRM Student",
				"reference_docname": student,
				"caller": SALE_EMAIL,
			}
		).insert(ignore_permissions=True).name
	interaction = frappe.db.get_value(
		"CRM Interaction",
		{"reference_doctype": "Call Log", "reference_docname": call_name},
		"name",
	)
	if not interaction:
		interaction = create_interaction(
			interaction_type="Connected",
			student=student,
			reference_doctype="Call Log",
			reference_docname=call_name,
			actor=SALE_EMAIL,
			summary=scenario["summary"],
		)
	interaction_doc = frappe.get_doc("CRM Interaction", interaction)
	if not interaction_doc.outcome:
		interaction_doc.outcome = "Captured"
		interaction_doc.notes = scenario["notes"]
		interaction_doc.save(ignore_permissions=True)
	return interaction


def _ensure_manual_interaction(student: str, scenario: dict) -> str:
	interaction_type = _ensure_interaction_type("Counseling")
	external_id = f"{NAMESPACE}:{scenario['key']}:engagement"
	existing = frappe.db.get_value("CRM Interaction", {"external_id": external_id}, "name")
	if existing:
		return existing
	return frappe.get_doc(
		{
			"doctype": "CRM Interaction",
			"student": student,
			"interaction_type": interaction_type,
			"interaction_datetime": now_datetime(),
			"external_id": external_id,
			"summary": scenario["summary"],
			"notes": scenario["notes"],
		}
	).insert(ignore_permissions=True).name


def _ensure_interaction_type(name: str) -> str:
	if frappe.db.exists("CRM Term", name):
		return name
	return frappe.get_doc({"doctype": "CRM Term", "term_name": name, "category": "interaction_type"}).insert(
		ignore_permissions=True
	).name


def _ensure_outcome(student: str, interaction: str, scenario: dict) -> str | None:
	if scenario["target_stage"] == "Lost":
		return None
	source_key = f"{NAMESPACE}:outcome:{scenario['key']}"
	existing = frappe.db.get_value("CRM Student Outcome", {"source_key": source_key}, "name")
	if existing:
		return existing
	from crm.fcrm.student_engagement import record_outcome

	evidence = []
	if scenario["target_stage"] in {"Applicant", "Enrolled"}:
		evidence.append({"category": "document", "doctype": "File", "name": _ensure_document_evidence(student, scenario)})
	result = record_outcome(
		student=student,
		interaction=interaction,
		outcome_code="qualified",
		continuity_kind="task" if scenario.get("next_action") else "terminal",
		next_action={"title": scenario["next_action"]} if scenario.get("next_action") else None,
		next_action_assignee=SALE_EMAIL if scenario.get("next_action") else None,
		next_action_due_at=now_datetime() + timedelta(days=1) if scenario.get("next_action") else None,
		continuity_reason="Đã hoàn thành chăm sóc ở mốc tuyển sinh này." if not scenario.get("next_action") else None,
		qualification_evidence=evidence,
		source_key=source_key,
		expected_revision=int(frappe.db.get_value("CRM Student", student, "engagement_revision") or 0),
		idempotency_key=f"{NAMESPACE}:outcome:{scenario['key']}",
		correlation_id=f"{NAMESPACE}:{scenario['key']}",
	)
	return result["event"]


def _ensure_document_evidence(student: str, scenario: dict) -> str:
	file_name = f"{scenario['key']}-phieu-tiep-nhan-ho-so-2026.txt"
	existing = frappe.db.get_value(
		"File",
		{"attached_to_doctype": "CRM Student", "attached_to_name": student, "file_name": file_name},
		"name",
	)
	if existing:
		return existing
	return frappe.get_doc(
		{
			"doctype": "File",
			"file_name": file_name,
			"is_private": 1,
			"content": (
				f"Phiếu tiếp nhận hồ sơ tuyển sinh 2026\n"
				f"Học sinh: {scenario['student_name']}\n"
				"Tình trạng: Đã tiếp nhận để đối chiếu theo quy trình tuyển sinh.\n"
			),
			"attached_to_doctype": "CRM Student",
			"attached_to_name": student,
		}
	).insert(ignore_permissions=True).name


def _ensure_lifecycle(student: str, scenario: dict, outcome: str | None):
	target = scenario["target_stage"]
	doc = frappe.get_doc("CRM Student", student)
	if doc.lifecycle_stage == target:
		return None
	if doc.lifecycle_stage != "Lead":
		raise frappe.ValidationError(f"Local admissions Student {student} is at unexpected lifecycle stage {doc.lifecycle_stage}.")
	from crm.fcrm.student_lifecycle import request_transition

	if target == "Lost":
		result = request_transition(
			student,
			"Lost",
			reason="Gia đình đã chọn chương trình đào tạo khác trong đợt tuyển sinh này.",
			expected_revision=int(doc.lifecycle_revision or 0),
			idempotency_key=f"{NAMESPACE}:lifecycle:{scenario['key']}",
			correlation_id=f"{NAMESPACE}:{scenario['key']}",
		)
		return result["event"]
	evidence = [{"category": "outcome", "doctype": "CRM Student Outcome", "name": outcome}]
	if target == "MQL":
		evidence.append({"category": "intent", "doctype": "CRM Intent", "name": _ensure_intent_evidence(student, scenario)})
	else:
		evidence.append({"category": "document", "doctype": "File", "name": _ensure_document_evidence(student, scenario)})
	result = request_transition(
		student,
		target,
		reason=f"Đủ bằng chứng nghiệp vụ để chuyển sang {target}.",
		evidence_refs=evidence,
		outcome_code="qualified",
		expected_revision=int(doc.lifecycle_revision or 0),
		idempotency_key=f"{NAMESPACE}:lifecycle:{scenario['key']}",
		correlation_id=f"{NAMESPACE}:{scenario['key']}",
	)
	return result["event"]


def _ensure_intent_evidence(student: str, scenario: dict) -> str:
	interaction = _ensure_manual_interaction(student, scenario)
	intent_type = seed_demo._ensure_intent_type("Scholarship", "High", "Quan tâm đến học bổng")
	existing = frappe.db.get_value(
		"CRM Intent", {"interaction": interaction, "intent_type": intent_type}, "name"
	)
	if existing:
		return existing
	return frappe.get_doc(
		{
			"doctype": "CRM Intent",
			"interaction": interaction,
			"intent_type": intent_type,
			"confidence": 88,
			"intent_role": "Dominant",
			"polarity": "Positive",
			"notes": "Học sinh cần tư vấn điều kiện học bổng.",
		}
	).insert(ignore_permissions=True).name


def _ensure_attribution(student: str, scenario: dict, context: dict):
	from crm.fcrm.student_attribution import record_campaign_touchpoint, record_event_participation

	for interaction_type in ("Campaign Touched", "Registered", "Checked-in"):
		_ensure_interaction_type(interaction_type)
	campaign_key = f"{NAMESPACE}:campaign:{scenario['key']}"
	if not frappe.db.exists("CRM Marketing Engagement", {"engagement_kind": "campaign_touch", "idempotency_key": campaign_key}):
		record_campaign_touchpoint(
			student,
			context["campaign"],
			source="Manual",
			notes=f"Open Day registration — {scenario['student_name']} thuộc cohort tuyển sinh TP.HCM 2026.",
			idempotency_key=campaign_key,
			correlation_id=f"{NAMESPACE}:{scenario['key']}",
		)
	if scenario["key"] in {"thao-an", "gia-han"}:
		event_key = f"{NAMESPACE}:event:{scenario['key']}"
		if not frappe.db.exists("CRM Marketing Engagement", {"engagement_kind": "event_participation", "idempotency_key": event_key}):
			record_event_participation(
				student,
				context["event"],
				status="Checked-in" if scenario["key"] == "gia-han" else "Registered",
				idempotency_key=event_key,
				correlation_id=f"{NAMESPACE}:{scenario['key']}",
			)


def _ensure_admissions_tasks(student: str, scenario: dict) -> list[str]:
	"""Create the five local walkthrough tasks exactly once for the hero Student."""
	if scenario.get("key") != "thao-an":
		return []
	lock_name = f"{NAMESPACE}:admissions-tasks:{student}"
	lock_result = frappe.db.sql("SELECT GET_LOCK(%s, 10)", (lock_name,))
	if not lock_result or not lock_result[0][0]:
		frappe.throw("Could not lock local admissions task seed; please retry.", frappe.DuplicateEntryError)
	try:
		names = []
		for template in ADMISSIONS_TASK_TEMPLATES:
			marker = f"[{NAMESPACE}:{scenario['key']}:task:{template['key']}]"
			existing = frappe.db.get_value(
				"Task",
				{
					"student": student,
					"reference_doctype": "CRM Student",
					"reference_docname": student,
					"description": ["like", f"{marker}%"],
				},
				"name",
			)
			if existing:
				names.append(existing)
				continue
			due_at = now_datetime() + timedelta(days=template["days"])
			task = frappe.get_doc(
				{
					"doctype": "Task",
					"title": template["title"],
					"description": f"{marker}\n{template['description']}",
					"priority": template["priority"],
					"status": "Todo",
					"assigned_to": SALE_EMAIL,
					"start_date": due_at.date(),
					"due_date": due_at,
					"student": student,
					"reference_doctype": "CRM Student",
					"reference_docname": student,
				}
			).insert(ignore_permissions=True)
			names.append(task.name)
		return names
	finally:
		frappe.db.sql("SELECT RELEASE_LOCK(%s)", (lock_name,))


def _ensure_potential_score(student: str, scenario: dict):
	"""Append the current, Desk-visible potential score through the CAS writer."""
	from crm.api.scoring_write import append_local_fixture_score
	from crm.fcrm.scoring_policy import get_active_policy

	profiles = {
		"thao-an": (25, 18, 5, 0, 0),
		"gia-han": (35, 22, 30, 0, 0),
		"minh-khang": (35, 25, 35, 0, 0),
		"khanh-linh": (20, 8, 0, 0, -18),
		"nhat-minh": (40, 25, 35, 0, 0),
	}
	fit, engagement, intent, time_decay, negative = profiles[scenario["key"]]
	final = fit + engagement + intent + time_decay + negative
	policy = get_active_policy()
	if not policy:
		raise frappe.ValidationError("The local admissions score template is not active.")
	student_doc = frappe.get_doc("CRM Student", student)
	return append_local_fixture_score(
		student=student,
		source_score_input_revision=int(student_doc.score_input_revision or 0),
		policy_revision=policy["policy_revision"],
		policy_hash=policy["policy_hash"],
		score_template=policy["template_id"],
		scoring_time=now_datetime().strftime("%Y-%m-%d %H:%M:%S"),
		fit_score=fit,
		engagement_score=engagement,
		intent_score=intent,
		time_decay_score=time_decay,
		negative_score=negative,
		final_score=final,
		score_change=final - float(student_doc.latest_score or 0),
		details=[
			{"category": "Fit", "signal": "Academic and programme fit", "score": fit},
			{"category": "Engagement", "signal": "Admission engagement", "score": engagement},
			{"category": "Intent", "signal": "Declared admission intent", "score": intent},
			{"category": "Negative", "signal": "Objection or inactivity", "score": negative},
		],
	)


def _ensure_escalated_sla(student: str):
	from crm.fcrm.student_sla import _process_due_attempt

	attempt_name = frappe.db.get_value("CRM Student SLA Attempt", {"student": student}, "name")
	if not attempt_name:
		raise frappe.ValidationError(f"Local admissions Student {student} has no SLA attempt.")
	attempt = frappe.get_doc("CRM Student SLA Attempt", attempt_name)
	if attempt.status == "escalated":
		return attempt.name
	for due_at in (attempt.warning_at, attempt.breach_at, attempt.escalation_at):
		attempt.reload()
		if attempt.status == "escalated":
			break
		_process_due_attempt(attempt.name, due_at)
	return attempt.name


def _ensure_responded_sla(student: str, interaction: str):
	"""Record the verified consultation as a qualifying SLA response."""
	from crm.fcrm.student_sla import record_qualifying_response

	attempt = frappe.db.get_value(
		"CRM Student SLA Attempt", {"student": student}, ["name", "status", "revision"], as_dict=True
	)
	if not attempt or attempt.status == "responded":
		return attempt.name if attempt else None
	return record_qualifying_response(attempt.name, interaction, expected_revision=int(attempt.revision or 0))


def _manifest_row(student: str, scenario: dict, task_names: list[str] | None = None) -> dict:
	doc = frappe.get_doc("CRM Student", student)
	attempt = frappe.db.get_value(
		"CRM Student SLA Attempt", {"student": student}, ["name", "status"], as_dict=True
	)
	return {
		"student": doc.name,
		"student_name": doc.student_name,
		"email": scenario["email"],
		"lifecycle_stage": doc.lifecycle_stage,
		"owner_staff": doc.owner_staff,
		"owning_pool": doc.owning_pool,
		"sla_attempt": attempt.name if attempt else None,
		"sla_status": attempt.status if attempt else None,
		"tasks": task_names or [],
	}
