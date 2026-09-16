"""Seed a minimal local Team-management fixture.

Creates exactly one active Group, two active Teams, and three local login
accounts: one Group lead, one Team lead, and one Team member. The fixture is
idempotent and intentionally does not remove or deactivate unrelated data.

Run locally with::

    bench --site crm.localhost execute crm.demo.seed_minimal_team_management.execute

All fixture accounts use the local-only password ``123456``.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import today
from frappe.utils.password import update_password

from crm.api.user import set_canonical_crm_profile
from crm.demo import seed_demo, seed_staff

LOCAL_SITE = "crm.localhost"
FIXTURE_PASSWORD = "123456"
PROVINCE = seed_demo.PROVINCE_NAME
CAMPUS = seed_demo.CAMPUS
DEPARTMENT = seed_staff.FIXTURE_DEPARTMENT_NAME
GROUP_NAME = "DEMO — Nhóm Tuyển sinh"
TEAM_LEAD_TEAM_NAME = "DEMO — Team Tư vấn A"
SECOND_TEAM_NAME = "DEMO — Team Tư vấn B"

ACCOUNT_FIXTURES: tuple[dict[str, Any], ...] = (
	{
		"email": "demo.group.lead@example.com",
		"full_name": "Demo Group Lead",
		"role": "Sale",
		"function": None,
	},
	{
		"email": "demo.team.lead@example.com",
		"full_name": "Demo Team Lead",
		"role": "Sale",
		"function": "Sale",
	},
	{
		"email": "demo.member@example.com",
		"full_name": "Demo Team Member",
		"role": "CTV Sale",
		"function": "CTV Sale",
	},
)


def _assert_local_site() -> None:
	if getattr(frappe.local, "site", None) != LOCAL_SITE:
		frappe.throw(
			"Seed Team tối giản chỉ được chạy trên crm.localhost.",
			frappe.ValidationError,
		)


def _ensure_context() -> dict[str, str]:
	province = seed_demo._ensure_province()
	campus = seed_demo._ensure_campus(province)
	department = seed_staff._ensure_fixture_department(campus)
	return {"province": province, "campus": campus, "department": department}


def _ensure_user(account: dict[str, Any]) -> str:
	if frappe.db.exists("User", account["email"]):
		user = frappe.get_doc("User", account["email"])
	else:
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": account["email"],
				"first_name": account["full_name"],
				"user_type": "System User",
				"enabled": 1,
				"language": "vi",
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)

	user.enabled = 1
	user.language = "vi"
	set_canonical_crm_profile(user, account["role"])
	user.save(ignore_permissions=True)
	update_password(user=account["email"], pwd=FIXTURE_PASSWORD, logout_all_sessions=True)
	return user.name


def _ensure_staff(account: dict[str, Any], context: dict[str, str]) -> str:
	staff_name = frappe.db.get_value("CRM Staff", {"user": account["email"]}, "name")
	if staff_name:
		staff = frappe.get_doc("CRM Staff", staff_name)
	else:
		staff = frappe.get_doc(
			{
				"doctype": "CRM Staff",
				"full_name": account["full_name"],
				"user": account["email"],
				"department": context["department"],
				"campus": context["campus"],
				"is_active": 1,
			}
		).insert(ignore_permissions=True)
		return staff.name

	staff.full_name = account["full_name"]
	staff.department = context["department"]
	staff.campus = context["campus"]
	staff.is_active = 1
	staff.save(ignore_permissions=True)
	return staff.name


def _ensure_group(group_lead_staff: str, province: str) -> str:
	if frappe.db.exists("CRM Team Group", GROUP_NAME):
		group = frappe.get_doc("CRM Team Group", GROUP_NAME)
	else:
		group = frappe.get_doc(
			{
				"doctype": "CRM Team Group",
				"group_name": GROUP_NAME,
				"province": province,
				"is_active": 1,
			}
		).insert(ignore_permissions=True)

	group.province = province
	group.group_lead_staff = group_lead_staff
	group.is_active = 1
	group.save(ignore_permissions=True)
	return group.name


def _ensure_membership(staff_name: str, team_name: str, function: str, is_team_lead: bool) -> None:
	staff = frappe.get_doc("CRM Staff", staff_name)
	membership = next((row for row in staff.team_memberships if row.team == team_name), None)
	if membership:
		membership.function = function
		membership.is_primary = 1
		membership.is_team_lead = int(is_team_lead)
		membership.effective_from = membership.effective_from or today()
		membership.effective_until = None
	else:
		staff.append(
			"team_memberships",
			{
				"team": team_name,
				"function": function,
				"is_primary": 1,
				"is_team_lead": int(is_team_lead),
				"effective_from": today(),
			},
		)
	staff.save(ignore_permissions=True)


def _ensure_team(team_name: str, group: str, campus: str) -> str:
	if frappe.db.exists("CRM Team", team_name):
		team = frappe.get_doc("CRM Team", team_name)
	else:
		team = frappe.get_doc(
			{
				"doctype": "CRM Team",
				"team_name": team_name,
				"group": group,
				"team_type": "Sales",
				"campus": campus,
				"is_active": 1,
			}
		).insert(ignore_permissions=True)

	team.group = group
	team.team_type = "Sales"
	team.campus = campus
	team.is_active = 1
	team.save(ignore_permissions=True)
	return team.name


def _set_team_lead(team_name: str, staff_name: str) -> None:
	team = frappe.get_doc("CRM Team", team_name)
	team.team_lead_staff = staff_name
	team.save(ignore_permissions=True)


def execute() -> dict[str, Any]:
	"""Create or repair the minimal local Group/Team fixture."""
	_assert_local_site()
	frappe.set_user("Administrator")
	context = _ensure_context()
	staff_by_email = {}
	for account in ACCOUNT_FIXTURES:
		_ensure_user(account)
		staff_by_email[account["email"]] = _ensure_staff(account, context)

	group = _ensure_group(staff_by_email[ACCOUNT_FIXTURES[0]["email"]], context["province"])
	team_a = _ensure_team(TEAM_LEAD_TEAM_NAME, group, context["campus"])
	team_b = _ensure_team(SECOND_TEAM_NAME, group, context["campus"])
	_ensure_membership(
		staff_by_email[ACCOUNT_FIXTURES[1]["email"]],
		team_a,
		"Sale",
		True,
	)
	_ensure_membership(
		staff_by_email[ACCOUNT_FIXTURES[2]["email"]],
		team_a,
		"CTV Sale",
		False,
	)
	_set_team_lead(team_a, staff_by_email[ACCOUNT_FIXTURES[1]["email"]])
	frappe.db.commit()

	return {
		"group": group,
		"teams": [team_a, team_b],
		"accounts": [
			{
				"email": account["email"],
				"password": FIXTURE_PASSWORD,
				"role": account["role"],
				"staff": staff_by_email[account["email"]],
			}
			for account in ACCOUNT_FIXTURES
		],
		"message": "Đã seed 1 Group, 2 Team và 3 tài khoản local.",
	}
