"""Operational control plane for the automatic Student assignment workspace."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import getdate, now_datetime, today

from crm.api.assignment_workspace import (
	_active_students_summary,
	_actor_context,
	_capacity_by_staff,
	_doctype_exists,
	_grouped_students,
	_overview_sources,
	_safe_get_all,
)
from crm.fcrm.role_policy import resolve_crm_profile
from crm.fcrm.student_feature_flags import enabled as feature_enabled

RECIPIENT_FUNCTIONS = {"Sale", "CTV Sale"}
CONTROL_DOCTYPE = "CRM Assignment Control"


def _as_bool(value) -> bool:
	if isinstance(value, bool):
		return value
	if isinstance(value, str):
		return value.lower() in {"1", "true", "yes", "on"}
	return bool(value)


def _require_control_access():
	context = _actor_context()
	if "system.configure" not in context["capabilities"]:
		frappe.throw(_("Chỉ Quản trị hệ thống mới được thay đổi thiết lập phân công tự động."), frappe.PermissionError)
	return context


def _stored_control():
	if not _doctype_exists(CONTROL_DOCTYPE):
		return None
	try:
		doc = frappe.get_single(CONTROL_DOCTYPE)
		return {
			fieldname: doc.get(fieldname)
			for fieldname in (
				"routing_enabled",
				"assignment_mode",
				"capacity_required",
				"last_changed_by",
				"last_change_reason",
				"revision",
			)
		}
	except Exception:
		return None


def _routing_enabled(control) -> bool:
	if control and control.get("routing_enabled") is not None:
		return _as_bool(control.get("routing_enabled"))
	return feature_enabled("routing")


def _load_rows(context):
	sources = _overview_sources(context)
	allowed_teams = {
		row.name
		for row in sources["teams"]
		if row.get("is_active") and row.get("team_type") == "Sales"
	}
	staff_map = {row.name: row for row in sources["staff"]}
	team_map = {row.name: row for row in sources["teams"]}
	user_enabled = {
		row.name: bool(row.get("enabled"))
		for row in _safe_get_all("User", ["name", "enabled"])
	}
	campus_map = {
		row.name: row.get("campus_name") or row.name
		for row in _safe_get_all("CRM Campus", ["name", "campus_name"])
	}
	students = _grouped_students()
	student_by, _ = _active_students_summary(students)
	capacity_by_staff = _capacity_by_staff()
	memberships = [
		row
		for row in sources["memberships"]
		if row.get("team") in allowed_teams and row.get("staff") in staff_map
	]
	rows = []
	memberships_by_staff = {}
	for membership in memberships:
		memberships_by_staff.setdefault(membership.get("staff"), []).append(membership)
	for staff_id, staff_memberships in memberships_by_staff.items():
		staff = staff_map[staff_id]
		staff_memberships.sort(
			key=lambda row: (
				not bool(row.get("is_primary")),
				(team_map.get(row.get("team")) or {}).get("team_name") or row.get("team") or "",
			)
		)
		primary_membership = staff_memberships[0]
		team_id = primary_membership.get("team")
		team = team_map.get(team_id)
		team_names = [
			(team_map.get(row.get("team")) or {}).get("team_name") or row.get("team")
			for row in staff_memberships
			if row.get("team")
		]
		capacity = capacity_by_staff.get(staff_id)
		active = int(student_by["owner_staff"].get(staff_id, 0) or 0)
		maximum = int(capacity.get("max_active_students") or 0) if capacity else 0
		workload = "unconfigured"
		if maximum > 0:
			workload = "over_capacity" if active >= maximum else "near_capacity" if active >= maximum * 0.85 else "healthy"
		eligible_membership = next(
			(
				row
				for row in staff_memberships
				if (row.get("function") or "Sale") in RECIPIENT_FUNCTIONS
			),
			None,
		)
		function = (eligible_membership or primary_membership).get("function") or "Sale"
		recipient_eligible = function in RECIPIENT_FUNCTIONS
		if recipient_eligible:
			recipient_eligible = bool(staff.get("user")) and user_enabled.get(staff.get("user"), False)
		if recipient_eligible:
			recipient_eligible = resolve_crm_profile(frappe.get_roles(staff.get("user"))) in {
			"sales",
			"ctv_sale",
		}
		rows.append(
			{
				"staff": staff_id,
				"staff_name": staff.get("full_name") or staff_id,
				"user": staff.get("user"),
				"team": team_id,
				"team_name": team.get("team_name") if team else team_id,
				"team_names": team_names,
				"campus": staff.get("campus") or (team.get("campus") if team else None),
				"campus_name": campus_map.get(staff.get("campus")) or campus_map.get(team.get("campus") if team else None),
				"function": function,
				"active_leads": active,
				"capacity": maximum or None,
				"remaining": max(0, maximum - active) if maximum else None,
				"load_percent": round(active / maximum * 100, 1) if maximum else None,
				"workload": workload,
				"capacity_configured": bool(maximum),
				"period_start": str(capacity.get("period_start")) if capacity and capacity.get("period_start") else None,
				"period_end": str(capacity.get("period_end")) if capacity and capacity.get("period_end") else None,
				"recipient_eligible": recipient_eligible,
				"is_active": bool(staff.get("is_active")),
			}
		)
	return sorted(rows, key=lambda row: (row.get("team_name") or "", row.get("staff_name") or "")), sources


def _policy_rows(context, sources):
	allowed_pools = {row.name for row in sources["pools"]}
	rows = _safe_get_all(
		"CRM Student Routing Policy",
		[
			"name",
			"policy_key",
			"policy_version",
			"status",
			"campus",
			"student_pool",
			"strategy",
			"scoring_weights",
			"effective_from",
			"effective_until",
			"authored_by",
			"approved_by",
			"approved_at",
		],
		order_by="modified desc, name desc",
	)
	return [row for row in rows if row.get("student_pool") in allowed_pools]


def _activation_checks(load_rows, policies, sources):
	sales_team_ids = {
		row.name
		for row in sources["teams"]
		if row.get("is_active") and row.get("team_type") == "Sales"
	}
	required_pools = [
		row
		for row in sources["pools"]
		if row.get("is_active") and row.get("team") in sales_team_ids
	]
	today_date = getdate()
	current_policies = [
		row
		for row in policies
		if row.get("status") == "active"
		and row.get("effective_from")
		and getdate(row.get("effective_from")) <= today_date
		and (
			not row.get("effective_until")
			or getdate(row.get("effective_until")) >= today_date
		)
	]
	policies_by_pool = {}
	for row in current_policies:
		policies_by_pool.setdefault(row.get("student_pool"), []).append(row)
	missing_pools = [
		row
		for row in required_pools
		if not policies_by_pool.get(row.name)
	]
	overlapping_pools = [
		row
		for row in required_pools
		if len(policies_by_pool.get(row.name, [])) > 1
	]
	recipients = [row for row in load_rows if row.get("recipient_eligible") and row.get("is_active")]
	missing_capacity = [row for row in recipients if not row.get("capacity_configured")]
	policy_ready = bool(required_pools) and not missing_pools and not overlapping_pools
	if not required_pools:
		policy_detail = _("Chưa có hàng chờ đang hoạt động thuộc nhóm Sales.")
	elif overlapping_pools:
		policy_detail = _("Có hàng chờ đang dùng nhiều cách chia cùng lúc: {0}.").format(
			", ".join(row.get("pool_name") or row.name for row in overlapping_pools[:5])
		)
	elif missing_pools:
		policy_detail = _("Chưa có cách chia đang dùng cho: {0}.").format(
			", ".join(row.get("pool_name") or row.name for row in missing_pools[:5])
		)
	else:
		policy_detail = _("Mỗi hàng chờ đang hoạt động đã có một cách chia hiệu lực.")
	checks = [
		{
			"code": "active_policy",
			"label": _("Có cách phân công đang dùng"),
			"passed": policy_ready,
			"count": len(current_policies),
			"detail": policy_detail,
		},
		{
			"code": "eligible_staff",
			"label": _("Có nhân viên tư vấn đủ điều kiện"),
			"passed": bool(recipients),
			"count": len(recipients),
			"detail": _("Kiểm tra nhân sự đang hoạt động, tài khoản và thành viên nhóm.")
			if not recipients
			else _("{0} nhân sự đang tham gia phân bổ Lead.").format(len(recipients)),
		},
		{
			"code": "capacity_configured",
			"label": _("Mọi nhân viên đều có giới hạn nhận Lead"),
			"passed": not missing_capacity,
			"count": len(missing_capacity),
			"detail": _("Còn thiếu: {0}.").format(", ".join(row["staff_name"] for row in missing_capacity[:5]))
			if missing_capacity
			else _("Mỗi nhân viên có giới hạn Lead và còn chỗ trống được tính."),
		},
	]
	return checks


def _policy_options(sources):
	return {
		"campuses": [
			{"value": row.name, "label": row.get("campus_name") or row.name}
			for row in sources["campuses"]
		],
		"pools": [
			{
				"value": row.name,
				"label": row.get("pool_name") or row.name,
				"campus": row.get("campus"),
			}
			for row in sources["pools"]
		],
	}


@frappe.whitelist()
def get_routing_control():
	"""Return the tabbed workspace model for toggle, policies and load balance."""
	context = _actor_context()
	load_rows, sources = _load_rows(context)
	policies = _policy_rows(context, sources)
	control = _stored_control()
	checks = _activation_checks(load_rows, policies, sources)
	active_rows = [row for row in load_rows if row.get("recipient_eligible") and row.get("is_active")]
	configured = [row for row in active_rows if row.get("capacity_configured")]
	return {
		"schemaVersion": "assignment-control-v1",
		"as_of": str(now_datetime()),
		"enabled": _routing_enabled(control),
		"control_source": "workspace" if control else "site_config_fallback",
		"control": control
		or {
			"capacity_required": False,
			"revision": 0,
		},
		"can_manage": "system.configure" in context["capabilities"],
		"can_approve_policy": "student.policy.approve" in context["capabilities"],
		"checks": checks,
		"ready_to_enable": all(check["passed"] for check in checks),
		"summary": {
			"eligible_staff": len(active_rows),
			"capacity_configured": len(configured),
			"capacity_missing": len(active_rows) - len(configured),
			"active_leads": sum(row["active_leads"] for row in active_rows),
			"total_capacity": sum(row["capacity"] or 0 for row in configured),
			"remaining_capacity": sum(row["remaining"] or 0 for row in configured),
			"near_capacity": sum(row["workload"] == "near_capacity" for row in active_rows),
			"over_capacity": sum(row["workload"] == "over_capacity" for row in active_rows),
		},
		"staff_load": load_rows,
		"policies": policies,
		"policy_options": _policy_options(sources),
	}


@frappe.whitelist(methods=["POST"])
def set_routing_enabled(enabled: bool | str, reason: str | None = None):
	"""Switch automatic assignment on/off after server-side readiness checks."""
	_require_control_access()
	reason = (reason or "").strip()
	if len(reason) < 5:
		frappe.throw(_("Cần ghi lý do thay đổi ít nhất 5 ký tự."), frappe.ValidationError)
	requested = _as_bool(enabled)
	snapshot = get_routing_control()
	if requested and not snapshot["ready_to_enable"]:
		failed = [check["label"] for check in snapshot["checks"] if not check["passed"]]
		frappe.throw(
			_("Chưa thể bật tự động phân công. Cần xử lý: {0}.").format("; ".join(failed)),
			frappe.ValidationError,
		)
	doc = frappe.get_single(CONTROL_DOCTYPE)
	doc.routing_enabled = 1 if requested else 0
	doc.capacity_required = 1
	doc.last_changed_by = frappe.session.user
	doc.last_change_reason = reason
	doc.revision = int(doc.revision or 0) + 1
	doc.save(ignore_permissions=True)
	return get_routing_control()


@frappe.whitelist(methods=["POST"])
def upsert_staff_capacity(
	staff: str,
	max_active_students: int | str,
	period_start: str | None = None,
	period_end: str | None = None,
	team: str | None = None,
	reason: str | None = None,
):
	"""Create or update the active capacity period used by routing."""
	_require_control_access()
	if not staff or not frappe.db.exists("CRM Staff", staff):
		frappe.throw(_("Hồ sơ nhân sự không tồn tại."), frappe.ValidationError)
	try:
		maximum = int(max_active_students)
	except (TypeError, ValueError):
		frappe.throw(_("Giới hạn nhận phải là số nguyên."), frappe.ValidationError)
	if maximum <= 0:
		frappe.throw(_("Giới hạn nhận phải lớn hơn 0 để tham gia phân công tự động."), frappe.ValidationError)
	start = getdate(period_start or today())
	end = getdate(period_end or f"{start.year}-12-31")
	if start > end:
		frappe.throw(_("Ngày bắt đầu không được sau ngày kết thúc."), frappe.ValidationError)
	if len((reason or "").strip()) < 5:
		frappe.throw(_("Cần ghi lý do cập nhật capacity ít nhất 5 ký tự."), frappe.ValidationError)
	staff_row = frappe.db.get_value("CRM Staff", staff, ["campus", "is_active"], as_dict=True)
	if not staff_row or not staff_row.is_active:
		frappe.throw(_("Nhân sự phải đang hoạt động."), frappe.ValidationError)
	if not team:
		team = frappe.db.get_value(
			"CRM Team Membership",
			{"parent": staff, "parenttype": "CRM Staff", "is_primary": 1},
			"team",
		)
	if team:
		team_row = frappe.db.get_value("CRM Team", team, ["campus", "is_active", "team_type"], as_dict=True)
		membership_exists = frappe.db.exists(
			"CRM Team Membership",
			{"parent": staff, "parenttype": "CRM Staff", "team": team},
		)
		if not team_row or not team_row.is_active or team_row.team_type != "Sales" or not membership_exists:
			frappe.throw(_("Nhóm phải là nhóm đang hoạt động của nhân sự."), frappe.ValidationError)
		if team_row.campus and staff_row.campus and team_row.campus != staff_row.campus:
			frappe.throw(_("Nhóm và cơ sở của nhân sự không khớp."), frappe.ValidationError)
	existing = frappe.db.get_value(
		"CRM Staff Capacity Period",
		{"staff": staff, "period_start": start, "period_end": end},
		"name",
	)
	doc = frappe.get_doc("CRM Staff Capacity Period", existing) if existing else frappe.new_doc("CRM Staff Capacity Period")
	doc.staff = staff
	doc.team = team
	doc.campus = staff_row.campus
	doc.period_type = doc.period_type or "Term"
	doc.period_start = start
	doc.period_end = end
	doc.capacity_units = maximum
	doc.max_active_students = maximum
	doc.approved = 1
	doc.effective_from = start
	doc.effective_until = end
	doc.source_reference = f"assignment-overview:{frappe.session.user}:{reason.strip()}"[:140]
	doc.save(ignore_permissions=True)
	return get_routing_control()
