"""CRM Rule Engine seed sourced from ``docs/FAIP Rule Engine Rules.pdf``.

Run with::

    bench --site crm.localhost execute crm.fcrm.rule_engine_seed.seed_catalog

or ``task seed-rule-engine``. Idempotent: safe to re-run after editing
``RULES`` below, it upserts by ``rule_id`` inside one draft
``CRM Rule Version`` (``FAIP-V1``).

Scope note
----------
The PDF documents eleven rule groups. Only the four seeded here — Student
Eligibility, Communication, Funnel/Admission and Action guardrails — can be
expressed exactly with the CRM Rule ``FACT_CATALOG``
(``crm/fcrm/rule_engine.py``), which is deliberately a narrow, contract-bound
list of thirteen facts backed by real ``CRM Student`` /
``CRM Admission Application`` fields. The remaining PDF groups (NBA Action,
Uplift, most of Priority, Timing, Governance/Security, AI Quality, Business)
reference facts the catalog does not expose yet — intent/engagement/uplift/
drop-off scores, contact counters, quiet hours and day-of-week windows,
model confidence, campaign fields, permission checks. Inventing facts for
those would misrepresent the real evaluator contract, so they are left out
on purpose; exposing them is a separate ``FACT_CATALOG`` change, not a seed
data problem. A few PDF conditions were also re-pointed at the closest real
enum values instead of the PDF's own placeholder values, since the PDF's
prose (e.g. ``Student.status = Active``) predates the concrete schema:

* ``student.stage`` uses the real ``CRM Student.student_stage`` options
  (New / Attempting / Connected / Qualified / Disqualified), not the PDF's
  Active/Inactive/Enrolled placeholders.
* ``application.status`` uses the real ``CRM Admission Application.status``
  options (Draft / Submitted / Under Review / Accepted / Enrolled / Lost /
  Withdrawn); "Enrolled" and "Draft" (for the PDF's "Incomplete") live here,
  not on the student.
"""

from __future__ import annotations

import frappe

RULE_VERSION_ID = "FAIP-V1"
RULE_VERSION_NAME = "FAIP Rule Engine Seed v1"
RULE_VERSION_DESCRIPTION = (
	"Seeded from docs/FAIP Rule Engine Rules.pdf: Student Eligibility, "
	"Communication, Funnel/Admission and Action guardrail rules that the "
	"current CRM Rule fact catalog can express exactly."
)

