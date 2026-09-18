"""Coverage for automatic Admission Offering resolution."""

from __future__ import annotations

import uuid

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.admission_application import _resolve_offering


class TestAdmissionOfferingResolution(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._cleanup = []

	def tearDown(self):
		for doctype, name in reversed(self._cleanup):
			if frappe.db.exists(doctype, name):
				frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)

	def _catalog(self):
		year = frappe.db.get_value("CRM Admission Year", {}, "name")
		campus = frappe.db.get_value("CRM Campus", {}, "name")
		major = frappe.db.get_value("CRM Major", {}, "name")
		if not all((year, campus, major)):
			self.skipTest("Admission catalog fixtures are required")
		return year, campus, major

	def test_resolver_creates_and_reuses_active_offering(self):
		year, campus, major = self._catalog()
		method = frappe.get_doc(
			{
				"doctype": "CRM Admission Method",
				"code": f"AUTO_OFFERING_{uuid.uuid4().hex[:8].upper()}",
				"display_name": "Automatic offering test method",
			}
		).insert(ignore_permissions=True)
		self._cleanup.append(("CRM Admission Method", method.name))

		student = frappe._dict(admission_year=year, branch=campus, major=major)
		values = {"admission_method": method.name}
		_resolve_offering(student, values)

		offering = frappe.get_doc("CRM Admission Offering", values["offering"])
		self._cleanup.append(("CRM Admission Offering", offering.name))
		self.assertEqual(offering.status, "Active")
		self.assertEqual(offering.admission_year, year)
		self.assertEqual(offering.campus, campus)
		self.assertEqual(offering.major, major)
		self.assertEqual(offering.admission_method, method.name)

		second_values = {"admission_method": method.name}
		_resolve_offering(student, second_values)
		self.assertEqual(second_values["offering"], offering.name)
