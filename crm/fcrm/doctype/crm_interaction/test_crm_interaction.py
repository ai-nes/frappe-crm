import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.interaction_log import create_interaction


class TestCRMInteraction(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._ensure_master_data()

	def tearDown(self):
		for name in frappe.db.get_all("CRM Intent", filters={"intent_type": "_Test Tuition Inquiry"}, pluck="name"):
			frappe.delete_doc("CRM Intent", name, force=True)
		for name in frappe.db.get_all("CRM Interaction", filters={"summary": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Interaction", name, force=True)
		for name in frappe.db.get_all("CRM Student", filters={"student_name": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Student", name, force=True)

	def _ensure_master_data(self):
		if not frappe.db.exists("CRM Interaction Type", "_Test Phone Call"):
			frappe.get_doc({
				"doctype": "CRM Interaction Type",
				"interaction_type_name": "_Test Phone Call",
			}).insert(ignore_permissions=True)

		if not frappe.db.exists("CRM Intent Type", "_Test Tuition Inquiry"):
			frappe.get_doc({
				"doctype": "CRM Intent Type",
				"intent_type_name": "_Test Tuition Inquiry",
				"importance": "Very High",
			}).insert(ignore_permissions=True)

	def _make_student(self):
		student = frappe.get_doc({
			"doctype": "CRM Student",
			"student_name": "_Test Interaction Student",
			"phone": "0901234567",
		})
		previous_intake_flag = getattr(frappe.flags, "student_intake_service", False)
		frappe.flags.student_intake_service = True
		try:
			student.insert(ignore_permissions=True)
		finally:
			frappe.flags.student_intake_service = previous_intake_flag
		return student

	def _make_interaction(self, student):
		interaction = frappe.get_doc({
			"doctype": "CRM Interaction",
			"student": student.name,
			"interaction_type": "_Test Phone Call",
			"summary": "_Test discussed tuition",
		})
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

		intent = frappe.get_doc({
			"doctype": "CRM Intent",
			"interaction": interaction.name,
			"intent_type": "_Test Tuition Inquiry",
			"confidence": 80,
		})
		intent.insert(ignore_permissions=True)

		self.assertEqual(intent.student, student.name)
		self.assertEqual(intent.importance, "Very High")

	# ---------------------------------------------------------------- validate()

	def test_validate_raises_without_student_or_contact(self):
		interaction = frappe.get_doc({
			"doctype": "CRM Interaction",
			"interaction_type": "_Test Phone Call",
			"summary": "_Test no target validate",
		})
		with self.assertRaises(frappe.ValidationError):
			interaction.insert(ignore_permissions=True)

	def test_validate_passes_with_only_crm_contact_set(self):
		contact = self._make_contact("_Test Interaction Validate Contact", "0919500001")
		interaction = frappe.get_doc({
			"doctype": "CRM Interaction",
			"crm_contact": contact.name,
			"interaction_type": "_Test Phone Call",
			"summary": "_Test only contact set",
		})
		interaction.insert(ignore_permissions=True)  # must not raise
		self.assertEqual(interaction.crm_contact, contact.name)

	# ------------------------------------------------ create_interaction() (pure logic)

	def test_create_interaction_resolves_student_from_contact(self):
		student = self._make_student()
		contact = self._make_contact("_Test Interaction Resolve Contact", "0919500002")
		contact.db_set("student", student.name)

		name = create_interaction(
			interaction_type="_Test Phone Call",
			crm_contact=contact.name,
			summary="_Test resolve student from contact",
		)

		self.assertTrue(name)
		interaction = frappe.get_doc("CRM Interaction", name)
		self.assertEqual(interaction.crm_contact, contact.name)
		self.assertEqual(interaction.student, student.name)

	def test_create_interaction_without_student_or_contact_returns_none(self):
		result = create_interaction(interaction_type="_Test Phone Call", summary="_Test no target")
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
			interaction_type="_Test Phone Call",
			student=student.name,
			summary="_Test actor default",
		)

		interaction = frappe.get_doc("CRM Interaction", name)
		self.assertEqual(interaction.actor, "Administrator")

	def test_create_interaction_honors_explicit_actor(self):
		student = self._make_student()
		name = create_interaction(
			interaction_type="_Test Phone Call",
			student=student.name,
			summary="_Test explicit actor",
			actor="Administrator",
		)

		interaction = frappe.get_doc("CRM Interaction", name)
		self.assertEqual(interaction.actor, "Administrator")

	# ------------------------------------------------------------- consent event mapping

	def test_consent_event_opted_out_creates_opt_out_interaction(self):
		contact = self._make_contact("_Test Consent Opt Out Contact", "0919500003")
		event = frappe.get_doc({
			"doctype": "CRM Contact Consent Event",
			"contact": contact.name,
			"event_type": "Opted Out",
			"occurred_at": frappe.utils.now_datetime(),
			"source": "_Test consent source",
		})
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
		self.assertEqual(interaction.interaction_type, "Opt-out")
		self.assertEqual(interaction.crm_contact, contact.name)

	def test_consent_event_marked_test_creates_no_interaction(self):
		contact = self._make_contact("_Test Consent Marked Test Contact", "0919500004")
		event = frappe.get_doc({
			"doctype": "CRM Contact Consent Event",
			"contact": contact.name,
			"event_type": "Marked Test",
			"occurred_at": frappe.utils.now_datetime(),
		})
		event.insert(ignore_permissions=True)
		self.addCleanup(self._delete_if_exists, "CRM Contact Consent Event", event.name)

		exists = frappe.db.exists(
			"CRM Interaction",
			{"reference_doctype": "CRM Contact Consent Event", "reference_docname": event.name},
		)
		self.assertFalse(exists)

	# ----------------------------------------------------------- cleanup on source delete

	def test_deleting_consent_event_clears_interaction_reference_but_keeps_interaction(self):
		contact = self._make_contact("_Test Consent Cleanup Contact", "0919500005")
		event = frappe.get_doc({
			"doctype": "CRM Contact Consent Event",
			"contact": contact.name,
			"event_type": "Opted Out",
			"occurred_at": frappe.utils.now_datetime(),
		})
		event.insert(ignore_permissions=True)

		interaction_name = frappe.db.get_value(
			"CRM Interaction",
			{"reference_doctype": "CRM Contact Consent Event", "reference_docname": event.name},
			"name",
		)
		self.assertTrue(interaction_name)
		self.addCleanup(self._delete_if_exists, "CRM Interaction", interaction_name)

		frappe.delete_doc("CRM Contact Consent Event", event.name, force=True)

		self.assertTrue(frappe.db.exists("CRM Interaction", interaction_name))
		interaction = frappe.get_doc("CRM Interaction", interaction_name)
		self.assertFalse(interaction.reference_doctype)
		self.assertFalse(interaction.reference_docname)

	# ---------------------------------------------------------------------- helpers

	def _make_contact(self, name, phone):
		contact = frappe.get_doc({
			"doctype": "CRM Contact",
			"full_name": name,
			"phone": phone,
		})
		contact.insert(ignore_permissions=True)
		self.addCleanup(self._delete_if_exists, "CRM Contact", contact.name)
		return contact

	def _delete_if_exists(self, doctype, name):
		if name and frappe.db.exists(doctype, name):
			frappe.delete_doc(doctype, name, force=True)
