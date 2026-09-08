"""Seed a 20-Lead assignment fixture covering the happy and the defect paths.

Run locally with::

    bench --site crm.localhost execute crm.demo.seed_assignment_conversion_scenarios.execute

Every Lead lands in ``NEW``, so the operator runs the two intake steps in order:
``Xử lý Lead`` promotes the intake-complete ones to ``PROCESSED``, then
``Phân công Lead`` assigns an active Sale/CTV and immediately creates an owned
``CRM Student`` for each of the twelve valid ones. The remaining eight carry
exactly one defect apiece so the operator can see every non-assigning outcome of
``crm.api.lead_processing`` and ``crm.api.lead_assignment_batch`` --
``manual_review`` for an INVALID identifier gate, a DUPLICATE CCCD pair, a
missing province, a missing campus and a province no Team manages.

Every Lead -- defective ones included -- is submitted through the canonical
intake command (``crm.fcrm.student_intake.submit_intake``) with valid data, then
the defect is stamped onto the persisted Lead. Only that command writes the
Student Identity, the Case Key and ``intake_integrity_state``; a Lead inserted
straight into ``CRM Lead`` would be rejected by conversion with
``INTEGRITY_UNRESOLVED`` and would therefore test the wrong failure.
"""

from __future__ import annotations

from typing import Any

import frappe

from crm.demo import seed_assignment_scenarios, seed_team_management
from crm.fcrm.student_feature_flags import enabled

LOCAL_SITE = "crm.localhost"
NAMESPACE = "local-assignment-conversion-20260908"
CAMPUS = "FPTU Ho Chi Minh Campus"
ADMISSION_YEAR = "2026"
POOL_PREFIX = "Hàng chờ phân công"

# A Province row that exists in the catalog but that no active Sales Team
# manages, so routing can only answer TEAM_NOT_FOUND_FOR_PROVINCE.
UNMANAGED_PROVINCE = "Hà Nội"

# The CCCD the duplicate pair collapses onto. It is scenario 19's own value, so
# `_classify_resolution` sees two Leads with one identifier and closes both as
# DUPLICATE -- the shape a real double submission takes.
DUPLICATE_ID = "079303000019"

