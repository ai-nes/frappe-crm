# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.student_dashboard import get_student_dashboard


class TestStudentDashboardEvents(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.campus = self._make_campus("_Test SD Campus")
		self.campaign = self._make_campaign("_Test SD Campaign", self.campus)

	def tearDown(self):
		for name in frappe.db.get_all(
			"CRM Marketing Engagement", filters={"engagement_kind": "event_participation", "crm_event": ["like", "_Test SD%"]}, pluck="name"
		):
			frappe.delete_doc("CRM Marketing Engagement", name, force=True)
		for name in frappe.db.get_all("CRM Contact", filters={"full_name": ["like", "_Test SD%"]}, pluck="name"):
			frappe.delete_doc("CRM Contact", name, force=True)
		for name in frappe.db.get_all("CRM Student", filters={"student_name": ["like", "_Test SD%"]}, pluck="name"):
			frappe.delete_doc("CRM Student", name, force=True)
		for name in frappe.db.get_all("CRM Event", filters={"title": ["like", "_Test SD%"]}, pluck="name"):
			frappe.delete_doc("CRM Event", name, force=True)
		for name in frappe.db.get_all("CRM Campaign", filters={"title": ["like", "_Test SD%"]}, pluck="name"):
			frappe.delete_doc("CRM Campaign", name, force=True)
		for name in frappe.db.get_all("CRM Campus", filters={"campus_name": ["like", "_Test SD%"]}, pluck="name"):
			frappe.delete_doc("CRM Campus", name, force=True)

	def _make_campus(self, name):
		if frappe.db.exists("CRM Campus", name):
			frappe.delete_doc("CRM Campus", name, force=True)
		doc = frappe.get_doc({"doctype": "CRM Campus", "campus_name": name})
		doc.insert(ignore_permissions=True)
		return doc.name

	def _make_campaign(self, title, campus):
		if frappe.db.exists("CRM Campaign", title):
			frappe.delete_doc("CRM Campaign", title, force=True)
		doc = frappe.get_doc({"doctype": "CRM Campaign", "title": title, "campus": campus})
		doc.insert(ignore_permissions=True)
		return doc.name

	def _make_student(self, name, phone):
		student = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"student_name": name,
				"phone": phone,
				"enrollment_status": "PROSPECT",
			}
		)
		previous_intake_flag = getattr(frappe.flags, "student_intake_service", False)
		frappe.flags.student_intake_service = True
		try:
			student.insert(ignore_permissions=True)
		finally:
			frappe.flags.student_intake_service = previous_intake_flag
		return student.name

	def _make_event(self, title, start_datetime="2026-09-01 10:00:00", event_date=None):
		fields = {
			"doctype": "CRM Event",
			"title": title,
			"crm_campaign": self.campaign,
		}
		if start_datetime:
			fields["start_datetime"] = start_datetime
		if event_date:
			fields["event_date"] = event_date
		doc = frappe.get_doc(fields)
		doc.insert(ignore_permissions=True)
		return doc.name

	def _make_contact(self, full_name, phone, crm_event=None, student=None):
		fields = {
			"doctype": "CRM Contact",
			"full_name": full_name,
			"phone": phone,
		}
		if crm_event:
			fields["crm_event"] = crm_event
		if student:
			fields["student"] = student
		doc = frappe.get_doc(fields)
		doc.insert(ignore_permissions=True)
		return doc.name

	def test_dashboard_requires_an_authenticated_session(self):
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				get_student_dashboard(phone="0987000099")
		finally:
			frappe.set_user("Administrator")

	def test_events_mapping_reads_canonical_participation(self):
		event_name = self._make_event("_Test SD Legacy Event", event_date="2026-09-10")
		student = self._make_student("_Test SD Canonical Student", "0987000001")
		contact_name = self._make_contact("_Test SD Canonical Contact", "0987000001", student=student)
		participation = frappe.get_doc({
			"doctype": "CRM Marketing Engagement", "engagement_kind": "event_participation",
			"reference_doctype": "CRM Event", "reference_name": event_name,
			"crm_event": event_name, "crm_contact": contact_name, "student": student,
			"status": "Checked-in",
		})
		participation.insert(ignore_permissions=True)

		try:
			result = get_student_dashboard(phone="0987000001")
			self.assertTrue(result["isSuccess"])
			event_items = result["data"]["events"]["items"]
			self.assertEqual(len(event_items), 1)
			self.assertEqual(event_items[0]["id"], event_name)
			self.assertEqual(event_items[0]["status"], "attended")
		finally:
			frappe.delete_doc("CRM Marketing Engagement", participation.name, force=True)
			frappe.delete_doc("CRM Contact", contact_name, force=True)
			frappe.delete_doc("CRM Event", event_name, force=True)

	def test_events_mapping_returns_only_canonical_participation(self):
		participation_event = self._make_event("_Test SD Participation Event", start_datetime="2026-09-20 09:00:00")
		student = self._make_student("_Test SD Participation Student", "0987000002")
		contact_name = self._make_contact(
			"_Test SD Participation Contact", "0987000002", student=student
		)

		participation = frappe.get_doc(
			{
				"doctype": "CRM Marketing Engagement",
				"engagement_kind": "event_participation",
				"reference_doctype": "CRM Event",
				"reference_name": participation_event,
				"crm_event": participation_event,
				"crm_contact": contact_name,
				"student": student,
				"status": "Checked-in",
			}
		)
		participation.insert(ignore_permissions=True)

		try:
			result = get_student_dashboard(phone="0987000002")
			event_items = result["data"]["events"]["items"]
			event_ids = [item["id"] for item in event_items]

			self.assertIn(participation_event, event_ids)

			matched = next(item for item in event_items if item["id"] == participation_event)
			self.assertEqual(matched["status"], "attended")
		finally:
			frappe.delete_doc("CRM Marketing Engagement", participation.name, force=True)
			frappe.delete_doc("CRM Contact", contact_name, force=True)
			frappe.delete_doc("CRM Event", participation_event, force=True)

	def test_events_mapping_maps_feedback_given_status(self):
		event_name = self._make_event("_Test SD Feedback Event", start_datetime="2026-09-25 09:00:00")
		student = self._make_student("_Test SD Feedback Student", "0987000003")
		contact_name = self._make_contact("_Test SD Feedback Contact", "0987000003", student=student)

		participation = frappe.get_doc(
			{
				"doctype": "CRM Marketing Engagement",
				"engagement_kind": "event_participation",
				"reference_doctype": "CRM Event",
				"reference_name": event_name,
				"crm_event": event_name,
				"crm_contact": contact_name,
				"student": student,
				"status": "Checked-in",
			}
		)
		participation.insert(ignore_permissions=True)
		# Attribution evidence is append-only in production; update the fixture
		# directly to exercise the dashboard mapping for this stored status.
		frappe.db.set_value(
			"CRM Marketing Engagement", participation.name, "status", "Feedback Given", update_modified=False
		)

		try:
			result = get_student_dashboard(phone="0987000003")
			event_items = result["data"]["events"]["items"]
			matched = next(item for item in event_items if item["id"] == event_name)
			self.assertEqual(matched["status"], "feedback_given")
		finally:
			frappe.delete_doc("CRM Marketing Engagement", participation.name, force=True)
			frappe.delete_doc("CRM Contact", contact_name, force=True)
			frappe.delete_doc("CRM Event", event_name, force=True)

	def test_suggested_events_prefer_start_datetime_over_event_date(self):
		event_name = self._make_event(
			"_Test SD Suggested Event", start_datetime="2026-12-01 08:00:00", event_date="2026-11-01"
		)
		contact_name = self._make_contact("_Test SD Suggested Contact", "0987000004")

		try:
			result = get_student_dashboard(phone="0987000004")
			suggested_items = result["data"]["suggestedEvents"]["items"]
			matched = next((item for item in suggested_items if item["id"] == event_name), None)
			self.assertIsNotNone(matched)

			expected_start = frappe.utils.get_datetime("2026-12-01 08:00:00")
			from crm.api.student_dashboard import to_unix

			self.assertEqual(matched["startsAt"], to_unix(expected_start))
		finally:
			frappe.delete_doc("CRM Contact", contact_name, force=True)
			frappe.delete_doc("CRM Event", event_name, force=True)
