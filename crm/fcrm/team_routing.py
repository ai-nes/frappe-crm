"""Shared readiness and selection rules for province-based Lead routing.

Lead batches use the small, operator-friendly topology::

    CRM Lead.province -> CRM Team Group.province -> active CRM Team -> Sale/CTV

Zone, Student Pool and Student Routing Policy remain available to the legacy
Student service, but they are deliberately not prerequisites for a Lead batch.
Keeping that distinction here prevents the dashboard and batch API from
silently reintroducing the old setup checklist.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import getdate, now_datetime

from crm.fcrm.role_policy import resolve_crm_profile
from crm.fcrm.utils.effective import is_effective

RECIPIENT_FUNCTIONS = {"Sale", "CTV Sale"}


def province_for_zone(zone: str | None) -> str | None:
	"""Resolve a Zone's canonical Province through Cluster."""
	if not zone or not frappe.db.exists("CRM Zone", zone):
		return None
	cluster = frappe.db.get_value("CRM Zone", zone, "cluster")
	if not cluster:
		return None
	return frappe.db.get_value("CRM Cluster", cluster, "province")


def _active_memberships(team_id: str, at=None) -> list[dict[str, Any]]:
	at = at or now_datetime()
	rows = frappe.get_all(
		"CRM Team Membership",
		filters={"team": team_id, "parenttype": "CRM Staff"},
		fields=["parent as staff", "function", "effective_from", "effective_until"],
		limit_page_length=0,
	)
	return [row for row in rows if is_effective(row, at)]


def team_routing_readiness(
	team_id: str,
	*,
	campus: str | None = None,
	expected_province: str | None = None,
	at=None,
) -> dict[str, Any]:
	"""Return whether a Team is ready for province-based Lead routing.

	This is intentionally a read-only check.  It does not repair legacy data or
	change ownership; callers decide whether to block an operation or display a
	setup warning.
	"""
	at = at or now_datetime()
	team = frappe.db.get_value(
		"CRM Team",
		team_id,
		["name", "team_name", "group", "campus", "team_type", "is_active", "team_lead_staff"],
		as_dict=True,
	)
	base = {
		"team": team_id,
		"teamName": (team or {}).get("team_name") or team_id,
		"group": (team or {}).get("group"),
		"province": None,
		"zoneCount": 0,
		"poolCount": 0,
		"policyCount": 0,
		"leadCount": 0,
		"recipientCount": 0,
		"status": "not_ready",
		"reason": "Team không tồn tại.",
		"reasonCode": "team_missing",
	}
	if not team:
		return base
	if not team.is_active:
		base.update(status="inactive", reason="Team đang ngừng hoạt động.", reasonCode="team_inactive")
		return base
	if team.team_type != "Sales":
		base["reason"] = "Chỉ Team Sales mới được nhận Lead."
		base["reasonCode"] = "team_type_mismatch"
		return base
	if campus and team.campus != campus:
		base["reason"] = "Team và cơ sở của Lead không khớp."
		base["reasonCode"] = "campus_mismatch"
		return base

	group = (
		frappe.db.get_value(
			"CRM Team Group",
			team.group,
			["name", "group_name", "province", "is_active"],
			as_dict=True,
		)
		if team.group
		else None
	)
	if not group or not group.is_active:
		base["reason"] = "Team chưa thuộc một Group đang hoạt động."
		base["reasonCode"] = "group_inactive"
		return base
	base["province"] = group.province
	if not group.province:
		base["reason"] = "Group chưa được gắn tỉnh."
		base["reasonCode"] = "group_missing_province"
		return base
	if expected_province and group.province != expected_province:
		base["reason"] = "Tỉnh của Team không khớp với tỉnh của Lead/Zone."
		base["reasonCode"] = "province_mismatch"
		return base

	staff_ids = {
		row.name
		for row in frappe.get_all("CRM Staff", filters={"is_active": 1}, fields=["name"], limit_page_length=0)
	}
	memberships = [row for row in _active_memberships(team_id, at) if row.staff != team.team_lead_staff]
	lead_members = [row for row in memberships if row.function == "Lead Sale" and row.staff in staff_ids]
	recipient_members = [
		row for row in memberships if row.function in RECIPIENT_FUNCTIONS and row.staff in staff_ids
	]
	base["leadCount"] = len(lead_members)
	base["recipientCount"] = len(recipient_members)
	team_lead_staff = team.team_lead_staff if team.team_lead_staff in staff_ids else None
	if not team_lead_staff:
		base["reason"] = "Team chưa có Trưởng nhóm đang hoạt động."
		base["reasonCode"] = "team_lead_missing"
		return base
	if not recipient_members:
		base["reason"] = "Team chưa có Sale hoặc CTV Sale đang hoạt động."
		base["reasonCode"] = "no_recipients"
		return base

	# Zone assignments are informational legacy data.  They are intentionally
	# not part of Lead batch readiness anymore.
	zone_rows = (
		frappe.get_all(
			"CRM Team Zone Assignment",
			filters={"team": team_id, "status": "Active", "effective_from": ["<=", getdate(at)]},
			fields=["zone", "effective_from", "effective_until"],
			limit_page_length=0,
		)
		if frappe.db.exists("DocType", "CRM Team Zone Assignment")
		else []
	)
	zone_rows = [row for row in zone_rows if is_effective(row, at)]
	base["zoneCount"] = len(zone_rows)
	base.update(
		status="ready",
		reason="Team có tỉnh, Trưởng nhóm và Sale/CTV đang hoạt động.",
		reasonCode="ready",
	)
	return base


