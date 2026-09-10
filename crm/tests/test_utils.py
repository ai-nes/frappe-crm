import time
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.resource import normalize_phone_filters
from crm.utils import (
	_get_communication_status,
	_should_update_modified,
	are_same_phone_number,
	create_crm_contact_from_incoming_email,
	get_phone_lookup_terms,
	normalize_phone_for_lookup,
	on_communication_update,
	parse_phone_number,
	seconds_to_duration,
)


class TestUtils(FrappeTestCase):
	def test_seconds_to_duration(self):
		self.assertEqual(seconds_to_duration(3661), "1h 1m 1s")
		self.assertEqual(seconds_to_duration(3660), "1h 1m")
		self.assertEqual(seconds_to_duration(3601), "1h 1s")
		self.assertEqual(seconds_to_duration(61), "1m 1s")
		self.assertEqual(seconds_to_duration(0), "0s")
		self.assertEqual(seconds_to_duration(None), "0s")

	def test_are_same_phone_number_normalized_input(self):
		self.assertTrue(are_same_phone_number("+91 9845552671", "9845552671"))
		self.assertTrue(are_same_phone_number("+1 415 555 2671", "4155552671", default_region="US"))
		self.assertFalse(are_same_phone_number("+1 415 555 2671", "4155552671"))
		self.assertFalse(are_same_phone_number("12345", "67890"))

	def test_are_same_phone_number_validate_false(self):
		self.assertTrue(
			are_same_phone_number(
				"+1 415 555 2671",
				"+1 415 555 2671",
				default_region="US",
				validate=False,
			)
		)

	def test_parse_phone_number(self):
		result = parse_phone_number("+919845552671")
		self.assertTrue(result["success"])
		self.assertEqual(result["country_code"], 91)
		self.assertEqual(result["country"], "IN")
		self.assertIn("E164", result["formats"])

		result = parse_phone_number("not-a-number")
		self.assertFalse(result["success"])
		self.assertIn("error", result)

	def test_normalize_vietnam_phone_for_lookup(self):
		self.assertEqual(normalize_phone_for_lookup("+84 901 100 001"), "0901100001")
		self.assertEqual(normalize_phone_for_lookup("84-901-100-001"), "0901100001")
		self.assertEqual(normalize_phone_for_lookup("0901100001"), "0901100001")
		self.assertEqual(normalize_phone_for_lookup("901100001"), "0901100001")

	def test_vietnam_phone_lookup_terms_include_zero_and_country_code_forms(self):
		self.assertEqual(
			get_phone_lookup_terms("+84 901 100 001"),
			["0901100001", "84901100001", "901100001"],
		)

	def test_normalize_resource_phone_filter_list(self):
		self.assertEqual(
			normalize_phone_filters('[["phone", "=", "+84 901 100 001"]]'),
			[["phone", "in", ["0901100001", "84901100001", "901100001"]]],
		)

	def test_normalize_resource_phone_filter_list_with_doctype(self):
		self.assertEqual(
			normalize_phone_filters(
				'[["CRM Lead", "phone", "=", "+84 901 100 001"]]'
			),
			[
				[
					"CRM Lead",
					"phone",
					"in",
					["0901100001", "84901100001", "901100001"],
				]
			],
		)

	def test_normalize_resource_phone_filter_dict(self):
		self.assertEqual(
			normalize_phone_filters({"phone": "+84 901 100 001", "email": "a@example.com"}),
			{
				"phone": ["in", ["0901100001", "84901100001", "901100001"]],
				"email": "a@example.com",
			},
		)


