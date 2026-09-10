"""Transactional score-write command and the Frappe-owned scoring boundary."""

from __future__ import annotations

import math

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from crm.fcrm.scoring_compute import compute_time_decay, compute_total, days_since_student_touchpoint
from crm.fcrm.scoring_contributors import validate_contributors
from crm.fcrm.scoring_policy import resolve_policy_rules


def _fixture_score_site_allowed() -> bool:
	"""The curated demo seed writes fixture scores as Administrator.

	Normally that is crm.localhost only. A demo / staging server opts in the
	same way the rest of the showcase seed does -- ``bench set-config
	allow_demo_seed 1`` -- so the deployed demo dataset carries scores too.
	"""
	if frappe.session.user != "Administrator":
		return False
	return frappe.local.site == "crm.localhost" or bool(frappe.conf.get("allow_demo_seed"))


def _require_agent_identity():
	if getattr(frappe.flags, "crm_internal_scoring", False):
		return
	if getattr(frappe.flags, "crm_local_fixture_score_write", False):
		if _fixture_score_site_allowed():
			return
		frappe.throw(
			_("Local fixture scoring is only available to Administrator on crm.localhost."),
			frappe.PermissionError,
		)
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication is required."), frappe.PermissionError)
	if frappe.session.user == "Administrator":
		return
	configured = frappe.conf.get("crm_agents_service_user")
	if not configured or frappe.session.user != configured:
		frappe.throw(
			_("This command is restricted to the crm-agents service identity."), frappe.PermissionError
		)


def _response(
	*,
	history=None,
	applied=False,
	duplicate=False,
	stale=False,
	final_score=None,
	score_change=None,
	time_decay_score=None,
	**extra,
) -> dict:
	return {
		"history": history,
		"applied": applied,
		"duplicate": duplicate,
		"stale": stale,
		"final_score": final_score,
		"score_change": score_change,
		"time_decay_score": time_decay_score,
		**extra,
	}


def _history_result(name: str | None) -> dict:
	if not name:
		return {"final_score": None, "score_change": None, "time_decay_score": None}
	row = (
		frappe.db.get_value(
			"CRM Score History",
			name,
			["final_score", "score_change", "time_decay_score"],
			as_dict=True,
		)
		or {}
	)
	return {
		"final_score": row.get("final_score"),
		"score_change": row.get("score_change"),
		"time_decay_score": row.get("time_decay_score"),
	}


def _failed_template_response() -> dict:
	return _response(failed=True, reason="template_unavailable")


def _parse_components(components) -> dict | None:
	if components is None:
		return None
	if isinstance(components, str):
		try:
			components = frappe.parse_json(components)
		except Exception:
			frappe.throw(_("Components must be a JSON object."), frappe.ValidationError)
	if not isinstance(components, dict):
		frappe.throw(_("Components must be a JSON object."), frappe.ValidationError)
	if set(components) != {"fit", "engagement", "intent", "negative"}:
		frappe.throw(
			_("Components must contain fit, engagement, intent, and negative."), frappe.ValidationError
		)
	negative = components.get("negative")
	if not isinstance(negative, dict) or set(negative) != {"score", "contributors"}:
		frappe.throw(_("Negative components must contain score and contributors."), frappe.ValidationError)
	try:
		values = {
			"fit": flt(components["fit"]),
			"engagement": flt(components["engagement"]),
			"intent": flt(components["intent"]),
			"negative": flt(negative["score"]),
		}
	except (TypeError, ValueError):
		frappe.throw(_("Component scores must be numeric."), frappe.ValidationError)
	if not all(math.isfinite(value) for value in values.values()):
		frappe.throw(_("Component scores must be finite."), frappe.ValidationError)
	for field in ("fit", "engagement", "intent"):
		if not 0.0 <= values[field] <= 100.0:
			frappe.throw(_(f"{field} must be between 0 and 100."), frappe.ValidationError)
	if values["negative"] > 0.0:
		frappe.throw(_("negative must be less than or equal to 0."), frappe.ValidationError)
	values["contributors"] = validate_contributors(negative.get("contributors"))
	return values


