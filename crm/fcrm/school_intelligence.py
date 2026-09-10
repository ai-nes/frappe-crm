"""Authoritative, read-oriented School 360 intelligence helpers.

Frappe owns the source rows and permission scope.  This module only derives
bounded school-level states from permission-aware reads; it never consults
Student Potential and never performs governance writes.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import now_datetime, nowdate

from crm.fcrm.admissions_migration import stable_fingerprint

POLICY_VERSION = "school-intelligence"
CALCULATION_REVISION = 1
RELATIONSHIP_STATES = frozenset({"New", "Active", "Dormant", "Do Not Contact"})
POTENTIAL_STATES = frozenset({"High", "Medium", "Low", "Unknown"})
SEGMENT_STATES = frozenset(
	{
		"High Potential / Active",
		"High Potential / Developing",
		"Low Potential / Active",
		"Low Potential / Developing",
		"Unknown",
	}
)
POTENTIAL_SEGMENT_BANDS = {"High": "High Potential", "Low": "Low Potential"}


def potential_value_from_metrics(actual: Any, threshold: Any) -> str | None:
	"""Return the canonical potential band for a snapshot metric pair."""
	try:
		ratio = float(actual) / float(threshold)
	except (TypeError, ValueError, ZeroDivisionError):
		return None
	if ratio >= 2:
		return "High"
	if ratio >= 1:
		return "Medium"
	return "Low"


def _scope_state() -> str:
	roles = set(frappe.get_roles()) if hasattr(frappe, "get_roles") else set()
	return "complete" if roles & {"Administrator", "System Manager", "Admissions Director", "Lead Sale", "Marketing", "Sale"} else "partial"


def _evidence(source: str, *, source_type: str, observed_at: Any = None, verification: str = "Verified") -> dict[str, Any]:
	return {
		# This is an opaque-to-the-model but resolvable provenance identifier.
		# Frappe rechecks it at render time; hashes cannot be safely re-authorized.
		"source": f"{source_type}:{source}",
		"source_class": "official" if verification == "Verified" else "observation",
		"observed_at": str(observed_at) if observed_at else None,
		"verification": verification,
	}


def _unknown(reason: str, *, evidence: list[dict[str, Any]] | None = None) -> dict[str, Any]:
	return {
		"value": "Unknown",
		"state": "unknown",
		"reason": reason,
		"policy_version": POLICY_VERSION,
		"calculation_revision": CALCULATION_REVISION,
		"source_data_revision": None,
		"as_of": None,
		"freshness": "unavailable",
		"evidence": evidence or [],
	}


def _latest_verified_snapshot(high_school: str, admission_year: str | None = None):
	filters: dict[str, Any] = {"high_school": high_school, "verification_status": "Verified", "period_type": "Annual"}
	if admission_year:
		filters["admission_year"] = admission_year
	rows = frappe.get_list(
		"CRM High School Annual Snapshot",
		filters=filters,
		fields=[
			"name", "high_school", "admission_year", "snapshot_date", "recorded_at",
			"ne_actual", "ne_target", "adjusted_ne_threshold", "applicant_count",
			"enrolled_count", "conversion_rate", "enrollment_rate", "revision",
			"idempotency_fingerprint", "verification_status",
		],
		order_by="admission_year desc, snapshot_date desc, revision desc",
		limit_page_length=1,
	)
	return rows[0] if rows else None


def calculate_school_potential(high_school: str, admission_year: str | None = None) -> dict[str, Any]:
	"""Calculate a school Potential state from a verified school snapshot.

	The policy intentionally uses only school-level source/derived metrics. A
	missing or non-positive threshold is unknown rather than inferred.
	"""
	snapshot = _latest_verified_snapshot(high_school, admission_year)
	if not snapshot:
		return _unknown("verified_snapshot_required")
	actual = snapshot.get("ne_actual")
	threshold = snapshot.get("adjusted_ne_threshold")
	value = potential_value_from_metrics(actual, threshold)
	if value is None:
		return _unknown("school_outcome_input_incomplete")
	source_revision = stable_fingerprint(
		"school-potential", snapshot.get("name"), snapshot.get("revision"),
		actual, threshold, snapshot.get("applicant_count"), snapshot.get("enrolled_count"),
		snapshot.get("conversion_rate"), snapshot.get("enrollment_rate"),
	)
	return {
		"value": value,
		"state": "current",
		"policy_version": POLICY_VERSION,
		"calculation_revision": CALCULATION_REVISION,
		"source_data_revision": source_revision,
		"as_of": str(snapshot.get("snapshot_date") or snapshot.get("recorded_at") or ""),
		"freshness": "as_of",
		"evidence": [_evidence(snapshot.get("name"), source_type="snapshot", observed_at=snapshot.get("snapshot_date"))],
		"scope_state": _scope_state(),
		"completeness": "caller_scope_only",
		"inputs": {"ne_actual": actual, "adjusted_ne_threshold": threshold},
	}


def derive_school_relationship(high_school: str) -> dict[str, Any]:
	"""Return the canonical relationship state from scoped stakeholder rows."""
	rows = frappe.get_list(
		"CRM School Stakeholder",
		filters={"high_school": high_school},
		fields=["name", "relationship_status", "relationship_revision", "relationship_changed_at", "creation", "effective_from", "effective_until"],
		order_by="modified desc",
		limit_page_length=0,
	)
	today = str(nowdate())
	rows = [
		row for row in rows
		if (not row.get("effective_from") or str(row["effective_from"]) <= today)
		and (not row.get("effective_until") or str(row["effective_until"]) >= today)
	]
	if not rows:
		return _unknown("stakeholder_association_required")
	statuses = {row.get("relationship_status") for row in rows}
	if "Do Not Contact" in statuses:
		value = "Do Not Contact"
	elif "Active" in statuses:
		value = "Active"
	elif "New" in statuses:
		value = "New"
	elif "Dormant" in statuses:
		value = "Dormant"
	else:
		return _unknown("relationship_state_unrecognised")
	return {
		"value": value,
		"state": "current",
		"policy_version": POLICY_VERSION,
		"calculation_revision": CALCULATION_REVISION,
		"source_data_revision": stable_fingerprint("school-relationship", *[(row.get("name"), row.get("relationship_revision"), row.get("relationship_status"), row.get("relationship_changed_at") or row.get("creation")) for row in rows]),
		"as_of": str(rows[0].get("relationship_changed_at") or rows[0].get("creation") or ""),
		"freshness": "live",
		"evidence": [_evidence(row.get("name"), source_type="stakeholder", observed_at=row.get("relationship_changed_at") or row.get("creation"), verification="Observed") for row in rows],
		"relationship_revisions": [row.get("relationship_revision") for row in rows],
		"scope_state": _scope_state(),
		"completeness": "caller_scope_only",
	}


def recent_school_activity_outcomes(high_school: str, admission_year: str | None = None) -> dict[str, Any]:
	"""Return bounded, resolvable activity/outcome evidence for School AI.

	No notes, attendee identities, or free-text next actions cross this boundary.
	Each outcome is tied to its owning activity so permission rechecks remain
	possible after the result has been persisted.
	"""
	filters: dict[str, Any] = {"high_school": high_school}
	if admission_year:
		filters["admission_year"] = admission_year
	rows = frappe.get_list(
		"CRM School Activity", filters=filters,
		fields=["name", "activity_date", "activity_type", "status", "outcome", "attendance", "prospect_count", "contact_count", "application_count"],
		order_by="activity_date desc, modified desc", limit_page_length=20,
	)
	return {
		"count": len(rows),
		"records": [
			{
				"activity_date": str(row.get("activity_date") or ""), "activity_type": row.get("activity_type"),
				"status": row.get("status"), "outcome": row.get("outcome"),
				"attendance": row.get("attendance"), "prospect_count": row.get("prospect_count"),
				"contact_count": row.get("contact_count"), "application_count": row.get("application_count"),
				"provenance_ids": [f"activity:{row.name}", f"outcome:{row.name}"],
			}
			for row in rows
		],
	}


def transition_school_relationship(
	association: str,
	new_status: str,
	idempotency_key: str,
	evidence_reference: str,
) -> dict[str, Any]:
	"""Apply one audited transition on the canonical stakeholder association."""
	if new_status not in RELATIONSHIP_STATES:
		raise ValueError("unsupported relationship status")
	if not idempotency_key or not evidence_reference:
		raise ValueError("idempotency_key and evidence_reference are required")
	doc = frappe.get_doc("CRM School Stakeholder", association)
	if not frappe.has_permission("CRM School Stakeholder", "write", doc):
		raise frappe.PermissionError("relationship transition is not permitted")
	if doc.get("relationship_last_idempotency_key") == idempotency_key:
		return {"status": "duplicate", "association": association, "revision": int(doc.get("relationship_revision") or 1)}
	transition_key = stable_fingerprint("relationship-transition", association, idempotency_key)
	activity_type = frappe.db.get_value(
		"CRM School Activity Type", {"name": "RELATIONSHIP_TOUCH"}, "name"
	)
	if not activity_type:
		raise ValueError("Relationship Touch activity type is not configured")
	frappe.db.sql(
		"select name from `tabCRM School Stakeholder` where name = %s for update",
		(association,),
	)
	doc = frappe.get_doc("CRM School Stakeholder", association)
	if doc.get("relationship_last_idempotency_key") == idempotency_key:
		return {"status": "duplicate", "association": association, "revision": int(doc.get("relationship_revision") or 1)}
	if frappe.db.exists("CRM School Activity", {"import_idempotency_key": transition_key}):
		return {"status": "duplicate", "association": association, "revision": int(doc.get("relationship_revision") or 1)}
	previous = doc.get("relationship_status") or "New"
	doc.relationship_status = new_status
	doc.relationship_revision = int(doc.get("relationship_revision") or 1) + 1
	doc.relationship_changed_at = now_datetime()
	doc.relationship_changed_by = frappe.session.user
	doc.relationship_last_idempotency_key = idempotency_key
	doc.relationship_evidence_reference = evidence_reference
	previous_flag = getattr(frappe.flags, "school_relationship_transition", False)
	frappe.flags.school_relationship_transition = True
	try:
		doc.save(ignore_permissions=True)
	finally:
		frappe.flags.school_relationship_transition = previous_flag
	frappe.get_doc(
		{
				"doctype": "CRM School Activity",
				"high_school": doc.high_school,
				"stakeholder": doc.name,
				"activity_type": activity_type,
				"activity_date": nowdate(),
				"owner_staff": doc.owner_staff,
				"owning_team": doc.owning_team,
				"status": "Completed",
				"evidence_reference": evidence_reference,
				"outcome": "Follow-up Needed" if new_status in {"New", "Dormant"} else "Positive",
				"import_idempotency_key": transition_key,
				"relationship_previous_status": previous,
				"relationship_new_status": new_status,
				"relationship_revision": doc.relationship_revision,
			}
	).insert(ignore_permissions=True)
	return {
		"status": "applied",
		"association": doc.name,
		"previous_status": previous,
		"relationship_status": new_status,
		"revision": doc.relationship_revision,
		"evidence_reference": evidence_reference,
		"policy_version": POLICY_VERSION,
	}


def derive_school_segment(potential: dict[str, Any], relationship: dict[str, Any]) -> dict[str, Any]:
	"""Derive the four-quadrant segment without consulting Key Account."""
	if potential.get("value") not in POTENTIAL_SEGMENT_BANDS:
		return _unknown("potential_unknown", evidence=potential.get("evidence", []))
	if relationship.get("value") not in RELATIONSHIP_STATES:
		return _unknown("relationship_unknown", evidence=relationship.get("evidence", []))
	if relationship.get("scope_state") == "partial":
		return _unknown("relationship_scope_partial", evidence=relationship.get("evidence", []))
	potential_band = POTENTIAL_SEGMENT_BANDS[potential["value"]]
	relationship_band = "Active" if relationship["value"] == "Active" else "Developing"
	return {
		"value": f"{potential_band} / {relationship_band}",
		"state": "current",
		"policy_version": POLICY_VERSION,
		"calculation_revision": CALCULATION_REVISION,
		"source_data_revision": stable_fingerprint(
			"school-segment", potential.get("source_data_revision"), relationship.get("source_data_revision")
		),
		"as_of": max(str(potential.get("as_of") or ""), str(relationship.get("as_of") or "")),
		"freshness": "as_of" if potential.get("freshness") == "as_of" else "live",
		"evidence": [*potential.get("evidence", []), *relationship.get("evidence", [])],
	}


def get_school_intelligence(high_school: str, admission_year: str | None = None) -> dict[str, Any]:
	"""Build the bounded school intelligence state for the current caller."""
	potential = calculate_school_potential(high_school, admission_year)
	relationship = derive_school_relationship(high_school)
	return {
		"school": high_school,
		"admission_year": admission_year,
		"potential": potential,
		"relationship": relationship,
		"segment": derive_school_segment(potential, relationship),
		"activity_outcomes": recent_school_activity_outcomes(high_school, admission_year),
		"provenance_ids": [f"school:{high_school}"],
		"policy_version": POLICY_VERSION,
		"calculation_revision": CALCULATION_REVISION,
		"scope": {"high_school": "caller-scoped", "annual_snapshot": "caller-scoped", "stakeholder": "caller-scoped"},
	}
