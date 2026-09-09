# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

"""Coverage for the canonical marketing engagement attribution projection."""

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.attribution import (
	get_campaign_names_by_last_touch,
	get_contact_attribution,
	get_contact_touchpoints,
	get_first_touch,
	get_last_touch,
	get_multi_touch_attribution,
)


class TestAttribution(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.contact_students = {}
		self.campus = self._make_campus("_Test Attr Campus")
		self.campaign_a = self._make_campaign("_Test Attr Campaign A", self.campus)
		self.campaign_b = self._make_campaign("_Test Attr Campaign B", self.campus)

	def tearDown(self):
		for name in frappe.db.get_all(
			"CRM Marketing Engagement", filters={"engagement_kind": "campaign_touch", "crm_campaign": ["in", [self.campaign_a, self.campaign_b]]}, pluck="name"
		):
			frappe.delete_doc("CRM Marketing Engagement", name, force=True)
		for name in frappe.db.get_all(
			"CRM Marketing Engagement",
			filters={"engagement_kind": "event_participation", "crm_event": ["in", frappe.db.get_all("CRM Event", filters={"title": ["like", "_Test Attr%"]}, pluck="name")]},
			pluck="name",
		):
			frappe.delete_doc("CRM Marketing Engagement", name, force=True)
		for name in frappe.db.get_all("CRM Event", filters={"title": ["like", "_Test Attr%"]}, pluck="name"):
			frappe.delete_doc("CRM Event", name, force=True)
		for name in frappe.db.get_all("CRM Student", filters={"full_name": ["like", "_Test Attr%"]}, pluck="name"):
			frappe.delete_doc("CRM Student", name, force=True)
		for name in frappe.db.get_all("CRM Lead", filters={"student_name": ["like", "_Test Attr%"]}, pluck="name"):
			frappe.delete_doc("CRM Lead", name, force=True)
		for name in frappe.db.get_all("CRM Campaign", filters={"title": ["like", "_Test Attr%"]}, pluck="name"):
			frappe.delete_doc("CRM Campaign", name, force=True)
		for name in frappe.db.get_all("CRM Campus", filters={"campus_name": ["like", "_Test Attr%"]}, pluck="name"):
			frappe.delete_doc("CRM Campus", name, force=True)

	# --------------------------------------------------------------- helpers

	def _make_campus(self, name):
		if frappe.db.exists("CRM Campus", name):
			frappe.delete_doc("CRM Campus", name, force=True)
		doc = frappe.get_doc(
			{"doctype": "CRM Campus", "campus_name": name, "campus_code": "TEST-ATTR"}
		)
		doc.insert(ignore_permissions=True)
		return doc.name

	def _make_campaign(self, title, campus):
		if frappe.db.exists("CRM Campaign", title):
			frappe.delete_doc("CRM Campaign", title, force=True)
		doc = frappe.get_doc({"doctype": "CRM Campaign", "title": title, "campus": campus})
		doc.insert(ignore_permissions=True)
		return doc.name

	def _make_event(self, title, campaign, start_datetime="2026-01-01 09:00:00"):
		if frappe.db.exists("CRM Event", title):
			frappe.delete_doc("CRM Event", title, force=True)
		doc = frappe.get_doc(
			{
				"doctype": "CRM Event",
				"title": title,
				"crm_campaign": campaign,
				"start_datetime": start_datetime,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc.name

	def _make_contact(self, name, phone):
		student = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"student_name": f"{name} Student",
				"phone": phone,
				"processing_status": "NEW",
			}
		)
		previous_intake_flag = getattr(frappe.flags, "student_intake_service", False)
		frappe.flags.student_intake_service = True
		try:
			student.insert(ignore_permissions=True)
		finally:
			frappe.flags.student_intake_service = previous_intake_flag
		contact = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"full_name": name,
				"phone": phone,
				"student_stage": "New",
				"student": student.name,
			}
		)
		contact.insert(ignore_permissions=True)
		self.contact_students[contact.name] = student.name
		return contact.name

	def _make_touchpoint(self, contact, campaign, touched_at):
		doc = frappe.get_doc(
			{
				"doctype": "CRM Marketing Engagement",
				"engagement_kind": "campaign_touch",
				"reference_doctype": "CRM Campaign",
				"reference_name": campaign,
				"crm_campaign": campaign,
				"crm_contact": contact,
				"student": self.contact_students[contact],
				"touched_at": touched_at,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc.name

	def _make_participation(self, contact, event, registered_at):
		doc = frappe.get_doc(
			{
				"doctype": "CRM Marketing Engagement",
				"engagement_kind": "event_participation",
				"reference_doctype": "CRM Event",
				"reference_name": event,
				"crm_event": event,
				"crm_contact": contact,
				"student": self.contact_students[contact],
				"registered_at": registered_at,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc.name

	# --------------------------------------------------------------- first/last touch

	def test_first_touch_picks_earliest_across_touchpoint_and_event_participation(self):
		contact = self._make_contact("_Test Attr First Touch Contact", "0966000001")
		event = self._make_event("_Test Attr First Touch Event", self.campaign_b)
		# Earlier: event participation. Later: campaign touchpoint.
		self._make_participation(contact, event, "2026-01-01 08:00:00")
		self._make_touchpoint(contact, self.campaign_a, "2026-01-05 08:00:00")

		first_touch = get_first_touch(contact)
		self.assertIsNotNone(first_touch)
		self.assertEqual(first_touch["campaign"], self.campaign_b)
		self.assertEqual(first_touch["source"], "Event Participation")

	def test_last_touch_picks_most_recent(self):
		contact = self._make_contact("_Test Attr Last Touch Contact", "0966000002")
		event = self._make_event("_Test Attr Last Touch Event", self.campaign_b)
		self._make_touchpoint(contact, self.campaign_a, "2026-01-01 08:00:00")
		self._make_participation(contact, event, "2026-01-10 08:00:00")

		last_touch = get_last_touch(contact)
		self.assertIsNotNone(last_touch)
		self.assertEqual(last_touch["campaign"], self.campaign_b)
		self.assertEqual(last_touch["source"], "Event Participation")

	def test_get_contact_touchpoints_returns_oldest_first(self):
		contact = self._make_contact("_Test Attr Ordering Contact", "0966000003")
		self._make_touchpoint(contact, self.campaign_a, "2026-01-05 08:00:00")
		self._make_touchpoint(contact, self.campaign_b, "2026-01-01 08:00:00")

		touchpoints = get_contact_touchpoints(contact)
		self.assertEqual(len(touchpoints), 2)
		self.assertEqual(touchpoints[0]["campaign"], self.campaign_b)
		self.assertEqual(touchpoints[1]["campaign"], self.campaign_a)

	def test_repeated_exposure_is_preserved_not_destructively_overwritten(self):
		contact = self._make_contact("_Test Attr Repeated Exposure", "0966000010")
		first = self._make_touchpoint(contact, self.campaign_a, "2026-01-01 08:00:00")
		second = self._make_touchpoint(contact, self.campaign_a, "2026-01-02 08:00:00")
		self.assertNotEqual(first, second)
		touchpoints = get_contact_touchpoints(contact)
		self.assertEqual([point["reference_docname"] for point in touchpoints], [first, second])
		self.assertEqual(get_multi_touch_attribution(contact), {self.campaign_a: 1.0})

	# --------------------------------------------------------------- multi-touch

	def test_multi_touch_splits_credit_equally_across_resolvable_touchpoints(self):
		contact = self._make_contact("_Test Attr Multi Touch Contact", "0966000004")
		self._make_touchpoint(contact, self.campaign_a, "2026-01-01 08:00:00")
		self._make_touchpoint(contact, self.campaign_a, "2026-01-02 08:00:00")
		event = self._make_event("_Test Attr Multi Touch Event", self.campaign_b)
		self._make_participation(contact, event, "2026-01-03 08:00:00")

		credit = get_multi_touch_attribution(contact)
		self.assertAlmostEqual(credit[self.campaign_a], 2 / 3)
		self.assertAlmostEqual(credit[self.campaign_b], 1 / 3)
		self.assertAlmostEqual(sum(credit.values()), 1.0)

	def test_multi_touch_excludes_unresolvable_campaign_touchpoints(self):
		contact = self._make_contact("_Test Attr Orphan Contact", "0966000005")
		self._make_touchpoint(contact, self.campaign_a, "2026-01-01 08:00:00")
		event = self._make_event("_Test Attr Orphan Event", self.campaign_b)
		participation_name = self._make_participation(contact, event, "2026-01-02 08:00:00")
		# Simulate an orphaned event->campaign link (e.g. the campaign was
		# deleted elsewhere, leaving a stale/blank crm_campaign on the Event) --
		# crm_campaign is `reqd` on CRM Event so this can't be produced via a
		# normal insert; we bypass validation with a direct db write instead.
		frappe.db.set_value("CRM Event", event, "crm_campaign", "", update_modified=False)

		credit = get_multi_touch_attribution(contact)
		# Only the resolvable touchpoint (campaign_a) gets credit; the
		# unresolvable one is excluded entirely, not counted as a zero-credit
		# member of the denominator.
		self.assertEqual(credit, {self.campaign_a: 1.0})

		# First/last touch must still surface both touchpoints (with
		# campaign=None for the unresolvable one) without erroring.
		touchpoints = get_contact_touchpoints(contact)
		self.assertEqual(len(touchpoints), 2)
		last_touch = get_last_touch(contact)
		self.assertIsNotNone(last_touch)
		self.assertIsNone(last_touch["campaign"])
		self.assertEqual(last_touch["reference_docname"], participation_name)

	# --------------------------------------------------------- last-touch campaign roll-up

	def test_get_campaign_names_by_last_touch_only_returns_contacts_whose_last_touch_matches(self):
		contact = self._make_contact("_Test Attr Last Touch Rollup Contact", "0966000006")
		self._make_touchpoint(contact, self.campaign_a, "2026-01-01 08:00:00")
		self._make_touchpoint(contact, self.campaign_b, "2026-01-05 08:00:00")

		# Contact was touched by campaign_a at some point, but its LAST touch
		# is campaign_b -- must not appear in campaign_a's roll-up.
		self.assertNotIn(contact, get_campaign_names_by_last_touch(self.campaign_a))
		self.assertIn(contact, get_campaign_names_by_last_touch(self.campaign_b))

	def test_get_campaign_names_by_last_touch_empty_for_untouched_campaign(self):
		untouched_campaign = self._make_campaign("_Test Attr Untouched Campaign", self.campus)
		self.assertEqual(get_campaign_names_by_last_touch(untouched_campaign), set())

	# --------------------------------------------------------------- empty state

	def test_empty_touchpoints_return_none_or_empty_without_error(self):
		contact = self._make_contact("_Test Attr Empty Contact", "0966000007")

		self.assertEqual(get_contact_touchpoints(contact), [])
		self.assertIsNone(get_first_touch(contact))
		self.assertIsNone(get_last_touch(contact))
		self.assertEqual(get_multi_touch_attribution(contact), {})

	# --------------------------------------------------------------- whitelisted endpoint

	def test_get_contact_attribution_returns_all_three_views(self):
		contact = self._make_contact("_Test Attr Whitelisted Contact", "0966000008")
		self._make_touchpoint(contact, self.campaign_a, "2026-01-01 08:00:00")

		result = get_contact_attribution(contact)
		self.assertEqual(result["firstTouch"]["campaign"], self.campaign_a)
		self.assertEqual(result["lastTouch"]["campaign"], self.campaign_a)
		self.assertEqual(result["multiTouch"], {self.campaign_a: 1.0})
		self.assertEqual(len(result["touchpoints"]), 1)

	def test_get_contact_attribution_raises_for_nonexistent_contact(self):
		with self.assertRaises(frappe.ValidationError):
			get_contact_attribution("CRM-CONTACT-DOES-NOT-EXIST")
