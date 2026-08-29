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


def validate_execution_package(action_type: str, package: dict) -> None:
	if action_type == "CALL":
		required = {
			"objective",
			"opening",
			"questions",
			"talking_points",
			"objections",
			"desired_outcome",
			"next_step",
		}
		missing = sorted(required.difference(package))
		if missing:
			raise ValueError(f"Call Script is missing: {', '.join(missing)}")
	if action_type == "EMAIL":
		required = {"template_version", "recipient_ref", "subject", "body", "cta"}
		missing = sorted(required.difference(package))
		if missing:
			raise ValueError(f"Email Package is missing: {', '.join(missing)}")


def render_initial_package(task) -> dict:
	"""Render a Frappe-owned package from a bounded generation seed."""
	seed = _json_object(task.package_seed)
	if task.action_type == "CALL":
		return {
			"objective": task.objective,
			"opening": seed.get("opening") or task.objective,
			"questions": seed.get("questions", []),
			"talking_points": seed.get("talking_points", []),
			"objections": seed.get("objections", []),
			"desired_outcome": seed.get("desired_outcome") or task.objective,
			"next_step": seed.get("next_step") or "Record the governed outcome in Frappe.",
		}
	if task.action_type == "EMAIL":
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
	validate_execution_package(task.action_type, package)
	revision = int(task.execution_package_version or 0) + 1
	frappe.get_doc(
		{
			"doctype": "CRM Action Revision",
			"action": task.name,
			"revision": revision,
			"package_type": "CallScriptV1"
			if task.action_type == "CALL"
			else "EmailPackageV1"
			if task.action_type == "EMAIL"
			else "Generic",
			"package": package,
			"author": frappe.session.user,
			"reason": "generated",
			"created_at": now_datetime(),
		}
	).insert(ignore_permissions=True)
	return package


def edit_email_package(task_name: str, expected_revision: int, package: dict, reason: str) -> dict:
	task = frappe.get_doc("CRM Action", task_name)
	if not task.has_permission("write"):
		frappe.throw("Action is outside the actor's Student scope.", frappe.PermissionError)
	if task.action_type != "EMAIL" or task.state not in {"accepted", "in-progress"}:
		frappe.throw("Only an accepted/in-progress EMAIL Action can be edited.", frappe.ValidationError)
	if int(task.execution_package_version or 0) != int(expected_revision):
		frappe.throw("Email package changed; refresh before editing.", frappe.ValidationError)
	if not reason or len(reason) > 500:
		frappe.throw("An edit reason is required.", frappe.ValidationError)
	validate_execution_package("EMAIL", package)
	new_revision = int(expected_revision) + 1
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
	frappe.flags.crm_action_command = True
	frappe.db.set_value(
		"CRM Action",
		task.name,
		{"package_seed": package, "execution_package_version": new_revision},
		update_modified=False,
	)
	frappe.flags.crm_action_command = False
	return {"action": task.name, "package_revision": new_revision, "package": package}


def queue_dispatch(action: str, *, package_revision: int, channel: str, inputs: dict) -> dict:
	"""Re-read Action/policy/authority and create one durable dispatch fence."""
	action_row = frappe.get_doc("CRM Action", action)
	if action_row.state not in {"accepted", "in-progress"} or action_row.requires_review:
		frappe.throw("Action is not dispatchable until reviewed/resumed.", frappe.ValidationError)
	package = _json_object(inputs.get("package") or action_row.package_seed)
	validate_execution_package(action_row.action_type, package)
	validate_action_command(
		action_row.action_type,
		student=action_row.student,
		inputs={**inputs, "objective": action_row.objective, "package": package},
		actor_roles=set(frappe.get_roles(frappe.session.user)),
	)
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