def _load_payload_template(score_template: str, policy_revision: int, policy_hash: str):
	try:
		template = frappe.get_doc("CRM Score Template", score_template)
	except Exception:
		return None
	if (
		template.name != score_template
		or template.status != "Active"
		or int(template.policy_revision or 0) != policy_revision
		or (template.policy_hash or "") != (policy_hash or "")
	):
		return None
	return template


def _drift_kind(
	expected_final_score,
	final_score,
	expected_time_decay_factor,
	time_decay_factor,
) -> str | None:
	if expected_time_decay_factor is None or expected_final_score is None:
		return None
	try:
		expected_decay = float(expected_time_decay_factor)
		expected_final = float(expected_final_score)
	except (TypeError, ValueError):
		return None
	if not math.isfinite(expected_decay) or not math.isfinite(expected_final):
		return None
	if abs(expected_decay - time_decay_factor) > 1e-9:
		return "decay_recency"
	if abs(expected_final - final_score) > 0.05:
		return "formula"
	return None


def _write_drift(
	*,
	student,
	expected_final_score,
	final_score,
	expected_time_decay_factor,
	time_decay_factor,
	expected_days_since,
	days_since,
	score_template,
	policy_revision,
	scoring_time,
) -> None:
	kind = _drift_kind(
		expected_final_score,
		final_score,
		expected_time_decay_factor,
		time_decay_factor,
	)
	if kind is None:
		return
	try:
		frappe.get_doc(
			{
				"doctype": "CRM Score Drift",
				"student": student,
				"expected_final_score": expected_final_score,
				"final_score": final_score,
				"expected_time_decay_factor": expected_time_decay_factor,
				"time_decay_factor": time_decay_factor,
				"expected_days_since": expected_days_since,
				"days_since": days_since,
				"score_template": score_template,
				"policy_revision": policy_revision,
				"drift_kind": kind,
				"scoring_time": scoring_time,
			}
		).insert(ignore_permissions=True, ignore_links=True)
	except Exception:
		# Drift is observability, never a reason to roll back an authoritative score.
		frappe.log_error(
			title="CRM Score Drift write failed",
			message=f"student={student}, template={score_template}, kind={kind}",
		)


