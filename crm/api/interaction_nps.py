"""Frappe-owned settlement and read APIs for call-quality NPS points."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

import frappe

from crm.fcrm.interaction_analysis import _safe_intelligence_text

_DIMENSIONS = ("satisfaction", "resolution", "friction", "complaint")
_CONFIDENCES = {"low", "medium", "high"}
_STATUSES = {"scored", "abstained"}
_QUALITY_ACTOR_ROLES = {"student", "parent"}
_CONTRACT_VERSION = "crm-call-quality-v1"
_FULL_READ_ROLES = {"Administrator", "System Manager", "CRM Manager", "Lead Sale", "Admissions Director"}
_SALE_ROLES = {"Sale", "CTV Sale"}


def _service_only() -> None:
	service_user = frappe.conf.get("crm_agents_service_user")
	if not service_user or frappe.session.user != service_user:
		frappe.throw("This command is restricted to the CRM-Agents capability.", frappe.PermissionError)


def _parse_json(value: Any, fieldname: str) -> Any:
	if isinstance(value, str):
		try:
			return json.loads(value)
		except (TypeError, ValueError):
			frappe.throw(f"{fieldname} must be valid JSON.", frappe.ValidationError)
	return value


def _required_text(value: Any, fieldname: str, maximum: int = 140) -> str:
	if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
		frappe.throw(f"{fieldname} is invalid or exceeds its bound.", frappe.ValidationError)
	return value.strip()


def _optional_text(value: Any, fieldname: str, maximum: int) -> str:
	if value in (None, ""):
		return ""
	return _required_text(value, fieldname, maximum)


def _canonical_digest(value: object) -> str:
	return hashlib.sha256(
		json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
	).hexdigest()


def _validate_digest(value: Any, fieldname: str) -> str:
	if (
		not isinstance(value, str)
		or len(value) != 64
		or value != value.lower()
		or any(character not in "0123456789abcdef" for character in value)
	):
		frappe.throw(f"{fieldname} must be a lowercase SHA-256 digest.", frappe.ValidationError)
	return value


def _validate_ref(ref: Any, fieldname: str) -> dict[str, str]:
	if not isinstance(ref, Mapping) or set(ref) != {"doctype", "name", "actor_role"}:
		frappe.throw(f"{fieldname} has an unsupported shape.", frappe.ValidationError)
	if ref.get("doctype") != "CRM Interaction Evidence" or ref.get("actor_role") not in _QUALITY_ACTOR_ROLES:
		frappe.throw(
			f"{fieldname} must reference student or parent Interaction Evidence.",
			frappe.PermissionError,
		)
	return {
		"doctype": _required_text(ref.get("doctype"), f"{fieldname}.doctype", 80),
		"name": _required_text(ref.get("name"), f"{fieldname}.name", 140),
		"actor_role": ref["actor_role"],
	}


def _validate_dimensions(value: Any) -> dict[str, dict[str, Any]]:
	if not isinstance(value, Mapping) or set(value) != set(_DIMENSIONS):
		frappe.throw("dimensions must contain exactly the four call-quality dimensions.", frappe.ValidationError)
	validated: dict[str, dict[str, Any]] = {}
	for dimension in _DIMENSIONS:
		item = value.get(dimension)
		if not isinstance(item, Mapping) or set(item) != {"score", "confidence", "evidence_refs", "explanation"}:
			frappe.throw(f"dimensions.{dimension} has an unsupported shape.", frappe.ValidationError)
		score = item.get("score")
		if not isinstance(score, int) or isinstance(score, bool) or not 1 <= score <= 10:
			frappe.throw(f"dimensions.{dimension}.score must be an integer from 1 to 10.", frappe.ValidationError)
		confidence = item.get("confidence")
		if confidence not in _CONFIDENCES:
			frappe.throw(f"dimensions.{dimension}.confidence is invalid.", frappe.ValidationError)
		refs = item.get("evidence_refs")
		if not isinstance(refs, list) or not 1 <= len(refs) <= 4:
			frappe.throw(f"dimensions.{dimension}.evidence_refs must contain 1 to 4 refs.", frappe.ValidationError)
		validated_refs = [
			_validate_ref(ref, f"dimensions.{dimension}.evidence_refs[{index}]")
			for index, ref in enumerate(refs)
		]
		if len({ref["name"] for ref in validated_refs}) != len(validated_refs):
			frappe.throw(f"dimensions.{dimension}.evidence_refs must be unique.", frappe.ValidationError)
		validated[dimension] = {
			"score": score,
			"confidence": confidence,
			"evidence_refs": validated_refs,
			"explanation": _safe_intelligence_text(
				item.get("explanation"), f"dimensions.{dimension}.explanation", 240
			),
		}
	return validated


def _assert_evidence_refs(
	interaction: str, student: str, source_revision: int, dimensions: Mapping[str, Mapping[str, Any]]
) -> None:
	for dimension, item in dimensions.items():
		for ref in item["evidence_refs"]:
			evidence = frappe.db.get_value(
				"CRM Interaction Evidence",
				ref["name"],
				["interaction", "student", "source_revision", "actor_role"],
				as_dict=True,
			)
			if not evidence:
				frappe.throw(f"Evidence for {dimension} is unavailable.", frappe.ValidationError)
			if (
				evidence.interaction != interaction
				or evidence.student != student
				or int(evidence.source_revision or 0) != source_revision
				or evidence.actor_role != ref["actor_role"]
			):
				frappe.throw(
					f"Evidence for {dimension} is outside the requested Interaction revision.",
					frappe.PermissionError,
				)


def _resolve_sale(agent_id: str | None) -> tuple[dict[str, str] | None, str | None]:
	"""Resolve one active CRM Staff from a Frappe user or Telephony mapping."""
	if not agent_id:
		return None, "agent_identity_missing"

	candidate_users: set[str] = set()
	staff_by_user = frappe.db.get_all(
		"CRM Staff", filters={"user": agent_id, "is_active": 1}, fields=["name", "user"]
	)
	candidate_users.update(row.user for row in staff_by_user if row.user)
	telephony_users = frappe.db.get_all(
		"Telephony Agent", filters={"worldfone_agent_id": agent_id}, fields=["user"]
	)
	candidate_users.update(row.user for row in telephony_users if row.user)

	if len(candidate_users) != 1:
		return None, "agent_identity_ambiguous" if len(candidate_users) > 1 else "agent_identity_unmapped"
	user = next(iter(candidate_users))
	staff = frappe.db.get_value(
		"CRM Staff", {"user": user, "is_active": 1}, ["name", "user"], as_dict=True
	)
	if not staff:
		return None, "agent_identity_unmapped"
	return {"name": staff.name, "user": staff.user}, None


def _assessment_payload(
	*,
	run_id: str,
	source_revision: int,
	source_digest: str,
	status: str,
	dimensions: Mapping[str, Any],
	confidence: str,
	explanation: str,
	terminal_reason: str,
	policy_revision: str,
	model_revision: str,
	contract_version: str,
) -> dict[str, Any]:
	return {
		"run_id": run_id,
		"source_revision": source_revision,
		"source_digest": source_digest,
		"status": status,
		"dimensions": dimensions,
		"confidence": confidence,
		"explanation": explanation,
		"terminal_reason": terminal_reason,
		"policy_revision": policy_revision,
		"model_revision": model_revision,
		"contract_version": contract_version,
	}


def _serialize_point(point: Any) -> dict[str, Any]:
	return {
		"name": point.name,
		"interaction": point.interaction,
		"analysis_run": point.analysis_run,
		"student": point.student,
		"sale": point.sale,
		"sale_user": point.sale_user,
		"agent_id": point.agent_id,
		"interaction_datetime": point.interaction_datetime,
		"source_revision": int(point.source_revision or 0),
		"source_digest": point.source_digest,
		"status": point.status,
		"terminal_reason": point.terminal_reason,
		"satisfaction_score": point.satisfaction_score,
		"resolution_score": point.resolution_score,
		"friction_score": point.friction_score,
		"complaint_score": point.complaint_score,
		"total_score": point.total_score,
		"normalized_score": point.normalized_score,
		"confidence": point.confidence,
		"evidence_refs": (
			frappe.parse_json(point.evidence_refs)
			if isinstance(point.evidence_refs, str)
			else point.evidence_refs
		),
		"explanation": point.explanation,
		"policy_revision": point.policy_revision,
		"model_revision": point.model_revision,
		"contract_version": point.contract_version,
		"supersedes": point.supersedes,
		"superseded_by": point.superseded_by,
	}


@frappe.whitelist(methods=["POST"])
def settle_interaction_nps_point(
	run_id: str,
	expected_source_revision: int,
	expected_source_digest: str,
	assessment_digest: str,
	status: str,
	dimensions=None,
	confidence: str | None = None,
	explanation: str | None = None,
	terminal_reason: str | None = None,
	policy_revision: str | None = None,
	model_revision: str | None = None,
	contract_version: str = _CONTRACT_VERSION,
) -> dict[str, Any]:
	"""Persist one idempotent NPS assessment from the AI service."""
	_service_only()
	run_id = _required_text(run_id, "run_id")
	if (
		not isinstance(expected_source_revision, int)
		or isinstance(expected_source_revision, bool)
		or expected_source_revision < 1
	):
		frappe.throw("Expected source revision is invalid.", frappe.ValidationError)
	expected_source_digest = _validate_digest(expected_source_digest, "expected_source_digest")
	assessment_digest = _validate_digest(assessment_digest, "assessment_digest")
	if status not in _STATUSES:
		frappe.throw("NPS assessment status is invalid.", frappe.ValidationError)
	if contract_version != _CONTRACT_VERSION:
		frappe.throw("NPS assessment contract version is unsupported.", frappe.ValidationError)
	policy_revision = _required_text(policy_revision, "policy_revision")
	model_revision = _required_text(model_revision, "model_revision")
	confidence = confidence or "low"
	if confidence not in _CONFIDENCES:
		frappe.throw("NPS assessment confidence is invalid.", frappe.ValidationError)
	dimensions = _parse_json(dimensions, "dimensions")
	validated_dimensions = _validate_dimensions(dimensions) if status == "scored" else {}
	if status == "scored" and confidence == "low":
		frappe.throw("A scored NPS assessment cannot have low confidence.", frappe.ValidationError)
	if status == "scored" and any(
		item["confidence"] == "low" for item in validated_dimensions.values()
	):
		frappe.throw("A scored NPS dimension cannot have low confidence.", frappe.ValidationError)
	if status == "abstained" and dimensions not in (None, {}, ""):
		frappe.throw("An abstained NPS assessment cannot carry scores.", frappe.ValidationError)
	explanation = _safe_intelligence_text(explanation or "", "explanation", 600) if explanation else ""
	terminal_reason = _optional_text(terminal_reason, "terminal_reason", 160)
	digest_payload = _assessment_payload(
		run_id=run_id,
		source_revision=expected_source_revision,
		source_digest=expected_source_digest,
		status=status,
		dimensions=validated_dimensions,
		confidence=confidence,
		explanation=explanation,
		terminal_reason=terminal_reason,
		policy_revision=policy_revision,
		model_revision=model_revision,
		contract_version=contract_version,
	)
	if _canonical_digest(digest_payload) != assessment_digest:
		frappe.throw("NPS assessment digest is invalid.", frappe.ValidationError)

	frappe.db.sql("SELECT name FROM `tabCRM Interaction Analysis Run` WHERE name=%s FOR UPDATE", (run_id,))
	run = frappe.db.get_value(
		"CRM Interaction Analysis Run", run_id, ["interaction", "source_revision", "source_digest"], as_dict=True
	)
	if not run:
		frappe.throw("Interaction analysis run is unavailable.", frappe.DoesNotExistError)
	if int(run.source_revision or 0) != expected_source_revision or run.source_digest != expected_source_digest:
		frappe.throw("Interaction analysis run is stale.", frappe.ValidationError)
	interaction = frappe.db.get_value(
		"CRM Interaction",
		run.interaction,
		["student", "agent_id", "channel", "interaction_datetime", "source_revision", "evidence_digest"],
		as_dict=True,
	)
	if not interaction or not interaction.student:
		frappe.throw("Interaction target is unavailable.", frappe.DoesNotExistError)
	if (
		int(interaction.source_revision or 0) != expected_source_revision
		or interaction.evidence_digest != expected_source_digest
	):
		frappe.throw("Interaction source revision is stale.", frappe.ValidationError)
	if interaction.channel != "phone":
		return {
			"point": None,
			"replayed": False,
			"status": "skipped",
			"terminal_reason": "nps_call_quality_requires_phone_interaction",
		}

	revision_point = frappe.db.get_value(
		"CRM NPS Point",
		{"interaction": run.interaction, "source_revision": expected_source_revision},
		["name", "source_digest"],
		as_dict=True,
	)
	if revision_point and revision_point.source_digest != expected_source_digest:
		frappe.throw("A different NPS source digest already exists for this revision.", frappe.ValidationError)

	assessment_key = _canonical_digest(
		{
			"interaction": run.interaction,
			"source_revision": expected_source_revision,
			"source_digest": expected_source_digest,
		}
	)
	existing = frappe.db.get_value(
		"CRM NPS Point", {"idempotency_key": assessment_key}, ["name", "assessment_digest"], as_dict=True
	)
	if existing:
		if existing.assessment_digest != assessment_digest:
			frappe.throw("NPS assessment conflicts with an existing settlement.", frappe.ValidationError)
		return {"point": existing.name, "replayed": True, "status": "replayed"}

	sale, mapping_reason = _resolve_sale(interaction.agent_id)
	effective_status = status
	effective_reason = terminal_reason
	if status == "scored" and not sale:
		effective_status = "abstained"
		effective_reason = mapping_reason or "agent_identity_unmapped"
	if effective_status == "abstained" and not effective_reason:
		effective_reason = "assessment_insufficient_evidence"
	if status == "scored":
		_assert_evidence_refs(run.interaction, interaction.student, expected_source_revision, validated_dimensions)

	active_dimensions = validated_dimensions if effective_status == "scored" else {}
	scores = [active_dimensions[name]["score"] for name in _DIMENSIONS] if active_dimensions else []
	total_score = round(sum(scores) / len(scores), 2) if scores else None
	normalized_score = round((total_score - 1) * 100 / 9, 2) if total_score is not None else None
	previous = frappe.db.get_all(
		"CRM NPS Point",
		filters={
			"interaction": run.interaction,
			"status": ["in", ["scored", "abstained"]],
			"source_revision": ["<", expected_source_revision],
		},
		fields=["name"],
		order_by="source_revision desc, creation desc",
	)
	point = frappe.get_doc(
		{
			"doctype": "CRM NPS Point",
			"interaction": run.interaction,
			"analysis_run": run_id,
			"student": interaction.student,
			"sale": sale["name"] if sale and effective_status == "scored" else None,
			"sale_user": sale["user"] if sale and effective_status == "scored" else None,
			"agent_id": interaction.agent_id,
			"interaction_datetime": interaction.interaction_datetime,
			"source_revision": expected_source_revision,
			"source_digest": expected_source_digest,
			"assessment_digest": assessment_digest,
			"idempotency_key": assessment_key,
			"status": effective_status,
			"terminal_reason": effective_reason,
			"satisfaction_score": active_dimensions.get("satisfaction", {}).get("score"),
			"resolution_score": active_dimensions.get("resolution", {}).get("score"),
			"friction_score": active_dimensions.get("friction", {}).get("score"),
			"complaint_score": active_dimensions.get("complaint", {}).get("score"),
			"total_score": total_score,
			"normalized_score": normalized_score,
			"confidence": confidence,
			"evidence_refs": json.dumps(
				{dimension: active_dimensions[dimension]["evidence_refs"] for dimension in active_dimensions},
				ensure_ascii=False,
				separators=(",", ":"),
			),
			"explanation": explanation,
			"policy_revision": policy_revision,
			"model_revision": model_revision,
			"contract_version": contract_version,
			"supersedes": previous[0].name if previous else None,
		}
	)
	previous_flag = getattr(frappe.flags, "crm_nps_point_service", False)
	frappe.flags.crm_nps_point_service = True
	try:
		point.insert(ignore_permissions=True)
		for old in previous:
			frappe.db.set_value(
				"CRM NPS Point", old.name, {"status": "superseded", "superseded_by": point.name}, update_modified=False
			)
	finally:
		frappe.flags.crm_nps_point_service = previous_flag
	return {
		"point": point.name,
		"replayed": False,
		"status": effective_status,
		"terminal_reason": effective_reason,
	}


def _require_readable_interaction(interaction: str) -> None:
	if not frappe.db.exists("CRM Interaction", interaction) or not frappe.has_permission(
		"CRM Interaction", "read", interaction
	):
		frappe.throw("Interaction is outside the current scope.", frappe.PermissionError)


@frappe.whitelist(methods=["GET", "POST"])
def get_interaction_nps_point(interaction: str) -> dict[str, Any]:
	"""Return the newest visible point for one canonical Interaction."""
	interaction = _required_text(interaction, "interaction")
	_require_readable_interaction(interaction)
	rows = frappe.get_list(
		"CRM NPS Point",
		filters={"interaction": interaction},
		fields=["name"],
		order_by="source_revision desc, creation desc",
		limit_page_length=1,
	)
	if not rows:
		return {"point": None}
	point = frappe.get_doc("CRM NPS Point", rows[0].name)
	if not point.has_permission("read"):
		frappe.throw("NPS point is outside the current scope.", frappe.PermissionError)
	return {"point": _serialize_point(point)}


def _visible_sale_filter(requested_sale: str | None) -> str | None:
	roles = set(frappe.get_roles())
	if roles & _FULL_READ_ROLES or frappe.session.user == "Administrator":
		return requested_sale or None
	if not roles & _SALE_ROLES:
		frappe.throw("You are not allowed to view NPS aggregates.", frappe.PermissionError)
	staff = frappe.db.get_value("CRM Staff", {"user": frappe.session.user, "is_active": 1}, "name")
	if not staff:
		frappe.throw("Your account is not linked to an active CRM Staff.", frappe.PermissionError)
	if requested_sale and requested_sale != staff:
		frappe.throw("A Sale may only view their own NPS aggregate.", frappe.PermissionError)
	return staff


@frappe.whitelist(methods=["GET", "POST"])
def get_nps_sale_summary(
	sale: str | None = None,
	from_date: str | None = None,
	to_date: str | None = None,
) -> dict[str, Any]:
	"""Return permission-scoped scored-point aggregates by Sale."""
	sale = _visible_sale_filter(sale)
	filters: dict[str, Any] = {"status": "scored"}
	if sale:
		filters["sale"] = sale
	if from_date:
		filters["interaction_datetime"] = [">=", from_date]
	if to_date:
		filters["interaction_datetime"] = (
			["<=", to_date]
			if "interaction_datetime" not in filters
			else ["between", [from_date, to_date]]
		)
	rows = frappe.get_list(
		"CRM NPS Point",
		filters=filters,
		fields=["sale", "sale_user", "normalized_score", "total_score", "confidence", "interaction_datetime"],
		limit_page_length=5000,
	)
	buckets: dict[str, dict[str, Any]] = {}
	for row in rows:
		if not row.sale:
			continue
		bucket = buckets.setdefault(
			row.sale,
			{
				"sale": row.sale,
				"sale_user": row.sale_user,
				"count": 0,
				"average_score": 0.0,
				"average_normalized_score": 0.0,
			},
		)
		bucket["count"] += 1
		bucket["average_score"] += float(row.total_score or 0)
		bucket["average_normalized_score"] += float(row.normalized_score or 0)
	for bucket in buckets.values():
		bucket["average_score"] = round(bucket["average_score"] / bucket["count"], 2)
		bucket["average_normalized_score"] = round(bucket["average_normalized_score"] / bucket["count"], 2)
	return {"records": list(buckets.values()), "total_points": len(rows)}
