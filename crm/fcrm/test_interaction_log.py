# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

"""Dispatcher-level coverage for crm/fcrm/interaction_log.py -- exercises the
doc_events wired in hooks.py (Communication after_insert/on_update, Task
on_update, Call Log after_insert) by inserting/saving the real source
doctypes and asserting on the CRM Interaction rows they create, including the
duplicate-guard scenarios.

Pure create_interaction()/CRMInteraction.validate() unit coverage, consent
event mapping, and cleanup-on-delete live in
crm/fcrm/doctype/crm_interaction/test_crm_interaction.py instead, since that
file already has the CRM Interaction Type fixtures those need. Contact
lifecycle-stage/assignment-change interaction coverage lives in
crm/fcrm/doctype/crm_contact/test_crm_contact.py alongside that doctype's
other save-path tests.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from unittest.mock import patch

from crm.fcrm.interaction_log import _source_matches_student


class TestInteractionLogDispatch(FrappeTestCase):
	def test_direct_student_reference_requires_the_same_student(self):
		with patch("crm.fcrm.interaction_log.frappe.db.exists", return_value=True):
			self.assertTrue(_source_matches_student("CRM Student", "STU-1", "STU-1"))
			self.assertFalse(_source_matches_student("CRM Student", "STU-1", "STU-2"))

	def setUp(self):
		frappe.set_user("Administrator")
		self._ensure_interaction_type("Outreach")
		self._ensure_interaction_type("Counseling")

	def tearDown(self):
		frappe.set_user("Administrator")

	# ---------------------------------------------------------------------- helpers

	def _ensure_interaction_type(self, name):
		# These are the same production CRM Interaction Type names the
		# seed_crm_interaction_types patch installs -- create_interaction() is a
		# no-op if the type doesn't already exist, so tests must seed it
		# themselves in this bench-less environment. Intentionally not
		# _Test-prefixed and not cleaned up in tearDown, matching how the real
		# patch would leave them in place.
		if not frappe.db.exists("CRM Interaction Type", name):
			frappe.get_doc({
				"doctype": "CRM Interaction Type",
				"interaction_type_name": name,
			}).insert(ignore_permissions=True)

	def _delete_if_exists(self, doctype, name):
		if name and frappe.db.exists(doctype, name):
			frappe.delete_doc(doctype, name, force=True)

	def _make_contact(self, name, phone):
		contact = frappe.get_doc({
			"doctype": "CRM Contact",
			"full_name": name,
			"phone": phone,
		})
		contact.insert(ignore_permissions=True)
		self.addCleanup(self._delete_if_exists, "CRM Contact", contact.name)
		return contact

	def _counseling_interactions(self, task_name):
		return frappe.db.get_all(
			"CRM Interaction",
			filters={
				"reference_doctype": "Task",
				"reference_docname": task_name,
				"interaction_type": "Counseling",
			},
			pluck="name",
		)

	# ----------------------------------------------- Communication insert -> Outreach

	def test_sent_communication_to_contact_creates_outreach_interaction(self):
		contact = self._make_contact("_Test Outreach Contact", "0919000001")
		comm = frappe.get_doc({
			"doctype": "Communication",
			"communication_type": "Communication",
			"communication_medium": "Email",
			"sent_or_received": "Sent",
			"subject": "_Test outreach subject",
			"reference_doctype": "CRM Contact",
			"reference_name": contact.name,
		})
		comm.insert(ignore_permissions=True)
		self.addCleanup(self._delete_if_exists, "Communication", comm.name)

		interaction_name = frappe.db.get_value(
			"CRM Interaction",
			{"reference_doctype": "Communication", "reference_docname": comm.name},
			"name",
		)
		self.assertTrue(interaction_name)
		self.addCleanup(self._delete_if_exists, "CRM Interaction", interaction_name)

		interaction = frappe.get_doc("CRM Interaction", interaction_name)
		self.assertEqual(interaction.interaction_type, "Outreach")
		self.assertEqual(interaction.crm_contact, contact.name)

	def test_received_communication_does_not_create_outreach_interaction(self):
		contact = self._make_contact("_Test No Outreach Contact", "0919000002")
		comm = frappe.get_doc({
			"doctype": "Communication",
			"communication_type": "Communication",
			"communication_medium": "Email",
			"sent_or_received": "Received",
			"subject": "_Test inbound subject",
			"reference_doctype": "CRM Contact",
			"reference_name": contact.name,
		})
		comm.insert(ignore_permissions=True)
		self.addCleanup(self._delete_if_exists, "Communication", comm.name)

		exists = frappe.db.exists(
			"CRM Interaction",
			{"reference_doctype": "Communication", "reference_docname": comm.name},
		)
		self.assertFalse(exists)

	# ---------------------------------------- Task status -> Done -> Counseling (+ guard)

	def test_task_marked_done_creates_single_counseling_interaction(self):
		contact = self._make_contact("_Test Counseling Contact", "0919000003")
		task = frappe.get_doc({
			"doctype": "Task",
			"title": "_Test counseling task",
			"description": "_Test discussed enrollment options",
			"status": "Todo",
			"reference_doctype": "CRM Contact",
			"reference_docname": contact.name,
		}).insert(ignore_permissions=True)
		self.addCleanup(self._delete_if_exists, "Task", task.name)

		task.status = "Done"
		task.save(ignore_permissions=True)

		interactions = self._counseling_interactions(task.name)
		self.assertEqual(len(interactions), 1)
		self.addCleanup(self._delete_if_exists, "CRM Interaction", interactions[0])

		# Regression guard: re-saving the already-Done task (no status change)
		# must not create a second Counseling interaction.
		task.description = "_Test discussed enrollment options (follow-up note)"
		task.save(ignore_permissions=True)

		self.assertEqual(len(self._counseling_interactions(task.name)), 1)

	def test_task_done_without_description_creates_no_interaction(self):
		contact = self._make_contact("_Test No Description Contact", "0919000004")
		task = frappe.get_doc({
			"doctype": "Task",
			"title": "_Test no description task",
			"status": "Todo",
			"reference_doctype": "CRM Contact",
			"reference_docname": contact.name,
		}).insert(ignore_permissions=True)
		self.addCleanup(self._delete_if_exists, "Task", task.name)

		task.status = "Done"
		task.save(ignore_permissions=True)

		self.assertEqual(len(self._counseling_interactions(task.name)), 0)

	def test_task_done_without_crm_reference_creates_no_interaction(self):
		task = frappe.get_doc({
			"doctype": "Task",
			"title": "_Test unrelated reference task",
			"description": "_Test discussed something unrelated",
			"status": "Todo",
		}).insert(ignore_permissions=True)
		self.addCleanup(self._delete_if_exists, "Task", task.name)

		task.status = "Done"
		task.save(ignore_permissions=True)

		self.assertEqual(len(self._counseling_interactions(task.name)), 0)
