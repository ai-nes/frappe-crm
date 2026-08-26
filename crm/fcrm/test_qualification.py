"""Pure Phase 5 qualification/continuity contract tests."""

from datetime import datetime, timedelta

from frappe.tests.utils import FrappeTestCase

from crm.fcrm.qualification import (
	QualificationValidationError,
	find_missing_qualification_evidence,
	normalize_evidence,
	validate_continuity,
	validate_qualification_evidence,
)


class TestPhase5Qualification(FrappeTestCase):
	def test_mql_requires_outcome_and_non_score_evidence(self):
		evidence = [
			{"category": "outcome", "doctype": "CRM Student Outcome", "name": "OUT-1"},
			{"category": "intent", "doctype": "CRM Interaction", "name": "INT-1", "private": "redact"},
		]
		result = validate_qualification_evidence("MQL", "qualified", evidence)
		self.assertEqual(
			result["evidence"],
			[
				{"category": "outcome", "doctype": "CRM Student Outcome", "name": "OUT-1"},
				{"category": "intent", "doctype": "CRM Interaction", "name": "INT-1"},
			],
		)

	def test_applicant_requires_appointment_or_document(self):
		self.assertIn(
			"appointment_or_document",
			find_missing_qualification_evidence(
				"Applicant", "qualified", [{"category": "intent", "doctype": "CRM Interaction", "name": "INT-1"}]
			),
		)

	def test_unknown_evidence_and_outcome_do_not_get_normalized(self):
		self.assertEqual(normalize_evidence([{"category": "score", "doctype": "X", "name": "1"}]), [])
		with self.assertRaises(QualificationValidationError):
			validate_qualification_evidence("MQL", "unknown", [])

	def test_meaningful_task_requires_assignee_and_due_date(self):
		with self.assertRaises(QualificationValidationError):
			validate_continuity("connected", "task", next_action={"student": "STU-1"})
		self.assertTrue(
			validate_continuity(
				"connected",
				"task",
				next_action={"student": "STU-1", "assigned_to": "user@example.com", "due_date": "2026-08-26"},
			)["meaningful"]
		)

	def test_waiting_is_bounded_and_terminal_has_reason(self):
		now = datetime(2026, 8, 25, 12, 0)
		self.assertTrue(
			validate_continuity(
				"follow_up_required",
				"waiting",
				reason="Student requested a later call",
				expires_at=now + timedelta(days=7),
				now=now,
			)["meaningful"]
		)
		with self.assertRaises(QualificationValidationError):
			validate_continuity("follow_up_required", "waiting", reason="too long", expires_at=now + timedelta(days=31), now=now)
		with self.assertRaises(QualificationValidationError):
			validate_continuity("completed", "terminal")
