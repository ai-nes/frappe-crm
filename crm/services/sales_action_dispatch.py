"""Fenced, send-time reauthorization for controlled Actions."""

from __future__ import annotations

import hashlib
import json

import frappe
from frappe.utils import now_datetime

from crm.services.sales_action_policy import validate_action_command


def _json_object(value) -> dict:
	"""Normalize a Frappe JSON field before using it as a Python mapping."""
	if isinstance(value, str):
		value = frappe.parse_json(value) if value else {}
	return value if isinstance(value, dict) else {}


CALL_PACKAGE_FIELDS = {
	"objective", "opening", "questions", "talking_points", "objections", "desired_outcome", "next_step"
}
EMAIL_PACKAGE_FIELDS = {"template_version", "recipient_ref", "subject", "body", "cta"}
EDITABLE_WORDING_FIELDS = {
	"CALL": CALL_PACKAGE_FIELDS - {"objective"},
	"EMAIL": {"subject", "body", "cta"},
}


def _validate_text(value, field: str, *, max_length: int = 4000) -> None:
	if not isinstance(value, str) or not value.strip() or len(value) > max_length:
		raise ValueError(f"{field} must be a non-empty string of at most {max_length} characters")


def _validate_text_list(value, field: str) -> None:
	if not isinstance(value, list) or len(value) > 50 or any(not isinstance(item, str) or not item.strip() for item in value):
		raise ValueError(f"{field} must be a list of non-empty strings")


def validate_execution_package(action_type: str, package: dict) -> None:
	"""Validate a discriminated, versioned package; unknown types fail closed."""
	if action_type not in {"CALL", "EMAIL"}:
		raise ValueError(f"No execution package is available for {action_type or 'unknown'}")
	if not isinstance(package, dict):
		raise ValueError("Execution package must be an object")
	fields = CALL_PACKAGE_FIELDS if action_type == "CALL" else EMAIL_PACKAGE_FIELDS
	extra = sorted(set(package) - fields)
	missing = sorted(fields - set(package))
	if extra:
		raise ValueError(f"{action_type} package contains unsupported fields: {', '.join(extra)}")
	if missing:
		raise ValueError(f"{action_type} package is missing: {', '.join(missing)}")
	for field, value in package.items():
		if field in {"questions", "talking_points", "objections"}:
			_validate_text_list(value, field)
		else:
			_validate_text(value, field, max_length=12000 if field == "body" else 4000)


def render_initial_package(task) -> dict:
	"""Render a Frappe-owned package from a bounded generation seed."""
	seed = _json_object(task.package_seed)
	action_code = task.get("action") or task.action_type
	if action_code == "CALL":
		return {
			"objective": task.objective,
			"opening": seed.get("opening") or task.objective,
			"questions": seed.get("questions", []),
			"talking_points": seed.get("talking_points", []),
			"objections": seed.get("objections", []),
			"desired_outcome": seed.get("desired_outcome") or task.objective,
			"next_step": seed.get("next_step") or "Record the governed outcome in Frappe.",
		}
	if action_code in {"EMAIL", "SEND_EMAIL"}:
		return {
			"template_version": seed.get("template_version") or "EmailPackageV1",
			"recipient_ref": seed.get("recipient_ref") or "Frappe-resolved",
			"subject": seed.get("subject") or task.objective,
			"body": seed.get("body") or task.objective,
			"cta": seed.get("cta") or "Reply through the Frappe task command.",
		}
	return seed


def persist_initial_package(task) -> dict:
	package = render_initial_package(task)
	action_code = task.get("action") or task.action_type
	validate_execution_package("EMAIL" if action_code == "SEND_EMAIL" else action_code, package)
	revision = int(task.execution_package_version or 0) + 1
	frappe.get_doc(
		{
			"doctype": "CRM Action Revision",
			"action": task.name,
			"revision": revision,
			"package_type": "CallScriptV1"
			if action_code == "CALL"
			else "EmailPackageV1"
			if action_code in {"EMAIL", "SEND_EMAIL"}
			else "Generic",
			"package": package,
			"author": frappe.session.user,
			"reason": "generated",
			"created_at": now_datetime(),
		}
	).insert(ignore_permissions=True)
	return package


def _current_consent_is_valid(task, channel: str | None = None) -> bool:
	if task.get("student") and frappe.db.get_value("CRM Student", task.student, "privacy_status") == "opted_out":
		return False
	if task.get("contact") and frappe.db.get_value("CRM Contact", task.contact, "is_opted_out"):
		return False
	if channel:
		from crm.services.outreach_consent import current_outreach_consent_allows

		if not current_outreach_consent_allows(
			student=task.get("student"), action_contact=task.get("contact"), channel=channel
		):
			return False
	return True


