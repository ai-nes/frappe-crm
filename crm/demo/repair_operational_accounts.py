"""Repair explicitly selected production accounts for assignment workspaces.

This command repairs identity data only. It never changes a password, creates a
new permission bypass, or guesses a user's organizational scope. Run it with
``bench execute`` using an explicit account payload from a System Manager.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import today

from crm.api.user import remove_roles, set_canonical_crm_profile
from crm.fcrm.role_policy import ROLE_BACKFILL_SOURCES

SUPPORTED_ROLES = frozenset({"Sale", "Lead Sale"})
ROLE_TO_FUNCTION = {role: role for role in SUPPORTED_ROLES}
LEGACY_ROLE_ALIASES = frozenset(ROLE_BACKFILL_SOURCES) | {"Lead Sales"}


def _error(message: str) -> None:
	frappe.throw(message, frappe.ValidationError)


def _text(value: Any, label: str, *, required: bool = False) -> str | None:
	text = str(value or "").strip()
	if required and not text:
		_error(_("{0} is required.").format(label))
	return text or None


def _bool(value: Any, default: bool = False) -> bool:
	if value is None:
		return default
	if isinstance(value, bool):
		return value
	return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _normalize_accounts(accounts: Any) -> list[dict[str, Any]]:
	if isinstance(accounts, str):
		try:
			accounts = frappe.parse_json(accounts)
		except (TypeError, ValueError):
			_error(_("accounts must be valid JSON."))
	if not isinstance(accounts, list) or not accounts:
		_error(_("accounts must be a non-empty list."))

	normalized = []
	seen_emails = set()
	for index, raw in enumerate(accounts, start=1):
		if not isinstance(raw, dict):
			_error(_("Account {0} must be an object.").format(index))
		email = _text(raw.get("email"), f"accounts[{index}].email", required=True)
		role = _text(raw.get("role"), f"accounts[{index}].role", required=True)
		if "@" not in email:
			_error(_("accounts[{0}].email is invalid.").format(index))
		if role not in SUPPORTED_ROLES:
			_error(
				_("accounts[{0}].role must be one of: {1}.").format(index, ", ".join(sorted(SUPPORTED_ROLES)))
			)
		if email in seen_emails:
			_error(_("Duplicate account email: {0}.").format(email))
		seen_emails.add(email)
		normalized.append(
			{
				"email": email,
				"role": role,
				"function": ROLE_TO_FUNCTION[role],
				"full_name": _text(raw.get("full_name"), f"accounts[{index}].full_name"),
				"department": _text(raw.get("department"), f"accounts[{index}].department"),
				"campus": _text(raw.get("campus"), f"accounts[{index}].campus"),
				"team": _text(raw.get("team"), f"accounts[{index}].team"),
				"is_primary": _bool(raw.get("is_primary"), default=True),
				"is_team_lead": _bool(raw.get("is_team_lead")),
			}
		)
	return normalized


def _require_admin_context() -> None:
	actor = getattr(frappe.session, "user", None)
	if actor in (None, "Administrator"):
		return
	if "System Manager" not in set(frappe.get_roles(actor)):
		frappe.throw(_("Only System Managers may repair operational accounts."), frappe.PermissionError)


def _prepare_user_profile(user, role: str) -> None:
	roles = {row.role for row in user.get("roles") or []}
	if user.name == "Administrator" or "System Manager" in roles:
		_error(_("Privileged account {0} cannot be repaired by this command.").format(user.name))
	if not user.enabled:
		_error(
			_("User {0} is disabled; enable it explicitly before repairing its CRM identity.").format(
				user.name
			)
		)
	set_canonical_crm_profile(user, role)
	# ``set_canonical_crm_profile`` intentionally preserves non-CRM roles. Clear
	# migration-era CRM aliases separately so runtime profile resolution succeeds.
	remove_roles(user, *LEGACY_ROLE_ALIASES)
	user.save(ignore_permissions=True)


def _validate_staff_links(department: str | None, campus: str | None) -> None:
	if not department or not campus:
		_error(_("A CRM Staff record requires both department and campus."))
	if not frappe.db.exists("CRM Department", department):
		_error(_("CRM Department {0} does not exist.").format(department))
	if not frappe.db.exists("CRM Campus", campus):
		_error(_("CRM Campus {0} does not exist.").format(campus))
	department_campus = frappe.db.get_value("CRM Department", department, "campus")
	if department_campus != campus:
		_error(_("CRM Department {0} does not belong to CRM Campus {1}.").format(department, campus))


def _ensure_staff(user, account: dict[str, Any]):
	full_name = account["full_name"] or user.full_name or user.name
	staff_name = frappe.db.get_value("CRM Staff", {"user": account["email"]}, "name")
	created = False
	if staff_name:
		staff = frappe.get_doc("CRM Staff", staff_name)
	else:
		staff_name = frappe.db.get_value("CRM Staff", {"full_name": full_name}, "name")
		if staff_name:
			staff = frappe.get_doc("CRM Staff", staff_name)
			linked_user = staff.user
			if linked_user and linked_user != account["email"]:
				_error(_("CRM Staff {0} is already linked to {1}.").format(staff.name, linked_user))
		else:
			staff = None

	department = account["department"] or (staff.department if staff else None)
	campus = account["campus"] or (staff.campus if staff else None)
	_validate_staff_links(department, campus)

	if not staff:
		staff = frappe.get_doc(
			{
				"doctype": "CRM Staff",
				"full_name": full_name,
				"user": account["email"],
				"department": department,
				"campus": campus,
				"is_active": 1,
			}
		).insert(ignore_permissions=True)
		created = True
	else:
		staff.full_name = full_name
		staff.user = account["email"]
		staff.department = department
		staff.campus = campus
		staff.is_active = 1
		staff.save(ignore_permissions=True)
	return staff, created


def _ensure_membership(staff, account: dict[str, Any]) -> str | None:
	team_name = account["team"]
	if not team_name:
		return None
	team = frappe.db.get_value(
		"CRM Team",
		team_name,
		["name", "campus", "team_type", "is_active"],
		as_dict=True,
	)
	if not team:
		_error(_("CRM Team {0} does not exist.").format(team_name))
	if not team.is_active or team.team_type != "Sales":
		_error(_("CRM Team {0} must be an active Sales team.").format(team_name))
	if team.campus != staff.campus:
		_error(_("CRM Team {0} does not belong to Staff campus {1}.").format(team_name, staff.campus))

	function = account["function"]
	primary_teams = {
		row.team
		for row in staff.team_memberships
		if row.get("is_primary") and row.get("team") and row.team != team_name
	}
	if account["is_primary"] and primary_teams:
		_error(
			_("Staff {0} already has another primary team: {1}.").format(
				staff.name, ", ".join(sorted(primary_teams))
			)
		)

	membership = next((row for row in staff.team_memberships if row.team == team_name), None)
	if membership:
		membership.function = function
		membership.is_primary = int(account["is_primary"])
		membership.is_team_lead = int(account["is_team_lead"])
		membership.effective_from = membership.effective_from or today()
		membership.effective_until = None
	else:
		staff.append(
			"team_memberships",
			{
				"team": team_name,
				"function": function,
				"is_primary": int(account["is_primary"]),
				"is_team_lead": int(account["is_team_lead"]),
				"effective_from": today(),
			},
		)
	staff.save(ignore_permissions=True)
	return team_name


def _repair_account(account: dict[str, Any]) -> dict[str, Any]:
	if not frappe.db.exists("User", account["email"]):
		_error(_("User {0} does not exist.").format(account["email"]))
	user = frappe.get_doc("User", account["email"])
	_prepare_user_profile(user, account["role"])
	staff, created = _ensure_staff(user, account)
	team = _ensure_membership(staff, account)
	return {
		"email": account["email"],
		"role": account["role"],
		"staff": staff.name,
		"created_staff": created,
		"team": team,
		"membership_configured": bool(team),
	}


def execute(accounts: Any = None) -> dict[str, Any]:
	"""Repair the supplied accounts and commit only after all accounts succeed."""
	_require_admin_context()
	normalized = _normalize_accounts(accounts)
	try:
		results = [_repair_account(account) for account in normalized]
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		raise
	return {"status": "repaired", "count": len(results), "accounts": results}
