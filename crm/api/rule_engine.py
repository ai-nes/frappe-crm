"""Admin and service APIs for the versioned Frappe-owned CRM Rule registry."""

from __future__ import annotations

import json

import frappe
from frappe import _

from crm.fcrm.rule_engine import (
	FEATURE_SCOPES,
	STATUSES,
	active_rule_catalog,
	fact_metadata,
	normalize_rule_data,
)
from crm.fcrm.rule_engine import normalize_rule_version_data

ADMIN_ROLES = frozenset({"Business Admin", "Admissions Director", "System Manager"})
VERSION_FIELDS = [
	"name",
	"version_id",
	"version_name",
	"description",
	"status",
	"is_active",
	"revision",
	"schema_version",
	"ruleset_revision",
	"ruleset_digest",
	"published_at",
	"published_by",
	"archive_reason",
	"modified",
]
RULE_FIELDS = [
	"name",
	"rule_version",
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
RULE_WRITABLE_FIELDS = {
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
MAX_PAGE_LENGTH = 200
MAX_CATALOG_RULES = 1000


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


def _as_bool(value) -> bool:
	if isinstance(value, str):
		return value.strip().lower() in {"1", "true", "yes", "on"}
	return bool(value)


def _as_int(value, fieldname: str, *, minimum: int = 0, maximum: int = 1000000) -> int:
	try:
		result = int(value)
	except (TypeError, ValueError):
		frappe.throw(_("{0} must be an integer.").format(fieldname), frappe.ValidationError)
	if result < minimum or result > maximum:
		frappe.throw(
			_("{0} must be between {1} and {2}.").format(fieldname, minimum, maximum),
			frappe.ValidationError,
		)
	return result


def _expected_revision(value, fieldname: str = "expected_revision") -> int:
	if value in (None, ""):
		frappe.throw(_("{0} is required.").format(fieldname), frappe.ValidationError)
	return _as_int(value, fieldname)


def _json_field(value, default):
	if value in (None, ""):
		return default
	if isinstance(value, str):
		try:
			return json.loads(value)
		except (TypeError, ValueError):
			return default
	return value


def _resolve_version_name(value: str) -> str:
	version_id = str(value or "").strip().upper()
	if not version_id:
		frappe.throw(_("version_id is required."), frappe.ValidationError)
	if frappe.db.exists("CRM Rule Version", version_id):
		return version_id
	name = frappe.db.get_value("CRM Rule Version", {"version_id": version_id}, "name")
	if name:
		return name
	frappe.throw(_("CRM Rule Version {0} does not exist.").format(version_id), frappe.DoesNotExistError)


def _get_version(name: str, permission_type: str = "read"):
	doc = frappe.get_doc("CRM Rule Version", name)
	doc.check_permission(permission_type)
	return doc


def _lock_all_versions() -> None:
	frappe.db.sql("SELECT name FROM `tabCRM Rule Version` ORDER BY name FOR UPDATE")


def _lock_version(name: str, permission_type: str = "read"):
	name = _resolve_version_name(name)
	rows = frappe.db.sql(
		"SELECT name FROM `tabCRM Rule Version` WHERE name = %s FOR UPDATE",
		(name,),
		as_dict=True,
	)
	if not rows:
		frappe.throw(_("CRM Rule Version {0} does not exist.").format(name), frappe.DoesNotExistError)
	return _get_version(name, permission_type)


def _assert_draft(version) -> None:
	if version.status != "draft" or version.is_active:
		frappe.throw(
			_("Only an inactive draft CRM Rule Version can be changed."),
			frappe.PermissionError,
		)


def _assert_expected_version(version, expected_revision) -> None:
	expected = _expected_revision(expected_revision, "expected_version_revision")
	if expected != int(version.revision or 0):
		frappe.throw(
			_("STALE_RULE_VERSION: the version changed. Reload it before retrying."),
			frappe.ValidationError,
		)


def _bump_version(version) -> None:
	frappe.db.set_value(
		"CRM Rule Version",
		version.name,
		"revision",
		int(version.revision or 0) + 1,
		update_modified=True,
	)


def _version_payload(row, rules_count: int | None = None) -> dict:
	as_dict = getattr(row, "as_dict", None)
	data = as_dict() if callable(as_dict) else dict(row)
	payload = {
		"name": data.get("name"),
		"version_id": data.get("version_id"),
		"version_name": data.get("version_name") or "",
		"description": data.get("description") or "",
		"status": data.get("status") or "draft",
		"is_active": _as_bool(data.get("is_active")),
		"revision": int(data.get("revision") or 0),
		"schema_version": data.get("schema_version") or "crm-rule-v1",
		"ruleset_revision": data.get("ruleset_revision"),
		"ruleset_digest": data.get("ruleset_digest"),
		"published_at": data.get("published_at"),
		"published_by": data.get("published_by"),
		"archive_reason": data.get("archive_reason"),
		"modified": data.get("modified"),
	}
	if rules_count is not None:
		payload["rules_count"] = rules_count
	return payload


def _rule_payload(row) -> dict:
	as_dict = getattr(row, "as_dict", None)
	data = as_dict() if callable(as_dict) else dict(row)
	return {
		"name": data.get("name"),
		"version_id": data.get("rule_version"),
		"rule_version": data.get("rule_version"),
		"rule_id": data.get("rule_id"),
		"rule_group": data.get("rule_group"),
		"rule_name": data.get("rule_name"),
		"description": data.get("description") or "",
		"feature_scope": data.get("feature_scope"),
		"rule_type": data.get("rule_type"),
		"gate_outcome": data.get("gate_outcome"),
		"priority": int(data.get("priority") or 0),
		"action": data.get("action"),
		"target_actions": _json_field(data.get("target_actions"), []),
		"condition": _json_field(data.get("condition"), {}),
		"status": data.get("status") or "draft",
		"enabled": _as_bool(data.get("enabled")),
		"revision": int(data.get("revision") or 0),
		"schema_version": data.get("schema_version") or "crm-rule-v1",
		"published_at": data.get("published_at"),
		"published_by": data.get("published_by"),
		"archive_reason": data.get("archive_reason"),
		"modified": data.get("modified"),
	}


def _group_summaries(version_name: str) -> list[dict]:
	rows = frappe.get_all(
		"CRM Rule",
		filters={"rule_version": version_name},
		fields=["rule_group"],
		limit_page_length=MAX_CATALOG_RULES,
	)
	counts = {}
	for row in rows:
		group_id = str(row.rule_group or "").strip().upper()
		if group_id:
			counts[group_id] = counts.get(group_id, 0) + 1
	return [
		{"group_id": group_id, "label": group_id, "count": count}
		for group_id, count in sorted(counts.items())
	]


@frappe.whitelist()
def list_rule_versions(
	status: str | None = None,
	active_only: bool | str = False,
	start: int = 0,
	page_length: int = 50,
) -> dict:
	_require_admin()
	if status and status.strip().lower() not in STATUSES:
		frappe.throw(_("Unsupported CRM Rule Version status."), frappe.ValidationError)
	start = _as_int(start or 0, "start", maximum=1000000)
	page_length = _as_int(page_length or 50, "page_length", minimum=1, maximum=MAX_PAGE_LENGTH)
	filters = {}
	if status:
		filters["status"] = status.strip().lower()
	if _as_bool(active_only):
		filters["is_active"] = 1
	rows = frappe.get_list(
		"CRM Rule Version",
		filters=filters,
		fields=VERSION_FIELDS,
		start=start,
		page_length=page_length,
		order_by="modified desc, version_id asc",
	)
	total = frappe.db.count("CRM Rule Version", filters=filters)
	return {
		"versions": [
			_version_payload(row, frappe.db.count("CRM Rule", {"rule_version": row.name})) for row in rows
		],
		"total": total,
		"start": start,
		"page_length": page_length,
	}


@frappe.whitelist()
def get_rule_version(name: str) -> dict:
	_require_admin()
	version = _get_version(_resolve_version_name(name))
	payload = _version_payload(version, frappe.db.count("CRM Rule", {"rule_version": version.name}))
	payload["groups"] = _group_summaries(version.name)
	return payload


@frappe.whitelist(methods=["POST"])
def create_rule_version(version_id: str, version_name: str, description: str | None = None) -> dict:
	_require_admin()
	try:
		data = normalize_rule_version_data(
			{
				"version_id": version_id,
				"version_name": version_name,
				"description": description,
				"status": "draft",
				"is_active": 0,
				"revision": 0,
			}
		)
	except ValueError as exc:
		frappe.throw(str(exc), frappe.ValidationError)
	if frappe.db.exists("CRM Rule Version", data["version_id"]):
		frappe.throw(_("CRM Rule Version already exists."), frappe.DuplicateEntryError)
	doc = frappe.new_doc("CRM Rule Version")
	doc.update(data)
	doc.insert(ignore_permissions=True)
	return _version_payload(doc, 0)


@frappe.whitelist(methods=["PUT", "POST"])
def update_rule_version(
	name: str,
	expected_revision: int | str | None = None,
	version_name: str | None = None,
	description: str | None = None,
) -> dict:
	_require_admin()
	version = _lock_version(name)
	_assert_expected_version(version, expected_revision)
	_assert_draft(version)
	if version_name is not None:
		version.version_name = version_name
	if description is not None:
		version.description = description
	try:
		normalized = normalize_rule_version_data(
			{
				"version_id": version.version_id,
				"version_name": version.version_name,
				"description": version.description,
				"status": "draft",
				"is_active": 0,
				"revision": version.revision,
			}
		)
	except ValueError as exc:
		frappe.throw(str(exc), frappe.ValidationError)
	version.version_name = normalized["version_name"]
	version.description = normalized["description"]
	version.revision = int(version.revision or 0) + 1
	version.save(ignore_permissions=True)
	return _version_payload(version, frappe.db.count("CRM Rule", {"rule_version": version.name}))


@frappe.whitelist(methods=["POST"])
def clone_rule_version(
	source_name: str,
	version_id: str,
	version_name: str | None = None,
	description: str | None = None,
) -> dict:
	_require_admin()
	source = _get_version(_resolve_version_name(source_name))
	rows = frappe.get_all(
		"CRM Rule",
		filters={"rule_version": source.name},
		fields=RULE_FIELDS,
		limit_page_length=MAX_CATALOG_RULES,
		order_by="priority desc, rule_id asc",
	)
	if not rows:
		frappe.throw(
			_("An empty CRM Rule Version cannot be cloned."),
			frappe.ValidationError,
		)
	try:
		version_data = normalize_rule_version_data(
			{
				"version_id": version_id,
				"version_name": version_name or f"Copy of {source.version_name}",
				"description": description if description is not None else source.description,
				"status": "draft",
				"is_active": 0,
				"revision": 0,
			}
		)
	except ValueError as exc:
		frappe.throw(str(exc), frappe.ValidationError)
	if frappe.db.exists("CRM Rule Version", version_data["version_id"]):
		frappe.throw(_("CRM Rule Version already exists."), frappe.DuplicateEntryError)
	new_version = frappe.new_doc("CRM Rule Version")
	new_version.update(version_data)
	new_version.insert(ignore_permissions=True)
	try:
		for row in rows:
			row_data = dict(row)
			rule = frappe.new_doc("CRM Rule")
			rule.rule_version = new_version.name
			for fieldname in RULE_WRITABLE_FIELDS:
				value = row_data.get(fieldname)
				if fieldname == "target_actions":
					value = _json_field(value, [])
				elif fieldname == "condition":
					value = _json_field(value, {})
				rule.set(fieldname, value)
			rule.status = "draft"
			rule.enabled = 0
			rule.revision = 0
			rule.insert(ignore_permissions=True)
	except Exception:
		frappe.db.rollback()
		raise
	return _version_payload(new_version, len(rows))


@frappe.whitelist()
def list_rule_groups(version_name: str) -> dict:
	_require_admin()
	version = _get_version(_resolve_version_name(version_name))
	return {"version_id": version.version_id, "groups": _group_summaries(version.name)}


@frappe.whitelist()
def list_rules(
	version_name: str | None = None,
	rule_group: str | None = None,
	search: str | None = None,
	status: str | None = None,
	start: int = 0,
	page_length: int = 50,
	feature_scope: str | None = None,
) -> dict:
	_require_admin()
	if feature_scope and feature_scope.strip().lower() not in FEATURE_SCOPES:
		frappe.throw(_("Unsupported feature scope."), frappe.ValidationError)
	if status and status.strip().lower() not in STATUSES:
		frappe.throw(_("Unsupported CRM Rule status."), frappe.ValidationError)
	start = _as_int(start or 0, "start", maximum=1000000)
	page_length = _as_int(page_length or 50, "page_length", minimum=1, maximum=MAX_PAGE_LENGTH)
	filters = {}
	if version_name:
		filters["rule_version"] = _resolve_version_name(version_name)
	if rule_group:
		filters["rule_group"] = rule_group.strip().upper()
	if status:
		filters["status"] = status.strip().lower()
	if feature_scope:
		filters["feature_scope"] = feature_scope.strip().lower()
	rows = frappe.get_all(
		"CRM Rule",
		filters=filters,
		fields=RULE_FIELDS,
		limit_page_length=MAX_CATALOG_RULES,
		order_by="priority desc, rule_group asc, rule_id asc",
	)
	query = str(search or "").strip().lower()
	if query:
		rows = [
			row
			for row in rows
			if query in str(row.rule_id or "").lower()
			or query in str(row.rule_name or "").lower()
			or query in str(row.rule_group or "").lower()
		]
	total = len(rows)
	rows = rows[start : start + page_length]
	return {
		"rules": [_rule_payload(row) for row in rows],
		"total": total,
		"start": start,
		"page_length": page_length,
	}


@frappe.whitelist()
def get_rule(name: str) -> dict:
	_require_admin()
	doc = frappe.get_doc("CRM Rule", name)
	doc.check_permission("read")
	return _rule_payload(doc)


def _set_rule_writable_fields(doc, values: dict) -> None:
	for fieldname in RULE_WRITABLE_FIELDS:
		if fieldname in values:
			doc.set(fieldname, values[fieldname])


@frappe.whitelist(methods=["POST"])
def create_rule(version_name: str, expected_version_revision: int | str, **values) -> dict:
	_require_admin()
	version = _lock_version(version_name)
	_assert_expected_version(version, expected_version_revision)
	_assert_draft(version)
	doc = frappe.new_doc("CRM Rule")
	doc.rule_version = version.name
	_set_rule_writable_fields(doc, values)
	doc.status = "draft"
	doc.enabled = 0
	doc.revision = 0
	doc.insert(ignore_permissions=True)
	_bump_version(version)
	return _rule_payload(doc)


@frappe.whitelist(methods=["POST", "PUT"])
def update_rule(
	name: str,
	expected_version_revision: int | str,
	**values,
) -> dict:
	_require_admin()
	doc = frappe.get_doc("CRM Rule", name)
	version = _lock_version(doc.rule_version)
	_assert_expected_version(version, expected_version_revision)
	_assert_draft(version)
	if "rule_id" in values and str(values["rule_id"]).strip().upper() != doc.rule_id:
		frappe.throw(_("CRM Rule ID cannot be changed after creation."), frappe.ValidationError)
	values.pop("rule_id", None)
	_set_rule_writable_fields(doc, values)
	doc.save(ignore_permissions=True)
	_bump_version(version)
	return _rule_payload(doc)


@frappe.whitelist(methods=["DELETE", "POST"])
def delete_draft_rule(name: str, expected_version_revision: int | str) -> dict:
	_require_admin()
	doc = frappe.get_doc("CRM Rule", name)
	version = _lock_version(doc.rule_version)
	_assert_expected_version(version, expected_version_revision)
	_assert_draft(version)
	if doc.status != "draft":
		frappe.throw(_("Only draft CRM Rules can be deleted."), frappe.PermissionError)
	doc.delete(ignore_permissions=True)
	_bump_version(version)
	return {"name": name, "deleted": True, "version_id": version.version_id}


@frappe.whitelist(methods=["POST"])
def publish_rule_version(name: str, expected_revision: int | str) -> dict:
	_require_admin()
	name = _resolve_version_name(name)
	_lock_all_versions()
	version = _get_version(name)
	_assert_expected_version(version, expected_revision)
	_assert_draft(version)
	rows = frappe.get_all(
		"CRM Rule",
		filters={"rule_version": version.name},
		fields=RULE_FIELDS,
		limit_page_length=MAX_CATALOG_RULES,
		order_by="priority desc, rule_group asc, rule_id asc",
	)
	if not rows:
		frappe.throw(
			_("A CRM Rule Version must contain at least one rule before it can be published."),
			frappe.ValidationError,
		)
	published_rows = []
	for row in rows:
		data = dict(row)
		data["status"] = "published"
		data["enabled"] = 1
		data["revision"] = int(row.revision or 0) + 1
		normalize_rule_data(data)
		published_rows.append(data)
	metadata = active_rule_catalog(published_rows)
	new_revision = int(version.revision or 0) + 1
	ruleset_revision = f"crm-rule-set-{version.version_id}-r{new_revision}-{metadata['ruleset_digest'][:12]}"
	now = frappe.utils.now_datetime()
	for row in rows:
		frappe.db.set_value(
			"CRM Rule",
			row.name,
			{
				"status": "published",
				"enabled": 1,
				"revision": int(row.revision or 0) + 1,
				"published_at": now,
				"published_by": frappe.session.user,
				"archive_reason": None,
			},
			update_modified=False,
		)
	for old in frappe.get_all(
		"CRM Rule Version",
		filters={"is_active": 1, "name": ["!=", version.name]},
		pluck="name",
		limit_page_length=MAX_CATALOG_RULES,
	):
		frappe.db.set_value("CRM Rule Version", old, "is_active", 0, update_modified=False)
	frappe.db.set_value(
		"CRM Rule Version",
		version.name,
		{
			"status": "published",
			"is_active": 1,
			"revision": new_revision,
			"ruleset_revision": ruleset_revision,
			"ruleset_digest": metadata["ruleset_digest"],
			"published_at": now,
			"published_by": frappe.session.user,
			"archive_reason": None,
		},
		update_modified=True,
	)
	return _version_payload(_get_version(version.name), len(rows))


@frappe.whitelist(methods=["POST"])
def archive_rule_version(
	name: str,
	expected_revision: int | str,
	reason: str | None = None,
) -> dict:
	_require_admin()
	version = _lock_version(name)
	_assert_expected_version(version, expected_revision)
	if version.is_active:
		frappe.throw(_("The active CRM Rule Version cannot be archived."), frappe.PermissionError)
	if version.status == "archived":
		return _version_payload(version, frappe.db.count("CRM Rule", {"rule_version": version.name}))
	if version.status not in {"draft", "published"}:
		frappe.throw(_("CRM Rule Version status is invalid."), frappe.ValidationError)
	new_revision = int(version.revision or 0) + 1
	archive_reason = str(reason or "Archived by Business Admin").strip()[:2000]
	for rule_name in frappe.get_all(
		"CRM Rule", filters={"rule_version": version.name}, pluck="name", limit_page_length=MAX_CATALOG_RULES
	):
		frappe.db.set_value(
			"CRM Rule",
			rule_name,
			{"status": "archived", "enabled": 0, "archive_reason": archive_reason},
			update_modified=False,
		)
	frappe.db.set_value(
		"CRM Rule Version",
		version.name,
		{
			"status": "archived",
			"is_active": 0,
			"revision": new_revision,
			"archive_reason": archive_reason,
		},
		update_modified=True,
	)
	return _version_payload(_get_version(version.name), frappe.db.count("CRM Rule", {"rule_version": version.name}))


@frappe.whitelist()
def list_fact_catalog() -> dict:
	_require_admin()
	return {"schema_version": "crm-rule-v1", "facts": fact_metadata()}


@frappe.whitelist()
def get_active_rule_catalog(feature_scope: str | None = None) -> dict:
	"""Return only the catalog from the one published active version."""
	_require_agent_identity()
	feature_scope = feature_scope.strip().lower() if feature_scope else None
	if feature_scope and feature_scope not in FEATURE_SCOPES:
		frappe.throw(_("Unsupported feature scope."), frappe.ValidationError)
	if not frappe.db.exists("DocType", "CRM Rule Version"):
		return active_rule_catalog([], feature_scope=feature_scope)
	active_versions = frappe.get_all(
		"CRM Rule Version",
		filters={"is_active": 1, "status": "published"},
		fields=VERSION_FIELDS,
		limit_page_length=2,
		order_by="modified desc, name asc",
	)
	if len(active_versions) != 1:
		return active_rule_catalog([], feature_scope=feature_scope)
	version = active_versions[0]
	rows = frappe.get_all(
		"CRM Rule",
		filters={"rule_version": version.name, "status": "published", "enabled": 1},
		fields=RULE_FIELDS,
		limit_page_length=MAX_CATALOG_RULES,
		order_by="priority desc, rule_group asc, rule_id asc",
	)
	return active_rule_catalog(
		rows,
		feature_scope=feature_scope,
		metadata={
			"version_id": version.version_id,
			"version_name": version.version_name,
			"ruleset_revision": version.ruleset_revision,
			"ruleset_digest": version.ruleset_digest,
		},
	)
