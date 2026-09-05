"""Read models for the assignment setup and overview workspace.

The workspace is deliberately a projection over the existing CRM DocTypes. It
does not introduce a second assignment table and it never treats a browser
profile value as an authorization source. Identity readiness is only exposed
to System Managers; operational managers receive the distribution rows that
belong to their server-derived scope.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import getdate, now_datetime, today

from crm.fcrm.role_policy import (
	PROFILE_LABELS,
	capabilities_for_roles,
	classify_role_set,
	resolve_crm_profile,
)

MAX_PAGE_SIZE = 100
LEVEL_ORDER = {
	"campus": 0,
	"province": 1,
	"cluster": 2,
	"zone": 3,
	"high_school": 4,
	"team": 5,
	"staff": 6,
}
FILTER_KEYS = {
	"campus",
	"province",
	"cluster",
	"zone",
	"school",
	"team",
	"staff",
	"status",
	"workload",
	"search",
}
STATUS_VALUES = {"all", "unassigned", "needs_review", "placeholder_zone", "capacity_warning", "healthy"}
WORKLOAD_VALUES = {"all", "unassigned", "near_capacity", "over_capacity"}
TOPOLOGY_ACTIONS = {"zone_team", "school_assignment"}
TOPOLOGY_RECEIPT_DOCTYPE = "CRM Student Command Receipt"
TEAM_MEMBER_FUNCTIONS = {
	"Sale",
	"Lead Sales",
	"Marketing",
	"Promoter",
	"Promoter-PR",
	"Admissions Director",
	"Team Leader",
	"Counseller",
	"CTV-Sale",
	"Marketing Operator",
	"Marketing Lead",
	"Admissions Operations",
}
MAX_BATCH_SCHOOLS = 100
REQUIRED_DOCTYPES = (
	"CRM Campus",
	"CRM Province",
	"CRM Cluster",
	"CRM Zone",
	"CRM Ward",
	"CRM High School",
	"CRM Team",
	"CRM Staff",
	"CRM Team Membership",
	"CRM Student Pool",
	"CRM Team Zone Assignment",
	"CRM High School Assignment",
	"CRM Student",
)


def _parse_object(value, label):
	if value in (None, "", {}):
		return {}
	if isinstance(value, str):
		try:
			value = frappe.parse_json(value)
		except (TypeError, ValueError):
			frappe.throw(_("{0} must be a JSON object.").format(label), frappe.ValidationError)
	if not isinstance(value, dict):
		frappe.throw(_("{0} must be an object.").format(label), frappe.ValidationError)
	return value


def _limit(value):
	try:
		value = int(value or 50)
	except (TypeError, ValueError):
		frappe.throw(_("limit must be an integer."), frappe.ValidationError)
	if not 1 <= value <= MAX_PAGE_SIZE:
		frappe.throw(_("limit must be between 1 and {0}.").format(MAX_PAGE_SIZE), frappe.ValidationError)
	return value


def _offset(value):
	if value in (None, ""):
		return 0
	try:
		value = int(value)
	except (TypeError, ValueError):
		frappe.throw(_("cursor is invalid."), frappe.ValidationError)
	if value < 0:
		frappe.throw(_("cursor is invalid."), frappe.ValidationError)
	return value


def _normalize_filters(filters):
	filters = _parse_object(filters, "filters")
	unknown = set(filters) - FILTER_KEYS
	if unknown:
		frappe.throw(_("Unsupported assignment workspace filter."), frappe.ValidationError)

	normalized = {}
	for key, value in filters.items():
		if value in (None, "", "all") and key not in {"status", "workload"}:
			continue
		if key in {"status", "workload"}:
			allowed = STATUS_VALUES if key == "status" else WORKLOAD_VALUES
			if value not in allowed:
				frappe.throw(_("Unsupported assignment workspace filter."), frappe.ValidationError)
			if value != "all":
				normalized[key] = value
			continue
		if not isinstance(value, str) or len(value) > 140:
			frappe.throw(_("An assignment workspace filter is invalid."), frappe.ValidationError)
		normalized[key] = value.strip()
	return normalized


def _doctype_exists(doctype):
	try:
		return bool(frappe.db.exists("DocType", doctype))
	except Exception:
		return False


def _safe_get_all(doctype, fields, filters=None, order_by=None):
	"""Read an optional projection source without breaking partial migrations."""
	if not _doctype_exists(doctype):
		return []
	try:
		return frappe.get_all(
			doctype,
			filters=filters or {},
			fields=fields,
			order_by=order_by,
			limit_page_length=0,
		)
	except (frappe.DoesNotExistError, frappe.ValidationError):
		return []


def _roles_for_user(user):
	try:
		return sorted(set(frappe.get_roles(user)))
	except Exception:
		return []


def _actor_context():
	actor = getattr(frappe.session, "user", None)
	if not actor or actor == "Guest":
		frappe.throw(_("Authentication is required."), frappe.AuthenticationError)

	administrator = actor == "Administrator"
	roles = _roles_for_user(actor)
	role_state = classify_role_set(roles, administrator=administrator)
	if administrator or role_state == "system_manager":
		profile = "system_manager"
	else:
		profile = resolve_crm_profile(roles)
	capabilities = capabilities_for_roles(roles, administrator=administrator)
	if not profile or not capabilities.intersection(
		{"system.configure", "team.oversee", "admissions.oversee", "student.routing.read"}
	):
		frappe.throw(_("You are not permitted to access assignment setup."), frappe.PermissionError)

	staff = None
	team_names = set()
	campus_names = set()
	if profile != "system_manager":
		staff = frappe.db.get_value(
			"CRM Staff", {"user": actor, "is_active": 1}, ["name", "campus"], as_dict=True
		)
		if not staff:
			frappe.throw(_("An active CRM Staff record is required."), frappe.PermissionError)
		membership_rows = _safe_get_all(
			"CRM Team Membership",
			["parent as staff", "team", "function", "is_primary", "effective_from", "effective_until"],
			{"parent": staff.name, "parenttype": "CRM Staff"},
		)
		team_names = {row.team for row in membership_rows if row.get("team") and _date_active(row)}
		campus_names = {staff.campus} if staff.campus else set()
		for team in _safe_get_all("CRM Team", ["name", "campus"], {"name": ["in", list(team_names)]}):
			if team.get("campus"):
				campus_names.add(team.campus)

	return {
		"actor": actor,
		"roles": roles,
		"administrator": administrator,
		"profile": profile,
		"role_state": role_state,
		"capabilities": sorted(capabilities),
		"staff": staff.name if staff else None,
		"teams": sorted(team_names),
		"campuses": sorted(campus_names),
		"is_system_manager": profile == "system_manager",
	}


def _require_setup_access():
	context = _actor_context()
	if "system.configure" not in context["capabilities"]:
		frappe.throw(_("Only System Managers may inspect account readiness."), frappe.PermissionError)
	return context


def _date_active(row, today=None):
	today = today or getdate()
	start = row.get("effective_from")
	end = row.get("effective_until")
	return (not start or getdate(start) <= today) and (not end or getdate(end) >= today)


def _label(row, name_field, fallback=None):
	return row.get(name_field) or row.get("name") or fallback or "—"


def _profile_record(role):
	if not role or not _doctype_exists("CRM Permission Profile"):
		return None
	try:
		return frappe.db.get_value(
			"CRM Permission Profile",
			{"role": role},
			["name", "role", "row_scope", "is_system_managed", "delete_requires_ownership"],
			as_dict=True,
		)
	except (frappe.DoesNotExistError, frappe.ValidationError):
		return None


def _identity_row(user, staff_by_user, memberships_by_staff, team_labels=None):
	team_labels = team_labels or {}
	roles = _roles_for_user(user.name)
	administrator = user.name == "Administrator"
	role_state = classify_role_set(roles, administrator=administrator)
	profile = None if administrator or role_state == "system_manager" else resolve_crm_profile(roles)
	profile_role = "System Manager" if role_state == "system_manager" else PROFILE_LABELS.get(profile)
	profile_record = _profile_record(profile_role)
	staff = staff_by_user.get(user.name)
	memberships = memberships_by_staff.get(staff.name, []) if staff else []
	issues = []

	if role_state in {"unmapped", "mixed_or_unmapped", "legacy_migration_required"}:
		issues.append(
			{
				"code": "role_not_supported",
				"label": _("Role cần rà soát"),
				"next_action": "assign_canonical_role",
			}
		)
	if profile_role and not profile_record:
		issues.append(
			{
				"code": "permission_profile_missing",
				"label": _("Thiếu CRM Permission Profile theo Role"),
				"next_action": "open_role_settings",
			}
		)
	if not administrator and role_state not in {
		"system_manager",
		"unmapped",
		"mixed_or_unmapped",
		"legacy_migration_required",
	}:
		if not staff:
			issues.append(
				{"code": "crm_staff_missing", "label": _("Chưa có profile Staff"), "next_action": "create_staff"}
			)
		elif not staff.is_active:
			issues.append(
				{
					"code": "crm_staff_inactive",
					"label": _("CRM Staff đã tắt"),
					"next_action": "activate_staff",
				}
			)
		if not memberships:
			issues.append(
				{
					"code": "team_membership_missing",
					"label": _("Chưa có Team Membership"),
					"next_action": "add_team_membership",
				}
			)
		if not staff or not staff.campus:
			issues.append(
				{"code": "campus_missing", "label": _("Chưa có Campus"), "next_action": "set_staff_campus"}
			)

	status = "healthy" if not issues else "needs_review"
	return {
		"id": user.name,
		"user": user.name,
		"email": user.email,
		"full_name": user.full_name or user.name,
		"enabled": bool(user.enabled),
		"roles": roles,
		"role_state": role_state,
		"crm_profile": profile,
		"crm_profile_label": PROFILE_LABELS.get(profile) if profile else profile_role,
		"permission_profile": {
			"role": profile_role,
			"name": profile_record.name if profile_record else None,
			"exists": bool(profile_record),
			"row_scope": profile_record.row_scope if profile_record else None,
			"is_system_managed": bool(profile_record.is_system_managed) if profile_record else False,
		},
		"crm_staff": {
			"name": staff.name if staff else None,
			"full_name": staff.full_name if staff else None,
			"is_active": bool(staff.is_active) if staff else False,
			"campus": staff.campus if staff else None,
			"teams": sorted(team_labels.get(row.team, row.team) for row in memberships if row.get("team")),
		},
		"status": status,
		"issues": issues,
	}


@frappe.whitelist()
def get_setup_readiness():
	"""Return production account/profile/staff setup gaps for system managers."""
	_require_setup_access()
	users = _safe_get_all(
		"User",
		["name", "email", "full_name", "enabled"],
		{"name": ["not in", ["Guest"]]},
		"full_name asc, name asc",
	)
	staff_rows = _safe_get_all(
		"CRM Staff",
		["name", "full_name", "user", "is_active", "campus"],
		order_by="full_name asc, name asc",
	)
	membership_rows = _safe_get_all(
		"CRM Team Membership",
		["parent as staff", "team", "function", "is_primary", "effective_from", "effective_until"],
	)
	team_labels = {
		row.name: _label(row, "team_name") for row in _safe_get_all("CRM Team", ["name", "team_name"])
	}
	staff_by_user = {row.user: row for row in staff_rows if row.get("user")}
	memberships_by_staff = defaultdict(list)
	for row in membership_rows:
		if row.get("staff") and _date_active(row):
			memberships_by_staff[row.staff].append(row)
	rows = [_identity_row(user, staff_by_user, memberships_by_staff, team_labels) for user in users]

	counts = defaultdict(int)
	for row in rows:
		counts[row["status"]] += 1
		for issue in row["issues"]:
			counts[issue["code"]] += 1

	return {
		"contractStatus": "ready" if _doctype_exists("CRM Permission Profile") else "partial",
		"schemaVersion": "assignment-readiness-v1",
		"as_of": str(now_datetime()),
		"summary": {
			"accounts": len(rows),
			"ready_accounts": counts["healthy"],
			"needs_review_accounts": counts["needs_review"],
			"role_not_supported": counts["role_not_supported"],
			"permission_profile_missing": counts["permission_profile_missing"],
			"crm_staff_missing": counts["crm_staff_missing"],
			"team_membership_missing": counts["team_membership_missing"],
			"campus_missing": counts["campus_missing"],
		},
		"rows": rows,
		"warnings": [
			{
				"code": "permission_profile_catalog_missing",
				"message": _("CRM Permission Profile chưa được migrate."),
			}
		]
		if not _doctype_exists("CRM Permission Profile")
		else [],
		"capabilities": {
			"can_edit_identity": True,
			"can_edit_distribution": True,
			"permission_profile_is_role_level": True,
		},
	}


def _grouped_students():
	if not _doctype_exists("CRM Student"):
		return []
	try:
		return frappe.get_list(
			"CRM Student",
			filters={"lifecycle_stage": ["not in", ["Lost"]]},
			fields=[
				"branch",
				"high_school",
				"owning_team",
				"owner_staff",
				"owning_pool",
				"count(name) as count",
			],
			group_by="branch, high_school, owning_team, owner_staff, owning_pool",
			limit_page_length=0,
		)
	except (frappe.DoesNotExistError, frappe.ValidationError):
		return []


def _capacity_by_staff():
	today = getdate()
	rows = _safe_get_all(
		"CRM Staff Capacity Period",
		["staff", "team", "campus", "period_start", "period_end", "max_active_students", "approved"],
	)
	capacity = {}
	for row in rows:
		if (
			not row.get("staff")
			or not row.get("approved")
			or not _date_active(
				{"effective_from": row.get("period_start"), "effective_until": row.get("period_end")}, today
			)
		):
			continue
		if row.get("max_active_students") is None:
			continue
		previous = capacity.get(row.staff)
		if not previous or getdate(row.period_start) > getdate(previous.period_start):
			capacity[row.staff] = row
	return capacity


def _workload_status(active, capacity):
	if capacity is None:
		return "unconfigured"
	maximum = int(capacity.get("max_active_students") or 0)
	if maximum <= 0:
		return "unconfigured"
	if active >= maximum:
		return "over_capacity"
	if active >= maximum * 0.85:
		return "near_capacity"
	return "healthy"


def _overview_sources(context):
	campuses = _safe_get_all(
		"CRM Campus", ["name", "campus_name", "province", "city"], "", "campus_name asc, name asc"
	)
	provinces = _safe_get_all(
		"CRM Province", ["name", "province_name"], order_by="province_name asc, name asc"
	)
	clusters = _safe_get_all(
		"CRM Cluster",
		["name", "cluster_name", "province", "is_placeholder", "is_active"],
		order_by="cluster_name asc, name asc",
	)
	zones = _safe_get_all(
		"CRM Zone",
		["name", "zone_name", "zone_code", "cluster", "is_placeholder", "current_team", "assignment_status"],
		order_by="zone_name asc, name asc",
	)
	wards = _safe_get_all(
		"CRM Ward", ["name", "ward_name", "zone", "province"], order_by="ward_name asc, name asc"
	)
	schools = _safe_get_all(
		"CRM High School",
		["name", "school_name", "province", "ward", "is_active"],
		order_by="school_name asc, name asc",
	)
	teams = _safe_get_all(
		"CRM Team",
		["name", "team_name", "team_type", "campus", "is_active"],
		order_by="team_name asc, name asc",
	)
	staff = _safe_get_all(
		"CRM Staff", ["name", "full_name", "user", "is_active", "campus"], order_by="full_name asc, name asc"
	)
	pools = _safe_get_all(
		"CRM Student Pool",
		["name", "pool_name", "team", "campus", "is_active"],
		order_by="pool_name asc, name asc",
	)
	zone_assignments = _safe_get_all(
		"CRM Team Zone Assignment",
		["name", "team", "zone", "status", "effective_from", "effective_until", "revision"],
		{"status": "Active"},
	)
	zone_assignments = [row for row in zone_assignments if _date_active(row)]
	school_assignments = _safe_get_all(
		"CRM High School Assignment",
		["name", "staff", "team", "high_school", "zone", "status", "needs_review", "assigned_on", "modified"],
		{"status": "Active"},
	)
	memberships = _safe_get_all(
		"CRM Team Membership",
		[
			"parent as staff",
			"team",
			"function",
			"is_primary",
			"is_team_lead",
			"effective_from",
			"effective_until",
		],
	)
	memberships = [row for row in memberships if _date_active(row)]
	policies = _safe_get_all(
		"CRM Student Routing Policy",
		[
			"name",
			"campus",
			"student_pool",
			"status",
			"strategy",
			"scoring_weights",
			"effective_from",
			"effective_until",
		],
		{"status": "active"},
	)

	allowed_teams = set(context["teams"])
	if context["is_system_manager"] or "admissions.oversee" in context["capabilities"]:
		allowed_teams = {row.name for row in teams}
	else:
		allowed_teams &= {row.name for row in teams}
	team_map = {row.name: row for row in teams if row.name in allowed_teams}
	allowed_campuses = {row.campus for row in team_map.values() if row.get("campus")}
	allowed_campuses.update(context["campuses"])
	if context["is_system_manager"] or "admissions.oversee" in context["capabilities"]:
		allowed_campuses = {row.name for row in campuses}

	active_zone_map = {row.zone: row for row in zone_assignments if row.get("team") in allowed_teams}
	if context["is_system_manager"] or "admissions.oversee" in context["capabilities"]:
		active_zone_map = {row.zone: row for row in zone_assignments}
	allowed_zones = set(active_zone_map)
	allowed_zones.update(row.name for row in zones if row.get("current_team") in allowed_teams)
	if context["is_system_manager"] or "admissions.oversee" in context["capabilities"]:
		allowed_zones = {row.name for row in zones}
	allowed_schools = {
		row.name
		for row in schools
		if row.get("ward") in {ward.name for ward in wards if ward.get("zone") in allowed_zones}
		or any(
			assignment.high_school == row.name and assignment.team in allowed_teams
			for assignment in school_assignments
		)
	}
	if context["is_system_manager"] or "admissions.oversee" in context["capabilities"]:
		allowed_schools = {row.name for row in schools}
	unrestricted = context["is_system_manager"] or "admissions.oversee" in context["capabilities"]
	visible_schools = [row for row in schools if unrestricted or row.name in allowed_schools]
	visible_zones = [row for row in zones if unrestricted or row.name in allowed_zones]
	visible_clusters = [
		row
		for row in clusters
		if unrestricted or row.name in {zone.cluster for zone in visible_zones if zone.get("cluster")}
	]
	visible_provinces = [
		row
		for row in provinces
		if unrestricted
		or row.name in {cluster.province for cluster in visible_clusters if cluster.get("province")}
		or row.name in {school.province for school in visible_schools if school.get("province")}
	]
	visible_wards = [
		row for row in wards if unrestricted or row.zone in {zone.name for zone in visible_zones}
	]

	return {
		"campuses": [row for row in campuses if unrestricted or row.name in allowed_campuses],
		"provinces": visible_provinces,
		"clusters": visible_clusters,
		"zones": visible_zones,
		"wards": visible_wards,
		"schools": visible_schools,
		"teams": list(team_map.values()),
		"staff": [
			row for row in staff if any(m.staff == row.name and m.team in allowed_teams for m in memberships)
		],
		"pools": [row for row in pools if row.team in allowed_teams],
		"zone_assignments": list(active_zone_map.values()),
		"school_assignments": [row for row in school_assignments if row.team in allowed_teams],
		"memberships": [row for row in memberships if row.team in allowed_teams],
		"policies": policies
		if context["is_system_manager"] or "admissions.oversee" in context["capabilities"]
		else [
			row
			for row in policies
			if any(pool.name == row.student_pool and pool.team in allowed_teams for pool in pools)
		],
	}


def _source_maps(sources):
	return {
		key: {row.name: row for row in rows}
		for key, rows in sources.items()
		if isinstance(rows, list) and rows and row_has_name(rows[0])
	}


def row_has_name(row):
	return bool(row.get("name"))


def _school_assignment_revision(assignments):
	"""Return a stable optimistic-lock token for the active school mapping."""
	if not assignments:
		return "0"
	value = "|".join(
		f"{row.get('name')}:{row.get('staff')}:{row.get('team')}:{row.get('modified')}"
		for row in sorted(assignments, key=lambda item: item.get("name") or "")
	)
	return hashlib.sha256(value.encode()).hexdigest()[:24]


def _can_edit_topology(context):
	return "system.configure" in context["capabilities"] or "admissions.oversee" in context["capabilities"]


def _topology_options(sources, context):
	if not _can_edit_topology(context):
		return {"teams": [], "staff": []}

	team_ids = {
		membership.team
		for membership in sources["memberships"]
		if membership.get("team") and membership.get("staff")
	}
	active_teams = [team for team in sources["teams"] if team.get("is_active") and team.name in team_ids]
	active_team_ids = {team.name for team in active_teams}
	staff_team_ids = defaultdict(set)
	for membership in sources["memberships"]:
		if (
			membership.get("staff") in {row.name for row in sources["staff"]}
			and membership.team in active_team_ids
		):
			staff_team_ids[membership.staff].add(membership.team)

	return {
		"teams": [
			{
				"value": team.name,
				"label": _label(team, "team_name"),
				"campus": team.campus,
			}
			for team in active_teams
		],
		"staff": [
			{
				"value": staff.name,
				"label": _label(staff, "full_name"),
				"campus": staff.campus,
				"team_ids": sorted(staff_team_ids.get(staff.name, set())),
			}
			for staff in sources["staff"]
			if staff.get("is_active") and staff_team_ids.get(staff.name)
		],
	}


def _parse_string_list(value, label, *, maximum=MAX_BATCH_SCHOOLS):
	if isinstance(value, str):
		try:
			value = frappe.parse_json(value)
		except (TypeError, ValueError):
			frappe.throw(_("{0} must be a JSON array.").format(label), frappe.ValidationError)
	if not isinstance(value, list):
		frappe.throw(_("{0} must be an array.").format(label), frappe.ValidationError)
	items = []
	for item in value:
		if not isinstance(item, str) or not item.strip():
			frappe.throw(_("{0} contains an invalid item.").format(label), frappe.ValidationError)
		item = item.strip()
		if item not in items:
			items.append(item)
	if not items or len(items) > maximum:
		frappe.throw(
			_("{0} must contain between 1 and {1} items.").format(label, maximum), frappe.ValidationError
		)
	return items


def _context_revision(staff_id):
	if not staff_id:
		return "0"
	staff = frappe.db.get_value(
		"CRM Staff",
		staff_id,
		["modified", "user", "full_name", "department", "campus", "is_active"],
		as_dict=True,
	)
	if not staff:
		return "0"
	memberships = frappe.get_all(
		"CRM Team Membership",
		filters={"parent": staff_id, "parenttype": "CRM Staff"},
		fields=["name", "team", "function", "term", "effective_from", "effective_until", "is_primary"],
		order_by="name asc",
	)
	payload = {"staff": staff, "memberships": memberships}
	return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:24]


def _staff_context_options():
	return {
		"campuses": [
			{"value": row.name, "label": _label(row, "campus_name")}
			for row in _safe_get_all(
				"CRM Campus", ["name", "campus_name"], order_by="campus_name asc, name asc"
			)
		],
		"departments": [
			{"value": row.name, "label": _label(row, "department_name"), "campus": row.campus}
			for row in _safe_get_all(
				"CRM Department",
				["name", "department_name", "campus"],
				order_by="department_name asc, name asc",
			)
		],
		"teams": [
			{"value": row.name, "label": _label(row, "team_name"), "campus": row.campus}
			for row in _safe_get_all(
				"CRM Team",
				["name", "team_name", "campus", "is_active"],
				{"is_active": 1},
				"team_name asc, name asc",
			)
		],
		"functions": sorted(TEAM_MEMBER_FUNCTIONS),
	}


def _staff_context_payload(staff_id, user=None):
	staff = (
		frappe.db.get_value(
			"CRM Staff",
			staff_id,
			["name", "full_name", "user", "department", "campus", "is_active", "modified"],
			as_dict=True,
		)
		if staff_id
		else None
	)
	if staff and user and staff.user != user:
		_command_error("STAFF_USER_MISMATCH", "CRM Staff không thuộc tài khoản đang chọn.")
	if user and not frappe.db.exists("User", user):
		_command_error("TARGET_NOT_FOUND", "User không tồn tại.")
	memberships = []
	if staff:
		memberships = _safe_get_all(
			"CRM Team Membership",
			[
				"name",
				"parent as staff",
				"team",
				"function",
				"term",
				"effective_from",
				"effective_until",
				"is_primary",
			],
			{"parent": staff.name, "parenttype": "CRM Staff"},
			"name asc",
		)
		user = staff.user
	return {
		"staff": dict(staff) if staff else None,
		"user": user,
		"revision": _context_revision(staff.name if staff else None),
		"memberships": memberships,
		"options": _staff_context_options(),
	}


@frappe.whitelist()
def get_staff_context(staff_id=None, user=None):
	"""Return editable CRM Staff + Team Membership context for setup managers."""
	_require_setup_access()
	if not staff_id and not user:
		frappe.throw(_("staff_id or user is required."), frappe.ValidationError)
	if staff_id and not frappe.db.exists("CRM Staff", staff_id):
		_command_error("TARGET_NOT_FOUND", "CRM Staff không tồn tại.")
	return _staff_context_payload(staff_id, user)


def _active_students_summary(student_rows):
	by = {
		key: defaultdict(int)
		for key in ("branch", "high_school", "owning_team", "owner_staff", "owning_pool")
	}
	total = 0
	for row in student_rows:
		count = int(row.get("count") or 0)
		total += count
		for key in by:
			if row.get(key):
				by[key][row[key]] += count
	return by, total


def _row_status(
	*, assigned=False, needs_review=False, placeholder=False, capacity_warning=False, missing_pool=False
):
	if missing_pool or not assigned:
		return "unassigned"
	if needs_review:
		return "needs_review"
	if placeholder:
		return "placeholder_zone"
	if capacity_warning:
		return "capacity_warning"
	return "healthy"


def _overview_rows(sources, context):
	province_map = {row.name: row for row in sources["provinces"]}
	cluster_map = {row.name: row for row in sources["clusters"]}
	zone_map = {row.name: row for row in sources["zones"]}
	ward_map = {row.name: row for row in sources["wards"]}
	team_map = {row.name: row for row in sources["teams"]}
	staff_map = {row.name: row for row in sources["staff"]}
	pool_by_team = defaultdict(list)
	for pool in sources["pools"]:
		if pool.get("is_active"):
			pool_by_team[pool.team].append(pool)

	assignment_by_school = defaultdict(list)
	for assignment in sources["school_assignments"]:
		assignment_by_school[assignment.high_school].append(assignment)
	team_zone_by_zone = {row.zone: row for row in sources["zone_assignments"]}
	team_zone_by_team = defaultdict(list)
	for assignment in sources["zone_assignments"]:
		team_zone_by_team[assignment.team].append(assignment)
	members_by_team = defaultdict(list)
	for membership in sources["memberships"]:
		if membership.get("team") in team_map:
			members_by_team[membership.team].append(membership)

	student_rows = _grouped_students()
	student_by, active_students = _active_students_summary(student_rows)
	capacity = _capacity_by_staff()
	active_staff_count = defaultdict(int)
	for row in sources["staff"]:
		active_staff_count[row.name] = student_by["owner_staff"].get(row.name, 0)

	# Keep the hierarchy readable without making the frontend infer scope from
	# all descendant rows. These aggregates are read-only projections; the
	# source of truth remains Ward -> Zone and High School -> Ward.
	ward_count_by_zone = defaultdict(int)
	school_count_by_zone = defaultdict(int)
	active_students_by_zone = defaultdict(int)
	for ward in sources["wards"]:
		if ward.get("zone"):
			ward_count_by_zone[ward.zone] += 1
	for school in sources["schools"]:
		ward = ward_map.get(school.get("ward"))
		if ward and ward.get("zone"):
			school_count_by_zone[ward.zone] += 1
			active_students_by_zone[ward.zone] += student_by["high_school"].get(school.name, 0)

	def campus_for_team(team_name):
		team = team_map.get(team_name)
		return team.campus if team else None

	def geography(school):
		ward = ward_map.get(school.get("ward"))
		zone = zone_map.get(ward.zone) if ward else None
		cluster = cluster_map.get(zone.cluster) if zone else None
		province_id = school.get("province") or (cluster.province if cluster else None)
		return ward, zone, cluster, province_id

	def row_base(row_id, level, label, parent_id, values, status="healthy", **extra):
		return {
			"id": row_id,
			"level": level,
			"label": label,
			"parent_id": parent_id,
			"path": extra.pop("path", row_id),
			"has_children": False,
			"status": status,
			"filter_values": values,
			"active_students": int(extra.pop("active_students", 0) or 0),
			"capacity": extra.pop("capacity", None),
			"load_percent": extra.pop("load_percent", None),
			**extra,
		}

	rows = []
	root_campus_ids = []
	for campus in sources["campuses"]:
		row_id = f"campus:{campus.name}"
		root_campus_ids.append(row_id)
		rows.append(
			row_base(
				row_id,
				"campus",
				_label(campus, "campus_name"),
				None,
				{"campus": {campus.name}},
				campus_name=_label(campus, "campus_name"),
				province_name=_label(province_map.get(campus.province), "province_name")
				if campus.get("province")
				else None,
				province=campus.province,
				campus_id=campus.name,
				active_students=student_by["branch"].get(campus.name, 0),
				path=row_id,
			)
		)

	# Put a province beneath its campus when the campus declares it. Schools
	# without a campus still remain visible under the first matching campus or
	# under an explicit unresolved branch in the school row.
	province_parent = {}
	for province in sources["provinces"]:
		campus = next((c for c in sources["campuses"] if c.get("province") == province.name), None)
		if not campus and sources["campuses"]:
			campus = next((c for c in sources["campuses"] if c.get("province") is None), None)
		if not campus:
			continue
		province_clusters = [row for row in sources["clusters"] if row.get("province") == province.name]
		province_zones = [
			row
			for row in sources["zones"]
			if row.get("cluster") in {cluster.name for cluster in province_clusters}
		]
		row_id = f"province:{province.name}"
		province_parent[province.name] = row_id
		rows.append(
			row_base(
				row_id,
				"province",
				_label(province, "province_name"),
				f"campus:{campus.name}",
				{"campus": {campus.name}, "province": {province.name}},
				campus_name=_label(campus, "campus_name"),
				province_id=province.name,
				cluster_count=len(province_clusters),
				zone_count=len(province_zones),
				ward_count=sum(ward_count_by_zone.get(zone.name, 0) for zone in province_zones),
				school_count=sum(school_count_by_zone.get(zone.name, 0) for zone in province_zones),
				active_students=sum(active_students_by_zone.get(zone.name, 0) for zone in province_zones),
				path=f"campus:{campus.name}/{row_id}",
			)
		)

	cluster_parent = {}
	for cluster in sources["clusters"]:
		parent = province_parent.get(cluster.province)
		if not parent:
			continue
		row_id = f"cluster:{cluster.name}"
		cluster_parent[cluster.name] = row_id
		cluster_zones = [row for row in sources["zones"] if row.get("cluster") == cluster.name]
		cluster_team_ids = {
			assignment.team
			for assignment in sources["zone_assignments"]
			if assignment.get("zone") in {zone.name for zone in cluster_zones}
		}
		rows.append(
			row_base(
				row_id,
				"cluster",
				_label(cluster, "cluster_name"),
				parent,
				{"province": {cluster.province}, "cluster": {cluster.name}},
				status="needs_review" if cluster.get("is_placeholder") else "healthy",
				province_name=_label(province_map.get(cluster.province), "province_name"),
				cluster_id=cluster.name,
				zone_count=len(cluster_zones),
				ward_count=sum(ward_count_by_zone.get(zone.name, 0) for zone in cluster_zones),
				school_count=sum(school_count_by_zone.get(zone.name, 0) for zone in cluster_zones),
				active_students=sum(active_students_by_zone.get(zone.name, 0) for zone in cluster_zones),
				team_names=sorted(
					_label(team_map.get(team_id), "team_name")
					for team_id in cluster_team_ids
					if team_map.get(team_id)
				),
				path=f"{parent}/{row_id}",
			)
		)

	zone_parent = {}
	for zone in sources["zones"]:
		parent = cluster_parent.get(zone.cluster)
		if not parent:
			continue
		row_id = f"zone:{zone.name}"
		zone_parent[zone.name] = row_id
		zone_assignment = team_zone_by_zone.get(zone.name)
		zone_team = team_map.get(zone_assignment.team) if zone_assignment else team_map.get(zone.current_team)
		zone_status = _row_status(
			assigned=bool(zone_team),
			placeholder=bool(zone.get("is_placeholder")),
		)
		zone_pool_list = pool_by_team.get(zone_team.name, []) if zone_team else []
		zone_members = members_by_team.get(zone_team.name, []) if zone_team else []
		rows.append(
			row_base(
				row_id,
				"zone",
				_label(zone, "zone_name"),
				parent,
				{
					"province": {cluster_map.get(zone.cluster).province}
					if cluster_map.get(zone.cluster)
					else set(),
					"cluster": {zone.cluster},
					"zone": {zone.name},
					"team": {zone_team.name} if zone_team else set(),
				},
				status=zone_status,
				province_name=_label(
					province_map.get(cluster_map.get(zone.cluster).province), "province_name"
				)
				if cluster_map.get(zone.cluster)
				else None,
				cluster_name=_label(cluster_map.get(zone.cluster), "cluster_name")
				if cluster_map.get(zone.cluster)
				else None,
				zone_name=_label(zone, "zone_name"),
				zone_id=zone.name,
				team_id=zone_team.name if zone_team else None,
				team_name=_label(zone_team, "team_name") if zone_team else None,
				ward_count=ward_count_by_zone.get(zone.name, 0),
				school_count=school_count_by_zone.get(zone.name, 0),
				active_students=active_students_by_zone.get(zone.name, 0),
				member_count=len(zone_members),
				member_names=sorted(
					_label(staff_map.get(member.staff), "full_name")
					for member in zone_members
					if staff_map.get(member.staff)
				),
				pool_names=[_label(pool, "pool_name") for pool in zone_pool_list],
				effective_from=zone_assignment.effective_from if zone_assignment else None,
				revision=zone_assignment.revision if zone_assignment else None,
				path=f"{parent}/{row_id}",
			)
		)

	for school in sources["schools"]:
		ward, zone, cluster, province_id = geography(school)
		parent = zone_parent.get(zone.name) if zone else None
		if not parent:
			campus = next((c for c in sources["campuses"] if c.get("province") == province_id), None)
			parent = f"campus:{campus.name}" if campus else None
		assignments = assignment_by_school.get(school.name, [])
		team_ids = {assignment.team for assignment in assignments if assignment.team in team_map}
		staff_ids = {assignment.staff for assignment in assignments if assignment.staff in staff_map}
		pools_for_school = {pool.name for team in team_ids for pool in pool_by_team.get(team, [])}
		capacity_warning = any(
			_workload_status(active_staff_count.get(staff_id, 0), capacity.get(staff_id))
			in {"near_capacity", "over_capacity"}
			for staff_id in staff_ids
		)
		status = _row_status(
			assigned=bool(assignments),
			needs_review=any(bool(assignment.needs_review) for assignment in assignments),
			placeholder=bool(zone and zone.get("is_placeholder")),
			capacity_warning=capacity_warning,
			missing_pool=bool(assignments) and not pools_for_school,
		)
		parent_values = {
			"campus": {campus_for_team(team_id) for team_id in team_ids if campus_for_team(team_id)} or set(),
			"province": {province_id} if province_id else set(),
			"cluster": {cluster.name} if cluster else set(),
			"zone": {zone.name} if zone else set(),
			"school": {school.name},
			"team": team_ids,
			"staff": staff_ids,
		}
		campus = next((c for c in sources["campuses"] if c.get("province") == province_id), None)
		campus_name = _label(campus, "campus_name") if campus else None
		if not campus_name:
			campus_name = _label(team_map.get(next(iter(team_ids), None)), "campus") if team_ids else None
		if campus_name and not parent_values["campus"]:
			campus = next((c for c in sources["campuses"] if _label(c, "campus_name") == campus_name), None)
			if campus:
				parent_values["campus"] = {campus.name}
		rows.append(
			row_base(
				f"school:{school.name}",
				"high_school",
				_label(school, "school_name"),
				parent,
				parent_values,
				status=status,
				high_school_id=school.name,
				campus_name=campus_name,
				province_name=_label(province_map.get(province_id), "province_name") if province_id else None,
				cluster_name=_label(cluster, "cluster_name") if cluster else None,
				zone_name=_label(zone, "zone_name") if zone else None,
				ward_id=ward.name if ward else None,
				ward_name=_label(ward, "ward_name") if ward else None,
				zone_id=zone.name if zone else None,
				province_id=province_id,
				team_ids=sorted(team_ids),
				team_names=sorted(_label(team_map[team_id], "team_name") for team_id in team_ids),
				staff_ids=sorted(staff_ids),
				staff_names=sorted(_label(staff_map[staff_id], "full_name") for staff_id in staff_ids),
				pool_ids=sorted(pools_for_school),
				pool_names=sorted(
					_label(next(pool for pool in sources["pools"] if pool.name == pool_id), "pool_name")
					for pool_id in pools_for_school
				),
				revision=_school_assignment_revision(assignments),
				active_students=student_by["high_school"].get(school.name, 0),
				needs_review=any(bool(assignment.needs_review) for assignment in assignments),
				path=f"{parent}/school:{school.name}" if parent else f"school:{school.name}",
			)
		)

	# Teams are deliberately shown below their owned Zone, with an additional
	# campus fallback for teams that have no active Zone mapping yet.
	for team in sources["teams"]:
		team_zones = [
			assignment.zone
			for assignment in team_zone_by_team.get(team.name, [])
			if assignment.zone in zone_parent
		]
		parents = team_zones or [None]
		for zone_name in parents:
			parent = (
				zone_parent.get(zone_name) if zone_name else f"campus:{team.campus}" if team.campus else None
			)
			row_id = f"team:{team.name}:{zone_name or 'campus'}"
			pool_list = pool_by_team.get(team.name, [])
			status = _row_status(assigned=bool(team.is_active and pool_list), missing_pool=not pool_list)
			rows.append(
				row_base(
					row_id,
					"team",
					_label(team, "team_name"),
					parent,
					{
						"campus": {team.campus} if team.campus else set(),
						"team": {team.name},
						"zone": {zone_name} if zone_name else set(),
					},
					status=status,
					campus_name=_label(
						next((c for c in sources["campuses"] if c.name == team.campus), None), "campus_name"
					)
					if team.get("campus")
					else None,
					zone_name=_label(zone_map.get(zone_name), "zone_name") if zone_name else None,
					cluster_name=_label(cluster_map.get(zone_map.get(zone_name).cluster), "cluster_name")
					if zone_name and zone_map.get(zone_name)
					else None,
					province_name=_label(
						province_map.get(cluster_map.get(zone_map.get(zone_name).cluster).province),
						"province_name",
					)
					if zone_name
					and zone_map.get(zone_name)
					and cluster_map.get(zone_map.get(zone_name).cluster)
					else None,
					team_id=team.name,
					team_type=team.team_type,
					pool_ids=[pool.name for pool in pool_list],
					pool_names=[_label(pool, "pool_name") for pool in pool_list],
					member_count=len(members_by_team.get(team.name, [])),
					member_names=sorted(
						_label(staff_map.get(member.staff), "full_name")
						for member in members_by_team.get(team.name, [])
						if staff_map.get(member.staff)
					),
					zone_count=len(team_zones),
					ward_count=sum(ward_count_by_zone.get(zone_name, 0) for zone_name in team_zones),
					school_count=sum(school_count_by_zone.get(zone_name, 0) for zone_name in team_zones),
					active_students=sum(
						active_students_by_zone.get(zone_name, 0) for zone_name in team_zones
					),
					path=f"{parent}/{row_id}" if parent else row_id,
				)
			)

	for team_name, memberships in members_by_team.items():
		team = team_map.get(team_name)
		if not team:
			continue
		zone_name = team_zone_by_team[team_name][0].zone if team_zone_by_team.get(team_name) else "campus"
		parent = f"team:{team_name}:{zone_name}"
		if not any(row["id"] == parent for row in rows):
			parent = f"team:{team_name}:campus"
		for membership in memberships:
			staff_row = staff_map.get(membership.staff)
			if not staff_row:
				continue
			active = active_staff_count.get(staff_row.name, 0)
			cap = capacity.get(staff_row.name)
			load_status = _workload_status(active, cap)
			status = (
				"needs_review"
				if not staff_row.is_active
				else ("capacity_warning" if load_status in {"near_capacity", "over_capacity"} else "healthy")
			)
			load_percent = (
				round(active / int(cap.max_active_students) * 100, 1)
				if cap and cap.max_active_students
				else None
			)
			rows.append(
				row_base(
					f"staff:{staff_row.name}:{team_name}",
					"staff",
					_label(staff_row, "full_name"),
					parent,
					{
						"campus": {staff_row.campus} if staff_row.campus else set(),
						"team": {team_name},
						"staff": {staff_row.name},
					},
					status=status,
					campus_name=_label(
						next((c for c in sources["campuses"] if c.name == staff_row.campus), None),
						"campus_name",
					)
					if staff_row.get("campus")
					else None,
					zone_name=_label(zone_map.get(zone_name), "zone_name") if zone_name != "campus" else None,
					staff_id=staff_row.name,
					user=staff_row.user,
					team_id=team_name,
					team_name=_label(team, "team_name"),
					function=membership.function,
					active_students=active,
					capacity=cap.max_active_students if cap else None,
					load_percent=load_percent,
					workload=load_status,
					path=f"{parent}/staff:{staff_row.name}:{team_name}",
				)
			)

	row_by_id = {row["id"]: row for row in rows}
	path_cache = {}

	def full_path(row_id):
		if row_id in path_cache:
			return path_cache[row_id]
		row = row_by_id[row_id]
		parent = row.get("parent_id")
		path = f"{full_path(parent)}/{row_id}" if parent in row_by_id else row_id
		path_cache[row_id] = path
		return path

	for row in rows:
		row["path"] = full_path(row["id"])

	return rows, active_students


def _filter_rows(rows, filters):
	if not filters:
		return rows
	row_map = {row["id"]: row for row in rows}
	children = defaultdict(list)
	for row in rows:
		if row.get("parent_id"):
			children[row["parent_id"]].append(row["id"])

	def match(row):
		values = row.get("filter_values", {})
		for key in ("campus", "province", "cluster", "zone", "school", "team", "staff"):
			if key in filters and filters[key] not in values.get(key, set()):
				return False
		status = filters.get("status")
		if status and row.get("status") != status:
			return False
		workload = filters.get("workload")
		if workload and row.get("workload") != workload:
			return False
		search = filters.get("search", "").lower()
		if search:
			text = " ".join(
				str(row.get(key) or "")
				for key in ("label", "team_name", "staff_name", "pool_names", "function", "status")
			).lower()
			if search not in text:
				return False
		return True

	matched = {row["id"] for row in rows if match(row)}
	visible = set(matched)
	for row in rows:
		if row["id"] not in matched:
			continue
		parent = row.get("parent_id")
		while parent and parent in row_map:
			visible.add(parent)
			parent = row_map[parent].get("parent_id")
	return [row for row in rows if row["id"] in visible]


def _clean_row(row, children):
	return {
		key: value for key, value in row.items() if key not in {"filter_values"} and key != "has_children"
	} | {"has_children": bool(children.get(row["id"]))}


@frappe.whitelist()
def get_overview(filters=None, cursor=None, limit=50):
	"""Return the bounded, permission-scoped assignment setup projection."""
	context = _actor_context()
	filters = _normalize_filters(filters)
	sources = _overview_sources(context)
	rows, active_students = _overview_rows(sources, context)
	rows = _filter_rows(rows, filters)
	rows.sort(key=lambda row: (row.get("path", ""), row["id"]))
	offset = _offset(cursor)
	page_size = _limit(limit)
	page = rows[offset : offset + page_size]
	children = defaultdict(list)
	for row in rows:
		if row.get("parent_id"):
			children[row["parent_id"]].append(row["id"])
	page = [_clean_row(row, children) for row in page]

	status_counts = defaultdict(int)
	for row in rows:
		status_counts[row.get("status", "healthy")] += 1
	missing_sources = [doctype for doctype in REQUIRED_DOCTYPES if not _doctype_exists(doctype)]
	policies = sources.get("policies", [])
	return {
		"contractStatus": "partial" if missing_sources else "ready",
		"schemaVersion": "assignment-overview-v1",
		"as_of": str(now_datetime()),
		"next_cursor": str(offset + len(page)) if offset + len(page) < len(rows) else None,
		"summary": {
			"campuses": len(sources["campuses"]),
			"zones": len(sources["zones"]),
			"schools": len(sources["schools"]),
			"teams": len(sources["teams"]),
			"staff": len(sources["staff"]),
			"assigned_rows": status_counts["healthy"]
			+ status_counts["needs_review"]
			+ status_counts["capacity_warning"],
			"unassigned_rows": status_counts["unassigned"],
			"needs_review_rows": status_counts["needs_review"],
			"capacity_warning_rows": status_counts["capacity_warning"],
			"active_students": active_students,
			"active_policies": len(policies),
		},
		"filter_schema": {
			"fields": [
				{
					"key": "campus",
					"label": _("Campus"),
					"options": [
						{"label": _label(row, "campus_name"), "value": row.name}
						for row in sources["campuses"]
					],
				},
				{
					"key": "province",
					"label": _("Tỉnh/TP"),
					"options": [
						{"label": _label(row, "province_name"), "value": row.name}
						for row in sources["provinces"]
					],
				},
				{
					"key": "cluster",
					"label": _("Cụm tuyển sinh"),
					"options": [
						{"label": _label(row, "cluster_name"), "value": row.name}
						for row in sources["clusters"]
					],
				},
				{
					"key": "zone",
					"label": _("Địa bàn"),
					"options": [
						{"label": _label(row, "zone_name"), "value": row.name} for row in sources["zones"]
					],
				},
				{
					"key": "school",
					"label": _("Trường THPT"),
					"options": [
						{"label": _label(row, "school_name"), "value": row.name} for row in sources["schools"]
					],
				},
				{
					"key": "team",
					"label": _("Nhóm"),
					"options": [
						{"label": _label(row, "team_name"), "value": row.name} for row in sources["teams"]
					],
				},
				{
					"key": "staff",
					"label": _("Nhân viên"),
					"options": [
						{"label": _label(row, "full_name"), "value": row.name} for row in sources["staff"]
					],
				},
				{
					"key": "status",
					"label": _("Trạng thái"),
					"options": [{"label": key, "value": key} for key in sorted(STATUS_VALUES - {"all"})],
				},
				{
					"key": "workload",
					"label": _("Tải"),
					"options": [{"label": key, "value": key} for key in sorted(WORKLOAD_VALUES - {"all"})],
				},
			],
		},
		"rows": page,
		"warnings": (
			[
				{
					"code": "partial_schema",
					"message": _("Một số DocType nền tảng chưa được migrate."),
					"doctypes": missing_sources,
				}
			]
			if missing_sources
			else []
		),
		"capabilities": {
			"profile": context["profile"],
			"role_state": context["role_state"],
			"can_view_readiness": "system.configure" in context["capabilities"],
			"can_edit_identity": "system.configure" in context["capabilities"],
			"can_edit_topology": "system.configure" in context["capabilities"]
			or "admissions.oversee" in context["capabilities"],
			"can_reassign_student": "student.ownership.manage" in context["capabilities"],
			"team_scoped": not context["is_system_manager"]
			and "admissions.oversee" not in context["capabilities"],
		},
		"edit_options": _topology_options(sources, context),
	}


def _required_command_text(value, label, *, minimum=1, maximum=140):
	if not isinstance(value, str):
		frappe.throw(_("{0} must be text.").format(label), frappe.ValidationError)
	value = value.strip()
	if not minimum <= len(value) <= maximum:
		frappe.throw(
			_("{0} must be between {1} and {2} characters.").format(label, minimum, maximum),
			frappe.ValidationError,
		)
	return value


def _command_error(code, message):
	frappe.throw(_("{0}: {1}").format(code, message), frappe.ValidationError)


def _command_bool(value):
	if isinstance(value, bool):
		return value
	if isinstance(value, str):
		return value.lower() in {"1", "true", "yes", "on"}
	return bool(value)


def _active_zone_assignment(zone):
	rows = _safe_get_all(
		"CRM Team Zone Assignment",
		["name", "team", "revision", "effective_from", "effective_until", "modified"],
		{"zone": zone, "status": "Active"},
		"effective_from desc, modified desc",
	)
	return next((row for row in rows if _date_active(row)), None)


def _active_school_assignments(high_school):
	return _safe_get_all(
		"CRM High School Assignment",
		["name", "staff", "team", "high_school", "zone", "status", "needs_review", "assigned_on", "modified"],
		{"high_school": high_school, "status": "Active"},
		"modified asc, name asc",
	)


def _school_revision_from_database(high_school):
	return _school_assignment_revision(_active_school_assignments(high_school))


def _student_count_for_schools(schools):
	if not schools or not _doctype_exists("CRM Student"):
		return 0
	return len(
		_safe_get_all(
			"CRM Student",
			["name"],
			{"high_school": ["in", list(schools)], "lifecycle_stage": ["not in", ["Lost"]]},
		)
	)


def _topology_impact(action, target_id):
	if action == "zone_team":
		schools = _safe_get_all(
			"CRM High School Assignment",
			["high_school"],
			{"zone": target_id, "status": "Active"},
		)
		school_ids = sorted({row.high_school for row in schools if row.get("high_school")})
		return {
			"target": target_id,
			"affected_high_schools": len(school_ids),
			"affected_students": _student_count_for_schools(school_ids),
			"current_assignments": [row.high_school for row in schools if row.get("high_school")],
		}

	assignments = _active_school_assignments(target_id)
	return {
		"target": target_id,
		"affected_high_schools": 1 if frappe.db.exists("CRM High School", target_id) else 0,
		"affected_students": _student_count_for_schools([target_id]),
		"current_assignments": [
			{"name": row.name, "staff": row.staff, "team": row.team, "needs_review": bool(row.needs_review)}
			for row in assignments
		],
	}


def _topology_receipt(command_key):
	if not _doctype_exists(TOPOLOGY_RECEIPT_DOCTYPE):
		_command_error("SCHEMA_NOT_READY", "CRM Student Command Receipt chưa được migrate.")
	return frappe.db.get_value(
		TOPOLOGY_RECEIPT_DOCTYPE,
		{"command_key": command_key},
		["name", "outcome", "result_json", "request_fingerprint"],
		as_dict=True,
	)


def _replay_topology_receipt(receipt, fingerprint=None):
	if fingerprint and receipt.get("request_fingerprint") != fingerprint:
		_command_error("IDEMPOTENCY_CONFLICT", "Idempotency key đã được dùng cho payload khác.")
	if receipt.outcome == "applied":
		try:
			result = frappe.parse_json(receipt.result_json or "{}")
		except (TypeError, ValueError):
			result = {}
		result["replayed"] = True
		return result
	if receipt.outcome == "pending":
		_command_error("COMMAND_IN_PROGRESS", "Lệnh setup đang được xử lý; hãy tải lại sau ít giây.")
	_command_error("COMMAND_REJECTED", "Lệnh setup trước đó không được áp dụng.")


def _reserve_topology_receipt(*, command_key, fingerprint, actor, correlation_id, context):
	try:
		receipt = frappe.get_doc(
			{
				"doctype": TOPOLOGY_RECEIPT_DOCTYPE,
				"receipt_key": command_key,
				"command_kind": "assignment_topology",
				"command_key": command_key,
				"source_key": f"assignment-topology:{command_key}",
				"nonce_key": f"assignment-topology:{command_key}",
				"request_fingerprint": fingerprint,
				"outcome": "pending",
				"actor": actor,
				"scope_snapshot": json.dumps(context, sort_keys=True, default=str),
				"policy_version": "assignment-workspace-v1",
				"schema_version": "assignment-workspace-v1",
				"correlation_token": correlation_id,
				"request_received_at": now_datetime(),
			}
		).insert(ignore_permissions=True)
		return receipt
	except frappe.DuplicateEntryError:
		frappe.db.rollback()
		receipt = _topology_receipt(command_key)
		if receipt:
			return _replay_topology_receipt(receipt, fingerprint)
		raise


def _complete_topology_receipt(receipt, result):
	receipt.outcome = "applied"
	receipt.result_json = json.dumps(result, sort_keys=True, default=str)
	receipt.result_revision = int(result["revision"]) if str(result.get("revision", "")).isdigit() else None
	receipt.completed_at = now_datetime()
	receipt.save(ignore_permissions=True)


def _assignment_audit_comment(*, action, reason, correlation_id, idempotency_key):
	return (
		f"<p><strong>{frappe.utils.escape_html(action)}</strong> "
		f"{frappe.utils.escape_html(_('from Assignment Overview'))}.</p>"
		f"<p><strong>{frappe.utils.escape_html(_('Reason'))}:</strong> {frappe.utils.escape_html(reason)}</p>"
		f"<p><small>Correlation: {frappe.utils.escape_html(correlation_id)} · "
		f"Idempotency: {frappe.utils.escape_html(idempotency_key)}</small></p>"
	)


def _validate_topology_target(action, target_id, team_id=None, staff_id=None):
	if action not in TOPOLOGY_ACTIONS:
		_command_error("UNKNOWN_ACTION", "Loại thay đổi setup không được hỗ trợ.")
	if action == "zone_team":
		if not frappe.db.exists("CRM Zone", target_id):
			_command_error("TARGET_NOT_FOUND", "Zone không tồn tại.")
		if not team_id or not frappe.db.exists("CRM Team", team_id):
			_command_error("TARGET_NOT_FOUND", "Team không tồn tại.")
		if not frappe.db.get_value("CRM Team", team_id, "is_active"):
			_command_error("TEAM_INACTIVE", "Team đích đã tắt.")
		if not frappe.db.sql(
			"""
			SELECT 1 FROM `tabCRM Team Membership` m
			JOIN `tabCRM Staff` s ON s.name = m.parent
			WHERE m.team = %s AND s.is_active = 1 LIMIT 1
			""",
			(team_id,),
		):
			_command_error("TEAM_WITHOUT_ACTIVE_MEMBER", "Team đích chưa có nhân sự active.")
		return

	if not frappe.db.exists("CRM High School", target_id):
		_command_error("TARGET_NOT_FOUND", "Trường THPT không tồn tại.")
	if not frappe.db.get_value("CRM High School", target_id, "is_active"):
		_command_error("SCHOOL_INACTIVE", "Trường THPT đích đã tắt.")
	if not team_id or not frappe.db.exists("CRM Team", team_id):
		_command_error("TARGET_NOT_FOUND", "Team không tồn tại.")
	if not staff_id or not frappe.db.exists("CRM Staff", staff_id):
		_command_error("TARGET_NOT_FOUND", "CRM Staff không tồn tại.")
	if not frappe.db.get_value("CRM Team", team_id, "is_active"):
		_command_error("TEAM_INACTIVE", "Team đích đã tắt.")
	if not frappe.db.get_value("CRM Staff", staff_id, "is_active"):
		_command_error("STAFF_INACTIVE", "Nhân sự nhận Lead đã tắt.")
	memberships = frappe.get_all(
		"CRM Team Membership",
		filters={"parent": staff_id, "parenttype": "CRM Staff", "team": team_id},
		fields=["effective_from", "effective_until"],
	)
	if not any(_date_active(row) for row in memberships):
		_command_error("STAFF_NOT_IN_TEAM", "CRM Staff chưa thuộc Team đích.")
	ward = frappe.db.get_value("CRM High School", target_id, "ward")
	zone_id = frappe.db.get_value("CRM Ward", ward, "zone") if ward else None
	if not zone_id:
		_command_error("SCHOOL_GEOGRAPHY_INCOMPLETE", "Trường chưa có Ward → Zone hợp lệ.")
	zone_assignments = frappe.get_all(
		"CRM Team Zone Assignment",
		filters={"zone": zone_id, "team": team_id, "status": "Active"},
		fields=["effective_from", "effective_until"],
	)
	if not any(_date_active(row) for row in zone_assignments):
		_command_error("TEAM_ZONE_MISMATCH", "Team đích không sở hữu Zone của trường.")


def _apply_zone_team(
	*, target_id, team_id, effective_from, expected_revision, reason, correlation_id, idempotency_key
):
	current = _active_zone_assignment(target_id)
	current_revision = str(current.revision if current else 0)
	if current_revision != str(expected_revision):
		_command_error("STALE_ASSIGNMENT_REVISION", "Zone đã thay đổi; hãy tải lại trước khi lưu.")
	impact = _topology_impact("zone_team", target_id)
	if current and current.team == team_id:
		return {
			"status": "no_change",
			"action": "zone_team",
			"target_id": target_id,
			"team": team_id,
			"revision": current.revision,
			**impact,
		}

	doc = frappe.get_doc(
		{
			"doctype": "CRM Team Zone Assignment",
			"team": team_id,
			"zone": target_id,
			"status": "Active",
			"effective_from": effective_from,
			"revision": int(current.revision or 0) + 1 if current else 1,
		}
	).insert(ignore_permissions=True)
	doc.add_comment(
		"Comment",
		_assignment_audit_comment(
			action="Zone → Team",
			reason=reason,
			correlation_id=correlation_id,
			idempotency_key=idempotency_key,
		),
	)
	return {
		"status": "applied",
		"action": "zone_team",
		"target_id": target_id,
		"team": team_id,
		"revision": doc.revision,
		"effective_from": str(effective_from),
		**impact,
	}


def _apply_school_assignment(
	*,
	target_id,
	team_id,
	staff_id,
	effective_from,
	expected_revision,
	reason,
	correlation_id,
	idempotency_key,
	replace_existing,
):
	assignments = _active_school_assignments(target_id)
	current_revision = _school_assignment_revision(assignments)
	if current_revision != str(expected_revision):
		_command_error("STALE_ASSIGNMENT_REVISION", "Mapping trường đã thay đổi; hãy tải lại trước khi lưu.")
	impact = _topology_impact("school_assignment", target_id)
	if len(assignments) == 1 and assignments[0].team == team_id and assignments[0].staff == staff_id:
		return {
			"status": "no_change",
			"action": "school_assignment",
			"target_id": target_id,
			"team": team_id,
			"staff": staff_id,
			"revision": current_revision,
			**impact,
		}
	if assignments and not replace_existing:
		_command_error(
			"ASSIGNMENT_REPLACEMENT_REQUIRED", "Mapping hiện tại sẽ được thay thế; hãy xác nhận lại."
		)

	for assignment in assignments:
		old_doc = frappe.get_doc("CRM High School Assignment", assignment.name)
		old_doc.status = "Retired"
		old_doc.save(ignore_permissions=True)
		old_doc.add_comment(
			"Comment",
			_assignment_audit_comment(
				action="Retire High School Assignment",
				reason=reason,
				correlation_id=correlation_id,
				idempotency_key=idempotency_key,
			),
		)

	doc = frappe.get_doc(
		{
			"doctype": "CRM High School Assignment",
			"staff": staff_id,
			"team": team_id,
			"high_school": target_id,
			"status": "Active",
			"needs_review": 0,
			"assigned_on": effective_from,
		}
	).insert(ignore_permissions=True)
	doc.add_comment(
		"Comment",
		_assignment_audit_comment(
			action="High School → Staff/Team",
			reason=reason,
			correlation_id=correlation_id,
			idempotency_key=idempotency_key,
		),
	)
	new_revision = _school_revision_from_database(target_id)
	return {
		"status": "applied",
		"action": "school_assignment",
		"target_id": target_id,
		"team": team_id,
		"staff": staff_id,
		"revision": new_revision,
		"effective_from": str(effective_from),
		"retired_assignments": [row.name for row in assignments],
		**impact,
	}


@frappe.whitelist()
def get_assignment_impact(action, target_id, team_id=None, staff_id=None):
	"""Preview topology impact before a manager confirms a mapping change."""
	context = _actor_context()
	if not _can_edit_topology(context):
		frappe.throw(
			_("Only Admissions Director or System Manager may edit topology."), frappe.PermissionError
		)
	action = _required_command_text(action, "action", maximum=40)
	target_id = _required_command_text(target_id, "target_id")
	team_id = team_id.strip() if isinstance(team_id, str) and team_id.strip() else None
	staff_id = staff_id.strip() if isinstance(staff_id, str) and staff_id.strip() else None
	_validate_topology_target(action, target_id, team_id, staff_id)
	current = _active_zone_assignment(target_id) if action == "zone_team" else None
	assignments = _active_school_assignments(target_id) if action == "school_assignment" else []
	return {
		"action": action,
		"target_id": target_id,
		"current_revision": str(current.revision if current else _school_assignment_revision(assignments)),
		"impact": _topology_impact(action, target_id),
		"requires_confirmation": bool(assignments)
		if action == "school_assignment"
		else bool(current and current.team != team_id),
		"options": _topology_options(_overview_sources(context), context),
	}


def _batch_validation_row(high_school, team_id, staff_id):
	assignments = _active_school_assignments(high_school)
	row = {
		"high_school_id": high_school,
		"label": frappe.db.get_value("CRM High School", high_school, "school_name") or high_school,
		"current_revision": _school_assignment_revision(assignments),
		"current_assignments": [
			{"staff": item.staff, "team": item.team, "needs_review": bool(item.needs_review)}
			for item in assignments
		],
		"affected_students": _student_count_for_schools([high_school]),
		"requires_replacement": bool(assignments),
		"valid": True,
	}
	try:
		_validate_topology_target("school_assignment", high_school, team_id, staff_id)
	except Exception as exc:
		row.update({"valid": False, "error": str(exc)})
	return row


@frappe.whitelist()
def get_assignment_batch_impact(high_school_ids, team_id=None, staff_id=None):
	"""Validate and preview a guarded batch of High School mappings."""
	context = _actor_context()
	if not _can_edit_topology(context):
		frappe.throw(
			_("Only Admissions Director or System Manager may edit topology."), frappe.PermissionError
		)
	school_ids = _parse_string_list(high_school_ids, "high_school_ids")
	team_id = _required_command_text(team_id, "team_id") if team_id else None
	staff_id = _required_command_text(staff_id, "staff_id") if staff_id else None
	if not team_id or not staff_id:
		_command_error("INVALID_INPUT", "Batch mapping cần Team và Nhân sự nhận Lead.")
	rows = [_batch_validation_row(school_id, team_id, staff_id) for school_id in school_ids]
	return {
		"action": "school_assignment_batch",
		"team_id": team_id,
		"staff_id": staff_id,
		"rows": rows,
		"all_valid": all(row["valid"] for row in rows),
		"requires_confirmation": any(row["requires_replacement"] for row in rows),
		"affected_high_schools": len(rows),
		"affected_students": sum(row["affected_students"] for row in rows),
		"options": _topology_options(_overview_sources(context), context),
	}


def _expected_revision_map(value, school_ids):
	if isinstance(value, str):
		try:
			value = frappe.parse_json(value)
		except (TypeError, ValueError):
			frappe.throw(_("expected_revisions must be a JSON object."), frappe.ValidationError)
	if not isinstance(value, dict):
		frappe.throw(_("expected_revisions must be an object."), frappe.ValidationError)
	missing = [school_id for school_id in school_ids if school_id not in value]
	if missing:
		_command_error("INVALID_INPUT", "Thiếu revision của một hoặc nhiều trường.")
	return {school_id: str(value[school_id]) for school_id in school_ids}


@frappe.whitelist(methods=["POST"])
def apply_assignment_batch_command(
	high_school_ids,
	team_id=None,
	staff_id=None,
	effective_from=None,
	expected_revisions=None,
	reason=None,
	idempotency_key=None,
	correlation_id=None,
	replace_existing=False,
):
	"""Apply an all-or-none, revision-guarded High School mapping batch."""
	context = _actor_context()
	if not _can_edit_topology(context):
		frappe.throw(
			_("Only Admissions Director or System Manager may edit topology."), frappe.PermissionError
		)
	school_ids = _parse_string_list(high_school_ids, "high_school_ids")
	team_id = _required_command_text(team_id, "team_id") if team_id else None
	staff_id = _required_command_text(staff_id, "staff_id") if staff_id else None
	reason = _required_command_text(reason, "reason", minimum=5, maximum=2000)
	idempotency_key = _required_command_text(idempotency_key, "idempotency_key", maximum=140)
	correlation_id = _required_command_text(
		correlation_id or str(uuid.uuid4()), "correlation_id", maximum=140
	)
	if not team_id or not staff_id:
		_command_error("INVALID_INPUT", "Batch mapping cần Team và Nhân sự nhận Lead.")
	if not _command_bool(replace_existing):
		_command_error("BATCH_CONFIRMATION_REQUIRED", "Batch mapping cần xác nhận thay thế mapping hiện tại.")
	if expected_revisions in (None, ""):
		_command_error("INVALID_INPUT", "expected_revisions là bắt buộc.")
	revisions = _expected_revision_map(expected_revisions, school_ids)
	try:
		effective_from = getdate(effective_from or today())
	except (TypeError, ValueError):
		_command_error("INVALID_INPUT", "effective_from không hợp lệ.")

	validation_rows = [_batch_validation_row(school_id, team_id, staff_id) for school_id in school_ids]
	if not all(row["valid"] for row in validation_rows):
		_command_error("BATCH_VALIDATION_FAILED", "Một hoặc nhiều trường không đủ điều kiện mapping.")
	request = {
		"action": "school_assignment_batch",
		"high_school_ids": school_ids,
		"team_id": team_id,
		"staff_id": staff_id,
		"effective_from": str(effective_from),
		"expected_revisions": revisions,
		"reason": reason,
		"replace_existing": True,
	}
	actor = frappe.session.user
	command_key = hashlib.sha256(f"assignment-topology-batch|{actor}|{idempotency_key}".encode()).hexdigest()
	fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
	existing = _topology_receipt(command_key)
	if existing:
		return _replay_topology_receipt(existing, fingerprint)
	receipt = _reserve_topology_receipt(
		command_key=command_key,
		fingerprint=fingerprint,
		actor=actor,
		correlation_id=correlation_id,
		context=context,
	)
	if isinstance(receipt, dict):
		return receipt
	try:
		results = []
		for school_id in school_ids:
			results.append(
				_apply_school_assignment(
					target_id=school_id,
					team_id=team_id,
					staff_id=staff_id,
					effective_from=effective_from,
					expected_revision=revisions[school_id],
					reason=reason,
					correlation_id=correlation_id,
					idempotency_key=idempotency_key,
					replace_existing=True,
				)
			)
		result = {
			"status": "applied",
			"action": "school_assignment_batch",
			"target_ids": school_ids,
			"rows": results,
			"affected_high_schools": len(results),
			"affected_students": sum(row.get("affected_students", 0) for row in results),
			"correlation_id": correlation_id,
			"replayed": False,
		}
		_complete_topology_receipt(receipt, result)
		frappe.db.commit()
		return result
	except Exception:
		frappe.db.rollback()
		raise


def _normalize_staff_memberships(value, campus):
	if isinstance(value, str):
		try:
			value = frappe.parse_json(value)
		except (TypeError, ValueError):
			frappe.throw(_("memberships must be a JSON array."), frappe.ValidationError)
	if not isinstance(value, list) or len(value) > 50:
		frappe.throw(_("memberships must be an array with at most 50 rows."), frappe.ValidationError)
	teams = {
		row.name: row for row in _safe_get_all("CRM Team", ["name", "campus", "is_active"], {"is_active": 1})
	}
	rows = []
	for item in value:
		if not isinstance(item, dict):
			frappe.throw(_("A Team Membership row is invalid."), frappe.ValidationError)
		team = item.get("team")
		function = item.get("function")
		if not team or team not in teams:
			_command_error("TEAM_INVALID", "Team Membership phải trỏ tới Team active.")
		if teams[team].campus != campus:
			_command_error("TEAM_CAMPUS_MISMATCH", "Team Membership phải cùng Campus với CRM Staff.")
		if function not in TEAM_MEMBER_FUNCTIONS:
			_command_error("FUNCTION_INVALID", "Chức năng Team Membership không được hỗ trợ.")
		start = item.get("effective_from")
		end = item.get("effective_until")
		try:
			if start:
				start = getdate(start)
			if end:
				end = getdate(end)
		except (TypeError, ValueError):
			_command_error("INVALID_INPUT", "Ngày hiệu lực của Team Membership không hợp lệ.")
		if start and end and start > end:
			_command_error("INVALID_INPUT", "Effective Until không được trước Effective From.")
		rows.append(
			{
				"team": team,
				"function": function,
				"term": str(item.get("term") or "").strip()[:140],
				"effective_from": start,
				"effective_until": end,
				"is_primary": int(_command_bool(item.get("is_primary"))),
			}
		)
	return rows


@frappe.whitelist(methods=["POST"])
def apply_staff_context_command(
	staff_id=None,
	user=None,
	full_name=None,
	department=None,
	campus=None,
	is_active=True,
	memberships=None,
	expected_revision=None,
	reason=None,
	idempotency_key=None,
	correlation_id=None,
):
	"""Create/update CRM Staff and its Team Membership context from setup UI."""
	context = _require_setup_access()
	staff_id = staff_id.strip() if isinstance(staff_id, str) and staff_id.strip() else None
	user = _required_command_text(user, "user") if user else None
	if staff_id and not frappe.db.exists("CRM Staff", staff_id):
		_command_error("TARGET_NOT_FOUND", "CRM Staff không tồn tại.")
	current = (
		frappe.db.get_value("CRM Staff", staff_id, ["user", "modified"], as_dict=True) if staff_id else None
	)
	user = current.user if current else user
	if not user or not frappe.db.exists("User", user):
		_command_error("TARGET_NOT_FOUND", "User không tồn tại.")
	full_name = _required_command_text(full_name, "full_name", maximum=140) if full_name else None
	if not full_name:
		full_name = frappe.db.get_value("User", user, "full_name") or user
	department = _required_command_text(department, "department")
	campus = _required_command_text(campus, "campus")
	if (
		not frappe.db.exists("CRM Department", department)
		or frappe.db.get_value("CRM Department", department, "campus") != campus
	):
		_command_error("DEPARTMENT_CAMPUS_MISMATCH", "Department phải thuộc Campus đã chọn.")
	if not frappe.db.exists("CRM Campus", campus):
		_command_error("TARGET_NOT_FOUND", "Campus không tồn tại.")
	if memberships is None:
		_command_error("INVALID_INPUT", "memberships là bắt buộc để ghi nhận đầy đủ Staff context.")
	normalized_memberships = _normalize_staff_memberships(memberships, campus)
	if expected_revision in (None, ""):
		_command_error("INVALID_INPUT", "expected_revision là bắt buộc.")
	current_revision = _context_revision(staff_id)
	if str(expected_revision) != current_revision:
		_command_error("STALE_STAFF_CONTEXT", "CRM Staff đã thay đổi; hãy tải lại context trước khi lưu.")
	reason = _required_command_text(reason, "reason", minimum=5, maximum=2000)
	idempotency_key = _required_command_text(idempotency_key, "idempotency_key", maximum=140)
	correlation_id = _required_command_text(
		correlation_id or str(uuid.uuid4()), "correlation_id", maximum=140
	)
	request = {
		"action": "staff_context",
		"staff_id": staff_id,
		"user": user,
		"full_name": full_name,
		"department": department,
		"campus": campus,
		"is_active": _command_bool(is_active),
		"memberships": normalized_memberships,
		"expected_revision": str(expected_revision),
		"reason": reason,
	}
	actor = frappe.session.user
	command_key = hashlib.sha256(f"assignment-staff-context|{actor}|{idempotency_key}".encode()).hexdigest()
	fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True, default=str).encode()).hexdigest()
	existing = _topology_receipt(command_key)
	if existing:
		return _replay_topology_receipt(existing, fingerprint)
	receipt = _reserve_topology_receipt(
		command_key=command_key,
		fingerprint=fingerprint,
		actor=actor,
		correlation_id=correlation_id,
		context=context,
	)
	if isinstance(receipt, dict):
		return receipt
	try:
		if current:
			doc = frappe.get_doc("CRM Staff", staff_id)
		else:
			if frappe.db.exists("CRM Staff", {"user": user}):
				_command_error("STAFF_ALREADY_EXISTS", "User này đã có CRM Staff.")
			doc = frappe.get_doc({"doctype": "CRM Staff", "user": user})
		doc.full_name = full_name
		doc.department = department
		doc.campus = campus
		doc.is_active = int(_command_bool(is_active))
		doc.set("team_memberships", normalized_memberships)
		if current:
			doc.save(ignore_permissions=True)
		else:
			doc.insert(ignore_permissions=True)
		doc.add_comment(
			"Comment",
			_assignment_audit_comment(
				action="CRM Staff context",
				reason=reason,
				correlation_id=correlation_id,
				idempotency_key=idempotency_key,
			),
		)
		result = {
			"status": "applied",
			"action": "staff_context",
			"staff_id": doc.name,
			"user": doc.user,
			"revision": _context_revision(doc.name),
			"correlation_id": correlation_id,
			"replayed": False,
		}
		_complete_topology_receipt(receipt, result)
		frappe.db.commit()
		return result
	except Exception:
		frappe.db.rollback()
		raise


@frappe.whitelist(methods=["POST"])
def apply_assignment_command(
	action,
	target_id,
	team_id=None,
	staff_id=None,
	effective_from=None,
	expected_revision=None,
	reason=None,
	idempotency_key=None,
	correlation_id=None,
	replace_existing=False,
):
	"""Apply one guarded topology mapping through the authoritative DocType controllers."""
	context = _actor_context()
	if not _can_edit_topology(context):
		frappe.throw(
			_("Only Admissions Director or System Manager may edit topology."), frappe.PermissionError
		)
	action = _required_command_text(action, "action", maximum=40)
	target_id = _required_command_text(target_id, "target_id")
	team_id = _required_command_text(team_id, "team_id") if team_id else None
	staff_id = _required_command_text(staff_id, "staff_id") if staff_id else None
	reason = _required_command_text(reason, "reason", minimum=5, maximum=2000)
	idempotency_key = _required_command_text(idempotency_key, "idempotency_key", maximum=140)
	correlation_id = _required_command_text(
		correlation_id or str(uuid.uuid4()), "correlation_id", maximum=140
	)
	if expected_revision in (None, ""):
		_command_error("INVALID_INPUT", "expected_revision là bắt buộc.")
	try:
		effective_from = getdate(effective_from or today())
	except (TypeError, ValueError):
		_command_error("INVALID_INPUT", "effective_from không hợp lệ.")
	_validate_topology_target(action, target_id, team_id, staff_id)

	request = {
		"action": action,
		"target_id": target_id,
		"team_id": team_id,
		"staff_id": staff_id,
		"effective_from": str(effective_from),
		"expected_revision": str(expected_revision),
		"reason": reason,
		"replace_existing": _command_bool(replace_existing),
	}
	actor = frappe.session.user
	command_key = hashlib.sha256(f"assignment-topology|{actor}|{idempotency_key}".encode()).hexdigest()
	fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
	existing = _topology_receipt(command_key)
	if existing:
		return _replay_topology_receipt(existing, fingerprint)
	receipt = _reserve_topology_receipt(
		command_key=command_key,
		fingerprint=fingerprint,
		actor=actor,
		correlation_id=correlation_id,
		context=context,
	)
	if isinstance(receipt, dict):
		return receipt
	try:
		if action == "zone_team":
			result = _apply_zone_team(
				target_id=target_id,
				team_id=team_id,
				effective_from=effective_from,
				expected_revision=expected_revision,
				reason=reason,
				correlation_id=correlation_id,
				idempotency_key=idempotency_key,
			)
		else:
			result = _apply_school_assignment(
				target_id=target_id,
				team_id=team_id,
				staff_id=staff_id,
				effective_from=effective_from,
				expected_revision=expected_revision,
				reason=reason,
				correlation_id=correlation_id,
				idempotency_key=idempotency_key,
				replace_existing=_command_bool(replace_existing),
			)
		result.update({"correlation_id": correlation_id, "replayed": False})
		_complete_topology_receipt(receipt, result)
		frappe.db.commit()
		return result
	except Exception:
		frappe.db.rollback()
		raise
