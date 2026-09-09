"""Reset local Lead/Student business data and seed assignment scenarios.

Run locally with::

    bench --site crm.localhost execute crm.demo.seed_assignment_scenarios.execute

The reset is intentionally restricted to ``crm.localhost``. It removes Lead,
Student and assignment audit rows so the dashboard's unassigned scan starts
from a clean state, while keeping provinces, schools, majors, Groups, Teams
and staff accounts intact.
"""

from __future__ import annotations

from typing import Any

import frappe

from crm.demo import seed_team_management

LOCAL_SITE = "crm.localhost"
NAMESPACE = "local-assignment-scenarios-20260908"
CAMPUS = "FPTU Ho Chi Minh Campus"


SCENARIOS: tuple[dict[str, Any], ...] = (
	{"name": "Nguyễn Minh Anh", "phone": "0902000001", "province": "Ho Chi Minh City", "school": "THPT Chuyên Lê Hồng Phong", "major": "Software Engineering", "id": "079302000001"},
	{"name": "Trần Gia Hân", "phone": "0902000002", "province": "Ho Chi Minh City", "school": "THPT Nguyễn Thượng Hiền", "major": "Artificial Intelligence", "id": "079302000002"},
	{"name": "Lê Hoàng Nam", "phone": "0902000003", "province": "Ho Chi Minh City", "school": "THPT Gia Định", "major": "Data Science", "id": "079302000003"},
	{"name": "Phạm Khánh Linh", "phone": "0902000004", "province": "Ho Chi Minh City", "school": "THPT Nguyễn Hữu Huân", "major": "Digital Marketing", "id": "079302000004"},
	{"name": "Võ Đức Anh", "phone": "0902000005", "province": "Ho Chi Minh City", "school": "THPT Thủ Đức", "major": "Business Administration", "id": "079302000005"},
	{"name": "Nguyễn Ngọc Mai", "phone": "0902000006", "province": "Ho Chi Minh City", "school": "THPT Chuyên Lê Hồng Phong", "major": "Graphic Design", "id": "079302000006"},
	{"name": "Đặng Quốc Bảo", "phone": "0902000007", "province": "Đồng Nai", "school": "THPT Ngô Quyền", "major": "Software Engineering", "id": "075302000007"},
	{"name": "Bùi Thanh Trúc", "phone": "0902000008", "province": "Đồng Nai", "school": "THPT Trấn Biên", "major": "Artificial Intelligence", "id": "075302000008"},
	{"name": "Hoàng Minh Khang", "phone": "0902000009", "province": "Đồng Nai", "school": "THPT Long Thành", "major": "Data Science", "id": "075302000009"},
	{"name": "Đỗ Quỳnh Anh", "phone": "0902000010", "province": "Đồng Nai", "school": "THPT Bình Sơn", "major": "Digital Marketing", "id": "075302000010"},
	{"name": "Phan Nhật Vy", "phone": "0902000011", "province": "Đồng Nai", "school": "THPT Trảng Bom", "major": "Business Administration", "id": "075302000011"},
	{"name": "Lý Thanh Tâm", "phone": "0902000012", "province": "Đồng Nai", "school": "THPT Thống Nhất", "major": "Graphic Design", "id": "075302000012"},
	{"name": "Nguyễn Khải Nam", "phone": None, "province": "Ho Chi Minh City", "school": "THPT Gia Định", "major": "Data Science", "id": "079302000013", "case": "missing_phone"},
	{"name": "Vũ Ngọc Hà", "phone": "0902000014", "province": "Ho Chi Minh City", "school": None, "major": "Artificial Intelligence", "id": "079302000014", "case": "missing_high_school"},
	{"name": "Phạm Tuấn Kiệt", "phone": "0902000015", "province": "Đồng Nai", "school": "THPT Long Thành", "major": None, "id": "075302000015", "case": "missing_major"},
	{"name": "Lê Bảo Ngọc", "phone": "0902000016", "province": None, "school": "THPT Nguyễn Thượng Hiền", "major": "Software Engineering", "id": "079302000016", "case": "missing_province"},
	{"name": "Trần Quốc Huy", "phone": "0902000017", "province": None, "school": "THPT Trấn Biên", "major": "Business Administration", "id": "075302000017", "case": "missing_province"},
	{"name": "Nguyễn Đức Long", "phone": "0902000018", "province": "Đồng Nai", "school": "THPT Ngô Quyền", "major": "Software Engineering", "id": "075302000018", "case": "duplicate_source"},
	{"name": "Nguyễn Đức Long", "phone": "0902000018", "province": "Đồng Nai", "school": "THPT Ngô Quyền", "major": "Software Engineering", "id": "075302000018", "case": "duplicate_copy"},
	{"name": "Mai Phương Thảo", "phone": "0902000019", "province": "Ho Chi Minh City", "school": "THPT Thủ Đức", "major": "Digital Marketing", "id": "079302000019"},
)


def _assert_local_site() -> None:
	if getattr(frappe.local, "site", None) != LOCAL_SITE:
		frappe.throw("Bộ seed Lead chỉ được chạy trên crm.localhost.", frappe.ValidationError)


