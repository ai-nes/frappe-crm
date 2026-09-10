"""Admin lifecycle and service catalog APIs for Frappe-owned CRM Rules."""

from __future__ import annotations

import json

import frappe
from frappe import _

from crm.fcrm.rule_engine import active_rule_catalog, fact_metadata
from crm.fcrm.role_policy import BUSINESS_ADMIN_ROLE

ADMIN_ROLES = frozenset({BUSINESS_ADMIN_ROLE, "Admissions Director", "System Manager"})
RULE_FIELDS = [
	"name",
	"rule_id",
	"rule_group",
	"rule_name",
	"description",
	"feature_scope",
	"rule_type",
	"gate_outcome",
	"priority",
	"action",
	"target_actions",
	"condition",
	"status",
	"enabled",
	"revision",
	"schema_version",
	"published_at",
	"published_by",
	"archive_reason",
	"modified",
]
WRITABLE_FIELDS = {
	"rule_id",
	"rule_group",
	"rule_name",
	"description",
	"feature_scope",
	"rule_type",
	"gate_outcome",
	"priority",
	"action",
	"target_actions",
	"condition",
}


def _require_admin() -> None:
	if frappe.session.user == "Administrator" or ADMIN_ROLES.intersection(frappe.get_roles()):
		return
	frappe.throw(_("Only a Business Admin may manage CRM Rules."), frappe.PermissionError)


def _require_agent_identity() -> None:
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication is required."), frappe.PermissionError)
	if frappe.session.user == "Administrator":
		return
	configured = frappe.conf.get("crm_agents_service_user")
	if not configured or frappe.session.user != configured:
		frappe.throw(
			_("This endpoint is restricted to the crm-agents service identity."),
			frappe.PermissionError,
		)


def _payload(doc, *, include_admin_fields: bool = True) -> dict:
	row = doc.as_dict() if hasattr(doc, "as_dict") else dict(doc)
	target_actions = _json_field(row.get("target_actions"), [])
	condition = _json_field(row.get("condition"), {})
	payload = {
		"name": row.get("name"),
		"rule_id": row.get("rule_id"),
		"rule_group": row.get("rule_group"),
		"rule_name": row.get("rule_name"),
		"description": row.get("description") or "",
		"feature_scope": row.get("feature_scope"),
		"rule_type": row.get("rule_type"),
		"gate_outcome": row.get("gate_outcome"),
		"priority": int(row.get("priority") or 0),
		"action": row.get("action"),
		"target_actions": target_actions,
		"condition": condition,
		"status": row.get("status") or "draft",
		"enabled": _as_bool(row.get("enabled")),
		"revision": int(row.get("revision") or 0),
		"schema_version": row.get("schema_version") or "crm-rule-v1",
	}
	if include_admin_fields:
		payload.update(
			{
				"published_at": row.get("published_at"),
				"published_by": row.get("published_by"),
				"archive_reason": row.get("archive_reason"),
				"modified": row.get("modified"),
			}
		)
	return payload


def _json_field(value, default):
	if value in (None, ""):
		return default
	if isinstance(value, str):
		try:
			return json.loads(value)
		except (TypeError, ValueError):
			return default
	return value


def _as_bool(value) -> bool:
	if isinstance(value, str):
		return value.strip().lower() in {"1", "true", "yes", "on"}
	return bool(value)


def _get_rule(name: str, permission_type: str = "read"):
	doc = frappe.get_doc("CRM Rule", name)
	doc.check_permission(permission_type)
	return doc


def _set_writable_fields(doc, values: dict) -> None:
	for fieldname in WRITABLE_FIELDS:
		if fieldname in values:
			doc.set(fieldname, values[fieldname])


def _lock_rule(name: str):
	rows = frappe.db.sql(
		"SELECT name FROM `tabCRM Rule` WHERE name = %s FOR UPDATE",
		(name,),
		as_dict=True,
	)
	if not rows:
		frappe.throw(_("CRM Rule {0} does not exist.").format(name), frappe.DoesNotExistError)
	return _get_rule(name, "write")


@frappe.whitelist()
def list_rules(
	feature_scope: str | None = None,
	status: str | None = None,
	start: int = 0,
	page_length: int = 50,
):
	"""List rules for the Frappe Desk/admin integration."""
	_require_admin()
	filters = {}
	if feature_scope:
		filters["feature_scope"] = feature_scope
	if status:
		filters["status"] = status
	rows = frappe.get_list(
		"CRM Rule",
		filters=filters,
		fields=RULE_FIELDS,
		start=max(int(start or 0), 0),
		page_length=min(max(int(page_length or 50), 1), 200),
		order_by="priority desc, rule_id asc",
	)
	return {"rules": [_payload(row) for row in rows]}


@frappe.whitelist()
def get_rule(name: str) -> dict:
	_require_admin()
	return _payload(_get_rule(name))


@frappe.whitelist(methods=["POST"])
def create_rule(**values) -> dict:
	_require_admin()
	doc = frappe.new_doc("CRM Rule")
	_set_writable_fields(doc, values)
	doc.status = "draft"
	doc.enabled = 0
	doc.revision = 0
	doc.insert()
	return _payload(doc)