RULES: list[dict] = [
	# --- 1. Student Eligibility Rules ---
	{
		"rule_id": "ELG-001",
		"rule_group": "Student Eligibility",
		"rule_name": "Student Active",
		"description": "Chỉ cho phép AI xử lý student chưa bị loại khỏi phễu tuyển sinh.",
		"feature_scope": "student_360",
		"rule_type": "ELIGIBILITY",
		"gate_outcome": "PASS",
		"priority": 700,
		"action": "ALLOW_AI",
		"target_actions": [],
		"condition": {"fact": "student.stage", "op": "neq", "value": "Disqualified"},
	},
	{
		"rule_id": "ELG-002",
		"rule_group": "Student Eligibility",
		"rule_name": "Student Disqualified",
		"description": "Không tạo recommendation hoặc sales action cho student đã bị loại.",
		"feature_scope": "student_360",
		"rule_type": "GUARDRAIL",
		"gate_outcome": "STOP",
		"priority": 700,
		"action": "BLOCK_AI",
		"target_actions": [],
		"condition": {"fact": "student.stage", "op": "eq", "value": "Disqualified"},
	},
	{
		"rule_id": "ELG-004",
		"rule_group": "Student Eligibility",
		"rule_name": "Already Applied",
		"description": "Student đã nộp application thì không recommend hành động Apply nữa.",
		"feature_scope": "all",
		"rule_type": "GUARDRAIL",
		"gate_outcome": "STOP",
		"priority": 700,
		"action": "BLOCK_APPLY_ACTION",
		"target_actions": [],
		"condition": {"fact": "application.status", "op": "eq", "value": "Submitted"},
	},
	{
		"rule_id": "ELG-007",
		"rule_group": "Student Eligibility",
		"rule_name": "Missing Admission Data",
		"description": "Khi hồ sơ còn thiếu tài liệu bắt buộc, yêu cầu bổ sung trước khi AI ra quyết định.",
		"feature_scope": "all",
		"rule_type": "PREREQUISITE",
		"gate_outcome": "WAIT",
		"priority": 400,
		"action": "REQUEST_DATA",
		"target_actions": [],
		"condition": {
			"fact": "application.document_completed",
			"op": "lt",
			"fact_ref": "application.document_total",
		},
	},
	# --- 2. Communication Rules ---
	{
		"rule_id": "COM-008",
		"rule_group": "Communication",
		"rule_name": "Opt-out",
		"description": "Student đã từ chối nhận thông tin thì không được tiếp tục contact.",
		"feature_scope": "all",
		"rule_type": "GUARDRAIL",
		"gate_outcome": "STOP",
		"priority": 900,
		"action": "BLOCK_CONTACT",
		"target_actions": [],
		"condition": {"fact": "student.is_opted_out", "op": "is_true"},
	},
	{
		"rule_id": "COM-009",
		"rule_group": "Communication",
		"rule_name": "Invalid Contact",
		"description": "Không thực hiện contact nếu email của student đã bounce.",
		"feature_scope": "all",
		"rule_type": "GUARDRAIL",
		"gate_outcome": "STOP",
		"priority": 700,
		"action": "BLOCK_CONTACT",
		"target_actions": [],
		"condition": {"fact": "student.email_bounced", "op": "is_true"},
	},
	# --- 3. Funnel / Admission Rules ---
	{
		"rule_id": "FNL-001",
		"rule_group": "Funnel",
		"rule_name": "New Student",
		"description": "Student mới cần được phép thực hiện initial contact.",
		"feature_scope": "student_360",
		"rule_type": "PREREQUISITE",
		"gate_outcome": "PASS",
		"priority": 400,
		"action": "ALLOW_INITIAL_CONTACT",
		"target_actions": [],
		"condition": {"fact": "student.stage", "op": "eq", "value": "New"},
	},
	{
		"rule_id": "FNL-002",
		"rule_group": "Funnel",
		"rule_name": "Contacted Student",
		"description": "Student đã được liên hệ có thể tiếp tục follow-up phù hợp.",
		"feature_scope": "student_360",
		"rule_type": "PREREQUISITE",
		"gate_outcome": "PASS",
		"priority": 400,
		"action": "ALLOW_FOLLOWUP",
		"target_actions": [],
		"condition": {
			"any": [
				{"fact": "student.stage", "op": "eq", "value": "Attempting"},
				{"fact": "student.stage", "op": "eq", "value": "Connected"},
			]
		},
	},
	{
		"rule_id": "FNL-003",
		"rule_group": "Funnel",
		"rule_name": "Already Enrolled",
		"description": "Student đã enrolled không cần tiếp tục xử lý sales/NBA conversion.",
		"feature_scope": "nba",
		"rule_type": "GUARDRAIL",
		"gate_outcome": "STOP",
		"priority": 700,
		"action": "BLOCK_SALES_NBA",
		"target_actions": [],
		"condition": {"fact": "application.status", "op": "eq", "value": "Enrolled"},
	},
	{
		"rule_id": "FNL-004",
		"rule_group": "Funnel",
		"rule_name": "Application Incomplete",
		"description": "Student đã bắt đầu application nhưng chưa nộp, cần được nhắc hoàn thành.",
		"feature_scope": "all",
		"rule_type": "MODIFIER",
		"gate_outcome": "PASS",
		"priority": 700,
		"action": "RECOMMEND_COMPLETE_APPLICATION",
		"target_actions": [],
		"condition": {"fact": "application.status", "op": "eq", "value": "Draft"},
	},
	{
		"rule_id": "FNL-005",
		"rule_group": "Funnel",
		"rule_name": "Missing Documents",
		"description": "Student còn thiếu hồ sơ cần được nhắc bổ sung tài liệu.",
		"feature_scope": "all",
		"rule_type": "MODIFIER",
		"gate_outcome": "PASS",
		"priority": 700,
		"action": "RECOMMEND_DOCUMENT_FOLLOWUP",
		"target_actions": [],
		"condition": {
			"fact": "application.document_completed",
			"op": "lt",
			"fact_ref": "application.document_total",
		},
	},
	{
		"rule_id": "FNL-006",
		"rule_group": "Funnel",
		"rule_name": "Application Submitted",
		"description": "Không recommend lại action Submit Application khi đã submitted.",
		"feature_scope": "all",
		"rule_type": "GUARDRAIL",
		"gate_outcome": "STOP",
		"priority": 700,
		"action": "BLOCK_APPLY_ACTION",
		"target_actions": [],
		"condition": {"fact": "application.status", "op": "eq", "value": "Submitted"},
	},
	{
		"rule_id": "FNL-007",
		"rule_group": "Funnel",
		"rule_name": "Admission Deadline Passed",
		"description": "Không tạo action liên quan đến deadline đã hết hạn.",
		"feature_scope": "all",
		"rule_type": "GUARDRAIL",
		"gate_outcome": "STOP",
		"priority": 900,
		"action": "BLOCK_DEADLINE_ACTION",
		"target_actions": [],
		"condition": {
			"fact": "application.deadline",
			"op": "before",
			"fact_ref": "system.now",
		},
	},
	# --- 5. Action Rules ---
	{
		"rule_id": "ACT-001",
		"rule_group": "Action",
		"rule_name": "Call Allowed",
		"description": "Cho phép gọi khi student đủ điều kiện và chưa opt-out.",
		"feature_scope": "all",
		"rule_type": "GUARDRAIL",
		"gate_outcome": "PASS",
		"priority": 700,
		"action": "ALLOW",
		"target_actions": ["CALL"],
		"condition": {
			"all": [
				{"fact": "requested_action.channel", "op": "eq", "value": "CALL"},
				{"fact": "student.is_opted_out", "op": "is_false"},
			]
		},
	},
	{
		"rule_id": "ACT-002",
		"rule_group": "Action",
		"rule_name": "Message Allowed",
		"description": "Cho phép gửi message khi channel hợp lệ và student chưa opt-out.",
		"feature_scope": "all",
		"rule_type": "GUARDRAIL",
		"gate_outcome": "PASS",
		"priority": 700,
		"action": "ALLOW",
		"target_actions": ["MESSAGE"],
		"condition": {
			"all": [
				{"fact": "requested_action.channel", "op": "eq", "value": "MESSAGE"},
				{"fact": "student.is_opted_out", "op": "is_false"},
			]
		},
	},
]


