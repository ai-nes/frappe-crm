"""Production-safe reconciliation for the Lead assignment topology.

This is intentionally additive and idempotent.  It uses the existing
production master data (Campus, Province, Ward and High School) and only
reconciles the small assignment-configuration layer around it.

Run through ``bench execute`` with ``apply=False`` first.  The apply mode:

* never edits or deletes CRM High School, CRM Ward, CRM Province, CRM Student,
  or CRM Student Routing Request rows;
* keeps historical demo Staff and policies when they are referenced by audit
  or routing history, but removes them from the active topology;
* creates Staff only for active production users with a canonical sales role.
"""

from __future__ import annotations

import json
from datetime import date

import frappe
from frappe.utils import getdate, now_datetime


SEED_STAFF_USERS = {
	"nguyen.minh.khoi@gmail.com",
	"le.thanh.huong@gmail.com",
	"pham.bao.chau@gmail.com",
	"tran.quoc.duy@gmail.com",
	"vo.thi.lan@gmail.com",
}

SALES_ROLES = {"Sale", "Lead Sale", "CTV Sale", "CTV Sale"}

EXPECTED_CAMPUS = "FPTU Ho Chi Minh Campus"
SOURCE_DEPARTMENT = "Tuyển sinh TP.HCM — Kỳ Thu 2026"
SOURCE_TEAM = "Tư vấn tuyển sinh TP.HCM"
SOURCE_POOL = "Nguồn tuyển sinh TP.HCM — Kỳ Thu 2026"

DEPARTMENT_LABEL = "Phòng Tư vấn Tuyển sinh FPTU TP.HCM"
TEAM_LABEL = "Đội Tư vấn Tuyển sinh FPTU TP.HCM"
POOL_LABEL = "Hàng chờ Lead Tuyển sinh FPTU TP.HCM"
POLICY_KEY = "lead-routing-fptu-hcm"


def _find_one(doctype, field, value):
	return frappe.db.get_value(doctype, {field: value}, "name")


def _resolve_existing(doctype, field, source, target):
	source_name = _find_one(doctype, field, source)
	target_name = _find_one(doctype, field, target)
	if target_name and source_name and target_name != source_name:
		frappe.throw(
			f"Both source and target {doctype} records exist: {source_name} / {target_name}. "
			"Resolve this duplicate manually before applying."
		)
	return target_name or source_name


def _plan(actions, action, **details):
	actions.append({"action": action, **details})


def _set_if_changed(doctype, name, fieldname, value, actions, *, apply):
	current = frappe.db.get_value(doctype, name, fieldname)
	if current == value:
		return False
	_plan(actions, "update_label", doctype=doctype, name=name, field=fieldname, before=current, after=value)
	if apply:
		frappe.db.set_value(doctype, name, fieldname, value, update_modified=False)
	return True


def _role_function(user):
	roles = set(frappe.get_roles(user))
	if "Sale" in roles:
		return "Sale"
	if roles & {"CTV Sale", "CTV Sale"}:
		return "CTV Sale"
	if "Lead Sale" in roles:
		return "Lead Sale"
	return None


def _ensure_staff(user, campus, department, team, actions, *, apply):
	function = _role_function(user.name)
	if not function or user.name in SEED_STAFF_USERS:
		return None

	staff_name = frappe.db.get_value("CRM Staff", {"user": user.name}, "name")
	if staff_name:
		staff = frappe.get_doc("CRM Staff", staff_name)
	else:
		staff = frappe.get_doc(
			{
				"doctype": "CRM Staff",
				"full_name": user.full_name or user.name,
				"user": user.name,
				"department": department,
				"campus": campus,
				"is_active": 1,
			}
		)
		_plan(actions, "create_staff", user=user.name, full_name=user.full_name or user.name, function=function)
		if apply:
			staff.insert(ignore_permissions=True)

	if apply:
		staff.full_name = user.full_name or user.name
		staff.department = department
		staff.campus = campus
		staff.is_active = 1
		membership = next((row for row in staff.team_memberships if row.team == team), None)
		if membership:
			membership.function = function
			membership.is_primary = 1
			membership.is_team_lead = int(function == "Lead Sale")
		else:
			staff.append(
				"team_memberships",
				{
					"team": team,
					"function": function,
					"is_primary": 1,
					"is_team_lead": int(function == "Lead Sale"),
				},
			)
		staff.save(ignore_permissions=True)
	else:
		_plan(actions, "ensure_staff_context", user=user.name, function=function, campus=campus, team=team)
	return staff.name


