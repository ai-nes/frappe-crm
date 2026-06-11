import frappe
from frappe import _
from frappe.model.document import Document

from crm.fcrm.utils.geo_resolver import resolve_high_school, resolve_province, resolve_ward


class CRMStudent(Document):
	def before_insert(self):
		self._set_defaults()
		self._normalize_phone_fields()
		self._resolve_geo()

	def before_save(self):
		self._normalize_phone_fields()
		self._resolve_geo()

	def on_update(self):
		self._sync_linked_contact_fields()

	def _set_defaults(self):
		if not self.admission_year:
			current_year = str(frappe.utils.now_datetime().year)
			if frappe.db.exists("CRM Admission Year", current_year):
				self.admission_year = current_year
		if not self.branch:
			default_branch = frappe.db.get_value("CRM Campus", {"is_default": 1}, "name")
			if default_branch:
				self.branch = default_branch

	def _resolve_geo(self):
		if self.province:
			self.province = resolve_province(self.province)
		if self.high_school:
			self.high_school = resolve_high_school(self.high_school, self.province)
		if self.ward:
			self.ward = resolve_ward(self.ward, self.province)

	def _normalize_phone_fields(self):
		phone = self.phone if isinstance(getattr(self, "phone", None), str) else (self.phone or "")
		mobile_no = self.mobile_no if isinstance(self.mobile_no, str) else (self.mobile_no or "")
		phone = phone.strip() if isinstance(phone, str) else phone
		mobile_no = mobile_no.strip() if isinstance(mobile_no, str) else mobile_no
		canonical_phone = phone or mobile_no
		self.phone = canonical_phone
		self.mobile_no = canonical_phone
		if isinstance(self.email, str):
			self.email = self.email.strip().lower()

	def _sync_linked_contact_fields(self):
		contact_name = frappe.db.get_value("CRM Contact", {"student": self.name}, "name")
		if not contact_name:
			return

		contact_values = frappe.db.get_value(
			"CRM Contact",
			contact_name,
			[
				"full_name",
				"phone",
				"email",
				"high_school",
				"province",
				"major",
				"aspiration",
				"source",
				"admission_year",
				"branch",
				"enrollment_status",
			],
			as_dict=True,
		) or {}
		target_values = {
			"full_name": self.student_name or "",
			"phone": self.phone or "",
			"email": self.email or "",
			"high_school": self.high_school,
			"province": self.province,
			"major": self.major,
			"aspiration": self.aspiration,
			"source": self.source,
			"admission_year": self.admission_year,
			"branch": self.branch,
			"enrollment_status": self.enrollment_status,
		}
		updates = {fieldname: value for fieldname, value in target_values.items() if contact_values.get(fieldname) != value}
		if updates:
			frappe.db.set_value("CRM Contact", contact_name, updates, update_modified=False)

	@staticmethod
	def default_list_data():
		columns = [
			{
				"label": "Student Name",
				"type": "Data",
				"key": "student_name",
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
				"label": "Enrollment Status",
				"type": "Link",
				"key": "enrollment_status",
				"options": "CRM Enrollment Status",
				"width": "12rem",
			},
			{
				"label": "Latest Score",
				"type": "Float",
				"key": "latest_score",
				"width": "8rem",
			},
			{
				"label": "Source",
				"type": "Link",
				"key": "source",
				"options": "CRM Lead Source",
				"width": "10rem",
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
			"student_name",
			"phone",
			"email",
			"enrollment_status",
			"latest_score",
			"source",
			"converted",
			"modified",
		]
		return {"columns": columns, "rows": rows}


@frappe.whitelist()
def convert_to_contact(student_name):
	student = frappe.get_doc("CRM Student", student_name)

	if student.converted:
		existing_contact = frappe.db.get_value("CRM Contact", {"student": student.name}, "name")
		if existing_contact:
			return existing_contact

	crm_staff_name = frappe.db.get_value("CRM Staff", {"user": frappe.session.user}, "name")

	contact = frappe.get_doc({
		"doctype": "CRM Contact",
		"full_name": student.student_name,
		"phone": student.phone,
		"email": student.email,
		"high_school": student.high_school,
		"province": student.province,
		"major": student.major,
		"aspiration": student.aspiration,
		"source": student.source,
		"admission_year": student.admission_year,
		"branch": student.branch,
		"student": student.name,
		"assigned_to": crm_staff_name,
		"enrollment_status": student.enrollment_status or "Mới",
		"lead_status": "Mới",
	})
	contact.insert(ignore_permissions=True)

	student.db_set("converted", 1)
	student.db_set("enrollment_status", "Đã chuyển đổi")

	return contact.name


@frappe.whitelist()
def create_from_contact(contact):
	contact_doc = frappe.get_doc("Contact", contact)

	if not contact_doc.has_permission("read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	if not frappe.has_permission("CRM Student", "create"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	student = frappe.get_doc({
		"doctype": "CRM Student",
		"student_name": contact_doc.full_name or contact_doc.name,
		"phone": contact_doc.mobile_no,
		"mobile_no": contact_doc.mobile_no,
		"email": contact_doc.email_id,
		"enrollment_status": "Mới",
	})
	student.insert()
	return student.name
