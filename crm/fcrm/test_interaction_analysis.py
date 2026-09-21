"""Regression coverage for replaying an Interaction analysis result."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.interaction_analysis import _resolve_dominant_intent


class TestInteractionAnalysisReplay(FrappeTestCase):
	def test_replay_reuses_same_dominant_intent(self):
		existing = frappe._dict(name="INTENT-2026-00041", intent_type="ENROLLMENT_INTENT")

		with (
			patch.object(frappe.db, "get_value", return_value=existing),
			patch("crm.fcrm.interaction_analysis.frappe.get_doc") as get_doc,
		):
			result = _resolve_dominant_intent(
				interaction="INTX-1",
				student="STU-1",
				intent_type="ENROLLMENT_INTENT",
				analysis_result="IRES-2",
			)

		self.assertEqual(result, existing.name)
		get_doc.assert_not_called()

	def test_replay_rejects_a_different_dominant_intent(self):
		existing = frappe._dict(name="INTENT-2026-00041", intent_type="ENROLLMENT_INTENT")

		with patch.object(frappe.db, "get_value", return_value=existing):
			with self.assertRaises(frappe.ValidationError):
				_resolve_dominant_intent(
					interaction="INTX-1",
					student="STU-1",
					intent_type="DEPOSIT_INTENT",
					analysis_result="IRES-2",
				)
