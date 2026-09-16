import frappe
from frappe import _
from frappe.auth import LoginAttemptTracker
from frappe.rate_limiter import rate_limit
from frappe.utils.password import check_password, update_password

from crm.fcrm.role_policy import (
	BUSINESS_ADMIN_ROLE,
	CANONICAL_SELECTABLE_ROLES,
	CRM_BUSINESS_ROLES,
	DESK_MANAGEMENT_ROLE_NAMES,
)

CRM_MANAGED_ROLES = CANONICAL_SELECTABLE_ROLES


@frappe.whitelist()
def get_all_roles():
	"""Expose the CRM Administrator profile in the User role selector.

	Frappe normally hides ``Administrator`` as an automatic role and exposes
	``System Manager``.  CRM uses Administrator as the visible control profile,
	so keep the technical role out of this business-facing selector.
	"""
	from frappe.core.doctype.user.user import get_all_roles as frappe_get_all_roles

	roles = set(frappe_get_all_roles())
	roles.discard("System Manager")
	roles.discard(BUSINESS_ADMIN_ROLE)
	roles.add("Administrator")
	return sorted(roles)


def _current_canonical_role(target_roles) -> str | None:
	"""Return the single canonical CRM role a user currently holds, if any."""
	if "System Manager" in target_roles:
		return "System Manager"
	matches = [role for role in target_roles if role in CRM_MANAGED_ROLES]
	return matches[0] if len(matches) == 1 else None


def _log_role_change(user: str, action: str, previous_role: str | None, new_role: str | None):
	"""Record a role change/removal. Called only after the mutation already saved."""
	frappe.get_doc(
		{
			"doctype": "CRM User Role Log",
			"user": user,
			"action": action,
			"previous_role": previous_role,
			"new_role": new_role,
		}
	).insert(ignore_permissions=True)


@frappe.whitelist()
def list_user_role_logs(user: str | None = None, start: int = 0, page_length: int = 50) -> dict:
	"""List role-change audit log rows, optionally filtered by target user."""
	_require_crm_role_manager()
	start = int(start or 0)
	page_length = min(int(page_length or 50), 200)
	filters = {"user": user} if user else {}
	logs = frappe.get_list(
		"CRM User Role Log",
		filters=filters,
		fields=["name", "user", "action", "previous_role", "new_role", "owner", "creation"],
		order_by="creation desc",
		start=start,
		page_length=page_length,
	)
	total = frappe.db.count("CRM User Role Log", filters=filters)
	return {"logs": logs, "total": total, "start": start, "page_length": page_length}


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
		remove_roles(user_doc, BUSINESS_ADMIN_ROLE, *CRM_BUSINESS_ROLES)
		user_doc.append_roles("System Manager", *DESK_MANAGEMENT_ROLE_NAMES)
		user_doc.set("block_modules", [])
		return
	remove_roles(
		user_doc,
		"System Manager",
		*DESK_MANAGEMENT_ROLE_NAMES,
		BUSINESS_ADMIN_ROLE,
		*CRM_BUSINESS_ROLES,
	)
	user_doc.append_roles(new_role)
	update_module_in_user(user_doc, "FCRM")


def _can_assign_role(is_system_manager: bool, new_role: str) -> bool:
	"""Only System Managers may create a new canonical profile assignment."""
	return is_system_manager and new_role in CRM_MANAGED_ROLES


def _can_manage_target(is_system_manager: bool, target_roles) -> bool:
	"""Prevent a non-administrator from demoting another business profile."""
	if is_system_manager:
		return True
	business_roles = set(target_roles) & CRM_BUSINESS_ROLES
	return not business_roles


def _can_remove_target(is_system_manager: bool, target_roles) -> bool:
	"""A non-administrator may never remove an administrator's CRM access."""
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
	_assert_password_strength(new_password)

	update_password(user=user, pwd=new_password, logout_all_sessions=False)
	return _("Password Updated Successfully")


def _assert_password_strength(password: str):
	from frappe.core.doctype.user.user import test_password_strength

	result = test_password_strength(password)
	feedback = result.get("feedback", {})
	if not feedback.get("password_policy_validation_passed", False):
		suggestions = feedback.get("suggestions", [])
		frappe.throw(_("Password is too weak. {0}").format(" ".join(suggestions) if suggestions else ""))


@frappe.whitelist()
def create_crm_user(email: str, full_name: str, password: str, role: str = "Sale"):
	"""Create a new CRM user with an immediate login password (no email invite)."""
	is_system_manager = _require_crm_role_manager()
	if not _can_assign_role(is_system_manager, role):
		frappe.throw(_("Only System Managers may assign this CRM profile."), frappe.PermissionError)

	email = (email or "").strip()
	full_name = (full_name or "").strip()
	if not email or not full_name:
		frappe.throw(_("Full name and email are required."), frappe.ValidationError)
	if frappe.db.exists("User", email):
		frappe.throw(_("A user with this email already exists."), frappe.ValidationError)

	_assert_password_strength(password)

	first_name, _sep, last_name = full_name.partition(" ")
	user_doc = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": first_name,
			"last_name": last_name or None,
			"user_type": "System User",
			"enabled": 1,
			"send_welcome_email": 0,
		}
	).insert(ignore_permissions=True)

	set_canonical_crm_profile(user_doc, role)
	user_doc.save(ignore_permissions=True)
	update_password(user=email, pwd=password, logout_all_sessions=True)
	return user_doc.name


@frappe.whitelist()
def update_crm_user_profile(user: str, full_name: str = None, new_password: str = None):
	"""Update a CRM user's display name and/or reset their password."""
	is_system_manager = _require_crm_role_manager()
	user_doc = frappe.get_doc("User", user)
	target_roles = [d.role for d in user_doc.roles]
	if not _can_manage_target(is_system_manager, target_roles):
		frappe.throw(_("Only System Managers may modify this CRM user."), frappe.PermissionError)

	full_name = (full_name or "").strip()
	if full_name:
		first_name, _sep, last_name = full_name.partition(" ")
		user_doc.first_name = first_name
		user_doc.last_name = last_name or None
		user_doc.save(ignore_permissions=True)

	if new_password:
		_assert_password_strength(new_password)
		update_password(user=user, pwd=new_password, logout_all_sessions=True)


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

	previous_role = _current_canonical_role(target_roles)

	set_canonical_crm_profile(user_doc, new_role)

	user_doc.save(ignore_permissions=True)

	_log_role_change(user, "role_changed", previous_role, new_role)


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

	previous_role = _current_canonical_role(roles)

	remove_roles(user_doc, BUSINESS_ADMIN_ROLE, *CRM_BUSINESS_ROLES)
	if "System Manager" in roles:
		remove_roles(user_doc, "System Manager", *DESK_MANAGEMENT_ROLE_NAMES)
		update_module_in_user(user_doc, "FCRM")

	user_doc.save(ignore_permissions=True)

	_log_role_change(user, "removed", previous_role, None)
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