def _active_teams_for_province(
	province: str | None,
	*,
	campus: str | None = None,
	team_id: str | None = None,
) -> list[dict[str, Any]]:
	"""Return active Sales Teams in a province, or all provinces when None."""
	filters: dict[str, Any] = {"is_active": 1, "team_type": "Sales"}
	if team_id:
		filters["name"] = team_id
	rows = frappe.get_all(
		"CRM Team",
		filters=filters,
		fields=["name", "team_name", "group", "campus", "team_type", "is_active"],
		order_by="team_name asc, name asc",
		limit_page_length=0,
	)
	result = []
	for row in rows:
		if campus and row.get("campus") != campus:
			continue
		group = frappe.db.get_value(
			"CRM Team Group",
			row.get("group"),
			["name", "group_name", "province", "is_active"],
			as_dict=True,
		)
		if not group or not group.is_active or (province is not None and group.province != province):
			continue
		result.append({**dict(row), "groupName": group.group_name, "province": group.province})
	return result


def _active_teams_for_group(
	group_id: str,
	*,
	campus: str | None = None,
	team_id: str | None = None,
) -> list[dict[str, Any]]:
	"""Return active Sales Teams in one Group, optionally constrained by campus."""
	filters: dict[str, Any] = {"is_active": 1, "team_type": "Sales", "group": group_id}
	if team_id:
		filters["name"] = team_id
	rows = frappe.get_all(
		"CRM Team",
		filters=filters,
		fields=["name", "team_name", "group", "campus", "team_type", "is_active"],
		order_by="team_name asc, name asc",
		limit_page_length=0,
	)
	group = frappe.db.get_value(
		"CRM Team Group",
		group_id,
		["name", "group_name", "province", "is_active"],
		as_dict=True,
	)
	if not group or not group.is_active:
		return []
	return [
		{**dict(row), "groupName": group.group_name, "province": group.province}
		for row in rows
		if not campus or row.get("campus") == campus
	]


def _active_teams_for_campus(
	campus: str,
	*,
	team_id: str | None = None,
) -> list[dict[str, Any]]:
	"""Return every active Sales Team in one campus, independent of province."""
	filters: dict[str, Any] = {"is_active": 1, "team_type": "Sales", "campus": campus}
	if team_id:
		filters["name"] = team_id
	rows = frappe.get_all(
		"CRM Team",
		filters=filters,
		fields=["name", "team_name", "group", "campus", "team_type", "is_active"],
		order_by="team_name asc, name asc",
		limit_page_length=0,
	)
	result = []
	for row in rows:
		group = (
			frappe.db.get_value(
				"CRM Team Group",
				row.get("group"),
				["name", "group_name", "province", "is_active"],
				as_dict=True,
			)
			if row.get("group")
			else None
		)
		if group and not group.is_active:
			continue
		result.append(
			{
				**dict(row),
				"groupName": (group or {}).get("group_name"),
				"province": (group or {}).get("province"),
			}
		)
	return result


