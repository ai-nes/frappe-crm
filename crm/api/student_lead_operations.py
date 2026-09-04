"""Whitelisted manager operations and read-only fairness reporting."""

import frappe

from crm.fcrm.role_policy import capabilities_for_roles
from crm.fcrm.student_assignment import fairness_report
from crm.fcrm.student_lead_operations import (
	complete_ctv_item,
	fairness_summary,
	manager_reassign_student,
	open_ctv_batch,
	replenish_ctv_batch,
)


@frappe.whitelist(methods=["POST"])
def manager_reassign(student, target_staff, target_team, reason, expected_revision, emergency_override=False):
	roles = frappe.get_roles(frappe.session.user)
	if "student.ownership.manage" not in capabilities_for_roles(
		roles, administrator=frappe.session.user == "Administrator"
	):
		frappe.throw("Manager ownership capability is required.", frappe.PermissionError)
	return manager_reassign_student(
		student, target_staff, target_team, reason, expected_revision, emergency_override=emergency_override
	)


@frappe.whitelist()
def fairness_report_read(zone=None, since=None, until=None):
	return fairness_summary(zone=zone, since=since, until=until)


@frappe.whitelist(methods=["POST"])
def open_ctv_batch_command(staff, team, size=10, validity_hours=24):
	return open_ctv_batch(staff, team, size=int(size), validity_hours=int(validity_hours))


@frappe.whitelist(methods=["POST"])
def complete_ctv_item_command(batch, student):
	return complete_ctv_item(batch, student)


@frappe.whitelist(methods=["POST"])
def replenish_ctv_batch_command(batch, validity_hours=24):
	return replenish_ctv_batch(batch, validity_hours=int(validity_hours))
