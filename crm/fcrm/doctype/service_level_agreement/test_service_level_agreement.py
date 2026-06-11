# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import uuid

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.doctype.service_level_agreement.utils import get_sla


class TestServiceLevelAgreement(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_create_sla_for_crm_contact(self):
		sla = create_test_sla()

		self.assertEqual(sla.apply_on, "CRM Contact")
		self.assertEqual(sla.priorities[0].priority, "Open")
		self.assertEqual(sla.priorities[1].priority, "Replied")

	def test_get_sla_returns_matching_crm_contact_sla(self):
		email = f"sla-{uuid.uuid4().hex[:8]}@example.com"
		sla = create_test_sla(condition=f"doc.email == '{email}'")
		contact = frappe.new_doc("CRM Contact")
		contact.full_name = "SLA Match"
		contact.email = email
		contact.stage = "Interested"
		contact.communication_status = "Open"

		result = get_sla(contact)

		self.assertEqual(result.name, sla.name)

	def test_get_sla_skips_non_matching_condition(self):
		email = f"sla-{uuid.uuid4().hex[:8]}@example.com"
		create_test_sla(condition=f"doc.email == '{email}'")
		contact = frappe.new_doc("CRM Contact")
		contact.full_name = "SLA No Match"
		contact.email = f"other-{uuid.uuid4().hex[:8]}@example.com"
		contact.stage = "Interested"
		contact.communication_status = "Open"

		result = get_sla(contact)

		if result:
			self.assertNotEqual(result.condition, f"doc.email == '{email}'")

	def test_crm_contact_applies_sla_on_insert(self):
		email = f"sla-{uuid.uuid4().hex[:8]}@example.com"
		sla = create_test_sla(condition=f"doc.email == '{email}'")

		contact = frappe.get_doc(
			{
				"doctype": "CRM Contact",
				"full_name": "Apply SLA",
				"email": email,
				"stage": "Interested",
			}
		).insert(ignore_permissions=True)

		self.assertEqual(contact.sla, sla.name)
		self.assertEqual(contact.communication_status, "Open")
		self.assertEqual(contact.sla_status, "First Response Due")
		self.assertTrue(contact.sla_creation)
		self.assertTrue(contact.response_by)

	def test_crm_contact_tracks_first_response(self):
		email = f"sla-{uuid.uuid4().hex[:8]}@example.com"
		create_test_sla(condition=f"doc.email == '{email}'")
		contact = frappe.get_doc(
			{
				"doctype": "CRM Contact",
				"full_name": "Response SLA",
				"email": email,
				"stage": "Interested",
			}
		).insert(ignore_permissions=True)

		contact.communication_status = "Replied"
		contact.save(ignore_permissions=True)

		self.assertTrue(contact.first_responded_on)
		self.assertIsNotNone(contact.first_response_time)
		self.assertEqual(contact.sla_status, "Fulfilled")

	def test_invalid_condition_fails_validation(self):
		sla = frappe.get_doc(
			{
				"doctype": "Service Level Agreement",
				"sla_name": "Invalid SLA",
				"enabled": 1,
				"apply_on": "CRM Contact",
				"condition": "doc.email ==",
				"priorities": [
					{
						"priority": "Open",
						"default_priority": 1,
						"first_response_time": 3600,
					}
				],
				"working_hours": [
					{"workday": "Monday", "start_time": "00:00:00", "end_time": "23:59:59"}
				],
			}
		)

		with self.assertRaises(frappe.ValidationError):
			sla.insert(ignore_permissions=True)


def create_test_sla(**kwargs):
	name = kwargs.pop("sla_name", f"Test SLA {uuid.uuid4().hex[:8]}")
	condition = kwargs.pop("condition", None)
	data = {
		"doctype": "Service Level Agreement",
		"sla_name": name,
		"enabled": 1,
		"default": 0,
		"apply_on": "CRM Contact",
		"condition": condition,
		"priorities": [
			{
				"priority": "Open",
				"default_priority": 1,
				"first_response_time": 3600,
			},
			{
				"priority": "Replied",
				"first_response_time": 3600,
			},
		],
		"working_hours": [
			{"workday": "Monday", "start_time": "00:00:00", "end_time": "23:59:59"},
			{"workday": "Tuesday", "start_time": "00:00:00", "end_time": "23:59:59"},
			{"workday": "Wednesday", "start_time": "00:00:00", "end_time": "23:59:59"},
			{"workday": "Thursday", "start_time": "00:00:00", "end_time": "23:59:59"},
			{"workday": "Friday", "start_time": "00:00:00", "end_time": "23:59:59"},
			{"workday": "Saturday", "start_time": "00:00:00", "end_time": "23:59:59"},
			{"workday": "Sunday", "start_time": "00:00:00", "end_time": "23:59:59"},
		],
	}
	data.update(kwargs)
	return frappe.get_doc(data).insert(ignore_permissions=True)