SCENARIOS: tuple[dict[str, Any], ...] = (
	# --- Happy path: 12 intake-complete Leads, 6 per province ------------------
	{
		"name": "Nguyễn Minh Anh",
		"phone": "0903000001",
		"province": "Ho Chi Minh City",
		"school": "THPT Chuyên Lê Hồng Phong",
		"major": "Software Engineering",
		"id": "079303000001",
	},
	{
		"name": "Trần Gia Hân",
		"phone": "0903000002",
		"province": "Ho Chi Minh City",
		"school": "THPT Nguyễn Thượng Hiền",
		"major": "Artificial Intelligence",
		"id": "079303000002",
	},
	{
		"name": "Lê Hoàng Nam",
		"phone": "0903000003",
		"province": "Ho Chi Minh City",
		"school": "THPT Gia Định",
		"major": "Data Science",
		"id": "079303000003",
	},
	{
		"name": "Phạm Khánh Linh",
		"phone": "0903000004",
		"province": "Ho Chi Minh City",
		"school": "THPT Nguyễn Hữu Huân",
		"major": "Digital Marketing",
		"id": "079303000004",
	},
	{
		"name": "Võ Đức Anh",
		"phone": "0903000005",
		"province": "Ho Chi Minh City",
		"school": "THPT Thủ Đức",
		"major": "Business Administration",
		"id": "079303000005",
	},
	{
		"name": "Ngô Bảo Ngọc",
		"phone": "0903000011",
		"province": "Ho Chi Minh City",
		"school": "THPT Chuyên Lê Hồng Phong",
		"major": "Data Science",
		"id": "079303000011",
	},
	{
		"name": "Đặng Quốc Bảo",
		"phone": "0903000006",
		"province": "Đồng Nai",
		"school": "THPT Ngô Quyền",
		"major": "Software Engineering",
		"id": "075303000006",
	},
	{
		"name": "Bùi Thanh Trúc",
		"phone": "0903000007",
		"province": "Đồng Nai",
		"school": "THPT Trấn Biên",
		"major": "Artificial Intelligence",
		"id": "075303000007",
	},
	{
		"name": "Hoàng Minh Khang",
		"phone": "0903000008",
		"province": "Đồng Nai",
		"school": "THPT Long Thành",
		"major": "Data Science",
		"id": "075303000008",
	},
	{
		"name": "Đỗ Quỳnh Anh",
		"phone": "0903000009",
		"province": "Đồng Nai",
		"school": "THPT Bình Sơn",
		"major": "Digital Marketing",
		"id": "075303000009",
	},
	{
		"name": "Phan Nhật Vy",
		"phone": "0903000010",
		"province": "Đồng Nai",
		"school": "THPT Trảng Bom",
		"major": "Business Administration",
		"id": "075303000010",
	},
	{
		"name": "Trịnh Gia Bảo",
		"phone": "0903000012",
		"province": "Đồng Nai",
		"school": "THPT Thống Nhất",
		"major": "Software Engineering",
		"id": "075303000012",
	},
	# --- Defect path: 8 Leads, one failure mode each ---------------------------
	{
		"name": "Lý Thu Trang",
		"phone": "0903000013",
		"province": "Ho Chi Minh City",
		"school": "THPT Gia Định",
		"major": "Data Science",
		"id": "079303000013",
		"defect": {
			"code": "INVALID_MISSING_MAJOR",
			"expected": "manual_review",
			"note": "Thiếu ngành quan tâm → xử lý Lead trả INVALID.",
			"fields": {"major": None},
		},
	},
	{
		"name": "Hà Tuấn Kiệt",
		"phone": "0903000014",
		"province": "Ho Chi Minh City",
		"school": "THPT Thủ Đức",
		"major": "Digital Marketing",
		"id": "079303000014",
		"defect": {
			"code": "INVALID_MISSING_HIGH_SCHOOL",
			"expected": "manual_review",
			"note": "Thiếu trường THPT → xử lý Lead trả INVALID.",
			"fields": {"high_school": None},
		},
	},
	{
		"name": "Mai Phương Thảo",
		"phone": "0903000015",
		"province": "Đồng Nai",
		"school": "THPT Ngô Quyền",
		"major": "Business Administration",
		"id": "075303000015",
		"defect": {
			"code": "INVALID_MISSING_ID_NUMBER",
			"expected": "manual_review",
			"note": "Thiếu CCCD → xử lý Lead trả INVALID.",
			"fields": {"id_number": None},
		},
	},
	{
		"name": "Chu Anh Tú",
		"phone": "0903000016",
		"province": "Đồng Nai",
		"school": "THPT Trấn Biên",
		"major": "Software Engineering",
		"id": "075303000016",
		"defect": {
			"code": "MISSING_PROVINCE",
			"expected": "manual_review",
			"note": "Không có tỉnh → batch không tìm được Team quản lý.",
			"fields": {"province": None},
		},
	},
	{
		"name": "Tạ Hoàng Sơn",
		"phone": "0903000017",
		"province": "Ho Chi Minh City",
		"school": "THPT Nguyễn Thượng Hiền",
		"major": "Artificial Intelligence",
		"id": "079303000017",
		"defect": {
			"code": "MISSING_CAMPUS",
			"expected": "manual_review",
			"note": "Không có cơ sở → batch dừng trước khi chọn người nhận.",
			"fields": {"branch": None},
		},
	},
	{
		"name": "Dương Khánh Chi",
		"phone": "0903000018",
		"province": "Ho Chi Minh City",
		"school": "THPT Nguyễn Hữu Huân",
		"major": "Data Science",
		"id": "079303000018",
		"defect": {
			"code": "TEAM_NOT_FOUND_FOR_PROVINCE",
			"expected": "manual_review",
			"note": f"Tỉnh {UNMANAGED_PROVINCE} chưa có Team Sales nào quản lý.",
			"fields": {"province": UNMANAGED_PROVINCE},
		},
	},
	{
		"name": "Vũ Đình Phong",
		"phone": "0903000019",
		"province": "Đồng Nai",
		"school": "THPT Long Thành",
		"major": "Digital Marketing",
		"id": DUPLICATE_ID,
		"defect": {
			"code": "DUPLICATE_PRIMARY",
			"expected": "manual_review",
			"note": "Bản ghi gốc của cặp trùng CCCD.",
			"fields": {},
		},
	},
	{
		"name": "Vũ Đình Phong (nộp lại)",
		"phone": "0903000020",
		"province": "Đồng Nai",
		"school": "THPT Long Thành",
		"major": "Digital Marketing",
		"id": "075303000020",
		"defect": {
			"code": "DUPLICATE_RESUBMIT",
			"expected": "manual_review",
			"note": "Nộp lại cùng CCCD → cả hai Lead đóng với resolution DUPLICATE.",
			"fields": {"id_number": DUPLICATE_ID},
		},
	},
)


