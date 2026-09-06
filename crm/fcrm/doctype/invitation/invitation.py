# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from crm.fcrm.role_policy import CANONICAL_SELECTABLE_ROLES


class Invitation(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		accepted_at: DF.Datetime | None
		email: DF.Data
		email_sent_at: DF.Datetime | None
		invited_by: DF.Link | None
		key: DF.Data | None
		role: DF.Literal["", "Sale", "Marketing", "Lead Sale", "Admissions Director", "System Manager"]
		status: DF.Literal["", "Pending", "Accepted", "Expired"]
	# end: auto-generated types

	def before_insert(self):
		frappe.utils.validate_email_address(self.email, True)
		self._validate_canonical_role()

		self.key = frappe.generate_hash(length=12)
		self.invited_by = frappe.session.user
		self.status = "Pending"

	def after_insert(self):
		self.invite_via_email()

	def invite_via_email(self):
		invite_link = frappe.utils.get_url(f"/api/method/crm.api.accept_invitation?key={self.key}")
		if frappe.local.dev_server:
			print(f"Invite link for {self.email}: {invite_link}")  # nosemgrep

		title = "Frappe CRM"
		template = "invitation"

		frappe.sendmail(
			recipients=self.email,
			subject=f"You have been invited to join {title}",
			template=template,
			args={"title": title, "invite_link": invite_link},
			now=True,
		)
		self.db_set("email_sent_at", frappe.utils.now())

	@frappe.whitelist()
	def accept_invitation(self):
		from crm.api.session import get_session_role_flags

		if not get_session_role_flags()["is_system_manager"]:
			frappe.throw(_("You are not allowed to accept invitations"), frappe.PermissionError)
		self.accept()

	def accept(self):
		if self.status != "Pending":
			frappe.throw(_("Invalid or expired key"))
		self._validate_canonical_role()

		user = self.create_user_if_not_exists()
		from crm.api.user import set_canonical_crm_profile

		set_canonical_crm_profile(user, self.role)
		user.save(ignore_permissions=True)

		self.status = "Accepted"
		self.accepted_at = frappe.utils.now()
		self.save(ignore_permissions=True)

	def _validate_canonical_role(self):
		if self.role not in CANONICAL_SELECTABLE_ROLES:
			frappe.throw(_("Invitation role must be a canonical CRM role"), frappe.ValidationError)

	def update_module_in_user(self, user, module):
		block_modules = frappe.get_all(
			"Module Def",
			fields=["name as module"],
			filters={"name": ["!=", module]},
		)

		if block_modules:
			user.set("block_modules", block_modules)

	def create_user_if_not_exists(self):
		if not frappe.db.exists("User", self.email):
			first_name = self.email.split("@")[0].title()
			user = frappe.get_doc(
				doctype="User",
				user_type="System User",
				email=self.email,
				send_welcome_email=0,
				first_name=first_name,
			).insert(ignore_permissions=True)
		else:
			user = frappe.get_doc("User", self.email)
		return user


def expire_invitations():
	"""expire invitations after 3 days"""
	from frappe.utils import add_days, now

	days = 3
	invitations_to_expire = frappe.db.get_all(
		"Invitation", filters={"status": "Pending", "creation": ["<", add_days(now(), -days)]}
	)
	for invitation in invitations_to_expire:
		invitation = frappe.get_doc("Invitation", invitation.name)
		invitation.status = "Expired"
		invitation.save(ignore_permissions=True)
