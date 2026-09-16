"""Seed three CRM Staff Capacity Period states across the local routing teams
to exercise the capacity-eligibility rule in ``crm.fcrm.team_routing``.

Run locally, after the Lead/Team reset, with::

    bench --site crm.localhost execute crm.demo.seed_assignment_scenarios.execute
    bench --site crm.localhost execute crm.demo.seed_capacity_scenarios.execute

This script only touches ``CRM Staff Capacity Period`` (and, for the "full"
scenario, the ownership of one already-seeded Lead) — it never re-seeds
Leads or Teams itself, so run ``seed_assignment_scenarios`` first so the 7
"Đội Tư vấn" teams, their Sale/CTV Sale staff and 20 fresh unassigned Leads
already exist.

Three states, mapped onto real teams so they can be exercised through the
actual Lead assignment batch UI, not just unit tests:

- Đồng Nai (Biên Hòa / Long Thành / Trảng Bom, 6 Sale/CTV): every capacity
  period removed → NOT CONFIGURED. Routing a Đồng Nai Lead must now fail with
  the new "chưa thiết lập capacity" message instead of silently succeeding
  as "unlimited" (the old, now-reversed default).
- Hồ Chí Minh, Bình Chánh + Quận 1 (4 Sale/CTV): capacity set high with zero
  load → HEALTHY. Routing a Hồ Chí Minh Lead must still succeed normally —
  this is the regression guard that the fix didn't break the working case.
- Hồ Chí Minh, Thủ Đức (2 Sale/CTV): capacity set to 1 and each made to
  already "own" one Lead → CONFIGURED BUT FULL. They must be excluded from
  selection (visible as 1/1 in Quản lý người dùng) without blocking the rest
  of the province, since Bình Chánh/Quận 1 remain eligible.

Bình Dương's only team has no Sale/CTV member at all — that pre-existing
"team not ready" case is left untouched as a fourth, unrelated scenario.
"""

from __future__ import annotations

from typing import Any

import frappe

from crm.api.assignment_control import upsert_staff_capacity

LOCAL_SITE = "crm.localhost"
REASON = "Seed local: kịch bản kiểm thử capacity (seed_capacity_scenarios)."

# Đội Tư vấn Biên Hòa / Long Thành / Trảng Bom — Đồng Nai.
NOT_CONFIGURED_STAFF = [
	"Lê Hoàng Phúc",
	"Đặng Ngọc Hà",
	"Nguyễn Thu Hà",
	"Trần Anh Khoa",
	"Bùi Ngọc Mai",
	"Võ Thành Đạt",
]

# Đội Tư vấn Bình Chánh / Quận 1 — Hồ Chí Minh.
HEALTHY_STAFF = [
	"Lê Bảo Châu",
	"Đỗ Minh Quân",
	"Trần Minh Anh",
	"Võ Ngọc Lan",
]

# Đội Tư vấn Thủ Đức — Hồ Chí Minh.
FULL_STAFF = [
	"Đặng Hoàng Long",
	"Nguyễn Thùy Linh",
]

FULL_STAFF_PROVINCE = "Hồ Chí Minh"


def _assert_local_site() -> None:
	if getattr(frappe.local, "site", None) != LOCAL_SITE:
		frappe.throw("Bộ seed capacity chỉ được chạy trên crm.localhost.", frappe.ValidationError)


def _clear_capacity(staff: str) -> int:
	names = frappe.get_all("CRM Staff Capacity Period", filters={"staff": staff}, pluck="name")
	for name in names:
		frappe.delete_doc("CRM Staff Capacity Period", name, force=True, ignore_permissions=True)
	return len(names)


def _give_one_active_lead(staff: str, province: str) -> str | None:
	"""Directly own one already-unassigned Lead so ``active_lead_count`` becomes 1.

	Deterministic without re-running the whole ``assign_lead`` workflow —
	only the ownership fields ``active_lead_count`` actually reads matter here.
	"""
	lead = frappe.db.get_value(
		"CRM Lead",
		{
			"province": province,
			"owner_staff": ["is", "not set"],
			"assigned_to": ["is", "not set"],
		},
		"name",
		order_by="creation asc",
	)
	if not lead:
		return None
	frappe.db.set_value(
		"CRM Lead",
		lead,
		{"owner_staff": staff, "assigned_to": staff, "processing_status": "ASSIGNED"},
		update_modified=False,
	)
	return lead


def execute() -> dict[str, Any]:
	_assert_local_site()
	frappe.set_user("Administrator")

	cleared_not_configured = {staff: _clear_capacity(staff) for staff in NOT_CONFIGURED_STAFF}

	for staff in HEALTHY_STAFF:
		_clear_capacity(staff)
		upsert_staff_capacity(staff=staff, max_active_students=20, reason=REASON)

	full_assignments = {}
	for staff in FULL_STAFF:
		_clear_capacity(staff)
		upsert_staff_capacity(staff=staff, max_active_students=1, reason=REASON)
		full_assignments[staff] = _give_one_active_lead(staff, FULL_STAFF_PROVINCE)

	frappe.db.commit()

	return {
		"not_configured_staff": {
			staff: f"đã xoá {count} capacity period" for staff, count in cleared_not_configured.items()
		},
		"healthy_staff": {staff: "capacity=20, active=0" for staff in HEALTHY_STAFF},
		"full_staff": {
			staff: f"capacity=1, active=1 (lead: {lead or 'không tìm thấy Lead trống để gán'})"
			for staff, lead in full_assignments.items()
		},
		"message": (
			"Đồng Nai (Biên Hòa/Long Thành/Trảng Bom): 6 Sale/CTV CHƯA thiết lập capacity "
			"→ phân công Lead ở Đồng Nai phải báo lỗi 'chưa thiết lập capacity'. "
			"Hồ Chí Minh (Bình Chánh, Quận 1): 4 Sale/CTV capacity=20, còn trống "
			"→ phân công Lead ở Hồ Chí Minh vẫn thành công bình thường. "
			"Hồ Chí Minh (Thủ Đức): 2 Sale/CTV capacity=1 và đã đầy (1/1) "
			"→ bị loại khỏi lựa chọn nhưng không chặn cả tỉnh vì Bình Chánh/Quận 1 vẫn nhận được. "
			"Bình Dương: Team chưa có Sale/CTV hoạt động (case có sẵn từ trước, không đụng tới)."
		),
	}
