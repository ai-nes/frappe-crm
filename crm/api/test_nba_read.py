"""Regression coverage for the read-only NBA listing APIs.

list_recommendations previously filtered on fields (``student``, ``status``)
that do not exist on CRM Recommendation -- the real fields are ``target_id``
and ``lifecycle_status`` -- causing a 500 on every real call with a student
or status filter. This locks the corrected field mapping in place.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from crm.api import nba_read
from crm.fcrm.test_permissions import TestSharedScopingPermissions


class TestNbaReadRecommendations(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._campus = TestSharedScopingPermissions._make_campus(self, "_Test NbaRead Campus")
		self._department = TestSharedScopingPermissions._get_or_create_department(
			self, "_Test NbaRead Dept", self._campus
		)
		self._sale_user, self._sale_staff = TestSharedScopingPermissions._make_user_and_staff(
			self, "_Test NbaRead Sale", roles=["Sale"]
		)
		phone = "0" + "".join(str((int(c, 16) + 1) % 10) for c in frappe.generate_hash(length=9))
		self._student = frappe.get_doc({"doctype": "CRM Student", "student_name": "_Test NbaRead Student", "phone": phone})
		previous = getattr(frappe.flags, "student_intake_service", False)
		frappe.flags.student_intake_service = True
		try:
			self._student.insert(ignore_permissions=True)
		finally:
			frappe.flags.student_intake_service = previous
		self._rec = frappe.get_doc(
			{
				"doctype": "CRM Recommendation",
				"recommendation_id": "REC-" + frappe.generate_hash(length=18),
				"target_type": "CRM Student",
				"target_id": self._student.name,
				"action": "CALL",
				"reason": "Silent for nine days.",
				"priority": "high",
				"channel": "CALL",
				"recommended_at": now_datetime(),
				"lifecycle_status": "proposed",
				"decision_status": "pending",
			}
		)
		self._rec.flags.ignore_links = True
		self._rec.insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.delete_doc("CRM Recommendation", self._rec.name, force=True)
		frappe.delete_doc("CRM Student", self._student.name, force=True)
		frappe.delete_doc("CRM Staff", self._sale_staff, force=True)
		frappe.delete_doc("User", self._sale_user, force=True)
		frappe.delete_doc("CRM Department", self._department, force=True)
		frappe.delete_doc("CRM Campus", self._campus, force=True)

	def test_filters_by_student_and_status_without_500(self):
		result = nba_read.list_recommendations(student=self._student.name, status="proposed")
		names = [row["name"] for row in result["rows"]]
		self.assertIn(self._rec.name, names)

	def test_status_filter_excludes_other_lifecycle_states(self):
		result = nba_read.list_recommendations(student=self._student.name, status="completed")
		names = [row["name"] for row in result["rows"]]
		self.assertNotIn(self._rec.name, names)
