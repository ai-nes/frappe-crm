# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import uuid

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.doctype.call_log.call_log import (
	create_contact_from_call_log,
	get_call_log,
	parse_call_log,
)


class TestCallLog(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_call_log_creation_incoming(self):
		call = create_test_call_log(
			type="Incoming",
			status="Completed",
			caller=None,
			receiver="Administrator",
		)

		self.assertEqual(call.type, "Incoming")
		self.assertEqual(call.status, "Completed")
		self.assertEqual(call.receiver, "Administrator")

	def test_call_log_creation_outgoing(self):
		call = create_test_call_log(
			type="Outgoing",
			status="Completed",
			caller="Administrator",
			receiver=None,
		)

		self.assertEqual(call.type, "Outgoing")
		self.assertEqual(call.status, "Completed")
		self.assertEqual(call.caller, "Administrator")

	def test_call_log_with_duration(self):
		call = create_test_call_log(duration=120)
		self.assertEqual(call.duration, 120)

	def test_call_log_with_recording_url(self):
		recording_url = "https://example.com/recording.mp3"
		call = create_test_call_log(recording_url=recording_url)
		self.assertEqual(call.recording_url, recording_url)

	def test_has_link_method(self):
		contact = create_test_crm_contact()
		call = create_test_call_log()

		self.assertFalse(call.has_link("CRM Student", contact.name))

		call.link_with_reference_doc("CRM Student", contact.name)
		self.assertTrue(call.has_link("CRM Student", contact.name))

	def test_link_with_reference_doc(self):
		contact = create_test_crm_contact()
		call = create_test_call_log()

		call.link_with_reference_doc("CRM Student", contact.name)
		call.save()

		self.assertTrue(call.has_link("CRM Student", contact.name))
		self.assertEqual(len(call.links), 1)
		self.assertEqual(call.links[0].link_doctype, "CRM Student")
		self.assertEqual(call.links[0].link_name, contact.name)

	def test_link_with_reference_doc_duplicate_prevention(self):
		contact = create_test_crm_contact()
		call = create_test_call_log()

		call.link_with_reference_doc("CRM Student", contact.name)
		call.link_with_reference_doc("CRM Student", contact.name)
		call.save()

		self.assertEqual(len(call.links), 1)

	def test_default_list_data_returns_actual_logs(self):
		from crm.fcrm.doctype.call_log.call_log import CallLog

		create_test_call_log(type="Incoming", caller=None, receiver="Administrator", status="Completed")
		create_test_call_log(type="Outgoing", caller="Administrator", receiver=None, status="Failed")

		data = CallLog.default_list_data()

		self.assertIn("columns", data)
		self.assertIn("rows", data)
		column_keys = [col["key"] for col in data["columns"]]
		self.assertIn("caller", column_keys)
		self.assertIn("receiver", column_keys)
		self.assertIn("type", column_keys)
		self.assertIn("status", column_keys)
		self.assertIn("name", data["rows"])

	def test_parse_call_log_incoming(self):
		if not frappe.db.exists("User", "test@example.com"):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": "test@example.com",
					"first_name": "Test",
				}
			).insert()

		parsed = parse_call_log(
			{
				"type": "Incoming",
				"from": "+1234567890",
				"to": "+0987654321",
				"receiver": "test@example.com",
				"duration": 120,
			}
		)

		self.assertEqual(parsed["activity_type"], "incoming_call")
		self.assertEqual(parsed["_duration"], "2m")
		self.assertEqual(parsed["_caller"]["label"], "Unknown")
		self.assertIn("label", parsed["_receiver"])

	def test_parse_call_log_outgoing(self):
		parsed = parse_call_log(
			{
				"type": "Outgoing",
				"from": "+1234567890",
				"to": "+0987654321",
				"caller": "Administrator",
				"duration": 180,
			}
		)

		self.assertEqual(parsed["activity_type"], "outgoing_call")
		self.assertEqual(parsed["_duration"], "3m")
		self.assertEqual(parsed["_caller"]["label"], "Administrator")
		self.assertEqual(parsed["_receiver"]["label"], "Unknown")

	def test_get_call_log_api(self):
		call = create_test_call_log(type="Outgoing", status="Completed", duration=60)
		result = get_call_log(call.name)

		self.assertEqual(result["name"], call.name)
		self.assertEqual(result["type"], "Outgoing")
		self.assertEqual(result["status"], "Completed")
		self.assertIn("_duration", result)
		self.assertIn("_tasks", result)
		self.assertIn("_notes", result)

	def test_get_call_log_with_reference_crm_contact(self):
		contact = create_test_crm_contact()
		call = create_test_call_log(
			reference_doctype="CRM Student",
			reference_docname=contact.name,
		)

		result = get_call_log(call.name)
		self.assertEqual(result.get("_crm_contact"), contact.name)

	def test_get_call_log_with_linked_task(self):
		call = create_test_call_log()
		task = frappe.get_doc(
			{
				"doctype": "Task",
				"title": "Follow up call",
				"assigned_to": "Administrator",
			}
		).insert()

		call.link_with_reference_doc("Task", task.name)
		call.save()

		result = get_call_log(call.name)
		self.assertEqual(len(result["_tasks"]), 1)
		self.assertEqual(result["_tasks"][0]["name"], task.name)

	def test_create_contact_from_call_log_basic(self):
		call = create_test_call_log(type="Incoming", from_number="+84912345678")

		contact_name = create_contact_from_call_log(
			call_log=frappe.as_json({"name": call.name}),
			contact_details=frappe.as_json({"full_name": "John Doe"}),
		)

		self.assertTrue(frappe.db.exists("CRM Student", contact_name))
		contact = frappe.get_doc("CRM Student", contact_name)
		self.assertEqual(contact.full_name, "John Doe")
		self.assertEqual(contact.phone, "0912345678")

		call.reload()
		self.assertTrue(call.has_link("CRM Student", contact_name))

	def test_create_contact_from_call_log_no_details(self):
		call = create_test_call_log(type="Incoming", from_number="+84987654321")

		contact_name = create_contact_from_call_log(call_log=frappe.as_json({"name": call.name}))

		contact = frappe.get_doc("CRM Student", contact_name)
		self.assertTrue(contact.full_name.startswith("Contact from call"))
		self.assertEqual(contact.phone, "0987654321")

	def test_create_contact_from_call_log_invalid_call_log(self):
		with self.assertRaises(frappe.DoesNotExistError):
			create_contact_from_call_log(call_log=frappe.as_json({"name": "invalid_name"}))

	def test_create_contact_from_call_log_permission_check(self):
		with self.assertRaises(frappe.ValidationError):
			create_contact_from_call_log(call_log=frappe.as_json({}))

	def test_call_log_status_filtering(self):
		completed_call = create_test_call_log(status="Completed", type="Incoming")
		failed_call = create_test_call_log(status="Failed", type="Outgoing")
		busy_call = create_test_call_log(status="Busy", type="Incoming")

		completed_names = [
			log.name for log in frappe.get_all("Call Log", filters={"status": "Completed"})
		]
		failed_names = [log.name for log in frappe.get_all("Call Log", filters={"status": "Failed"})]

		self.assertIn(completed_call.name, completed_names)
		self.assertIn(failed_call.name, failed_names)
		self.assertNotIn(busy_call.name, completed_names)
		self.assertNotIn(busy_call.name, failed_names)

	def test_call_log_with_telephony_medium(self):
		call = create_test_call_log(telephony_medium="Twilio")
		self.assertEqual(call.telephony_medium, "Twilio")

		call = create_test_call_log(telephony_medium="Exotel")
		self.assertEqual(call.telephony_medium, "Exotel")


def create_test_call_log(**kwargs):
	unique_id = kwargs.pop("id", str(uuid.uuid4())[:10])

	if "from_number" in kwargs:
		kwargs["from"] = kwargs.pop("from_number")

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
		"full_name": "Test CRM Student",
		"email": f"contact-{uuid.uuid4().hex[:8]}@example.com",
		"stage": "Interested",
	}
	data.update(kwargs)
	return frappe.get_doc(data).insert(ignore_permissions=True)
