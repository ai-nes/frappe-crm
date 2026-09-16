"""CRM Rule Engine seed for the FAIP MVP v3 catalog.

Run with::

    bench --site crm.localhost execute crm.fcrm.rule_engine_seed.seed_and_activate_catalog

or ``task seed-rule-engine``. Idempotent: safe to re-run after editing
``RULES`` below, it upserts by ``rule_id`` inside one draft
``CRM Rule Version`` (``FAIP-MVP-V3``). The six EXPLAINABILITY entries in the
source document are protected runtime policies, not ordinary business rules;
the runtime already enforces them through the decision/explanation contract.
The 83 executable rules are represented below. Rules whose source condition
does not have a corresponding closed Frappe fact are retained as disabled
catalog rows, so the snapshot is complete without inventing a fact producer.
"""

from __future__ import annotations

import frappe

from crm.fcrm.action_type_catalog import canonicalize_action_type
from crm.fcrm.rule_engine import normalize_rule_data

RULE_VERSION_ID = "FAIP-MVP-V3"
RULE_VERSION_NAME = "FAIP Rule Engine MVP v3"
RULE_VERSION_DESCRIPTION = (
	"Complete executable FAIP Rule Catalog MVP v3. The six EXPLAINABILITY "
	"policies remain protected runtime invariants."
)

_MISSING = object()

RULE_GROUP_CODES = {
	"Student Lifecycle": "student_lifecycle",
	"Application Admission": "application_admission",
	"Program Offering": "program_offering",
	"Communication": "communication",
	"Timing / Frequency": "timing_frequency",
	"Scholarship / Finance": "scholarship_finance",
	"Action Eligibility": "action_eligibility",
	"AI Admission": "ai_admission",
	"AI Reliability": "ai_reliability",
	"NBA Decision": "nba_decision",
	"Business Policy": "business_policy",
	"Explainability": "explainability",
}

PROTECTED_POLICIES = (
	"EXP-001",
	"EXP-002",
	"EXP-003",
	"EXP-004",
	"EXP-005",
	"EXP-006",
)
DOCUMENT_RULE_COUNT = 89


def _condition(fact: str, operator: str, value=_MISSING) -> dict:
	result = {"fact": fact, "op": operator}
	if value is not _MISSING:
		result["value"] = value
	return result


def _all(*conditions: dict) -> dict:
	return {"all": list(conditions)}


def _unsupported_condition() -> dict:
	"""Use a real fact while keeping an unsupported source policy disabled."""
	return _condition("student.stage", "exists")


def _doc_rule(
	rule_id: str,
	group: str,
	name: str,
	rule_type: str,
	outcome: str,
	condition: dict | None = None,
	*,
	feature: str = "nba",
	target_actions: tuple[str, ...] = (),
	enabled: bool = True,
	priority: int | None = None,
	source_condition: str = "",
	effect: str = "",
	applies_to: str = "",
) -> dict:
	return {
		"rule_id": rule_id,
		"rule_group": group,
		"rule_name": name,
		"description": " | ".join(
			part
			for part in (
				f"FAIP MVP v3: {source_condition}" if source_condition else None,
				f"Effect: {effect}" if effect else None,
				f"Applies to: {applies_to}" if applies_to else None,
			)
			if part
		),
		"feature_scope": feature,
		"rule_type": rule_type,
		"gate_outcome": outcome,
		"priority": priority
		or (950 if rule_type == "RESOLUTION" else 900 if outcome in {"STOP", "WAIT"} else 600),
		"target_actions": list(target_actions),
		"condition": condition or _unsupported_condition(),
		"enabled": enabled,
		"business_reason_template": "{action}: hệ thống áp dụng quy tắc {rule_name}.",
		"sales_next_step_template": "Kiểm tra dữ liệu liên quan và thực hiện bước tiếp theo phù hợp.",
	}


