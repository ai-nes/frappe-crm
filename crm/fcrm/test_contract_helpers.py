"""Bench-independent Phase 9 registry and reconciliation contract tests."""

import unittest

from crm.fcrm.governance_audit_reconciliation import build_report, classify_governed_row
from crm.fcrm.governed_reference_registry import (
	REGISTRY_REVISION,
	GOVERNED_REFERENCE_REGISTRY,
	validate_registry,
)


class TestPhase9ContractHelpers(unittest.TestCase):
	def test_registry_is_versioned_and_covers_governed_doctypes(self):
		self.assertTrue(validate_registry())
		self.assertEqual(REGISTRY_REVISION, "P9-DEC-002")
		self.assertIn("CRM Lead Source", GOVERNED_REFERENCE_REGISTRY)

	def test_reconciliation_classification_is_deterministic_and_redacted(self):
		self.assertEqual(
			classify_governed_row({"name": "HN", "owner_role": "Admissions Director", "approval_state": "Approved", "version": 1, "effective_date": "2026-08-25"}),
			"ok",
		)
		report = build_report([
			{"doctype": "CRM Campus", "name": "HN", "owner_role": "Admissions Director", "approval_state": "Approved", "version": 1, "effective_date": "2026-08-25", "private_note": "redact"},
		])
		self.assertEqual(report["counts"], {"ok": 1})
		self.assertNotIn("private_note", report["items"][0])
		self.assertEqual(report["write_mode"], "dry_run")
