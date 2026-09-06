from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import task as task_api
from crm.api.task import create_task, delete_task, get_task, list_sales_tasks, list_tasks, update_task


class TestTaskApi(FrappeTestCase):
	def setUp(self):
		self._original_user = frappe.session.user
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user(self._original_user)
		frappe.db.rollback()

	def test_task_crud_is_scoped_to_reference(self):
		contact = frappe.get_doc(
			{
				"doctype": "CRM Contact",
				"full_name": "Task API Contact",
				"email": "task-api-contact@example.com",
				"stage": "Interested",
			}
		).insert(ignore_permissions=True)

		created = create_task(
			"CRM Contact",
			contact.name,
			"Initial task",
			description="Follow up",
			priority="High",
			status="Todo",
		)
		self.assertEqual(created["reference_doctype"], "CRM Contact")
		self.assertEqual(created["reference_docname"], contact.name)

		listed = list_tasks("CRM Contact", contact.name)
		self.assertEqual(listed["total"], 1)
		self.assertEqual(listed["tasks"][0]["name"], created["name"])

		fetched = get_task(created["name"])
		self.assertEqual(fetched["title"], "Initial task")

		updated = update_task(created["name"], title="Updated task", status="Done")
		self.assertEqual(updated["title"], "Updated task")
		self.assertEqual(updated["status"], "Done")

		self.assertEqual(delete_task(created["name"]), {"deleted": created["name"]})
		self.assertFalse(frappe.db.exists("Task", created["name"]))

	def test_task_permissions_cover_ctv_sale_create_and_update(self):
		permissions = frappe.get_meta("Task").permissions

		for role in ("CTV Sale",):
			role_permissions = [permission for permission in permissions if permission.role == role]
			self.assertTrue(role_permissions, f"Task must define permissions for {role}")
			self.assertTrue(
				any(
					permission.create and permission.read and permission.write
					for permission in role_permissions
				)
			)

	def test_task_permission_query_conditions_are_reference_scoped(self):
		with (
			patch.object(
				task_api,
				"_permission_condition",
				side_effect=[
					"student_scope.owner_staff = 'STAFF-001'",
					"contact_scope.owner_staff = 'STAFF-001'",
				],
			),
			patch.object(frappe, "get_roles", return_value=["Sale"]),
		):
			condition = task_api.get_permission_query_conditions("sale@example.com")

		self.assertIn("EXISTS", condition)
		self.assertIn("`tabCRM Student`", condition)
		self.assertIn("`tabCRM Contact`", condition)
		self.assertIn("`tabTask`.reference_doctype", condition)

	def test_task_has_permission_checks_reference_scope(self):
		doc = frappe._dict(
			doctype="Task",
			reference_doctype="CRM Student",
			reference_docname="ENR-2026-00001",
			name="TASK-00001",
		)
		with (
			patch.object(task_api, "_check_reference_access") as check_reference,
			patch.object(frappe, "get_roles", return_value=["Sale"]),
		):
			self.assertTrue(task_api.has_permission(doc, user="sale@example.com", ptype="write"))

		check_reference.assert_called_once_with("CRM Student", "ENR-2026-00001", "read")

	@patch("crm.api.task._require_sales_task_access", return_value="Administrator")
	@patch("crm.api.task._aggregate_tasks_sql", return_value=("SELECT 1", []))
	def test_sales_task_aggregate_is_paginated_and_serialized(self, _aggregate, _access):
		rows = [
			frappe._dict(
				task_id="Task:1",
				name="1",
				doctype="Task",
				task_type="Task",
				title="Call student",
				description=None,
				status="Todo",
				priority="High",
				due_date="2999-09-05 10:00:00",
				assigned_to="Administrator",
				assigned_to_name="Administrator",
				student="ENR-2026-00001",
				student_name="Test Student",
				reference_doctype="CRM Student",
				reference_docname="ENR-2026-00001",
				linked_interaction=None,
				action=None,
				action_type=None,
				origin=None,
				created_at="2026-09-04 09:00:00",
				modified="2026-09-04 09:00:00",
			)
		]
		with (
			patch.object(
				frappe.db,
				"sql",
				side_effect=[[frappe._dict(total=3)], rows],
			) as sql,
			patch(
				"crm.api.task.now_datetime",
				return_value=frappe.utils.get_datetime("2026-09-05 00:00:00"),
			),
		):
			result = list_sales_tasks(start=1, page_length=1)

		self.assertEqual(result["total"], 3)
		self.assertEqual(result["total_count"], 3)
		self.assertEqual(result["start"], 1)
		self.assertEqual(result["page_length"], 1)
		self.assertTrue(result["has_more"])
		self.assertEqual(result["tasks"][0]["task_id"], "Task:1")
		self.assertFalse(result["tasks"][0]["is_overdue"])
		self.assertEqual(sql.call_count, 2)
		self.assertEqual(sql.call_args_list[1].args[1][-2:], [1, 1])
		_aggregate.assert_called_once_with("Administrator", None, None, None, "all", None)

	@patch("crm.api.task._permission_condition", return_value="1=1")
	def test_sales_task_aggregate_uses_canonical_action_items_only(self, _permission):
		query, values = task_api._aggregate_tasks_sql("Administrator", None, None, None, "all", None)

		self.assertIn("FROM `tabCRM Action Item` action_item", query)
		self.assertEqual(values, [])
		self.assertEqual(_permission.call_count, 1)

	@patch("crm.api.task._permission_condition", return_value="1=1")
	def test_sales_task_type_filter_rejects_legacy_task_source(self, _permission):
		query, values = task_api._aggregate_tasks_sql("Administrator", None, None, None, "all", "Task")

		self.assertEqual(query, "")
		self.assertEqual(values, [])
