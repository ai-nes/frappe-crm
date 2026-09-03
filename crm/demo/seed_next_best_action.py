"""Idempotent local demo data for the Director Next Best Action workspace.

This seed complements :mod:`crm.demo.seed_showcase`: the showcase already
creates Students, interactions and SLA attempts, while this module adds the
canonical assessment/recommendation/action chain consumed by the Director
read model. It only runs on ``crm.localhost`` and uses the governed services
for every aggregate write.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import frappe
from frappe.utils import now_datetime

from crm.fcrm.recommendation_producer import produce_recommendation
from crm.fcrm.student_assessment import record_student_assessment
from crm.fcrm.student_decision import decide_recommendation, transition_action

LOCAL_SITE = "crm.localhost"
NAMESPACE = "crm-demo-showcase:nba"
PRODUCER_ID = "demo:director-next-best-action"
POLICY_VERSION = "action-policy-2026.08"
MODEL_VERSION = "nba-demo-2026.09"
ASSESSMENT_POLICY_VERSION = "student-360-assessment-v1"


_PROFILES: tuple[dict[str, Any], ...] = (
	{
		"key": "scholarship-counseling",
		"action": "COUNSELING",
		"priority": "high",
		"due_hours": -2,
		"expiry_days": 7,
		"interest": "High",
		"fit": "High",
		"barrier": "Cost",
		"probability": 72,
		"confidence": (91, 88, 86),
		"cta": "Tư vấn gói học bổng trong hôm nay",
		"reason": "Hồ sơ phù hợp ngành đăng ký nhưng đang chững lại ở bước cân nhắc học phí.",
		"talking_points": [
			"Xác nhận mức học phí gia đình đang cân nhắc.",
			"Giới thiệu học bổng đầu vào và mốc hoàn tất hồ sơ.",
		],
		"evidence": [
			{"display": "Đã tham dự webinar học bổng trong 7 ngày qua", "impact": "Tăng khả năng chuyển đổi", "confidence": 91, "projected_probability": 84},
			{"display": "Chưa có tương tác sau lần nhận bảng phí", "impact": "Rủi ro mất động lực", "confidence": 86},
		],
	},
	{
		"key": "parent-follow-up",
		"action": "CALL",
		"priority": "high",
		"due_hours": 2,
		"expiry_days": 5,
		"interest": "High",
		"fit": "Medium",
		"barrier": "Family",
		"probability": 64,
		"confidence": (86, 78, 82),
		"cta": "Gọi phụ huynh để xác nhận kế hoạch nhập học",
		"reason": "Học sinh đã hỏi về ký túc xá nhưng quyết định còn phụ thuộc xác nhận từ gia đình.",
		"talking_points": [
			"Hỏi rõ mốc gia đình có thể chốt lựa chọn.",
			"Gửi lại thông tin ký túc xá theo nhu cầu đã nêu.",
		],
		"evidence": [
			{"display": "Phụ huynh yêu cầu gọi lại sau giờ làm", "impact": "Tín hiệu nhu cầu cao", "confidence": 89, "projected_probability": 78},
			{"display": "Đã xem trang thông tin ký túc xá 3 lần", "impact": "Có ý định tìm hiểu sâu", "confidence": 84},
		],
	},
	{
		"key": "campus-event-invite",
		"action": "EVENT_INVITE",
		"priority": "medium",
		"due_hours": 8,
		"expiry_days": 10,
		"interest": "High",
		"fit": "High",
		"barrier": "Information",
		"probability": 58,
		"confidence": (83, 90, 76),
		"cta": "Mời tham quan cơ sở gần nhất",
		"reason": "Mức độ quan tâm tốt nhưng hồ sơ chưa có trải nghiệm trực tiếp tại cơ sở.",
		"talking_points": [
			"Mời chọn một trong hai khung giờ tham quan cuối tuần.",
			"Chuẩn bị tư vấn viên theo nhóm ngành quan tâm.",
		],
		"evidence": [
			{"display": "Đã mở email giới thiệu campus nhưng chưa đăng ký lịch", "impact": "Còn thiếu bước xác thực", "confidence": 81, "projected_probability": 71},
			{"display": "Phù hợp cao với ngành và cơ sở mục tiêu", "impact": "Cơ hội chuyển đổi tốt", "confidence": 88},
		],
	},
	{
		"key": "information-email",
		"action": "EMAIL",
		"priority": "medium",
		"due_hours": 26,
		"expiry_days": 8,
		"interest": "Medium",
		"fit": "High",
		"barrier": "Information",
		"probability": 49,
		"confidence": (75, 87, 80),
		"cta": "Gửi lại thông tin ngành và lộ trình học",
		"reason": "Hồ sơ có độ phù hợp tốt nhưng còn thiếu thông tin về lộ trình nghề nghiệp.",
		"talking_points": [
			"Đính kèm lộ trình học 4 năm và các mốc thực tập.",
			"Nêu ví dụ đầu ra nghề nghiệp đúng ngành quan tâm.",
		],
		"evidence": [
			{"display": "Đã tải brochure ngành nhưng chưa hoàn tất form tư vấn", "impact": "Cần bổ sung thông tin", "confidence": 79, "projected_probability": 63},
			{"display": "Điểm phù hợp ngành ở mức cao", "impact": "Nền tảng hồ sơ tích cực", "confidence": 87},
		],
	},
	{
		"key": "application-document-check",
		"action": "FOLLOW_UP",
		"priority": "high",
		"due_hours": 44,
		"expiry_days": 12,
		"interest": "High",
		"fit": "High",
		"barrier": "Capability",
		"probability": 81,
		"confidence": (94, 92, 87),
		"cta": "Theo dõi bổ sung giấy tờ hồ sơ",
		"reason": "Khả năng nhập học cao; chỉ còn một giấy tờ đầu vào chưa được xác nhận.",
		"talking_points": [
			"Xác nhận thời điểm học sinh có thể bổ sung giấy tờ.",
			"Đề nghị hỗ trợ kiểm tra bản scan trước khi nộp.",
		],
		"evidence": [
			{"display": "Đã hoàn thành 4/5 bước hồ sơ", "impact": "Gần hoàn tất đăng ký", "confidence": 95, "projected_probability": 91},
			{"display": "Thiếu xác nhận học bạ bản chính", "impact": "Điểm nghẽn có thể xử lý", "confidence": 90},
		],
	},
	{
		"key": "career-consultation",
		"action": "COUNSELING",
		"priority": "medium",
		"due_hours": 50,
		"expiry_days": 14,
		"interest": "Medium",
		"fit": "Medium",
		"barrier": "Competition",
		"probability": 43,
		"confidence": (79, 73, 77),
		"cta": "Đặt lịch tư vấn định hướng nghề nghiệp",
		"reason": "Học sinh đang so sánh nhiều trường và cần một cuộc trao đổi theo mục tiêu nghề nghiệp.",
		"talking_points": [
			"Bắt đầu từ mục tiêu nghề nghiệp thay vì giới thiệu chương trình chung.",
			"So sánh ngắn gọn lợi thế của ngành đang quan tâm.",
		],
		"evidence": [
			{"display": "Đã tương tác với nội dung của 3 trường khác nhau", "impact": "Rủi ro cạnh tranh cao", "confidence": 82, "projected_probability": 56},
			{"display": "Chưa có cuộc gọi tư vấn chuyên sâu", "impact": "Cơ hội tạo khác biệt", "confidence": 78},
		],
	},
	{
		"key": "owner-handoff",
		"action": "HANDOFF",
		"priority": "high",
		"due_hours": 72,
		"expiry_days": 10,
		"interest": "High",
		"fit": "Medium",
		"barrier": "Geography",
		"probability": 67,
		"confidence": (88, 80, 85),
		"cta": "Chuyển người phụ trách theo khu vực",
		"reason": "Học sinh ở ngoài địa bàn hiện tại; nên chuyển cho tư vấn viên phụ trách khu vực để tiếp tục.",
		"talking_points": [
			"Bàn giao đầy đủ lịch sử tương tác và nhu cầu chính.",
			"Đặt mốc liên hệ đầu tiên trong ngày làm việc kế tiếp.",
		],
		"evidence": [
			{"display": "Địa chỉ hiện tại khác khu vực phụ trách", "impact": "Cần điều phối ownership", "confidence": 93, "projected_probability": 76},
			{"display": "Hồ sơ vẫn phản hồi tốt trong 14 ngày gần nhất", "impact": "Nên xử lý sớm", "confidence": 84},
		],
	},
	{
		"key": "accepted-active-follow-up",
		"action": "CALL",
		"priority": "high",
		"due_hours": 4,
		"expiry_days": 7,
		"interest": "High",
		"fit": "High",
		"barrier": "None",
		"probability": 76,
		"confidence": (92, 91, 90),
		"cta": "Gọi xác nhận lịch nộp hồ sơ",
		"reason": "Hồ sơ đã được tư vấn viên tiếp nhận; cần xác nhận mốc nộp hồ sơ tiếp theo.",
		"talking_points": [
			"Xác nhận ngày gia đình có thể hoàn tất hồ sơ.",
			"Đề nghị hỗ trợ trực tiếp nếu còn vướng biểu mẫu.",
		],
		"evidence": [
			{"display": "Đã đồng ý nhận checklist hồ sơ", "impact": "Sẵn sàng thực hiện", "confidence": 92, "projected_probability": 88},
			{"display": "Có lịch hẹn gọi lại với tư vấn viên", "impact": "Đang trong luồng xử lý", "confidence": 89},
		],
		"accepted": True,
	},
	{
		"key": "completed-scholarship-call",
		"action": "CALL",
		"priority": "medium",
		"due_hours": -24,
		"expiry_days": 5,
		"interest": "High",
		"fit": "High",
		"barrier": "Cost",
		"probability": 69,
		"confidence": (90, 88, 84),
		"cta": "Theo dõi sau cuộc gọi học bổng",
		"reason": "Đã hoàn tất cuộc gọi về học bổng; cần ghi nhận ảnh hưởng đến quyết định nhập học.",
		"talking_points": ["Ghi nhận phản hồi của gia đình sau khi nhận chính sách học bổng."],
		"evidence": [
			{"display": "Đã nhận bảng tính học phí theo phương án học bổng", "impact": "Giảm rào cản chi phí", "confidence": 93, "projected_probability": 82},
		],
		"accepted": True,
		"outcome": ("INTEREST_INCREASED", "Gia đình xác nhận tiếp tục hoàn thiện hồ sơ sau cuộc gọi học bổng."),
	},
	{
		"key": "completed-application-support",
		"action": "CALL",
		"priority": "high",
		"due_hours": -48,
		"expiry_days": 6,
		"interest": "High",
		"fit": "High",
		"barrier": "Capability",
		"probability": 88,
		"confidence": (95, 94, 91),
		"cta": "Xác nhận hồ sơ đã sẵn sàng nộp",
		"reason": "Hồ sơ gần hoàn tất; hành động tiếp theo là xác nhận bộ giấy tờ cuối cùng.",
		"talking_points": ["Kiểm tra lại giấy tờ cuối trước khi chuyển trạng thái hồ sơ."],
		"evidence": [
			{"display": "Đã hoàn tất checklist hồ sơ trực tuyến", "impact": "Khả năng nộp hồ sơ cao", "confidence": 96, "projected_probability": 94},
		],
		"accepted": True,
		"outcome": ("APPLICATION_STARTED", "Học sinh đã bắt đầu quy trình nộp hồ sơ sau khi được hỗ trợ."),
	},
)


def _assert_local_site() -> None:
	if frappe.local.site != LOCAL_SITE:
		frappe.throw("Next Best Action demo seed chỉ được phép chạy trên crm.localhost.", frappe.PermissionError)


def _existing_seed_recommendations() -> dict[str, dict[str, Any]]:
	if not frappe.db.table_exists("CRM Recommendation"):
		return {}
	rows = frappe.get_all(
		"CRM Recommendation",
		filters={"rule_key": ["like", f"{NAMESPACE}:%"]},
		fields=["name", "student", "rule_key", "source_intent_id", "status", "decision_revision"],
		limit_page_length=0,
	)
	return {str(row.rule_key): row for row in rows}


def _students_for_seed(existing: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
	rows = frappe.get_all(
		"CRM Student",
		filters={"admission_year": "2026", "owner_staff": ["is", "set"]},
		fields=["name", "student_name", "owner_staff"],
		order_by="creation asc, name asc",
		limit_page_length=0,
	)
	by_name = {str(row.name): row for row in rows}
	selected: dict[str, dict[str, Any]] = {}
	used = set()
	for profile in _PROFILES:
		rule_key = f"{NAMESPACE}:{profile['key']}"
		row = existing.get(rule_key)
		if row and str(row.student) in by_name:
			selected[profile["key"]] = by_name[str(row.student)]
			used.add(str(row.student))

	confirmed = set(
		frappe.get_all(
			"CRM Student Assessment",
			filters={"status": "confirmed"},
			pluck="student",
			limit_page_length=0,
		)
	)
	available = [row for row in rows if str(row.name) not in used and str(row.name) not in confirmed]
	for profile in _PROFILES:
		key = profile["key"]
		if key in selected:
			continue
		if not available:
			frappe.throw("Không đủ CRM Student chưa có assessment để tạo NBA demo.", frappe.ValidationError)
		selected[key] = available.pop(0)
		used.add(str(selected[key].name))
	return selected


def _ensure_assessment(student: str, profile: dict[str, Any]) -> bool:
	current = frappe.db.get_value(
		"CRM Student Assessment",
		{"student": student, "status": "confirmed"},
		"name",
		order_by="assessment_revision desc, creation desc",
	)
	if current:
		return False
	interest_confidence, fit_confidence, barrier_confidence = profile["confidence"]
	record_student_assessment(
		student,
		{
			"interest": profile["interest"],
			"interest_confidence": interest_confidence,
			"fit": profile["fit"],
			"fit_confidence": fit_confidence,
			"primary_barrier": profile["barrier"],
			"barrier_confidence": barrier_confidence,
			"enrollment_probability": profile["probability"],
		},
		source="manual",
		reason=profile["reason"],
		evidence_references=[item["display"] for item in profile["evidence"]],
		policy_version=ASSESSMENT_POLICY_VERSION,
		model_version=MODEL_VERSION,
		confirm=True,
	)
	return True


def _ensure_recommendation(
	student: str, profile: dict[str, Any], existing: dict[str, dict[str, Any]], as_of
):
	key = profile["key"]
	rule_key = f"{NAMESPACE}:{key}"
	source_intent_id = f"{NAMESPACE}:{student}:{key}"
	if rule_key in existing and str(existing[rule_key].student) == student:
		return frappe.get_doc("CRM Recommendation", existing[rule_key].name), False
	recommendation = produce_recommendation(
		student=student,
		rule_key=rule_key,
		source_intent_id=source_intent_id,
		recommended_action=profile["action"],
		priority=profile["priority"],
		reason=profile["reason"],
		evidence=profile["evidence"],
		recommended_timing=as_of + timedelta(hours=profile["due_hours"]),
		expires_at=as_of + timedelta(days=profile["expiry_days"]),
		cta=profile["cta"],
		talking_points=profile["talking_points"],
		condition_version=1,
		policy_version=POLICY_VERSION,
		producer_revision=1,
	)
	return recommendation, True


def _ensure_accepted_action(recommendation, student: dict[str, Any], profile: dict[str, Any], as_of):
	if recommendation.status != "accepted":
		decide_recommendation(
			name=recommendation.name,
			expected_revision=int(recommendation.decision_revision or 0),
			status="accepted",
			idempotency_key=f"{NAMESPACE}:accept:{profile['key']}:{student['name']}",
			correlation_id=f"{NAMESPACE}:accept:{profile['key']}:{student['name']}",
			decision_reason="Đã xác nhận trong luồng demo Director Next Best Action.",
			due_at=as_of + timedelta(hours=profile["due_hours"]),
			assignee_staff=student.owner_staff,
		)
	return frappe.get_doc(
		"CRM Action", frappe.db.get_value("CRM Action", {"recommendation": recommendation.name}, "name")
	)


def _ensure_completed_action(action, profile: dict[str, Any], student_name: str) -> bool:
	if action.state == "completed":
		return False
	if action.state == "accepted":
		transition_action(
			name=action.name,
			expected_revision=int(action.action_revision or 1),
			status="in_progress",
			idempotency_key=f"{NAMESPACE}:start:{profile['key']}:{student_name}",
			correlation_id=f"{NAMESPACE}:start:{profile['key']}:{student_name}",
			_internal_service=True,
		)
		action.reload()
	if action.state != "in-progress":
		frappe.throw(f"Không thể hoàn tất action {action.name} ở trạng thái {action.state}.", frappe.ValidationError)
	outcome_code, evidence = profile["outcome"]
	transition_action(
		name=action.name,
		expected_revision=int(action.action_revision or 1),
		status="completed",
		outcome_code=outcome_code,
		evidence=evidence,
		idempotency_key=f"{NAMESPACE}:complete:{profile['key']}:{student_name}",
		correlation_id=f"{NAMESPACE}:complete:{profile['key']}:{student_name}",
		_internal_service=True,
	)
	return True


def execute() -> dict[str, Any]:
	"""Seed realistic NBA rows and return a compact manifest."""
	_assert_local_site()
	previous_user = frappe.session.user
	previous_producer = frappe.conf.get("crm_recommendation_producer_id")
	frappe.set_user("Administrator")
	frappe.conf["crm_recommendation_producer_id"] = PRODUCER_ID
	created = {"assessments": 0, "recommendations": 0, "accepted": 0, "completed": 0}
	try:
		existing = _existing_seed_recommendations()
		students = _students_for_seed(existing)
		as_of = now_datetime()
		for profile in _PROFILES:
			student = students[profile["key"]]
			student_name = str(student.name)
			created["assessments"] += int(_ensure_assessment(student_name, profile))
			recommendation, was_created = _ensure_recommendation(
				student_name, profile, existing, as_of
			)
			created["recommendations"] += int(was_created)
			if profile.get("accepted"):
				was_already_accepted = recommendation.status == "accepted"
				action = _ensure_accepted_action(recommendation, student, profile, as_of)
				created["accepted"] += int(not was_already_accepted)
				if profile.get("outcome"):
					created["completed"] += int(
						_ensure_completed_action(action, profile, student_name)
					)
		frappe.db.commit()
		result = {
			"namespace": NAMESPACE,
			"model_version": MODEL_VERSION,
			"policy_version": POLICY_VERSION,
			"students": len(students),
			"rows": created,
			"note": "Idempotent; chạy lại không tạo recommendation/action/assessment trùng.",
		}
		print(frappe.as_json(result))
		return result
	finally:
		if previous_producer is None:
			frappe.conf.pop("crm_recommendation_producer_id", None)
		else:
			frappe.conf["crm_recommendation_producer_id"] = previous_producer
		frappe.set_user(previous_user)


def verify() -> dict[str, Any]:
	"""Verify that the local NBA dataset is visible to the canonical aggregates."""
	_assert_local_site()
	counts = {
		"recommendations": frappe.db.count(
			"CRM Recommendation", {"rule_key": ["like", f"{NAMESPACE}:%"]}
		),
		"assessments": frappe.db.count(
			"CRM Student Assessment", {"model_version": MODEL_VERSION, "status": "confirmed"}
		),
	}
	recommendations = frappe.get_all(
		"CRM Recommendation",
		filters={"rule_key": ["like", f"{NAMESPACE}:%"]},
		pluck="name",
		limit_page_length=0,
	)
	counts["actions"] = frappe.db.count("CRM Action", {"recommendation": ["in", recommendations]}) if recommendations else 0
	result = {"namespace": NAMESPACE, "ok": counts["recommendations"] == len(_PROFILES), "counts": counts}
	print(frappe.as_json(result))
	return result


def reset() -> dict[str, int]:
	"""Remove only this module's recommendation/assessment data on localhost."""
	_assert_local_site()
	previous_user = frappe.session.user
	frappe.set_user("Administrator")
	deleted = {"actions": 0, "recommendations": 0, "assessments": 0}
	try:
		recommendations = frappe.get_all(
			"CRM Recommendation",
			filters={"rule_key": ["like", f"{NAMESPACE}:%"]},
			pluck="name",
			limit_page_length=0,
		)
		for recommendation in recommendations:
			actions = frappe.get_all(
				"CRM Action", filters={"recommendation": recommendation}, pluck="name", limit_page_length=0
			)
			for action in actions:
				frappe.delete_doc("CRM Action", action, force=True, ignore_permissions=True, delete_permanently=True)
			deleted["actions"] += len(actions)
			frappe.delete_doc(
				"CRM Recommendation", recommendation, force=True, ignore_permissions=True, delete_permanently=True
			)
			deleted["recommendations"] += 1
		assessments = frappe.get_all(
			"CRM Student Assessment",
			filters={"model_version": MODEL_VERSION},
			pluck="name",
			limit_page_length=0,
		)
		for assessment in assessments:
			frappe.delete_doc(
				"CRM Student Assessment", assessment, force=True, ignore_permissions=True, delete_permanently=True
			)
		deleted["assessments"] += 1
		frappe.db.commit()
		print(frappe.as_json(deleted))
		return deleted
	finally:
		frappe.set_user(previous_user)
