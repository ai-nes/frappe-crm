# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.desk.form.assign_to import add as assign
from frappe.desk.form.assign_to import remove as unassign
from frappe.model.document import Document


class Task(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		assigned_to: DF.Link | None
		description: DF.TextEditor | None
		due_date: DF.Datetime | None
		name: DF.Int | None
		priority: DF.Literal["Low", "Medium", "High"]
		reference_docname: DF.DynamicLink | None
		reference_doctype: DF.Link | None
		start_date: DF.Date | None
		status: DF.Literal["Backlog", "Todo", "In Progress", "Done", "Canceled"]
		title: DF.Data
	# end: auto-generated types

	# Fields below `producer_identity` govern an AI-generated task (crm-agents
	# Student Task V2, formerly the standalone CRM Student Task doctype). A
	# plain manual task never sets `producer_identity` and is unaffected by
	# any of the checks in this block.
	_PROTECTED_FIELDS = frozenset(
		{
			"student",
			"current_slot",
			"source_context_revision",
			"disposition",
			"action_type",
			"objective",
			"policy_version",
			"context_version",
			"generation_idempotency_key",
			"producer_identity",
			"payload_digest",
			"recommendation",
			"sales_action",
			"evidence_references",
			"package_seed",
			"status",
			"requires_review",
			"review_revision",
			"action_revision",
			"execution_package_version",
			"outcome",
			"priority",
			"revisit_at",
			"decision_reason",
			"decision_actor",
			"decision_at",
			"decision_revision",
		}
	)

	# priority -> worklist_priority_rank ordering. Keyed on Title Case since
	# that is Task's canonical casing (crm-agents maps its own lowercase
	# priority to this at the Frappe integration boundary).
	_PRIORITY_RANK = {"High": 0, "Medium": 1, "Low": 2}

	def after_insert(self):
		self.assign_to()

	def validate(self):
		before = self.get_doc_before_save()
		# A row is AI-governed if it is now, or was before this save --
		# `producer_identity` must be set-once. Gating only on the current
		# value would let a direct edit clear it and walk every protected
		# field out of governance in the same save.
		if self.producer_identity or (before and before.get("producer_identity")):
			self._validate_ai_governed(before)
		self._validate_assignment(before)

	def _validate_ai_governed(self, before):
		if before and before.get("producer_identity") and not self.producer_identity:
			frappe.throw(
				"producer_identity cannot be cleared once set.",
				frappe.PermissionError,
			)
		self.worklist_priority_rank = self._PRIORITY_RANK.get(self.priority, 99)
		is_controlled_command = getattr(frappe.flags, "student_task_command", False)
		if before and not is_controlled_command:
			for field in self._PROTECTED_FIELDS:
				if before.get(field) != self.get(field):
					frappe.throw(
						"AI-governed Task fields can only be changed by controlled commands.",
						frappe.PermissionError,
					)
		if self.current_slot and self.current_slot != "CURRENT":
			raise ValueError("current_slot must be CURRENT or empty")
		if self.disposition == "ACT" and not self.action_type:
			raise ValueError("ACT task requires action_type")
		if self.disposition and self.disposition != "ACT" and self.action_type:
			raise ValueError("MONITOR/NURTURE task cannot carry action_type")
		if self.status != "DEFERRED" and self.revisit_at:
			raise ValueError("revisit_at is only valid for a DEFERRED task")

	def _validate_assignment(self, before):
		if self.is_new() or not self.assigned_to or not before:
			return

		if before.assigned_to == self.assigned_to:
			return

		if self.producer_identity and not (
			getattr(frappe.flags, "student_task_command", False)
			or getattr(frappe.flags, "student_ownership_sync", False)
		):
			frappe.throw(
				"assigned_to on an AI-governed Task can only change via task generation "
				"or the CRM Student ownership-sync hook, not a direct edit.",
				frappe.PermissionError,
			)

		self.unassign_from_previous_user(before.assigned_to)
		self.assign_to()

	def on_trash(self):
		if self.producer_identity and not getattr(frappe.flags, "student_task_command", False):
			frappe.throw(
				"An AI-governed Task cannot be deleted directly; use the controlled decision command.",
				frappe.PermissionError,
			)

	def unassign_from_previous_user(self, user: str | None):
		if user:
			unassign(self.doctype, self.name, user)

	def assign_to(self):
		if self.assigned_to:
			assign(
				{
					"assign_to": [self.assigned_to],
					"doctype": self.doctype,
					"name": self.name,
					"description": self.title or self.description or self.objective,
				}
			)

	@staticmethod
	def default_list_data():
		columns = [
			{
				"label": "Title",
				"type": "Data",
				"key": "title",
				"width": "16rem",
			},
			{
				"label": "Status",
				"type": "Select",
				"key": "status",
				"width": "8rem",
			},
			{
				"label": "Priority",
				"type": "Select",
				"key": "priority",
				"width": "8rem",
			},
			{
				"label": "Due Date",
				"type": "Date",
				"key": "due_date",
				"width": "8rem",
			},
			{
				"label": "Assigned To",
				"type": "Link",
				"key": "assigned_to",
				"width": "10rem",
			},
			{
				"label": "Last Modified",
				"type": "Datetime",
				"key": "modified",
				"width": "8rem",
			},
		]

		rows = [
			"name",
			"title",
			"description",
			"assigned_to",
			"due_date",
			"status",
			"priority",
			"reference_doctype",
			"reference_docname",
			"modified",
			# Always fetched (not shown as columns) so the Tasks list can gate
			# AI-governed row actions (accept/reject/defer) without an extra call.
			"student",
			"producer_identity",
			"disposition",
			"action_type",
			"objective",
			"revisit_at",
			"decision_revision",
		]
		return {"columns": columns, "rows": rows}

	@staticmethod
	def default_kanban_settings():
		return {
			"column_field": "status",
			"title_field": "title",
			"kanban_fields": '["description", "priority", "creation"]',
		}


def get_permission_query_conditions(user=None):
	"""Student-scope a Task only when it references a Student; a plain manual
	Task (no student) is unaffected and falls back to the base role permission."""
	from crm.fcrm.permissions import get_permission_query_conditions as student_scope

	if not user:
		user = frappe.session.user
	condition = student_scope("CRM Student", user=user)
	if not condition:
		return None
	return (
		f"(`tabTask`.student is null or `tabTask`.student in "
		f"(select `tabCRM Student`.name from `tabCRM Student` where {condition}))"
	)


def has_permission(doc, user=None, permission_type=None):
	student = doc.get("student") if isinstance(doc, dict) else getattr(doc, "student", None)
	if not student:
		return True

	if not user:
		user = frappe.session.user
	from crm.fcrm.permissions import get_permission_query_conditions as student_scope

	condition = student_scope("CRM Student", user=user)
	if condition is None:
		return True
	return bool(
		frappe.db.sql(
			"select name from `tabCRM Student` where name = %s and (" + condition + ") limit 1", (student,)
		)
	)