def _capacity_snapshot(limit: int, active: int, *, configured: bool = True) -> dict[str, int | bool | None]:
	return {
		"active": active,
		"limit": limit or None,
		"remaining": max(0, limit - active) if limit else None,
		"configured": configured,
	}


def _staff_capacity(staff: str, at=None) -> dict[str, int | bool | None]:
	"""Report active Lead load without requiring or enforcing a capacity period."""
	return _capacity_snapshot(0, active_lead_count(staff), configured=False)


def active_lead_count(staff: str) -> int:
	"""Count current ownership using the Lead assignment workflow state.

	Assignment capacity uses processing status and the converted Student link,
	and treats missing processing
	status as an active legacy Lead, not as an SQL ``NULL NOT IN`` miss.
	"""
	if not staff:
		return 0
	row = frappe.db.sql(
		"""
		select count(distinct name)
		from `tabCRM Lead`
		where (owner_staff = %s or assigned_to = %s)
			and coalesce(processing_status, 'NEW') <> 'CLOSED'
			and coalesce(converted_student, '') = ''
		""",
		(staff, staff),
	)[0]
	return int(row[0] or 0)


def active_lead_count_by_staff(staff_ids: list[str]) -> dict[str, int]:
	"""Batched form of ``active_lead_count`` for many staff at once.

	Used where a per-staff loop would issue one query per staff (e.g. a Users
	admin listing) instead of one query for the whole page.
	"""
	staff_ids = [s for s in staff_ids if s]
	if not staff_ids:
		return {}
	rows = frappe.db.sql(
		"""
		select staff, count(distinct name) as active
		from (
			select owner_staff as staff, name
			from `tabCRM Lead`
			where owner_staff in %(staff_ids)s
				and coalesce(processing_status, 'NEW') <> 'CLOSED'
				and coalesce(converted_student, '') = ''
			union
			select assigned_to as staff, name
			from `tabCRM Lead`
			where assigned_to in %(staff_ids)s
				and coalesce(processing_status, 'NEW') <> 'CLOSED'
				and coalesce(converted_student, '') = ''
		) combined
		group by staff
		""",
		{"staff_ids": staff_ids},
		as_dict=True,
	)
	return {row.staff: int(row.active or 0) for row in rows}


def _team_recipient_pool(team_id: str, at=None) -> list[dict[str, Any]]:
	"""Resolve active Sale/CTV members and their current Lead load."""
	at = at or now_datetime()
	team_lead_staff = frappe.db.get_value("CRM Team", team_id, "team_lead_staff")
	memberships = [
		row
		for row in _active_memberships(team_id, at)
		if row.function in RECIPIENT_FUNCTIONS and row.staff != team_lead_staff
	]
	staff_ids = sorted({row.staff for row in memberships if row.staff})
	if not staff_ids:
		return []
	staff_rows = frappe.get_all(
		"CRM Staff",
		filters={"name": ["in", staff_ids], "is_active": 1},
		fields=["name", "full_name", "user", "campus"],
		limit_page_length=0,
	)
	by_id = {row.name: row for row in staff_rows}
	result = []
	for membership in memberships:
		staff = by_id.get(membership.staff)
		if not staff or not staff.user:
			continue
		if frappe.db.get_value("User", staff.user, "enabled") not in (1, True, "1"):
			continue
		profile = resolve_crm_profile(frappe.get_roles(staff.user))
		if profile not in {"sales", "ctv_sale"}:
			continue
		result.append(
			{
				"staff": staff.name,
				"staffName": staff.full_name or staff.name,
				"team": team_id,
				"function": membership.function,
				"capacity": _staff_capacity(staff.name, at),
			}
		)
	return result


