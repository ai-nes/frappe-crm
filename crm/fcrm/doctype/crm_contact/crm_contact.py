import frappe
from frappe.model.document import Document

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
				"label": "Enrollment Status",
				"type": "Link",
				"key": "enrollment_status",
				"options": "CRM Enrollment Status",
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
			"enrollment_status",
			"assigned_to",
			"modified",
		]
		return {"columns": columns, "rows": rows}

	@staticmethod
	def default_kanban_settings():
		return {
			"title_field": "full_name",
			"kanban_fields": '["name", "full_name", "phone", "email", "enrollment_status", "assigned_to"]',
		}

	def before_insert(self):
		self._set_defaults()
		self._normalize_shared_fields()
		self._sync_fields_from_student_if_blank()
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
		self._normalize_shared_fields()
		self._sync_fields_from_student_if_blank()
		if self.province:
			self.province = resolve_province(self.province)
		if self.high_school:
			self.high_school = resolve_high_school(self.high_school, self.province)

	def after_insert(self):
		self._auto_create_student()

	def on_update(self):
		self._sync_student_fields()

	def validate(self):
		self._normalize_shared_fields()
		self._validate_unique_phone()
		self._validate_unique_email()

	def _validate_unique_phone(self):
		if not self.phone:
			return
		existing = frappe.db.get_value(
			"CRM Contact",
			{"phone": self.phone, "name": ("!=", self.name or "")},
			["name", "full_name"],
			as_dict=True,
		)
		if existing:
			frappe.throw(
				f"Số điện thoại <b>{self.phone}</b> đã tồn tại trong liên hệ "
				f'<a href="/crm/contacts/{existing.name}">{existing.full_name}</a>',
				title="Số điện thoại trùng",
			)
		existing_student = frappe.db.get_value(
			"CRM Student",
			{"phone": self.phone, "name": ("!=", self.student or "")},
			["name", "student_name"],
			as_dict=True,
		)
		if existing_student:
			frappe.throw(
				f"Số điện thoại <b>{self.phone}</b> đã tồn tại ở học sinh "
				f'<a href="/crm/crm-students/{existing_student.name}">{existing_student.student_name}</a>',
				title="Số điện thoại trùng",
			)

	def _validate_unique_email(self):
		if not self.email:
			return
		existing = frappe.db.get_value(
			"CRM Contact",
			{"email": self.email, "name": ("!=", self.name or "")},
			["name", "full_name"],
			as_dict=True,
		)
		if existing:
			frappe.throw(
				f"Email <b>{self.email}</b> đã tồn tại trong liên hệ "
				f'<a href="/crm/contacts/{existing.name}">{existing.full_name}</a>',
				title="Email trùng",
			)
		existing_student = frappe.db.get_value(
			"CRM Student",
			{"email": self.email, "name": ("!=", self.student or "")},
			["name", "student_name"],
			as_dict=True,
		)
		if existing_student:
			frappe.throw(
				f"Email <b>{self.email}</b> đã tồn tại ở học sinh "
				f'<a href="/crm/crm-students/{existing_student.name}">{existing_student.student_name}</a>',
				title="Email trùng",
			)

	def _normalize_shared_fields(self):
		if isinstance(self.phone, str):
			self.phone = self.phone.strip()
		if isinstance(self.email, str):
			self.email = self.email.strip().lower()

	def _sync_fields_from_student_if_blank(self):
		if not self.student:
			return

		student_values = frappe.db.get_value(
			"CRM Student",
			self.student,
			[
				"student_name",
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
		field_map = {
			"full_name": student_values.get("student_name"),
			"phone": student_values.get("phone"),
			"email": student_values.get("email"),
			"high_school": student_values.get("high_school"),
			"province": student_values.get("province"),
			"major": student_values.get("major"),
			"aspiration": student_values.get("aspiration"),
			"source": student_values.get("source"),
			"admission_year": student_values.get("admission_year"),
			"branch": student_values.get("branch"),
			"enrollment_status": student_values.get("enrollment_status"),
		}
		for fieldname, value in field_map.items():
			if not self.get(fieldname) and value:
				self.set(fieldname, value)

	def _auto_create_student(self):
		if self.student:
			return
		if not self.phone:
			return
		if frappe.db.exists("CRM Student", {"phone": self.phone}):
			return
		student = frappe.new_doc("CRM Student")
		student.student_name = self.full_name
		student.phone = self.phone
		student.email = self.email
		student.enrollment_status = self.enrollment_status
		student.high_school = self.high_school
		student.province = self.province
		student.major = self.major
		student.aspiration = self.aspiration
		student.branch = self.branch
		student.admission_year = self.admission_year
		student.source = self.source
		student.alt_name = self.parent_name
		student.alt_phone = self.parent_phone
		student.insert(ignore_permissions=True)
		frappe.db.set_value("CRM Contact", self.name, "student", student.name, update_modified=False)

	def _sync_student_fields(self):
		if not self.student:
			return

		student_values = frappe.db.get_value(
			"CRM Student",
			self.student,
			[
				"student_name",
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
			"student_name": self.full_name or "",
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
		updates = {fieldname: value for fieldname, value in target_values.items() if student_values.get(fieldname) != value}
		if updates:
			frappe.db.set_value("CRM Student", self.student, updates, update_modified=False)

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
