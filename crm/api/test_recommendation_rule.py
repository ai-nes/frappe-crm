import uuid

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.action import _api_payload, _set_writable_fields, create_action, delete_action, update_action
from crm.api.action_type import create_action_type, delete_action_type
from crm.api.recommendation_rule import (
	archive_rule,
	create_rule,
	delete_rule,
	list_condition_fields,
	list_rules,
	preview_rule,
	publish_rule,
	update_rule,
)
from crm.fcrm.action_constraints import defaults_for_action
from crm.fcrm.action_type_registry import available_action_types, is_available_action_type


class _DocumentStub:
	def __init__(self):
		self.values = {}

	def set(self, fieldname, value):
		self.values[fieldname] = value


class TestRecommendationRuleApi(FrappeTestCase):
	def setUp(self):
		self._original_user = frappe.session.user
		frappe.set_user("Administrator")
		self.action = self._ensure_action()

	def tearDown(self):
		frappe.set_user(self._original_user)
		frappe.db.rollback()

	def _ensure_action(self):
		code = "SEND_RELEVANT_FAQ"
		if not frappe.db.exists("CRM Action Type", "INFORMATION"):
			frappe.get_doc(
				{
					"doctype": "CRM Action Type",
					"action_type": "INFORMATION",
					"display_name": "Thông tin",
					"enabled": 1,
					"sort_order": 20,
				}
			).insert(ignore_permissions=True)
		if not frappe.db.exists("CRM Action", code):
			defaults = defaults_for_action(code, "INFORMATION")
			return frappe.get_doc(
				{
					"doctype": "CRM Action",
					"code": code,
					"display_name": "Gửi FAQ phù hợp",
					"action_type": "INFORMATION",
					"purpose": "Cung cấp câu trả lời phù hợp",
					**defaults,
					"enabled": 1,
					"sort_order": 900,
				}
			).insert(ignore_permissions=True)
		action = frappe.get_doc("CRM Action", code)
		if not action.enabled:
			action.enabled = 1
			action.save(ignore_permissions=True)
		return action

	@staticmethod
	def _conditions():
		return {
			"all": [
				{"field": "student.lifecycle_stage", "operator": "equals", "value": "Lead"},
				{"field": "student.latest_score", "operator": "gte", "value": 70},
			],
			"any": [],
		}

	def test_action_api_serializes_json_arrays_before_document_save(self):
		doc = _DocumentStub()
		_set_writable_fields(
			doc,
			{"allowed_actors": ["Sale"], "allowed_time_slots": ["6-12", "12-18"]},
		)
		self.assertEqual(doc.values["allowed_actors"], '["Sale"]')
		self.assertEqual(doc.values["allowed_time_slots"], '["6-12", "12-18"]')

	def test_action_api_returns_json_fields_as_arrays(self):
		payload = _api_payload(
			{
				"name": "CALL",
				"allowed_actors": '["Sale"]',
				"allowed_time_slots": '["6-12"]',
			}
		)
		self.assertEqual(payload["allowed_actors"], ["Sale"])
		self.assertEqual(payload["allowed_time_slots"], ["6-12"])

	def test_action_api_handles_frappe_dict_rows(self):
		payload = _api_payload(
			frappe._dict(
				{
					"name": "CALL",
					"allowed_actors": '["Sale"]',
					"allowed_time_slots": '["6-12"]',
				}
			)
		)
		self.assertEqual(payload["allowed_actors"], ["Sale"])
		self.assertEqual(payload["allowed_time_slots"], ["6-12"])

	def test_custom_action_type_and_action_support_crud(self):
		action_type_code = f"CUSTOM_{uuid.uuid4().hex[:8].upper()}"
		action_code = f"CUSTOM_ACTION_{uuid.uuid4().hex[:8].upper()}"
		created_type = create_action_type(
			action_type=action_type_code,
			display_name="Custom Sales Actions",
			enabled=1,
			sort_order=999,
		)
		created_action = create_action(
			code=action_code,
			display_name="Custom Follow Up",
			action_type=action_type_code,
			purpose="Follow up using a custom configured action",
			default_channel="NONE",
			allowed_actors=["Sale"],
			allowed_time_slots=[],
			enabled=1,
			sort_order=999,
		)
		self.assertEqual(created_type["action_type"], action_type_code)
		self.assertEqual(created_action["code"], action_code)
		self.assertTrue(is_available_action_type(action_code))

		action_type_doc = frappe.get_doc("CRM Action Type", action_type_code)
		action_type_doc.enabled = 0
		action_type_doc.save(ignore_permissions=True)
		self.assertFalse(is_available_action_type(action_code))
		self.assertNotIn(action_code, available_action_types())
		with self.assertRaises(frappe.ValidationError):
			delete_action_type(action_type_code)
		action_type_doc.enabled = 1
		action_type_doc.save(ignore_permissions=True)

		updated_action = update_action(action_code, display_name="Updated Custom Follow Up")
		self.assertEqual(updated_action["display_name"], "Updated Custom Follow Up")
		self.assertEqual(delete_action(action_code), {"deleted": action_code})
		self.assertEqual(delete_action_type(action_type_code), {"deleted": action_type_code})

	def test_rule_crud_publish_update_and_archive(self):
		rule_key = f"test_rule_{uuid.uuid4().hex[:10]}"
		created = create_rule(
			rule_key=rule_key,
			display_name="Test Recommendation Rule",
			action_code=self.action.code,
			conditions=self._conditions(),
			stop_conditions=["student_lost"],
		)
		self.assertEqual(created["status"], "draft")
		self.assertEqual(created["enabled"], 0)
		self.assertEqual(created["conditions"], self._conditions())

		published = publish_rule(created["name"], expected_version=1)
		self.assertEqual(published["status"], "published")
		self.assertEqual(published["enabled"], 1)
		self.assertEqual(published["version"], 2)

		edited = update_rule(created["name"], display_name="Updated Rule")
		self.assertEqual(edited["status"], "draft")
		self.assertEqual(edited["enabled"], 0)
		self.assertEqual(edited["version"], 2)

		republished = publish_rule(created["name"], expected_version=2)
		self.assertEqual(republished["status"], "published")
		self.assertEqual(republished["version"], 3)

		archived = archive_rule(created["name"], reason="Test cleanup")
		self.assertEqual(archived["status"], "archived")
		self.assertEqual(archived["archive_reason"], "Test cleanup")

		listed = list_rules(search=rule_key)
		self.assertEqual(listed["total"], 1)
		self.assertEqual(listed["rules"][0]["rule_key"], rule_key)

	def test_rule_preview_and_condition_metadata(self):
		preview = preview_rule(
			rule={"action_code": self.action.code, "conditions": self._conditions(), "priority": "high"},
			context={"student": {"lifecycle_stage": "Lead", "latest_score": 82}},
		)
		self.assertTrue(preview["eligible"])
		self.assertEqual(preview["action"]["code"], self.action.code)

		metadata = list_condition_fields()
		self.assertTrue(any(field["field"] == "student.lifecycle_stage" for field in metadata["fields"]))

	def test_draft_rule_can_be_deleted(self):
		rule_key = f"test_delete_rule_{uuid.uuid4().hex[:10]}"
		created = create_rule(
			rule_key=rule_key,
			display_name="Delete test rule",
			action_code=self.action.code,
			conditions=self._conditions(),
		)
		self.assertEqual(delete_rule(created["name"]), {"deleted": created["name"]})
		self.assertFalse(frappe.db.exists("CRM Recommendation Rule", created["name"]))

	def test_published_and_archived_rules_cannot_be_deleted(self):
		published_key = f"test_published_delete_{uuid.uuid4().hex[:10]}"
		published = create_rule(
			rule_key=published_key,
			display_name="Published delete test",
			action_code=self.action.code,
			conditions=self._conditions(),
		)
		publish_rule(published["name"], expected_version=1)
		with self.assertRaises(frappe.PermissionError):
			delete_rule(published["name"])

		archived_key = f"test_archived_delete_{uuid.uuid4().hex[:10]}"
		archived = create_rule(
			rule_key=archived_key,
			display_name="Archived delete test",
			action_code=self.action.code,
			conditions=self._conditions(),
		)
		publish_rule(archived["name"], expected_version=1)
		archive_rule(archived["name"], reason="Test cleanup")
		with self.assertRaises(frappe.PermissionError):
			delete_rule(archived["name"])