RULES: list[dict] = [
	# STUDENT_LIFECYCLE (6)
	_doc_rule(
		"STU-001",
		"Student Lifecycle",
		"Student Active",
		"ELIGIBILITY",
		"PASS",
		_condition("student.stage", "neq", "Disqualified"),
		feature="all",
		source_condition="student.status = Active",
		effect="ALLOW_AI",
		applies_to="Intent / 360 / NBA / Copilot",
	),
	_doc_rule(
		"STU-002",
		"Student Lifecycle",
		"Student Inactive",
		"GUARDRAIL",
		"STOP",
		_condition("student.stage", "eq", "Disqualified"),
		feature="all",
		source_condition="student.status = Inactive",
		effect="BLOCK_AI",
		applies_to="Decision-grade AI / NBA",
	),
	_doc_rule(
		"STU-003",
		"Student Lifecycle",
		"Already Enrolled",
		"GUARDRAIL",
		"STOP",
		_condition("application.status", "eq", "Enrolled"),
		source_condition="student.stage = Enrolled",
		effect="BLOCK_CONVERSION_NBA",
		applies_to="NBA",
	),
	_doc_rule(
		"STU-004",
		"Student Lifecycle",
		"Invalid / Unknown Stage",
		"PREREQUISITE",
		"WAIT",
		_condition("student.stage", "eq", "__UNKNOWN__"),
		feature="all",
		enabled=False,
		source_condition="student.lifecycle_stage is UNKNOWN/invalid",
		effect="REQUEST_DATA",
		applies_to="Decision-grade AI",
	),
	_doc_rule(
		"STU-005",
		"Student Lifecycle",
		"Terminal Lifecycle",
		"GUARDRAIL",
		"STOP",
		_condition("application.status", "in", ["Lost", "Withdrawn", "Cancelled"]),
		enabled=True,
		source_condition="student.lifecycle_stage in [Lost, Withdrawn, Cancelled]",
		effect="BLOCK_SALES_NBA",
		applies_to="NBA",
	),
	_doc_rule(
		"STU-006",
		"Student Lifecycle",
		"Conflicting Identity",
		"PREREQUISITE",
		"WAIT",
		enabled=False,
		source_condition="identity state = CONFLICTING",
		effect="REQUIRE_IDENTITY_RESOLUTION",
		applies_to="Decision-grade AI",
	),
	# APPLICATION_ADMISSION (10)
	_doc_rule(
		"APP-001",
		"Application Admission",
		"No Live Application",
		"ELIGIBILITY",
		"STOP",
		_condition("application.exists", "is_false"),
		feature="all",
		target_actions=("REMIND_COMPLETE_APPLICATION",),
		source_condition="no live application exists",
		effect="BLOCK_APPLICATION_FOLLOWUP",
		applies_to="Application-specific candidate action",
	),
	_doc_rule(
		"APP-002",
		"Application Admission",
		"Application Incomplete",
		"ELIGIBILITY",
		"PASS",
		_condition("application.status", "in", ["Draft", "Incomplete"]),
		target_actions=("REMIND_COMPLETE_APPLICATION",),
		source_condition="application.status in [Draft, Incomplete]",
		effect="ALLOW_COMPLETE_APPLICATION",
		applies_to="NBA / Application",
	),
	_doc_rule(
		"APP-003",
		"Application Admission",
		"Missing Required Documents",
		"ELIGIBILITY",
		"PASS",
		_condition("application.missing_count", "gt", 0),
		target_actions=("REQUEST_MISSING_DOCUMENT",),
		source_condition="required_documents_missing = true",
		effect="ALLOW_REQUEST_MISSING_DOCUMENT",
		applies_to="NBA / Application",
	),
	_doc_rule(
		"APP-004",
		"Application Admission",
		"Application Submitted",
		"GUARDRAIL",
		"STOP",
		_condition("application.status", "eq", "Submitted"),
		target_actions=("REMIND_APPLICATION",),
		source_condition="application.status = Submitted",
		effect="BLOCK_APPLY_ACTION",
		applies_to="Apply / Submit candidate",
	),
	_doc_rule(
		"APP-005",
		"Application Admission",
		"Application Deadline Passed",
		"GUARDRAIL",
		"STOP",
		_condition("application.days_to_deadline", "lt", 0),
		target_actions=("REMIND_APPLICATION", "REMIND_APPLICATION_DEADLINE"),
		source_condition="application.deadline < system.now",
		effect="BLOCK_DEADLINE_ACTION",
		applies_to="Application deadline-bound actions",
	),
	_doc_rule(
		"APP-006",
		"Application Admission",
		"Application Deadline Near",
		"MODIFIER",
		"PASS",
		_all(
			_condition("application.days_to_deadline", "gte", 0),
			_condition("application.days_to_deadline", "lte", 7),
		),
		target_actions=("REMIND_APPLICATION_DEADLINE",),
		source_condition="0 <= application.deadline_days <= 7",
		effect="INCREASE_PRIORITY",
		applies_to="NBA",
	),
	_doc_rule(
		"APP-007",
		"Application Admission",
		"Conflicting Application State",
		"PREREQUISITE",
		"WAIT",
		_condition("application.status", "eq", "Conflicting"),
		enabled=False,
		source_condition="application state = CONFLICTING",
		effect="REQUEST_DATA",
		applies_to="Decision-grade AI / NBA",
	),
	_doc_rule(
		"APP-008",
		"Application Admission",
		"Enrollment Deadline Passed",
		"GUARDRAIL",
		"STOP",
		_condition("application.days_to_deadline", "lt", 0),
		target_actions=("REMIND_ENROLLMENT_DEADLINE",),
		source_condition="enrollment.deadline < system.now",
		effect="BLOCK_ENROLLMENT_ACTION",
		applies_to="Enrollment actions",
	),
	_doc_rule(
		"APP-009",
		"Application Admission",
		"Enrollment Deadline Near",
		"MODIFIER",
		"PASS",
		_all(
			_condition("application.days_to_deadline", "gte", 0),
			_condition("application.days_to_deadline", "lte", 7),
		),
		target_actions=("REMIND_ENROLLMENT_DEADLINE",),
		source_condition="0 <= enrollment.deadline_days <= 7",
		effect="INCREASE_PRIORITY",
		applies_to="NBA",
	),
	_doc_rule(
		"APP-010",
		"Application Admission",
		"Required Documents Complete",
		"GUARDRAIL",
		"STOP",
		_all(
			_condition("application.missing_count", "eq", 0),
			_condition("application.completeness", "eq", "COMPLETE"),
		),
		target_actions=("REQUEST_MISSING_DOCUMENT",),
		source_condition="required_documents_missing = false AND document_set_complete = true",
		effect="BLOCK_REQUEST_DOCUMENT",
		applies_to="REQUEST_MISSING_DOCUMENT",
	),
	# PROGRAM_OFFERING (6) — source facts are not in the closed CRM fact registry yet.
	_doc_rule(
		"PRG-001",
		"Program Offering",
		"Offering Active",
		"ELIGIBILITY",
		"PASS",
		enabled=False,
		source_condition="offering.status = Active AND effective window valid",
		effect="ALLOW_PROGRAM_ACTION",
		applies_to="Program / NBA",
	),
	_doc_rule(
		"PRG-002",
		"Program Offering",
		"Offering Inactive / Expired",
		"GUARDRAIL",
		"STOP",
		enabled=False,
		source_condition="offering inactive OR effective window expired",
		effect="BLOCK_PROGRAM",
		applies_to="Program / NBA",
	),
	_doc_rule(
		"PRG-003",
		"Program Offering",
		"Offering Scope Mismatch",
		"GUARDRAIL",
		"STOP",
		enabled=False,
		source_condition="year/campus/major/admission_method does not match requested offering",
		effect="BLOCK_PROGRAM",
		applies_to="Program / NBA",
	),
	_doc_rule(
		"PRG-004",
		"Program Offering",
		"Program Eligible",
		"ELIGIBILITY",
		"PASS",
		enabled=False,
		source_condition="deterministic program requirements satisfied",
		effect="ALLOW_PROGRAM",
		applies_to="Program / NBA",
	),
	_doc_rule(
		"PRG-005",
		"Program Offering",
		"Program Not Eligible",
		"GUARDRAIL",
		"STOP",
		enabled=False,
		source_condition="deterministic program requirements not satisfied",
		effect="BLOCK_PROGRAM",
		applies_to="Program / NBA",
	),
	_doc_rule(
		"PRG-006",
		"Program Offering",
		"Program Eligibility Data Missing",
		"PREREQUISITE",
		"WAIT",
		enabled=False,
		source_condition="required eligibility facts unavailable",
		effect="REQUEST_DATA",
		applies_to="Program / NBA",
	),
	# COMMUNICATION (7)
	_doc_rule(
		"COM-001",
		"Communication",
		"Opt-out",
		"GUARDRAIL",
		"STOP",
		_condition("student.is_opted_out", "is_true"),
		feature="all",
		target_actions=("CALL", "SEND_EMAIL", "SEND_ZALO"),
		source_condition="student.is_opted_out = true",
		effect="BLOCK_CONTACT",
		applies_to="Call / Email / Message",
	),
	_doc_rule(
		"COM-002",
		"Communication",
		"Consent Unknown",
		"PREREQUISITE",
		"WAIT",
		_condition("contact.consent_state", "in", ["UNKNOWN", "UNAVAILABLE"]),
		target_actions=("CALL", "SEND_EMAIL", "SEND_ZALO"),
		source_condition="outbound consent state in [UNKNOWN, UNAVAILABLE]",
		effect="REQUIRE_CONSENT_STATE",
		applies_to="Outbound communication",
	),
	_doc_rule(
		"COM-003",
		"Communication",
		"Invalid Phone",
		"GUARDRAIL",
		"STOP",
		_condition("contact.recipient_bound", "is_false"),
		target_actions=("CALL",),
		source_condition="phone invalid/unavailable",
		effect="BLOCK_CALL",
		applies_to="Call",
	),
	_doc_rule(
		"COM-004",
		"Communication",
		"Invalid Email / Bounced",
		"GUARDRAIL",
		"STOP",
		_condition("contact.email_bounced", "is_true"),
		target_actions=("SEND_EMAIL",),
		source_condition="email invalid OR email_bounced = true",
		effect="BLOCK_EMAIL",
		applies_to="Email",
	),
	_doc_rule(
		"COM-005",
		"Communication",
		"Channel Not Allowed",
		"GUARDRAIL",
		"STOP",
		_condition("requested_action.effective", "is_false"),
		source_condition="requested channel disabled/not allowed",
		effect="BLOCK_CHANNEL",
		applies_to="Communication",
	),
	_doc_rule(
		"COM-006",
		"Communication",
		"Preferred Channel",
		"MODIFIER",
		"PASS",
		enabled=False,
		source_condition="student.preferred_channel is KNOWN and eligible",
		effect="PREFER_CHANNEL",
		applies_to="Communication / NBA",
	),
	_doc_rule(
		"COM-007",
		"Communication",
		"Repeated No Response",
		"MODIFIER",
		"PASS",
		_all(
			_condition("activity.consecutive_failures", "gte", 3),
			_condition("requested_action.alternate_message_available", "is_true"),
		),
		target_actions=("SEND_ZALO",),
		source_condition="no_response_attempts >= 3 AND alternate eligible channel exists",
		effect="PREFER_ALTERNATE_CHANNEL",
		applies_to="NBA / Communication",
	),
	# TIMING_FREQUENCY (6)
	_doc_rule(
		"TIM-001",
		"Timing / Frequency",
		"Contact Cooldown",
		"PREREQUISITE",
		"WAIT",
		_condition("activity.days_since_last_contact", "lt", 1),
		target_actions=("CALL", "SEND_ZALO", "SEND_EMAIL"),
		source_condition="system.now - last_contact_at < configured cooldown",
		effect="DELAY_ACTION",
		applies_to="Outbound communication",
	),
	_doc_rule(
		"TIM-002",
		"Timing / Frequency",
		"Daily Contact Limit",
		"PREREQUISITE",
		"WAIT",
		enabled=False,
		source_condition="contact_count_day >= daily_limit",
		effect="DELAY_ACTION",
		applies_to="Outbound communication",
	),
	_doc_rule(
		"TIM-003",
		"Timing / Frequency",
		"Weekly Contact Limit",
		"PREREQUISITE",
		"WAIT",
		enabled=False,
		source_condition="contact_count_7d >= weekly_limit",
		effect="DELAY_ACTION",
		applies_to="Outbound communication",
	),
	_doc_rule(
		"TIM-004",
		"Timing / Frequency",
		"Quiet Hours",
		"PREREQUISITE",
		"WAIT",
		_condition("requested_action.time_allowed", "is_false"),
		target_actions=("CALL", "SEND_ZALO"),
		source_condition="system.now outside allowed contact hours",
		effect="DELAY_ACTION",
		applies_to="Call / Message",
	),
	_doc_rule(
		"TIM-005",
		"Timing / Frequency",
		"Weekend Restriction",
		"PREREQUISITE",
		"WAIT",
		enabled=False,
		source_condition="weekend=true AND weekend_contact_restricted=true",
		effect="DELAY_ACTION",
		applies_to="Outbound communication",
	),
	_doc_rule(
		"TIM-006",
		"Timing / Frequency",
		"Recent Equivalent Interaction",
		"GUARDRAIL",
		"STOP",
		_condition("requested_action.duplicate_active", "is_true"),
		source_condition="equivalent recent interaction/recommendation exists inside dedupe window",
		effect="BLOCK_DUPLICATE_ACTION",
		applies_to="NBA / Communication",
	),
	# SCHOLARSHIP_FINANCE (7)
	_doc_rule(
		"SCH-001",
		"Scholarship / Finance",
		"Scholarship Policy Active",
		"ELIGIBILITY",
		"PASS",
		enabled=False,
		source_condition="scholarship policy active AND effective window valid",
		effect="ALLOW_SCHOLARSHIP_ACTION",
		applies_to="Scholarship / NBA",
	),
	_doc_rule(
		"SCH-002",
		"Scholarship / Finance",
		"Scholarship Expired / Inactive",
		"GUARDRAIL",
		"STOP",
		enabled=False,
		source_condition="scholarship inactive OR deadline/effective window expired",
		effect="BLOCK_SCHOLARSHIP_ACTION",
		applies_to="Scholarship / NBA",
	),
	_doc_rule(
		"SCH-003",
		"Scholarship / Finance",
		"Scholarship Eligible",
		"ELIGIBILITY",
		"PASS",
		enabled=False,
		source_condition="deterministic scholarship criteria satisfied",
		effect="ALLOW_SCHOLARSHIP_ACTION",
		applies_to="Scholarship / NBA",
	),
	_doc_rule(
		"SCH-004",
		"Scholarship / Finance",
		"Scholarship Not Eligible",
		"GUARDRAIL",
		"STOP",
		enabled=False,
		source_condition="deterministic scholarship criteria not satisfied",
		effect="BLOCK_SCHOLARSHIP_ACTION",
		applies_to="Scholarship / NBA",
	),
	_doc_rule(
		"SCH-005",
		"Scholarship / Finance",
		"Scholarship Eligibility Facts Missing",
		"PREREQUISITE",
		"WAIT",
		enabled=False,
		source_condition="required scholarship facts unavailable",
		effect="REQUEST_DATA",
		applies_to="Scholarship / NBA",
	),
	_doc_rule(
		"SCH-006",
		"Scholarship / Finance",
		"Tuition Concern",
		"ELIGIBILITY",
		"PASS",
		_all(
			_condition("assessment.primary_barrier", "eq", "TUITION"),
			_condition("requested_action.effective", "is_true"),
		),
		target_actions=("ADVISE_TUITION",),
		source_condition="committed concern = Tuition AND tuition consultation action enabled",
		effect="ALLOW_TUITION_CONSULTATION",
		applies_to="NBA",
	),
	_doc_rule(
		"SCH-007",
		"Scholarship / Finance",
		"Scholarship Concern",
		"ELIGIBILITY",
		"PASS",
		_all(
			_condition("assessment.primary_barrier", "eq", "SCHOLARSHIP"),
			_condition("requested_action.effective", "is_true"),
		),
		target_actions=("ADVISE_SCHOLARSHIP",),
		source_condition="committed concern = Scholarship AND scholarship active/eligible",
		effect="ALLOW_SCHOLARSHIP_CONSULTATION",
		applies_to="NBA",
	),
	# ACTION_ELIGIBILITY (9)
	_doc_rule(
		"ACT-001",
		"Action Eligibility",
		"Action Exists and Enabled",
		"ELIGIBILITY",
		"PASS",
		_condition("requested_action.enabled", "is_true"),
		source_condition="action exists AND enabled",
		effect="ALLOW_ACTION",
		applies_to="NBA candidate action",
	),
	_doc_rule(
		"ACT-002",
		"Action Eligibility",
		"Action Missing / Disabled",
		"GUARDRAIL",
		"STOP",
		_condition("requested_action.enabled", "is_false"),
		source_condition="action missing OR disabled",
		effect="BLOCK_ACTION",
		applies_to="NBA candidate action",
	),
	_doc_rule(
		"ACT-003",
		"Action Eligibility",
		"Action Invalid for Stage",
		"GUARDRAIL",
		"STOP",
		_condition("requested_action.academic_eligible", "is_false"),
		source_condition="action not valid for current lifecycle stage",
		effect="BLOCK_ACTION",
		applies_to="NBA candidate action",
	),
	_doc_rule(
		"ACT-004",
		"Action Eligibility",
		"Outside Frappe-authorized Candidate Set",
		"GUARDRAIL",
		"STOP",
		_condition("requested_action.in_candidate_set", "is_false"),
		source_condition="candidate not present in Frappe-authorized action set",
		effect="BLOCK_ACTION",
		applies_to="NBA",
	),
	_doc_rule(
		"ACT-005",
		"Action Eligibility",
		"Duplicate Active Recommendation",
		"GUARDRAIL",
		"STOP",
		_condition("requested_action.duplicate_active", "is_true"),
		source_condition="same recommendation already active",
		effect="BLOCK_DUPLICATE_NBA",
		applies_to="NBA",
	),
	_doc_rule(
		"ACT-006",
		"Action Eligibility",
		"Action Recently Completed",
		"GUARDRAIL",
		"STOP",
		_condition("requested_action.recently_completed", "is_true"),
		source_condition="same action completed inside configured dedupe period",
		effect="BLOCK_DUPLICATE_ACTION",
		applies_to="NBA",
	),
	_doc_rule(
		"ACT-007",
		"Action Eligibility",
		"Event Unavailable / Full",
		"GUARDRAIL",
		"STOP",
		_condition("requested_action.effective", "is_false"),
		source_condition="event unavailable OR capacity reached",
		effect="BLOCK_ACTION",
		applies_to="Campus Visit / Event",
	),
	_doc_rule(
		"ACT-008",
		"Action Eligibility",
		"Action Prerequisite Missing",
		"PREREQUISITE",
		"WAIT",
		_condition("contact.recipient_bound", "is_false"),
		source_condition="required action prerequisite missing",
		effect="REQUEST_DATA",
		applies_to="NBA candidate action",
	),
	_doc_rule(
		"ACT-009",
		"Action Eligibility",
		"Human Approval Required",
		"MODIFIER",
		"PASS",
		_condition("requested_action.requires_approval", "is_true"),
		source_condition="action metadata requires human approval",
		effect="REQUIRE_HUMAN_REVIEW",
		applies_to="Recommendation",
	),
	# AI_ADMISSION (11) — model/source revision facts are owned by the AI runtime.
	_doc_rule(
		"AIA-001",
		"AI Admission",
		"Intent — No New Content",
		"GUARDRAIL",
		"STOP",
		enabled=False,
		source_condition="interaction.has_new_content = false",
		effect="REUSE_OR_SKIP",
		applies_to="Intent",
	),
	_doc_rule(
		"AIA-002",
		"AI Admission",
		"Intent — Source Already Analyzed",
		"GUARDRAIL",
		"STOP",
		enabled=False,
		source_condition="interaction.source_revision = intent.source_revision",
		effect="REUSE_EXISTING_RESULT",
		applies_to="Intent",
	),
	_doc_rule(
		"AIA-003",
		"AI Admission",
		"Intent — Minimum Evidence Missing",
		"PREREQUISITE",
		"WAIT",
		enabled=False,
		source_condition="minimum intent evidence unavailable",
		effect="WAIT_FOR_EVIDENCE",
		applies_to="Intent",
	),
	_doc_rule(
		"AIA-004",
		"AI Admission",
		"Student 360 — Minimum Profile Missing",
		"PREREQUISITE",
		"WAIT",
		enabled=False,
		source_condition="required 360 profile facts unavailable",
		effect="WAIT_FOR_DATA",
		applies_to="Student 360",
	),
	_doc_rule(
		"AIA-005",
		"AI Admission",
		"Student 360 — Fresh and Unchanged",
		"GUARDRAIL",
		"STOP",
		enabled=False,
		source_condition="existing 360 fresh AND source_revision unchanged",
		effect="REUSE_EXISTING_RESULT",
		applies_to="Student 360",
	),
	_doc_rule(
		"AIA-006",
		"AI Admission",
		"Student 360 — Meaningful Source Change",
		"ELIGIBILITY",
		"PASS",
		enabled=False,
		source_condition="meaningful source revision changed AND minimum profile available",
		effect="ALLOW_ANALYSIS",
		applies_to="Student 360",
	),
	_doc_rule(
		"AIA-007",
		"AI Admission",
		"School 360 — Minimum Data Missing",
		"PREREQUISITE",
		"WAIT",
		enabled=False,
		source_condition="required school facts unavailable",
		effect="WAIT_FOR_DATA",
		applies_to="School 360",
	),
	_doc_rule(
		"AIA-008",
		"AI Admission",
		"School 360 — Fresh and Unchanged",
		"GUARDRAIL",
		"STOP",
		enabled=False,
		source_condition="existing School 360 fresh AND source_revision unchanged",
		effect="REUSE_EXISTING_RESULT",
		applies_to="School 360",
	),
	_doc_rule(
		"AIA-009",
		"AI Admission",
		"Score-dependent AI — Score Unavailable",
		"PREREQUISITE",
		"WAIT",
		enabled=False,
		source_condition="required committed score missing",
		effect="WAIT_FOR_SCORE",
		applies_to="Score-dependent AI",
	),
	_doc_rule(
		"AIA-010",
		"AI Admission",
		"Score-dependent AI — Score Stale / Source Mismatch",
		"PREREQUISITE",
		"WAIT",
		_condition("score.freshness", "eq", "STALE"),
		enabled=False,
		source_condition="score stale OR score.source_revision incompatible",
		effect="WAIT_FOR_SCORE",
		applies_to="Score-dependent AI",
	),
	_doc_rule(
		"AIA-011",
		"AI Admission",
		"Copilot — Read-only / Cached Path",
		"GUARDRAIL",
		"STOP",
		enabled=False,
		source_condition="request can be answered from authorized read-only/cached projection",
		effect="REUSE_OR_READ",
		applies_to="Copilot deep analysis",
	),
	# AI_RELIABILITY (9) — protected AI reliability signals are not Frappe facts.
	_doc_rule(
		"AIR-001",
		"AI Reliability",
		"Độ tin cậy Intent thấp",
		"MODIFIER",
		"PASS",
		enabled=False,
		source_condition="committed intent confidence < configured threshold",
		effect="IGNORE_INTENT",
		applies_to="NBA / AI",
	),
	_doc_rule(
		"AIR-002",
		"AI Reliability",
		"Độ tin cậy dự đoán thấp",
		"PREREQUISITE",
		"WAIT",
		enabled=False,
		source_condition="prediction confidence < configured threshold",
		effect="REQUIRE_HUMAN_REVIEW",
		applies_to="NBA / Predictive input",
	),
	_doc_rule(
		"AIR-003",
		"AI Reliability",
		"Kết quả dự đoán đã cũ",
		"PREREQUISITE",
		"WAIT",
		enabled=False,
		source_condition="prediction age > configured freshness threshold",
		effect="REFRESH_PREDICTION",
		applies_to="Predictive input",
	),
	_doc_rule(
		"AIR-004",
		"AI Reliability",
		"Thiếu dữ liệu đầu vào bắt buộc cho model",
		"PREREQUISITE",
		"WAIT",
		enabled=False,
		source_condition="required model features unavailable",
		effect="BLOCK_PREDICTION",
		applies_to="Model invocation",
	),
	_doc_rule(
		"AIR-005",
		"AI Reliability",
		"Model không khả dụng",
		"GUARDRAIL",
		"STOP",
		enabled=False,
		source_condition="model unavailable",
		effect="FALLBACK_RULES",
		applies_to="Model invocation",
	),
	_doc_rule(
		"AIR-006",
		"AI Reliability",
		"LLM không khả dụng",
		"GUARDRAIL",
		"STOP",
		enabled=False,
		source_condition="LLM unavailable",
		effect="FALLBACK_TEMPLATE",
		applies_to="LLM generation",
	),
	_doc_rule(
		"AIR-007",
		"AI Reliability",
		"Tín hiệu AI mâu thuẫn",
		"PREREQUISITE",
		"WAIT",
		enabled=False,
		source_condition="decision-grade AI signals conflict materially",
		effect="REQUIRE_HUMAN_REVIEW",
		applies_to="NBA",
	),
	_doc_rule(
		"AIR-008",
		"AI Reliability",
		"Phiên bản model không hợp lệ",
		"GUARDRAIL",
		"STOP",
		enabled=False,
		source_condition="prediction.model_version not active/accepted",
		effect="BLOCK_PREDICTION",
		applies_to="AI / NBA",
	),
	_doc_rule(
		"AIR-009",
		"AI Reliability",
		"Thiếu nguồn gốc kết quả AI",
		"PREREQUISITE",
		"WAIT",
		enabled=False,
		source_condition="decision-grade AI output lacks source/model revision provenance",
		effect="REJECT_AI_SIGNAL",
		applies_to="NBA / AI",
	),
	# NBA_DECISION (7). RESOLUTION rules use the runtime DIRECT/ESCALATE outcomes.
	_doc_rule(
		"NBR-001",
		"NBA Decision",
		"Direct — Request Missing Documents",
		"RESOLUTION",
		"DIRECT",
		_all(
			_condition("application.status", "in", ["Draft", "Incomplete"]),
			_condition("application.missing_count", "gt", 0),
			_condition("application.days_to_deadline", "gte", 0),
		),
		target_actions=("REQUEST_MISSING_DOCUMENT",),
		source_condition="application Draft/Incomplete AND required docs missing AND deadline valid",
		effect="REQUEST_MISSING_DOCUMENT",
		applies_to="NBA Resolver",
	),
	_doc_rule(
		"NBR-002",
		"NBA Decision",
		"Direct — Complete Application",
		"RESOLUTION",
		"DIRECT",
		_all(
			_condition("application.status", "in", ["Draft", "Incomplete"]),
			_condition("application.missing_count", "eq", 0),
			_condition("requested_action.effective", "is_true"),
		),
		target_actions=("REMIND_COMPLETE_APPLICATION",),
		source_condition="application Draft/Incomplete AND documents complete AND completion action eligible",
		effect="COMPLETE_APPLICATION",
		applies_to="NBA Resolver",
	),
	_doc_rule(
		"NBR-003",
		"NBA Decision",
		"Direct — Change Channel After Repeated No Response",
		"RESOLUTION",
		"DIRECT",
		_all(
			_condition("activity.consecutive_failures", "gte", 3),
			_condition("requested_action.alternate_message_available", "is_true"),
		),
		target_actions=("SEND_ZALO",),
		source_condition="no_response_attempts >= 3 AND alternate channel eligible",
		effect="CHANGE_CHANNEL",
		applies_to="NBA Resolver",
	),
	_doc_rule(
		"NBR-004",
		"NBA Decision",
		"Direct — Scholarship Consultation",
		"RESOLUTION",
		"DIRECT",
		_all(
			_condition("assessment.primary_barrier", "eq", "SCHOLARSHIP"),
			_condition("requested_action.effective", "is_true"),
		),
		target_actions=("ADVISE_SCHOLARSHIP",),
		source_condition="scholarship concern AND scholarship policy active AND student eligible",
		effect="SCHOLARSHIP_CONSULTATION",
		applies_to="NBA Resolver",
	),
	_doc_rule(
		"NBR-005",
		"NBA Decision",
		"Direct — Tuition Consultation",
		"RESOLUTION",
		"DIRECT",
		_all(
			_condition("assessment.primary_barrier", "eq", "TUITION"),
			_condition("requested_action.effective", "is_true"),
		),
		target_actions=("ADVISE_TUITION",),
		source_condition="tuition concern AND tuition consultation action eligible",
		effect="TUITION_CONSULTATION",
		applies_to="NBA Resolver",
	),
	_doc_rule(
		"NBR-006",
		"NBA Decision",
		"Escalate Competing Actions",
		"RESOLUTION",
		"ESCALATE",
		enabled=False,
		source_condition="multiple eligible actions AND no explicit resolution rule wins",
		effect="ESCALATE",
		applies_to="NBA Resolver",
	),
	_doc_rule(
		"NBR-007",
		"NBA Decision",
		"Escalate Conflicting Resolutions",
		"RESOLUTION",
		"ESCALATE",
		enabled=False,
		source_condition="two incompatible RESOLUTION rules match with same effective precedence",
		effect="ESCALATE",
		applies_to="NBA Resolver",
	),
	# BUSINESS_POLICY (5)
	_doc_rule(
		"BIZ-001",
		"Business Policy",
		"Campaign Active",
		"ELIGIBILITY",
		"PASS",
		enabled=False,
		source_condition="campaign.status = Active AND effective window valid",
		effect="ALLOW_CAMPAIGN_ACTION",
		applies_to="Campaign / NBA",
	),
	_doc_rule(
		"BIZ-002",
		"Business Policy",
		"Campaign Expired",
		"GUARDRAIL",
		"STOP",
		enabled=False,
		source_condition="campaign.end_date < system.now OR status=Expired",
		effect="BLOCK_CAMPAIGN",
		applies_to="Campaign / NBA",
	),
	_doc_rule(
		"BIZ-003",
		"Business Policy",
		"Priority Region",
		"MODIFIER",
		"PASS",
		enabled=False,
		source_condition="student.region in configured priority_regions",
		effect="INCREASE_PRIORITY",
		applies_to="NBA",
	),
	_doc_rule(
		"BIZ-004",
		"Business Policy",
		"Strategic Program",
		"MODIFIER",
		"PASS",
		enabled=False,
		source_condition="program in configured strategic_programs",
		effect="INCREASE_PRIORITY",
		applies_to="NBA",
	),
	_doc_rule(
		"BIZ-005",
		"Business Policy",
		"Active Scholarship Campaign",
		"MODIFIER",
		"PASS",
		enabled=False,
		source_condition="scholarship campaign active",
		effect="INCREASE_SCHOLARSHIP_PRIORITY",
		applies_to="NBA",
	),
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
		"rules": _rules_for_groups("Student Lifecycle", "Application Admission"),
	},
	{
		"version_id": "FAIP-V5",
		"version_name": "FAIP Rule Engine Action 2026",
		"description": "Bộ Rule kiểm soát các Action được phép thực hiện.",
		"status": "draft",
		"rules": _rules_for_groups("Action Eligibility"),
	},
)


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
	if len(rows) == len(RULES) and "Explainability" not in seen:
		groups.append(
			{
				"code": RULE_GROUP_CODES["Explainability"],
				"label": "Explainability",
				"enabled": True,
				"description": "Protected explainability policies from the FAIP CRM catalog.",
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
		"protected_policy_count": len(PROTECTED_POLICIES),
		"catalog_items_total": len(RULES) + len(PROTECTED_POLICIES),
	}


def seed_and_activate_catalog() -> dict:
	"""Seed the complete MVP v3 snapshot and publish it atomically."""
	seed_result = seed_catalog()
	if seed_result.get("status") != "ok":
		return seed_result

	from crm.api.rule_engine import update_rule_version

	version = frappe.get_doc("CRM Rule Version", seed_result["version"])
	if str(version.status or "draft").lower() == "draft":
		update_rule_version(
			name=version.name,
			expected_revision=int(version.revision or 0),
			status="testing",
			change_note="Validate the complete FAIP MVP v3 rule catalog.",
		)
		version.reload()
	settings = frappe.db.get_singles_dict("CRM Rule Settings", cast=True)
	activated = update_rule_version(
		name=version.name,
		expected_revision=int(version.revision or 0),
		expected_settings_revision=int((settings or {}).get("pointer_revision") or 0),
		status="active",
		change_note="Activate the complete FAIP MVP v3 rule catalog.",
	)
	return {
		**seed_result,
		"status": "activated",
		"version": activated["name"],
		"version_status": activated["status"],
		"ruleset_digest": activated["ruleset_digest"],
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
