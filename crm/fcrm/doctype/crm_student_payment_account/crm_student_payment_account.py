import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from crm.fcrm.student_profile import (
	PAYMENT_ACCOUNT_PURPOSES,
	PAYMENT_ACCOUNT_VERIFICATION_STATUSES,
	validate_unique_primary_account,
)


class CRMStudentPaymentAccount(Document):
	def before_validate(self):
		self.account_purpose = self.account_purpose or "Other"
		self.verification_status = self.verification_status or "Pending"

	def validate(self):
		if not self.student or not frappe.db.exists("CRM Student", self.student):
			frappe.throw(_("A valid Student is required for a payment account."), frappe.ValidationError)
		if not str(self.bank_name or "").strip() or not str(self.account_number or "").strip():
			frappe.throw(_("Bank name and account number are required."), frappe.ValidationError)
		if not str(self.account_holder_name or "").strip():
			frappe.throw(_("Account holder name is required."), frappe.ValidationError)
		if self.account_purpose not in PAYMENT_ACCOUNT_PURPOSES:
			frappe.throw(_("Payment account purpose is invalid."), frappe.ValidationError)
		if self.verification_status not in PAYMENT_ACCOUNT_VERIFICATION_STATUSES:
			frappe.throw(_("Payment account verification status is invalid."), frappe.ValidationError)
		if self.verification_status == "Verified":
			if not self.verified_by:
				self.verified_by = frappe.session.user
			if not self.verified_at:
				self.verified_at = now_datetime()
		if self.verification_status == "Rejected" and not str(self.rejection_reason or "").strip():
			frappe.throw(_("A rejected payment account requires a reason."), frappe.ValidationError)
		self._validate_guardian_student()
		validate_unique_primary_account(self)

	def _validate_guardian_student(self):
		if not self.guardian:
			return
		guardian_student = frappe.db.get_value("CRM Student Guardian", self.guardian, "student")
		if guardian_student and guardian_student != self.student:
			frappe.throw(
				_("Guardian and payment account must belong to the same Student."), frappe.ValidationError
			)


def get_permission_query_conditions(user=None):
	from crm.fcrm.permissions import get_permission_query_conditions

	condition = get_permission_query_conditions("CRM Student", user=user)
	if condition is None:
		return None
	if condition == "1=0":
		return condition
	return (
		"`tabCRM Student Payment Account`.student in (select `tabCRM Student`.name "
		f"from `tabCRM Student` where ({condition}))"
	)


def has_permission(doc, user=None, permission_type=None, ptype=None):
	student = doc.get("student") if hasattr(doc, "get") else getattr(doc, "student", None)
	if not student:
		return False
	return frappe.has_permission("CRM Student", permission_type or ptype or "read", student, user=user)
