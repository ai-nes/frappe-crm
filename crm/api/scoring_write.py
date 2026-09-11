"""Transactional score-write command -- the only mutation path for a V2
score calculation result.

Replaces the old REST create-CRM-Score-History + PATCH-CRM-Student two-step
(non-atomic, no ordering guarantee) with a single locked, idempotent,
compare-and-swap write. Ordering/CAS uses only the total-order tuple
`(source_score_input_revision, policy_revision)`; `policy_hash` and the
creation-time ruleset identity are recorded for provenance/audit and never
participate in the comparison.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import now_datetime

from crm.services.score_revision import (
	RULESET_IDENTITY_FIELDS,
	normalize_score_ruleset_identity,
	score_input_ruleset_identity,
)


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
	if getattr(frappe.flags, "crm_local_fixture_score_write", False):
		if _fixture_score_site_allowed():
			return
		frappe.throw(_("Local fixture scoring is only available to Administrator on crm.localhost."), frappe.PermissionError)
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication is required."), frappe.PermissionError)
	if frappe.session.user == "Administrator":
		return
	configured = frappe.conf.get("crm_agents_service_user")
	if not configured or frappe.session.user != configured:
		frappe.throw(
			_("This command is restricted to the crm-agents service identity."), frappe.PermissionError
		)


@frappe.whitelist()
def append_score_if_current(
	student: str,
	source_score_input_revision: int,
	policy_revision: int,
	policy_hash: str,
	score_template: str,
	scoring_time: str,
	fit_score: float,
	engagement_score: float,
	intent_score: float,
	time_decay_score: float,
	negative_score: float,
	final_score: float,
	score_change: float,
	details: list | str | None = None,
	triggered_by_doctype: str = "",
	triggered_by: str = "",
	rule_version: str | None = None,
	rule_version_digest: str | None = None,
	ruleset_digest: str | None = None,
) -> dict:
	"""Append one CRM Score History row and update the current score
	projection, only if the incoming (revision, policy_revision) tuple is
	strictly newer than the tuple currently applied for this Student.

	Returns `{"duplicate": True}` for a retried identical tuple (existing
	history row, no new write) and `{"stale": True}` for a tuple that is not
	newer than what is already applied (silently accepted as settled, per the
	plan's "stale CAS is non-retryable" rule -- this is not an error, since a
	newer or concurrent calculation has already won). Stale responses also
	include the applied score-input and policy revisions so the caller can
	observe which tuple won the CAS comparison.
	"""
	_require_agent_identity()
	if isinstance(details, str):
		details = frappe.parse_json(details) or []
	details = details or []
	source_score_input_revision = int(source_score_input_revision)
	policy_revision = int(policy_revision)
	if source_score_input_revision < 0 or policy_revision < 0:
		frappe.throw(_("Invalid revision."), frappe.ValidationError)

	row = frappe.db.sql(
		"SELECT name, applied_score_input_revision, applied_policy_revision "
		"FROM `tabCRM Student` WHERE name = %s FOR UPDATE",
		(student,),
		as_dict=True,
	)
	if not row:
		frappe.throw(_("Student not found."), frappe.DoesNotExistError)
	try:
		ruleset_identity = score_input_ruleset_identity(
			student,
			source_score_input_revision,
			supplied={
				"rule_version": rule_version,
				"rule_version_digest": rule_version_digest,
				"ruleset_digest": ruleset_digest,
			},
			require_supplied=True,
		)
	except ValueError as exc:
		frappe.throw(str(exc), frappe.ValidationError)

	idempotency_key = f"{student}:{source_score_input_revision}:{policy_revision}"
	existing = frappe.db.get_value(
		"CRM Score History",
		{"idempotency_key": idempotency_key},
		["name", *RULESET_IDENTITY_FIELDS],
		as_dict=True,
	)
	if existing:
		try:
			existing_identity = normalize_score_ruleset_identity(
				{field: existing.get(field) for field in RULESET_IDENTITY_FIELDS},
				allow_empty=True,
			)
		except ValueError as exc:
			frappe.throw(str(exc), frappe.ValidationError)
		if existing_identity != ruleset_identity:
			frappe.throw(
				_("Score History ruleset identity does not match the CAS request."),
				frappe.ValidationError,
			)
		return {
			"history": existing.name,
			"applied": False,
			"duplicate": True,
			"stale": False,
			**ruleset_identity,
		}

	current_tuple = (
		int(row[0].applied_score_input_revision or 0),
		int(row[0].applied_policy_revision or 0),
	)
	incoming_tuple = (source_score_input_revision, policy_revision)
	if incoming_tuple <= current_tuple:
		return {
			"history": None,
			"applied": False,
			"duplicate": False,
			"stale": True,
			"current_revision": current_tuple[0],
			"current_policy_revision": current_tuple[1],
			**ruleset_identity,
		}

	payload = {
		"doctype": "CRM Score History",
		"student": student,
		"score_template": score_template,
		"source_score_input_revision": source_score_input_revision,
		"policy_revision": policy_revision,
		"policy_hash": policy_hash,
		**ruleset_identity,
		"idempotency_key": idempotency_key,
		"scoring_time": scoring_time or now_datetime().strftime("%Y-%m-%d %H:%M:%S"),
		"fit_score": fit_score,
		"engagement_score": engagement_score,
		"intent_score": intent_score,
		"time_decay_score": time_decay_score,
		"negative_score": negative_score,
		"final_score": final_score,
		"score_change": score_change,
		"details": details,
	}
	if triggered_by_doctype:
		payload["triggered_by_doctype"] = triggered_by_doctype
		payload["triggered_by"] = triggered_by
	# The Student row is locked and verified above. Its just-created HS name can
	# still be absent from Frappe's Link cache within this transaction.
	history = frappe.get_doc(payload).insert(ignore_permissions=True, ignore_links=True)

	frappe.db.set_value(
		"CRM Student",
		student,
		{
			"latest_score": final_score,
			"applied_score_input_revision": source_score_input_revision,
			"applied_policy_revision": policy_revision,
		},
		update_modified=False,
	)
	return {
		"history": history.name,
		"applied": True,
		"duplicate": False,
		"stale": False,
		**ruleset_identity,
	}


def append_local_fixture_score(**values) -> dict:
	"""Write a score for the fixed local seed without impersonating crm-agents."""
	if not _fixture_score_site_allowed():
		frappe.throw(_("Local fixture scoring is only available to Administrator on crm.localhost."), frappe.PermissionError)
	previous_flag = getattr(frappe.flags, "crm_local_fixture_score_write", False)
	frappe.flags.crm_local_fixture_score_write = True
	try:
		return append_score_if_current(**values)
	finally:
		frappe.flags.crm_local_fixture_score_write = previous_flag