def _active_team_recipients(team_id: str, at=None) -> list[dict[str, Any]]:
	"""Return active Sale/CTV recipients without a Lead capacity gate."""
	return _team_recipient_pool(team_id, at)


def list_province_recipients(
	province: str,
	*,
	campus: str | None = None,
	at=None,
	include_leads: bool = False,
	allow_all_provinces: bool = False,
) -> list[dict[str, Any]]:
	"""List active Sale/CTV recipients eligible for a Lead's routing scope."""
	province = str(province or "").strip()
	if not province and not allow_all_provinces:
		return []

	targets = []
	for team in _active_teams_for_province(province or None, campus=campus):
		readiness = team_routing_readiness(
			team["name"],
			campus=team["campus"],
			expected_province=province,
			at=at,
		)
		if readiness["status"] != "ready" and not (
			include_leads and readiness.get("reasonCode") in {"no_recipients", "team_lead_missing"}
		):
			continue
		recipients = _active_team_recipients(team["name"], at) if readiness["status"] == "ready" else []
		if include_leads:
			leads = list_team_lead_recipients(team["name"])
			lead_ids = {row["staff"] for row in leads}
			recipients = [row for row in recipients if row["staff"] not in lead_ids] + leads
		for recipient in recipients:
			targets.append(
				{
					**recipient,
					"teamName": team["team_name"],
					"effectiveActive": recipient["capacity"]["active"],
				}
			)

	return sorted(
		targets,
		key=lambda row: (row["teamName"], row["staffName"], row["staff"]),
	)


def list_team_lead_recipients(team_id: str) -> list[dict[str, Any]]:
	"""Resolve designated leaders who are active members of the target Team."""
	team = frappe.db.get_value("CRM Team", team_id, ["team_lead_staff", "group"], as_dict=True)
	if not team:
		return []
	group_lead = frappe.db.get_value("CRM Team Group", team.get("group"), "group_lead_staff")
	member_ids = {row.staff for row in _active_memberships(team_id)}
	result = []
	seen = set()
	for staff_id, function in ((group_lead, "Lead Group"), (team.get("team_lead_staff"), "Lead Team")):
		if not staff_id or staff_id in seen or staff_id not in member_ids:
			continue
		staff = frappe.db.get_value(
			"CRM Staff", staff_id, ["name", "full_name", "user", "is_active"], as_dict=True
		)
		if not staff or not staff.is_active or not staff.user:
			continue
		if frappe.db.get_value("User", staff.user, "enabled") not in (1, True, "1"):
			continue
		seen.add(staff_id)
		result.append(
			{
				"staff": staff_id,
				"staffName": staff.full_name or staff_id,
				"team": team_id,
				"function": function,
				"capacity": _capacity_snapshot(0, active_lead_count(staff_id), configured=False),
			}
		)
	return result


