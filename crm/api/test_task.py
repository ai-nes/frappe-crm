from unittest.mock import call, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import task as task_api
from crm.api.task import create_task, delete_task, get_task, list_sales_tasks, list_tasks, update_task
from crm.fcrm.test_permissions import TestSharedScopingPermissions


class TestTaskApi(FrappeTestCase):
	def setUp(self):
		self._original_user = frappe.session.user
		frappe.set_user("Administrator")
		self._campus = TestSharedScopingPermissions._make_campus(self, "_Test Task Assignee Campus")
		self._department = TestSharedScopingPermissions._get_or_create_department(
			self, "_Test Task Assignee Department", self._campus
		)
		self._assignees = [
			TestSharedScopingPermissions._make_user_and_staff(
				self, f"_Test Task Assignee {index}", roles=["Sale"]
			)
			for index in range(1, 5)
		]

	def tearDown(self):
		frappe.set_user(self._original_user)
		frappe.db.rollback()

	def test_task_crud_is_scoped_to_reference(self):
		contact = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"full_name": "Task API Contact",
				"email": "task-api-contact@example.com",
				"stage": "Interested",
			}
		).insert(ignore_permissions=True)

		created = create_task(
			"CRM Student",
			contact.name,
			"Initial task",
			description="Follow up",
			priority="High",
			status="Todo",
		)
		self.assertEqual(created["reference_doctype"], "CRM Student")
		self.assertEqual(created["reference_docname"], contact.name)

		listed = list_tasks("CRM Student", contact.name)
		self.assertEqual(listed["total"], 1)
		self.assertEqual(listed["tasks"][0]["name"], created["name"])

		fetched = get_task(created["name"])
		self.assertEqual(fetched["title"], "Initial task")

		updated = update_task(created["name"], title="Updated task", status="Done")
		self.assertEqual(updated["title"], "Updated task")
		self.assertEqual(updated["status"], "Done")

		self.assertEqual(delete_task(created["name"]), {"deleted": created["name"]})
		self.assertFalse(frappe.db.exists("Task", created["name"]))

	def test_student_task_crud_uses_action_item_with_task_dto(self):
		student = frappe.get_all("CRM Student", fields=["name"], limit_page_length=1)[0].name

		created = create_task(
			"CRM Student",
			student,
			"Compatibility task",
			description="Keep the old Task API contract.",
			priority="High",
			status="Todo",
		)

		self.assertTrue(frappe.db.exists("CRM Action Item", created["name"]))
		self.assertEqual(
			frappe.db.get_value("CRM Action Item", created["name"], "objective"),
			"Compatibility task",
		)
		self.assertEqual(created["priority"], "High")
		self.assertEqual(created["status"], "Todo")
		self.assertEqual(created["action_code"], "CREATE_TASK")
		self.assertEqual(created["reference_doctype"], "CRM Student")
		self.assertEqual(created["reference_docname"], student)

		listed = list_tasks("CRM Student", student)
		self.assertIn(created["name"], {row["name"] for row in listed["tasks"]})
		listed_row = next(row for row in listed["tasks"] if row["name"] == created["name"])
		self.assertEqual(listed_row["reference_doctype"], "CRM Student")
		self.assertEqual(listed_row["action_code"], "CREATE_TASK")

		updated = update_task(created["name"], title="Updated compatibility task", status="Done")
		self.assertEqual(updated["title"], "Updated compatibility task")
		self.assertEqual(updated["status"], "Done")

		self.assertEqual(delete_task(created["name"]), {"deleted": created["name"]})
		self.assertTrue(frappe.db.get_value("CRM Action Item", created["name"], "legacy_task_deleted"))
		self.assertNotIn(
			created["name"], {row["name"] for row in list_tasks("CRM Student", student)["tasks"]}
		)

	def test_segment_task_crud_uses_segment_reference(self):
		segment = frappe.get_doc({"doctype": "CRM Segment", "title": "Task API Segment"}).insert(
			ignore_permissions=True
		)

		created = create_task("CRM Segment", segment.name, "Review segment audience", status="Todo")
		self.assertTrue(frappe.db.exists("CRM Action Item", created["name"]))
		self.assertFalse(frappe.db.exists("Task", created["name"]))
		self.assertEqual(frappe.db.get_value("CRM Action Item", created["name"], "segment"), segment.name)
		self.assertEqual(created["reference_doctype"], "CRM Segment")
		self.assertEqual(created["reference_docname"], segment.name)

		listed = list_tasks("CRM Segment", segment.name)
		self.assertEqual(listed["total"], 1)
		self.assertEqual(listed["tasks"][0]["name"], created["name"])

		updated = update_task(created["name"], title="Review updated segment")
		self.assertEqual(updated["title"], "Review updated segment")
		self.assertEqual(delete_task(created["name"]), {"deleted": created["name"]})
		self.assertTrue(frappe.db.get_value("CRM Action Item", created["name"], "legacy_task_deleted"))

	def test_legacy_lead_reference_resolves_to_canonical_student(self):
		lead = frappe._dict(name="LEAD-1")
		with (
			patch.object(task_api, "_check_reference_access", return_value=lead) as check_reference,
			patch.object(task_api, "canonical_student", return_value="STU-1"),
		):
			self.assertEqual(task_api._action_target("CRM Lead", "LEAD-1"), ("STU-1", None))

		check_reference.assert_has_calls(
			[
				call("CRM Lead", "LEAD-1", "read"),
				call("CRM Student", "STU-1", "read"),
			]
		)

	def test_student_task_assignee_accepts_user_and_staff_values(self):
		student = frappe.get_all("CRM Student", fields=["name"], limit_page_length=1)[0].name

		for user, staff_name in self._assignees:
			staff = frappe.db.get_value("CRM Staff", {"user": user}, ["name", "full_name"], as_dict=True)
			self.assertEqual(staff.name, staff_name)

			for assigned_to in (user, staff.name, staff.full_name):
				created = create_task(
					"CRM Student",
					student,
					f"Assignee compatibility: {assigned_to}",
					assigned_to=assigned_to,
				)
				self.assertEqual(created["assigned_to"], user)
				self.assertEqual(delete_task(created["name"]), {"deleted": created["name"]})

			created = create_task(
				"CRM Student",
				student,
				f"Assignee object compatibility: {user}",
				assigned_to={"name": user, "full_name": staff.full_name},
			)
			self.assertEqual(created["assigned_to"], user)
			self.assertEqual(delete_task(created["name"]), {"deleted": created["name"]})

	def test_list_tasks_without_reference_lists_action_items(self):
		student = frappe.get_all("CRM Student", fields=["name"], limit_page_length=1)[0].name
		created = create_task("CRM Student", student, "Global task list compatibility")

		listed = list_tasks(search="Global task list compatibility")

		self.assertEqual(listed["total"], 1)
		self.assertEqual(listed["tasks"][0]["name"], created["name"])
		self.assertEqual(listed["tasks"][0]["reference_doctype"], "CRM Student")
		self.assertEqual(delete_task(created["name"]), {"deleted": created["name"]})

	def test_action_item_task_updates_check_student_scope(self):
		action = frappe._dict(
			doctype="CRM Action Item",
			name="ACT-TASK-SCOPE",
			student="STU-2026-00001",
			contact="CRM-CONTACT-001",
			objective="Scoped task",
			state="pending",
			priority="medium",
		)
		with (
			patch.object(task_api, "_action_item_for_task", return_value=action),
			patch.object(task_api, "_check_reference_access") as check_reference,
			patch.object(task_api, "update_manual_action"),
			patch.object(frappe, "get_doc", return_value=action),
		):
			updated = update_task(action.name, title="Updated scoped task")

		self.assertEqual(updated["title"], "Scoped task")
		check_reference.assert_called_once_with("CRM Student", action.student, "read")

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
					"legacy_lead_scope.owner_staff = 'STAFF-001'",
					"segment_scope.owner = 'sale@example.com'",
				],
			),
			patch.object(frappe, "get_roles", return_value=["Sale"]),
		):
			condition = task_api.get_permission_query_conditions("sale@example.com")

		self.assertIn("EXISTS", condition)
		self.assertIn("`tabCRM Lead`", condition)
		self.assertIn("`tabCRM Student`", condition)
		self.assertIn("`tabCRM Segment`", condition)
		self.assertIn("`tabTask`.reference_doctype", condition)

	def test_task_has_permission_checks_reference_scope(self):
		doc = frappe._dict(
			doctype="Task",
			reference_doctype="CRM Student",
			reference_docname="STU-2026-00001",
			name="TASK-00001",
		)
		with (
			patch.object(task_api, "_check_reference_access") as check_reference,
			patch.object(frappe, "get_roles", return_value=["Sale"]),
		):
			self.assertTrue(task_api.has_permission(doc, user="sale@example.com", ptype="write"))

		check_reference.assert_called_once_with("CRM Student", "STU-2026-00001", "read")

	@patch("crm.api.task._require_sales_task_access", return_value="Administrator")
	@patch("crm.api.task._aggregate_tasks_sql", return_value=("SELECT 1", []))
	def test_sales_task_aggregate_is_paginated_and_serialized(self, _aggregate, _access):
		rows = [
			frappe._dict(
				task_id="CRM Action Item:ACT-1",
				name="1",
				doctype="CRM Action Item",
				task_type="CONTACT",
				title="Call student",
				description=None,
				status="Todo",
				priority="High",
				due_date="2999-09-05 10:00:00",
				assigned_to="Administrator",
				assigned_to_name="Administrator",
				student="STU-2026-00001",
				student_name="Test Student",
				reference_doctype="CRM Student",
				reference_docname="STU-2026-00001",
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
		self.assertEqual(result["tasks"][0]["task_id"], "CRM Action Item:ACT-1")
		self.assertFalse(result["tasks"][0]["is_overdue"])
		self.assertEqual(sql.call_count, 2)
		self.assertEqual(sql.call_args_list[1].args[1][-2:], [1, 1])
		_aggregate.assert_called_once_with("Administrator", None, None, None, "all", None)

	@patch("crm.api.task._permission_condition", return_value="1=1")
	def test_sales_task_aggregate_uses_canonical_action_items_only(self, _permission):
		query, values = task_api._aggregate_tasks_sql("Administrator", None, None, None, "all", None)

		self.assertIn("FROM `tabCRM Action Item` action_item", query)
		self.assertNotIn("FROM `tabTask` task", query)
		self.assertEqual(values, [])
		self.assertEqual(_permission.call_count, 1)

	@patch("crm.api.task._permission_condition", return_value="1=1")
	def test_sales_task_manual_filter_stays_on_action_items(self, _permission):
		query, values = task_api._aggregate_tasks_sql("Administrator", None, None, None, "all", "Task")

		self.assertIn("FROM `tabCRM Action Item` action_item", query)
		self.assertNotIn("FROM `tabTask` task", query)
		self.assertIn("action_item.origin = 'manual'", query)
		self.assertIn("action_item.action = 'CREATE_TASK'", query)
		_permission.assert_called_once_with("CRM Student", "student_scope", "Administrator")
		self.assertEqual(values, [])
