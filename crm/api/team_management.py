"""Team management projection and guarded commands for dashboard-crm.

CRM Team remains the routing unit. CRM Team Group is the province boundary
above a Team and is used to validate the routing topology.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import add_days, getdate, now_datetime, today

from crm.api.assignment_workspace import (
	_actor_context,
	_complete_topology_receipt,
	_date_active,
	_replay_topology_receipt,
	_reserve_topology_receipt,
	_topology_receipt,
)
from crm.fcrm.team_routing import team_routing_readiness

RECIPIENT_FUNCTIONS = {"Sale", "CTV Sale"}
SUPPORTED_FUNCTIONS = ("Sale", "CTV Sale", "Lead Sale")
TEAM_MANAGEMENT_READ_CAPABILITIES = frozenset(
	{"system.configure", "admissions.oversee", "team.oversee", "student.execute"}
)
TEAM_MANAGEMENT_WRITE_CAPABILITIES = frozenset(
	{"system.configure", "admissions.oversee", "team.oversee"}
)
TEAM_MANAGEMENT_TEMPORARY_WRITE_PROFILES = frozenset({"sales", "lead_sales"})


def _text(value, label, *, required=True, maximum=140):
	value = str(value or "").strip() if value is not None else ""
	if required and not value:
		frappe.throw(_("{0} là bắt buộc.").format(label), frappe.ValidationError)
	if len(value) > maximum:
		frappe.throw(_("{0} quá dài.").format(label), frappe.ValidationError)
	return value or None


def _bool(value, default=False):
	if value is None:
		return default
	if isinstance(value, bool):
		return value
	return str(value).lower() in {"1", "true", "yes", "on"}


def _error(code, message):
	exception = frappe.ValidationError(message)
	exception.code = code
	frappe.throw(message, exc=exception)


def _is_global(context):
	return bool(context.get("is_system_manager") or context.get("profile") in {"ceo", "admissions_director"})


def _can_manage_leads(context):
	return _is_global(context) or context.get("profile") in {"lead_sales", "sales"}


def _has_unrestricted_team_management_scope(context):
	return _is_global(context) or context.get("profile") in TEAM_MANAGEMENT_TEMPORARY_WRITE_PROFILES


def _require_access(*, write=False):
	context = _actor_context(required_capabilities=TEAM_MANAGEMENT_READ_CAPABILITIES)
	capabilities = set(context.get("capabilities") or [])
	if not capabilities.intersection(TEAM_MANAGEMENT_READ_CAPABILITIES):
		frappe.throw(_("Bạn không có quyền xem quản lý đội ngũ."), frappe.PermissionError)
	if write and not (
		capabilities.intersection(TEAM_MANAGEMENT_WRITE_CAPABILITIES)
		or context.get("profile") in TEAM_MANAGEMENT_TEMPORARY_WRITE_PROFILES
	):
		frappe.throw(_("Bạn không có quyền thay đổi quản lý đội ngũ."), frappe.PermissionError)
	return context


def _team_in_scope(team_id, context):
	return _has_unrestricted_team_management_scope(context) or team_id in set(context.get("teams") or [])


def _assert_team_scope(team_id, context):
	if not frappe.db.exists("CRM Team", team_id):
		_error("TEAM_NOT_FOUND", "Đội tư vấn không tồn tại.")
	if not _team_in_scope(team_id, context):
		frappe.throw(_("Đội này không thuộc phạm vi quản lý của bạn."), frappe.PermissionError)


def _assert_group_scope(group_id, context):
	if not frappe.db.exists("CRM Team Group", group_id):
		_error("GROUP_NOT_FOUND", "Nhóm quản lý không tồn tại.")
	if _has_unrestricted_team_management_scope(context):
		return
	team_ids = frappe.get_all("CRM Team", filters={"group": group_id}, pluck="name")
	if not set(team_ids).intersection(set(context.get("teams") or [])):
		frappe.throw(_("Nhóm này không thuộc phạm vi quản lý của bạn."), frappe.PermissionError)


def _active_memberships():
	rows = frappe.get_all(
		"CRM Team Membership",
		filters={"parenttype": "CRM Staff"},
		fields=[
			"name",
			"parent as staff",
			"team",
			"function",
			"term",
			"effective_from",
			"effective_until",
			"is_primary",
		],
		limit_page_length=0,
	)
	return [row for row in rows if _date_active(row)]


def _revision(payload):
	return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:24]


def _group_revision(group_id):
	row = frappe.db.get_value(
		"CRM Team Group",
		group_id,
		["name", "group_name", "province", "group_lead_staff", "is_active", "modified"],
		as_dict=True,
	)
	return _revision(dict(row)) if row else "0"


def _team_revision(team_id, memberships=None):
	row = frappe.db.get_value(
		"CRM Team",
		team_id,
		[
			"name",
			"team_name",
			"group",
			"team_type",
			"campus",
			"territory",
			"team_lead_staff",
			"is_active",
			"modified",
		],
		as_dict=True,
	)
	if not row:
		return "0"
	memberships = memberships if memberships is not None else _active_memberships()
	return _revision(
		{
			"team": dict(row),
			"memberships": [dict(item) for item in memberships if item.get("team") == team_id],
		}
	)


def _staff_revision(staff_id, memberships=None):
	row = frappe.db.get_value(
		"CRM Staff",
		staff_id,
		["name", "full_name", "user", "department", "campus", "is_active", "modified"],
		as_dict=True,
	)
	if not row:
		return "0"
	memberships = memberships if memberships is not None else _active_memberships()
	return _revision(
		{
			"staff": dict(row),
			"memberships": [dict(item) for item in memberships if item.get("staff") == staff_id],
		}
	)


def _command(
	action,
	payload,
	context,
	callback,
	*,
	idempotency_key=None,
	correlation_id=None,
):
	idempotency_key = _text(idempotency_key, "idempotency_key", maximum=140)
	correlation_id = _text(correlation_id or str(uuid.uuid4()), "correlation_id", maximum=140)
	command_key = hashlib.sha256(f"team-management|{context['actor']}|{idempotency_key}".encode()).hexdigest()
	fingerprint = hashlib.sha256(
		json.dumps({"action": action, **payload}, sort_keys=True, default=str).encode()
	).hexdigest()
	existing = _topology_receipt(command_key)
	if existing:
		return _replay_topology_receipt(existing, fingerprint)
	receipt = _reserve_topology_receipt(
		command_key=command_key,
		fingerprint=fingerprint,
		actor=context["actor"],
		correlation_id=correlation_id,
		context={**context, "workspace": "team_management"},
	)
	if isinstance(receipt, dict):
		return receipt
	try:
		result = callback()
		result.update({"status": "applied", "correlation_id": correlation_id, "replayed": False})
		_complete_topology_receipt(receipt, result)
		frappe.db.commit()
		return result
	except Exception:
		frappe.db.rollback()
		raise


def _staff_label(staff, fallback=None):
	return (staff or {}).get("full_name") or (staff or {}).get("name") or fallback or "—"


def _initials(name):
	parts = [part for part in str(name or "").split() if part]
	if len(parts) < 2:
		return str(name or "—")[:2].upper()
	return f"{parts[0][0]}{parts[-1][0]}".upper()


def _member_role(function):
	return {
		"Sale": "SALE",
		"CTV Sale": "CTV_SALE",
		"Lead Sale": "LEAD_SALE",
	}.get(function, "SALE")


def _read_workspace(context):
	groups = frappe.get_all(
		"CRM Team Group",
		fields=["name", "group_name", "province", "group_lead_staff", "is_active", "modified"],
		order_by="group_name asc, name asc",
		limit_page_length=0,
	)
	teams = frappe.get_all(
		"CRM Team",
		fields=[
			"name",
			"team_name",
			"group",
			"team_type",
			"campus",
			"territory",
			"team_lead_staff",
			"is_active",
			"modified",
		],
		order_by="team_name asc, name asc",
		limit_page_length=0,
	)
	staff = frappe.get_all(
		"CRM Staff",
		fields=["name", "full_name", "user", "department", "campus", "is_active", "modified"],
		order_by="full_name asc, name asc",
		limit_page_length=0,
	)
	memberships = _active_memberships()

	team_map = {row.name: row for row in teams}
	staff_map = {row.name: row for row in staff}
	members_by_team = defaultdict(list)
	memberships_by_staff = defaultdict(list)
	for membership in memberships:
		if membership.team in team_map and membership.staff in staff_map:
			members_by_team[membership.team].append(membership)
			memberships_by_staff[membership.staff].append(membership)

	zone_counts = defaultdict(int)
	pool_counts = defaultdict(int)
	policy_counts = defaultdict(int)
	if frappe.db.exists("DocType", "CRM Team Zone Assignment"):
		for row in frappe.get_all(
			"CRM Team Zone Assignment",
			filters={"status": "Active"},
			fields=["team", "zone", "effective_from", "effective_until"],
			limit_page_length=0,
		):
			if _date_active(row):
				zone_counts[row.team] += 1
	if frappe.db.exists("DocType", "CRM Student Pool"):
		pool_rows = frappe.get_all(
			"CRM Student Pool",
			filters={"is_active": 1},
			fields=["name", "team"],
			limit_page_length=0,
		)
		for row in pool_rows:
			pool_counts[row.team] += 1
		if frappe.db.exists("DocType", "CRM Student Routing Policy"):
			pool_to_team = {row.name: row.team for row in pool_rows}
			for row in frappe.get_all(
				"CRM Student Routing Policy",
				filters={"status": "active"},
				fields=["student_pool", "effective_from", "effective_until"],
				limit_page_length=0,
			):
				if _date_active(row) and pool_to_team.get(row.student_pool):
					policy_counts[pool_to_team[row.student_pool]] += 1

	team_rows = []
	for team in teams:
		team_members = members_by_team.get(team.name, [])
		lead_members = [
			row
			for row in team_members
			if row.function == "Lead Sale" and staff_map.get(row.staff) and staff_map[row.staff].is_active
		]
		recipient_members = [
			row
			for row in team_members
			if row.function in RECIPIENT_FUNCTIONS
			and staff_map.get(row.staff)
			and staff_map[row.staff].is_active
		]
		team_lead = next(
			(
				row
				for row in team_members
				if row.staff == team.team_lead_staff
				and staff_map.get(row.staff)
				and staff_map[row.staff].is_active
			),
			None,
		)
		lead_id = team.team_lead_staff
		if not team.is_active:
			readiness, readiness_reason = "inactive", "Đội đang ngừng hoạt động."
		elif not team_lead:
			readiness, readiness_reason = "not_ready", "Team chưa có Trưởng nhóm đang hoạt động."
		elif not recipient_members:
			readiness, readiness_reason = "not_ready", "Chưa có Sale/CTV Sale đang hoạt động."
		else:
			readiness, readiness_reason = "ready", "Đủ nhân sự để nhận Lead."
		if readiness != "ready":
			routing_readiness, routing_reason = readiness, readiness_reason
		else:
			routing = team_routing_readiness(team.name, campus=team.campus)
			routing_readiness, routing_reason = routing["status"], routing["reason"]
		team_rows.append(
			{
				"id": team.name,
				"name": team.team_name,
				"groupId": team.group,
				"teamType": team.team_type,
				"campusId": team.campus,
				"territoryId": team.territory,
				"leadId": lead_id,
				"memberIds": sorted({row.staff for row in team_members}),
				"memberCount": len({row.staff for row in team_members}),
				"leadCount": len(lead_members),
				"saleCount": sum(row.function == "Sale" for row in recipient_members),
				"ctvCount": sum(row.function == "CTV Sale" for row in recipient_members),
				"zoneCount": zone_counts[team.name],
				"poolCount": pool_counts[team.name],
				"policyCount": policy_counts[team.name],
				"isActive": bool(team.is_active),
				"readiness": readiness,
				"readinessReason": readiness_reason,
				"routingReadiness": routing_readiness,
				"routingReadinessReason": routing_reason,
				"revision": _team_revision(team.name, memberships),
			}
		)

	member_rows = []
	for row in staff:
		joined = memberships_by_staff.get(row.name, [])
		primary = next((item for item in joined if item.is_primary), joined[0] if joined else None)
		function = primary.function if primary else "Sale"
		member_rows.append(
			{
				"id": row.name,
				"name": row.full_name,
				"initials": _initials(row.full_name),
				"email": row.user,
				"role": _member_role(function),
				"isActive": bool(row.is_active),
				"campusId": row.campus,
				"teamIds": sorted({item.team for item in joined}),
				"memberships": [
					{
						"id": item.name,
						"teamId": item.team,
						"function": item.function,
						"role": _member_role(item.function),
						"isPrimary": bool(item.is_primary),
						"isTeamLead": bool(
							team_map.get(item.team) and team_map[item.team].team_lead_staff == row.name
						),
						"term": item.term,
					}
					for item in joined
				],
				"revision": _staff_revision(row.name, memberships),
			}
		)

	group_rows = []
	for group in groups:
		group_teams = [row for row in team_rows if row["groupId"] == group.name]
		group_member_ids = {member_id for team in group_teams for member_id in team["memberIds"]}
		group_rows.append(
			{
				"id": group.name,
				"name": group.group_name,
				"groupLeadId": group.group_lead_staff,
				"provinceId": group.province,
				"provinceCode": frappe.db.get_value("CRM Province", group.province, "province_code")
				if group.province
				else None,
				"provinceName": frappe.db.get_value("CRM Province", group.province, "province_name")
				if group.province
				else None,
				"teamIds": [team["id"] for team in group_teams],
				"teamCount": len(group_teams),
				"memberCount": len(group_member_ids),
				"isActive": bool(group.is_active),
				"revision": _group_revision(group.name),
			}
		)

	campuses = frappe.get_all(
		"CRM Campus", fields=["name", "campus_name"], order_by="campus_name asc, name asc"
	)
	provinces = frappe.get_all(
		"CRM Province",
		fields=["name", "province_name", "province_code"],
		order_by="province_name asc, name asc",
		limit_page_length=0,
	)
	return {
		"schemaVersion": "team-management-v1",
		"asOf": str(now_datetime()),
		"summary": {
			"groupCount": len(group_rows),
			"teamCount": len(team_rows),
			"activeTeamCount": sum(row["isActive"] for row in team_rows),
			"staffCount": len(member_rows),
			"activeStaffCount": sum(row["isActive"] for row in member_rows),
		},
		"groups": group_rows,
		"teams": team_rows,
		"members": member_rows,
		"options": {
			"campuses": [{"id": row.name, "label": row.campus_name or row.name} for row in campuses],
			"provinces": [
				{
					"id": row.name,
					"label": row.province_name or row.name,
					"code": row.province_code,
				}
				for row in provinces
			],
			"functions": [{"value": value, "label": value} for value in SUPPORTED_FUNCTIONS],
		},
		"permissions": {
			"canManage": bool(
				set(context.get("capabilities") or []).intersection(
					{"system.configure", "admissions.oversee", "team.oversee"}
				)
			),
			"canManageAll": _is_global(context),
		},
	}


@frappe.whitelist()
def get_team_management_workspace():
	context = _require_access()
	return _read_workspace(context)


@frappe.whitelist()
def get_team_group_detail(group_id):
	context = _require_access()
	_assert_group_scope(_text(group_id, "group_id"), context)
	payload = _read_workspace(context)
	group_id = str(group_id)
	return {
		**payload,
		"group": next((row for row in payload["groups"] if row["id"] == group_id), None),
		"teams": [row for row in payload["teams"] if row["groupId"] == group_id],
	}


@frappe.whitelist()
def get_team_detail(team_id):
	context = _require_access()
	team_id = _text(team_id, "team_id")
	_assert_team_scope(team_id, context)
	payload = _read_workspace(context)
	team = next((row for row in payload["teams"] if row["id"] == team_id), None)
	if not team:
		_error("TEAM_NOT_FOUND", "Đội tư vấn không tồn tại.")
	member_ids = set(team["memberIds"])
	return {
		**payload,
		"team": team,
		"group": next((row for row in payload["groups"] if row["id"] == team["groupId"]), None),
		"members": [row for row in payload["members"] if row["id"] in member_ids],
	}


def _save_group(
	group_id,
	group_name,
	province,
	group_lead_staff,
	clear_group_lead,
	is_active,
	context,
):
	group_id = _text(group_id, "group_id", required=False)
	group_name = _text(group_name, "group_name")
	if group_id:
		_assert_group_scope(group_id, context)
		doc = frappe.get_doc("CRM Team Group", group_id)
	else:
		if frappe.db.exists("CRM Team Group", {"group_name": group_name}):
			_error("GROUP_ALREADY_EXISTS", "Tên nhóm quản lý đã tồn tại.")
		doc = frappe.get_doc({"doctype": "CRM Team Group"})
	doc.group_name = group_name
	if province is not None:
		doc.province = _text(province, "province", required=False)
	if not doc.province and _bool(is_active, True):
		_error("GROUP_PROVINCE_REQUIRED", "Group đang hoạt động phải được gắn với một tỉnh.")
	if doc.province and _bool(is_active, True):
		other_group = frappe.db.get_value(
			"CRM Team Group",
			{
				"province": doc.province,
				"is_active": 1,
				"name": ["!=", doc.name or ""],
			},
			"name",
		)
		if other_group:
			_error("PROVINCE_GROUP_EXISTS", "Tỉnh này đã có Group đang hoạt động.")
	if (clear_group_lead or group_lead_staff is not None) and not _can_manage_leads(context):
		frappe.throw(_("Bạn không có quyền đổi Trưởng Group."), frappe.PermissionError)
	if clear_group_lead:
		doc.group_lead_staff = None
	elif group_lead_staff is not None:
		staff = frappe.db.get_value("CRM Staff", group_lead_staff, ["name", "is_active"], as_dict=True)
		if not staff:
			_error("STAFF_NOT_FOUND", "Nhân sự không tồn tại.")
		if not staff.is_active:
			_error("STAFF_INACTIVE", "Trưởng Group phải là nhân sự đang hoạt động.")
		doc.group_lead_staff = group_lead_staff
	doc.is_active = int(_bool(is_active, True))
	if group_id:
		doc.save(ignore_permissions=True)
	else:
		doc.insert(ignore_permissions=True)
	return {
		"action": "group_setup",
		"groupId": doc.name,
		"revision": _group_revision(doc.name),
	}


@frappe.whitelist(methods=["POST"])
def save_team_group(
	group_id=None,
	group_name=None,
	province=None,
	group_lead_staff=None,
	clear_group_lead=False,
	is_active=True,
	expected_revision=None,
	idempotency_key=None,
	correlation_id=None,
):
	context = _require_access(write=True)
	if not group_id and not _is_global(context):
		frappe.throw(
			_("Chỉ quản trị viên cấp Admissions mới được tạo Group."),
			frappe.PermissionError,
		)
	payload = {
		"group_id": group_id,
		"group_name": group_name,
		"province": province,
		"group_lead_staff": group_lead_staff,
		"clear_group_lead": _bool(clear_group_lead),
		"is_active": _bool(is_active, True),
		"expected_revision": expected_revision,
	}

	def apply():
		if group_id and str(expected_revision or "") != _group_revision(group_id):
			_error("STALE_GROUP_REVISION", "Nhóm đã thay đổi; hãy tải lại trước khi lưu.")
		return _save_group(
			group_id,
			group_name,
			province,
			group_lead_staff,
			_bool(clear_group_lead),
			is_active,
			context,
		)

	return _command(
		"group_setup",
		payload,
		context,
		apply,
		idempotency_key=idempotency_key,
		correlation_id=correlation_id,
	)


def _save_team(
	team_id,
	team_name,
	group_id,
	team_type,
	campus,
	territory,
	team_lead_staff,
	is_active,
	context,
):
	team_id = _text(team_id, "team_id", required=False)
	team_name = _text(team_name, "team_name")
	campus = _text(campus, "campus")
	if not frappe.db.exists("CRM Campus", campus):
		_error("CAMPUS_NOT_FOUND", "Cơ sở không tồn tại.")
	if not _is_global(context) and campus not in set(context.get("campuses") or []):
		frappe.throw(_("Cơ sở này không thuộc phạm vi quản lý của bạn."), frappe.PermissionError)
	if group_id:
		_assert_group_scope(group_id, context)
		group = frappe.db.get_value("CRM Team Group", group_id, ["is_active", "province"], as_dict=True)
		if not group.is_active and _bool(is_active, True):
			_error("GROUP_INACTIVE", "Không thể bật Team trong nhóm đã ngừng hoạt động.")
		if _bool(is_active, True) and not group.province:
			_error("GROUP_PROVINCE_REQUIRED", "Group phải được gắn tỉnh trước khi bật Team.")
	if team_id:
		_assert_team_scope(team_id, context)
		doc = frappe.get_doc("CRM Team", team_id)
		requested_lead = _text(team_lead_staff, "team_lead_staff", required=False)
		if not _can_manage_leads(context) and requested_lead != (doc.team_lead_staff or None):
			frappe.throw(
				_("Bạn không có quyền chọn hoặc thay đổi Trưởng nhóm."),
				frappe.PermissionError,
			)
	else:
		if frappe.db.exists("CRM Team", {"team_name": team_name}):
			_error("TEAM_ALREADY_EXISTS", "Tên đội tư vấn đã tồn tại.")
		doc = frappe.get_doc({"doctype": "CRM Team"})
		if team_lead_staff and not _can_manage_leads(context):
			frappe.throw(
				_("Bạn không có quyền chọn Trưởng nhóm."),
				frappe.PermissionError,
			)
	doc.team_name = team_name
	if group_id is not None:
		doc.group = _text(group_id, "group_id", required=False)
	elif not team_id and _bool(is_active, True):
		_error("GROUP_REQUIRED", "Team mới đang hoạt động phải thuộc một Group.")
	doc.team_type = _text(team_type or "Sales", "team_type")
	doc.campus = campus
	doc.territory = _text(territory, "territory", required=False)
	doc.team_lead_staff = _text(team_lead_staff, "team_lead_staff", required=False)
	doc.is_active = int(_bool(is_active, True))
	if team_id:
		doc.save(ignore_permissions=True)
	else:
		doc.insert(ignore_permissions=True)
	return {
		"action": "team_setup",
		"teamId": doc.name,
		"revision": _team_revision(doc.name),
	}


@frappe.whitelist(methods=["POST"])
def save_team(
	team_id=None,
	team_name=None,
	group_id=None,
	team_type="Sales",
	campus=None,
	territory=None,
	team_lead_staff=None,
	is_active=True,
	expected_revision=None,
	idempotency_key=None,
	correlation_id=None,
):
	context = _require_access(write=True)
	payload = {
		"team_id": team_id,
		"team_name": team_name,
		"group_id": group_id,
		"team_type": team_type,
		"campus": campus,
		"territory": territory,
		"team_lead_staff": team_lead_staff,
		"is_active": _bool(is_active, True),
		"expected_revision": expected_revision,
	}

	def apply():
		if team_id and str(expected_revision or "") != _team_revision(team_id):
			_error("STALE_TEAM_REVISION", "Đội đã thay đổi; hãy tải lại trước khi lưu.")
		return _save_team(
			team_id,
			team_name,
			group_id,
			team_type,
			campus,
			territory,
			team_lead_staff,
			is_active,
			context,
		)

	return _command(
		"team_setup",
		payload,
		context,
		apply,
		idempotency_key=idempotency_key,
		correlation_id=correlation_id,
	)


def _staff_doc(staff_id, context):
	staff_id = _text(staff_id, "staff_id")
	staff = frappe.get_doc("CRM Staff", staff_id)
	if not staff.is_active:
		_error("STAFF_INACTIVE", "Nhân sự đã ngừng hoạt động.")
	if not _is_global(context) and staff.campus not in set(context.get("campuses") or []):
		frappe.throw(_("Nhân sự không thuộc phạm vi quản lý của bạn."), frappe.PermissionError)
	return staff


def _team_doc(team_id, context):
	team_id = _text(team_id, "team_id")
	_assert_team_scope(team_id, context)
	return frappe.get_doc("CRM Team", team_id)


def _clear_primary_conflicts(staff_doc, team, function, term, keep_name=None):
	for row in staff_doc.team_memberships:
		if (
			row.name != keep_name
			and row.is_primary
			and row.function == function
			and row.term == term
			and frappe.db.get_value("CRM Team", row.team, "campus") == team.campus
		):
			row.is_primary = 0


def _find_active_membership(staff_doc, team_id):
	return next(
		(row for row in staff_doc.team_memberships if row.team == team_id and _date_active(row.as_dict())),
		None,
	)


def _save_membership(
	staff_id,
	team_id,
	function,
	is_primary,
	term,
	is_team_lead,
	context,
):
	staff_doc = _staff_doc(staff_id, context)
	team_doc = _team_doc(team_id, context)
	if not team_doc.is_active:
		_error("TEAM_INACTIVE", "Không thể thêm nhân sự vào Team đang ngừng hoạt động.")
	if team_doc.team_type != "Sales":
		_error("TEAM_TYPE_INVALID", "Chỉ đội Sales mới nhận Lead.")
	if staff_doc.campus != team_doc.campus:
		_error("CAMPUS_MISMATCH", "Nhân sự và Team phải cùng Cơ sở.")
	function = _text(function or "Sale", "function")
	if function not in SUPPORTED_FUNCTIONS:
		_error("FUNCTION_INVALID", "Vai trò nhân sự không được hỗ trợ.")
	is_team_lead = _bool(is_team_lead)
	if is_team_lead and not _can_manage_leads(context):
		frappe.throw(
			_("Bạn không có quyền chọn Trưởng nhóm."),
			frappe.PermissionError,
		)
	term = _text(term, "term", required=False)
	membership = _find_active_membership(staff_doc, team_id)
	if membership and team_doc.team_lead_staff == staff_doc.name and not is_team_lead:
		_error(
			"TEAM_LEAD_REPLACEMENT_REQUIRED",
			"Hãy chọn Trưởng nhóm mới trước khi hạ vai trò hoặc chuyển người này.",
		)
	if membership:
		membership.function = function
		membership.term = term
		membership.is_primary = int(_bool(is_primary))
		membership.is_team_lead = int(is_team_lead)
	else:
		membership = staff_doc.append(
			"team_memberships",
			{
				"team": team_id,
				"function": function,
				"term": term,
				"is_primary": int(_bool(is_primary)),
				"is_team_lead": int(is_team_lead),
				"effective_from": today(),
			},
		)
	_clear_primary_conflicts(staff_doc, team_doc, function, term, membership.name)
	staff_doc.save(ignore_permissions=True)
	if is_team_lead:
		team_doc.team_lead_staff = staff_doc.name
		team_doc.save(ignore_permissions=True)
	return {
		"action": "membership_setup",
		"staffId": staff_doc.name,
		"teamId": team_doc.name,
		"revision": _revision(
			{
				"staff": staff_doc.name,
				"modified": staff_doc.modified,
				"memberships": [row.as_dict() for row in staff_doc.team_memberships],
			}
		),
	}


@frappe.whitelist(methods=["POST"])
def add_team_member(
	staff_id=None,
	team_id=None,
	function="Sale",
	is_primary=False,
	term=None,
	is_team_lead=False,
	idempotency_key=None,
	correlation_id=None,
):
	context = _require_access(write=True)
	payload = {
		"staff_id": staff_id,
		"team_id": team_id,
		"function": function,
		"is_primary": _bool(is_primary),
		"term": term,
		"is_team_lead": _bool(is_team_lead),
	}
	return _command(
		"membership_setup",
		payload,
		context,
		lambda: _save_membership(
			staff_id,
			team_id,
			function,
			is_primary,
			term,
			is_team_lead,
			context,
		),
		idempotency_key=idempotency_key,
		correlation_id=correlation_id,
	)


@frappe.whitelist(methods=["POST"])
def move_team_member(
	staff_id=None,
	source_team_id=None,
	target_team_id=None,
	function="Sale",
	is_primary=False,
	term=None,
	idempotency_key=None,
	correlation_id=None,
):
	context = _require_access(write=True)
	payload = {
		"staff_id": staff_id,
		"source_team_id": source_team_id,
		"target_team_id": target_team_id,
		"function": function,
		"is_primary": _bool(is_primary),
		"term": term,
	}

	def apply():
		source_team = _team_doc(source_team_id, context)
		target_team = _team_doc(target_team_id, context)
		if source_team.name == target_team.name:
			_error("SAME_TEAM", "Team nguồn và Team đích phải khác nhau.")
		if not target_team.is_active:
			_error("TEAM_INACTIVE", "Không thể chuyển nhân sự vào Team đang ngừng hoạt động.")
		if source_team.campus != target_team.campus:
			_error("CAMPUS_MISMATCH", "Team nguồn và Team đích phải cùng Cơ sở.")
		staff_doc = _staff_doc(staff_id, context)
		source_membership = _find_active_membership(staff_doc, source_team.name)
		if not source_membership:
			_error("MEMBERSHIP_NOT_FOUND", "Nhân sự không còn thuộc Team nguồn.")
		function_name = _text(function or source_membership.function or "Sale", "function")
		if function_name not in SUPPORTED_FUNCTIONS:
			_error("FUNCTION_INVALID", "Vai trò nhân sự không được hỗ trợ.")
		if source_team.team_lead_staff == staff_doc.name:
			_error(
				"TEAM_LEAD_REPLACEMENT_REQUIRED",
				"Hãy chọn Trưởng nhóm mới trước khi chuyển người này.",
			)
		source_membership.effective_until = add_days(getdate(today()), -1)
		target_membership = _find_active_membership(staff_doc, target_team.name)
		if target_membership:
			target_membership.function = function_name
			target_membership.is_primary = int(_bool(is_primary))
		else:
			target_membership = staff_doc.append(
				"team_memberships",
				{
					"team": target_team.name,
					"function": function_name,
					"term": term or source_membership.term,
					"is_primary": int(_bool(is_primary)),
					"is_team_lead": 0,
					"effective_from": today(),
				},
			)
		_clear_primary_conflicts(
			staff_doc,
			target_team,
			target_membership.function,
			target_membership.term,
			target_membership.name,
		)
		staff_doc.save(ignore_permissions=True)
		return {
			"action": "membership_move",
			"staffId": staff_doc.name,
			"sourceTeamId": source_team.name,
			"targetTeamId": target_team.name,
			"revision": _revision(
				{
					"staff": staff_doc.name,
					"modified": staff_doc.modified,
					"memberships": [row.as_dict() for row in staff_doc.team_memberships],
				}
			),
		}

	return _command(
		"membership_move",
		payload,
		context,
		apply,
		idempotency_key=idempotency_key,
		correlation_id=correlation_id,
	)


@frappe.whitelist(methods=["POST"])
def remove_team_member(
	staff_id=None,
	team_id=None,
	expected_revision=None,
	idempotency_key=None,
	correlation_id=None,
):
	context = _require_access(write=True)
	payload = {
		"staff_id": staff_id,
		"team_id": team_id,
		"expected_revision": expected_revision,
	}

	def apply():
		staff_doc = _staff_doc(staff_id, context)
		team_doc = _team_doc(team_id, context)
		if expected_revision and expected_revision != _staff_revision(staff_id):
			_error("STALE_STAFF_REVISION", "Nhân sự đã thay đổi; hãy tải lại trước khi lưu.")
		membership = _find_active_membership(staff_doc, team_doc.name)
		if not membership:
			_error("MEMBERSHIP_NOT_FOUND", "Nhân sự không còn thuộc Team.")
		if team_doc.is_active and team_doc.team_lead_staff == staff_doc.name:
			_error(
				"TEAM_LEAD_REPLACEMENT_REQUIRED",
				"Hãy chọn Trưởng nhóm mới trước khi gỡ người này.",
			)
		recipient_count = sum(
			1
			for row in _active_memberships()
			if row.team == team_doc.name
			and row.staff != staff_doc.name
			and row.function in RECIPIENT_FUNCTIONS
			and frappe.db.get_value("CRM Staff", row.staff, "is_active")
		)
		if team_doc.is_active and recipient_count == 0:
			_error(
				"TEAM_WOULD_BE_EMPTY",
				"Không thể gỡ người cuối cùng có thể nhận Lead khỏi Team đang hoạt động.",
			)
		membership.effective_until = add_days(getdate(today()), -1)
		staff_doc.save(ignore_permissions=True)
		if team_doc.team_lead_staff == staff_doc.name:
			team_doc.team_lead_staff = None
			team_doc.save(ignore_permissions=True)
		return {"action": "membership_remove", "staffId": staff_id, "teamId": team_id}

	return _command(
		"membership_remove",
		payload,
		context,
		apply,
		idempotency_key=idempotency_key,
		correlation_id=correlation_id,
	)


@frappe.whitelist(methods=["POST"])
def change_team_lead(
	team_id=None,
	new_lead_staff=None,
	expected_revision=None,
	idempotency_key=None,
	correlation_id=None,
):
	"""Change the organizational Team leader without changing staff function."""
	context = _require_access(write=True)
	if not _can_manage_leads(context):
		frappe.throw(
			_("Bạn không có quyền chọn hoặc thay đổi Trưởng nhóm."),
			frappe.PermissionError,
		)
	payload = {
		"team_id": team_id,
		"new_lead_staff": new_lead_staff,
		"expected_revision": expected_revision,
	}

	def apply():
		team_doc = _team_doc(team_id, context)
		if not team_doc.is_active:
			_error("TEAM_INACTIVE", "Không thể đổi Trưởng nhóm trong Team đang ngừng hoạt động.")
		if expected_revision and expected_revision != _team_revision(team_doc.name):
			_error("STALE_TEAM_REVISION", "Đội đã thay đổi; hãy tải lại trước khi lưu.")
		new_staff_doc = _staff_doc(new_lead_staff, context)
		if new_staff_doc.campus != team_doc.campus:
			_error("CAMPUS_MISMATCH", "Nhân sự và Team phải cùng Cơ sở.")
		new_membership = _find_active_membership(new_staff_doc, team_doc.name)
		if not new_membership:
			_error(
				"MEMBERSHIP_NOT_FOUND",
				"Trưởng nhóm mới phải là thành viên đang hoạt động của Team.",
			)

		previous_lead_id = team_doc.team_lead_staff
		if previous_lead_id == new_staff_doc.name:
			return {
				"action": "team_lead_change",
				"teamId": team_doc.name,
				"previousLeadId": previous_lead_id,
				"teamLeadStaffId": new_staff_doc.name,
				"revision": _team_revision(team_doc.name),
			}

		frappe.db.set_value(
			"CRM Team",
			team_doc.name,
			"team_lead_staff",
			new_staff_doc.name,
			update_modified=False,
		)
		for row in _active_memberships():
			if row.team == team_doc.name:
				frappe.db.set_value(
					"CRM Team Membership",
					row.name,
					"is_team_lead",
					int(row.staff == new_staff_doc.name),
					update_modified=False,
				)
		return {
			"action": "team_lead_change",
			"teamId": team_doc.name,
			"previousLeadId": previous_lead_id,
			"teamLeadStaffId": new_staff_doc.name,
			"revision": _team_revision(team_doc.name),
		}

	return _command(
		"team_lead_change",
		payload,
		context,
		apply,
		idempotency_key=idempotency_key,
		correlation_id=correlation_id,
	)


@frappe.whitelist(methods=["POST"])
def update_team_member(
	staff_id=None,
	full_name=None,
	expected_revision=None,
	idempotency_key=None,
	correlation_id=None,
):
	context = _require_access(write=True)
	full_name = _text(full_name, "full_name")
	payload = {
		"staff_id": staff_id,
		"full_name": full_name,
		"expected_revision": expected_revision,
	}

	def apply():
		staff_doc = _staff_doc(staff_id, context)
		if expected_revision and expected_revision != _staff_revision(staff_id):
			_error("STALE_STAFF_REVISION", "Nhân sự đã thay đổi; hãy tải lại trước khi lưu.")
		staff_doc.full_name = full_name
		staff_doc.save(ignore_permissions=True)
		return {"action": "staff_update", "staffId": staff_doc.name, "fullName": full_name}

	return _command(
		"staff_update",
		payload,
		context,
		apply,
		idempotency_key=idempotency_key,
		correlation_id=correlation_id,
	)