def select_recipient_for_teams(
	teams: list[dict[str, Any]],
	*,
	scope_key: str,
	policy_version: str,
	strategy: str = "least_load",
	require_capacity: bool = True,
	load_overrides: dict[str, int] | None = None,
	at=None,
) -> dict[str, Any]:
	"""Select an active Sale/CTV by load, without enforcing Lead capacity.

	``require_capacity`` is retained for compatibility with existing policy callers.
	"""
	overrides = load_overrides or {}
	strategy = strategy if strategy in {"least_load", "round_robin"} else "least_load"
	candidates = []
	blocked_team_reasons = []
	for team in teams:
		pool = _team_recipient_pool(team["name"], at)
		if not pool:
			blocked_team_reasons.append(f"{team.get('team_name') or team['name']}: chưa có Sale/CTV")
			continue
		for recipient in pool:
			capacity = dict(recipient["capacity"])
			effective_active = int(capacity.get("active") or 0) + int(overrides.get(recipient["staff"], 0))
			candidates.append(
				{
					**recipient,
					"teamName": team.get("team_name") or team["name"],
					"effectiveActive": effective_active,
				}
			)
	if not candidates:
		if blocked_team_reasons:
			_raise_routing_error(
				"NO_ELIGIBLE_RECIPIENT",
				"Không có Team đủ điều kiện: " + "; ".join(blocked_team_reasons),
			)
		_raise_routing_error(
			"NO_ELIGIBLE_RECIPIENT", "Không có Sale/CTV đủ điều kiện trong phạm vi phân công."
		)

	candidates.sort(key=lambda row: (row["teamName"], row["staffName"], row["staff"]))
	if strategy == "round_robin":
		cursor = sum(int(row["effectiveActive"]) for row in candidates) % len(candidates)
		winner = candidates[cursor]
	else:
		winner = min(
			candidates,
			key=lambda row: (row["effectiveActive"], row["teamName"], row["staffName"], row["staff"]),
		)

	capacity = dict(winner["capacity"])
	capacity["active"] = winner["effectiveActive"]
	if capacity.get("limit"):
		capacity["remaining"] = max(0, int(capacity["limit"]) - winner["effectiveActive"])
	return {
		"team": winner["team"],
		"teamName": winner["teamName"],
		"ownerStaff": winner["staff"],
		"ownerName": winner["staffName"],
		"function": winner["function"],
		"capacity": capacity,
		"reason": (
			f"{scope_key} → {winner['teamName']} → {winner['staffName']} "
			f"({winner['function']}, tải {winner['effectiveActive']}"
			f"/{winner['capacity'].get('limit') or 'không giới hạn'}, {strategy})."
		),
		"policyVersion": policy_version,
		"tier": scope_key.split(":", 1)[0].lower(),
		"queue": scope_key,
		"scope": scope_key,
	}


def select_province_recipient(
	province: str,
	*,
	campus: str | None = None,
	team_id: str | None = None,
	load_overrides: dict[str, int] | None = None,
	at=None,
) -> dict[str, Any]:
	"""Select the least-loaded active Sale/CTV across Teams managing a province."""
	province = str(province or "").strip()
	if not province:
		_raise_routing_error("MISSING_PROVINCE", "Lead chưa có tỉnh để phân công.")
	teams = _active_teams_for_province(province, campus=campus, team_id=team_id)
	if not teams:
		_raise_routing_error(
			"TEAM_NOT_FOUND_FOR_PROVINCE", "Chưa có Team đang hoạt động quản lý tỉnh của Lead."
		)
	overrides = load_overrides or {}
	candidates = []
	blocked_team_reasons = []
	for team in teams:
		readiness = team_routing_readiness(
			team["name"],
			campus=team["campus"],
			expected_province=province,
			at=at,
		)
		if readiness["status"] != "ready":
			blocked_team_reasons.append(f"{team['team_name']}: {readiness['reason']}")
			continue
		for recipient in _team_recipient_pool(team["name"], at):
			capacity = recipient["capacity"]
			effective_active = capacity["active"] + int(overrides.get(recipient["staff"], 0))
			candidates.append(
				{**recipient, "teamName": team["team_name"], "effectiveActive": effective_active}
			)
	if not candidates:
		if blocked_team_reasons:
			_raise_routing_error(
				"NO_ELIGIBLE_RECIPIENT", "Không có Team đủ điều kiện: " + "; ".join(blocked_team_reasons)
			)
		_raise_routing_error("NO_ELIGIBLE_RECIPIENT", "Team chưa có Sale/CTV đủ điều kiện nhận Lead.")
	winner = min(
		candidates,
		key=lambda row: (row["effectiveActive"], row["teamName"], row["staffName"], row["staff"]),
	)
	capacity = dict(winner["capacity"])
	capacity["active"] = winner["effectiveActive"]
	if capacity["limit"]:
		capacity["remaining"] = max(0, capacity["limit"] - winner["effectiveActive"])
	return {
		"province": province,
		"team": winner["team"],
		"teamName": winner["teamName"],
		"ownerStaff": winner["staff"],
		"ownerName": winner["staffName"],
		"function": winner["function"],
		"capacity": capacity,
		"reason": (
			f"Tỉnh {province} → {winner['teamName']} → {winner['staffName']} "
			f"({winner['function']}, tải {winner['effectiveActive']}"
			f"/{winner['capacity']['limit'] or 'không giới hạn'})."
		),
		"policyVersion": "province-capacity-v1",
	}


