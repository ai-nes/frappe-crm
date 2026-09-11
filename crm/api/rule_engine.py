"""Admin and service APIs for the Frappe-owned CRM Rule control plane."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from contextlib import contextmanager
from copy import deepcopy

import frappe
from frappe import _

from crm.fcrm.rule_engine import (
	CATALOG_SCHEMA,
	MAX_GROUPS,
	MAX_RULES,
	STATUSES,
	catalog_from_rows,
	fact_descriptors,
	normalize_feature_scope,
	normalize_group_catalog,
	normalize_rule_data,
	normalize_rule_version_data,
)

SETTINGS_NAME = "CRM Rule Settings"
MAX_PAGE_LENGTH = 200
HEX_DIGEST = re.compile(r"^[a-f0-9]{64}$")
VERSION_FIELDS = [
	"name",
	"owner",
	"version_id",
	"version_name",
	"description",
	"status",
	"group_catalog",
	"revision",
	"schema_version",
	"ruleset_revision",
	"ruleset_digest",
	"activated_at",
	"activated_by",
	"superseded_at",
	"superseded_by",
	"change_note",
	"modified",
]
RULE_FIELDS = [
	"name",
	"rule_version",
	"group_code",
	"rule_id",
	"rule_name",
	"description",
	"feature",
	"rule_type",
	"outcome",
	"precedence",
	"unknown_policy",
	"reason_code",
	"business_reason_template",
	"target_actions",
	"conditions",
	"status",
	"enabled",
	"revision",
	"schema_version",
	"modified",
]


def _require_admin() -> None:
	if frappe.session.user == "Administrator":
		return
	frappe.throw(_("Only Administrator may manage CRM Rules."), frappe.PermissionError)


def _require_service_identity() -> None:
	configured = frappe.conf.get("crm_agents_service_user")
	if frappe.session.user == "Administrator":
		return
	if frappe.session.user == "Guest" or not configured or frappe.session.user != configured:
		frappe.throw(
			_("This endpoint is restricted to the configured crm-agents service identity."),
			frappe.PermissionError,
		)


def _as_bool(value) -> bool:
	if isinstance(value, str):
		return value.strip().lower() in {"1", "true", "yes", "on"}
	return bool(value)


def _as_int(value, fieldname: str, *, minimum: int = 0, maximum: int = 1000000) -> int:
	if isinstance(value, bool):
		frappe.throw(_("{0} must be an integer.").format(fieldname), frappe.ValidationError)
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


def _expected_revision(value, fieldname: str) -> int:
	if value in (None, ""):
		frappe.throw(_("{0} is required.").format(fieldname), frappe.ValidationError)
	return _as_int(value, fieldname)


def _json_field(value, fieldname: str, default=None):
	if value in (None, ""):
		return deepcopy(default)
	if isinstance(value, str):
		try:
			return json.loads(value)
		except (TypeError, ValueError):
			frappe.throw(_("{0} must be valid JSON.").format(fieldname), frappe.ValidationError)
	return deepcopy(value)


def _throw_value_error(exc: ValueError) -> None:
	frappe.throw(str(exc), frappe.ValidationError)


@contextmanager
def _flag(name: str):
	previous = getattr(frappe.flags, name, None)
	setattr(frappe.flags, name, True)
	try:
		yield
	finally:
		if previous is None:
			try:
				delattr(frappe.flags, name)
			except AttributeError:
				setattr(frappe.flags, name, False)
		else:
			setattr(frappe.flags, name, previous)


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


def _get_settings(*, create: bool, permission_type: str = "read"):
	# Single DocTypes are stored in tabSingles, not in a tabCRM Rule Settings
	# table.  Read the raw rows first so a fresh site can distinguish an
	# uninitialized singleton from one whose pointer is intentionally empty.
	existing = frappe.db.get_singles_dict(SETTINGS_NAME, cast=True)
	if not existing and not create:
		frappe.throw(_("CRM Rule Settings has no active rule pointer."), frappe.DoesNotExistError)
	settings = frappe.get_single(SETTINGS_NAME)
	settings.check_permission(permission_type)
	if not existing:
		settings.pointer_revision = 0
		with _flag("crm_rule_settings_lifecycle"):
			settings.save(ignore_permissions=True)
	return settings


def _lock_settings():
	_get_settings(create=True, permission_type="read")
	# ``for_update`` is handled by BaseDocument through get_singles_dict for a
	# Single DocType, locking the singleton rows used by the activation CAS.
	return frappe.get_doc("CRM Rule Settings", SETTINGS_NAME, for_update=True)


def _assert_expected_version(version, expected_revision) -> None:
	expected = _expected_revision(expected_revision, "expected_version_revision")
	if expected != int(version.revision or 0):
		frappe.throw(
			_("STALE_RULE_VERSION: the version changed. Reload it before retrying."),
			frappe.ValidationError,
		)


def _assert_expected_settings(settings, expected_revision) -> None:
	expected = _expected_revision(expected_revision, "expected_settings_revision")
	if expected != int(settings.pointer_revision or 0):
		frappe.throw(
			_("STALE_RULE_SETTINGS: the active pointer changed. Reload it before retrying."),
			frappe.ValidationError,
		)


def _assert_draft(version) -> None:
	if str(version.status or "").strip().lower() != "draft":
		frappe.throw(
			_("Only a draft CRM Rule Version can be changed. Clone an immutable snapshot first."),
			frappe.PermissionError,
		)


def _version_groups(version) -> list[dict]:
	try:
		return normalize_group_catalog(version.get("group_catalog"))
	except ValueError as exc:
		_throw_value_error(exc)
	return []


def _rule_rows(version_name: str, *, order_by: str = "precedence desc, group_code asc, rule_id asc"):
	total = frappe.db.count("CRM Rule", {"rule_version": version_name})
	if total > MAX_RULES:
		frappe.throw(
			_("CRM Rule Version contains {0} rules; the maximum complete snapshot is {1}.").format(
				total, MAX_RULES
			),
			frappe.ValidationError,
		)
	return frappe.get_all(
		"CRM Rule",
		filters={"rule_version": version_name},
		fields=RULE_FIELDS,
		limit_page_length=MAX_RULES,
		order_by=order_by,
	)


def _version_payload(row, rules_count: int | None = None) -> dict:
	as_dict = getattr(row, "as_dict", None)
	data = as_dict() if callable(as_dict) else dict(row)
	payload = {
		"name": data.get("name"),
		"owner": data.get("owner"),
		"version_id": data.get("version_id"),
		"version_name": data.get("version_name") or "",
		"description": data.get("description") or "",
		"status": data.get("status") or "draft",
		"group_catalog": _json_field(data.get("group_catalog"), "group_catalog", []),
		"revision": int(data.get("revision") or 0),
		"schema_version": data.get("schema_version") or CATALOG_SCHEMA,
		"ruleset_revision": data.get("ruleset_revision"),
		"ruleset_digest": data.get("ruleset_digest"),
		"activated_at": data.get("activated_at"),
		"activated_by": data.get("activated_by"),
		"superseded_at": data.get("superseded_at"),
		"superseded_by": data.get("superseded_by"),
		"change_note": data.get("change_note"),
		"modified": data.get("modified"),
	}
	if rules_count is not None:
		payload["rules_count"] = rules_count
	return payload


def _rule_payload(row) -> dict:
	as_dict = getattr(row, "as_dict", None)
	data = as_dict() if callable(as_dict) else dict(row)
	try:
		normalized = normalize_rule_data(data)
	except ValueError as exc:
		_throw_value_error(exc)
	return {
		"name": data.get("name"),
		"version_id": normalized["rule_version"],
		"rule_version": normalized["rule_version"],
		"rule_id": normalized["rule_id"],
		"group_code": normalized["group_code"],
		"rule_name": normalized["name"],
		"description": normalized["description"],
		"feature": normalized["feature"],
		"rule_type": normalized["rule_type"],
		"outcome": normalized["outcome"],
		"precedence": normalized["precedence"],
		"unknown_policy": normalized["unknown_policy"],
		"reason_code": normalized["reason_code"],
		"business_reason_template": normalized["business_reason_template"],
		"target_actions": normalized["target_actions"],
		"conditions": normalized["conditions"],
		"status": normalized["status"],
		"enabled": normalized["enabled"],
		"revision": normalized["revision"],
		"schema_version": normalized["schema_version"],
		"modified": data.get("modified"),
	}


def _group_payloads(version) -> list[dict]:
	groups = _version_groups(version)
	counts = {}
	for row in frappe.get_all(
		"CRM Rule",
		filters={"rule_version": version.name},
		fields=["group_code"],
		limit_page_length=MAX_RULES,
	):
		code = str(row.group_code or "").strip().lower()
		if code:
			counts[code] = counts.get(code, 0) + 1
	return [
		{**group, "rule_count": counts.get(group["code"], 0)}
		for group in groups
	]


def _version_wire_catalog(version, *, require_stored_digest: bool = True) -> dict:
	rows = _rule_rows(version.name)
	if str(version.status).lower() not in {"active", "superseded"}:
		frappe.throw(_("Only Active or Superseded versions have immutable catalogs."), frappe.PermissionError)
	if any(str(row.status or "").lower() != str(version.status).lower() for row in rows):
		frappe.throw(_("Rule status does not match its immutable version."), frappe.ValidationError)
	try:
		catalog = catalog_from_rows(
			rows,
			version_id=version.version_id,
			technical_revision=int(version.revision or 0),
			group_catalog=version.group_catalog,
		)
	except ValueError as exc:
		_throw_value_error(exc)
	if require_stored_digest:
		stored_digest = str(version.ruleset_digest or "")
		if not HEX_DIGEST.fullmatch(stored_digest) or stored_digest != catalog["ruleset_digest"]:
			frappe.throw(_("The stored CRM Rule Version digest is invalid."), frappe.ValidationError)
	return catalog


def active_ruleset_identity() -> dict[str, str]:
	"""Return the current immutable rule identity for in-process producers.

	This helper is intentionally not whitelisted. Interaction/analysis/NBA
	creation happens inside Frappe's authoritative transaction, where the
	producer must pin the same Settings pointer as the service read endpoint
	without impersonating the crm-agents service user.
	"""
	settings = frappe.db.get_singles_dict(SETTINGS_NAME, cast=True)
	if not settings or not settings.active_rule_version or not settings.active_ruleset_digest:
		frappe.throw(
			_("CRM Rule Settings has no complete active snapshot."),
			frappe.ValidationError,
		)
	version = frappe.get_doc("CRM Rule Version", settings.active_rule_version)
	if str(version.status or "").lower() != "active":
		frappe.throw(
			_("CRM Rule Settings points to a non-active snapshot."),
			frappe.ValidationError,
		)
	catalog = _version_wire_catalog(version)
	if catalog["ruleset_digest"] != str(settings.active_ruleset_digest):
		frappe.throw(
			_("CRM Rule Settings pointer digest does not match the version."),
			frappe.ValidationError,
		)
	return {
		"rule_version": str(catalog["rule_version"]),
		# The current wire contract binds both technical identity fields to the
		# complete immutable snapshot digest.
		"rule_version_digest": catalog["ruleset_digest"],
		"ruleset_digest": catalog["ruleset_digest"],
	}


def active_rule_catalog_internal(feature_scope: str | None = None) -> dict:
	"""Read the active snapshot for an authoritative in-process producer.

	This is deliberately not whitelisted.  Delegated users may create a durable
	NBA request after passing Student permission, but they must not receive the
	complete business-rule catalog over the service API.  Frappe-owned request
	assembly can still use the same pointer/digest validation internally.
	"""
	_validate_feature_scope(feature_scope)
	settings = frappe.db.get_singles_dict(SETTINGS_NAME, cast=True)
	if not settings or not settings.active_rule_version or not settings.active_ruleset_digest:
		frappe.throw(
			_("CRM Rule Settings has no complete active snapshot."),
			frappe.ValidationError,
		)
	version = frappe.get_doc("CRM Rule Version", settings.active_rule_version)
	if str(version.status or "").lower() != "active":
		frappe.throw(
			_("CRM Rule Settings points to a non-active snapshot."),
			frappe.ValidationError,
		)
	catalog = _version_wire_catalog(version)
	if catalog["ruleset_digest"] != str(settings.active_ruleset_digest):
		frappe.throw(
			_("CRM Rule Settings pointer digest does not match the version."),
			frappe.ValidationError,
		)
	return catalog


def _assert_pointer_consistent(settings) -> None:
	if not settings.active_rule_version:
		return
	try:
		version = _get_version(settings.active_rule_version, "read")
	except Exception:
		frappe.throw(_("CRM Rule Settings points to a missing version."), frappe.ValidationError)
	if str(version.status or "").lower() != "active":
		frappe.throw(_("CRM Rule Settings points to a non-active version."), frappe.ValidationError)
	if str(settings.active_ruleset_digest or "") != str(version.ruleset_digest or ""):
		frappe.throw(_("CRM Rule Settings pointer digest is inconsistent."), frappe.ValidationError)
	_version_wire_catalog(version)


def _save_draft_version(version, groups: list[dict]) -> None:
	version.group_catalog = groups
	version.revision = int(version.revision or 0) + 1
	version.ruleset_revision = None
	version.ruleset_digest = None
	with _flag("crm_rule_version_authoring"):
		version.save(ignore_permissions=True)


def _ensure_group(version, group_code: str) -> tuple[list[dict], bool]:
	groups = _version_groups(version)
	for group in groups:
		if group["code"] == group_code:
			if not group["enabled"]:
				frappe.throw(_("The referenced rule group is disabled."), frappe.ValidationError)
			return groups, False
	if len(groups) >= MAX_GROUPS:
		frappe.throw(_("A CRM Rule Version cannot contain more than {0} groups.").format(MAX_GROUPS), frappe.ValidationError)
	groups.append(
		{
			"code": group_code,
			"label": group_code.replace("_", " ").title(),
			"enabled": True,
		}
	)
	return groups, True


def _apply_rule_data(doc, data: Mapping) -> None:
	doc.rule_version = data["rule_version"]
	doc.rule_id = data["rule_id"]
	doc.group_code = data["group_code"]
	doc.rule_name = data["name"]
	doc.description = data["description"]
	doc.feature = data["feature"]
	doc.rule_type = data["rule_type"]
	doc.outcome = data["outcome"]
	doc.precedence = data["precedence"]
	doc.unknown_policy = data["unknown_policy"]
	doc.reason_code = data["reason_code"]
	doc.business_reason_template = data["business_reason_template"]
	doc.target_actions = json.dumps(data["target_actions"], ensure_ascii=False)
	doc.conditions = json.dumps(data["conditions"], ensure_ascii=False)
	doc.status = data["status"]
	doc.enabled = int(data["enabled"])
	doc.revision = data["revision"]
	doc.schema_version = data["schema_version"]


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
		filters["status"] = "active"
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
	payload["groups"] = _group_payloads(version)
	return payload


@frappe.whitelist(methods=["POST"])
def create_rule_version(
	version_id: str,
	version_name: str,
	description: str | None = None,
	group_catalog=None,
) -> dict:
	_require_admin()
	try:
		data = normalize_rule_version_data(
			{
				"version_id": version_id,
				"version_name": version_name,
				"description": description,
				"status": "draft",
				"group_catalog": group_catalog,
				"revision": 0,
			}
		)
	except ValueError as exc:
		_throw_value_error(exc)
	if frappe.db.exists("CRM Rule Version", data["version_id"]):
		frappe.throw(_("CRM Rule Version already exists."), frappe.DuplicateEntryError)
	doc = frappe.new_doc("CRM Rule Version")
	doc.update(data)
	with _flag("crm_rule_version_authoring"):
		doc.insert(ignore_permissions=True)
	return _version_payload(doc, 0)


@frappe.whitelist(methods=["PUT", "POST"])
def update_rule_version(
	name: str,
	expected_revision: int | str | None = None,
	version_name: str | None = None,
	description: str | None = None,
	group_catalog=None,
) -> dict:
	_require_admin()
	version = _lock_version(name, "write")
	_assert_expected_version(version, expected_revision)
	_assert_draft(version)
	try:
		data = normalize_rule_version_data(
			{
				"version_id": version.version_id,
				"version_name": version_name if version_name is not None else version.version_name,
				"description": description if description is not None else version.description,
				"status": "draft",
				"group_catalog": group_catalog if group_catalog is not None else version.group_catalog,
				"revision": version.revision,
			}
		)
	except ValueError as exc:
		_throw_value_error(exc)
	version.version_name = data["version_name"]
	version.description = data["description"]
	version.group_catalog = data["group_catalog"]
	version.revision = int(version.revision or 0) + 1
	version.ruleset_revision = None
	version.ruleset_digest = None
	with _flag("crm_rule_version_authoring"):
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
	source = _get_version(_resolve_version_name(source_name), "read")
	groups = _version_groups(source)
	rows = _rule_rows(source.name)
	if str(source.status or "").lower() in {"active", "superseded"}:
		_version_wire_catalog(source)
	elif rows:
		try:
			catalog_from_rows(
				rows,
				version_id=source.version_id,
				technical_revision=int(source.revision or 0),
				group_catalog=groups,
			)
		except ValueError as exc:
			_throw_value_error(exc)
	try:
		version_data = normalize_rule_version_data(
			{
				"version_id": version_id,
				"version_name": version_name or f"Copy of {source.version_name}",
				"description": description if description is not None else source.description,
				"status": "draft",
				"group_catalog": groups,
				"revision": 0,
			}
		)
	except ValueError as exc:
		_throw_value_error(exc)
	if frappe.db.exists("CRM Rule Version", version_data["version_id"]):
		frappe.throw(_("CRM Rule Version already exists."), frappe.DuplicateEntryError)
	new_version = frappe.new_doc("CRM Rule Version")
	new_version.update(version_data)
	with _flag("crm_rule_version_authoring"):
		new_version.insert(ignore_permissions=True)
	try:
		for row in rows:
			try:
				data = normalize_rule_data(dict(row))
			except ValueError as exc:
				_throw_value_error(exc)
			data["rule_version"] = new_version.version_id
			data["status"] = "draft"
			data["revision"] = 0
			rule = frappe.new_doc("CRM Rule")
			_apply_rule_data(rule, data)
			with _flag("crm_rule_authoring"):
				rule.insert(ignore_permissions=True)
	except Exception:
		frappe.db.rollback()
		raise
	return _version_payload(new_version, len(rows))


@frappe.whitelist()
def list_rule_groups(version_name: str) -> dict:
	_require_admin()
	version = _get_version(_resolve_version_name(version_name))
	return {"version_id": version.version_id, "groups": _group_payloads(version)}


@frappe.whitelist(methods=["POST"])
def create_rule_group(
	version_name: str,
	expected_version_revision: int | str,
	code: str,
	label: str,
	enabled: bool | str = True,
	description: str | None = None,
	sort_order: int | str | None = None,
) -> dict:
	_require_admin()
	version = _lock_version(version_name, "write")
	_assert_expected_version(version, expected_version_revision)
	_assert_draft(version)
	try:
		group_value = {"code": code, "label": label, "enabled": _as_bool(enabled)}
		if description is not None:
			group_value["description"] = description
		if sort_order is not None:
			group_value["sort_order"] = _as_int(sort_order, "sort_order", maximum=10000)
		group = normalize_group_catalog([group_value])[0]
		groups = _version_groups(version)
		if any(item["code"] == group["code"] for item in groups):
			frappe.throw(_("Rule group already exists in this version."), frappe.DuplicateEntryError)
		groups.append(group)
	except ValueError as exc:
		_throw_value_error(exc)
	_save_draft_version(version, groups)
	return {"version_id": version.version_id, "group": group, "revision": version.revision}


@frappe.whitelist(methods=["PUT", "POST"])
def update_rule_group(
	version_name: str,
	code: str,
	expected_version_revision: int | str,
	label: str | None = None,
	enabled: bool | str | None = None,
	description: str | None = None,
	sort_order: int | str | None = None,
) -> dict:
	_require_admin()
	version = _lock_version(version_name, "write")
	_assert_expected_version(version, expected_version_revision)
	_assert_draft(version)
	groups = _version_groups(version)
	code = str(code or "").strip().lower()
	group = next((item for item in groups if item["code"] == code), None)
	if group is None:
		frappe.throw(_("Rule group does not exist in this version."), frappe.DoesNotExistError)
	if label is not None or description is not None or sort_order is not None:
		candidate = {
			"code": code,
			"label": label if label is not None else group["label"],
			"enabled": group["enabled"],
		}
		if enabled is not None:
			candidate["enabled"] = _as_bool(enabled)
		if description is not None:
			candidate["description"] = description
		elif "description" in group:
			candidate["description"] = group["description"]
		if sort_order is not None:
			candidate["sort_order"] = _as_int(sort_order, "sort_order", maximum=10000)
		elif "sort_order" in group:
			candidate["sort_order"] = group["sort_order"]
		try:
			group = normalize_group_catalog([candidate])[0]
		except ValueError as exc:
			_throw_value_error(exc)
	else:
		if enabled is not None:
			group["enabled"] = _as_bool(enabled)
	for index, item in enumerate(groups):
		if item["code"] == code:
			groups[index] = group
			break
	_save_draft_version(version, groups)
	return {"version_id": version.version_id, "group": group, "revision": version.revision}


@frappe.whitelist(methods=["DELETE", "POST"])
def delete_rule_group(version_name: str, code: str, expected_version_revision: int | str) -> dict:
	_require_admin()
	version = _lock_version(version_name, "write")
	_assert_expected_version(version, expected_version_revision)
	_assert_draft(version)
	code = str(code or "").strip().lower()
	groups = _version_groups(version)
	if not any(item["code"] == code for item in groups):
		frappe.throw(_("Rule group does not exist in this version."), frappe.DoesNotExistError)
	if frappe.db.count("CRM Rule", {"rule_version": version.name, "group_code": code}):
		frappe.throw(_("A rule still references this group."), frappe.ValidationError)
	_save_draft_version(version, [item for item in groups if item["code"] != code])
	return {"version_id": version.version_id, "code": code, "deleted": True, "revision": version.revision}


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
	feature_scope = _validate_feature_scope(feature_scope)
	if status and status.strip().lower() not in STATUSES:
		frappe.throw(_("Unsupported CRM Rule status."), frappe.ValidationError)
	start = _as_int(start or 0, "start", maximum=1000000)
	page_length = _as_int(page_length or 50, "page_length", minimum=1, maximum=MAX_PAGE_LENGTH)
	filters = {}
	if version_name:
		filters["rule_version"] = _resolve_version_name(version_name)
	if rule_group:
		filters["group_code"] = rule_group.strip().lower()
	if status:
		filters["status"] = status.strip().lower()
	rows = frappe.get_all(
		"CRM Rule",
		filters=filters,
		fields=RULE_FIELDS,
		limit_page_length=MAX_RULES,
		order_by="precedence desc, group_code asc, rule_id asc",
	)
	if feature_scope and feature_scope != "all":
		rows = [
			row
			for row in rows
			if _rule_payload(row)["feature"] in {feature_scope, "all"}
		]
	query = str(search or "").strip().lower()
	if query:
		rows = [
			row
			for row in rows
			if query in str(row.rule_id or "").lower()
			or query in str(row.rule_name or "").lower()
			or query in str(row.group_code or "").lower()
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


def _rule_input_from_doc(doc) -> dict:
	data = doc.as_dict()
	data.setdefault("rule_version", doc.rule_version)
	return data


@frappe.whitelist(methods=["POST"])
def create_rule(version_name: str, expected_version_revision: int | str, **values) -> dict:
	_require_admin()
	version = _lock_version(version_name, "write")
	_assert_expected_version(version, expected_version_revision)
	_assert_draft(version)
	values.setdefault("enabled", True)
	try:
		data = normalize_rule_data({**values, "rule_version": version.version_id, "status": "draft", "revision": 0})
	except ValueError as exc:
		_throw_value_error(exc)
	groups, added_group = _ensure_group(version, data["group_code"])
	if added_group:
		_save_draft_version(version, groups)
	doc = frappe.new_doc("CRM Rule")
	_apply_rule_data(doc, data)
	with _flag("crm_rule_authoring"):
		doc.insert(ignore_permissions=True)
	if not added_group:
		_save_draft_version(version, groups)
	return _rule_payload(doc)


@frappe.whitelist(methods=["POST", "PUT"])
def update_rule(name: str, expected_version_revision: int | str, **values) -> dict:
	_require_admin()
	doc = frappe.get_doc("CRM Rule", name)
	version = _lock_version(doc.rule_version, "write")
	_assert_expected_version(version, expected_version_revision)
	_assert_draft(version)
	current = _rule_input_from_doc(doc)
	if "rule_id" in values and str(values["rule_id"]).strip().upper() != str(doc.rule_id).upper():
		frappe.throw(_("CRM Rule ID cannot be changed after creation."), frappe.ValidationError)
	values.pop("rule_id", None)
	current.update(values)
	current["rule_version"] = version.version_id
	current["status"] = "draft"
	current["revision"] = int(doc.revision or 0)
	try:
		data = normalize_rule_data(current)
	except ValueError as exc:
		_throw_value_error(exc)
	groups, added_group = _ensure_group(version, data["group_code"])
	if added_group:
		_save_draft_version(version, groups)
	_apply_rule_data(doc, data)
	# The admin command is the only authoring seam. Keep the same flag active
	# for the ORM save so the immutable-document guard does not mistake this
	# intentional update for a direct edit.
	previous = getattr(frappe.flags, "crm_rule_authoring", None)
	frappe.flags.crm_rule_authoring = True
	try:
		doc.save(ignore_permissions=True)
	finally:
		if previous is None:
			try:
				delattr(frappe.flags, "crm_rule_authoring")
			except AttributeError:
				pass
		else:
			frappe.flags.crm_rule_authoring = previous
	if not added_group:
		_save_draft_version(version, groups)
	return _rule_payload(doc)


@frappe.whitelist(methods=["DELETE", "POST"])
def delete_draft_rule(name: str, expected_version_revision: int | str) -> dict:
	_require_admin()
	doc = frappe.get_doc("CRM Rule", name)
	version = _lock_version(doc.rule_version, "write")
	_assert_expected_version(version, expected_version_revision)
	_assert_draft(version)
	if doc.status != "draft":
		frappe.throw(_("Only draft CRM Rules can be deleted."), frappe.PermissionError)
	with _flag("crm_rule_authoring"):
		doc.delete(ignore_permissions=True)
	_save_draft_version(version, _version_groups(version))
	return {"name": name, "deleted": True, "version_id": version.version_id, "revision": version.revision}


@frappe.whitelist(methods=["POST"])
def activate_rule_version(
	name: str,
	expected_settings_revision: int | str,
	expected_version_revision: int | str,
	change_note: str | None = None,
) -> dict:
	"""Atomically make a draft or known-good superseded snapshot active."""
	_require_admin()
	settings = _lock_settings()
	_lock_all_versions()
	version = _lock_version(name, "write")
	_assert_expected_settings(settings, expected_settings_revision)
	_assert_expected_version(version, expected_version_revision)
	_assert_pointer_consistent(settings)
	status = str(version.status or "").strip().lower()
	if status == "active":
		frappe.throw(_("The selected CRM Rule Version is already active."), frappe.ValidationError)
	if status not in {"draft", "superseded"}:
		frappe.throw(_("Only Draft or Superseded versions can be activated."), frappe.ValidationError)
	note = str(change_note or "").strip()
	if len(note) > 2000:
		frappe.throw(_("change_note cannot exceed 2000 characters."), frappe.ValidationError)
	rows = _rule_rows(version.name)
	if status == "draft":
		if not rows:
			frappe.throw(_("A CRM Rule Version must contain at least one rule before activation."), frappe.ValidationError)
		try:
			catalog = catalog_from_rows(
				rows,
				version_id=version.version_id,
				technical_revision=int(version.revision or 0) + 1,
				group_catalog=version.group_catalog,
			)
		except ValueError as exc:
			_throw_value_error(exc)
		next_revision = int(version.revision or 0) + 1
		ruleset_revision = str(next_revision)
	else:
		catalog = _version_wire_catalog(version)
		next_revision = int(version.revision or 0)
		ruleset_revision = str(version.ruleset_revision or next_revision)
	now = frappe.utils.now_datetime()
	for old_name in frappe.get_all("CRM Rule Version", filters={"status": "active"}, pluck="name"):
		if old_name == version.name:
			continue
		frappe.db.set_value(
			"CRM Rule Version",
			old_name,
			{
				"status": "superseded",
				"superseded_at": now,
				"superseded_by": frappe.session.user,
				"change_note": note or f"Superseded by {version.version_id}.",
			},
			update_modified=False,
		)
		for old_rule in frappe.get_all(
			"CRM Rule", filters={"rule_version": old_name, "status": "active"}, pluck="name"
		):
			frappe.db.set_value("CRM Rule", old_rule, "status", "superseded", update_modified=False)
	for row in rows:
		values = {"status": "active"}
		if status == "draft":
			values["revision"] = int(row.revision or 0) + 1
		frappe.db.set_value("CRM Rule", row.name, values, update_modified=False)
	frappe.db.set_value(
		"CRM Rule Version",
		version.name,
		{
			"status": "active",
			"revision": next_revision,
			"schema_version": CATALOG_SCHEMA,
			"ruleset_revision": ruleset_revision,
			"ruleset_digest": catalog["ruleset_digest"],
			"activated_at": now,
			"activated_by": frappe.session.user,
			"superseded_at": None,
			"superseded_by": None,
			"change_note": note or None,
		},
		update_modified=True,
	)
	settings.active_rule_version = version.name
	settings.pointer_revision = int(settings.pointer_revision or 0) + 1
	settings.active_ruleset_digest = catalog["ruleset_digest"]
	settings.changed_at = now
	settings.changed_by = frappe.session.user
	with _flag("crm_rule_settings_lifecycle"):
		settings.save(ignore_permissions=True)
	return _version_payload(_get_version(version.name), len(rows))


@frappe.whitelist(methods=["POST"])
def publish_rule_version(
	name: str,
	expected_revision: int | str,
	expected_settings_revision: int | str,
	change_note: str | None = None,
) -> dict:
	"""Compatibility alias; activation is the only lifecycle implementation."""
	_require_admin()
	if expected_settings_revision in (None, ""):
		frappe.throw(
			_("expected_settings_revision is required; reload the active pointer before publishing."),
			frappe.ValidationError,
		)
	return activate_rule_version(
		name,
		expected_settings_revision,
		expected_revision,
		change_note=change_note,
	)


@frappe.whitelist(methods=["POST"])
def archive_rule_version(name: str, expected_revision: int | str, reason: str | None = None) -> dict:
	"""Compatibility endpoint retained as an explicit no-op rejection."""
	_require_admin()
	_lock_version(name, "read")
	frappe.throw(
		_("Archive is retired. Activate another Draft or Superseded snapshot instead."),
		frappe.PermissionError,
	)


@frappe.whitelist()
def list_fact_catalog() -> dict:
	_require_admin()
	return {"schema": CATALOG_SCHEMA, "facts": fact_descriptors()}


def _validate_feature_scope(feature_scope: str | None) -> str | None:
	if not feature_scope:
		return None
	try:
		return normalize_feature_scope(feature_scope)
	except ValueError as exc:
		frappe.throw(_("Unsupported feature scope."), frappe.ValidationError)
		raise exc


@frappe.whitelist()
def get_active_rule_catalog(feature_scope: str | None = None) -> dict:
	"""Return the complete catalog selected by the authoritative Settings pointer."""
	_require_service_identity()
	_validate_feature_scope(feature_scope)
	settings = _get_settings(create=False, permission_type="read")
	if not settings.active_rule_version or not settings.active_ruleset_digest:
		frappe.throw(_("CRM Rule Settings has no complete active snapshot."), frappe.ValidationError)
	version = _get_version(settings.active_rule_version, "read")
	if str(version.status or "").lower() != "active":
		frappe.throw(_("CRM Rule Settings points to a non-active snapshot."), frappe.ValidationError)
	if str(version.ruleset_digest or "") != str(settings.active_ruleset_digest):
		frappe.throw(_("CRM Rule Settings pointer digest does not match the version."), frappe.ValidationError)
	return _version_wire_catalog(version)


@frappe.whitelist()
def get_rule_catalog(version: str, expected_digest: str) -> dict:
	"""Return one immutable Active/Superseded snapshot by exact digest."""
	_require_service_identity()
	if not isinstance(expected_digest, str) or not HEX_DIGEST.fullmatch(expected_digest):
		frappe.throw(_("expected_digest must be a lowercase SHA-256 digest."), frappe.ValidationError)
	doc = _get_version(_resolve_version_name(version), "read")
	if str(doc.status or "").lower() not in {"active", "superseded"}:
		frappe.throw(_("Draft rule catalogs cannot be used for durable work."), frappe.PermissionError)
	if str(doc.ruleset_digest or "") != expected_digest:
		frappe.throw(_("The requested CRM Rule Version digest does not match."), frappe.ValidationError)
	catalog = _version_wire_catalog(doc)
	if catalog["ruleset_digest"] != expected_digest:
		frappe.throw(_("The immutable CRM Rule Version content changed."), frappe.ValidationError)
	return catalog
