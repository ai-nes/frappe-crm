import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.student_import import upsert_student


class TestStudentImport(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._ensure_master_data()

	def tearDown(self):
		for doctype, filters in (
			("CRM Student", {"student_name": ["like", "_Test Inbound%"]}),
			("CRM High School", {"school_code": "TINB-HS"}),
			("CRM Province", {"province_name": "_Test Inbound Province"}),
			("CRM Province", {"province_name": "_Test Inbound Other Province"}),
			("CRM Campus", {"campus_name": "_Test Inbound Campus"}),
			("CRM Major", {"major_name": "_Test Inbound Major"}),
			("CRM Aspiration", {"aspiration_name": "_Test Inbound Aspiration"}),
			("CRM Admission Year", {"year_name": "2099"}),
			("CRM Lead Source", {"source_name": "_Test Inbound Source"}),
		):
			for name in frappe.get_all(doctype, filters=filters, pluck="name"):
				frappe.delete_doc(doctype, name, force=True)
		frappe.set_user("Administrator")

	def test_creates_student_from_payload_and_preserves_unmapped_fields(self):
		result = upsert_student(self._payload())

		self.assertEqual(result["action"], "created")
		student = frappe.get_doc("CRM Student", result["name"])
		self.assertEqual(student.student_name, "_Test Inbound An Nguyen")
		self.assertEqual(student.phone, "0901234567")
		self.assertEqual(student.email, "inbound@example.com")
		self.assertEqual(student.branch, "_Test Inbound Campus")
		self.assertEqual(student.province, "_Test Inbound Province")
		self.assertEqual(student.high_school, "_Test Inbound High School")
		self.assertEqual(student.major, "_Test Inbound Major")
		self.assertEqual(student.aspiration, "_Test Inbound Aspiration")
		self.assertEqual(student.admission_year, "2099")
		self.assertEqual(student.source, "_Test Inbound Source")
		self.assertEqual(student.enrollment_status, "Mới")
		self.assertEqual(student.advertising_channel, "Facebook")
		self.assertEqual(
			student.notes,
			"Thông tin bổ sung từ nguồn tích hợp:\n- ID người phụ trách: 19x1\n- Công ty: Example Co",
		)

	def test_retries_update_the_same_student(self):
		first = upsert_student(self._payload())
		payload = self._payload(lastname="Updated")
		second = upsert_student(payload)

		self.assertEqual(second, {"name": first["name"], "action": "updated"})
		self.assertEqual(frappe.db.count("CRM Student", {"phone": "0901234567"}), 1)
		self.assertEqual(
			frappe.db.get_value("CRM Student", first["name"], "student_name"), "_Test Inbound Updated"
		)

	def test_resolves_high_school_from_school_code(self):
		self._ensure(
			"CRM Province",
			{"province_name": "_Test Inbound Other Province", "province_code": "OTHR"},
		)
		self._ensure(
			"CRM High School",
			{
				"school_name": "_Test Inbound Other High School",
				"school_code": "TINB-HS",
				"province_name": "_Test Inbound Other Province",
				"province_code": "OTHR",
			},
		)
		payload = self._payload()
		payload.pop("cf_school")
		payload["cf_school_code"] = "TINB-HS"

		result = upsert_student(payload)

		self.assertEqual(frappe.db.get_value("CRM Student", result["name"], "high_school"), "TINB-HS - TINB")

	def test_guest_can_create_a_student(self):
		frappe.set_user("Guest")
		try:
			result = upsert_student(self._payload())
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(result["action"], "created")
		self.assertTrue(frappe.db.exists("CRM Student", result["name"]))

	def test_rejects_payload_when_phone_and_email_belong_to_different_students(self):
		upsert_student(self._payload())
		upsert_student(self._payload(mobile="0907654321", email="other@example.com", lastname="Other"))

		with self.assertRaises(frappe.ValidationError):
			upsert_student(self._payload(email="other@example.com"))

	def _payload(self, **overrides):
		payload = {
			"firstname": "_Test Inbound",
			"lastname": "An Nguyen",
			"mobile": "0901234567",
			"email": "inbound@example.com",
			"leadsource": "_Test Inbound Source",
			"leads_campus": "test_inbound_campus",
			"cf_city": "_Test Inbound Province",
			"cf_school": "_Test Inbound High School",
			"cf_major": "TINB",
			"cf_nvfpt": "_Test Inbound Aspiration",
			"cf_registered_year": "2099",
			"leadstatus": "New",
			"cf_kenh_quang_cao": "Facebook",
			"assigned_user_id": "19x1",
			"company": "Example Co",
		}
		payload.update(overrides)
		return payload

	def _ensure_master_data(self):
		self._ensure(
			"CRM Enrollment Status",
			{"status_name": "Mới", "stage_category": "open", "lifecycle_stage": "Lead"},
		)
		self._ensure("CRM Lead Source", {"source_name": "_Test Inbound Source"})
		self._ensure("CRM Province", {"province_name": "_Test Inbound Province", "province_code": "TINB"})
		self._ensure(
			"CRM Campus", {"campus_name": "_Test Inbound Campus", "campus_code": "test_inbound_campus"}
		)
		self._ensure("CRM Major", {"major_name": "_Test Inbound Major", "major_code": "TINB"})
		self._ensure("CRM Aspiration", {"aspiration_name": "_Test Inbound Aspiration"})
		self._ensure("CRM Admission Year", {"year_name": "2099"})
		self._ensure(
			"CRM High School",
			{
				"school_name": "_Test Inbound High School",
				"school_code": "TINB-HS",
				"province_name": "_Test Inbound Province",
				"province_code": "TINB",
			},
		)

	def _ensure(self, doctype, values):
		fieldname, value = next(iter(values.items()))
		if not frappe.db.exists(doctype, {fieldname: value}):
			frappe.get_doc({"doctype": doctype, **values}).insert(ignore_permissions=True)
