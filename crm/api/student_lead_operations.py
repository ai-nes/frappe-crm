"""Whitelisted manager operations and read-only fairness reporting."""

import frappe

from crm.fcrm.role_policy import capabilities_for_roles, resolve_crm_profile
from crm.fcrm.student_assignment import fairness_report
from crm.fcrm.student_lead_operations import (
	complete_ctv_item,
	fairness_summary,
	manager_reassign_student,
	open_ctv_batch,
	replenish_ctv_batch,
)

_MANAGER_PROFILES = frozenset({"lead_sales", "admissions_director"})
_CTV_BATCH_PROFILES = _MANAGER_PROFILES | {"ctv_sale"}
_CTV_FUNCTIONS = frozenset({"CTV Sale"})
_OWNER_FUNCTIONS = frozenset({"Sale", "CTV Sale"})


def _actor_context():
	actor = getattr(getattr(frappe, "session", None), "user", None)
	if not actor or actor in {"Guest", "None"}:
		frappe.throw("Authentication is required.", frappe.PermissionError)
	roles = set(frappe.get_roles(actor))
	profile = resolve_crm_profile(roles)
	capabilities = capabilities_for_roles(roles, administrator=actor == "Administrator")
	return actor, profile, capabilities


def _require_manager_access():
	actor, profile, capabilities = _actor_context()
	if actor != "Administrator" and (
		profile not in _MANAGER_PROFILES or "student.ownership.manage" not in capabilities
	):
		frappe.throw("Lead Sale or Admissions Director access is required.", frappe.PermissionError)
	return actor, profile


def _active_staff_for_user(user):
	row = frappe.db.get_value("CRM Staff", {"user": user}, ["name", "is_active"], as_dict=True)
	if not row or row.get("is_active") not in (1, True, "1"):
		return None
	return row.get("name")


def _team_names_for_staff(staff):
	if not staff:
		return set()
	rows = frappe.get_all(
		"CRM Team Membership",
		filters={"parent": staff, "parenttype": "CRM Staff"},
		fields=["team"],
	)
	return {row.get("team") for row in rows if row.get("team")}


def _team_staff_scope(actor):
	teams = _team_names_for_staff(_active_staff_for_user(actor))
	if not teams:
		return set()
	rows = frappe.get_all(
		"CRM Team Membership",
		filters={"team": ["in", list(teams)], "parenttype": "CRM Staff"},
		fields=["parent", "function"],
	)
	return {
		row.get("parent") for row in rows if row.get("parent") and row.get("function") in _OWNER_FUNCTIONS
	}


def _has_ctv_membership(staff, team):
	if not staff or not team:
		return False
	return bool(
		frappe.get_all(
			"CRM Team Membership",
			filters={
				"parent": staff,
				"parenttype": "CRM Staff",
				"team": team,
				"function": ["in", list(_CTV_FUNCTIONS)],
			},
			fields=["name"],
			limit_page_length=1,
		)
	)


def _validate_ctv_target(staff, team):
	row = frappe.db.get_value("CRM Staff", staff, ["name", "user", "is_active"], as_dict=True)
	if not row or row.get("is_active") not in (1, True, "1") or not row.get("user"):
		frappe.throw("The target CTV staff is not active.", frappe.PermissionError)
	target_profile = resolve_crm_profile(set(frappe.get_roles(row.user)))
	if target_profile != "ctv_sale" or not _has_ctv_membership(row.name, team):
		frappe.throw(
			"The batch target must be an active CTV Sale in the target team.", frappe.PermissionError
		)


def _require_ctv_batch_access(*, staff=None, team=None, batch=None):
	actor, profile, capabilities = _actor_context()
	if actor == "Administrator":
		return actor, profile, batch
	if profile not in _CTV_BATCH_PROFILES:
		frappe.throw("CTV Sale or Lead Sale access is required.", frappe.PermissionError)
	if profile == "ctv_sale" and "student.execute" not in capabilities:
		frappe.throw("Student processing capability is required.", frappe.PermissionError)
	if profile in _MANAGER_PROFILES and "student.ownership.manage" not in capabilities:
		frappe.throw("Student ownership capability is required.", frappe.PermissionError)

	target_staff = batch.get("staff") if batch else staff
	target_team = batch.get("team") if batch else team
	if not target_staff or not target_team:
		frappe.throw("CTV staff and team are required.", frappe.ValidationError)

	if profile == "ctv_sale":
		actor_staff = _active_staff_for_user(actor)
		if actor_staff != target_staff or not _has_ctv_membership(actor_staff, target_team):
			frappe.throw("A CTV Sale can only operate their own CTV batch.", frappe.PermissionError)
	else:
		if profile == "lead_sales" and target_team not in _team_names_for_staff(
			_active_staff_for_user(actor)
		):
			frappe.throw("The CTV batch is outside the Lead Sale team scope.", frappe.PermissionError)
		_validate_ctv_target(target_staff, target_team)
	return actor, profile, batch


@frappe.whitelist(methods=["POST"])
def manager_reassign(student, target_staff, target_team, reason, expected_revision, emergency_override=False):
	actor, profile = _require_manager_access()
	if profile == "lead_sales" and target_team not in _team_names_for_staff(_active_staff_for_user(actor)):
		frappe.throw("The target team is outside the Lead Sale team scope.", frappe.PermissionError)
	return manager_reassign_student(
		student, target_staff, target_team, reason, expected_revision, emergency_override=emergency_override
	)


@frappe.whitelist()
def fairness_report_read(zone=None, since=None, until=None):
	actor, profile = _require_manager_access()
	staff_scope = _team_staff_scope(actor) if profile == "lead_sales" else None
	return fairness_summary(zone=zone, since=since, until=until, staff_scope=staff_scope)


@frappe.whitelist(methods=["POST"])
def open_ctv_batch_command(staff, team, size=10, validity_hours=24):
	_require_ctv_batch_access(staff=staff, team=team)
	return open_ctv_batch(staff, team, size=int(size), validity_hours=int(validity_hours))


@frappe.whitelist(methods=["POST"])
def complete_ctv_item_command(batch, student):
	batch_doc = frappe.get_doc("CRM Student Assignment Batch", batch)
	_require_ctv_batch_access(batch=batch_doc)
	return complete_ctv_item(batch, student)


@frappe.whitelist(methods=["POST"])
def replenish_ctv_batch_command(batch, validity_hours=24):
	batch_doc = frappe.get_doc("CRM Student Assignment Batch", batch)
	_require_ctv_batch_access(batch=batch_doc)
	return replenish_ctv_batch(batch, validity_hours=int(validity_hours))
