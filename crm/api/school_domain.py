from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import frappe

from crm.services.intelligence_refs import build_decision_ref, build_subject_ref


SCHOOL360_CONTRACT_VERSION = "school360.overview.read:v1"
SCHOOL360_POLICY_VERSION = "school360-read-v1"
SCHOOL360_CONTRACT_REVISION = "school360-overview-r1"
RECOMMENDATION_CONTEXT_CONTRACT_VERSION = "school360.recommendation.context.read:v1"
RECOMMENDATION_POLICY_VERSION = "school360-recommendation-v1"
RECOMMENDATION_POLICY_REVISION = "school360-recommendation-policy-r1"
RECOMMENDATION_DTO_REVISION = "school360-recommendation-dto-r1"
RECOMMENDATION_ROLLOUT_CONFIG_KEY = "crm_agents_school360_recommendation_rollout"
RECOMMENDATION_KILL_SWITCH_CONFIG_KEY = "crm_agents_school360_recommendation_kill_switch"
RECOMMENDATION_GATE_REVISION_CONFIG_KEY = "crm_agents_school360_recommendation_gate_revision"
_YEAR_MIN, _YEAR_MAX = 2000, 2100
_MAX_ACTIVITIES, _MAX_STAKEHOLDERS = 100, 50
_MAX_RECOMMENDATION_AGE_DAYS = 365


