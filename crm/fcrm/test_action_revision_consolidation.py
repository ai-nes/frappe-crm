"""Focused source contracts for retiring the temporary revision DocTypes."""

import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def _source(*parts: str) -> str:
	return (ROOT.joinpath(*parts)).read_text(encoding="utf-8")


class TestActionRevisionConsolidation(unittest.TestCase):
	def test_newer_current_package_never_lowers_version_fence(self):
		from crm.patches.v1_0.consolidate_action_revisions import _package_reconciliation

		item = {
			"execution_package_version": 5,
			"package_seed": "{}",
			"action": "CALL",
		}
		with patch(
			"crm.patches.v1_0.consolidate_action_revisions._package_is_valid",
			return_value=True,
		):
			self.assertEqual(_package_reconciliation(item, 3), "preserve")
		with patch(
			"crm.patches.v1_0.consolidate_action_revisions._package_is_valid",
			return_value=False,
		):
			self.assertEqual(_package_reconciliation(item, 3), "unreconciled")

	def test_runtime_action_paths_do_not_reference_retired_revision_doctypes(self):
		for parts in (
			("fcrm", "doctype", "crm_action", "crm_action.py"),
			("services", "sales_action_dispatch.py"),
			("api", "student_worklist.py"),
		):
			source = _source(*parts)
			self.assertNotIn("CRM Action Definition Revision", source)
			self.assertNotIn("CRM Action Revision", source)


	def test_event_revision_is_a_scalar_and_consolidation_patch_is_registered(self):
		event = _source("fcrm", "doctype", "crm_student_decision_event", "crm_student_decision_event.json")
		self.assertIn('"fieldname": "action_definition_revision", "fieldtype": "Int"', event)
		patches = _source("patches.txt")
		self.assertIn("crm.patches.v1_0.consolidate_action_revisions", patches)


	def test_consolidation_patch_has_backfill_then_drop_order(self):
		source = _source("patches", "v1_0", "consolidate_action_revisions.py")
		self.assertLess(source.index("_ensure_action_definition_columns()"), source.index("_backfill_action_definitions()"))
		self.assertLess(source.index("_backfill_event_revisions()"), source.index("_drop_revision_doctype"))
		self.assertLess(source.index("_backfill_action_definitions()"), source.index("_drop_revision_doctype"))
		self.assertIn("DROP TABLE", source)
		self.assertIn("_columns_exist", source)
		self.assertIn("current_revision > candidate_revision", source)
		self.assertIn("unreconciled", source)
		self.assertIn("repair or quarantine", source)

	def test_unresolved_event_reference_is_not_coerced_to_null(self):
		from crm.patches.v1_0.consolidate_action_revisions import _resolve_event_revision

		self.assertIsNone(_resolve_event_revision("missing", {}, None, {}))
		self.assertEqual(_resolve_event_revision("3", {}, None, {}), 3)
		self.assertEqual(_resolve_event_revision("legacy-row", {"legacy-row": 4}, None, {}), 4)
		self.assertEqual(_resolve_event_revision("", {}, "ADVISE_MAJOR", {"ADVISE_MAJOR": 5}), 5)

	def test_unresolved_event_reference_aborts_before_revision_tables_drop(self):
		from crm.patches.v1_0 import consolidate_action_revisions as migration

		with (
			patch.object(migration, "_ensure_action_definition_columns"),
			patch.object(migration, "_backfill_action_definitions", return_value=[]),
			patch.object(migration, "_backfill_action_packages", return_value=[]),
			patch.object(migration, "_backfill_event_revisions", return_value=["event-1:missing"]),
			patch.object(migration, "_drop_revision_doctype") as drop,
			patch.object(migration.frappe, "throw", side_effect=RuntimeError("abort")) as throw,
		):
			with self.assertRaisesRegex(RuntimeError, "abort"):
				migration.execute()
			drop.assert_not_called()
			throw.assert_called_once()
