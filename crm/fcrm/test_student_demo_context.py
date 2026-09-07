"""Contract checks for the redacted Student Detail demo projection."""

from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from crm.fcrm.student_context import _demo_context


class TestStudentDemoContext(FrappeTestCase):
	def test_demo_context_exposes_display_fields_without_attribution_identifiers(self):
		attribution = {
			"touchpoints": [
				{
					"campaign": "Open Day 2026",
					"source": "Open Day invitation",
					"touched_at": "2026-08-20 09:00:00",
					"reference_doctype": "CRM Marketing Engagement",
					"reference_docname": "CMP-PRIVATE",
				},
				{
					"campaign": "Open Day 2026",
					"event": "Open Day HCM",
					"status": "Checked-in",
					"touched_at": "2026-08-24 08:00:00",
					"reference_doctype": "CRM Marketing Engagement",
					"reference_docname": "EVT-PRIVATE",
				},
			]
		}
		with (
			patch(
				"crm.fcrm.student_context._scholarship_interest",
				return_value={"label": "Scholarship", "notes": "Mục tiêu học bổng: 50%"},
			),
			patch(
				"crm.fcrm.student_context._next_action",
				return_value={"title": "Follow-up hồ sơ", "due_date": "2026-08-28"},
			),
		):
			context = _demo_context("STU-1", attribution)

		self.assertEqual(context["campaign"]["label"], "Open Day 2026")
		self.assertEqual(context["event"]["status"], "Checked-in")
		self.assertEqual(context["scholarship"]["notes"], "Mục tiêu học bổng: 50%")
		self.assertEqual(context["next_action"]["summary"], "Follow-up hồ sơ")
		self.assertEqual([item["summary"] for item in context["activity"]], ["Checked in at Open Day HCM"])
		self.assertNotIn("reference_docname", str(context))
		self.assertNotIn("reference_doctype", str(context))

	def test_demo_context_omits_superseded_attribution_rows(self):
		with (
			patch("crm.fcrm.student_context._scholarship_interest", return_value=None),
			patch("crm.fcrm.student_context._next_action", return_value=None),
		):
			context = _demo_context(
				"STU-1",
				{
					"touchpoints": [
						{"campaign": "Old campaign", "touched_at": "2026-08-20", "superseded": True},
					]
				},
			)

		self.assertIsNone(context["campaign"])
		self.assertEqual(context["activity"], [])