def _delete_rows_for_links(doctype: str, fieldname: str, values: set[str]) -> int:
	if not values or not frappe.db.table_exists(doctype):
		return 0
	names = frappe.get_all(
		doctype,
		filters={fieldname: ["in", sorted(values)]},
		pluck="name",
		limit_page_length=0,
	)
	for name in names:
		frappe.db.delete(doctype, {"name": name})
	return len(names)


def _purge_business_data() -> dict[str, int]:
	lead_names = set(frappe.get_all("CRM Lead", pluck="name", limit_page_length=0))
	student_names = set(frappe.get_all("CRM Student", pluck="name", limit_page_length=0))
	all_names = lead_names | student_names
	deleted = {"CRM Lead": 0, "CRM Student": 0}

	# Remove child rows whose parent is a Lead/Student before deleting parents.
	for meta_row in frappe.get_all("DocType", filters={"istable": 1}, pluck="name", limit_page_length=0):
		if not frappe.db.table_exists(meta_row):
			continue
		frappe.db.sql(
			f"delete from `tab{meta_row}` where parenttype in ('CRM Lead', 'CRM Student') "
			"and parent in %(names)s",
			{"names": tuple(sorted(all_names)) or ("__none__",)},
		)

	# Remove every link-backed audit/operational row that points to either type.
	for doctype in frappe.get_all("DocType", filters={"issingle": 0}, pluck="name", limit_page_length=0):
		if doctype in {"CRM Lead", "CRM Student"} or not frappe.db.table_exists(doctype):
			continue
		meta = frappe.get_meta(doctype)
		for field in meta.fields:
			if field.fieldtype != "Link" or field.options not in {"CRM Lead", "CRM Student"}:
				continue
			_delete_rows_for_links(doctype, field.fieldname, lead_names if field.options == "CRM Lead" else student_names)

	# Assignment history is an internal audit projection and must not point to
	# deleted Leads. Remove all old runs so the next click is easy to inspect.
	for doctype in (
		"CRM Lead Assignment Batch Item",
		"CRM Lead Assignment Batch",
		"CRM Student Assignment Batch Item",
		"CRM Student Assignment Batch",
	):
		if frappe.db.table_exists(doctype):
			frappe.db.sql(f"delete from `tab{doctype}`")

	if lead_names:
		frappe.db.delete("CRM Lead", {"name": ["in", sorted(lead_names)]})
		deleted["CRM Lead"] = len(lead_names)
	if student_names:
		frappe.db.delete("CRM Student", {"name": ["in", sorted(student_names)]})
		deleted["CRM Student"] = len(student_names)
	frappe.db.commit()
	return deleted


def _active_source() -> str:
	source = frappe.db.get_value(
		"CRM Lead Source",
		{"approval_state": ["!=", "Retired"]},
		"name",
		order_by="creation asc",
	)
	if not source:
		frappe.throw("Chưa có Nguồn Lead đang hoạt động.", frappe.ValidationError)
	return source


def _lookup(doctype: str, value: str | None, fieldname: str) -> str | None:
	if not value:
		return None
	if doctype == "CRM Province":
		from crm.api.lead_mapping import _resolve_province

		return _resolve_province(value)
	return frappe.db.get_value(doctype, {fieldname: value}, "name") or value


def _insert_lead(spec: dict[str, Any], source: str, index: int) -> str:
	province = _lookup("CRM Province", spec.get("province"), "province_name")
	school = _lookup("CRM High School", spec.get("school"), "school_name")
	major = _lookup("CRM Major", spec.get("major"), "major_name")
	email = f"local.assignment.{index:02d}@example.test"
	lead = frappe.get_doc(
		{
			"doctype": "CRM Lead",
			"student_name": spec["name"],
			"phone": spec["phone"],
			"email": email,
			"province": province,
			"high_school": school,
			"major": major,
			"branch": CAMPUS,
			"source": source,
			"lead_status": "New",
			"processing_status": "NEW",
			"resolution": "PENDING",
			"conversion_status": "Not Ready",
			"lifecycle_stage": "Lead",
			"notes": f"Local assignment scenario: {spec.get('case', 'valid')}",
			"import_source_id": f"{NAMESPACE}:{index:02d}",
		}
	).insert(ignore_permissions=True)
	# The assignment button must discover these records as unassigned.
	frappe.db.set_value(
		"CRM Lead",
		lead.name,
		{"assigned_to": None, "owner_staff": None, "owning_team": None, "owning_pool": None},
		update_modified=False,
	)
	return lead.name


def execute() -> dict[str, Any]:
	"""Reset local business rows and create twenty unassigned Leads."""
	_assert_local_site()
	frappe.set_user("Administrator")
	seed_team_management.execute()
	deleted = _purge_business_data()
	source = _active_source()
	lead_names = [_insert_lead(spec, source, index) for index, spec in enumerate(SCENARIOS, start=1)]
	frappe.db.commit()

	return {
		"deleted": deleted,
		"seeded_leads": len(lead_names),
		"students_after_reset": frappe.db.count("CRM Student"),
		"source": source,
		"lead_names": lead_names,
		"cases": {
			"valid_rows_before_duplicate_resolution": 13,
			"invalid_missing_phone_school_major": 3,
			"manual_review_missing_province": 2,
			"duplicate_pair": 2,
		},
		"message": "Đã reset Lead/Student local và seed 20 Lead NEW chưa phân công.",
	}
