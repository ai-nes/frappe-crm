import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.task import create_task, delete_task, get_task, list_tasks, update_task


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