def _rules_for_groups(*group_names: str) -> list[dict]:
	return [row for row in RULES if row["rule_group"] in group_names]


MULTI_VERSION_SPECS = (
	{
		"version_id": RULE_VERSION_ID,
		"version_name": RULE_VERSION_NAME,
		"description": RULE_VERSION_DESCRIPTION,
		"status": "draft",
		"rules": RULES,
	},
	{
		"version_id": "FAIP-V2",
		"version_name": "FAIP Rule Engine Admission 2026",
		"description": "Bộ Rule tuyển sinh cho phiên bản Admission 2026.",
		"status": "draft",
		"rules": RULES,
	},
	{
		"version_id": "FAIP-V3",
		"version_name": "FAIP Rule Engine Communication 2026",
		"description": "Bộ Rule kiểm soát các kênh liên lạc với học sinh.",
		"status": "draft",
		"rules": _rules_for_groups("Communication"),
	},
	{
		"version_id": "FAIP-V4",
		"version_name": "FAIP Rule Engine Funnel 2026",
		"description": "Bộ Rule kiểm soát điều kiện và trạng thái trong phễu tuyển sinh.",
		"status": "draft",
		"rules": _rules_for_groups("Student Eligibility", "Funnel"),
	},
	{
		"version_id": "FAIP-V5",
		"version_name": "FAIP Rule Engine Action 2026",
		"description": "Bộ Rule kiểm soát các Action được phép thực hiện.",
		"status": "draft",
		"rules": _rules_for_groups("Action"),
	},
)


