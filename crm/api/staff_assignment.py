import json

import frappe
from frappe import _
from frappe.utils import now_datetime

from crm.fcrm.permissions import derive_owner_fields


ASSIGNABLE_DOCTYPES = {"CRM Student", "CRM Contact"}
STAFF_ASSIGN_DENIED_ROLES = {"Sale", "CTV-Sale", "Promoter-PR"}
STAFF_ASSIGN_ALLOWED_ROLES = {"System Manager", "Administrator", "Team Leader", "Counseller"}


def _has_staff_assign_permission(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	roles = set(frappe.get_roles(user))
	if roles.intersection(STAFF_ASSIGN_ALLOWED_ROLES):
		return True
	if roles.intersection(STAFF_ASSIGN_DENIED_ROLES):
		return False
	return False


@frappe.whitelist()
def can_assign_staff() -> bool:
	return _has_staff_assign_permission()


@frappe.whitelist()
def assign_staff(doctype: str, names: str | list, staff: str):
	if doctype not in ASSIGNABLE_DOCTYPES:
		frappe.throw(_("Staff assignment is only supported for CRM Student and CRM Contact."), frappe.PermissionError)

	if not _has_staff_assign_permission():
		frappe.throw(_("You are not permitted to assign staff."), frappe.PermissionError)

	if isinstance(names, str):
		names = json.loads(names)
	if not isinstance(names, list) or not names:
		frappe.throw(_("Please select at least one record."))

	if not staff or not frappe.db.exists("CRM Staff", staff):
		frappe.throw(_("Please select a valid CRM Staff."))

	updated = 0
	for name in names:
		doc = frappe.get_doc(doctype, name)
		if not doc.has_permission("write"):
			frappe.throw(_("Not permitted to update {0}").format(name), frappe.PermissionError)
		doc.assigned_to = staff
		doc.save()
		# doc.save() re-derives owner_staff/owning_team via validate(), but the
		# reciprocal linked record below is updated with a raw db.set_value that
		# bypasses hooks entirely — it must set those two fields explicitly too, or
		# they go stale on the linked record after this reassignment.
		owner_staff, owning_team = derive_owner_fields(staff)
		linked_updates = {"assigned_to": staff, "owner_staff": owner_staff, "owning_team": owning_team}
		if doctype == "CRM Student":
			contact = frappe.db.get_value("CRM Contact", {"student": name}, "name")
			if contact:
				contact_updates = dict(linked_updates)
				# sla_started_at only lives on CRM Contact and is set-once (see
				# CRMContact._track_sla_start); this raw write bypasses validate(),
				# so it must be applied here too or the SLA clock never starts for
				# a Contact whose assignment only ever changes via its linked Student.
				if not frappe.db.get_value("CRM Contact", contact, "sla_started_at"):
					contact_updates["sla_started_at"] = now_datetime()
				frappe.db.set_value("CRM Contact", contact, contact_updates, update_modified=False)
		elif doctype == "CRM Contact" and doc.get("student"):
			frappe.db.set_value("CRM Student", doc.student, linked_updates, update_modified=False)
		updated += 1

	frappe.db.commit()
	return {"updated": updated}
