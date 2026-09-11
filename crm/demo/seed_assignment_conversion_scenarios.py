"""Seed a 20-Lead assignment fixture covering the happy and the defect paths.

Run locally with::

    bench --site crm.localhost execute crm.demo.seed_assignment_conversion_scenarios.execute

Every Lead lands in ``NEW``, so the operator runs the two intake steps in order:
``Xử lý Lead`` promotes the intake-complete ones to ``PROCESSED``, then
``Phân công Lead`` assigns an active Sale/CTV without creating a ``CRM Student``.
The remaining defects are closed during processing or routing so the operator
can see each non-assigning outcome of ``crm.api.lead_processing`` and
``crm.api.lead_assignment_batch``.

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
from crm.fcrm.lead_code import is_valid_lead_code

LOCAL_SITE = "crm.localhost"
NAMESPACE = "local-assignment-conversion-20260908"
CAMPUS = "FPTU Ho Chi Minh Campus"
ADMISSION_YEAR = "2026"
POOL_PREFIX = "Hàng chờ phân công"

# A Province row that exists in the catalog but that no active Sales Team
# manages, so routing can only answer TEAM_NOT_FOUND_FOR_PROVINCE.
UNMANAGED_PROVINCE = "Hà Nội"

# The duplicate pair starts with different phone numbers so intake can create
# both Leads. The resubmission is then stamped with the primary phone to
# exercise the Lead duplicate resolver without inventing a CCCD on a Lead.
DUPLICATE_PHONE = "0903000019"
_SPLIT_RECEIPT_LINK_GAP_PATCHED = False


def _intake_namespace(run_token: str) -> str:
	"""Give each fresh local fixture run a distinct immutable intake source."""
	return f"{NAMESPACE}:run:{run_token}"


def _patch_split_receipt_link_gap() -> None:
	"""Keep Lead intake receipts valid while the receipt schema still links Student."""
	global _SPLIT_RECEIPT_LINK_GAP_PATCHED
	if _SPLIT_RECEIPT_LINK_GAP_PATCHED:
		return

	import crm.fcrm.admission_case_key as admission_case_key
	import crm.fcrm.student_intake as student_intake

	original_write_receipt = admission_case_key._write_receipt

	def _write_lead_safe_receipt(**kwargs):
		kwargs.pop("student", None)
		return original_write_receipt(student=None, **kwargs)

	admission_case_key._write_receipt = _write_lead_safe_receipt

	original_persist_receipt = student_intake._persist_receipt

	def _persist_lead_safe_receipt(keys, *, result, **kwargs):
		lead = result.get("student")
		safe_result = dict(result)
		safe_result.pop("student", None)
		persisted = original_persist_receipt(keys, result=safe_result, **kwargs)
		if lead:
			persisted["student"] = lead
		return persisted

	student_intake._persist_receipt = _persist_lead_safe_receipt

	original_persist_consent = student_intake._persist_consent_grant

	def _persist_lead_safe_consent(student, consent, **kwargs):
		if student and frappe.db.exists("CRM Lead", student) and not frappe.db.exists("CRM Student", student):
			return None
		return original_persist_consent(student, consent, **kwargs)

	student_intake._persist_consent_grant = _persist_lead_safe_consent
	_SPLIT_RECEIPT_LINK_GAP_PATCHED = True


def _require_lead_code(lead: str) -> str:
	"""Return the server-managed public Lead code or fail the fixture early."""
	lead_code = frappe.db.get_value("CRM Lead", lead, "lead_code")
	if not lead_code or not is_valid_lead_code(lead_code):
		frappe.throw(
			f"Lead {lead} không có leadCode hợp lệ (kỳ vọng LD-YYYY-REGION-NNNNNN).",
			frappe.ValidationError,
		)
	return lead_code


SCENARIOS: tuple[dict[str, Any], ...] = (
	# --- Happy path: 12 intake-complete Leads, 6 per province ------------------
	{
		"name": "Nguyễn Minh Anh",
		"phone": "0903000001",
		"province": "Ho Chi Minh City",
		"school": "THPT Chuyên Lê Hồng Phong",
		"major": "Software Engineering",
	},
	{
		"name": "Trần Gia Hân",
		"phone": "0903000002",
		"province": "Ho Chi Minh City",
		"school": "THPT Nguyễn Thượng Hiền",
		"major": "Artificial Intelligence",
	},
	{
		"name": "Lê Hoàng Nam",
		"phone": "0903000003",
		"province": "Ho Chi Minh City",
		"school": "THPT Gia Định",
		"major": "Data Science",
	},
	{
		"name": "Phạm Khánh Linh",
		"phone": "0903000004",
		"province": "Ho Chi Minh City",
		"school": "THPT Nguyễn Hữu Huân",
		"major": "Digital Marketing",
	},
	{
		"name": "Võ Đức Anh",
		"phone": "0903000005",
		"province": "Ho Chi Minh City",
		"school": "THPT Thủ Đức",
		"major": "Business Administration",
	},
	{
		"name": "Ngô Bảo Ngọc",
		"phone": "0903000011",
		"province": "Ho Chi Minh City",
		"school": "THPT Chuyên Lê Hồng Phong",
		"major": "Data Science",
	},
	{
		"name": "Đặng Quốc Bảo",
		"phone": "0903000006",
		"province": "Đồng Nai",
		"school": "THPT Ngô Quyền",
		"major": "Software Engineering",
	},
	{
		"name": "Bùi Thanh Trúc",
		"phone": "0903000007",
		"province": "Đồng Nai",
		"school": "THPT Trấn Biên",
		"major": "Artificial Intelligence",
	},
	{
		"name": "Hoàng Minh Khang",
		"phone": "0903000008",
		"province": "Đồng Nai",
		"school": "THPT Long Thành",
		"major": "Data Science",
	},
	{
		"name": "Đỗ Quỳnh Anh",
		"phone": "0903000009",
		"province": "Đồng Nai",
		"school": "THPT Bình Sơn",
		"major": "Digital Marketing",
	},
	{
		"name": "Phan Nhật Vy",
		"phone": "0903000010",
		"province": "Đồng Nai",
		"school": "THPT Trảng Bom",
		"major": "Business Administration",
	},
	{
		"name": "Trịnh Gia Bảo",
		"phone": "0903000012",
		"province": "Đồng Nai",
		"school": "THPT Thống Nhất",
		"major": "Software Engineering",
	},
	# --- Defect path: 8 Leads, one failure mode each ---------------------------
	{
		"name": "Lý Thu Trang",
		"phone": "0903000013",
		"province": "Ho Chi Minh City",
		"school": "THPT Gia Định",
		"major": "Data Science",
		"defect": {
			"code": "INVALID_MISSING_MAJOR",
			"expected": "manual_review",
			"note": "Thiếu ngành quan tâm → xử lý Lead đóng hồ sơ.",
			"fields": {"major": None},
		},
	},
	{
		"name": "Hà Tuấn Kiệt",
		"phone": "0903000014",
		"province": "Ho Chi Minh City",
		"school": "THPT Thủ Đức",
		"major": "Digital Marketing",
		"defect": {
			"code": "INVALID_MISSING_HIGH_SCHOOL",
			"expected": "assigned",
			"note": "Thiếu trường THPT nhưng Lead vẫn hợp lệ → được phân công theo tỉnh.",
			"fields": {"high_school": None},
		},
	},
	{
		"name": "Mai Phương Thảo",
		"phone": "0903000015",
		"province": "Đồng Nai",
		"school": "THPT Ngô Quyền",
		"major": "Business Administration",
		"defect": {
			"code": "INVALID_MISSING_PHONE",
			"expected": "manual_review",
			"note": "Thiếu số điện thoại → xử lý Lead đóng hồ sơ.",
			"fields": {"phone": None},
		},
	},
	{
		"name": "Chu Anh Tú",
		"phone": "0903000016",
		"province": "Đồng Nai",
		"school": "THPT Trấn Biên",
		"major": "Software Engineering",
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
		"defect": {
			"code": "MISSING_CAMPUS",
			"expected": "assigned",
			"note": "Không có cơ sở → vẫn phân công theo tỉnh.",
			"fields": {"branch": None},
		},
	},
	{
		"name": "Dương Khánh Chi",
		"phone": "0903000018",
		"province": "Ho Chi Minh City",
		"school": "THPT Nguyễn Hữu Huân",
		"major": "Data Science",
		"defect": {
			"code": "TEAM_NOT_FOUND_FOR_PROVINCE",
			"expected": "manual_review",
			"note": f"Tỉnh {UNMANAGED_PROVINCE} chưa có Team Sales nào quản lý → Lead đóng khi phân công.",
			"fields": {"province": UNMANAGED_PROVINCE},
		},
	},
	{
		"name": "Vũ Đình Phong",
		"phone": "0903000019",
		"province": "Đồng Nai",
		"school": "THPT Long Thành",
		"major": "Digital Marketing",
		"defect": {
			"code": "DUPLICATE_PRIMARY",
			"expected": "assigned",
			"note": "Bản ghi đại diện được giữ lại để tiếp tục xử lý và phân công.",
			"fields": {},
		},
	},
	{
		"name": "Vũ Đình Phong (nộp lại)",
		"phone": "0903000020",
		"province": "Đồng Nai",
		"school": "THPT Long Thành",
		"major": "Digital Marketing",
		"defect": {
			"code": "DUPLICATE_RESUBMIT",
			"expected": "manual_review",
			"note": "Trùng số điện thoại với Lead đã xử lý → Lead nộp lại được đóng tự động.",
			"fields": {"phone": DUPLICATE_PHONE},
		},
	},
)


def _assert_local_site() -> None:
	if getattr(frappe.local, "site", None) != LOCAL_SITE:
		frappe.throw("Bộ seed Lead → Student chỉ được chạy trên crm.localhost.", frappe.ValidationError)


def _lookup(doctype: str, value: str, fieldname: str) -> str:
	if doctype == "CRM Province":
		from crm.api.lead_mapping import _resolve_province

		return _resolve_province(value)
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


def _purge_orphan_command_receipts() -> int:
	"""Remove local receipts pointing to records cleared by the fixture reset."""
	if not frappe.db.table_exists("CRM Student Command Receipt"):
		return 0

	orphan_names: list[str] = []
	for row in frappe.get_all(
		"CRM Student Command Receipt",
		fields=["name", "target_student", "target_case_key"],
		limit_page_length=0,
	):
		student = row.get("target_student")
		case_key = row.get("target_case_key")
		student_missing = student and not (
			frappe.db.exists("CRM Lead", student) or frappe.db.exists("CRM Student", student)
		)
		case_key_missing = case_key and not frappe.db.exists("CRM Student Case Key", case_key)
		if student_missing or case_key_missing:
			orphan_names.append(row.name)

	for name in orphan_names:
		frappe.db.sql("delete from `tabCRM Student Command Receipt` where name = %s", (name,))
	return len(orphan_names)


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

	_patch_split_receipt_link_gap()
	intake_namespace = _intake_namespace(run_token)
	payload = {
		"student_name": spec["name"],
		"phone": spec["phone"],
		# Keyed on the phone, not the list position: phone and email are the only
		# identity roots intake looks up, so a scenario keeps the same pair even
		# when the fixture is reordered or extended.
		"email": f"local.assignment.conversion.{spec['phone']}@example.test",
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
		# Intake receipts are append-only and source-idempotent. The fixture purges
		# the Lead/identity graph between runs, so each fresh run needs a new source
		# namespace instead of colliding with a receipt whose target was deleted.
		source_namespace=intake_namespace,
		source_record_id=f"lead:{spec['phone']}",
		idempotency_key=f"{NAMESPACE}:{run_token}:{index:02d}",
		correlation_id=f"{intake_namespace}:{index:02d}",
	)
	lead = result.get("student")
	if result.get("outcome") != "created" or not lead:
		frappe.throw(f"Intake không tạo được Lead {spec['name']}: {result}", frappe.ValidationError)
	defect = spec.get("defect")
	notes = (
		f"Local defect {defect['code']}: {defect['note']} → {defect['expected']}."
		if defect
		else "Local happy-path: assignment assigns an owner without creating a CRM Student."
	)
	frappe.db.set_value(
		"CRM Lead",
		lead,
		{"notes": notes, "import_source_id": f"{NAMESPACE}:{spec['phone']}"},
		update_modified=False,
	)
	if defect:
		_apply_defect(lead, defect)
	_require_lead_code(lead)
	return lead


def execute() -> dict[str, Any]:
	"""Reset local Lead/Student rows and seed the 20-Lead assignment fixture."""
	_assert_local_site()
	frappe.set_user("Administrator")
	seed_team_management.execute()
	deleted = seed_assignment_scenarios._purge_business_data()
	purged_identities = _purge_identity_graph()
	purged_receipts = _purge_orphan_command_receipts()
	source = seed_assignment_scenarios._active_source()
	pools = {province: _ensure_pool(team) for province, team in _team_by_province().items()}
	run_token = frappe.generate_hash(length=10)
	seeded: list[dict[str, Any]] = []
	for index, spec in enumerate(SCENARIOS, start=1):
		lead = _submit_lead(spec, source, index, pools[spec["province"]], run_token)
		lead_code = _require_lead_code(lead)
		defect = spec.get("defect")
		seeded.append(
			{
				"lead": lead,
				"leadCode": lead_code,
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
		"purged_orphan_receipts": purged_receipts,
		"seeded_leads": len(seeded),
		"happy_leads": len(happy),
		"defect_leads": len(seeded) - len(happy),
		"students_before_assignment": frappe.db.count("CRM Student"),
		"source": source,
		"pools": pools,
		"leads": seeded,
		"message": (
			f"Đã seed {len(seeded)} Lead ({len(happy)} hồ sơ có thể phân công, "
			f"{len(seeded) - len(happy)} hồ sơ lỗi). "
			"Bấm Xử lý Lead rồi Phân công Lead: hệ thống chỉ cập nhật trạng thái và người phụ trách, "
			"không tạo hồ sơ Student."
		),
	}