class TestUpdateModifiedTimestamp(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self._enqueue_patch = patch("frappe.enqueue", self._immediate_enqueue)
		self._enqueue_patch.start()

	@staticmethod
	def _immediate_enqueue(method, **kwargs):
		from crm.utils import update_modified_background

		if method == update_modified_background or (
			isinstance(method, str) and method.endswith("update_modified_background")
		):
			return update_modified_background(kwargs["doctype"], kwargs["docname"])
		return None

	def tearDown(self):
		frappe.db.rollback()
		self._enqueue_patch.stop()
		super().tearDown()

	def _make_contact(self, suffix=""):
		return frappe.get_doc(
			{
				"doctype": "CRM Student",
				"full_name": "Timestamp Contact" + suffix,
				"email": f"timestamp{suffix}@example.com",
				"stage": "Interested",
			}
		).insert(ignore_permissions=True)

	def test_timestamp_updated_on_new_communication(self):
		frappe.db.set_single_value("FCRM Settings", "update_timestamp_on_new_communication", 1)
		contact = self._make_contact("comm")
		original_modified = frappe.db.get_value("CRM Student", contact.name, "modified")

		time.sleep(0.1)
		comm = _make_communication("Received", contact)
		comm.insert(ignore_permissions=True)

		updated_modified = frappe.db.get_value("CRM Student", contact.name, "modified")
		self.assertGreater(updated_modified, original_modified)

	def test_timestamp_not_updated_when_setting_disabled(self):
		frappe.db.set_single_value("FCRM Settings", "update_timestamp_on_new_communication", 0)
		contact = self._make_contact("disabled")
		original_modified = frappe.db.get_value("CRM Student", contact.name, "modified")

		time.sleep(0.1)
		comm = _make_communication("Received", contact)
		comm.insert(ignore_permissions=True)

		updated_modified = frappe.db.get_value("CRM Student", contact.name, "modified")
		self.assertEqual(updated_modified, original_modified)

	def test_timestamp_direct_call_updates_contact(self):
		frappe.db.set_single_value("FCRM Settings", "update_timestamp_on_new_communication", 1)
		contact = self._make_contact("direct")
		comm = _make_communication("Received", contact)
		comm.insert(ignore_permissions=True)

		before = frappe.db.get_value("CRM Student", contact.name, "modified")
		time.sleep(0.1)
		on_communication_update(comm)
		after = frappe.db.get_value("CRM Student", contact.name, "modified")
		self.assertGreaterEqual(after, before)

	def test_timestamp_not_updated_for_other_reference(self):
		frappe.db.set_single_value("FCRM Settings", "update_timestamp_on_new_communication", 1)
		comm = frappe.get_doc(
			{
				"doctype": "Communication",
				"communication_type": "Communication",
				"communication_medium": "Email",
				"sent_or_received": "Received",
				"subject": "Wrong reference",
				"reference_doctype": "Contact",
				"reference_name": "CONTACT-0001",
			}
		)
		self.assertFalse(_should_update_modified(comm))


class TestUpdateCommunicationStatus(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _make_contact(self, suffix=""):
		return frappe.get_doc(
			{
				"doctype": "CRM Student",
				"full_name": "Status Contact" + suffix,
				"email": f"status{suffix}@example.com",
				"stage": "Interested",
			}
		).insert(ignore_permissions=True)

	def test_status_set_to_open_on_received_communication(self):
		frappe.db.set_single_value("FCRM Settings", "auto_reopen_on_new_communication", 1)
		contact = self._make_contact("recv")
		communication = _make_communication("Received", contact)

		status = _get_communication_status(communication)
		self.assertEqual(status, "Open")

	def test_status_set_to_replied_on_sent_communication(self):
		frappe.db.set_single_value("FCRM Settings", "auto_mark_replied_on_response", 1)
		contact = self._make_contact("sent")
		communication = _make_communication("Sent", contact)

		status = _get_communication_status(communication)
		self.assertEqual(status, "Replied")

	def test_status_not_updated_when_settings_disabled(self):
		frappe.db.set_single_value("FCRM Settings", "auto_reopen_on_new_communication", 0)
		frappe.db.set_single_value("FCRM Settings", "auto_mark_replied_on_response", 0)
		contact = self._make_contact("off")
		communication = _make_communication("Received", contact)

		self.assertIsNone(_get_communication_status(communication))

	def test_status_not_updated_for_non_communication_doctype(self):
		comment = frappe.get_doc(
			{
				"doctype": "Comment",
				"comment_type": "Comment",
				"reference_doctype": "CRM Student",
				"reference_name": "CRM-CONTACT-0001",
				"content": "test",
			}
		)
		self.assertIsNone(_get_communication_status(comment))


class TestCreateCRMContactFromIncomingEmail(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _make_email_account(self, create_contact=1):
		email_account = frappe.get_doc(
			{
				"doctype": "Email Account",
				"email_account_name": "Test CRM Incoming",
				"email_id": "test-crm-incoming@example.com",
				"enable_incoming": 1,
				"create_crm_contact_from_incoming_email": create_contact,
			}
		)
		email_account.flags.ignore_mandatory = True
		email_account.flags.ignore_validate = True
		email_account.insert(ignore_permissions=True)
		return email_account

	def _incoming_comm(self, sender, email_account_name, sender_full_name=None, **kwargs):
		doc = frappe.get_doc(
			{
				"doctype": "Communication",
				"communication_type": "Communication",
				"communication_medium": "Email",
				"sent_or_received": "Received",
				"subject": "Test Incoming Email",
				"sender": sender,
				"email_account": email_account_name,
				**kwargs,
			}
		)
		if sender_full_name:
			doc.sender_full_name = sender_full_name
		return doc

	def test_contact_created_from_incoming_email(self):
		email_account = self._make_email_account()
		doc = self._incoming_comm(
			"newcontact@example.com",
			email_account.name,
			sender_full_name="New Contact",
		)
		doc.insert(ignore_permissions=True)

		self.assertTrue(frappe.db.exists("CRM Student", {"email": "newcontact@example.com"}))

	def test_contact_not_created_when_setting_disabled(self):
		email_account = self._make_email_account(create_contact=0)
		doc = self._incoming_comm("disabled@example.com", email_account.name)
		doc.insert(ignore_permissions=True)

		self.assertFalse(frappe.db.exists("CRM Student", {"email": "disabled@example.com"}))

	def test_contact_not_created_when_communication_already_referenced(self):
		email_account = self._make_email_account()
		existing = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"full_name": "Referenced",
				"email": "referenced-source@example.com",
				"stage": "Interested",
			}
		).insert(ignore_permissions=True)

		doc = self._incoming_comm(
			"referenced@example.com",
			email_account.name,
			reference_doctype="CRM Student",
			reference_name=existing.name,
		)
		doc.insert(ignore_permissions=True)

		self.assertFalse(frappe.db.exists("CRM Student", {"email": "referenced@example.com"}))

	def test_contact_not_created_when_contact_already_exists_for_sender(self):
		email_account = self._make_email_account()
		frappe.get_doc(
			{
				"doctype": "CRM Student",
				"full_name": "Existing",
				"email": "dupe@example.com",
				"stage": "Interested",
			}
		).insert(ignore_permissions=True)

		doc = self._incoming_comm("dupe@example.com", email_account.name)
		doc.insert(ignore_permissions=True)

		self.assertEqual(frappe.db.count("CRM Student", {"email": "dupe@example.com"}), 1)

	def test_contact_full_name_from_sender_full_name(self):
		email_account = self._make_email_account()
		doc = self._incoming_comm("fullname@example.com", email_account.name, sender_full_name="Jane Doe")
		create_crm_contact_from_incoming_email(doc)

		full_name = frappe.db.get_value("CRM Student", {"email": "fullname@example.com"}, "full_name")
		self.assertEqual(full_name, "Jane Doe")

	def test_contact_full_name_falls_back_to_email_prefix(self):
		email_account = self._make_email_account()
		doc = self._incoming_comm("prefix@example.com", email_account.name)
		create_crm_contact_from_incoming_email(doc)

		full_name = frappe.db.get_value("CRM Student", {"email": "prefix@example.com"}, "full_name")
		self.assertEqual(full_name, "prefix")

	def test_communication_linked_back_to_created_contact(self):
		email_account = self._make_email_account()
		doc = self._incoming_comm("linked@example.com", email_account.name, sender_full_name="Link Test")
		create_crm_contact_from_incoming_email(doc)

		self.assertEqual(doc.reference_doctype, "CRM Student")
		contact_name = frappe.db.get_value("CRM Student", {"email": "linked@example.com"}, "name")
		self.assertEqual(doc.reference_name, contact_name)

	def test_contact_source_set_to_email_when_source_exists(self):
		if not frappe.db.exists("CRM Lead Source", "Email"):
			frappe.get_doc({"doctype": "CRM Lead Source", "source_name": "Email"}).insert(
				ignore_permissions=True
			)

		email_account = self._make_email_account()
		doc = self._incoming_comm("leadsource@example.com", email_account.name)
		create_crm_contact_from_incoming_email(doc)

		source = frappe.db.get_value("CRM Student", {"email": "leadsource@example.com"}, "source")
		self.assertEqual(source, "Email")


def _make_communication(sent_or_received, contact):
	return frappe.get_doc(
		{
			"doctype": "Communication",
			"communication_type": "Communication",
			"communication_medium": "Email",
			"sent_or_received": sent_or_received,
			"subject": f"Test {sent_or_received}",
			"reference_doctype": "CRM Student",
			"reference_name": contact.name,
		}
	)
