import frappe
from frappe.model.document import Document

from crm.fcrm.role_policy import LEGACY_OVERLAY_ROLES, clear_permission_profile_cache


class CRMPermissionProfile(Document):
	def validate(self):
		if not self.applicable_doctypes:
			frappe.throw("A permission profile must have at least one applicable DocType row.")
		if not self.is_new():
			previous_role = frappe.db.get_value("CRM Permission Profile", self.name, "role")
			if previous_role and previous_role != self.role:
				frappe.throw("The Role on an existing permission profile cannot be changed.")

	def on_update(self):
		clear_permission_profile_cache(self.role)


def get_permission_query_conditions(user=None):
	"""Desk list-view declutter only -- never used for access control.

	Legacy/compatibility-overlay role profiles (e.g. the Vietnamese
	"Giám đốc Tuyển sinh") still have to exist so `case_scope_for_roles()`
	resolves correctly for any account still holding that role name; this
	only keeps them out of the profile list so admins see the roles the
	product actually requires. `case_scope_for_roles()` reads a profile with
	`frappe.db.get_value`/`frappe.get_doc`, neither of which applies this
	condition, so it never affects live permission resolution.
	"""
	if not LEGACY_OVERLAY_ROLES:
		return ""
	roles = ", ".join(frappe.db.escape(role) for role in LEGACY_OVERLAY_ROLES)
	return f"`tabCRM Permission Profile`.`role` not in ({roles})"
