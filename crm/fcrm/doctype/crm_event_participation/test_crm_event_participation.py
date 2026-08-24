# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestCRMEventParticipation(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.campus = self._make_campus("_Test EvtP Campus")
		self.campaign = self._make_campaign("_Test EvtP Campaign", self.campus)
		self.event = self._make_event("_Test EvtP Event", self.campaign)
		self.contact = self._make_contact("_Test EvtP Contact", "0977000001")

	def tearDown(self):
		for name in frappe.db.get_all(
			"CRM Event Participation", filters={"crm_event": self.event}, pluck="name"
		):
			frappe.delete_doc("CRM Event Participation", name, force=True)
		for name in frappe.db.get_all(
			"CRM Interaction", filters={"reference_doctype": "CRM Event Participation"}, pluck="name"
		):
			frappe.delete_doc("CRM Interaction", name, force=True)
		for name in frappe.db.get_all("CRM Contact", filters={"full_name": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Contact", name, force=True)
		for name in frappe.db.get_all("CRM Event", filters={"title": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Event", name, force=True)
		for name in frappe.db.get_all("CRM Campaign", filters={"title": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Campaign", name, force=True)
		for name in frappe.db.get_all("CRM Campus", filters={"campus_name": ["like", "_Test%"]}, pluck="name"):
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

	def _make_event(self, title, campaign):
		if frappe.db.exists("CRM Event", title):
			frappe.delete_doc("CRM Event", title, force=True)
		doc = frappe.get_doc(
			{
				"doctype": "CRM Event",
				"title": title,
				"crm_campaign": campaign,
				"start_datetime": "2026-09-01 09:00:00",
			}
		)
		doc.insert(ignore_permissions=True)
		return doc.name

	def _make_contact(self, name, phone):
		contact = frappe.get_doc(
			{
				"doctype": "CRM Contact",
				"full_name": name,
				"phone": phone,
				"enrollment_status": "Có triển vọng",
			}
		)
		contact.insert(ignore_permissions=True)
		return contact.name

	def _ensure_interaction_type(self, name):
		if not frappe.db.exists("CRM Interaction Type", name):
			frappe.get_doc(
				{"doctype": "CRM Interaction Type", "interaction_type_name": name}
			).insert(ignore_permissions=True)

	def _make_participation(self, **kwargs):
		payload = {
			"doctype": "CRM Event Participation",
			"crm_event": self.event,
			"crm_contact": self.contact,
		}
		payload.update(kwargs)
		return frappe.get_doc(payload)

	# --------------------------------------------------------------- defaults

	def test_before_validate_defaults_student_actor_registered_at(self):
		frappe.set_user("Administrator")
		participation = self._make_participation()
		participation.insert(ignore_permissions=True)
		participation.reload()

		expected_student = frappe.db.get_value("CRM Contact", self.contact, "student")
		self.assertEqual(participation.student, expected_student)
		self.assertEqual(participation.actor, "Administrator")
		self.assertTrue(participation.registered_at)

	def test_explicit_values_are_not_overridden(self):
		participation = self._make_participation(
			actor="Administrator",
			registered_at="2026-01-01 08:00:00",
		)
		participation.insert(ignore_permissions=True)
		participation.reload()
		self.assertEqual(str(participation.registered_at), "2026-01-01 08:00:00")

	def test_checked_in_at_auto_set_when_status_is_checked_in(self):
		participation = self._make_participation(status="Checked-in")
		participation.insert(ignore_permissions=True)
		participation.reload()
		self.assertTrue(participation.checked_in_at)

	# ---------------------------------------------------------- duplicate guard

	def test_duplicate_event_contact_pair_raises(self):
		first = self._make_participation()
		first.insert(ignore_permissions=True)

		duplicate = self._make_participation()
		with self.assertRaises(frappe.ValidationError):
			duplicate.insert(ignore_permissions=True)

	def test_same_contact_different_event_is_allowed(self):
		first = self._make_participation()
		first.insert(ignore_permissions=True)

		other_event = self._make_event("_Test EvtP Other Event", self.campaign)
		second = self._make_participation(crm_event=other_event)
		second.insert(ignore_permissions=True)  # must not raise
		self.assertTrue(second.name)

	# ------------------------------------------------- CRM Interaction dispatch
	# (crm.fcrm.interaction_log.create_interaction_from_event_participation_*)

	def test_insert_fires_registered_interaction(self):
		self._ensure_interaction_type("Registered")

		participation = self._make_participation()
		participation.insert(ignore_permissions=True)

		count = frappe.db.count(
			"CRM Interaction",
			{"reference_doctype": "CRM Event Participation", "reference_docname": participation.name},
		)
		self.assertEqual(count, 1)
		interaction_type = frappe.db.get_value(
			"CRM Interaction",
			{"reference_doctype": "CRM Event Participation", "reference_docname": participation.name},
			"interaction_type",
		)
		self.assertEqual(interaction_type, "Registered")

	def test_status_change_to_checked_in_fires_new_interaction(self):
		self._ensure_interaction_type("Registered")
		self._ensure_interaction_type("Checked-in")

		participation = self._make_participation()
		participation.insert(ignore_permissions=True)

		participation.status = "Checked-in"
		participation.save(ignore_permissions=True)

		checked_in_count = frappe.db.count(
			"CRM Interaction",
			{
				"reference_doctype": "CRM Event Participation",
				"reference_docname": participation.name,
				"interaction_type": "Checked-in",
			},
		)
		self.assertEqual(checked_in_count, 1)

		total_count = frappe.db.count(
			"CRM Interaction",
			{"reference_doctype": "CRM Event Participation", "reference_docname": participation.name},
		)
		self.assertEqual(total_count, 2)  # Registered (insert) + Checked-in (update)

	def test_no_status_change_does_not_refire_interaction(self):
		self._ensure_interaction_type("Registered")

		participation = self._make_participation()
		participation.insert(ignore_permissions=True)

		participation.feedback_notes = "no status change here"
		participation.save(ignore_permissions=True)

		total_count = frappe.db.count(
			"CRM Interaction",
			{"reference_doctype": "CRM Event Participation", "reference_docname": participation.name},
		)
		self.assertEqual(total_count, 1)

	def test_in_patch_flag_suppresses_interaction_dispatch(self):
		self._ensure_interaction_type("Registered")
		self._ensure_interaction_type("Checked-in")

		frappe.flags.in_patch = True
		try:
			participation = self._make_participation()
			participation.insert(ignore_permissions=True)

			participation.status = "Checked-in"
			participation.save(ignore_permissions=True)
		finally:
			frappe.flags.in_patch = False

		total_count = frappe.db.count(
			"CRM Interaction",
			{"reference_doctype": "CRM Event Participation", "reference_docname": participation.name},
		)
		self.assertEqual(total_count, 0)
