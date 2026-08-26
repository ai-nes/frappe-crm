"""Transactional score-write command -- the only mutation path for a V2
score calculation result.

Replaces the old REST create-CRM-Score-History + PATCH-CRM-Student two-step
(non-atomic, no ordering guarantee) with a single locked, idempotent,
compare-and-swap write. Ordering/CAS uses only the total-order tuple
`(source_score_input_revision, policy_revision)`; `policy_hash` is recorded
for provenance/audit and never participates in the comparison.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import now_datetime


def _require_agent_identity():
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication is required."), frappe.PermissionError)
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
) -> dict:
	"""Append one CRM Score History row and update the current score
	projection, only if the incoming (revision, policy_revision) tuple is
	strictly newer than the tuple currently applied for this Student.

	Returns `{"duplicate": True}` for a retried identical tuple (existing
	history row, no new write) and `{"stale": True}` for a tuple that is not
	newer than what is already applied (silently accepted as settled, per the
	plan's "stale CAS is non-retryable" rule -- this is not an error, since a
	newer or concurrent calculation has already won).
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

	idempotency_key = f"{student}:{source_score_input_revision}:{policy_revision}"
	existing = frappe.db.get_value("CRM Score History", {"idempotency_key": idempotency_key}, "name")
	if existing:
		return {"history": existing, "applied": False, "duplicate": True, "stale": False}

	current_tuple = (
		int(row[0].applied_score_input_revision or 0),
		int(row[0].applied_policy_revision or 0),
	)
	incoming_tuple = (source_score_input_revision, policy_revision)
	if incoming_tuple <= current_tuple:
		return {"history": None, "applied": False, "duplicate": False, "stale": True}

	payload = {
		"doctype": "CRM Score History",
		"student": student,
		"score_template": score_template,
		"source_score_input_revision": source_score_input_revision,
		"policy_revision": policy_revision,
		"policy_hash": policy_hash,
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
	history = frappe.get_doc(payload).insert(ignore_permissions=True)

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
	return {"history": history.name, "applied": True, "duplicate": False, "stale": False}
