import frappe
from frappe import _
from frappe.auth import LoginAttemptTracker
from frappe.rate_limiter import rate_limit
from frappe.utils.password import check_password, update_password

from crm.fcrm.role_policy import CANONICAL_SELECTABLE_ROLES, CRM_BUSINESS_ROLES

CRM_MANAGED_ROLES = CANONICAL_SELECTABLE_ROLES


def _require_crm_role_manager():
	"""Allow role mutations only through the canonical session authority."""
	from crm.api.session import get_session_role_flags

	if get_session_role_flags()["is_system_manager"]:
		return True
	frappe.throw(_("Only System Managers may change CRM users."), frappe.PermissionError)


def set_canonical_crm_profile(user_doc, new_role: str):
	"""Replace CRM business aliases atomically while preserving unrelated roles."""
	if new_role not in CRM_MANAGED_ROLES:
		frappe.throw(_("Cannot assign this role"), frappe.ValidationError)
	if new_role == "System Manager":
		remove_roles(user_doc, *CRM_BUSINESS_ROLES)
		user_doc.append_roles("System Manager")
		user_doc.set("block_modules", [])
		return
	remove_roles(user_doc, "System Manager", *CRM_BUSINESS_ROLES)
	user_doc.append_roles(new_role)
	update_module_in_user(user_doc, "FCRM")


def _can_assign_role(is_system_manager: bool, new_role: str) -> bool:
	"""Only System Managers may create a new canonical profile assignment."""
	return is_system_manager and new_role in CRM_MANAGED_ROLES


def _can_manage_target(is_system_manager: bool, target_roles) -> bool:
	"""Prevent a legacy Sales Manager from demoting another business profile."""
	if is_system_manager:
		return True
	business_roles = set(target_roles) & CRM_BUSINESS_ROLES
	return not business_roles


def _can_remove_target(is_system_manager: bool, target_roles) -> bool:
	"""A legacy Sales Manager may never remove an administrator's CRM access."""
	roles = set(target_roles)
	return _can_manage_target(is_system_manager, roles) and (
		is_system_manager or "System Manager" not in roles
	)


@frappe.whitelist()
@rate_limit(limit=5, seconds=300)  # 5 attempts per 5 minutes per user/IP
def change_password(old_password: str, new_password: str):
	"""
	Change password for the current logged-in user.
	Uses Frappe's LoginAttemptTracker for attempt counting/lockout, and rate_limit for API abuse protection.
	"""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("You must be logged in to change your password"), frappe.AuthenticationError)

	tracker = LoginAttemptTracker(user)
	if not tracker.is_user_allowed():
		frappe.throw(_("Too many failed attempts. Please try again after some time."))

	if old_password == new_password:
		frappe.throw(
			_("New password cannot be the same as current password. Please choose a different password.")
		)

	try:
		check_password(user, old_password)
	except frappe.AuthenticationError:
		tracker.add_failure_attempt()
		frappe.throw(_("Incorrect current password. Please try again."))
	else:
		tracker.add_success_attempt()

	# Validate new password strength (server-side enforcement)
	from frappe.core.doctype.user.user import test_password_strength

	result = test_password_strength(new_password)
	feedback = result.get("feedback", {})
	if not feedback.get("password_policy_validation_passed", False):
		suggestions = feedback.get("suggestions", [])
		frappe.throw(_("Password is too weak. {0}").format(" ".join(suggestions) if suggestions else ""))

	update_password(user=user, pwd=new_password, logout_all_sessions=False)
	return _("Password Updated Successfully")


@frappe.whitelist()
def add_existing_users(users: str | list, role: str = "Sale"):
	"""
	Add existing users to the CRM by assigning a canonical role.
	:param users: List of user names to be added
	"""
	is_system_manager = _require_crm_role_manager()
	if not _can_assign_role(is_system_manager, role):
		frappe.throw(_("Only System Managers may assign this CRM profile."), frappe.PermissionError)

	users = frappe.parse_json(users)

	for user in users:
		update_user_role(user, role)


@frappe.whitelist()
def update_user_role(user: str, new_role: str):
	"""
	Replace a user's CRM business profile without granting extra permissions.
	"""

	is_system_manager = _require_crm_role_manager()
	if not _can_assign_role(is_system_manager, new_role):
		frappe.throw(_("Only System Managers may assign this CRM profile."), frappe.PermissionError)

	user_doc = frappe.get_doc("User", user)
	target_roles = [d.role for d in user_doc.roles]
	target_is_system_manager = "System Manager" in target_roles
	if not _can_manage_target(is_system_manager, target_roles):
		frappe.throw(_("Only System Managers may modify this CRM user."), frappe.PermissionError)

	if target_is_system_manager and new_role != "System Manager":
		frappe.throw(
			_("Remove System Manager access separately before changing this user"), frappe.PermissionError
		)
	if user == frappe.session.user and new_role != "System Manager":
		frappe.throw(_("You cannot remove your own System Manager access."), frappe.PermissionError)

	set_canonical_crm_profile(user_doc, new_role)

	user_doc.save(ignore_permissions=True)


@frappe.whitelist()
def remove_crm_roles_from_user(user: str):
	"""
	Remove a user by clearing their CRM business roles.
	:param user: The name of the user to be removed
	"""
	is_system_manager = _require_crm_role_manager()

	if user == frappe.session.user:
		frappe.throw(_("You cannot remove yourself."), frappe.PermissionError)

	user_doc = frappe.get_doc("User", user)
	roles = [d.role for d in user_doc.roles]
	if not _can_remove_target(is_system_manager, roles):
		frappe.throw(_("Only System Managers may remove this CRM user."), frappe.PermissionError)

	if user_doc.get("role_profiles") or user_doc.get("role_profile_name"):
		return frappe.throw(
			_("User {0} cannot be removed as it has a Role Profile assigned to it.").format(user)
		)

	remove_roles(user_doc, *CRM_BUSINESS_ROLES)
	if "System Manager" in roles:
		remove_roles(user_doc, "System Manager")
		update_module_in_user(user_doc, "FCRM")

	user_doc.save(ignore_permissions=True)
	frappe.msgprint(_("User {0} has been removed from CRM roles.").format(user))


def remove_roles(self, *roles):
	existing_roles = {d.role: d for d in self.get("roles")}
	for role in roles:
		if role in existing_roles:
			self.get("roles").remove(existing_roles[role])


def update_module_in_user(user, module):
	block_modules = frappe.get_all(
		"Module Def",
		fields=["name as module"],
		filters={"name": ["!=", module]},
	)

	if block_modules:
		user.set("block_modules", block_modules)
