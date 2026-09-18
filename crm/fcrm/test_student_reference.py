from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.student_reference import canonical_student, lead_for_reference


class TestStudentReference(FrappeTestCase):
	def test_display_code_resolves_directly_to_legacy_named_student(self):
		with patch.object(frappe.db, "exists", return_value=False), patch.object(
			frappe, "get_all", return_value=[
				{"name": "CRMC-2026-002284", "lead_code": None, "admission_year": "2026"}
			]
		):
			self.assertEqual(canonical_student("HS-2026-HCM-002284"), "CRMC-2026-002284")

	def test_display_code_resolves_to_lead(self):
		def exists(doctype, name):
			return doctype == "CRM Lead" and name == "ENR-2026-00021"

		with patch.object(frappe.db, "exists", side_effect=exists), patch.object(
			frappe.db, "get_value", return_value=None
		):
			self.assertEqual(
				lead_for_reference("CRM HS-2026-HCM-000021"),
				"ENR-2026-00021",
			)

	def test_display_code_resolves_to_canonical_student(self):
		def exists(doctype, name):
			if doctype == "CRM Student":
				return name == "CRMC-2026-00060"
			return doctype == "CRM Lead" and name == "ENR-2026-00021"

		def get_value(doctype, name, fields, **_kwargs):
			if doctype == "CRM Lead" and name == "ENR-2026-00021" and isinstance(fields, list):
				return {"converted_student": None, "student": "CRMC-2026-00060"}
			return None

		with patch.object(frappe.db, "exists", side_effect=exists), patch.object(
			frappe.db, "get_value", side_effect=get_value
		), patch.object(frappe, "get_all", return_value=[]):
			self.assertEqual(canonical_student("HS-2026-HCM-000021"), "CRMC-2026-00060")
