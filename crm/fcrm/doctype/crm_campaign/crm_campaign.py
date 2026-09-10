import frappe
from frappe import _
from frappe.model.document import Document

from crm.fcrm.campaign_code import (
	campaign_code_date,
	next_campaign_code,
	normalize_campus_code,
)


class CRMCampaign(Document):
	def before_insert(self):
		# Campaign code is server-managed, just like Lead code.
		self.stable_code = None
		if not self.owner_staff:
			self.owner_staff = frappe.db.get_value("CRM Staff", {"user": frappe.session.user}, "name")

	def after_insert(self):
		self._ensure_campaign_code()
		frappe.db.set_value("CRM Campaign", self.name, "stable_code", self.stable_code, update_modified=False)

	def before_save(self):
		before = self.get_doc_before_save()
		if before and before.get("stable_code") and self.get("stable_code") != before.get("stable_code"):
			frappe.throw(
				_("Campaign Code is immutable after creation."),
				frappe.ValidationError,
			)

	def _ensure_campaign_code(self):
		if self.get("stable_code"):
			return
		campus_code = frappe.db.get_value("CRM Campus", self.get("campus"), "campus_code")
		if not campus_code:
			frappe.throw(
				_("Campus Code is required before creating a Campaign."),
				frappe.ValidationError,
			)
		try:
			normalized_campus_code = normalize_campus_code(campus_code)
		except ValueError as error:
			frappe.throw(_(str(error)), frappe.ValidationError)
		code_date = campaign_code_date(self.get("creation"), frappe.utils.now_datetime())
		code = next_campaign_code(normalized_campus_code, code_date)
		while frappe.db.exists("CRM Campaign", {"stable_code": code, "name": ["!=", self.name]}):
			code = next_campaign_code(normalized_campus_code, code_date)
		self.stable_code = code

	@staticmethod
	def default_list_data():
		columns = [
			{"label": "Campaign Code", "type": "Data", "key": "stable_code", "width": "12rem"},
			{"label": "Title", "type": "Data", "key": "title", "width": "16rem"},
			{"label": "Campus", "type": "Link", "key": "campus", "options": "CRM Campus", "width": "12rem"},
			{"label": "Campaign Type", "type": "Link", "key": "campaign_type", "options": "CRM Campaign Type", "width": "12rem"},
			{"label": "Status", "type": "Select", "key": "status", "width": "8rem"},
			{"label": "Owner", "type": "Link", "key": "owner_staff", "options": "CRM Staff", "width": "10rem"},
			{"label": "Start Date", "type": "Date", "key": "start_date", "width": "10rem"},
			{"label": "Last Modified", "type": "Datetime", "key": "modified", "width": "8rem"},
		]
		rows = [
			"name",
			"stable_code",
			"title",
			"campus",
			"campaign_type",
			"status",
			"owner_staff",
			"start_date",
			"modified",
		]
		return {"columns": columns, "rows": rows}
