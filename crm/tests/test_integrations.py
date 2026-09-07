# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import uuid

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.integrations.api import (
	add_note_to_call_log,
	add_task_to_call_log,
	get_contact_by_phone_number,
	get_contact_reference_from_number,
	get_integrations,
	get_user_default_calling_medium,
	is_call_integration_enabled,
	set_default_calling_medium,
)


class TestIntegrations(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_is_call_integration_enabled_both_disabled(self):
		frappe.db.set_single_value("Twilio Settings", "enabled", 0)
		frappe.db.set_single_value("Exotel Settings", "enabled", 0)

		result = is_call_integration_enabled()

		self.assertFalse(result["integrations"]["twilio"])
		self.assertFalse(result["integrations"]["exotel"])

	def test_is_call_integration_enabled_twilio_only(self):
		frappe.db.set_single_value("Twilio Settings", "enabled", 1)
		frappe.db.set_single_value("Exotel Settings", "enabled", 0)

		result = is_call_integration_enabled()

		self.assertTrue(result["integrations"]["twilio"])
		self.assertFalse(result["integrations"]["exotel"])

	def test_is_call_integration_enabled_exotel_only(self):
		frappe.db.set_single_value("Exotel Settings", "enabled", 1)
		frappe.db.set_single_value("Twilio Settings", "enabled", 0)

		result = is_call_integration_enabled()

		self.assertFalse(result["integrations"]["twilio"])
		self.assertTrue(result["integrations"]["exotel"])

	def test_get_integrations_returns_call_and_zalo_types(self):
		frappe.db.set_single_value("Twilio Settings", "enabled", 1)
		frappe.db.set_single_value("Exotel Settings", "enabled", 0)

		result = get_integrations()

		self.assertEqual(result["meta"]["requested_type"], None)
		self.assertEqual(result["meta"]["returned_types"], ["call", "zalo"])
		self.assertEqual(result["meta"]["total"], 3)
		self.assertEqual(
			[(item["type"], item["provider"], item["enabled"]) for item in result["data"]],
			[("call", "twilio", True), ("call", "exotel", False), ("zalo", "zalo_oa", False)],
		)
		self.assertEqual(result["data"][2]["status"], "not_configured")

	def test_get_integrations_filters_by_type(self):
		call_result = get_integrations("call")
		zalo_result = get_integrations("zalo")

		self.assertEqual(call_result["meta"]["requested_type"], "call")
		self.assertEqual({item["provider"] for item in call_result["data"]}, {"twilio", "exotel"})
		self.assertEqual(zalo_result["meta"]["requested_type"], "zalo")
		self.assertEqual([item["provider"] for item in zalo_result["data"]], ["zalo_oa"])

	def test_get_integrations_rejects_unsupported_type(self):
		with self.assertRaises(frappe.ValidationError):
			get_integrations("email")

	def test_get_user_default_calling_medium_no_agent(self):
		if frappe.db.exists("Telephony Agent", frappe.session.user):
			frappe.delete_doc("Telephony Agent", frappe.session.user)

		self.assertIsNone(get_user_default_calling_medium())

	def test_get_user_default_calling_medium_with_agent(self):
		_delete_current_agent()
		frappe.get_doc(
			{
				"doctype": "Telephony Agent",
				"user": frappe.session.user,
				"default_medium": "Twilio",
			}
		).insert()

		self.assertEqual(get_user_default_calling_medium(), "Twilio")

	def test_set_default_calling_medium_creates_new_record(self):
		_delete_current_agent()

		result = set_default_calling_medium("Exotel")

		self.assertEqual(result, "Exotel")
		self.assertTrue(frappe.db.exists("Telephony Agent", frappe.session.user))
		agent = frappe.get_doc("Telephony Agent", frappe.session.user)
		self.assertEqual(agent.default_medium, "Exotel")

	def test_set_default_calling_medium_updates_existing_record(self):
		_delete_current_agent()
		frappe.get_doc(
			{
				"doctype": "Telephony Agent",
				"user": frappe.session.user,
				"default_medium": "Twilio",
			}
		).insert()

		result = set_default_calling_medium("Exotel")

		self.assertEqual(result, "Exotel")
		agent = frappe.get_doc("Telephony Agent", frappe.session.user)
		self.assertEqual(agent.default_medium, "Exotel")

	def test_add_note_to_call_log_creates_new_note(self):
		call_log = create_test_call_log()

		result = add_note_to_call_log(
			call_log.name,
			{"content": "Discussed application next steps"},
		)

		self.assertTrue(frappe.db.exists("FCRM Note", result.name))
		self.assertEqual(result.content, "Discussed application next steps")

		call_log.reload()
		linked_notes = [link.link_name for link in call_log.links if link.link_doctype == "FCRM Note"]
		self.assertIn(result.name, linked_notes)

	def test_add_note_to_call_log_updates_existing_note(self):
		call_log = create_test_call_log()
		note = frappe.get_doc(
			{
				"doctype": "FCRM Note",
				"content": "Initial content",
			}
		).insert()

		add_note_to_call_log(
			call_log.name,
			{"name": note.name, "content": "Updated content"},
		)

		note.reload()
		self.assertEqual(note.content, "Updated content")

	def test_add_task_to_call_log_creates_new_task(self):
		call_log = create_test_call_log()

		result = add_task_to_call_log(
			call_log.name,
			{
				"title": "Follow up call",
				"description": "Call student next week",
				"assigned_to": "Administrator",
				"due_date": "2026-12-31",
				"status": "Todo",
				"priority": "High",
			},
		)

		self.assertTrue(frappe.db.exists("Task", result.name))
		self.assertEqual(result.title, "Follow up call")
		self.assertEqual(result.assigned_to, "Administrator")
		self.assertEqual(result.status, "Todo")

		call_log.reload()
		linked_tasks = [link.link_name for link in call_log.links if link.link_doctype == "Task"]
		self.assertIn(str(result.name), linked_tasks)

	def test_add_task_to_call_log_updates_existing_task(self):
		call_log = create_test_call_log()
		task = frappe.get_doc(
			{
				"doctype": "Task",
				"title": "Initial Task",
				"status": "Todo",
				"priority": "Medium",
			}
		).insert()

		result = add_task_to_call_log(
			call_log.name,
			{
				"name": task.name,
				"title": "Updated Task Title",
				"description": "Updated description",
				"assigned_to": "Administrator",
				"due_date": "2026-12-31",
				"status": "In Progress",
				"priority": "High",
			},
		)

		self.assertEqual(result.name, task.name)
		task.reload()
		self.assertEqual(task.title, "Updated Task Title")
		self.assertEqual(task.status, "In Progress")
		self.assertEqual(task.priority, "High")

	def test_get_contact_by_phone_number_finds_crm_contact(self):
		contact = create_test_crm_contact(phone="0912345600")

		result = get_contact_by_phone_number("0912345600")

		self.assertEqual(result["name"], contact.name)
		self.assertEqual(result["crm_contact"], contact.name)
		self.assertEqual(result["doctype"], "CRM Student")

	def test_get_contact_by_phone_number_finds_contact(self):
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "John",
				"last_name": "Doe",
				"phone_nos": [{"phone": "+91 9845552671", "is_primary_mobile_no": 1}],
			}
		).insert()

		result = get_contact_by_phone_number("+91 9845552671")

		self.assertEqual(result["name"], contact.name)
		self.assertEqual(result["full_name"], "John Doe")

	def test_get_contact_by_phone_number_returns_phone_only_if_not_found(self):
		result = get_contact_by_phone_number("+9999999999")

		self.assertEqual(result["mobile_no"], "+9999999999")
		self.assertNotIn("name", result)
		self.assertNotIn("full_name", result)

	def test_get_contact_reference_from_number_returns_crm_contact(self):
		contact = create_test_crm_contact(phone="0912345700")

		docname, doctype = get_contact_reference_from_number("0912345700")

		self.assertEqual(docname, contact.name)
		self.assertEqual(doctype, "CRM Student")

	def test_get_contact_reference_from_number_returns_contact(self):
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "Standalone",
				"last_name": "Contact",
				"phone_nos": [{"phone": "+91 9845552672", "is_primary_mobile_no": 1}],
			}
		).insert()

		docname, doctype = get_contact_reference_from_number("+91 9845552672")

		self.assertEqual(docname, contact.name)
		self.assertEqual(doctype, "Contact")

	def test_get_contact_reference_from_number_returns_none_when_not_found(self):
		docname, doctype = get_contact_reference_from_number("+1 999-999-9999")

		self.assertIsNone(docname)
		self.assertIsNone(doctype)

	def test_integration_workflow_call_with_note_and_task(self):
		call_log = create_test_call_log()
		note = add_note_to_call_log(
			call_log.name,
			{"content": "Student interested in admission counseling"},
		)
		task = add_task_to_call_log(
			call_log.name,
			{
				"title": "Schedule counseling",
				"description": "Set up counseling session",
				"assigned_to": "Administrator",
				"status": "Todo",
				"priority": "High",
			},
		)

		call_log.reload()
		link_types = {link.link_doctype for link in call_log.links}
		self.assertIn("FCRM Note", link_types)
		self.assertIn("Task", link_types)

		note_links = [link for link in call_log.links if link.link_doctype == "FCRM Note"]
		task_links = [link for link in call_log.links if link.link_doctype == "Task"]
		self.assertEqual(note_links[0].link_name, note.name)
		self.assertEqual(task_links[0].link_name, str(task.name))


def create_test_call_log(**kwargs):
	unique_id = kwargs.pop("id", str(uuid.uuid4())[:10])
	data = {
		"doctype": "Call Log",
		"id": unique_id,
		"type": "Incoming",
		"status": "Completed",
		"to": "+1234567890",
		"from": "+0987654321",
	}
	data.update(kwargs)

	return frappe.get_doc(data).insert()


def create_test_crm_contact(**kwargs):
	data = {
		"doctype": "CRM Student",
		"full_name": "Phone Lookup Contact",
		"phone": "0912345000",
		"email": f"lookup-{uuid.uuid4().hex[:8]}@example.com",
		"stage": "Interested",
	}
	data.update(kwargs)
	return frappe.get_doc(data).insert(ignore_permissions=True)


def _delete_current_agent():
	if frappe.db.exists("Telephony Agent", frappe.session.user):
		frappe.delete_doc("Telephony Agent", frappe.session.user)
