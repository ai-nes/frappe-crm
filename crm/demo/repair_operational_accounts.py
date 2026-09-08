"""Audit and repair explicitly selected production CRM accounts.

The audit is read-only. The repair command changes identity data only: it never
changes a password, creates a new permission bypass, or guesses a user's
organizational scope. Run both with ``bench execute`` from a System Manager.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

import frappe
from frappe import _
from frappe.utils import getdate, today

from crm.api.user import remove_roles, set_canonical_crm_profile
from crm.fcrm.role_policy import (
	CANONICAL_SELECTABLE_ROLES,
	LEGACY_OVERLAY_ROLES,
	LEGACY_UNMAPPED_ROLES,
	PROFILE_LABELS,
	ROLE_BACKFILL_SOURCES,
	SYSTEM_MANAGER_ROLE,
	backfill_target_for_roles,
	capabilities_for_roles,
	classify_role_set,
	resolve_crm_profile,
)

SUPPORTED_ROLES = CANONICAL_SELECTABLE_ROLES - {"Administrator"}
GLOBAL_SCOPE_ROLES = frozenset({"Admissions Director"})
TEAM_MEMBERSHIP_ROLES = frozenset({"Sale", "Lead Sale", "CTV Sale"})
TEAM_SCOPED_PROFILES = frozenset({"sales", "lead_sales", "ctv_sale"})
ROLE_TO_FUNCTION = {role: role for role in TEAM_MEMBERSHIP_ROLES}
MEMBERSHIP_FUNCTION_ALIASES = {
	"CTV-Sale": "CTV Sale",
	"Counseller": "Sale",
	"Sales User": "Sale",
	"Sales Manager": "Lead Sale",
	"Team Leader": "Lead Sale",
	"Promoter-PR": "Promoter",
	"Marketing Operator": "Marketing",
	"Marketing Lead": "Marketing",
	"Admissions Operations": "Admissions Director",
	"Giám đốc Tuyển sinh": "Admissions Director",
}
LEGACY_ROLE_ALIASES = frozenset(ROLE_BACKFILL_SOURCES) | {"Lead Sales"}
AUDIT_ROLE_NAMES = frozenset(
	CANONICAL_SELECTABLE_ROLES
	| ROLE_BACKFILL_SOURCES
	| LEGACY_UNMAPPED_ROLES
	| LEGACY_OVERLAY_ROLES
	| {SYSTEM_MANAGER_ROLE}
)
GLOBAL_SCOPE_PROFILES = frozenset({"system_manager", "ceo", "admissions_director"})


def _is_truthy(value: Any) -> bool:
	return value in (1, True, "1", "true", "True")


def _issue(code: str, severity: str = "blocking") -> dict[str, str]:
	return {"code": code, "severity": severity}


def _membership_is_active(row: dict[str, Any], today_value: Any) -> bool:
	start = row.get("effective_from")
	end = row.get("effective_until")
	current = getdate(today_value)
	return (not start or getdate(start) <= current) and (not end or getdate(end) >= current)


def _profile_for_roles(user_name: str, roles: set[str]):
	role_state = classify_role_set(roles, administrator=user_name == "Administrator")
	if user_name == "Administrator" or role_state == "system_manager":
		return role_state, "system_manager"
	return role_state, resolve_crm_profile(roles)


def _staff_summary(staff: dict[str, Any] | None) -> dict[str, Any] | None:
	if not staff:
		return None
	return {
		"name": staff.get("name"),
		"full_name": staff.get("full_name"),
		"user": staff.get("user"),
		"is_active": _is_truthy(staff.get("is_active")),
		"department": staff.get("department"),
		"campus": staff.get("campus"),
	}


def _recommended_role(profile: str | None, roles: set[str]) -> str | None:
	if profile:
		return PROFILE_LABELS.get(profile)
	if "Lead Sales" in roles:
		return "Lead Sale"
	return backfill_target_for_roles(roles)


def _audit_account(
	user: dict[str, Any],
	roles: set[str],
	staff_rows: list[dict[str, Any]],
	membership_rows: list[dict[str, Any]],
	team_rows: dict[str, dict[str, Any]],
	*,
	today_value: Any,
) -> dict[str, Any]:
	user_name = user.get("name") or user.get("email")
	role_state, profile = _profile_for_roles(user_name, roles)
	issues: list[dict[str, str]] = []

	if not profile:
		issues.append(_issue("ROLE_NOT_CANONICAL"))
	if not _is_truthy(user.get("enabled")):
		issues.append(_issue("USER_DISABLED"))

	active_staff = [row for row in staff_rows if _is_truthy(row.get("is_active"))]
	staff = active_staff[0] if active_staff else (staff_rows[0] if staff_rows else None)
	if len(staff_rows) > 1:
		issues.append(_issue("DUPLICATE_STAFF_LINK"))

	if profile and profile not in GLOBAL_SCOPE_PROFILES:
		if not active_staff:
			issues.append(_issue("MISSING_ACTIVE_CRM_STAFF"))
		else:
			if not staff.get("department") or not staff.get("campus"):
				issues.append(_issue("STAFF_ORGANIZATION_INCOMPLETE"))
			if staff.get("department") and not staff.get("department_exists", True):
				issues.append(_issue("DEPARTMENT_NOT_FOUND"))
			if staff.get("campus") and not staff.get("campus_exists", True):
				issues.append(_issue("CAMPUS_NOT_FOUND"))
			if (
				staff.get("department_campus")
				and staff.get("campus")
				and staff.get("department_campus") != staff.get("campus")
			):
				issues.append(_issue("DEPARTMENT_CAMPUS_MISMATCH"))

	active_memberships = [row for row in membership_rows if _membership_is_active(row, today_value)]
	if profile in TEAM_SCOPED_PROFILES and not active_memberships:
		issues.append(_issue("NO_ACTIVE_TEAM_MEMBERSHIP"))

	membership_summary = []
	for membership in active_memberships:
		team_name = membership.get("team")
		team = team_rows.get(team_name) if team_name else None
		membership_summary.append(
			{
				"team": team_name,
				"function": membership.get("function"),
				"is_primary": _is_truthy(membership.get("is_primary")),
				"is_team_lead": _is_truthy(membership.get("is_team_lead")),
				"team_active": _is_truthy(team.get("is_active")) if team else False,
				"team_type": team.get("team_type") if team else None,
				"team_campus": team.get("campus") if team else None,
			}
		)
		if not team:
			issues.append(_issue("TEAM_NOT_FOUND"))
			continue
		if not _is_truthy(team.get("is_active")):
			issues.append(_issue("TEAM_INACTIVE"))
		if team.get("team_type") != "Sales":
			issues.append(_issue("TEAM_NOT_SALES"))
		if staff and team.get("campus") and staff.get("campus") != team.get("campus"):
			issues.append(_issue("TEAM_CAMPUS_MISMATCH"))
		if profile in TEAM_SCOPED_PROFILES:
			expected_function = PROFILE_LABELS.get(profile)
			if expected_function and membership.get("function") != expected_function:
				issues.append(_issue("TEAM_FUNCTION_MISMATCH"))

	if profile in TEAM_SCOPED_PROFILES and active_memberships:
		if not any(_is_truthy(row.get("is_primary")) for row in active_memberships):
			issues.append(_issue("NO_PRIMARY_TEAM_MEMBERSHIP", "warning"))

	recommended_role = _recommended_role(profile, roles)
	return {
		"user": user_name,
		"email": user.get("email") or user_name,
		"full_name": user.get("full_name"),
		"enabled": _is_truthy(user.get("enabled")),
		"roles": sorted(roles),
		"role_state": role_state,
		"crm_profile": profile,
		"recommended_role": recommended_role,
		"capabilities": sorted(capabilities_for_roles(roles, administrator=user_name == "Administrator")),
		"staff": _staff_summary(staff),
		"memberships": membership_summary,
		"issues": issues,
	}


def _audit_candidate(roles: set[str], has_staff: bool) -> bool:
	return has_staff or bool(roles.intersection(AUDIT_ROLE_NAMES))


def _enrich_staff_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
	enriched = []
	for row in rows:
		snapshot = dict(row)
		department = snapshot.get("department")
		campus = snapshot.get("campus")
		snapshot["department_exists"] = bool(department and frappe.db.exists("CRM Department", department))
		snapshot["campus_exists"] = bool(campus and frappe.db.exists("CRM Campus", campus))
		snapshot["department_campus"] = (
			frappe.db.get_value("CRM Department", department, "campus") if department else None
		)
		enriched.append(snapshot)
	return enriched


def _audit_memberships(
	staff_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
	staff_names = [row.get("name") for row in staff_rows if row.get("name")]
	if not staff_names:
		return [], {}
	memberships = frappe.get_all(
		"CRM Team Membership",
		filters={"parent": ["in", staff_names], "parenttype": "CRM Staff"},
		fields=[
			"parent as staff",
			"team",
			"function",
			"is_primary",
			"is_team_lead",
			"effective_from",
			"effective_until",
		],
		limit_page_length=0,
	)
	team_names = {row.get("team") for row in memberships if row.get("team")}
	if not team_names:
		return memberships, {}
	teams = frappe.get_all(
		"CRM Team",
		filters={"name": ["in", sorted(team_names)]},
		fields=["name", "campus", "team_type", "is_active"],
		limit_page_length=0,
	)
	return memberships, {row.get("name"): dict(row) for row in teams if row.get("name")}


def audit_operational_accounts() -> dict[str, Any]:
	"""Return a read-only identity/readiness report for every CRM account."""
	from crm.api.session import _get_policy_roles

	_require_admin_context()
	user_rows = frappe.get_all(
		"User",
		filters={"user_type": "System User"},
		fields=["name", "email", "full_name", "enabled"],
		order_by="name asc",
		limit_page_length=0,
	)
	staff_rows = _enrich_staff_rows(
		frappe.get_all(
			"CRM Staff",
			fields=["name", "full_name", "user", "is_active", "department", "campus"],
			limit_page_length=0,
		)
	)
	staff_by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
	for staff in staff_rows:
		if staff.get("user"):
			staff_by_user[staff["user"]].append(staff)

	accounts = []
	for user in user_rows:
		user_name = user.get("name")
		roles = set(_get_policy_roles(user_name))
		linked_staff = staff_by_user.get(user_name, [])
		if not _audit_candidate(roles, bool(linked_staff)):
			continue
		memberships, teams = _audit_memberships(linked_staff)
		accounts.append(
			_audit_account(
				dict(user),
				roles,
				linked_staff,
				memberships,
				teams,
				today_value=today(),
			)
		)

	issue_counts = Counter(issue["code"] for account in accounts for issue in account["issues"])
	blocking_count = sum(
		1 for account in accounts for issue in account["issues"] if issue["severity"] == "blocking"
	)
	warning_count = sum(
		1 for account in accounts for issue in account["issues"] if issue["severity"] == "warning"
	)
	accounts_with_issues = sum(bool(account["issues"]) for account in accounts)
	return {
		"status": "healthy" if not issue_counts else "issues_found",
		"total_accounts": len(accounts),
		"healthy_accounts": len(accounts) - accounts_with_issues,
		"accounts_with_issues": accounts_with_issues,
		"blocking_issue_count": blocking_count,
		"warning_issue_count": warning_count,
		"issue_counts": dict(sorted(issue_counts.items())),
		"accounts": accounts,
	}


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
		team = _text(raw.get("team"), f"accounts[{index}].team")
		if team and role not in TEAM_MEMBERSHIP_ROLES:
			_error(_("accounts[{0}].team is only supported for Sales profiles.").format(index))
		if email in seen_emails:
			_error(_("Duplicate account email: {0}.").format(email))
		seen_emails.add(email)
		normalized.append(
			{
				"email": email,
				"role": role,
				"function": ROLE_TO_FUNCTION.get(role),
				"full_name": _text(raw.get("full_name"), f"accounts[{index}].full_name"),
				"department": _text(raw.get("department"), f"accounts[{index}].department"),
				"campus": _text(raw.get("campus"), f"accounts[{index}].campus"),
				"team": team,
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
	if user.name == "Administrator" or roles.intersection({"Administrator", "System Manager"}):
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


def _normalize_membership_functions(staff) -> None:
	for membership in staff.team_memberships:
		function = membership.get("function")
		canonical_function = MEMBERSHIP_FUNCTION_ALIASES.get(function)
		if canonical_function:
			membership.function = canonical_function


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
	if (
		not staff
		and account["role"] in GLOBAL_SCOPE_ROLES
		and not any(account[field] for field in ("department", "campus", "team"))
	):
		return None, False
	if (
		staff
		and account["role"] in GLOBAL_SCOPE_ROLES
		and not any(account[field] for field in ("department", "campus", "team"))
	):
		return staff, False

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
		_normalize_membership_functions(staff)
		staff.save(ignore_permissions=True)
	return staff, created


def _ensure_membership(staff, account: dict[str, Any]) -> str | None:
	_normalize_membership_functions(staff)
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
	team = _ensure_membership(staff, account) if staff else None
	return {
		"email": account["email"],
		"role": account["role"],
		"staff": staff.name if staff else None,
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
