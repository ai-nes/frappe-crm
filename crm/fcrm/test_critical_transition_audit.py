"""Focused contract tests for the Phase 9 critical-transition read facade."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe

from crm.fcrm import critical_transition_audit as audit


class TestCriticalTransitionAudit(unittest.TestCase):
	def _rows(self, manifest, student, _as_of, _cursor=None):
		# One deliberately identical timestamp per source proves the source/event
		# tie breakers, rather than database row order, define the page order.
		return [
			{
				"name": f"raw-{manifest['source']}",
				"event_id": f"event-{manifest['source']}",
				"student": student,
				manifest["time"]: "2026-08-25 10:00:00",
				"actor": "private@example.com",
				"correlation_id": "private-correlation",
				"from_stage": "Lead",
				"to_stage": "Applicant",
				"outcome_code": "qualified",
				"event_type": "assigned",
				"transition_kind": "forward",
			}
		], None

	@patch.object(audit, "_can_read_student", return_value=True)
	@patch.object(audit, "_read_source")
	def test_default_deny_redacts_raw_ids_and_actor(self, read_source, _can_read):
		read_source.side_effect = self._rows
		with patch.object(audit, "_reason_allowed", return_value=False):
			result = audit.critical_transition_timeline("STU-1", limit=2)

		self.assertEqual(len(result["timeline"]), 2)
		first = result["timeline"][0]
		self.assertNotIn("actor", first)
		self.assertNotIn("_cursor_event_id", first)
		self.assertTrue(first["event_id"].startswith("ref_"))
		self.assertNotIn("event-", first["event_id"])
		self.assertTrue(first["correlation"].startswith("ref_"))
		self.assertTrue(result["next_cursor"])
		self.assertTrue(result["completeness"]["complete"])

	@patch.object(audit, "_can_read_student", return_value=True)
	@patch.object(audit, "_read_source")
	def test_cursor_is_stable_for_identical_timestamps(self, read_source, _can_read):
		read_source.side_effect = self._rows
		with patch.object(audit, "_reason_allowed", return_value=True):
			first = audit.critical_transition_timeline("STU-1", limit=3)
			second = audit.critical_transition_timeline("STU-1", limit=3, cursor=first["next_cursor"])

		first_ids = {row["event_id"] for row in first["timeline"]}
		second_ids = {row["event_id"] for row in second["timeline"]}
		self.assertFalse(first_ids & second_ids)
		self.assertEqual(first["as_of"], second["as_of"])
		self.assertIn("actor", first["timeline"][0])

	@patch.object(audit, "_can_read_student", return_value=True)
	@patch.object(audit, "_read_source")
	def test_source_failure_is_explicit_not_silent(self, read_source, _can_read):
		def side_effect(manifest, student, as_of, _cursor=None):
			if manifest["source"] == "decision":
				return [], "source_query_failed"
			return self._rows(manifest, student, as_of)

		read_source.side_effect = side_effect
		result = audit.critical_transition_timeline("STU-1")
		self.assertFalse(result["completeness"]["complete"])
		self.assertIn({"source": "decision", "reason": "source_query_failed"}, result["completeness"]["omitted_sources"])

	def test_cursor_rejects_cross_student_reuse(self):
		cursor = audit._encode_cursor(
			{"v": audit.CURSOR_VERSION, "student": "STU-1", "as_of": "2026-08-25", "occurred_at": "2026-08-25", "source": "lifecycle", "event_id": "raw"}
		)
		with self.assertRaises(frappe.ValidationError):
			audit._decode_cursor(cursor, "STU-2")
