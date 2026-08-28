"""Idempotently create the named local admissions cohort."""

import frappe

from frappe.utils.password import update_password

from crm.api.user import set_canonical_crm_profile
from crm.fcrm.master_data_governance import create_additive_value
CANONICAL_FIXTURE_USERS = {
	"nguyen-minh-khoi.sale@example.test": {"full_name": "Nguyễn Minh Khôi", "role": "Sale"},
	"le-thanh-huong.leadsales@example.test": {"full_name": "Lê Thanh Hương", "role": "Lead Sales"},
	"pham-bao-chau.marketing@example.test": {"full_name": "Phạm Bảo Châu", "role": "Marketing"},
	"tran-quoc-duy.director@example.test": {"full_name": "Trần Quốc Duy", "role": "Admissions Director"},
}

CONVENIENCE_ALIAS_USERS = {
	"sale@gmail.com": {"full_name": "Sale Gmail", "role": "Sale"},
	"sale@example.com": {"full_name": "Sale Example", "role": "Sale"},
	"leadsales@gmail.com": {"full_name": "Lead Sales Gmail", "role": "Lead Sales"},
	"leadsales@example.com": {"full_name": "Lead Sales Example", "role": "Lead Sales"},
	"marketing@gmail.com": {"full_name": "Marketing Gmail", "role": "Marketing"},
	"marketing@example.com": {"full_name": "Marketing Example", "role": "Marketing"},
	"director@gmail.com": {"full_name": "Director Gmail", "role": "Admissions Director"},
	"director@example.com": {"full_name": "Director Example", "role": "Admissions Director"},
}

FIXTURE_PASSWORD_SITE_CONFIG_KEY = "crm_phase2_fixture_password"
FIXTURE_SALES_TEAM_NAME = "Tư vấn tuyển sinh TP.HCM"
FIXTURE_STUDENT_POOL_NAME = "Nguồn tuyển sinh TP.HCM — Kỳ Thu 2026"
FIXTURE_DEPARTMENT_NAME = "Tuyển sinh TP.HCM — Kỳ Thu 2026"
FIXTURE_CAMPUS_NAME = "FPTU Ho Chi Minh Campus"


def execute():
	fixture_password = frappe.conf.get(FIXTURE_PASSWORD_SITE_CONFIG_KEY)
	if not fixture_password:
		frappe.throw(
			f"Set the {FIXTURE_PASSWORD_SITE_CONFIG_KEY} site config before seeding canonical fixture users.",
			frappe.ValidationError,
		)

	campus = frappe.db.exists("CRM Campus", FIXTURE_CAMPUS_NAME)
	if not campus:
		campus = create_additive_value(
			"CRM Campus",
			FIXTURE_CAMPUS_NAME,
			reason="Local admissions fixture campus for the HCMC recruitment cohort.",
			idempotency_key="local-admissions-fixture:CRM Campus:FPTU Ho Chi Minh Campus",
			correlation_id="local-admissions-fixture",
		)["name"]
	department = _ensure_fixture_department(campus)

	created = []
	fixture_users = []
	staff_by_user = {}
	for email, fixture in CANONICAL_FIXTURE_USERS.items():
		user = _ensure_canonical_fixture_user(email, fixture, fixture_password)
		fixture_users.append(user.name)
		staff_name, was_created = _ensure_fixture_staff(email, fixture, department, campus)
		staff_by_user[email] = staff_name
		if was_created:
			created.append(staff_name)

	for email, fixture in CONVENIENCE_ALIAS_USERS.items():
		_ensure_canonical_fixture_user(email, fixture, fixture_password)
		_ensure_fixture_staff(email, fixture, department, campus)

	frappe.db.set_single_value("System Settings", "language", "vi")
	if frappe.db.exists("User", "Administrator"):
		frappe.db.set_value("User", "Administrator", "language", "vi")

	team = _ensure_fixture_sales_team(campus)
	_ensure_fixture_team_memberships(team)
	pool = _ensure_fixture_student_pool(team)
	frappe.db.commit()
	return {
		"created": created,
		"count": len(created),
		"fixture_users": fixture_users,
		"staff_by_user": staff_by_user,
		"team": team,
		"pool": pool,
		"campus": campus,
	}


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
				"language": "vi",
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)

	user.full_name = fixture["full_name"]
	user.enabled = 1
	user.language = "vi"
	set_canonical_crm_profile(user, fixture["role"])
	user.save(ignore_permissions=True)
	update_password(user=email, pwd=password, logout_all_sessions=True)
	return user



def _ensure_fixture_staff(email, fixture, department, campus):
	staff_name = frappe.db.get_value("CRM Staff", {"user": email}, "name")
	if not staff_name and frappe.db.exists("CRM Staff", fixture["full_name"]):
		staff_name = fixture["full_name"]
	if staff_name:
		staff = frappe.get_doc("CRM Staff", staff_name)
		staff.user = email
		staff.full_name = fixture["full_name"]
		staff.campus = campus
		staff.department = department
		staff.is_active = 1
		staff.save(ignore_permissions=True)
		return staff_name, False

	staff = frappe.get_doc(
		{
			"doctype": "CRM Staff",
			"full_name": fixture["full_name"],
			"user": email,
			"department": department,
			"campus": campus,
			"is_active": 1,
		}
	).insert(ignore_permissions=True)
	return staff.name, True




def _ensure_fixture_department(campus):
	"""Return the fixture's unique department without recreating it on rerun."""
	department = frappe.db.exists("CRM Department", FIXTURE_DEPARTMENT_NAME)
	if department:
		if frappe.db.get_value("CRM Department", department, "campus") != campus:
			frappe.throw("Local admissions department belongs to another campus.", frappe.ValidationError)
		return department
	return frappe.get_doc(
		{"doctype": "CRM Department", "department_name": FIXTURE_DEPARTMENT_NAME, "campus": campus}
	).insert(ignore_permissions=True).name


def _ensure_fixture_sales_team(campus):
	team_name = FIXTURE_SALES_TEAM_NAME
	if frappe.db.exists("CRM Team", team_name):
		existing_campus = frappe.db.get_value("CRM Team", team_name, "campus")
		if existing_campus == campus:
			return team_name
		frappe.throw("Local admissions team belongs to another campus.", frappe.ValidationError)
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
	pool_name = FIXTURE_STUDENT_POOL_NAME
	if frappe.db.exists("CRM Student Pool", pool_name):
		pool = frappe.db.get_value("CRM Student Pool", pool_name, ["team", "is_active"], as_dict=True)
		if pool.team != team or not pool.is_active:
			frappe.throw("Local admissions pool conflicts with the current team topology.", frappe.ValidationError)
		return pool_name
	team_doc = frappe.db.get_value("CRM Team", team, ["name", "campus"], as_dict=True)
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
		("nguyen-minh-khoi.sale@example.test", "Sale", 0),
		("le-thanh-huong.leadsales@example.test", "Lead Sales", 1),
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
