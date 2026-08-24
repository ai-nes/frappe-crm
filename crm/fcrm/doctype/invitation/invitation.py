# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


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
		role: DF.Literal["", "Sale", "Marketing", "Lead Sales", "Admissions Director", "System Manager"]
		status: DF.Literal["", "Pending", "Accepted", "Expired"]
	# end: auto-generated types

	def before_insert(self):
		frappe.utils.validate_email_address(self.email, True)

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
		frappe.only_for("System Manager", True)
		self.accept()

	def _lock_pending_row(self, key=None):
		"""Lock and validate this invitation before any account mutation.

		The guest endpoint and a concurrent replay can otherwise both load a
		Pending document and login as the invited user.  A row lock plus a
		Pending/key check makes acceptance a one-shot state transition.
		"""
		rows = frappe.db.sql(
			"""
			SELECT status, `key`
			FROM `tabInvitation`
			WHERE name = %s
			FOR UPDATE
			""",
			(self.name,),
			as_dict=True,
		)
		row = rows[0] if rows else None
		if not row or row.status != "Pending" or (key is not None and row.key != key):
			frappe.throw(_("Invalid or expired key"))

	def accept(self, key=None):
		self._lock_pending_row(key)
		from crm.api.user import _set_single_crm_role

		user = self.create_user_if_not_exists()
		if self.role != "System Manager" and "System Manager" in frappe.get_roles(user.name):
			frappe.throw(_("A System Manager account cannot be downgraded by an invitation."), frappe.PermissionError)
		# Replace the canonical CRM role instead of appending it.  This keeps one
		# business role per account and prevents permission union/escalation when
		# an existing user accepts a new invitation.
		_set_single_crm_role(user, self.role)
		if self.role != "System Manager":
			self.update_module_in_user(user, "FCRM")
		user.save(ignore_permissions=True)

		self.status = "Accepted"
		self.accepted_at = frappe.utils.now()
		# The bearer link is a one-time secret; never retain it after acceptance.
		self.key = None
		self.save(ignore_permissions=True)

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