def edit_action_package(
	task_name: str, expected_action_revision: int, expected_package_revision: int, changes: dict, reason: str
) -> dict:
	"""Atomically apply only server-declared wording changes to CALL/EMAIL."""
	if not isinstance(changes, dict):
		frappe.throw("Wording changes must be an object.", frappe.ValidationError)
	task = frappe.get_doc("CRM Action Item", task_name)
	if not task.has_permission("write"):
		frappe.throw("Action is outside the actor's Student scope.", frappe.PermissionError)
	frappe.db.sql("select name from `tabCRM Action Item` where name = %s for update", task.name)
	task.reload()
	action_code = task.get("action") or task.action_type
	if (action_code not in EDITABLE_WORDING_FIELDS and action_code != "SEND_EMAIL") or task.state not in {"accepted", "in-progress"} or task.current_slot != "CURRENT":
		frappe.throw("This Action is not editable in the current state.", frappe.ValidationError)
	if int(task.action_revision or 1) != int(expected_action_revision) or int(task.execution_package_version or 0) != int(expected_package_revision):
		frappe.throw("Action or package changed; refresh before editing.", frappe.ValidationError, title="STALE_REVISION")
	if not reason or len(reason) > 500:
		frappe.throw("An edit reason is required.", frappe.ValidationError)
	if not _current_consent_is_valid(task):
		frappe.throw("Current consent no longer permits this action.", frappe.PermissionError, title="CONSENT_REQUIRED")
	from crm.services.sales_action_policy import allowed_operations, validate_action_command
	edit_operation = next(item for item in allowed_operations(task, actor_roles=set(frappe.get_roles(frappe.session.user))) if item["operation"] == "EDIT")
	if edit_operation["state"] != "allowed":
		frappe.throw("Action edit is not currently permitted.", frappe.PermissionError)
	current = _json_object(task.package_seed)
	if task.execution_package_version:
		rows = frappe.get_all("CRM Action Revision", filters={"action": task.name, "revision": int(task.execution_package_version)}, fields=["package"], limit_page_length=1)
		if rows:
			current = _json_object(rows[0].package)
	package = {**current, **changes}
	policy_code = "EMAIL" if action_code == "SEND_EMAIL" else action_code
	validate_execution_package(policy_code, package)
	validate_action_command(policy_code, student=task.student, inputs={"objective": task.objective, "package": package}, actor_roles=set(frappe.get_roles(frappe.session.user)))
	new_revision = int(expected_package_revision) + 1
	frappe.get_doc(
		{
			"doctype": "CRM Action Revision",
			"action": task.name,
			"revision": new_revision,
			"package_type": "EmailPackageV1",
			"package": package,
			"author": frappe.session.user,
			"reason": reason,
			"created_at": now_datetime(),
		}
	).insert(ignore_permissions=True)
	# `db.set_value` bypasses the controller, so the Frappe-owned risk tier is
	# re-derived here in the same write -- a package edit must never leave a
	# stale tier the client could have influenced. The tier is monotonic: an
	# edit may raise it but never lower it.
	from crm.fcrm.student_decision import compute_risk_tier, max_risk_tier

	new_tier = max_risk_tier(task.get("risk_tier"), compute_risk_tier(action_code, package))
	previous_flag = getattr(frappe.flags, "crm_action_command", False)
	frappe.flags.crm_action_command = True
	try:
		frappe.db.set_value(
			"CRM Action Item",
			task.name,
			{
				"package_seed": package,
				"execution_package_version": new_revision,
				"risk_tier": new_tier,
			},
			update_modified=False,
		)
	finally:
		frappe.flags.crm_action_command = previous_flag
	return {"action": task.name, "action_revision": int(task.action_revision or 1), "package_revision": new_revision, "package": package}


def edit_email_package(task_name: str, expected_revision: int, package: dict, reason: str) -> dict:
	"""Compatibility wrapper; legacy callers are constrained to wording fields."""
	return edit_action_package(task_name, expected_action_revision=int(expected_revision), expected_package_revision=int(expected_revision), changes=package, reason=reason)


def queue_dispatch(action: str, *, package_revision: int, channel: str, inputs: dict) -> dict:
	"""Re-read Action/policy/authority and create one durable dispatch fence."""
	action_row = frappe.get_doc("CRM Action Item", action)
	if action_row.state not in {"accepted", "in-progress"} or action_row.requires_review:
		frappe.throw("Action is not dispatchable until reviewed/resumed.", frappe.ValidationError)
	action_code = action_row.get("action") or action_row.action_type
	if action_code == "HANDOFF":
		frappe.throw("HANDOFF has no dispatch path.", frappe.ValidationError)
	package = _json_object(action_row.package_seed)
	policy_code = "EMAIL" if action_code == "SEND_EMAIL" else action_code
	validate_execution_package(policy_code, package)
	validate_action_command(
		policy_code,
		student=action_row.student,
		inputs={**inputs, "objective": action_row.objective, "package": package, "contact": action_row.get("contact"), "channel": channel},
		actor_roles=set(frappe.get_roles(frappe.session.user)),
	)
	if not _current_consent_is_valid(action_row, channel):
		frappe.throw("Current consent no longer permits this channel or recipient.", frappe.PermissionError, title="CONSENT_REQUIRED")
	provider_key = hashlib.sha256(f"{action_row.name}:{package_revision}:{channel}".encode()).hexdigest()
	existing = frappe.db.get_value("CRM Student Dispatch Receipt", {"provider_key": provider_key}, "name")
	if existing:
		return {"receipt": existing, "idempotent": True}
	receipt = frappe.get_doc(
		{
			"doctype": "CRM Student Dispatch Receipt",
			"action": action_row.name,
			"package_revision": package_revision,
			"channel": channel,
			"provider_key": provider_key,
			"fence": str(action_row.modified),
			"status": "queued",
			"created_at": now_datetime(),
		}
	).insert(ignore_permissions=True)
	return {"receipt": receipt.name, "provider_key": provider_key, "idempotent": False}
