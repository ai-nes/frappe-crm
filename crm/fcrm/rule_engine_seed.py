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

from crm.fcrm.action_type_catalog import canonicalize_action_type
from crm.fcrm.rule_engine import normalize_rule_data

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
			"fact": "application.missing_count",
			"op": "gt",
			"value": 0,
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
		"condition": {"fact": "contact.email_bounced", "op": "is_true"},
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
			"fact": "student.stage",
			"op": "in",
			"value": ["Attempting", "Connected"],
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
			"fact": "application.missing_count",
			"op": "gt",
			"value": 0,
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
			"fact": "application.days_to_deadline",
			"op": "lt",
			"value": 0,
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

RULE_GROUP_CODES = {
	"Student Eligibility": "student_eligibility",
	"Communication": "communication",
	"Funnel": "funnel",
	"Action": "action",
}


def _group_catalog_for(rows: list[dict]) -> list[dict]:
	"""Build the canonical version-scoped groups used by the seed rules."""
	seen = set()
	groups = []
	for row in rows:
		label = str(row["rule_group"]).strip()
		if label in seen:
			continue
		seen.add(label)
		code = RULE_GROUP_CODES.get(label)
		if not code:
			raise ValueError(f"Unsupported seed rule group: {label}")
		groups.append(
			{
				"code": code,
				"label": label,
				"enabled": True,
				"description": f"{label} rules from the FAIP CRM seed catalog.",
				"sort_order": len(groups) * 10 + 10,
			}
		)
	return groups


def _canonical_seed_rule(row: dict, version_id: str) -> dict:
	"""Translate the historical seed literals into the current rule contract."""
	group_code = RULE_GROUP_CODES.get(str(row["rule_group"]).strip())
	if not group_code:
		raise ValueError(f"Unsupported seed rule group: {row['rule_group']}")
	return normalize_rule_data(
		{
			"rule_version": version_id,
			"rule_id": row["rule_id"],
			"group_code": group_code,
			"rule_name": row["rule_name"],
			"description": row.get("description"),
			"feature": row.get("feature_scope"),
			"rule_type": row.get("rule_type"),
			"outcome": row.get("gate_outcome"),
			"precedence": row.get("priority"),
			"unknown_policy": row.get("unknown_policy", "WAIT"),
			"reason_code": row.get("reason_code") or f"RULE_{str(row['rule_id']).replace('-', '_')}",
			"target_actions": [
				canonicalize_action_type(str(action).strip().upper())
				for action in row.get("target_actions") or []
			],
			"condition": row.get("condition"),
			"business_reason_template": row.get(
				"business_reason_template", "{action} is governed by {rule_name}."
			),
			"sales_next_step_template": row.get(
				"sales_next_step_template", "Chưa có bước tiếp theo được xác định."
			),
			"enabled": row.get("enabled", True),
			"status": "draft",
			"revision": 0,
		}
	)


def _api_rule_values(data: dict) -> dict:
	"""Return only fields accepted by the rule admin command."""
	return {
		fieldname: data[fieldname]
		for fieldname in (
			"rule_id",
			"group_code",
			"rule_name",
			"description",
			"feature",
			"rule_type",
			"outcome",
			"precedence",
			"unknown_policy",
			"reason_code",
			"business_reason_template",
			"sales_next_step_template",
			"target_actions",
			"conditions",
			"enabled",
		)
	}


def _ensure_version(
	version_id: str = RULE_VERSION_ID,
	version_name: str = RULE_VERSION_NAME,
	description: str = RULE_VERSION_DESCRIPTION,
	group_catalog: list[dict] | None = None,
) -> str:
	if frappe.db.exists("CRM Rule Version", version_id):
		return version_id
	from crm.api.rule_engine import create_rule_version

	result = create_rule_version(
		version_id=version_id,
		version_name=version_name,
		description=description,
		group_catalog=group_catalog or _group_catalog_for(RULES),
	)
	return result["name"]


def _upsert_rule(version_name: str, row: dict) -> bool:
	"""Create or update one rule through the current admin command seam."""
	from crm.api.rule_engine import create_rule, update_rule

	version = frappe.get_doc("CRM Rule Version", version_name)
	data = _canonical_seed_rule(row, version.version_id)
	existing_name = frappe.db.exists("CRM Rule", {"rule_version": version.name, "rule_id": data["rule_id"]})
	values = _api_rule_values(data)
	if existing_name:
		update_rule(
			name=existing_name,
			expected_version_revision=int(version.revision or 0),
			**values,
		)
		return False
	create_rule(
		version_name=version.version_id,
		expected_version_revision=int(version.revision or 0),
		**values,
	)
	return True


def seed_catalog() -> dict:
	if not frappe.db.exists("DocType", "CRM Rule Version") or not frappe.db.exists("DocType", "CRM Rule"):
		return {"status": "skipped", "reason": "rule_engine_doctypes_unavailable"}

	version_name = _ensure_version(group_catalog=_group_catalog_for(RULES))
	version = frappe.get_doc("CRM Rule Version", version_name)
	if str(version.status or "draft").lower() != "draft":
		return {
			"status": "skipped",
			"reason": "version_not_draft",
			"version": version_name,
			"version_status": version.status,
		}
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


def ensure_active_catalog() -> dict:
	"""Create and activate the default catalog once on an existing site."""
	if any(
		not frappe.db.exists("DocType", doctype)
		for doctype in ("CRM Rule Version", "CRM Rule", "CRM Rule Settings")
	):
		return {"status": "skipped", "reason": "rule_engine_doctypes_unavailable"}

	settings = frappe.db.get_singles_dict("CRM Rule Settings", cast=True)
	if settings and settings.get("active_rule_version") and settings.get("active_ruleset_digest"):
		return {
			"status": "already_active",
			"version": settings.get("active_rule_version"),
			"pointer_revision": int(settings.get("pointer_revision") or 0),
		}
	if frappe.db.count("CRM Rule Version", {"status": "active"}):
		frappe.throw("An active CRM Rule Version exists but CRM Rule Settings has no complete pointer.")

	seed_result = seed_catalog()
	version_name = seed_result.get("version")
	version = frappe.get_doc("CRM Rule Version", version_name)
	from crm.api.rule_engine import update_rule_version

	version_status = str(version.status or "draft").lower()
	if version_status not in {"draft", "testing"}:
		frappe.throw(f"Cannot bootstrap a CRM Rule Version in {version_status} status.")
	if version_status == "draft":
		update_rule_version(
			name=version.name,
			expected_revision=int(version.revision or 0),
			status="testing",
			change_note="Bootstrap the default FAIP rule catalog for the CRM runtime.",
		)
		version.reload()

	settings = frappe.db.get_singles_dict("CRM Rule Settings", cast=True)
	update_rule_version(
		name=version.name,
		expected_revision=int(version.revision or 0),
		expected_settings_revision=int((settings or {}).get("pointer_revision") or 0),
		status="active",
		change_note="Activate the default FAIP rule catalog for the CRM runtime.",
	)
	return {
		"status": "activated",
		"version": version.name,
		"rules": frappe.db.count("CRM Rule", {"rule_version": version.name}),
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
		version_name = _ensure_version(
			spec["version_id"],
			spec["version_name"],
			spec["description"],
			_group_catalog_for(spec["rules"]),
		)
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
