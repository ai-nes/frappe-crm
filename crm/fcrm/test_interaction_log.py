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
file already has the lookup fixtures those need. Contact
lifecycle-stage/assignment-change interaction coverage lives in
crm/fcrm/doctype/crm_contact/test_crm_contact.py alongside that doctype's
other save-path tests.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.interaction_log import _source_matches_student, ingest_external_interaction
from crm.fcrm.student_intake import StudentIntakeError


class TestInteractionLogDispatch(FrappeTestCase):
	def test_direct_student_reference_requires_the_same_student(self):
		with patch("crm.fcrm.interaction_log.frappe.db.exists", return_value=True):
			self.assertTrue(_source_matches_student("CRM Lead", "STU-1", "STU-1"))
			self.assertFalse(_source_matches_student("CRM Lead", "STU-1", "STU-2"))

	def test_external_interaction_replay_does_not_create_a_second_row(self):
		payload = {
			"source_namespace": "chatwoot",
			"source_record_id": "message-replay-1",
			"idempotency_key": "interaction-replay-1",
			"student_id": "STU-1",
			"channel": "facebook",
			"direction": "inbound",
			"turns": [{"speaker_role": "student", "content": "Need tuition details"}],
			"occurred_at": "2026-08-29 09:00:00",
		}
		result = {
			"outcome": "created",
			"interaction": "INT-1",
			"student": "STU-1",
			"contact": None,
			"receipt": "REC-1",
		}
		authority = {
			"actor_user": "sales@example.com",
			"actor_staff": "STAFF-1",
			"profile": "sales",
			"campus_scope": ["HCM"],
			"team_scope": ["TEAM-1"],
		}

		with (
			patch("crm.fcrm.student_intake._resolve_authority", return_value=authority),
			patch("crm.fcrm.student_intake._receipt_replay", side_effect=[None, result]),
			patch("crm.fcrm.student_intake._assert_replay_scope"),
			patch("crm.fcrm.student_intake._persist_receipt", return_value=result),
			patch(
				"crm.fcrm.interaction_log._resolve_external_interaction_target",
				return_value={"student": "STU-1", "contact": None},
			),
			patch("crm.fcrm.interaction_log._assert_interaction_scope"),
			patch("crm.fcrm.interaction_log._ensure_interaction_evidence", return_value=["EVID-1"]),
			patch("crm.fcrm.interaction_log._ensure_interaction_analysis_run", return_value="IAR-1"),
			patch("crm.fcrm.interaction_log.create_interaction", return_value="INT-1") as create,
			patch.object(frappe.db, "exists", return_value=True),
			patch.object(
				frappe.db,
				"get_value",
				side_effect=[
					None,
					{
						"name": "INT-1",
						"student": "STU-1",
						"crm_contact": None,
						"notes": payload["turns"][0]["content"],
						"channel": "facebook",
						"direction": "inbound",
						"interaction_datetime": "2026-08-29 09:00:00",
						"conversation_id": None,
						"agent_id": None,
					},
				],
			),
		):
			first = ingest_external_interaction(payload)
			second = ingest_external_interaction(payload)

		self.assertEqual(first, result)
		self.assertEqual(second, result)
		create.assert_called_once()
		self.assertEqual(create.call_args.kwargs["interaction_type"], "MESSAGE")

	def test_configured_service_user_has_only_interaction_authority(self):
		from crm.fcrm.student_intake import INTERACTION_CAPABILITY, SUBMIT_CAPABILITY, _resolve_authority

		previous_user = frappe.session.user
		previous_service_user = frappe.conf.get("crm_agents_service_user")
		try:
			frappe.conf.crm_agents_service_user = "ai-service@crm-agents.local"
			frappe.set_user("ai-service@crm-agents.local")
			authority = _resolve_authority(INTERACTION_CAPABILITY)
			self.assertEqual(authority["profile"], "service")
			self.assertTrue(authority["scope_all"])
			with self.assertRaises(StudentIntakeError):
				_resolve_authority(SUBMIT_CAPABILITY)
		finally:
			frappe.set_user(previous_user)
			if previous_service_user is None:
				frappe.conf.pop("crm_agents_service_user", None)
			else:
				frappe.conf.crm_agents_service_user = previous_service_user

	def setUp(self):
		frappe.set_user("Administrator")
		self._ensure_interaction_type("OUTREACH")

	def tearDown(self):
		frappe.set_user("Administrator")

	# ---------------------------------------------------------------------- helpers

	def _ensure_interaction_type(self, code):
		# These are the same production CRM Interaction Type codes the
		# seed_reference_lookups patch installs -- create_interaction() is a
		# no-op if the type doesn't already exist, so tests must seed it
		# themselves in this bench-less environment. Intentionally not
		# cleaned up in tearDown, matching how the real seed leaves them in place.
		if not frappe.db.exists("CRM Interaction Type", code):
			frappe.get_doc(
				{
					"doctype": "CRM Interaction Type",
					"code": code,
					"display_name": code,
				}
			).insert(ignore_permissions=True)

	def _delete_if_exists(self, doctype, name):
		if name and frappe.db.exists(doctype, name):
			frappe.delete_doc(doctype, name, force=True)

	def _make_contact(self, name, phone):
		contact = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"full_name": name,
				"phone": phone,
			}
		)
		contact.insert(ignore_permissions=True)
		self.addCleanup(self._delete_if_exists, "CRM Student", contact.name)
		return contact

	def _task_interactions(self, task_name):
		return frappe.db.get_all(
			"CRM Interaction",
			filters={
				"reference_doctype": "Task",
				"reference_docname": task_name,
				"interaction_type": "SYSTEM_ACTIVITY",
			},
			pluck="name",
		)

	# ----------------------------------------------- Communication insert -> Outreach

	def test_sent_communication_to_contact_creates_outreach_interaction(self):
		contact = self._make_contact("_Test Outreach Contact", "0919000001")
		comm = frappe.get_doc(
			{
				"doctype": "Communication",
				"communication_type": "Communication",
				"communication_medium": "Email",
				"sent_or_received": "Sent",
				"subject": "_Test outreach subject",
				"reference_doctype": "CRM Student",
				"reference_name": contact.name,
			}
		)
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
		self.assertEqual(interaction.interaction_type, "OUTREACH")
		self.assertEqual(interaction.crm_contact, contact.name)

	def test_received_communication_does_not_create_outreach_interaction(self):
		contact = self._make_contact("_Test No Outreach Contact", "0919000002")
		comm = frappe.get_doc(
			{
				"doctype": "Communication",
				"communication_type": "Communication",
				"communication_medium": "Email",
				"sent_or_received": "Received",
				"subject": "_Test inbound subject",
				"reference_doctype": "CRM Student",
				"reference_name": contact.name,
			}
		)
		comm.insert(ignore_permissions=True)
		self.addCleanup(self._delete_if_exists, "Communication", comm.name)

		exists = frappe.db.exists(
			"CRM Interaction",
			{"reference_doctype": "Communication", "reference_docname": comm.name},
		)
		self.assertFalse(exists)

	# ----------------------------------- Task status -> Done -> System Activity

	def test_task_marked_done_creates_single_system_activity_interaction(self):
		contact = self._make_contact("_Test Counseling Contact", "0919000003")
		task = frappe.get_doc(
			{
				"doctype": "Task",
				"title": "_Test counseling task",
				"description": "_Test discussed enrollment options",
				"status": "Todo",
				"reference_doctype": "CRM Student",
				"reference_docname": contact.name,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(self._delete_if_exists, "Task", task.name)

		task.status = "Done"
		task.save(ignore_permissions=True)

		interactions = self._task_interactions(task.name)
		self.assertEqual(len(interactions), 1)
		self.addCleanup(self._delete_if_exists, "CRM Interaction", interactions[0])

		# Regression guard: re-saving the already-Done task (no status change)
		# must not create a second System Activity interaction.
		task.description = "_Test discussed enrollment options (follow-up note)"
		task.save(ignore_permissions=True)

		self.assertEqual(len(self._task_interactions(task.name)), 1)

	def test_task_done_without_description_creates_no_interaction(self):
		contact = self._make_contact("_Test No Description Contact", "0919000004")
		task = frappe.get_doc(
			{
				"doctype": "Task",
				"title": "_Test no description task",
				"status": "Todo",
				"reference_doctype": "CRM Student",
				"reference_docname": contact.name,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(self._delete_if_exists, "Task", task.name)

		task.status = "Done"
		task.save(ignore_permissions=True)

		self.assertEqual(len(self._task_interactions(task.name)), 0)

	def test_task_done_without_crm_reference_creates_no_interaction(self):
		task = frappe.get_doc(
			{
				"doctype": "Task",
				"title": "_Test unrelated reference task",
				"description": "_Test discussed something unrelated",
				"status": "Todo",
			}
		).insert(ignore_permissions=True)
		self.addCleanup(self._delete_if_exists, "Task", task.name)

		task.status = "Done"
		task.save(ignore_permissions=True)

		self.assertEqual(len(self._task_interactions(task.name)), 0)
