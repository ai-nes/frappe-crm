import frappe
from frappe.model.document import Document

from crm.fcrm.doctype.service_level_agreement.utils import get_sla
from crm.fcrm.utils.geo_resolver import resolve_high_school, resolve_province


class CRMContact(Document):
	@staticmethod
	def default_list_data():
		columns = [
			{
				"label": "Full Name",
				"type": "Data",
				"key": "full_name",
				"width": "16rem",
			},
			{
				"label": "Phone",
				"type": "Data",
				"key": "phone",
				"width": "10rem",
			},
			{
				"label": "Email",
				"type": "Data",
				"key": "email",
				"width": "14rem",
			},
			{
				"label": "Stage",
				"type": "Select",
				"key": "stage",
				"width": "10rem",
			},
			{
				"label": "Assigned To",
				"type": "Link",
				"key": "assigned_to",
				"options": "CRM Staff",
				"width": "12rem",
			},
			{
				"label": "Last Modified",
				"type": "Datetime",
				"key": "modified",
				"width": "8rem",
			},
		]
		rows = [
			"name",
			"full_name",
			"phone",
			"email",
			"stage",
			"assigned_to",
			"modified",
		]
		return {"columns": columns, "rows": rows}

	@staticmethod
	def default_kanban_settings():
		return {
			"title_field": "full_name",
			"kanban_fields": '["name", "full_name", "phone", "email", "assigned_to"]',
		}

	def before_insert(self):
		self._set_defaults()
		self._normalize_phone()
		self._sync_phone_from_student_if_blank()
		if self.province:
			self.province = resolve_province(self.province)
		if self.high_school:
			self.high_school = resolve_high_school(self.high_school, self.province)

	def _set_defaults(self):
		if not self.admission_year:
			current_year = str(frappe.utils.now_datetime().year)
			if frappe.db.exists("CRM Admission Year", current_year):
				self.admission_year = current_year
		if not self.branch:
			default_branch = frappe.db.get_value("CRM Campus", {"is_default": 1}, "name")
			if default_branch:
				self.branch = default_branch

	def before_save(self):
		self._normalize_phone()
		if self.province:
			self.province = resolve_province(self.province)
		if self.high_school:
			self.high_school = resolve_high_school(self.high_school, self.province)

	def on_update(self):
		self._sync_student_mobile_no()

	def validate(self):
		self.apply_sla()

	def _normalize_phone(self):
		if isinstance(self.phone, str):
			self.phone = self.phone.strip()

	def _sync_phone_from_student_if_blank(self):
		if not self.student or self.phone:
			return

		self.phone = frappe.db.get_value("CRM Student", self.student, "mobile_no")

	def _sync_student_mobile_no(self):
		if not self.student:
			return

		mobile_no = self.phone or ""
		current_mobile_no = frappe.db.get_value("CRM Student", self.student, "mobile_no") or ""
		if current_mobile_no != mobile_no:
			frappe.db.set_value(
				"CRM Student",
				self.student,
				"mobile_no",
				mobile_no,
				update_modified=False,
			)

	def apply_sla(self):
		if not self.communication_status:
			self.communication_status = "Open"

		sla = get_sla(self)
		if not sla:
			self.sla = None
			return

		self.sla = sla.name
		frappe.get_doc("Service Level Agreement", sla.name).apply(self)


def get_permission_query_conditions(user=None):
	if not user:
		user = frappe.session.user

	if "System Manager" in frappe.get_roles(user) or "CRM Manager" in frappe.get_roles(user):
		return None

	crm_staff_name = frappe.db.get_value("CRM Staff", {"user": user}, "name")
	if not crm_staff_name:
		return "1=0"

	campus = frappe.db.get_value("CRM Staff", crm_staff_name, "campus")
	if not campus:
		return "1=0"

	crm_staff_in_campus = frappe.db.get_all(
		"CRM Staff",
		filters={"campus": campus},
		pluck="name",
	)

	if not crm_staff_in_campus:
		return "1=0"

	escaped = ", ".join(frappe.db.escape(s) for s in crm_staff_in_campus)
	return f"`tabCRM Contact`.assigned_to in ({escaped})"
