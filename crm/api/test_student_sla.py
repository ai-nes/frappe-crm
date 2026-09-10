"""Frappe-backed SLA lifecycle checks (run with ``bench run-tests``)."""

from importlib import import_module
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.doc import get_data

student_sla = import_module("crm.fcrm.student_sla")
from crm.fcrm.student_sla import (
	MEANINGFUL_OUTCOMES,
	StudentSLAError,
	process_due_sla_attempts,
	record_qualifying_response,
)


class TestStudentSLA(FrappeTestCase):
	def test_sla_attempt_has_default_list_configuration(self):
		"""A first-time SLA list view must not require saved View Settings."""
		original_exists = frappe.db.exists

		def exists_without_view_settings(doctype, filters=None, *args, **kwargs):
			if doctype == "View Settings":
				return None
			return original_exists(doctype, filters, *args, **kwargs)

		with patch("crm.api.doc.frappe.db.exists", side_effect=exists_without_view_settings):
			list_data = get_data(
				doctype="CRM Student SLA Attempt",
				filters={},
				order_by="modified desc",
				view={"view_type": "list", "custom_view_name": "", "group_by_field": "owner"},
				default_filters={"status": ["in", ["breached", "escalated"]]},
			)

		self.assertEqual(
			[column["key"] for column in list_data["columns"]],
			["student", "owner_staff", "status", "warning_at", "breach_at", "modified"],
		)
		self.assertEqual(
			list_data["rows"],
			[
				"name",
				"student",
				"owner_staff",
				"status",
				"warning_at",
				"breach_at",
				"modified",
				"owner",
				"creation",
				"modified_by",
				"_assign",
				"_liked_by",
			],
		)

	def test_only_meaningful_outcomes_can_satisfy_response(self):
		self.assertIn("Resolved", MEANINGFUL_OUTCOMES)
		self.assertNotIn("No Response", MEANINGFUL_OUTCOMES)

	def test_disabled_due_worker_is_a_safe_pause(self):
		previous = frappe.conf.pop("crm_student_sla_enabled", None)
		try:
			self.assertEqual(process_due_sla_attempts(), {"processed": 0, "failed": 0, "disabled": 1})
		finally:
			if previous is not None:
				frappe.conf.crm_student_sla_enabled = previous

	def test_foreign_or_fabricated_interaction_cannot_satisfy_an_sla(self):
		attempt = frappe._dict(name="SLA-1", student="STU-1", status="open", revision=3)
		foreign = frappe._dict(
			name="INT-1",
			student="STU-2",
			interaction_datetime="2026-01-01 10:00:00",
			outcome="Resolved",
			actor="Administrator",
			reference_doctype="File",
			source_verified=1,
		)
		foreign.reload = lambda: None
		with (
			patch.object(student_sla, "enabled", return_value=True),
			patch.object(student_sla, "_lock_attempt", return_value=attempt),
			patch.object(student_sla, "_assert_scope"),
			patch.object(student_sla.frappe, "get_doc", return_value=foreign),
			patch("frappe.db.sql"),
		):
			with self.assertRaises(StudentSLAError) as error:
				record_qualifying_response("SLA-1", "INT-1", expected_revision=3)
		self.assertEqual(error.exception.code, "INVALID_INTERACTION")
		self.assertEqual(attempt.status, "open")
		self.assertEqual(attempt.revision, 3)

	def test_outcome_alone_is_not_a_qualifying_response(self):
		attempt = frappe._dict(
			name="SLA-2", student="STU-1", status="open", revision=0, opened_at="2026-01-01 00:00:00"
		)
		interaction = frappe._dict(
			name="INT-2",
			student="STU-1",
			interaction_datetime="9999-01-01 00:00:00",
			outcome="Resolved",
			actor="Administrator",
			reference_doctype="File",
			source_verified=1,
		)
		interaction.reload = lambda: None
		with (
			patch.object(student_sla, "enabled", return_value=True),
			patch.object(student_sla, "_lock_attempt", return_value=attempt),
			patch.object(student_sla, "_assert_scope"),
			patch.object(student_sla.frappe, "get_doc", return_value=interaction),
			patch("frappe.db.sql"),
		):
			with self.assertRaises(StudentSLAError) as error:
				record_qualifying_response("SLA-2", "INT-2", expected_revision=0)
		self.assertEqual(error.exception.code, "INVALID_INTERACTION_SOURCE")
		self.assertEqual(attempt.status, "open")
