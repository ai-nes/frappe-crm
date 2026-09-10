"""Seed the local Team-management fixture used by dashboard-crm.

The fixture is intentionally local-only and repeatable.  It keeps exactly two
active province Groups with three active Teams each.  Existing fixture Teams
from earlier iterations are deactivated, not deleted; active Zone rows for
those Teams are retired first so historical data remains readable.

Run locally with::

    bench --site crm.localhost execute crm.demo.seed_team_management.execute

All fixture accounts use the local-only password ``12345@``.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import frappe
from frappe.utils import getdate, today
from frappe.utils.password import update_password

from crm.api.user import set_canonical_crm_profile
from crm.demo import seed_lead_api_lookups, seed_role_accounts, seed_showcase, seed_staff

LOCAL_SITE = "crm.localhost"
FIXTURE_PASSWORD = "12345@"
FIXTURE_CAMPUS = "FPTU Ho Chi Minh Campus"
FIXTURE_DEPARTMENT = seed_staff.FIXTURE_DEPARTMENT_NAME

GROUP_FIXTURES: tuple[dict[str, Any], ...] = (
	{
		"name": "Phân nhóm Tuyển sinh Hồ Chí Minh",
		"province": "Ho Chi Minh City",
		"group_lead_email": "nguyen.hai.nam@fpt.edu.vn",
		"legacy_names": ("Phân nhóm Tuyển sinh TP.HCM",),
		"teams": (
			{
				"name": "Đội Tư vấn Quận 1 - TP.HCM",
				"lead_email": "tran.minh.anh@fpt.edu.vn",
				"members": (
					("tran.minh.anh@fpt.edu.vn", "Sale"),
					("vo.ngoc.lan@fpt.edu.vn", "CTV Sale"),
				),
			},
			{
				"name": "Đội Tư vấn Thủ Đức - TP.HCM",
				"lead_email": "dang.hoang.long@fpt.edu.vn",
				"members": (
					("dang.hoang.long@fpt.edu.vn", "Sale"),
					("nguyen.thuy.linh@fpt.edu.vn", "CTV Sale"),
				),
			},
			{
				"name": "Đội Tư vấn Bình Chánh - TP.HCM",
				"lead_email": "le.bao.chau@fpt.edu.vn",
				"members": (
					("le.bao.chau@fpt.edu.vn", "Sale"),
					("do.minh.quan@fpt.edu.vn", "CTV Sale"),
				),
			},
		),
	},
	{
		"name": "Phân nhóm Tuyển sinh Đồng Nai",
		"province": "Đồng Nai",
		"group_lead_email": "nguyen.thao.vy@fpt.edu.vn",
		"legacy_names": (),
		"teams": (
			{
				"name": "Đội Tư vấn Biên Hòa - Đồng Nai",
				"lead_email": "le.hoang.phuc@fpt.edu.vn",
				"members": (
					("le.hoang.phuc@fpt.edu.vn", "Sale"),
					("dang.ngoc.ha@fpt.edu.vn", "CTV Sale"),
				),
			},
			{
				"name": "Đội Tư vấn Long Thành - Đồng Nai",
				"lead_email": "nguyen.thu.ha@fpt.edu.vn",
				"members": (
					("nguyen.thu.ha@fpt.edu.vn", "Sale"),
					("tran.anh.khoa@fpt.edu.vn", "CTV Sale"),
				),
			},
			{
				"name": "Đội Tư vấn Trảng Bom - Đồng Nai",
				"lead_email": "bui.ngoc.mai@fpt.edu.vn",
				"members": (
					("bui.ngoc.mai@fpt.edu.vn", "Sale"),
					("vo.thanh.dat@fpt.edu.vn", "CTV Sale"),
				),
			},
		),
	},
)

CATALOG_FIXTURES: tuple[dict[str, Any], ...] = (
	{
		"province": "Ho Chi Minh City",
		"cluster": {"name": "TP.HCM - Tuyển sinh", "code": "HCM-TS"},
		"zones": (
			{
				"name": "TP.HCM - Khu trung tâm (Quận 5)",
				"code": "HCM-CENTRAL",
				"ward": {"code": "760", "name": "Bến Nghé"},
			},
		),
		"schools": (
			{"name": "THPT Chuyên Lê Hồng Phong", "code": "HCM-LHP", "ward_code": "760"},
			{"name": "THPT Nguyễn Thượng Hiền", "code": "HCM-NTH", "ward_code": "760"},
			{"name": "THPT Gia Định", "code": "HCM-GD", "ward_code": "760"},
			{"name": "THPT Nguyễn Hữu Huân", "code": "HCM-NHH", "ward_code": "760"},
			{"name": "THPT Thủ Đức", "code": "HCM-TD", "ward_code": "760"},
		),
	},
	{
		"province": "Đồng Nai",
		"cluster": {"name": "Đồng Nai - Tuyển sinh", "code": "DNI-TS"},
		"zones": (
			{
				"name": "Đồng Nai - Khu Biên Hòa",
				"code": "DNI-BIEN-HOA",
				"ward": {"code": "DNI-BH", "name": "Biên Hòa"},
			},
			{
				"name": "Đồng Nai - Khu Long Thành",
				"code": "DNI-LONG-THANH",
				"ward": {"code": "DNI-LT", "name": "Long Thành"},
			},
			{
				"name": "Đồng Nai - Khu Trảng Bom",
				"code": "DNI-TRANG-BOM",
				"ward": {"code": "DNI-TB", "name": "Trảng Bom"},
			},
		),
		"schools": (
			{"name": "THPT Ngô Quyền", "code": "DNI-NGO-QUYEN", "ward_code": "DNI-BH"},
			{"name": "THPT Trấn Biên", "code": "DNI-TRAN-BIEN", "ward_code": "DNI-BH"},
			{"name": "THPT Long Thành", "code": "DNI-LONG-THANH", "ward_code": "DNI-LT"},
			{"name": "THPT Bình Sơn", "code": "DNI-BINH-SON", "ward_code": "DNI-LT"},
			{"name": "THPT Trảng Bom", "code": "DNI-TRANG-BOM", "ward_code": "DNI-TB"},
			{"name": "THPT Thống Nhất", "code": "DNI-THONG-NHAT", "ward_code": "DNI-TB"},
		),
	},
)

STAFF_FIXTURES: tuple[dict[str, str], ...] = (
	{"full_name": "Nguyễn Hải Nam", "email": "nguyen.hai.nam@fpt.edu.vn", "role": "Lead Sale"},
	{"full_name": "Trần Minh Anh", "email": "tran.minh.anh@fpt.edu.vn", "role": "Sale"},
	{"full_name": "Võ Ngọc Lan", "email": "vo.ngoc.lan@fpt.edu.vn", "role": "CTV Sale"},
	{"full_name": "Phạm Gia Huy", "email": "pham.gia.huy@fpt.edu.vn", "role": "Lead Sale"},
	{"full_name": "Đặng Hoàng Long", "email": "dang.hoang.long@fpt.edu.vn", "role": "Sale"},
	{"full_name": "Nguyễn Thùy Linh", "email": "nguyen.thuy.linh@fpt.edu.vn", "role": "CTV Sale"},
	{"full_name": "Đinh Quốc Duy", "email": "dinh.quoc.duy@fpt.edu.vn", "role": "Lead Sale"},
	{"full_name": "Lê Bảo Châu", "email": "le.bao.chau@fpt.edu.vn", "role": "Sale"},
	{"full_name": "Đỗ Minh Quân", "email": "do.minh.quan@fpt.edu.vn", "role": "CTV Sale"},
	{"full_name": "Nguyễn Thảo Vy", "email": "nguyen.thao.vy@fpt.edu.vn", "role": "Lead Sale"},
	{"full_name": "Lê Hoàng Phúc", "email": "le.hoang.phuc@fpt.edu.vn", "role": "Sale"},
	{"full_name": "Đặng Ngọc Hà", "email": "dang.ngoc.ha@fpt.edu.vn", "role": "CTV Sale"},
	{"full_name": "Lê Thanh Bình", "email": "le.thanh.binh@fpt.edu.vn", "role": "Lead Sale"},
	{"full_name": "Nguyễn Thu Hà", "email": "nguyen.thu.ha@fpt.edu.vn", "role": "Sale"},
	{"full_name": "Trần Anh Khoa", "email": "tran.anh.khoa@fpt.edu.vn", "role": "CTV Sale"},
	{"full_name": "Phạm Nhật Minh", "email": "pham.nhat.minh@fpt.edu.vn", "role": "Lead Sale"},
	{"full_name": "Bùi Ngọc Mai", "email": "bui.ngoc.mai@fpt.edu.vn", "role": "Sale"},
	{"full_name": "Võ Thành Đạt", "email": "vo.thanh.dat@fpt.edu.vn", "role": "CTV Sale"},
)


def _assert_local_site() -> None:
	if getattr(frappe.local, "site", None) != LOCAL_SITE:
		frappe.throw("Bộ seed Team chỉ được chạy trên crm.localhost.", frappe.ValidationError)


def _ensure_staff(spec: dict[str, str], campus: str, department: str) -> str:
	email = spec["email"]
	user = frappe.get_doc("User", email) if frappe.db.exists("User", email) else None
	if not user:
		first_name, _, last_name = spec["full_name"].partition(" ")
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
	user.full_name = spec["full_name"]
	user.enabled = 1
	user.language = "vi"
	set_canonical_crm_profile(user, spec["role"])
	user.save(ignore_permissions=True)
	update_password(user=email, pwd=FIXTURE_PASSWORD, logout_all_sessions=True)

	staff_name = frappe.db.get_value("CRM Staff", {"user": email}, "name")
	if staff_name:
		staff = frappe.get_doc("CRM Staff", staff_name)
	else:
		staff = frappe.get_doc(
			{
				"doctype": "CRM Staff",
				"full_name": spec["full_name"],
				"user": email,
				"department": department,
				"campus": campus,
				"is_active": 1,
			}
		).insert(ignore_permissions=True)
		staff_name = staff.name
	staff.full_name = spec["full_name"]
	staff.department = department
	staff.campus = campus
	staff.is_active = 1
	staff.save(ignore_permissions=True)
	return staff_name


def _ensure_catalog_province(province_name: str) -> str:
	province = frappe.db.exists("CRM Province", province_name)
	if not province:
		# The assignment fixture keeps legacy English labels, while the current
		# province catalog may already contain the Vietnamese canonical label.
		# Reuse that row so existing Cluster/Zone parents are never re-parented.
		from crm.api.lead_mapping import _resolve_province

		try:
			province = _resolve_province(province_name)
		except frappe.ValidationError:
			province = None
		if province and frappe.db.exists("CRM Province", province):
			return province
	if not province:
		province = (
			frappe.get_doc(
				{
					"doctype": "CRM Province",
					"province_name": province_name,
					"province_code": f"LOCAL-{province_name.upper().replace(' ', '-').replace('Đ', 'D')}",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
	return province


def _ensure_catalog_geography(fixture: dict[str, Any]) -> dict[str, str]:
	province = _ensure_catalog_province(fixture["province"])
	cluster_spec = fixture["cluster"]
	cluster = frappe.db.exists("CRM Cluster", cluster_spec["name"])
	if cluster:
		cluster_doc = frappe.get_doc("CRM Cluster", cluster)
		cluster_doc.province = province
		cluster_doc.cluster_code = cluster_spec["code"]
		cluster_doc.is_active = 1
		cluster_doc.save(ignore_permissions=True)
	else:
		cluster = (
			frappe.get_doc(
				{
					"doctype": "CRM Cluster",
					"cluster_name": cluster_spec["name"],
					"cluster_code": cluster_spec["code"],
					"province": province,
					"is_active": 1,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	ward_by_code = {}
	for zone_spec in fixture["zones"]:
		zone = frappe.db.exists("CRM Zone", zone_spec["name"])
		if zone:
			zone_doc = frappe.get_doc("CRM Zone", zone)
			zone_doc.cluster = cluster
			zone_doc.zone_code = zone_spec["code"]
			zone_doc.save(ignore_permissions=True)
		else:
			zone = (
				frappe.get_doc(
					{
						"doctype": "CRM Zone",
						"zone_name": zone_spec["name"],
						"zone_code": zone_spec["code"],
						"cluster": cluster,
						"assignment_status": "Unassigned",
					}
				)
				.insert(ignore_permissions=True)
				.name
			)
		ward_spec = zone_spec["ward"]
		ward_name = frappe.db.exists("CRM Ward", {"ward_code": ward_spec["code"], "province": province})
		if ward_name:
			ward_doc = frappe.get_doc("CRM Ward", ward_name)
			ward_doc.ward_name = ward_spec["name"]
			ward_doc.zone = zone
			ward_doc.province_name = fixture["province"]
			ward_doc.save(ignore_permissions=True)
		else:
			ward_name = (
				frappe.get_doc(
					{
						"doctype": "CRM Ward",
						"ward_code": ward_spec["code"],
						"ward_name": ward_spec["name"],
						"zone": zone,
						"province": province,
						"province_name": fixture["province"],
					}
				)
				.insert(ignore_permissions=True)
				.name
			)
		ward_by_code[ward_spec["code"]] = ward_name
	return {"province": province, "cluster": cluster, **ward_by_code}


def _ensure_catalog_schools(fixture: dict[str, Any], geography: dict[str, str]) -> list[str]:
	created_or_updated = []
	for school_spec in fixture["schools"]:
		ward = geography.get(school_spec["ward_code"])
		if not ward:
			frappe.throw(
				f"Thiếu địa bàn {school_spec['ward_code']} cho trường {school_spec['name']}.",
				frappe.ValidationError,
			)
		filters = {
			"school_code": school_spec["code"],
			"province": geography["province"],
			"ward": ward,
		}
		school_name = frappe.db.exists("CRM High School", filters)
		if school_name:
			school = frappe.get_doc("CRM High School", school_name)
			school.school_name = school_spec["name"]
			school.is_active = 1
			school.save(ignore_permissions=True)
		else:
			school = frappe.get_doc(
				{
					"doctype": "CRM High School",
					"school_name": school_spec["name"],
					"school_code": school_spec["code"],
					"province": geography["province"],
					"ward": ward,
					"is_active": 1,
				}
			).insert(ignore_permissions=True)
		created_or_updated.append(school.name)
	return created_or_updated


def _ensure_catalog_majors() -> dict[str, Any]:
	created = 0
	majors = []
	for spec in seed_lead_api_lookups.PUBLIC_LEAD_MAJORS:
		name, was_created = seed_lead_api_lookups._ensure_major(spec)
		created += int(was_created)
		majors.append({"name": name, "code": spec["code"], "label": spec["name"]})
	return {"created": created, "total": len(majors), "majors": majors}


def _remove_scroll_fixture_schools() -> dict[str, int]:
	"""Delete only synthetic scroll schools that have no business links."""
	rows = frappe.get_all(
		"CRM High School",
		filters={"school_code": ["like", "ASSIGN-SCROLL-%"]},
		fields=["name", "school_name", "school_code"],
		limit_page_length=0,
	)
	deleted = 0
	kept = 0
	for row in rows:
		linked = any(
			frappe.db.exists(doctype, {"high_school": row.name})
			for doctype in ("CRM Lead", "CRM Student", "CRM Contact")
			if frappe.db.exists("DocType", doctype)
		)
		if linked:
			kept += 1
			continue
		frappe.delete_doc("CRM High School", row.name, ignore_permissions=True, force=True)
		deleted += 1
	return {"deleted": deleted, "kept_with_links": kept}


def _ensure_assignment_catalogs() -> dict[str, Any]:
	geography = []
	schools = []
	for fixture in CATALOG_FIXTURES:
		resolved = _ensure_catalog_geography(fixture)
		geography.append(
			{
				"province": resolved["province"],
				"cluster": resolved["cluster"],
				"zones": len(fixture["zones"]),
			}
		)
		schools.extend(_ensure_catalog_schools(fixture, resolved))
	majors = _ensure_catalog_majors()
	return {
		"geography": geography,
		"schools_managed": len(schools),
		"majors": majors,
		"scroll_fixture_cleanup": _remove_scroll_fixture_schools(),
	}


def _ensure_group(fixture: dict[str, Any], staff_by_email: dict[str, str]) -> str:
	province = _ensure_catalog_province(fixture["province"])
	if not province:
		frappe.throw(f"Thiếu tỉnh {fixture['province']} để seed Group.", frappe.ValidationError)
	group_name = frappe.db.exists("CRM Team Group", fixture["name"])
	if not group_name:
		for legacy_name in fixture["legacy_names"]:
			if frappe.db.exists("CRM Team Group", legacy_name):
				frappe.rename_doc("CRM Team Group", legacy_name, fixture["name"], force=True)
				group_name = fixture["name"]
				break
	if group_name:
		group = frappe.get_doc("CRM Team Group", group_name)
	else:
		group = frappe.get_doc(
			{
				"doctype": "CRM Team Group",
				"group_name": fixture["name"],
				"province": province,
				"is_active": 1,
			}
		).insert(ignore_permissions=True)
	group.province = province
	group.is_active = 1
	group.group_lead_staff = staff_by_email[fixture["group_lead_email"]]
	group.save(ignore_permissions=True)
	return group.name


def _ensure_membership(staff, team_name: str, function: str, is_team_lead: bool) -> None:
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


def _remove_unlisted_members(team_name: str, keep_staff: set[str]) -> None:
	for staff_name in frappe.get_all(
		"CRM Staff",
		filters={"is_active": 1},
		pluck="name",
		limit_page_length=0,
	):
		staff = frappe.get_doc("CRM Staff", staff_name)
		changed = False
		for membership in list(staff.team_memberships):
			if membership.team == team_name and staff.name not in keep_staff:
				staff.remove(membership)
				changed = True
		if changed:
			staff.save(ignore_permissions=True)


def _remove_legacy_fixture_memberships(staff_by_email: dict[str, str]) -> None:
	"""Detach this fixture's accounts from teams from earlier local seeds."""
	fixture_staff = set(staff_by_email.values())
	fixture_teams = {team["name"] for group in GROUP_FIXTURES for team in group["teams"]}
	for staff_name in fixture_staff:
		staff = frappe.get_doc("CRM Staff", staff_name)
		changed = False
		for membership in list(staff.team_memberships):
			if membership.team not in fixture_teams:
				staff.remove(membership)
				changed = True
		if changed:
			staff.save(ignore_permissions=True)


