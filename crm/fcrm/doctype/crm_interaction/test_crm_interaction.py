from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.interaction_log import create_interaction


class TestCRMInteraction(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._ensure_master_data()

	def tearDown(self):
		for name in frappe.db.get_all(
			"CRM Intent", filters={"intent_type": "TUITION_FEE"}, pluck="name"
		):
			frappe.delete_doc("CRM Intent", name, force=True)
		for name in frappe.db.get_all(
			"CRM Interaction", filters={"summary": ["like", "_Test%"]}, pluck="name"
		):
			frappe.delete_doc("CRM Interaction", name, force=True)
		for name in frappe.db.get_all(
			"CRM Lead", filters={"student_name": ["like", "_Test%"]}, pluck="name"
		):
			frappe.delete_doc("CRM Lead", name, force=True)

	def _ensure_master_data(self):
		for doctype, code, display_name in (
			("CRM Interaction Type", "MESSAGE", "Tin nhắn"),
			("CRM Interaction Type", "OPT_OUT", "Từ chối nhận tin"),
			("CRM Intent Type", "TUITION_FEE", "Học phí"),
		):
			if not frappe.db.exists(doctype, code):
				frappe.get_doc(
					{
						"doctype": doctype,
						"code": code,
						"display_name": display_name,
					}
				).insert(ignore_permissions=True)

	def _make_student(self):
		student = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"student_name": "_Test Interaction Student",
				"phone": "0901234567",
			}
		)
		previous_intake_flag = getattr(frappe.flags, "student_intake_service", False)
		frappe.flags.student_intake_service = True
		try:
			student.insert(ignore_permissions=True)
		finally:
			frappe.flags.student_intake_service = previous_intake_flag
		return student

	def _make_interaction(self, student):
		interaction = frappe.get_doc(
			{
				"doctype": "CRM Interaction",
				"student": student.name,
				"interaction_type": "MESSAGE",
				"summary": "_Test discussed tuition",
			}
		)
		interaction.insert(ignore_permissions=True)
		return interaction

	def test_interaction_defaults_datetime(self):
		student = self._make_student()
		interaction = self._make_interaction(student)

		self.assertEqual(interaction.student, student.name)
		self.assertTrue(interaction.interaction_datetime)

	def test_intent_snapshots_student_and_importance(self):
		student = self._make_student()
		interaction = self._make_interaction(student)

		intent = frappe.get_doc(
			{
				"doctype": "CRM Intent",
				"interaction": interaction.name,
				"intent_type": "TUITION_FEE",
				"confidence": 80,
			}
		)
		intent.insert(ignore_permissions=True)

		self.assertEqual(intent.student, student.name)
		self.assertEqual(intent.importance, "High")

	# ---------------------------------------------------------------- validate()

	def test_validate_raises_without_student_or_contact(self):
		interaction = frappe.get_doc(
			{
				"doctype": "CRM Interaction",
				"interaction_type": "MESSAGE",
				"summary": "_Test no target validate",
			}
		)
		with self.assertRaises(frappe.ValidationError):
			interaction.insert(ignore_permissions=True)

	def test_validate_passes_with_only_crm_contact_set(self):
		contact = self._make_contact("_Test Interaction Validate Contact", "0919500001")
		interaction = frappe.get_doc(
			{
				"doctype": "CRM Interaction",
				"crm_contact": contact.name,
				"interaction_type": "MESSAGE",
				"summary": "_Test only contact set",
			}
		)
		interaction.insert(ignore_permissions=True)  # must not raise
		self.assertEqual(interaction.crm_contact, contact.name)

	# ------------------------------------------------ create_interaction() (pure logic)

	def test_create_interaction_resolves_student_from_contact(self):
		student = self._make_student()
		contact = self._make_contact("_Test Interaction Resolve Contact", "0919500002")
		contact.db_set("student", student.name)

		name = create_interaction(
			interaction_type="MESSAGE",
			crm_contact=contact.name,
			summary="_Test resolve student from contact",
		)

		self.assertTrue(name)
		interaction = frappe.get_doc("CRM Interaction", name)
		self.assertEqual(interaction.crm_contact, contact.name)
		self.assertEqual(interaction.student, student.name)

	def test_create_interaction_without_student_or_contact_returns_none(self):
		result = create_interaction(interaction_type="MESSAGE", summary="_Test no target")
		self.assertIsNone(result)
		self.assertFalse(frappe.db.exists("CRM Interaction", {"summary": "_Test no target"}))

	def test_create_interaction_unknown_type_returns_none(self):
		student = self._make_student()
		result = create_interaction(
			interaction_type="_Test Nonexistent Interaction Type",
			student=student.name,
			summary="_Test unknown type",
		)
		self.assertIsNone(result)
		self.assertFalse(frappe.db.exists("CRM Interaction", {"summary": "_Test unknown type"}))

	def test_create_interaction_defaults_actor_to_session_user(self):
		student = self._make_student()
		name = create_interaction(
			interaction_type="MESSAGE",
			student=student.name,
			summary="_Test actor default",
		)

		interaction = frappe.get_doc("CRM Interaction", name)
		self.assertEqual(interaction.actor, "Administrator")

	# ------------------------------------------------------------- external_id dedup

	def test_create_interaction_is_idempotent_for_same_reference_and_type(self):
		# CRM Contact itself is excluded from dedup (NON_DEDUPABLE_REFERENCE_
		# DOCTYPES -- see test_crm_contact.py's lifecycle/assignment regression
		# tests), so this must reference a genuine discrete source event instead.
		student = self._make_student()
		event = self._make_consent_event("_Test Interaction Dedup Contact", "0919500010")

		first = create_interaction(
			interaction_type="MESSAGE",
			student=student.name,
			reference_doctype="CRM Contact Consent Event",
			reference_docname=event.name,
			summary="_Test dedup first",
		)
		second = create_interaction(
			interaction_type="MESSAGE",
			student=student.name,
			reference_doctype="CRM Contact Consent Event",
			reference_docname=event.name,
			summary="_Test dedup retried",
		)

		self.assertEqual(first, second)
		self.assertEqual(
			frappe.db.count(
				"CRM Interaction",
				{
					"reference_doctype": "CRM Contact Consent Event",
					"reference_docname": event.name,
					"interaction_type": "MESSAGE",
				},
			),
			1,
		)

	def test_create_interaction_recovers_from_concurrent_duplicate_insert(self):
		# Simulates two workers racing past the pre-insert existence check
		# before either commits: the first frappe.db.get_value() call misses
		# (patched to None) as if the winner's row hadn't landed yet, so
		# create_interaction() proceeds to insert() and hits the real unique
		# external_id constraint. It must resolve that to the winner's row
		# instead of raising.
		student = self._make_student()
		event = self._make_consent_event("_Test Interaction Race Contact", "0919500011")
		external_id = f"CRM Contact Consent Event:{event.name}:MESSAGE"

		winner = frappe.get_doc(
			{
				"doctype": "CRM Interaction",
				"student": student.name,
				"interaction_type": "MESSAGE",
				"reference_doctype": "CRM Contact Consent Event",
				"reference_docname": event.name,
				"summary": "_Test race winner",
				"external_id": external_id,
			}
		)
		winner.insert(ignore_permissions=True)
		self.assertEqual(winner.external_id, external_id)

		real_get_value = frappe.db.get_value
		seen = {"n": 0}

		def _flaky_get_value(doctype, filters=None, fieldname=None, *args, **kwargs):
			# Target only create_interaction()'s external_id existence check --
			# not any other frappe.db.get_value call the surrounding code paths
			# make (e.g. frappe.db.exists() is implemented on top of get_value
			# in some Frappe versions, so a bare global call counter would also
			# intercept the unrelated "CRM Interaction Type" exists() check and
			# make it spuriously report the type as unknown).
			if (
				doctype == "CRM Interaction"
				and isinstance(filters, dict)
				and filters.get("external_id") == external_id
			):
				seen["n"] += 1
				if seen["n"] == 1:
					return None
			return real_get_value(doctype, filters, fieldname, *args, **kwargs)

		with patch.object(frappe.db, "get_value", side_effect=_flaky_get_value):
			result = create_interaction(
				interaction_type="MESSAGE",
				student=student.name,
				reference_doctype="CRM Contact Consent Event",
				reference_docname=event.name,
				summary="_Test race loser",
			)

		self.assertEqual(result, winner.name)
		self.assertEqual(
			frappe.db.count("CRM Interaction", {"external_id": external_id}),
			1,
		)

	def test_manual_interaction_without_reference_is_not_deduplicated(self):
		student = self._make_student()
		first = create_interaction(
			interaction_type="MESSAGE", student=student.name, summary="_Test manual one"
		)
		second = create_interaction(
			interaction_type="MESSAGE", student=student.name, summary="_Test manual two"
		)
		self.assertNotEqual(first, second)

	def test_create_interaction_honors_explicit_actor(self):
		student = self._make_student()
		name = create_interaction(
			interaction_type="MESSAGE",
			student=student.name,
			summary="_Test explicit actor",
			actor="Administrator",
		)

		interaction = frappe.get_doc("CRM Interaction", name)
		self.assertEqual(interaction.actor, "Administrator")

	# ------------------------------------------------------------- consent event mapping

	def test_consent_event_opted_out_creates_opt_out_interaction(self):
		contact = self._make_contact("_Test Consent Opt Out Contact", "0919500003")
		event = frappe.get_doc(
			{
				"doctype": "CRM Contact Consent Event",
				"contact": contact.name,
				"event_type": "Opted Out",
				"occurred_at": frappe.utils.now_datetime(),
				"source": "_Test consent source",
			}
		)
		event.insert(ignore_permissions=True)
		self.addCleanup(self._delete_if_exists, "CRM Contact Consent Event", event.name)

		interaction_name = frappe.db.get_value(
			"CRM Interaction",
			{"reference_doctype": "CRM Contact Consent Event", "reference_docname": event.name},
			"name",
		)
		self.assertTrue(interaction_name)
		self.addCleanup(self._delete_if_exists, "CRM Interaction", interaction_name)

		interaction = frappe.get_doc("CRM Interaction", interaction_name)
		self.assertEqual(interaction.interaction_type, "OPT_OUT")
		self.assertEqual(interaction.crm_contact, contact.name)

	def test_consent_event_marked_test_creates_no_interaction(self):
		contact = self._make_contact("_Test Consent Marked Test Contact", "0919500004")
		event = frappe.get_doc(
			{
				"doctype": "CRM Contact Consent Event",
				"contact": contact.name,
				"event_type": "Marked Test",
				"occurred_at": frappe.utils.now_datetime(),
			}
		)
		event.insert(ignore_permissions=True)
		self.addCleanup(self._delete_if_exists, "CRM Contact Consent Event", event.name)

		exists = frappe.db.exists(
			"CRM Interaction",
			{"reference_doctype": "CRM Contact Consent Event", "reference_docname": event.name},
		)
		self.assertFalse(exists)

	# ----------------------------------------------------------- cleanup on source delete

	def test_deleting_consent_event_is_rejected_and_keeps_interaction(self):
		contact = self._make_contact("_Test Consent Cleanup Contact", "0919500005")
		event = frappe.get_doc(
			{
				"doctype": "CRM Contact Consent Event",
				"contact": contact.name,
				"event_type": "Opted Out",
				"occurred_at": frappe.utils.now_datetime(),
			}
		)
		event.insert(ignore_permissions=True)

		interaction_name = frappe.db.get_value(
			"CRM Interaction",
			{"reference_doctype": "CRM Contact Consent Event", "reference_docname": event.name},
			"name",
		)
		self.assertTrue(interaction_name)
		self.addCleanup(self._delete_if_exists, "CRM Interaction", interaction_name)

		with self.assertRaises(frappe.PermissionError):
			frappe.delete_doc("CRM Contact Consent Event", event.name, force=True)

		self.assertTrue(frappe.db.exists("CRM Interaction", interaction_name))
		interaction = frappe.get_doc("CRM Interaction", interaction_name)
		self.assertEqual(interaction.reference_doctype, "CRM Contact Consent Event")
		self.assertEqual(interaction.reference_docname, event.name)

	# ------------------------------------------------------------- on_trash() revision bump

	def test_deleting_interaction_bumps_score_input_revision(self):
		student = self._make_student()
		interaction = self._make_interaction(student)
		before_revision = frappe.db.get_value("CRM Lead", student.name, "score_input_revision") or 0

		frappe.delete_doc("CRM Interaction", interaction.name, force=True)

		after_revision = frappe.db.get_value("CRM Lead", student.name, "score_input_revision") or 0
		self.assertGreater(after_revision, before_revision)

	def test_deleting_interaction_resolves_student_from_contact(self):
		contact = self._make_contact("_Test Interaction Trash Contact", "0919500020")
		student = self._make_student()
		contact.db_set("student", student.name)
		interaction = frappe.get_doc(
			{
				"doctype": "CRM Interaction",
				"crm_contact": contact.name,
				"interaction_type": "MESSAGE",
				"summary": "_Test trash via contact",
			}
		)
		interaction.insert(ignore_permissions=True)
		before_revision = frappe.db.get_value("CRM Lead", student.name, "score_input_revision") or 0

		frappe.delete_doc("CRM Interaction", interaction.name, force=True)

		after_revision = frappe.db.get_value("CRM Lead", student.name, "score_input_revision") or 0
		self.assertGreater(after_revision, before_revision)

	# ---------------------------------------------------------------------- helpers

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

	def _make_consent_event(self, contact_name, phone):
		contact = self._make_contact(contact_name, phone)
		event = frappe.get_doc(
			{
				"doctype": "CRM Contact Consent Event",
				"contact": contact.name,
				# "Marked Test" is excluded from CONSENT_EVENT_TO_INTERACTION_TYPE
				# dispatch, so inserting this doesn't itself create an interaction
				# and pollute the dedup counts this helper's callers assert on.
				"event_type": "Marked Test",
				"occurred_at": frappe.utils.now_datetime(),
			}
		)
		event.insert(ignore_permissions=True)
		self.addCleanup(self._delete_if_exists, "CRM Contact Consent Event", event.name)
		return event

	def _delete_if_exists(self, doctype, name):
		if name and frappe.db.exists(doctype, name):
			if doctype == "CRM Contact Consent Event":
				frappe.db.delete(doctype, {"name": name})
			else:
				frappe.delete_doc(doctype, name, force=True)
