import frappe
from frappe.tests.utils import FrappeTestCase
from unittest.mock import patch

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

	def test_legacy_route_requires_authentication(self):
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				upsert_student(self._payload())
		finally:
			frappe.set_user("Administrator")

	def test_authenticated_legacy_route_requires_signed_command_identity(self):
		with self.assertRaises(frappe.ValidationError):
			upsert_student(self._payload())

	def test_authenticated_route_delegates_only_to_canonical_intake(self):
		with patch("crm.api.student_import.submit_intake", return_value={"outcome": "created", "student": "CRM-STU-1"}) as intake:
			result = upsert_student(
				self._payload(source_record_id="legacy-1", idempotency_key="idem-1")
			)
		self.assertEqual(result["action"], "created")
		self.assertEqual(result["name"], "CRM-STU-1")
		intake.assert_called_once()

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