def _ensure_team(group: str, fixture: dict[str, Any], staff_by_email: dict[str, str], campus: str) -> str:
	team_name = frappe.db.exists("CRM Team", fixture["name"])
	team = frappe.get_doc("CRM Team", team_name) if team_name else None
	if not team:
		team = frappe.get_doc(
			{
				"doctype": "CRM Team",
				"team_name": fixture["name"],
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
	keep_staff = {staff_by_email[email] for email, _ in fixture["members"]}
	_remove_unlisted_members(team.name, keep_staff)
	for email, function in fixture["members"]:
		staff = frappe.get_doc("CRM Staff", staff_by_email[email])
		_ensure_membership(staff, team.name, function, email == fixture["lead_email"])
		staff.save(ignore_permissions=True)
	team.team_lead_staff = staff_by_email[fixture["lead_email"]]
	team.save(ignore_permissions=True)
	return team.name


def _retire_active_zone_assignments(team_name: str) -> int:
	rows = frappe.get_all(
		"CRM Team Zone Assignment",
		filters={"team": team_name, "status": "Active"},
		fields=["name", "zone"],
		limit_page_length=0,
	)
	for row in rows:
		frappe.db.set_value(
			"CRM Team Zone Assignment",
			row.name,
			{"status": "Retired", "effective_until": getdate(today()) - timedelta(days=1)},
			update_modified=False,
		)
		if row.zone:
			frappe.db.set_value(
				"CRM Zone",
				row.zone,
				{"current_team": None, "assignment_status": "Unassigned"},
				update_modified=False,
			)
	return len(rows)


def _deactivate_obsolete_teams(group_names: set[str], keep_team_names: set[str]) -> list[str]:
	retired = []
	retired_group = frappe.db.exists("CRM Team Group", "Nhóm chưa thiết lập")
	for row in frappe.get_all(
		"CRM Team",
		filters={"group": ["in", sorted(group_names)]},
		fields=["name", "group", "is_active", "team_lead_staff"],
		limit_page_length=0,
	):
		if row.name in keep_team_names:
			continue
		_retire_active_zone_assignments(row.name)
		team = frappe.get_doc("CRM Team", row.name)
		was_managed = bool(team.is_active or team.team_lead_staff or team.group != retired_group)
		team.is_active = 0
		team.team_lead_staff = None
		if retired_group:
			team.group = retired_group
		if was_managed:
			team.save(ignore_permissions=True)
			retired.append(row.name)
	return retired


def _catalog_summary(provinces: tuple[str, ...]) -> dict[str, Any]:
	return {
		"provinces": [
			{
				"name": province,
				"schools": frappe.db.count(
					"CRM High School", {"province": _ensure_catalog_province(province)}
				),
			}
			for province in provinces
		],
		"majors": frappe.db.count("CRM Major", {"is_active": 1}),
		"sources": frappe.db.count("CRM Lead Source", {"approval_state": ["!=", "Retired"]}),
	}


def execute() -> dict[str, Any]:
	"""Reset the managed local fixture and return login details for QA."""
	_assert_local_site()
	frappe.set_user("Administrator")
	seed_showcase.ensure_local_integrity_keys()
	seed_role_accounts.execute()
	lookup_result = _ensure_assignment_catalogs()

	campus = frappe.db.exists("CRM Campus", FIXTURE_CAMPUS)
	if not campus:
		frappe.throw(f"Thiếu cơ sở {FIXTURE_CAMPUS} để seed Team.", frappe.ValidationError)
	department = frappe.db.exists("CRM Department", FIXTURE_DEPARTMENT)
	if not department:
		department = seed_staff._ensure_fixture_department(campus)
	staff_by_email = {spec["email"]: _ensure_staff(spec, campus, department) for spec in STAFF_FIXTURES}
	_remove_legacy_fixture_memberships(staff_by_email)
	groups = []
	group_names_before = set()
	for fixture in GROUP_FIXTURES:
		group_names_before.update(fixture["legacy_names"])
		group_names_before.add(fixture["name"])
		group_name = _ensure_group(fixture, staff_by_email)
		teams = [_ensure_team(group_name, team, staff_by_email, campus) for team in fixture["teams"]]
		groups.append({"name": group_name, "province": fixture["province"], "teams": teams})

	keep_team_names = {team for group in groups for team in group["teams"]}
	managed_groups = {
		row.name
		for row in frappe.get_all(
			"CRM Team Group",
			filters={"name": ["in", sorted(group_names_before)]},
			fields=["name"],
			limit_page_length=0,
		)
	}
	managed_groups.update(group["name"] for group in groups)
	retired_teams = _deactivate_obsolete_teams(managed_groups, keep_team_names)
	frappe.db.commit()

	return {
		"groups": groups,
		"active_team_count": len(keep_team_names),
		"retired_team_count": len(retired_teams),
		"retired_teams": retired_teams,
		"campus": campus,
		"catalog": _catalog_summary(tuple(fixture["province"] for fixture in GROUP_FIXTURES)),
		"lookup_seed": lookup_result,
		"password": FIXTURE_PASSWORD,
		"admin_accounts": [
			{"email": "admin@gmail.com", "role": "Administrator"},
			{"email": "admissionsdirector@gmail.com", "role": "Admissions Director"},
		],
		"team_accounts": [
			{"email": spec["email"], "name": spec["full_name"], "role": spec["role"]}
			for spec in STAFF_FIXTURES
		],
		"message": "Đã seed 2 Group tỉnh, mỗi Group 3 Team và catalog Lead trên local.",
	}