def _school360_scope(
	doctype: str,
	fields: list[str],
	*,
	status: str | None = None,
	probe_filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
	"""Return an opaque, explicit proof of one child-resource permission check."""
	try:
		permitted = bool(frappe.has_permission(doctype, "read"))
	except Exception:
		return {"status": "unavailable", "permitted": False, "scope_proof": False, "field_projection": []}
	if permitted and probe_filters is not None:
		try:
			# A bounded row probe makes the caller's row scope explicit without
			# returning the child identifier in the DTO.
			frappe.get_list(doctype, filters=probe_filters, fields=["name"], limit_page_length=1)
		except Exception:
			return {"status": "unavailable", "permitted": False, "scope_proof": False, "field_projection": []}
	return {
		"status": status or ("available" if permitted else "denied"),
		"permitted": permitted,
		"scope_proof": True,
		"field_projection": fields if permitted else [],
	}


def _school360_permission_error() -> None:
	message = "School 360 access is not permitted"
	permission_error = getattr(frappe, "PermissionError", PermissionError)
	if hasattr(frappe, "throw"):
		frappe.throw(message, permission_error)
	raise permission_error(message)


def _school360_year(admission_year: str | None) -> str | None:
	if admission_year is None or admission_year == "":
		return None
	if not isinstance(admission_year, str) or not admission_year.isdigit() or len(admission_year) != 4:
		raise ValueError("admission_year must be a four-digit year")
	year = int(admission_year)
	if not _YEAR_MIN <= year <= _YEAR_MAX:
		raise ValueError("admission_year is outside the supported range")
	return admission_year


def _school360_rows(
	doctype: str,
	*,
	filters: dict[str, Any],
	fields: list[str],
	limit: int,
	order_by: str = "modified desc",
) -> list[dict[str, Any]]:
	rows = frappe.get_list(
		doctype,
		filters=filters,
		fields=fields,
		order_by=order_by,
		limit_page_length=limit,
	)
	return [dict(row) for row in rows]


@frappe.whitelist()
def get_school_stakeholders(high_school: str, limit: int = 50):
	"""Return school associations with the linked Person identity for the panel."""
	# Use permission-aware list queries: Promoter scope is enforced by the
	# DocType hooks and must also apply to this whitelisted panel endpoint.
	associations = frappe.get_list(
		"CRM School Stakeholder",
		filters={"high_school": high_school},
		fields=[
			"person", "stakeholder_role", "position_title",
			"relationship_status", "influence", "is_primary",
		],
		order_by="modified desc",
		limit_page_length=min(int(limit or 50), 100),
	)
	person_names = [row.person for row in associations if row.person]
	people = {
		row.name: row
		for row in frappe.get_list(
			"CRM Person",
			filters={"name": ["in", person_names]} if person_names else {"name": "__none__"},
			fields=["name", "full_name"],
			limit_page_length=0,
		)
	}
	return [
		{
			"full_name": people.get(row.person, {}).get("full_name") if row.person else None,
			"stakeholder_role": row.stakeholder_role,
			"position_title": row.position_title,
			"relationship_status": row.relationship_status,
			"influence": row.influence,
			"is_primary": bool(row.is_primary),
		}
		for row in associations
	]


@frappe.whitelist()
def get_school360_overview(high_school: str, admission_year: str | None = None) -> dict[str, Any]:
	"""Return one bounded, permission-intersected School 360 read model.

	The endpoint deliberately has no method/query or arbitrary filter arguments.
	Every section records the child-resource permission proof used to build it;
	denied sections are explicit and never represented as an empty fact list.
	"""
	if not isinstance(high_school, str) or not high_school.strip() or len(high_school) > 140:
		raise ValueError("high_school must identify exactly one school")
	high_school = high_school.strip()
	admission_year = _school360_year(admission_year)
	identity_fields = [
		"school_name", "school_code", "school_type", "school_area", "school_tier",
		"boarding_type", "province", "ward", "latitude", "longitude",
	]
	identity_rows = _school360_rows(
		"CRM High School", filters={"name": high_school}, fields=identity_fields, limit=1
	)
	if not identity_rows:
		# A permission-aware list is the correct row-scope proof for portfolio
		# roles; passing a bare name to has_permission bypasses their doc hook.
		_school360_permission_error()
	identity = identity_rows[0]

	scope_by_resource: dict[str, dict[str, Any]] = {
		"High School": _school360_scope("CRM High School", identity_fields),
		"Snapshot": _school360_scope(
			"CRM High School Annual Snapshot",
			[
				"admission_year", "period_type", "revision", "ne_actual",
				"average_score", "snapshot_date",
				"verification_status",
			],
		),
		"Person": _school360_scope(
			"CRM Person", ["full_name"], status="partial"
		),
		"Activity": _school360_scope(
			"CRM School Activity",
			[
				"activity_type", "activity_date", "status", "outcome", "attendance",
			], status="partial",
		),
		# Presence is checked independently, but canonical child identifiers are
		# never projected into this DTO.
		"Contact": _school360_scope("CRM Student", [], probe_filters={"high_school": high_school}),
		"Student": _school360_scope("CRM Student", [], probe_filters={"high_school": high_school}),
	}
	relationship_scope = _school360_scope(
		"CRM School Stakeholder",
		[
			"stakeholder_role", "position_title", "relationship_status",
			"relationship_revision", "relationship_changed_at", "influence", "is_primary",
		], status="partial",
	)
	snapshot_filters: dict[str, Any] = {
		"high_school": high_school,
		"period_type": "Annual",
		"verification_status": "Verified",
	}
	if admission_year:
		snapshot_filters["admission_year"] = admission_year
	snapshots: list[dict[str, Any]] = []
	if scope_by_resource["Snapshot"]["permitted"]:
		snapshots = _school360_rows(
			"CRM High School Annual Snapshot",
			filters=snapshot_filters,
			fields=scope_by_resource["Snapshot"]["field_projection"],
			limit=100,
			order_by="admission_year desc, snapshot_date desc, revision desc",
		)
		# Child-row-scoped aggregate proof is intentionally not assumed here;
		# redact contact/student/application totals from every School 360 output.
		for row in snapshots:
			for field in (
				"applicant_count", "enrolled_count", "contact_count", "student_count",
				"conversion_count", "conversion_rate", "enrollment_rate",
			):
				row.pop(field, None)
	else:
		scope_by_resource["Snapshot"]["status"] = "denied"

	stakeholder_rows: list[dict[str, Any]] = []
	if scope_by_resource["Person"]["permitted"] and relationship_scope["permitted"]:
		associations = _school360_rows(
			"CRM School Stakeholder",
			filters={"high_school": high_school},
			fields=[
				"person", "stakeholder_role", "position_title", "relationship_status",
				"relationship_revision", "relationship_changed_at", "influence", "is_primary",
			],
			limit=_MAX_STAKEHOLDERS,
		)
		person_names = [row.get("person") for row in associations if row.get("person")]
		people = {
			row.get("name"): row.get("full_name")
			for row in _school360_rows(
				"CRM Person",
				filters={"name": ["in", person_names]} if person_names else {"name": "__none__"},
				fields=["name", "full_name"],
				limit=_MAX_STAKEHOLDERS,
			)
		}
		stakeholder_rows = [
			{
				"full_name": people.get(row.get("person")),
				"stakeholder_role": row.get("stakeholder_role"),
				"position_title": row.get("position_title"),
				"relationship_status": row.get("relationship_status"),
				"relationship_revision": row.get("relationship_revision"),
				"relationship_changed_at": row.get("relationship_changed_at"),
				"influence": row.get("influence"),
				"is_primary": bool(row.get("is_primary")),
			}
			for row in associations
		]
	else:
		if not scope_by_resource["Person"]["permitted"]:
			scope_by_resource["Person"]["status"] = "denied"
		if not relationship_scope["permitted"]:
			relationship_scope["status"] = "denied"

	activities: list[dict[str, Any]] = []
	if scope_by_resource["Activity"]["permitted"]:
		activities = _school360_rows(
			"CRM School Activity",
			filters={"high_school": high_school},
			fields=scope_by_resource["Activity"]["field_projection"],
			limit=_MAX_ACTIVITIES,
		)
		for row in activities:
			for field in ("prospect_count", "contact_count", "application_count"):
				row.pop(field, None)
	else:
		scope_by_resource["Activity"]["status"] = "denied"

	# Potential uses the governance-controlled adjusted threshold (permlevel 1).
	# Do not derive it for ordinary roles merely because they can read snapshots;
	# the protected input must be authorized independently.
	try:
		roles = set(frappe.get_roles()) if hasattr(frappe, "get_roles") else set()
		if roles & {"Administrator", "System Manager", "Admissions Director"}:
			from crm.fcrm.school_intelligence import get_school_intelligence
			intelligence = get_school_intelligence(high_school, admission_year=admission_year)
		else:
			intelligence = None
	except Exception:
		# The bounded endpoint remains usable for identity/verified facts, but the
		# derived section is explicitly unknown rather than silently fabricated.
		intelligence = None

	def _section(status: str, data: Any, *, resource: str, freshness: str = "fresh") -> dict[str, Any]:
		return {
			"status": status,
			"data": data if status != "denied" else None,
			"scope_proof": bool(scope_by_resource[resource].get("scope_proof")),
			"verification": "verified" if status in {"available", "partial"} else "unknown",
			"freshness": freshness,
		}

	identity_section = _section("available", identity, resource="High School")
	geography_section = _section(
		"available",
		{field: identity.get(field) for field in ("province", "ward", "latitude", "longitude")},
		resource="High School",
	)
	snapshot_status = "available" if snapshots else "partial"
	if snapshots and (not scope_by_resource["Contact"]["permitted"] or not scope_by_resource["Student"]["permitted"]):
		snapshot_status = "partial"
	if not scope_by_resource["Snapshot"]["permitted"]:
		snapshot_status = "denied"
	# Child records are row-scoped; a permission-aware list is not proof of
	# completeness, so expose them as partial even when rows are returned.
	activity_status = "partial" if scope_by_resource["Activity"]["permitted"] else "denied"
	stakeholder_status = (
		"partial"
		if scope_by_resource["Person"]["permitted"] and relationship_scope["permitted"]
		else "denied"
	)

	latest_snapshot = snapshots[0] if snapshots else None
	outcomes = {
		field: latest_snapshot.get(field)
		for field in ("average_score",)
		if latest_snapshot and latest_snapshot.get(field) is not None
	}

	scope_revision = hashlib.sha256(
		json.dumps(
			{"resources": scope_by_resource, "relationship": relationship_scope},
			sort_keys=True,
			default=str,
		).encode("utf-8")
	).hexdigest()[:16]
	as_of = latest_snapshot.get("snapshot_date") if latest_snapshot else None
	source_revision = hashlib.sha256(
		json.dumps({"snapshots": snapshots, "activities": activities, "scope": scope_revision}, sort_keys=True, default=str).encode("utf-8")
	).hexdigest()[:16]
	now = datetime.now(timezone.utc).isoformat()
	try:
		as_of_dt = datetime.fromisoformat(str(as_of)) if as_of else None
		overview_freshness = "fresh" if as_of_dt and (datetime.now(timezone.utc).date() - as_of_dt.date()).days <= _MAX_RECOMMENDATION_AGE_DAYS else "stale" if as_of_dt else "unknown"
	except (TypeError, ValueError):
		overview_freshness = "unknown"
	def _redacted_signal(value: Any) -> dict[str, Any]:
		if not isinstance(value, dict):
			return {"value": "Unknown", "state": "unknown", "freshness": "unknown"}
		result = {
			key: value.get(key)
			for key in (
				"value", "state", "policy_version", "calculation_revision",
				"source_data_revision", "as_of", "freshness", "evidence",
				"relationship_revisions",
			)
			if value.get(key) is not None
		}
		if result.get("freshness") not in {"fresh", "unknown", "stale"}:
			result["freshness"] = "fresh" if result.get("freshness") else "unknown"
		return result
	return {
		"contract_version": SCHOOL360_CONTRACT_VERSION,
		"contract_revision": SCHOOL360_CONTRACT_REVISION,
		"policy_version": SCHOOL360_POLICY_VERSION,
		"source_data_revision": source_revision,
		"principal_scope_revision": scope_revision,
		"as_of": as_of or now,
		"freshness": overview_freshness,
		"scope_by_resource": scope_by_resource,
		"relationship_scope": relationship_scope,
		"identity": identity_section,
		"geography": geography_section,
		"academic_scale": _section(snapshot_status, snapshots, resource="Snapshot"),
		"stakeholders": {
			"status": stakeholder_status,
			"data": stakeholder_rows if stakeholder_status != "denied" else None,
			"scope_proof": bool(relationship_scope.get("scope_proof")),
			"verification": "verified" if stakeholder_status in {"available", "partial"} else "unknown",
			"freshness": "fresh",
		},
		"activity_history": _section(activity_status, activities, resource="Activity"),
		"outcomes": _section("partial" if snapshot_status != "denied" else "denied", outcomes, resource="Snapshot"),
		"intelligence": _section(
			"available" if intelligence and scope_by_resource["Snapshot"]["permitted"] and scope_by_resource["Person"]["permitted"] and relationship_scope["permitted"] and intelligence.get("potential", {}).get("state") == "current" and intelligence.get("relationship", {}).get("state") == "current" else "denied" if not scope_by_resource["Snapshot"]["permitted"] else "partial",
			{
				"potential": _redacted_signal(intelligence.get("potential") if intelligence else None),
				**(
					{
						"relationship": _redacted_signal(intelligence.get("relationship")),
						"segment": _redacted_signal(intelligence.get("segment")),
					}
					if intelligence and scope_by_resource["Person"]["permitted"] and relationship_scope["permitted"]
					else {}
				),
				"policy_version": intelligence.get("policy_version") if intelligence else None,
				"calculation_revision": intelligence.get("calculation_revision") if intelligence else None,
				"source_fingerprint": (
					intelligence.get("potential", {}).get("source_data_revision")
					if intelligence else None
				),
				"as_of": intelligence.get("as_of") if intelligence else None,
				"freshness": intelligence.get("freshness") if intelligence else "unknown",
			},
			resource="Snapshot",
		),
		"provenance": {
			"authoritative": True,
			"redacted": True,
			"as_of": as_of or now,
			"freshness": overview_freshness,
			"contract_revision": SCHOOL360_CONTRACT_REVISION,
			"policy_revision": SCHOOL360_POLICY_VERSION,
			"source_data_revision": source_revision,
			"principal_scope_revision": scope_revision,
		},
	}


@frappe.whitelist()
def get_school_recommendation_context(high_school: str, use_case: str) -> dict[str, Any]:
	"""Return one deterministic, advisory candidate chosen by Frappe policy.

	The endpoint intentionally returns no mutation token and accepts no threshold,
	ranking, filter or candidate arguments.  AI consumers can explain this
	projection, but cannot manufacture a different candidate.
	"""
	if not isinstance(high_school, str) or not high_school.strip() or len(high_school) > 140:
		raise ValueError("high_school must identify exactly one school")
	if not isinstance(use_case, str) or not use_case.strip() or len(use_case) > 60:
		raise ValueError("use_case is required")
	high_school = high_school.strip()
	use_case = use_case.strip().casefold()
	allowed_cases = {"outreach", "admissions", "admission_follow_up", "relationship_review", "engagement"}
	if use_case not in allowed_cases:
		raise ValueError("unsupported use_case")
	conf = getattr(frappe, "conf", None)
	get_conf = getattr(conf, "get", lambda *_args: None)
	rollout = get_conf(RECOMMENDATION_ROLLOUT_CONFIG_KEY) or "disabled"
	kill_switch = str(get_conf(RECOMMENDATION_KILL_SWITCH_CONFIG_KEY) or "1").casefold() in {"1", "true", "yes", "on"}
	if kill_switch or rollout == "disabled":
		raise frappe.PermissionError("School recommendation rollout is disabled")
	if rollout == "shadow":
		return {
			"contract_version": RECOMMENDATION_CONTEXT_CONTRACT_VERSION,
			"context_id": hashlib.sha256(f"shadow:{high_school}:{use_case}".encode()).hexdigest()[:32],
			"high_school": high_school, "use_case": use_case, "disposition": "REVIEW",
			"candidates": [], "missing_evidence": ["shadow_only"],
			"abstention_reason": "Shadow mode never exposes recommendations.",
			"scope_state": "unavailable", "freshness": "unknown",
			"policy_version": RECOMMENDATION_POLICY_VERSION, "policy_revision": RECOMMENDATION_POLICY_REVISION,
			"source_data_revision": "shadow", "dto_revision": RECOMMENDATION_DTO_REVISION,
			"principal_scope_revision": "shadow", "issued_at": datetime.now(timezone.utc).isoformat(),
			"expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
		}
	if rollout == "pilot" and (not get_conf(RECOMMENDATION_GATE_REVISION_CONFIG_KEY) or "Admissions Director" not in set(frappe.get_roles() or [])):
		raise frappe.PermissionError("School recommendation pilot is not approved for this role")
	# The overview call performs the canonical school row/child scope checks.
	overview = get_school360_overview(high_school)
	identity = overview.get("identity", {}) if isinstance(overview, dict) else {}
	intelligence_section = overview.get("intelligence", {}) if isinstance(overview, dict) else {}
	intelligence = intelligence_section.get("data") if isinstance(intelligence_section, dict) else None
	if not isinstance(identity, dict) or identity.get("status") in {"denied", "unavailable"}:
		raise frappe.PermissionError("School recommendation context is not permitted")

	now = datetime.now(timezone.utc)
	expires_at = now.replace(microsecond=0)
	expires_at = expires_at + timedelta(hours=24)
	source_revision = str(overview.get("source_data_revision") or "unknown")
	scope_revision = str(overview.get("principal_scope_revision") or "unknown")
	base = {
		"contract_version": RECOMMENDATION_CONTEXT_CONTRACT_VERSION,
		"context_id": hashlib.sha256(f"{high_school}:{use_case}:{source_revision}:{scope_revision}".encode()).hexdigest()[:32],
		"high_school": high_school,
		"use_case": use_case,
		"policy_version": RECOMMENDATION_POLICY_VERSION,
		"policy_revision": RECOMMENDATION_POLICY_REVISION,
		"source_data_revision": source_revision,
		"dto_revision": RECOMMENDATION_DTO_REVISION,
		"principal_scope_revision": scope_revision,
		"scope_state": "available" if overview.get("freshness") == "fresh" else "partial",
		"freshness": overview.get("freshness") if overview.get("freshness") in {"fresh", "unknown", "stale"} else "unknown",
		"issued_at": now.isoformat(),
		"expires_at": expires_at.isoformat(),
	}
	subject_ref = build_subject_ref("school", high_school, str(frappe.local.site or "frappe"))
	def decision_ref(disposition: str, *, evidence_refs: list[str] = (), reason: str | None = None):
		return build_decision_ref(
			decision_id=f"school:{high_school}:{base['context_id']}",
			domain="school_recommendation",
			subject=subject_ref,
			disposition=disposition,
			policy_revision=RECOMMENDATION_POLICY_REVISION,
			evidence_refs=evidence_refs,
			expires_at=base["expires_at"] if disposition == "recommend" else None,
			abstention_reason=reason,
		).copy()
	potential = intelligence.get("potential", {}) if isinstance(intelligence, dict) else {}
	relationship = intelligence.get("relationship", {}) if isinstance(intelligence, dict) else {}
	missing: list[str] = []
	if not isinstance(intelligence, dict) or intelligence_section.get("status") in {"denied", "unavailable"}:
		missing.append("intelligence_scope")
	intelligence_scope_complete = all(
		bool(overview.get("scope_by_resource", {}).get(resource, {}).get("permitted"))
		and bool(overview.get("scope_by_resource", {}).get(resource, {}).get("scope_proof"))
		for resource in ("Snapshot", "Person")
	) and bool(overview.get("relationship_scope", {}).get("permitted")) and bool(overview.get("relationship_scope", {}).get("scope_proof"))
	if intelligence_section.get("status") != "available" and not intelligence_scope_complete:
		missing.append("intelligence_scope")
	if potential.get("value") in {None, "Unknown"}:
		missing.append("verified_school_potential")
	if relationship.get("value") in {None, "Unknown"}:
		missing.append("school_relationship")
	if potential.get("state") != "current":
		missing.append("current_school_potential")
	if relationship.get("state") != "current":
		missing.append("current_school_relationship")
	if base["freshness"] != "fresh":
		missing.append("fresh_current_snapshot")
	if missing:
		disposition = "REVIEW" if "school_relationship" not in missing else "ABSTAIN"
		reason = "Insufficient or non-current evidence for a governed candidate."
		return {**base, "disposition": disposition, "decision_ref": decision_ref("review" if disposition == "REVIEW" else "abstain", reason=reason).copy(), "candidates": [], "missing_evidence": missing, "abstention_reason": reason}

	# Ordered policy table: only this server-side order is exposed to the consumer.
	policy = {
		"outreach": ("relationship_review", "schedule_outreach", "School relationship is available for a human-reviewed outreach.",),
		"admissions": ("school_review", "review_school", "Verified school potential is available for a human decision.",),
		"admission_follow_up": ("follow_up", "prepare_follow_up", "Verified school and relationship signals support a follow-up review.",),
		"relationship_review": ("relationship_review", "review_school", "The canonical school relationship is available for review.",),
		"engagement": ("relationship_review", "prepare_follow_up", "Current relationship evidence supports a prepared engagement review.",),
	}
	candidate_type, action, claim = policy[use_case]
	recommendation_id = hashlib.sha256(f"{base['context_id']}:{candidate_type}".encode()).hexdigest()[:32]
	evidence_refs = [f"school:{high_school}", f"source:{source_revision}"]
	candidate = {
		"recommendation_id": recommendation_id,
		"candidate_type": candidate_type,
		"disposition": "RECOMMEND",
		"allowed_action": action,
		"rationale_claims": [claim],
		"evidence_refs": evidence_refs,
		"missing_evidence": [],
		"scope_state": base["scope_state"],
		"freshness": base["freshness"],
		"policy_version": base["policy_version"],
		"policy_revision": base["policy_revision"],
		"source_data_revision": source_revision,
		"dto_revision": RECOMMENDATION_DTO_REVISION,
		"expires_at": base["expires_at"],
		"decision_ref": decision_ref("recommend", evidence_refs=[f"school:{high_school}:{source_revision}", f"source:{source_revision}:{source_revision}"]).copy(),
	}
	return {**base, "disposition": "RECOMMEND", "decision_ref": candidate["decision_ref"], "candidates": [candidate], "missing_evidence": [], "abstention_reason": None}
