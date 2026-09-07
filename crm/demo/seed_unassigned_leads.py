"""Seed ten unassigned Leads for the local automatic-assignment test.

The records use ordinary Vietnamese names and real catalog links, but all
contact values are synthetic.  They deliberately have no owner, Team or Pool
so the dashboard action can discover them.

Run locally with::

    bench --site crm.localhost execute crm.demo.seed_unassigned_leads.execute
"""

from __future__ import annotations

from typing import Any

import frappe

from crm.api import lead_mapping
from crm.demo import seed_team_management

LOCAL_SITE = "crm.localhost"
NAMESPACE = "local-unassigned-assignment"
CAMPUS = "FPTU Ho Chi Minh Campus"

LEAD_FIXTURES: tuple[dict[str, str], ...] = (
	{
		"student_name": "Nguyễn Minh Anh",
		"phone": "0901000001",
		"email": "nguyen.minh.anh.local@gmail.com",
		"id_number": "079301000001",
		"province": "Ho Chi Minh City",
		"high_school": "THPT Chuyên Lê Hồng Phong",
		"major": "Software Engineering",
	},
	{
		"student_name": "Trần Gia Hân",
		"phone": "0901000002",
		"email": "tran.gia.han.local@gmail.com",
		"id_number": "079301000002",
		"province": "Ho Chi Minh City",
		"high_school": "THPT Nguyễn Thượng Hiền",
		"major": "Artificial Intelligence",
	},
	{
		"student_name": "Lê Hoàng Nam",
		"phone": "0901000003",
		"email": "le.hoang.nam.local@gmail.com",
		"id_number": "079301000003",
		"province": "Ho Chi Minh City",
		"high_school": "THPT Gia Định",
		"major": "Data Science",
	},
	{
		"student_name": "Phạm Khánh Linh",
		"phone": "0901000004",
		"email": "pham.khanh.linh.local@gmail.com",
		"id_number": "079301000004",
		"province": "Ho Chi Minh City",
		"high_school": "THPT Nguyễn Hữu Huân",
		"major": "Digital Marketing",
	},
	{
		"student_name": "Võ Đức Anh",
		"phone": "0901000005",
		"email": "vo.duc.anh.local@gmail.com",
		"id_number": "079301000005",
		"province": "Ho Chi Minh City",
		"high_school": "THPT Thủ Đức",
		"major": "Business Administration",
	},
	{
		"student_name": "Nguyễn Ngọc Mai",
		"phone": "0901000006",
		"email": "nguyen.ngoc.mai.local@gmail.com",
		"id_number": "075301000006",
		"province": "Đồng Nai",
		"high_school": "THPT Ngô Quyền",
		"major": "Software Engineering",
	},
	{
		"student_name": "Đặng Quốc Bảo",
		"phone": "0901000007",
		"email": "dang.quoc.bao.local@gmail.com",
		"id_number": "075301000007",
		"province": "Đồng Nai",
		"high_school": "THPT Trấn Biên",
		"major": "Artificial Intelligence",
	},
	{
		"student_name": "Bùi Thanh Trúc",
		"phone": "0901000008",
		"email": "bui.thanh.truc.local@gmail.com",
		"id_number": "075301000008",
		"province": "Đồng Nai",
		"high_school": "THPT Long Thành",
		"major": "Data Science",
	},
	{
		"student_name": "Hoàng Minh Khang",
		"phone": "0901000009",
		"email": "hoang.minh.khang.local@gmail.com",
		"id_number": "075301000009",
		"province": "Đồng Nai",
		"high_school": "THPT Bình Sơn",
		"major": "Digital Marketing",
	},
	{
		"student_name": "Đỗ Quỳnh Anh",
		"phone": "0901000010",
		"email": "do.quynh.anh.local@gmail.com",
		"id_number": "075301000010",
		"province": "Đồng Nai",
		"high_school": "THPT Trảng Bom",
		"major": "Business Administration",
	},
)


def _assert_local_site() -> None:
	if getattr(frappe.local, "site", None) != LOCAL_SITE:
		frappe.throw("Seed Lead chỉ được chạy trên crm.localhost.", frappe.ValidationError)


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


def _ensure_lead(spec: dict[str, str], source: str) -> tuple[str, bool]:
	import_source_id = f"{NAMESPACE}:{spec['phone']}"
	existing = frappe.db.get_value("CRM Lead", {"import_source_id": import_source_id}, "name")
	if existing:
		return existing, False

	values = lead_mapping._normalize_public_lead_payload(
		{
			**spec,
			"branch": CAMPUS,
			"source": source,
			"import_source_id": import_source_id,
			"notes": "Lead local để kiểm thử nút phân công tự động.",
		},
		require_campaign=False,
	)
	lead = frappe.get_doc(
		{
			"doctype": "CRM Lead",
			**values,
			"processing_status": "NEW",
			"resolution": "PENDING",
			"conversion_status": "Not Ready",
			"lifecycle_stage": "Lead",
		}
	).insert(ignore_permissions=True)
	# CRM Lead derives a technical owning team for newly inserted records.  Clear
	# it after creation so this fixture is genuinely discovered as unassigned.
	frappe.db.set_value(
		"CRM Lead",
		lead.name,
		{"assigned_to": None, "owner_staff": None, "owning_team": None, "owning_pool": None},
		update_modified=False,
	)
	return lead.name, True


def execute() -> dict[str, Any]:
	_assert_local_site()
	frappe.set_user("Administrator")
	seed_team_management.execute()
	source = _active_source()

	created = []
	existing = []
	for spec in LEAD_FIXTURES:
		name, was_created = _ensure_lead(spec, source)
		(created if was_created else existing).append(name)
	frappe.db.commit()
	return {
		"source": source,
		"created": created,
		"existing": existing,
		"total": len(created) + len(existing),
		"message": "Đã chuẩn bị 10 Lead chưa phân công để kiểm thử.",
	}
