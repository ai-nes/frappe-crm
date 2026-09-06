"""Seed one local CTV Sale login with three assigned Student cases.

Run with::

    bench --site crm.localhost execute crm.demo.seed_ctv_sale.execute

The account receives the canonical ``CTV Sale`` role and the persisted team
membership value ``CTV Sale``. The fixture is idempotent and never removes
unrelated data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import frappe

from crm.demo import seed_demo, seed_showcase, seed_staff

NAMESPACE = "crm-demo-ctv-sale"
ACCOUNT_EMAIL = "ctvsale@gmail.com"
ACCOUNT_FULL_NAME = "CTV Sale"
ACCOUNT_ROLE = "CTV Sale"
PASSWORD = "123456"
TEAM_MEMBERSHIP_FUNCTION = "CTV Sale"

STUDENT_SCENARIOS: tuple[dict[str, Any], ...] = (
	{
		"key": "student-01",
		"student_name": "Nguyễn Minh Khang",
		"email": "ctv-sale.student01@example.test",
		"phone": "0909900101",
		"gender": "Nam",
		"date_of_birth": "2008-03-18",
		"id_number": "079308031801",
		"id_issued_date": "2024-04-15",
		"graduation_score": 8.6,
		"transcript_score": 8.8,
		"english_converted_score": 7.0,
		"total_score": 24.4,
		"notes": "Học sinh quan tâm ngành Software Engineering và cần tư vấn học bổng.",
		"parent": {
			"name": "Trần Minh Hoàng",
			"phone": "0909901101",
			"address": "Quận 3, Thành phố Hồ Chí Minh",
		},
	},
	{
		"key": "student-02",
		"student_name": "Trần Gia Hân",
		"email": "ctv-sale.student02@example.test",
		"phone": "0909900102",
		"gender": "Nữ",
		"date_of_birth": "2008-07-24",
		"id_number": "079308072402",
		"id_issued_date": "2024-08-12",
		"graduation_score": 8.9,
		"transcript_score": 9.1,
		"english_converted_score": 7.5,
		"total_score": 25.5,
		"notes": "Học sinh đã tìm hiểu học phí, học bổng và muốn được gọi lại cùng phụ huynh.",
		"parent": {
			"name": "Nguyễn Thị Thu Hà",
			"phone": "0909901102",
			"address": "Quận Bình Thạnh, Thành phố Hồ Chí Minh",
		},
	},
	{
		"key": "student-03",
		"student_name": "Lê Hoàng Nam",
		"email": "ctv-sale.student03@example.test",
		"phone": "0909900103",
		"gender": "Nam",
		"date_of_birth": "2008-11-02",
		"id_number": "079308110203",
		"id_issued_date": "2024-12-10",
		"graduation_score": 8.1,
		"transcript_score": 8.4,
		"english_converted_score": 6.5,
		"total_score": 23.0,
		"notes": "Học sinh đang so sánh chương trình đào tạo và cần tư vấn lộ trình xét tuyển.",
		"parent": {
			"name": "Lê Văn Bình",
			"phone": "0909901103",
			"address": "Thành phố Thủ Đức, Thành phố Hồ Chí Minh",
		},
	},
)


@dataclass(frozen=True)
class SalesAccountSeed:
	namespace: str
	account_email: str
	account_full_name: str
	account_role: str
	password: str
	team_membership_function: str
	student_scenarios: tuple[dict[str, Any], ...]
	assign_students_to_account: bool = True
	is_team_lead: bool = False


SEED_SPEC = SalesAccountSeed(
	namespace=NAMESPACE,
	account_email=ACCOUNT_EMAIL,
	account_full_name=ACCOUNT_FULL_NAME,
	account_role=ACCOUNT_ROLE,
	password=PASSWORD,
	team_membership_function=TEAM_MEMBERSHIP_FUNCTION,
	student_scenarios=STUDENT_SCENARIOS,
)


def _ensure_user(spec: SalesAccountSeed):
	from frappe.utils.password import update_password

	from crm.api.user import set_canonical_crm_profile

	first_name, _, last_name = spec.account_full_name.partition(" ")

	if frappe.db.exists("User", spec.account_email):
		user = frappe.get_doc("User", spec.account_email)
	else:
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": spec.account_email,
				"first_name": first_name,
				"last_name": last_name or None,
				"user_type": "System User",
				"enabled": 1,
				"language": "vi",
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)

	user.first_name = first_name
	user.last_name = last_name or None
	user.full_name = spec.account_full_name
	user.user_type = "System User"
	user.enabled = 1
	user.language = "vi"
	set_canonical_crm_profile(user, spec.account_role)
	user.save(ignore_permissions=True)
	# This is a disposable local fixture login, just like the other demo seeds.
	update_password(user=spec.account_email, pwd=spec.password, logout_all_sessions=True)
	return user


def _ensure_staff(spec: SalesAccountSeed, campus: str, department: str) -> str:
	staff_name = frappe.db.get_value("CRM Staff", {"user": spec.account_email}, "name")
	if staff_name:
		staff = frappe.get_doc("CRM Staff", staff_name)
	else:
		staff_name = frappe.db.exists("CRM Staff", spec.account_full_name)
		if staff_name:
			existing_user = frappe.db.get_value("CRM Staff", staff_name, "user")
			if existing_user and existing_user != spec.account_email:
				frappe.throw(
					f"CRM Staff {spec.account_full_name!r} is already linked to {existing_user}.",
					frappe.ValidationError,
				)
			staff = frappe.get_doc("CRM Staff", staff_name)
		else:
			staff = frappe.get_doc(
				{
					"doctype": "CRM Staff",
					"full_name": spec.account_full_name,
					"user": spec.account_email,
					"department": department,
					"campus": campus,
					"is_active": 1,
				}
			).insert(ignore_permissions=True)

	staff.full_name = spec.account_full_name
	staff.user = spec.account_email
	staff.department = department
	staff.campus = campus
	staff.is_active = 1
	staff.save(ignore_permissions=True)
	return staff.name


def _ensure_team_membership(spec: SalesAccountSeed, staff_name: str, team: str) -> None:
	staff = frappe.get_doc("CRM Staff", staff_name)
	other_primary_teams = {
		row.team for row in staff.team_memberships if row.get("is_primary") and row.get("team") != team
	}
	if other_primary_teams:
		frappe.throw(
			f"{spec.account_full_name} already has another primary team: "
			f"{', '.join(sorted(other_primary_teams))}.",
			frappe.ValidationError,
		)
	membership = next((row for row in staff.team_memberships if row.team == team), None)
	if membership:
		membership.function = spec.team_membership_function
		membership.is_primary = 1
		membership.is_team_lead = int(spec.is_team_lead)
	else:
		staff.append(
			"team_memberships",
			{
				"team": team,
				"function": spec.team_membership_function,
				"is_primary": 1,
				"is_team_lead": int(spec.is_team_lead),
			},
		)
	staff.save(ignore_permissions=True)


def _ensure_assignment(
	spec: SalesAccountSeed, student: str, staff_name: str, team: str, key: str
) -> dict[str, Any] | None:
	current = frappe.db.get_value(
		"CRM Student",
		student,
		["owner_staff", "owning_team", "owning_pool", "ownership_revision"],
		as_dict=True,
	)
	if current.get("owner_staff") == staff_name:
		return None
	if not current.get("owning_pool") and not current.get("owner_staff"):
		frappe.throw(
			f"Student {student} has no canonical owner or pool; refusing raw assignment.",
			frappe.ValidationError,
		)

	from crm.fcrm.student_ownership import change_student_ownership

	return change_student_ownership(
		student=student,
		target_kind="owner",
		target_id=staff_name,
		target_team_id=team,
		reason=f"Seed three Student cases for the local {spec.account_full_name} fixture.",
		idempotency_key=f"{spec.namespace}:assign:{key}:r{current.get('ownership_revision') or 0}",
		expected_revision=int(current.get("ownership_revision") or 0),
		correlation_id=f"{spec.namespace}:{key}",
		_internal_service=True,
		_internal_actor="Administrator",
		_commit=False,
	)


def _ensure_child_row(doc, table_field: str, identity_field: str, values: dict[str, Any]) -> bool:
	identity = values[identity_field]
	row = next((item for item in doc.get(table_field) if item.get(identity_field) == identity), None)
	if row:
		changed = False
		for field, value in values.items():
			if row.get(field) != value:
				row.set(field, value)
				changed = True
		return changed
	doc.append(table_field, values)
	return True


def _complete_student_profile(
	spec: SalesAccountSeed,
	context: dict[str, Any],
	student: str,
	scenario: dict[str, Any],
) -> None:
	"""Fill the profile fields shown by Student 360, including child tables."""
	parent = scenario["parent"]
	admission_year = int(context["admission_year"])
	transcript_score = scenario["transcript_score"]
	english_score = scenario["english_converted_score"]
	doc = frappe.get_doc("CRM Student", student)
	values = {
		"student_name": scenario["student_name"],
		"phone": scenario["phone"],
		"email": scenario["email"],
		"gender": scenario["gender"],
		"date_of_birth": scenario["date_of_birth"],
		"enrollment_status": context["enrollment_status"],
		"branch": context["campus"],
		"high_school": context["high_school"],
		"province": context["province"],
		"ward": context["ward"],
		"current_grade": "12",
		"study_stage": "grade_12_h2",
		"major": context["major"],
		"aspiration": context["aspiration"],
		"source": context["source"],
		"advertising_channel": scenario.get("advertising_channel", "Facebook Ads - Scholarship 2026"),
		"admission_year": context["admission_year"],
		"cohort_start_year": scenario.get("cohort_start_year", admission_year - 3),
		"cohort_end_year": scenario.get("cohort_end_year", admission_year),
		"education_program": context["education_program"],
		"graduation_score": scenario["graduation_score"],
		"transcript_score": transcript_score,
		"english_converted_score": english_score,
		"total_score": scenario["total_score"],
		"step": 3,
		"admission_method": "TRANSCRIPT_REVIEW",
		"alt_name": parent["name"],
		"alt_phone": parent["phone"],
		"alt_address": parent["address"],
		"notes": scenario["notes"],
		"id_number": scenario["id_number"],
		"id_issued_date": scenario["id_issued_date"],
		"id_issued_place": "Cục Cảnh sát QLHC về TTXH",
		"import_source_id": f"{spec.namespace}:{scenario['key']}",
	}
	missing = [field for field, value in values.items() if value is None or value == ""]
	if missing:
		frappe.throw(
			f"Student profile for {scenario['key']} is incomplete: {', '.join(missing)}.",
			frappe.ValidationError,
		)
	changed = False
	for field, value in values.items():
		if doc.get(field) != value:
			doc.set(field, value)
			changed = True

	academic_rows = scenario.get("academic_results") or (
		{
			"school_year": f"{admission_year - 2}-{admission_year - 1}",
			"grade": "11",
			"academic_rank": "Khá",
			"gpa": scenario.get("grade_11_gpa", 8.2),
		},
		{
			"school_year": f"{admission_year - 1}-{admission_year}",
			"grade": "12",
			"academic_rank": "Giỏi",
			"gpa": transcript_score,
		},
	)
	for row_values in academic_rows:
		changed |= _ensure_child_row(doc, "academic_results", "school_year", row_values)
	changed |= _ensure_child_row(
		doc,
		"language_certificates",
		"certificate_name",
		{
			"language": "Tiếng Anh",
			"certificate_name": "IELTS Academic",
			"score_level": str(english_score),
			"issue_date": scenario.get("certificate_issue_date", "2025-08-20"),
			"expiry_date": scenario.get("certificate_expiry_date", "2027-08-20"),
		},
	)
	if changed:
		doc.save(ignore_permissions=True)


def _ensure_student(
	spec: SalesAccountSeed,
	context: dict[str, Any],
	pool: str,
	team: str,
	staff_name: str,
	scenario: dict[str, Any],
) -> str:
	key = scenario["key"]
	source_id = f"{spec.namespace}:{key}"
	student = frappe.db.get_value("CRM Student", {"import_source_id": source_id}, "name")
	student_by_email = frappe.db.get_value("CRM Student", {"email": scenario["email"]}, "name")
	if student and student_by_email and student != student_by_email:
		frappe.throw(
			f"Seed identity collision for {scenario['email']}: {student} vs {student_by_email}.",
			frappe.ValidationError,
		)
	if (
		student_by_email
		and frappe.db.get_value("CRM Student", student_by_email, "import_source_id") != source_id
	):
		frappe.throw(
			f"Student email {scenario['email']} already belongs to another seed or business record.",
			frappe.ValidationError,
		)
	student = student or student_by_email

	if not student:
		from crm.fcrm.student_intake import submit_intake

		payload = {
			"student_name": scenario["student_name"],
			"email": scenario["email"],
			"phone": scenario["phone"],
			"gender": scenario["gender"],
			"date_of_birth": scenario["date_of_birth"],
			"id_number": scenario["id_number"],
			"admission_method": "TRANSCRIPT_REVIEW",
			"campus": context["campus"],
			"owning_team": pool,
			"admission_year": context["admission_year"],
			"enrollment_status": "NEW",
			"high_school": context["high_school"],
			"province": context["province"],
			"ward": context["ward"],
			"current_grade": "12",
			"study_stage": "grade_12_h2",
			"major": context["major"],
			"aspiration": context["aspiration"],
			"source": context["source"],
			"advertising_channel": scenario.get("advertising_channel", "Facebook Ads - Scholarship 2026"),
			"alt_name": scenario["parent"]["name"],
			"alt_phone": scenario["parent"]["phone"],
			"consent": {
				"granted": True,
				"granted_at": "2026-08-20 09:00:00",
				"purpose": "admissions_counseling",
				"scope": "student_profile_and_parent_follow_up",
				"source": spec.namespace,
			},
		}
		if spec.assign_students_to_account:
			payload["assigned_to"] = staff_name

		result = submit_intake(
			payload,
			source_namespace=spec.namespace,
			source_record_id=key,
			idempotency_key=f"{spec.namespace}:intake:{key}",
			correlation_id=f"{spec.namespace}:{key}",
		)
		if result.get("outcome") not in {"created", "attached"} or not result.get("student"):
			frappe.throw(f"Student intake did not create {key}: {result}", frappe.ValidationError)
		student = result["student"]

	frappe.db.set_value(
		"CRM Student",
		student,
		{
			"student_name": scenario["student_name"],
			"admission_method": "TRANSCRIPT_REVIEW",
			"import_source_id": source_id,
		},
		update_modified=False,
	)
	_complete_student_profile(spec, context, student, scenario)
	if spec.assign_students_to_account:
		_ensure_assignment(spec, student, staff_name, team, key)
	return student


def execute_seed(spec: SalesAccountSeed) -> dict[str, Any]:
	"""Create one local Sales account and three role-scoped Student cases."""
	seed_showcase._assert_local_site()
	seed_showcase.ensure_local_integrity_keys()
	seed_showcase.ensure_demo_config()
	frappe.set_user("Administrator")

	with seed_showcase._temporary_local_flags():
		context = seed_demo._bootstrap()
		seed_showcase._ensure_lifecycle_statuses()
		department = seed_staff._ensure_fixture_department(context["campus"])
		team = seed_staff._ensure_fixture_sales_team(context["campus"])
		pool = seed_staff._ensure_fixture_student_pool(team)
		_ensure_user(spec)
		staff_name = _ensure_staff(spec, context["campus"], department)
		_ensure_team_membership(spec, staff_name, team)
		seed_showcase._ensure_policies(context["campus"], pool)
		frappe.db.commit()

		students = []
		for scenario in spec.student_scenarios:
			students.append(_ensure_student(spec, context, pool, team, staff_name, scenario))
			frappe.db.commit()

	return {
		"account": {
			"email": spec.account_email,
			"password": spec.password,
			"role": spec.account_role,
		},
		"staff": staff_name,
		"team": team,
		"pool": pool,
		"students": students,
	}


def execute() -> dict[str, Any]:
	"""Create the local CTV Sale account and three assigned Student cases."""
	return execute_seed(SEED_SPEC)