def _assert_local_site() -> None:
	if getattr(frappe.local, "site", None) != LOCAL_SITE:
		frappe.throw("Bộ seed Lead → Student chỉ được chạy trên crm.localhost.", frappe.ValidationError)


def _lookup(doctype: str, value: str, fieldname: str) -> str:
	return frappe.db.get_value(doctype, {fieldname: value}, "name") or value


def _purge_identity_graph() -> dict[str, int]:
	"""Drop the intake identity graph left behind by earlier fixture runs.

	``_purge_business_data`` removes Leads and every row linking to one, but a
	``CRM Student Identity`` links to nothing and therefore survives, still
	holding the phone/email observations of the deleted Leads. Reusing a seeded
	phone next to a different seeded email then resolves to two identity roots
	and intake answers ``review_required`` instead of ``created`` -- the fixture
	would silently stop testing assignment at all. A local fixture owns its
	identifiers outright, so the graph is rebuilt with the Leads.
	"""
	deleted: dict[str, int] = {}
	for doctype in ("CRM Student Intake Review", "CRM Student Case Key", "CRM Student Identity"):
		if not frappe.db.table_exists(doctype):
			continue
		deleted[doctype] = frappe.db.count(doctype)
		frappe.db.sql(f"delete from `tab{doctype}`")
	if frappe.db.table_exists("CRM Student Identity Identifier"):
		frappe.db.sql(
			"delete from `tabCRM Student Identity Identifier` where parenttype = 'CRM Student Identity'"
		)
	return deleted


def _team_by_province() -> dict[str, str]:
	"""Pick one active Sales Team per seeded province group.

	The Lead enters the pool of the first Team of its own province group, which
	is exactly what a province intake queue looks like before routing runs.
	"""
	return {
		fixture["province"]: fixture["teams"][0]["name"] for fixture in seed_team_management.GROUP_FIXTURES
	}