def _deactivate_seed_staff(actions, *, apply):
	for user in sorted(SEED_STAFF_USERS):
		staff_name = frappe.db.get_value("CRM Staff", {"user": user}, "name")
		if not staff_name:
			continue
		active = frappe.db.get_value("CRM Staff", staff_name, "is_active")
		if not active:
			continue
		_plan(
			actions,
			"deactivate_legacy_seed_staff",
			user=user,
			staff=staff_name,
			reason="Historical demo staff is retained for audit references but excluded from new routing.",
		)
		if apply:
			frappe.db.set_value("CRM Staff", staff_name, "is_active", 0, update_modified=False)


def _ensure_zone_topology(team, actions, *, apply):
	zone_rows = frappe.get_all(
		"CRM Zone",
		fields=["name", "zone_name", "cluster", "is_placeholder"],
		order_by="zone_name asc, name asc",
		limit_page_length=0,
	)
	for zone in zone_rows:
		province = frappe.db.get_value("CRM Cluster", zone.cluster, "province")
		province_label = frappe.db.get_value("CRM Province", province, "province_name") or province
		cluster_label = f"Cụm Tuyển sinh – {province_label}"
		zone_label = f"Địa bàn Tuyển sinh – {province_label}"
		cluster_name = zone.cluster
		_set_if_changed("CRM Cluster", cluster_name, "cluster_name", cluster_label, actions, apply=apply)
		_set_if_changed("CRM Cluster", cluster_name, "is_placeholder", 0, actions, apply=apply)
		_set_if_changed("CRM Zone", zone.name, "zone_name", zone_label, actions, apply=apply)
		_set_if_changed("CRM Zone", zone.name, "is_placeholder", 0, actions, apply=apply)

		active = frappe.get_all(
			"CRM Team Zone Assignment",
			filters={"zone": zone.name, "status": "Active"},
			fields=["name", "team", "revision"],
			limit_page_length=0,
		)
		if any(row.team == team for row in active):
			continue
		if active:
			_plan(actions, "replace_zone_team", zone=zone.name, old=[row.team for row in active], new=team)
		else:
			_plan(actions, "map_zone_to_team", zone=zone.name, team=team)
		if apply:
			for row in active:
				frappe.db.set_value(
					"CRM Team Zone Assignment",
					row.name,
					{"status": "Retired", "effective_until": date.today()},
					update_modified=False,
				)
			assignment = frappe.get_doc(
				{
					"doctype": "CRM Team Zone Assignment",
					"team": team,
					"zone": zone.name,
					"status": "Active",
					"effective_from": date.today(),
					"revision": max([int(row.revision or 0) for row in active] or [0]) + 1,
				}
			)
			assignment.insert(ignore_permissions=True)


