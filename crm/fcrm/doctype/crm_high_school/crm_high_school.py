# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from crm.fcrm.school_domain_permissions import (
	has_school_portfolio_permission,
	school_portfolio_condition,
)


class CRMHighSchool(Document):
	_DEPENDENT_DOCTYPES = (
		"CRM Contact",
		"CRM High School Annual Snapshot",
		"CRM High School Assignment",
		"CRM School Activity",
		"CRM School Analysis Run",
		"CRM School Contact",
		"CRM School Intelligence Revision Journal",
		"CRM School Relationship",
		"CRM School Stakeholder",
		"CRM Student",
		"CRM Student Geography Snapshot",
	)

	def before_validate(self):
		self._sync_canonical_geography()

	def validate(self):
		self._validate_geography()
		self._validate_business_identity()
		self._validate_key_account_governance()
		self._sync_derived_key_account()

	def on_trash(self):
		for doctype in self._DEPENDENT_DOCTYPES:
			if not frappe.db.exists("DocType", doctype):
				continue
			if frappe.db.exists(doctype, {"high_school": self.name}):
				frappe.throw(
					"Cannot delete this High School: it is referenced by {0}. "
					"Deactivate or re-point the dependent records first.".format(doctype),
					frappe.ValidationError,
				)

	def _sync_canonical_geography(self):
		if self.ward and frappe.db.exists("CRM Ward", self.ward):
			ward_province = frappe.db.get_value("CRM Ward", self.ward, "province")
			if not self.province:
				self.province = ward_province

	def _validate_geography(self):
		if self.province and self.ward:
			ward_province = frappe.db.get_value("CRM Ward", self.ward, "province")
			if ward_province and ward_province != self.province:
				frappe.throw("The selected ward must belong to the selected province.", frappe.ValidationError)

	def _validate_business_identity(self):
		if not (self.province and self.ward and self.school_code):
			return
		filters = {"school_code": self.school_code, "province": self.province, "ward": self.ward}
		if not self.is_new():
			filters["name"] = ["!=", self.name]
		if frappe.db.exists("CRM High School", filters):
			frappe.throw("A school with the same province, ward and school code already exists.", frappe.DuplicateEntryError)

	def _sync_derived_key_account(self):
		"""Project the latest annual eligibility without accepting manual input."""
		if not frappe.db.exists("DocType", "CRM High School Annual Snapshot"):
			return
		rows = frappe.get_all(
			"CRM High School Annual Snapshot",
			filters={"high_school": self.name, "verification_status": "Verified", "period_type": "Annual"},
			fields=["admission_year", "ne_actual", "adjusted_ne_threshold", "key_account_eligible", "snapshot_date"],
			order_by="admission_year desc, snapshot_date desc, revision desc",
			limit_page_length=1,
		)
		if not rows:
			self.is_key_account = 0
			return
		snapshot = rows[0]
		if snapshot.ne_actual in (None, "") or snapshot.adjusted_ne_threshold in (None, ""):
			self.is_key_account = 0
			return
		self.is_key_account = int(bool(snapshot.key_account_eligible))

	def _validate_key_account_governance(self):
		if not self.get_doc_before_save() or frappe.session.user in {"Administrator"}:
			return
		roles = set(frappe.get_roles(frappe.session.user))
		if not roles & {"Promoter"}:
			return
		previous = self.get_doc_before_save()
		if any(
			previous.get(fieldname) != self.get(fieldname)
			for fieldname in ("key_account_tier", "key_account_owner", "key_account_team")
		):
			frappe.throw("Promoters cannot change key-account governance fields.", frappe.PermissionError)

	@staticmethod
	def default_list_data():
		columns = [
			{
				"label": "School Name",
				"type": "Data",
				"key": "school_name",
				"width": "20rem",
			},
			{
				"label": "School Type",
				"type": "Link",
				"key": "school_type",
				"options": "CRM School Type",
				"width": "10rem",
			},
			{
				"label": "Area",
				"type": "Select",
				"key": "school_area",
				"width": "8rem",
			},
			{
				"label": "Province",
				"type": "Link",
				"key": "province",
				"options": "CRM Province",
				"width": "12rem",
			},
			{
				"label": "Ward",
				"type": "Link",
				"key": "ward",
				"options": "CRM Ward",
				"width": "14rem",
			},
			{
				"label": "Key Account",
				"type": "Check",
				"key": "is_key_account",
				"width": "8rem",
			},
			{
				"label": "Owner",
				"type": "Link",
				"key": "key_account_owner",
				"options": "CRM Staff",
				"width": "12rem",
			},
			{
				"label": "Address",
				"type": "Small Text",
				"key": "address",
				"width": "20rem",
			},
		]
		rows = [
			"name",
			"school_name",
			"school_type",
			"school_area",
			"province",
			"ward",
			"is_key_account",
			"key_account_owner",
			"address",
			"modified",
		]
		return {"columns": columns, "rows": rows}


# Module-level permission hooks (registered in hooks.py). Kept out of the
# Document subclass so they never shadow Document.has_permission, which would
# bypass the ignore_permissions guard and mis-bind permtype as the doc arg.
def get_permission_query_conditions(user=None, doctype=None):
	if doctype not in (None, "CRM High School"):
		return "1=0"
	return school_portfolio_condition("CRM High School", user)


def has_permission(doc, user=None, permission_type=None, ptype=None):
	return has_school_portfolio_permission(doc, user, permission_type, ptype)