def _ensure_pool(team: str) -> str:
	"""Ensure the Team has an active input queue for intake to write into.

	``submit_intake`` refuses a pool whose Team is not an active Sales Team at
	the Campus, so the queue has to follow the Team topology this seed just
	rebuilt rather than any older fixture pool.
	"""
	row = frappe.db.get_value("CRM Team", team, ["name", "campus", "team_type", "is_active"], as_dict=True)
	if not row or not row.is_active or row.team_type != "Sales":
		frappe.throw(f"Team {team} không hoạt động để nhận Lead.", frappe.ValidationError)
	pool_name = f"{POOL_PREFIX} - {team}"
	existing = frappe.db.get_value("CRM Student Pool", {"pool_name": pool_name}, "name")
	if existing:
		frappe.db.set_value(
			"CRM Student Pool",
			existing,
			{"team": row.name, "campus": row.campus, "is_active": 1},
		)
		return existing
	return (
		frappe.get_doc(
			{
				"doctype": "CRM Student Pool",
				"pool_name": pool_name,
				"team": row.name,
				"campus": row.campus,
				"is_active": 1,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _apply_defect(lead: str, defect: dict[str, Any]) -> None:
	"""Stamp one defect onto a Lead that intake has already accepted.

	The defect is written after the command so the Lead keeps the identity and
	integrity stamps only ``submit_intake`` can produce. That is what makes the
	fixture exercise the assignment gate under test rather than the intake
	integrity gate, which would reject every one of these Leads first.
	"""
	updates = {field: value for field, value in defect.get("fields", {}).items()}
	if updates:
		frappe.db.set_value("CRM Lead", lead, updates, update_modified=False)


def _submit_lead(spec: dict[str, Any], source: str, index: int, pool: str, run_token: str) -> str:
	"""Create one intake-complete Lead sitting unassigned in its province pool."""
	from crm.fcrm.student_intake import submit_intake

	payload = {
		"student_name": spec["name"],
		"phone": spec["phone"],
		# Keyed on the phone, not the list position: phone and email are the only
		# identity roots intake looks up, so a scenario keeps the same pair even
		# when the fixture is reordered or extended.
		"email": f"local.assignment.conversion.{spec['phone']}@example.test",
		"id_number": spec["id"],
		"campus": CAMPUS,
		"owning_team": pool,
		"admission_year": ADMISSION_YEAR,
		"enrollment_status": "NEW",
		"province": _lookup("CRM Province", spec["province"], "province_name"),
		"high_school": _lookup("CRM High School", spec["school"], "school_name"),
		"major": _lookup("CRM Major", spec["major"], "major_name"),
		"current_grade": "12",
		"study_stage": "grade_12_h2",
		"source": source,
		"consent": {
			"granted": True,
			"granted_at": str(frappe.utils.now_datetime()),
			"purpose": "admissions_counseling",
			"scope": "student_profile_and_parent_follow_up",
			"source": NAMESPACE,
		},
	}
	result = submit_intake(
		payload,
		source_namespace=NAMESPACE,
		source_record_id=f"lead:{spec['phone']}",
		# Each reseed is a new command: the previous run's Leads were purged, so
		# replaying its receipt would return a Lead that no longer exists.
		idempotency_key=f"{NAMESPACE}:{run_token}:{index:02d}",
		correlation_id=f"{NAMESPACE}:{run_token}:{index:02d}",
	)
	lead = result.get("student")
	if result.get("outcome") != "created" or not lead:
		frappe.throw(f"Intake không tạo được Lead {spec['name']}: {result}", frappe.ValidationError)
	defect = spec.get("defect")
	notes = (
		f"Local defect {defect['code']}: {defect['note']} → {defect['expected']}."
		if defect
		else "Local happy-path: assignment creates an owned CRM Student."
	)
	frappe.db.set_value(
		"CRM Lead",
		lead,
		{"notes": notes, "import_source_id": f"{NAMESPACE}:{spec['phone']}"},
		update_modified=False,
	)
	if defect:
		_apply_defect(lead, defect)
	return lead


def execute() -> dict[str, Any]:
	"""Reset local Lead/Student rows and seed the 20-Lead assignment fixture."""
	_assert_local_site()
	if not enabled("conversion_write"):
		frappe.throw(
			"conversion_write đang tắt; hãy bật quyền ghi chuyển Lead → Student trước khi test.",
			frappe.ValidationError,
		)
	frappe.set_user("Administrator")
	seed_team_management.execute()
	deleted = seed_assignment_scenarios._purge_business_data()
	purged_identities = _purge_identity_graph()
	source = seed_assignment_scenarios._active_source()
	pools = {province: _ensure_pool(team) for province, team in _team_by_province().items()}
	run_token = frappe.generate_hash(length=10)
	seeded: list[dict[str, Any]] = []
	for index, spec in enumerate(SCENARIOS, start=1):
		lead = _submit_lead(spec, source, index, pools[spec["province"]], run_token)
		defect = spec.get("defect")
		seeded.append(
			{
				"lead": lead,
				"name": spec["name"],
				"expected": defect["expected"] if defect else "assigned",
				"defect": defect["code"] if defect else None,
			}
		)
	frappe.db.commit()
	happy = [row for row in seeded if row["expected"] == "assigned"]
	return {
		"deleted": deleted,
		"purged_identities": purged_identities,
		"seeded_leads": len(seeded),
		"happy_leads": len(happy),
		"defect_leads": len(seeded) - len(happy),
		"students_before_assignment": frappe.db.count("CRM Student"),
		"source": source,
		"pools": pools,
		"leads": seeded,
		"message": (
			f"Đã seed {len(seeded)} Lead ({len(happy)} hợp lệ, {len(seeded) - len(happy)} lỗi). "
			"Bấm Xử lý Lead rồi Phân công Lead: Lead hợp lệ tạo Student có người phụ trách, "
			"Lead lỗi rơi vào cần xem xét thủ công."
		),
	}