def _ensure_policy(campus, pool, actions, *, apply):
	active = frappe.get_all(
		"CRM Student Routing Policy",
		filters={"campus": campus, "student_pool": pool, "status": "active"},
		fields=["name", "policy_key", "policy_version"],
		limit_page_length=0,
		order_by="policy_version desc, creation desc",
	)
	current = frappe.db.get_value("CRM Student Routing Policy", {"policy_key": POLICY_KEY}, "name")
	if not current:
		version = max([int(row.policy_version or 0) for row in active] or [0]) + 1
		_plan(actions, "create_production_routing_policy", policy_key=POLICY_KEY, policy_version=version)
		if apply:
			previous_service_flag = getattr(frappe.flags, "student_policy_service", False)
			frappe.flags.student_policy_service = True
			try:
				for row in active:
					legacy = frappe.get_doc("CRM Student Routing Policy", row.name)
					legacy.status = "retired"
					legacy.save(ignore_permissions=True)
			finally:
				frappe.flags.student_policy_service = previous_service_flag
		doc = frappe.get_doc(
			{
				"doctype": "CRM Student Routing Policy",
				"policy_key": POLICY_KEY,
				"policy_version": version,
				"status": "active",
				"campus": campus,
				"student_pool": pool,
				"strategy": "round_robin",
				"scoring_weights": json.dumps(
					{"load": 0.35, "territory": 0.30, "performance": 0.20, "rotation": 0.15}
				),
				"effective_from": now_datetime(),
				"recipient_scope": json.dumps({"roles": ["Sale", "CTV Sale"]}),
				"cursor_revision": 0,
				"authored_by": "Administrator",
				"approved_by": "Administrator",
				"approved_at": now_datetime(),
				"break_glass_reason": "Cấu hình production cho phân công Lead tuyển sinh FPTU TP.HCM.",
				"schema_version": "student-routing",
			}
		)
		if apply:
			previous_service_flag = getattr(frappe.flags, "student_policy_service", False)
			frappe.flags.student_policy_service = True
			try:
				doc.insert(ignore_permissions=True)
			finally:
				frappe.flags.student_policy_service = previous_service_flag
	else:
		_plan(actions, "reuse_production_routing_policy", policy=POLICY_KEY)


def run(apply=False):
	"""Return a plan, or apply it when ``apply=True``."""
	if not frappe.db.exists("CRM Campus", EXPECTED_CAMPUS):
		frappe.throw(f"Expected existing Campus not found: {EXPECTED_CAMPUS}")

	campus = EXPECTED_CAMPUS
	department = _resolve_existing("CRM Department", "department_name", SOURCE_DEPARTMENT, DEPARTMENT_LABEL)
	team = _resolve_existing("CRM Team", "team_name", SOURCE_TEAM, TEAM_LABEL)
	pool = _resolve_existing("CRM Student Pool", "pool_name", SOURCE_POOL, POOL_LABEL)
	if not department or not team or not pool:
		frappe.throw("Expected existing Department, Team, and Student Pool were not found.")

	actions = []
	warnings = [
		"CRM High School, CRM Ward, CRM Province, CRM Student and CRM Student Routing Request are read-only for this reconciliation.",
		"Legacy seed Staff and policies are retained when history references them; only active routing uses the new topology.",
	]

	_set_if_changed("CRM Department", department, "department_name", DEPARTMENT_LABEL, actions, apply=apply)
	_set_if_changed("CRM Team", team, "team_name", TEAM_LABEL, actions, apply=apply)
	_set_if_changed("CRM Student Pool", pool, "pool_name", POOL_LABEL, actions, apply=apply)
	_deactivate_seed_staff(actions, apply=apply)

	users = frappe.get_all(
		"User",
		filters={"enabled": 1, "name": ["not in", ["Guest", "Administrator"]]},
		fields=["name", "full_name"],
		order_by="full_name asc, name asc",
		limit_page_length=0,
	)
	staff = []
	for user in users:
		staff_name = _ensure_staff(user, campus, department, team, actions, apply=apply)
		if staff_name:
			staff.append(staff_name)

	_ensure_zone_topology(team, actions, apply=apply)
	_ensure_policy(campus, pool, actions, apply=apply)

	if apply:
		frappe.db.commit()

	return {
		"mode": "apply" if apply else "dry-run",
		"campus": campus,
		"department": department,
		"team": team,
		"pool": pool,
		"active_staff_candidates": sorted(staff),
		"actions": actions,
		"warnings": warnings,
		"read_only_doctypes": [
			"CRM High School",
			"CRM Ward",
			"CRM Province",
			"CRM Student",
			"CRM Student Routing Request",
		],
	}
