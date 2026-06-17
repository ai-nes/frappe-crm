import re

import frappe
from frappe import _
from frappe.model.document import Document

from crm.fcrm.utils.geo_resolver import (
	resolve_high_school_strict,
	resolve_province,
	resolve_ward,
)


class CRMStudent(Document):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		# Frappe's _validate_links() runs before before_insert/before_save/validate
		# and throws its own generic error for any Link field holding free-text
		# input (e.g. high_school/province/ward from a Data Import row), before our
		# resolvers ever get a chance to run. We disable it here and re-run it
		# ourselves at the end of validate(), once geo fields are resolved.
		self.flags.ignore_links = True

	def before_insert(self):
		self._set_defaults()
		self._normalize_phone_fields()
		self._resolve_geo()

	def before_save(self):
		self._normalize_phone_fields()
		self._resolve_geo()
		if self.cohort_end_year:
			self.cohort_start_year = int(self.cohort_end_year) - 3

	def validate(self):
		self._validate_phone_format()
		self._resolve_geo()
		self._validate_high_school_format()
		self._validate_unique_phone()
		self._validate_unique_email()
		self._validate_unique_id_number()
		self.flags.ignore_links = False
		self._validate_links()

	def _validate_high_school_format(self):
		if not self.high_school:
			return
		self.high_school = resolve_high_school_strict(self.high_school, self.province)

	def _validate_phone_format(self):
		if not self.phone:
			return
		phone = self.phone.strip()
		if phone.startswith("+84"):
			phone = "0" + phone[3:]
		self.phone = phone
		if not re.fullmatch(r"0\d{9}", phone):
			frappe.throw(
				f"Số điện thoại <b>{phone}</b> không hợp lệ. Số điện thoại phải gồm đúng 10 số.",
				title="Số điện thoại không hợp lệ",
			)

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
		# high_school is intentionally NOT resolved here — _validate_high_school_format()
		# is the single source of truth for it (resolve_high_school_strict), called right
		# after this in validate(). Resolving it twice would be wasted work whose result
		# gets discarded.
		if self.province:
			self.province = resolve_province(self.province)
		if self.ward:
			self.ward = resolve_ward(self.ward, self.province)

	def _normalize_phone_fields(self):
		if isinstance(self.phone, str):
			self.phone = self.phone.strip()
		if isinstance(self.email, str):
			self.email = self.email.strip().lower()
		if isinstance(self.id_number, str):
			self.id_number = self.id_number.strip()

	def _validate_unique_phone(self):
		if not self.phone:
			return
		existing_student = frappe.db.get_value(
			"CRM Student",
			{"phone": self.phone, "name": ("!=", self.name or "")},
			["name", "student_name"],
			as_dict=True,
		)
		if existing_student:
			frappe.throw(
				f"Số điện thoại <b>{self.phone}</b> đã tồn tại ở học sinh "
				f'<a href="/crm/crm-students/{existing_student.name}">{existing_student.student_name}</a>',
				title="Số điện thoại trùng",
			)
		existing_contact = frappe.db.get_value(
			"CRM Contact",
			{"phone": self.phone, "student": ("!=", self.name or "")},
			["name", "full_name"],
			as_dict=True,
		)
		if existing_contact:
			frappe.throw(
				f"Số điện thoại <b>{self.phone}</b> đã tồn tại trong liên hệ "
				f'<a href="/crm/contacts/{existing_contact.name}">{existing_contact.full_name}</a>',
				title="Số điện thoại trùng",
			)

	def _validate_unique_email(self):
		if not self.email:
			return
		existing_student = frappe.db.get_value(
			"CRM Student",
			{"email": self.email, "name": ("!=", self.name or "")},
			["name", "student_name"],
			as_dict=True,
		)
		if existing_student:
			frappe.throw(
				f"Email <b>{self.email}</b> đã tồn tại ở học sinh "
				f'<a href="/crm/crm-students/{existing_student.name}">{existing_student.student_name}</a>',
				title="Email trùng",
			)
		existing_contact = frappe.db.get_value(
			"CRM Contact",
			{"email": self.email, "student": ("!=", self.name or "")},
			["name", "full_name"],
			as_dict=True,
		)
		if existing_contact:
			frappe.throw(
				f"Email <b>{self.email}</b> đã tồn tại trong liên hệ "
				f'<a href="/crm/contacts/{existing_contact.name}">{existing_contact.full_name}</a>',
				title="Email trùng",
			)

	def _validate_unique_id_number(self):
		if not self.id_number:
			return
		existing = frappe.db.get_value(
			"CRM Student",
			{"id_number": self.id_number, "name": ("!=", self.name or "")},
			["name", "student_name"],
			as_dict=True,
		)
		if existing:
			frappe.throw(
				f"Số CCCD <b>{self.id_number}</b> đã tồn tại ở học sinh "
				f'<a href="/crm/crm-students/{existing.name}">{existing.student_name}</a>',
				title="Số CCCD trùng",
			)

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
				"parent_name",
				"parent_phone",
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
			"parent_name": self.alt_name,
			"parent_phone": self.alt_phone,
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
			"source",
			"modified",
		]
		return {"columns": columns, "rows": rows}


@frappe.whitelist()
def convert_to_contact(student_name):
	student = frappe.get_doc("CRM Student", student_name)

	existing_contact = frappe.db.get_value("CRM Contact", {"student": student.name}, "name")
	if existing_contact:
		if student.enrollment_status != "Có triển vọng":
			student.db_set("enrollment_status", "Có triển vọng")
		frappe.db.set_value(
			"CRM Contact", existing_contact, "enrollment_status", "Có triển vọng", update_modified=False
		)
		return existing_contact

	if not student.phone:
		frappe.throw(_("Student must have a phone number before converting to a contact."))

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
		"enrollment_status": "Có triển vọng",
		"lead_status": "Mới",
		"parent_name": student.alt_name,
		"parent_phone": student.alt_phone,
	})
	contact.insert(ignore_permissions=True)

	student.db_set("enrollment_status", "Có triển vọng")

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
		"phone": contact_doc.get("phone"),
		"email": contact_doc.email_id,
		"enrollment_status": "Mới",
	})
	student.insert()
	return student.name
