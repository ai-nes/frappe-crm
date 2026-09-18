"""Permission-profile endpoints used by the CRM administration dashboard."""

from __future__ import annotations

import frappe
from frappe import _

from crm.api._pagination import parse_pagination
from crm.api.user import _require_crm_role_manager
from crm.fcrm.role_policy import PROFILE_LABELS, SYSTEM_MANAGER_ROLE

PERMISSION_FIELDS = ("read", "write", "create", "delete", "export")
DEFAULT_PAGE_LENGTH = 8
ROW_SCOPES = frozenset(
	{
		"assigned",
		"own_assigned",
		"campus_assigned",
		"campus_assigned_contact",
		"team_and_team_pool",
		"team_members_and_own_team_pool",
		"no_case_scope",
		"all",
		"deny",
	}
)
MANAGED_PROFILE_ROLES = (SYSTEM_MANAGER_ROLE, *PROFILE_LABELS.values())


def _managed_profile_role(role: str) -> str:
	role = str(role or "").strip()
	if role not in MANAGED_PROFILE_ROLES:
		frappe.throw(_("This role does not have a managed CRM permission profile."), frappe.ValidationError)
	if not frappe.db.exists("Role", role):
		frappe.throw(_("Role {0} does not exist.").format(role), frappe.ValidationError)
	return role


def _as_bool(value, fieldname: str) -> bool:
	if isinstance(value, bool):
		return value
	if isinstance(value, int) and value in (0, 1):
		return bool(value)
	if isinstance(value, str) and value.strip().lower() in {"0", "1", "false", "true"}:
		return value.strip().lower() in {"1", "true"}
	frappe.throw(_("{0} must be a boolean.").format(fieldname), frappe.ValidationError)


def _normalize_doctype_rows(applicable_doctypes) -> list[dict]:
	if isinstance(applicable_doctypes, str):
		try:
			applicable_doctypes = frappe.parse_json(applicable_doctypes)
		except Exception:
			frappe.throw(_("Applicable DocTypes must be a list."), frappe.ValidationError)
	if not isinstance(applicable_doctypes, list) or not applicable_doctypes:
		frappe.throw(_("At least one applicable DocType is required."), frappe.ValidationError)

	rows = []
	seen = set()
	for item in applicable_doctypes:
		if not isinstance(item, dict):
			frappe.throw(_("Each permission row must be an object."), frappe.ValidationError)
		document_type = str(item.get("document_type") or "").strip()
		if not document_type or not frappe.db.exists("DocType", document_type):
			frappe.throw(
				_("DocType {0} does not exist.").format(document_type or "(empty)"),
				frappe.ValidationError,
			)
		if document_type in seen:
			frappe.throw(
				_("DocType {0} appears more than once.").format(document_type), frappe.ValidationError
			)
		seen.add(document_type)
		rows.append(
			{
				"document_type": document_type,
				**{field: int(_as_bool(item.get(field, False), field)) for field in PERMISSION_FIELDS},
			}
		)
	return rows


def _serialized_doctype_rows(profile) -> list[dict]:
	doctype_flags = {}
	for row in profile.applicable_doctypes:
		# The runtime profile loader is a dict keyed by DocType, so its last
		# duplicate row wins. Serialize the same effective shape for the UI.
		doctype_flags[row.document_type] = {field: bool(row.get(field)) for field in PERMISSION_FIELDS}

	return [{"document_type": document_type, **flags} for document_type, flags in doctype_flags.items()]


def _serialize_profile(profile, applicable_doctypes=None) -> dict:
	rows = _serialized_doctype_rows(profile) if applicable_doctypes is None else applicable_doctypes
	return {
		"name": profile.name,
		"role": profile.role,
		"row_scope": profile.row_scope,
		"delete_requires_ownership": bool(profile.delete_requires_ownership),
		"is_system_managed": bool(profile.is_system_managed),
		"applicable_doctypes": rows,
	}


def _get_profile(role: str):
	name = frappe.db.get_value("CRM Permission Profile", {"role": role}, "name")
	if not name:
		frappe.throw(_("Permission profile for role {0} was not found.").format(role), frappe.ValidationError)
	return frappe.get_doc("CRM Permission Profile", name)


@frappe.whitelist()
def list_permission_profiles(
	role: str | None = None,
	start: int | str = 0,
	page_length: int | str = DEFAULT_PAGE_LENGTH,
) -> dict:
	"""Return one API-paginated DocType matrix page for the selected role."""
	_require_crm_role_manager()
	start, page_length = parse_pagination(start, page_length)
	all_profiles = []
	for profile_role in MANAGED_PROFILE_ROLES:
		if frappe.db.exists("CRM Permission Profile", {"role": profile_role}):
			all_profiles.append(_get_profile(profile_role))

	if not all_profiles:
		return {
			"profiles": [],
			"selected_role": None,
			"total": 0,
			"start": start,
			"page_length": page_length,
		}

	selected_role = str(role or "").strip() or all_profiles[0].role
	selected_profile = _get_profile(_managed_profile_role(selected_role))
	selected_rows = _serialized_doctype_rows(selected_profile)
	page_rows = selected_rows[start : start + page_length]
	profiles = [
		_serialize_profile(
			profile,
			page_rows if profile.role == selected_profile.role else [],
		)
		for profile in all_profiles
	]
	return {
		"profiles": profiles,
		"selected_role": selected_profile.role,
		"total": len(selected_rows),
		"start": start,
		"page_length": page_length,
	}


@frappe.whitelist(methods=["POST"])
def update_permission_profile(
	role: str,
	row_scope: str,
	delete_requires_ownership=False,
	applicable_doctypes=None,
	replace_applicable_doctypes=True,
) -> dict:
	"""Update one CRM permission profile and publish its managed DocPerm rows.

	When ``replace_applicable_doctypes`` is false, the submitted rows are merged
	into the existing matrix. The paginated admin UI uses this mode so saving one
	page does not remove rows from pages that were not loaded.
	"""
	_require_crm_role_manager()
	role = _managed_profile_role(role)
	row_scope = str(row_scope or "").strip()
	if row_scope not in ROW_SCOPES:
		frappe.throw(_("Invalid row scope {0}.").format(row_scope or "(empty)"), frappe.ValidationError)

	rows = _normalize_doctype_rows(applicable_doctypes)
	profile = _get_profile(role)
	if not _as_bool(replace_applicable_doctypes, "replace_applicable_doctypes"):
		existing_rows = _serialized_doctype_rows(profile)
		rows_by_doctype = {row["document_type"]: row for row in existing_rows}
		doctype_order = list(rows_by_doctype)
		for row in rows:
			if row["document_type"] not in rows_by_doctype:
				doctype_order.append(row["document_type"])
			rows_by_doctype[row["document_type"]] = row
		rows = [rows_by_doctype[document_type] for document_type in doctype_order]
	profile.row_scope = row_scope
	profile.delete_requires_ownership = int(_as_bool(delete_requires_ownership, "delete_requires_ownership"))
	profile.set("applicable_doctypes", [])
	for row in rows:
		profile.append("applicable_doctypes", row)
	profile.save(ignore_permissions=True)

	from crm.patches.v1_0.setup_crm_permissions import apply_managed_docperms

	apply_managed_docperms()
	frappe.clear_cache()
	return _serialize_profile(profile)