@frappe.whitelist()
def append_score_if_current(
	student: str,
	source_score_input_revision: int,
	policy_revision: int,
	policy_hash: str,
	score_template: str,
	scoring_time: str,
	fit_score: float | None = None,
	engagement_score: float | None = None,
	intent_score: float | None = None,
	time_decay_score: float | None = None,
	negative_score: float | None = None,
	final_score: float | None = None,
	score_change: float | None = None,
	details: list | str | None = None,
	triggered_by_doctype: str = "",
	triggered_by: str = "",
	components: dict | str | None = None,
	expected_final_score: float | None = None,
	expected_time_decay_factor: float | None = None,
	expected_days_since: int | None = None,
) -> dict:
	"""Append a score under the per-student CAS boundary.

	When ``components`` is present, Frappe resolves the named template and owns
	the component validation, recency, time decay, total, and score change.  An
	absent ``components`` object deliberately preserves the legacy fixture/write
	path and stores the supplied score values unchanged.
	"""
	_require_agent_identity()
	if isinstance(details, str):
		details = frappe.parse_json(details) or []
	details = details or []
	source_score_input_revision = int(source_score_input_revision)
	policy_revision = int(policy_revision)
	if source_score_input_revision < 0 or policy_revision < 0:
		frappe.throw(_("Invalid revision."), frappe.ValidationError)

	component_values = _parse_components(components)
	days_since = None
	template = None
	if component_values is not None:
		template = _load_payload_template(score_template, policy_revision, policy_hash)
		if template is None:
			return _failed_template_response()
		# This query intentionally precedes the SELECT ... FOR UPDATE below.
		days_since = days_since_student_touchpoint(student, now_datetime())
		validate_contributors(details)
		_, _, time_decay_config = resolve_policy_rules(template)
		time_decay_score = compute_time_decay(days_since, time_decay_config)
		final_score = compute_total(
			component_values["fit"],
			component_values["engagement"],
			component_values["intent"],
			component_values["negative"],
			template.fit_weight,
			template.engagement_weight,
			template.intent_weight,
			time_decay_score,
		)

	row = frappe.db.sql(
		"SELECT name, latest_score, applied_score_input_revision, applied_policy_revision, "
		"applied_score_template FROM `tabCRM Student` WHERE name = %s FOR UPDATE",
		(student,),
		as_dict=True,
	)
	if not row:
		frappe.throw(_("Student not found."), frappe.DoesNotExistError)
	student_row = row[0]
	idempotency_key = f"{student}:{source_score_input_revision}:{score_template}:{policy_revision}"
	existing = frappe.db.get_value("CRM Score History", {"idempotency_key": idempotency_key}, "name")
	if existing:
		return _response(history=existing, duplicate=True, **_history_result(existing))

	current_tuple = (
		int(student_row.get("applied_score_input_revision") or 0),
		int(student_row.get("applied_policy_revision") or 0),
	)
	incoming_tuple = (source_score_input_revision, policy_revision)
	applied_template = student_row.get("applied_score_template")
	# A NULL stamp is expected for students written before this field was
	# deployed. Treat the first component write as a re-baseline instead of
	# letting an old tuple comparison discard the migrated student's score.
	template_switch = applied_template != score_template
	if incoming_tuple <= current_tuple and not template_switch:
		applied_history = frappe.db.get_value(
			"CRM Score History",
			{
				"student": student,
				"source_score_input_revision": current_tuple[0],
				"policy_revision": current_tuple[1],
			},
			"name",
			order_by="scoring_time desc, creation desc",
		)
		return _response(
			stale=True,
			**_history_result(applied_history),
			current_revision=current_tuple[0],
			current_policy_revision=current_tuple[1],
		)

	if component_values is None:
		stored_final = final_score
		stored_decay = time_decay_score
		stored_change = score_change
		stored_fit = fit_score
		stored_engagement = engagement_score
		stored_intent = intent_score
		stored_negative = negative_score
	else:
		stored_final = final_score
		stored_decay = time_decay_score
		stored_change = stored_final - (flt(student_row.get("latest_score")) or 0.0)
		stored_fit = component_values["fit"]
		stored_engagement = component_values["engagement"]
		stored_intent = component_values["intent"]
		stored_negative = component_values["negative"]

	payload = {
		"doctype": "CRM Score History",
		"student": student,
		"score_template": score_template,
		"source_score_input_revision": source_score_input_revision,
		"policy_revision": policy_revision,
		"policy_hash": policy_hash,
		"idempotency_key": idempotency_key,
		"scoring_time": scoring_time or now_datetime().strftime("%Y-%m-%d %H:%M:%S"),
		"fit_score": stored_fit,
		"engagement_score": stored_engagement,
		"intent_score": stored_intent,
		"time_decay_score": stored_decay,
		"negative_score": stored_negative,
		"final_score": stored_final,
		"score_change": stored_change,
		"details": details,
	}
	if triggered_by_doctype:
		payload["triggered_by_doctype"] = triggered_by_doctype
		payload["triggered_by"] = triggered_by
	history = frappe.get_doc(payload).insert(ignore_permissions=True, ignore_links=True)

	student_values = {
		"latest_score": stored_final,
		"applied_score_input_revision": source_score_input_revision,
		"applied_policy_revision": policy_revision,
		"applied_score_template": score_template,
	}
	frappe.db.set_value("CRM Student", student, student_values, update_modified=False)

	if component_values is not None:
		_write_drift(
			student=student,
			expected_final_score=expected_final_score,
			final_score=stored_final,
			expected_time_decay_factor=expected_time_decay_factor,
			time_decay_factor=stored_decay,
			expected_days_since=expected_days_since,
			days_since=days_since,
			score_template=score_template,
			policy_revision=policy_revision,
			scoring_time=payload["scoring_time"],
		)
	return _response(
		history=history.name,
		applied=True,
		final_score=stored_final,
		score_change=stored_change,
		time_decay_score=stored_decay,
	)


def append_local_fixture_score(**values) -> dict:
	"""Write a score for the fixed local seed without impersonating crm-agents."""
	if not _fixture_score_site_allowed():
		frappe.throw(
			_("Local fixture scoring is only available to Administrator on crm.localhost."),
			frappe.PermissionError,
		)
	previous_flag = getattr(frappe.flags, "crm_local_fixture_score_write", False)
	frappe.flags.crm_local_fixture_score_write = True
	try:
		return append_score_if_current(**values)
	finally:
		frappe.flags.crm_local_fixture_score_write = previous_flag