def select_province_fallback_recipient(
	province: str,
	*,
	campus: str | None = None,
	team_id: str | None = None,
	at=None,
) -> dict[str, Any]:
	"""Fall back to a Team's active Trưởng nhóm when no Sale/CTV is eligible.

	Call this only after ``select_province_recipient`` fails with a
	recipient-side reason (a Team covers the province but has no live Sale/CTV
	right now). A routing failure must still name someone accountable instead
	of leaving the Lead ownerless, so the Team's own team lead stands in until
	a Sale/CTV becomes available.
	"""
	province = str(province or "").strip()
	if not province:
		_raise_routing_error("MISSING_PROVINCE", "Lead chưa có tỉnh để phân công.")
	teams = _active_teams_for_province(province, campus=campus, team_id=team_id)
	if not teams:
		_raise_routing_error(
			"TEAM_NOT_FOUND_FOR_PROVINCE", "Chưa có Team đang hoạt động quản lý tỉnh của Lead."
		)
	staff_ids = {
		row.name
		for row in frappe.get_all("CRM Staff", filters={"is_active": 1}, fields=["name"], limit_page_length=0)
	}
	candidates = []
	for team in teams:
		team_lead_staff = frappe.db.get_value("CRM Team", team["name"], "team_lead_staff")
		if not team_lead_staff or team_lead_staff not in staff_ids:
			continue
		staff_row = frappe.db.get_value(
			"CRM Staff", team_lead_staff, ["name", "full_name", "user"], as_dict=True
		)
		if not staff_row or not staff_row.user:
			continue
		if frappe.db.get_value("User", staff_row.user, "enabled") not in (1, True, "1"):
			continue
		candidates.append(
			{
				"staff": team_lead_staff,
				"staffName": staff_row.full_name or team_lead_staff,
				"team": team["name"],
				"teamName": team["team_name"],
				"function": "Lead Sale",
				"activeLoad": active_lead_count(team_lead_staff),
			}
		)
	if not candidates:
		_raise_routing_error(
			"NO_ELIGIBLE_RECIPIENT",
			"Không có Team nào tại tỉnh này có Trưởng nhóm đang hoạt động để nhận tạm Lead.",
		)
	winner = min(
		candidates,
		key=lambda row: (row["activeLoad"], row["teamName"], row["staffName"], row["staff"]),
	)
	return {
		"province": province,
		"team": winner["team"],
		"teamName": winner["teamName"],
		"ownerStaff": winner["staff"],
		"ownerName": winner["staffName"],
		"function": winner["function"],
		"capacity": {"active": winner["activeLoad"], "limit": None, "remaining": None},
		"reason": (
			f"Chưa có Sale/CTV khả dụng tại tỉnh {province}; tạm gán cho Trưởng nhóm "
			f"{winner['staffName']} ({winner['teamName']}) để đảm bảo có người xử lý."
		),
		"policyVersion": "province-capacity-v1",
		"fallback": True,
	}


def _raise_routing_error(code: str, message: str):
	exception = frappe.ValidationError(message)
	exception.code = code
	exception.error_code = code
	raise exception


def require_team_routing_ready(
	team_id: str,
	*,
	campus: str | None = None,
	expected_province: str | None = None,
) -> dict[str, Any]:
	"""Raise a stable ``TEAM_NOT_READY`` error when a batch cannot route."""
	readiness = team_routing_readiness(
		team_id,
		campus=campus,
		expected_province=expected_province,
	)
	if readiness["status"] != "ready":
		exception = frappe.ValidationError(readiness["reason"])
		exception.code = "TEAM_NOT_READY"
		exception.error_code = "TEAM_NOT_READY"
		frappe.throw(readiness["reason"], exc=exception)
	return readiness
