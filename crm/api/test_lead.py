from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import frappe

from crm.api import lead as lead_api


class TestLeadCrudApi(TestCase):
	def setUp(self):
		self.meta = SimpleNamespace(
			fields=[
				SimpleNamespace(fieldname="lead_status", fieldtype="Select", read_only=0),
				SimpleNamespace(fieldname="student_name", fieldtype="Data", read_only=0),
				SimpleNamespace(fieldname="phone", fieldtype="Data", read_only=0),
				SimpleNamespace(fieldname="notes", fieldtype="Text", read_only=0),
				SimpleNamespace(fieldname="enrollment_status", fieldtype="Link", read_only=0),
				SimpleNamespace(fieldname="lead_code", fieldtype="Data", read_only=1),
				SimpleNamespace(fieldname="status_change_log", fieldtype="Table", read_only=1),
				SimpleNamespace(fieldname="section_identity", fieldtype="Section Break", read_only=0),
			]
		)

	def test_list_returns_leads_and_validates_query(self):
		with (
			patch.object(lead_api.frappe, "get_meta", return_value=self.meta),
			patch.object(
				lead_api,
				"paged_list",
				return_value={"total": 1, "start": 0, "page_length": 20, "rows": [{"name": "LEAD-1"}]},
			) as paged_list,
		):
			result = lead_api.list_leads(
				filters='{"lead_status": "New"}',
				search="An",
				order_by="modified desc",
			)

		self.assertEqual(result["leads"], [{"name": "LEAD-1"}])
		self.assertEqual(result["total"], 1)
		self.assertEqual(paged_list.call_args.kwargs["filters"], {"lead_status": "New"})
		self.assertEqual(len(paged_list.call_args.kwargs["or_filters"]), len(lead_api.SEARCH_FIELDS))
		self.assertEqual(paged_list.call_args.kwargs["order_by"], "modified desc, name desc")

	def test_list_rejects_unknown_filters_and_unsafe_order(self):
		with patch.object(lead_api.frappe, "get_meta", return_value=self.meta):
			with self.assertRaises(frappe.ValidationError):
				lead_api.list_leads(filters='{"not_a_lead_field": "x"}')
			with self.assertRaises(frappe.ValidationError):
				lead_api.list_leads(filters='{"status_change_log": "x"}')
			with self.assertRaises(frappe.ValidationError):
				lead_api.list_leads(order_by="modified desc; delete from tabCRM Lead")

	def test_payload_rejects_server_managed_and_unknown_fields(self):
		with patch.object(lead_api.frappe, "get_meta", return_value=self.meta):
			with self.assertRaises(frappe.ValidationError):
				lead_api._validate_payload({"lead_code": "LD-2026-00001"}, operation="create")
			with self.assertRaises(frappe.ValidationError):
				lead_api._validate_payload({"unknown": "value"}, operation="create")

	def test_update_rejects_lifecycle_field_and_empty_payload(self):
		with patch.object(lead_api.frappe, "get_meta", return_value=self.meta):
			with self.assertRaises(frappe.PermissionError):
				lead_api._validate_payload({"enrollment_status": "PROSPECT"}, operation="update")
			with self.assertRaises(frappe.ValidationError):
				lead_api.update_lead("LEAD-1", fields={})

	def test_get_checks_read_permission_and_serializes_document(self):
		doc = Mock()
		doc.as_dict.return_value = {"name": "LEAD-1", "student_name": "An"}
		with patch.object(lead_api.frappe, "get_doc", return_value=doc):
			result = lead_api.get_lead("LEAD-1")

		self.assertEqual(result["name"], "LEAD-1")
		doc.check_permission.assert_called_once_with("read")

	def test_create_update_delete_use_document_permissions_and_lifecycle(self):
		created = Mock()
		created.as_dict.return_value = {"name": "LEAD-1", "student_name": "An"}
		created.set.side_effect = lambda fieldname, value: setattr(created, fieldname, value)
		updated = Mock()
		updated.as_dict.return_value = {"name": "LEAD-1", "student_name": "Updated"}
		updated.set.side_effect = lambda fieldname, value: setattr(updated, fieldname, value)
		with (
			patch.object(lead_api.frappe, "get_meta", return_value=self.meta),
			patch.object(lead_api.frappe, "new_doc", return_value=created),
			patch.object(lead_api.frappe, "get_doc", return_value=updated),
		):
			self.assertEqual(lead_api.create_lead({"student_name": "An"})["name"], "LEAD-1")
			self.assertEqual(
				lead_api.update_lead("LEAD-1", {"student_name": "Updated"})["student_name"],
				"Updated",
			)
			self.assertEqual(lead_api.delete_lead("LEAD-1"), {"deleted": "LEAD-1"})

		created.insert.assert_called_once_with()
		updated.check_permission.assert_any_call("write")
		updated.save.assert_called_once_with()
		updated.check_permission.assert_any_call("delete")
		updated.delete.assert_called_once_with()

	def test_create_and_update_accept_direct_fields_but_reject_mixed_payloads(self):
		with patch.object(lead_api.frappe, "get_meta", return_value=self.meta):
			self.assertEqual(
				lead_api._payload_from_arguments(None, {"student_name": "An", "cmd": "ignored"}),
				{"student_name": "An"},
			)
			with self.assertRaises(frappe.ValidationError):
				lead_api._payload_from_arguments({"student_name": "An"}, {"notes": "Mixed"})
