"""Idempotently attach CRM Staff rows to enabled CRM demo users."""

import frappe

from frappe.utils.password import update_password

from crm.api.user import set_canonical_crm_profile
from crm.fcrm.role_policy import is_crm_user


CANONICAL_FIXTURE_USERS = {
	"sale@gmail.com": {"full_name": "Sale", "role": "Sale"},
	"leadsale@gmail.com": {"full_name": "Lead Sales", "role": "Lead Sales"},
	"marketing@gmail.com": {"full_name": "Marketing", "role": "Marketing"},
	"director@gmail.com": {"full_name": "Admissions Director", "role": "Admissions Director"},
}
FIXTURE_PASSWORD_SITE_CONFIG_KEY = "crm_phase2_fixture_password"
FIXTURE_SALES_TEAM_NAME = "Phase 2 Canonical Sales Team"
FIXTURE_CAMPUS_NAME = "FPTU Ho Chi Minh Campus"


def execute():
	fixture_password = frappe.conf.get(FIXTURE_PASSWORD_SITE_CONFIG_KEY)
	if not fixture_password:
		frappe.throw(
		f"Set the {FIXTURE_PASSWORD_SITE_CONFIG_KEY} site config before seeding canonical fixture users.",
			frappe.ValidationError,
		)

	campus = frappe.db.exists("CRM Campus", FIXTURE_CAMPUS_NAME) or frappe.db.get_value("CRM Campus", {}, "name")
	if not campus:
		campus = frappe.get_doc({"doctype": "CRM Campus", "campus_name": "Demo Campus"}).insert(
			ignore_permissions=True
		).name
	department = _ensure_fixture_department(campus)

	created = []
	fixture_users = []
	for email, fixture in CANONICAL_FIXTURE_USERS.items():
		user = _ensure_canonical_fixture_user(email, fixture, fixture_password)
		fixture_users.append(user.name)
	for user in frappe.get_all("User", filters={"enabled": 1}, fields=["name", "full_name"]):
		if user.name in {"Administrator", "Guest"} or not is_crm_user(frappe.get_roles(user.name)):
			continue
		if frappe.db.exists("CRM Staff", {"user": user.name}):
			continue
		staff = frappe.get_doc(
			{
				"doctype": "CRM Staff",
				"full_name": user.full_name or user.name,
				"user": user.name,
				"department": department,
				"campus": campus,
			}
		).insert(ignore_permissions=True)
		created.append(staff.name)

	team = _ensure_fixture_sales_team(campus)
	_ensure_fixture_team_memberships(team)
	pool = _ensure_fixture_student_pool(team)
	frappe.db.commit()
	return {"created": created, "count": len(created), "fixture_users": fixture_users, "team": team, "pool": pool}


def _ensure_canonical_fixture_user(email, fixture, password):
	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
	else:
		first_name, _, last_name = fixture["full_name"].partition(" ")
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": first_name,
				"last_name": last_name,
				"user_type": "System User",
				"enabled": 1,
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)

	user.full_name = fixture["full_name"]
	set_canonical_crm_profile(user, fixture["role"])
	user.save(ignore_permissions=True)
	update_password(user=email, pwd=password, logout_all_sessions=True)
	return user


def _ensure_fixture_department(campus):
	"""Return the fixture's unique department without recreating it on rerun."""
	department = frappe.db.exists("CRM Department", "Demo Admissions")
	if department:
		return department
	return frappe.get_doc(
		{"doctype": "CRM Department", "department_name": "Demo Admissions", "campus": campus}
	).insert(ignore_permissions=True).name


def _ensure_fixture_sales_team(campus):
	team_name = FIXTURE_SALES_TEAM_NAME
	if frappe.db.exists("CRM Team", team_name):
		existing_campus = frappe.db.get_value("CRM Team", team_name, "campus")
		if existing_campus == campus:
			return team_name
		existing_team = frappe.get_all(
			"CRM Team",
			filters={"campus": campus, "team_type": "Sales", "is_active": 1},
			pluck="name",
			order_by="creation asc",
			limit_page_length=1,
		)
		if existing_team:
			return existing_team[0]
		team_name = f"{FIXTURE_SALES_TEAM_NAME} - {campus}"
	if frappe.db.exists("CRM Team", team_name):
		return team_name
	return frappe.get_doc(
		{
			"doctype": "CRM Team",
			"team_name": team_name,
			"team_type": "Sales",
			"campus": campus,
			"is_active": 1,
		}
	).insert(ignore_permissions=True).name


def _ensure_fixture_student_pool(team):
	pool_name = f"{team} Pool"
	if frappe.db.exists("CRM Student Pool", pool_name):
		return pool_name
	team_doc = frappe.db.get_value("CRM Team", team, ["name", "campus"], as_dict=True)
	existing_pool = frappe.db.get_value(
		"CRM Student Pool",
		{"team": team_doc.name, "campus": team_doc.campus, "is_active": 1},
		"name",
	)
	if existing_pool:
		return existing_pool
	return frappe.get_doc(
		{
			"doctype": "CRM Student Pool",
			"pool_name": pool_name,
			"team": team_doc.name,
			"campus": team_doc.campus,
			"is_active": 1,
		}
	).insert(ignore_permissions=True).name


def _ensure_fixture_team_memberships(team):
	for email, function, is_team_lead in (
		("sale@gmail.com", "Sale", 0),
		("leadsale@gmail.com", "Lead Sales", 1),
	):
		staff_name = frappe.db.get_value("CRM Staff", {"user": email}, "name")
		if not staff_name:
			frappe.throw(f"Missing CRM Staff fixture for {email}", frappe.ValidationError)
		staff = frappe.get_doc("CRM Staff", staff_name)
		membership = next((row for row in staff.team_memberships if row.team == team), None)
		if membership:
			membership.function = function
			membership.is_primary = 1
			membership.is_team_lead = is_team_lead
		else:
			staff.append(
				"team_memberships",
				{
					"team": team,
					"function": function,
					"is_primary": 1,
					"is_team_lead": is_team_lead,
				},
			)
		staff.save(ignore_permissions=True)