def _ensure_version(
	version_id: str = RULE_VERSION_ID,
	version_name: str = RULE_VERSION_NAME,
	description: str = RULE_VERSION_DESCRIPTION,
) -> str:
	if frappe.db.exists("CRM Rule Version", version_id):
		return version_id
	doc = frappe.new_doc("CRM Rule Version")
	doc.version_id = version_id
	doc.version_name = version_name
	doc.description = description
	doc.insert(ignore_permissions=True)
	return doc.name


def _upsert_rule(version_name: str, row: dict) -> bool:
	"""Create or update one CRM Rule. Returns True when a new row was created."""
	existing_name = frappe.db.exists("CRM Rule", {"rule_version": version_name, "rule_id": row["rule_id"]})
	doc = frappe.get_doc("CRM Rule", existing_name) if existing_name else frappe.new_doc("CRM Rule")
	if not existing_name:
		doc.rule_version = version_name
		doc.rule_id = row["rule_id"]
	for fieldname in (
		"rule_group",
		"rule_name",
		"description",
		"feature_scope",
		"rule_type",
		"gate_outcome",
		"priority",
		"action",
		"target_actions",
		"condition",
	):
		doc.set(fieldname, row[fieldname])
	if existing_name:
		doc.save(ignore_permissions=True)
		return False
	doc.insert(ignore_permissions=True)
	return True


def seed_catalog() -> dict:
	if not frappe.db.exists("DocType", "CRM Rule Version") or not frappe.db.exists("DocType", "CRM Rule"):
		return {"status": "skipped", "reason": "rule_engine_doctypes_unavailable"}

	version_name = _ensure_version()
	created = 0
	updated = 0
	for row in RULES:
		if _upsert_rule(version_name, row):
			created += 1
		else:
			updated += 1
	frappe.db.commit()
	return {
		"status": "ok",
		"version": version_name,
		"rules_created": created,
		"rules_updated": updated,
		"rules_total": len(RULES),
	}


def _reset_rule_engine_data() -> dict[str, int]:
	"""Delete only CRM Rule Engine rows before rebuilding local seed fixtures."""
	rule_names = frappe.get_all("CRM Rule", pluck="name", limit_page_length=100000)
	for rule_name in rule_names:
		frappe.db.delete("CRM Rule", rule_name)

	version_names = frappe.get_all("CRM Rule Version", pluck="name", limit_page_length=100000)
	for version_name in version_names:
		frappe.db.delete("CRM Rule Version", version_name)

	return {"rules_deleted": len(rule_names), "versions_deleted": len(version_names)}


def seed_many_versions() -> dict:
	"""Reset and seed multiple local CRM Rule Versions for UI testing."""
	if not frappe.db.exists("DocType", "CRM Rule Version") or not frappe.db.exists("DocType", "CRM Rule"):
		return {"status": "skipped", "reason": "rule_engine_doctypes_unavailable"}

	deleted = _reset_rule_engine_data()
	version_results = []
	for spec in MULTI_VERSION_SPECS:
		version_name = _ensure_version(spec["version_id"], spec["version_name"], spec["description"])
		created = 0
		for row in spec["rules"]:
			if _upsert_rule(version_name, row):
				created += 1
		if spec["status"] == "archived":
			frappe.db.set_value(
				"CRM Rule Version",
				version_name,
				{
					"status": "archived",
					"is_active": 0,
					"revision": 1,
					"archive_reason": "Seed UI fixture",
				},
				update_modified=False,
			)
		version_results.append(
			{
				"version": version_name,
				"status": spec["status"],
				"rules_created": created,
				"rules_total": len(spec["rules"]),
			}
		)

	frappe.db.commit()
	return {
		"status": "ok",
		**deleted,
		"versions_created": len(version_results),
		"rules_created": sum(item["rules_created"] for item in version_results),
		"versions": version_results,
	}
