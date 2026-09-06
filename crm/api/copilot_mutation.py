"""Named, audited CRM mutation boundary for the isolated Copilot demo."""

from __future__ import annotations

import json
import uuid

import frappe
from frappe import _

from crm.api.session import resolve_copilot_profile

_CONFIG_KEY = "crm_agents_demo_full_access"
_PROTECTED_DOCTYPES = frozenset({
	"CRM AI Capability Grant", "CRM Agent Event", "CRM Copilot Audit Event",
	"CRM Student Command Receipt", "CRM Student Decision Event",
})
_PROTECTED_FIELDS = frozenset({
	"doctype", "name", "owner", "creation", "modified", "modified_by", "idx", "docstatus",
})


def _enabled() -> bool:
	return frappe.conf.get(_CONFIG_KEY) in (1, "1", True, "true", "True")


def _require_demo_user() -> None:
	if frappe.session.user in ("", "Guest") or not _enabled():
		frappe.throw(_("Copilot demo mutations are disabled."), frappe.PermissionError)
	if resolve_copilot_profile(frappe.get_roles(frappe.session.user)) not in {"Sale", "Marketing", "Lead Sale", "Admissions Director"}:
		frappe.throw(_("Only a canonical CRM Copilot role may mutate CRM demo data."), frappe.PermissionError)


def _audit(*, operation: str, doctype: str, name: str | None, values: dict, proposal_id: str | None, status: str, error: str | None = None) -> str:
	event_id = f"COPILOT-{uuid.uuid4().hex}"
	frappe.get_doc({
		"doctype": "CRM Copilot Audit Event",
		"event_id": event_id,
		"event_type": "crm_mutation",
		"operation": operation,
		"target_doctype": doctype,
		"target_name": name,
		"changed_fields": json.dumps(sorted(values)),
		"requested_values": json.dumps(values, default=str),
		"actor": frappe.session.user,
		"proposal_id": proposal_id,
		"status": status,
		"error_code": error,
	}).insert(ignore_permissions=True)
	return event_id


@frappe.whitelist(methods=["POST"])
def apply(operation: str, doctype: str, name: str | None = None, values: dict | None = None, proposal_id: str | None = None):
	"""Apply one approved CRM mutation as the authenticated Frappe user."""
	_require_demo_user()
	if not isinstance(doctype, str) or not doctype.startswith("CRM ") or doctype in _PROTECTED_DOCTYPES:
		frappe.throw(_("This DocType is not available to Copilot demo mutations."), frappe.PermissionError)
	if operation not in {"insert", "update", "delete"}:
		frappe.throw(_("Unsupported CRM mutation."), frappe.ValidationError)
	if isinstance(values, str):
		values = frappe.parse_json(values)
	values = values or {}
	if not isinstance(values, dict) or set(values) & _PROTECTED_FIELDS:
		frappe.throw(_("Protected CRM fields cannot be changed by Copilot."), frappe.PermissionError)
	try:
		if operation == "insert":
			doc = frappe.get_doc({"doctype": doctype, **values})
			doc.insert(ignore_permissions=True)
			name = doc.name
		elif operation == "update":
			if not name:
				frappe.throw(_("A record name is required."), frappe.ValidationError)
			doc = frappe.get_doc(doctype, name)
			for field, value in values.items():
				doc.set(field, value)
			doc.save(ignore_permissions=True)
		else:
			if not name:
				frappe.throw(_("A record name is required."), frappe.ValidationError)
			frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
		audit_id = _audit(operation=operation, doctype=doctype, name=name, values=values, proposal_id=proposal_id, status="succeeded")
		return {"status": "succeeded", "operation": operation, "doctype": doctype, "name": name, "audit_id": audit_id, "actor": frappe.session.user}
	except (frappe.ValidationError, frappe.PermissionError, frappe.DoesNotExistError, frappe.DuplicateEntryError) as exc:
		# Expected, caller-actionable failures: return a structured result at
		# HTTP 200 so the agent can surface a reason and let the user
		# re-propose, instead of a bare HTTP 417. Roll back any partial write
		# from a failed save/delete FIRST (this function now returns normally,
		# so the request would otherwise commit), then record the failed audit.
		frappe.db.rollback()
		audit_id = _audit(operation=operation, doctype=doctype, name=name, values=values, proposal_id=proposal_id, status="failed", error=type(exc).__name__)
		return {
			"status": "failed", "operation": operation, "doctype": doctype, "name": name,
			"error_code": type(exc).__name__, "message": str(exc), "audit_id": audit_id,
		}
	except Exception as exc:
		_audit(operation=operation, doctype=doctype, name=name, values=values, proposal_id=proposal_id, status="failed", error=type(exc).__name__)
		raise
