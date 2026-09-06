# Keep the workspace module available as a package attribute for callers that
# patch or import it through ``crm.api.lead_sales_workspace``. Frappe's lazy
# module loading can otherwise leave that dotted target unresolved in tests.
from importlib import import_module

import frappe
from bs4 import BeautifulSoup
from frappe import _
from frappe.core.api.file import get_max_file_size
from frappe.translate import get_all_translations
from frappe.utils import cstr, split_emails, validate_email_address

lead_sales_workspace = import_module("crm.api.lead_sales_workspace")
from crm.api.session import get_session_role_flags
from crm.fcrm.role_policy import CANONICAL_SELECTABLE_ROLES
from crm.utils import is_frappe_version


@frappe.whitelist(allow_guest=True)
def get_translations():
	language = None
	if frappe.session.user != "Guest":
		language = frappe.db.get_value("User", frappe.session.user, "language")

	language = language or frappe.db.get_single_value("System Settings", "language") or "vi"
	return get_all_translations(language)


@frappe.whitelist()
def get_user_signature():
	user = frappe.session.user
	user_email_signature = (
		frappe.db.get_value(
			"User",
			user,
			"email_signature",
		)
		if user
		else None
	)

	signature = user_email_signature or frappe.db.get_value(
		"Email Account",
		{"default_outgoing": 1, "add_signature": 1},
		"signature",
	)

	if not signature:
		return

	soup = BeautifulSoup(signature, "html.parser")
	html_signature = soup.find("div", {"class": "ql-editor read-mode"})
	_signature = None
	if html_signature:
		_signature = html_signature.renderContents()
	content = ""
	if cstr(_signature) or signature:
		content = f'<br><p class="signature">{signature}</p>'
	return content


def check_app_permission():
	if frappe.session.user == "Administrator":
		return True

	allowed_modules = []

	if is_frappe_version("15"):
		allowed_modules = frappe.config.get_modules_from_all_apps_for_user()
	elif is_frappe_version("16", above=True):
		from frappe.utils.modules import get_modules_from_all_apps_for_user

		allowed_modules = get_modules_from_all_apps_for_user()

	allowed_modules = [x["module_name"] for x in allowed_modules]
	if "FCRM" not in allowed_modules:
		return False

	try:
		return bool(get_session_role_flags()["is_crm_user"])
	except frappe.PermissionError:
		return False


@frappe.whitelist(allow_guest=True)
def accept_invitation(key: str | None = None):
	if not key:
		frappe.throw(_("Invalid or expired key"))

	result = frappe.db.get_all("Invitation", filters={"key": key}, pluck="name")
	if not result:
		frappe.throw(_("Invalid or expired key"))
	invitation = frappe.get_doc("Invitation", result[0])
	invitation.accept()
	invitation.reload()

	if invitation.status == "Accepted":
		frappe.local.login_manager.login_as(invitation.email)
		frappe.local.response["type"] = "redirect"
		frappe.local.response["location"] = "/crm"


@frappe.whitelist()
def invite_by_email(emails: str, role: str):
	session_roles = get_session_role_flags()

	if role not in CANONICAL_SELECTABLE_ROLES:
		frappe.throw(_("Cannot invite for this role"), frappe.PermissionError)
	if not session_roles["is_system_manager"]:
		frappe.throw(_("You are not allowed to invite this CRM profile"), frappe.PermissionError)

	if not emails:
		return
	email_string = validate_email_address(emails, throw=False)
	email_list = split_emails(email_string)
	if not email_list:
		return
	existing_members = frappe.db.get_all("User", filters={"email": ["in", email_list]}, pluck="email")
	existing_invites = frappe.db.get_all(
		"Invitation",
		filters={
			"email": ["in", email_list],
			"status": "Pending",
		},
		pluck="email",
	)

	to_invite = list(set(email_list) - set(existing_members) - set(existing_invites))

	for email in to_invite:
		frappe.get_doc(doctype="Invitation", email=email, role=role).insert(ignore_permissions=True)

	return {
		"existing_members": existing_members,
		"existing_invites": existing_invites,
		"to_invite": to_invite,
	}


@frappe.whitelist(methods=["DELETE", "POST"])
def delete_attachment(doctype: str, docname: str, file_url: str):
	if not frappe.has_permission(doctype, doc=docname, ptype="write"):
		frappe.throw(_("You don't have permission to delete this attachment"), frappe.PermissionError)

	file_name = frappe.db.get_value(
		"File",
		{"file_url": file_url, "attached_to_doctype": doctype, "attached_to_name": docname},
		"name",
	)
	if file_name:
		frappe.delete_doc("File", file_name)


@frappe.whitelist()
def get_file_uploader_defaults(doctype: str):
	max_number_of_files = None
	make_attachments_public = False
	if doctype:
		meta = frappe.get_meta(doctype)
		max_number_of_files = meta.get("max_attachments")
		make_attachments_public = meta.get("make_attachments_public")

	return {
		"allowed_file_types": frappe.get_system_settings("allowed_file_extensions"),
		"max_file_size": get_max_file_size(),
		"max_number_of_files": max_number_of_files,
		"make_attachments_public": bool(make_attachments_public),
	}
