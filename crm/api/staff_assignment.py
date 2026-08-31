import json

import frappe
from frappe import _


# CRM Student ownership is a domain transition and must go through
# crm.api.student_ownership. Contact assignment remains a legacy-compatible
# operation, but it never writes the linked Student as a side effect.
ASSIGNABLE_DOCTYPES = {"CRM Contact"}
STAFF_ASSIGN_DENIED_ROLES = {"Sale", "CTV-Sale", "Promoter", "Promoter-PR"}
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
		frappe.throw(_("Generic staff assignment is only supported for CRM Contact."), frappe.PermissionError)

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
		updated += 1

	frappe.db.commit()
	return {"updated": updated}