@frappe.whitelist(methods=["POST", "PUT"])
def update_rule(name: str, **values) -> dict:
	_require_admin()
	doc = _get_rule(name, "write")
	if "rule_id" in values and str(values["rule_id"]).strip().upper() != doc.rule_id:
		frappe.throw(_("CRM Rule ID cannot be changed after creation."), frappe.ValidationError)
	values.pop("rule_id", None)
	if doc.status in {"published", "archived"}:
		doc.status = "draft"
		doc.enabled = 0
		doc.published_at = None
		doc.published_by = None
		doc.archive_reason = None
	_set_writable_fields(doc, values)
	previous = getattr(frappe.flags, "crm_rule_lifecycle", False)
	frappe.flags.crm_rule_lifecycle = True
	try:
		doc.save()
	finally:
		frappe.flags.crm_rule_lifecycle = previous
	return _payload(doc)


@frappe.whitelist(methods=["POST"])
def reopen_rule(name: str) -> dict:
	"""Move a published/archived rule back to draft for controlled editing."""
	_require_admin()
	doc = _get_rule(name, "write")
	if doc.status == "draft":
		return _payload(doc)
	doc.status = "draft"
	doc.enabled = 0
	doc.published_at = None
	doc.published_by = None
	doc.archive_reason = None
	previous = getattr(frappe.flags, "crm_rule_lifecycle", False)
	frappe.flags.crm_rule_lifecycle = True
	try:
		doc.save()
	finally:
		frappe.flags.crm_rule_lifecycle = previous
	return _payload(doc)


@frappe.whitelist(methods=["POST"])
def publish_rule(name: str, expected_revision: int | str | None = None) -> dict:
	_require_admin()
	doc = _lock_rule(name)
	if doc.status == "archived":
		frappe.throw(_("Archived CRM Rules must be edited before publishing again."), frappe.ValidationError)
	if expected_revision in (None, ""):
		frappe.throw(_("expected_revision is required when publishing a CRM Rule."), frappe.ValidationError)
	try:
		expected_revision = int(expected_revision)
	except (TypeError, ValueError):
		frappe.throw(_("expected_revision must be an integer."), frappe.ValidationError)
	if expected_revision != int(doc.revision or 0):
		frappe.throw(_("CRM Rule has changed. Reload it before publishing."), frappe.ValidationError)
	doc.status = "published"
	doc.enabled = 1
	doc.revision = int(doc.revision or 0) + 1
	doc.published_at = frappe.utils.now_datetime()
	doc.published_by = frappe.session.user
	doc.archive_reason = None
	previous = {
		"lifecycle": getattr(frappe.flags, "crm_rule_lifecycle", False),
		"publish": getattr(frappe.flags, "crm_rule_publish", False),
	}
	frappe.flags.crm_rule_lifecycle = True
	frappe.flags.crm_rule_publish = True
	try:
		doc.save()
	finally:
		frappe.flags.crm_rule_lifecycle = previous["lifecycle"]
		frappe.flags.crm_rule_publish = previous["publish"]
	return _payload(doc)


@frappe.whitelist(methods=["POST"])
def archive_rule(name: str, reason: str | None = None) -> dict:
	_require_admin()
	doc = _lock_rule(name)
	if doc.status == "archived":
		return _payload(doc)
	doc.status = "archived"
	doc.enabled = 0
	doc.archive_reason = str(reason or "Archived by Business Admin").strip()[:2000]
	previous = {
		"lifecycle": getattr(frappe.flags, "crm_rule_lifecycle", False),
		"archive": getattr(frappe.flags, "crm_rule_archive", False),
	}
	frappe.flags.crm_rule_lifecycle = True
	frappe.flags.crm_rule_archive = True
	try:
		doc.save()
	finally:
		frappe.flags.crm_rule_lifecycle = previous["lifecycle"]
		frappe.flags.crm_rule_archive = previous["archive"]
	return _payload(doc)


@frappe.whitelist()
def list_fact_catalog() -> dict:
	_require_admin()
	return {"schema_version": "crm-rule-v1", "facts": fact_metadata()}


@frappe.whitelist()
def get_active_rule_catalog(feature_scope: str | None = None) -> dict:
	"""Return the published catalog consumed by ``ai-crm``."""
	_require_agent_identity()
	if feature_scope and feature_scope not in {"all", "intent", "student_360", "scoring", "nba", "copilot"}:
		frappe.throw(_("Unsupported feature scope."), frappe.ValidationError)
	rows = frappe.get_all(
		"CRM Rule",
		filters={"status": "published", "enabled": 1},
		fields=[
			"rule_id",
			"rule_group",
			"rule_name",
			"description",
			"feature_scope",
			"rule_type",
			"gate_outcome",
			"priority",
			"action",
			"target_actions",
			"condition",
			"revision",
			"schema_version",
		],
		limit_page_length=1000,
		order_by="priority desc, rule_id asc",
	)
	return active_rule_catalog(rows, feature_scope=feature_scope)
