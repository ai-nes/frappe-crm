"""Bench-scoped behavioral tests for NBA decision-signal projection."""

from datetime import UTC, datetime
from unittest.mock import patch

try:
	import frappe
	from frappe.tests.utils import FrappeTestCase
except Exception:  # pragma: no cover - pure environment without a bench
	frappe = None
	FrappeTestCase = None


if FrappeTestCase is not None:

	class TestNbaContextProjection(FrappeTestCase):
		def _run_projection(self, *, interactions, runs, results):
			from crm.api import student_decision_context

			def get_all(doctype, **kwargs):
				if doctype == "CRM Interaction":
					return interactions
				if doctype == "CRM Interaction Analysis Run":
					return runs
				if doctype == "CRM Interaction Analysis Result":
					return results
				raise AssertionError(f"unexpected projection query: {doctype}")

			with (
				patch.object(student_decision_context.frappe, "get_all", side_effect=get_all),
				patch.object(student_decision_context.frappe.utils, "get_system_timezone", return_value="UTC"),
				patch.object(student_decision_context.frappe.utils, "get_datetime", side_effect=lambda value: value),
			):
				return student_decision_context._decision_signals_projection("STU-1")

		@staticmethod
		def _observation(ref="EVID-1"):
			return {
				"need_code": "RESOLVE_MAJOR_UNCERTAINTY",
				"status": "open",
				"basis": "explicit",
				"confidence": "high",
				"blocks_progress": True,
				"explicit_request": True,
				"advice_readiness": "ready",
				"application_readiness": "hesitant",
				"parent_influence": "unknown",
				"evidence_refs": [ref],
			}

		def test_unknown_intent_is_projected_but_revision_mismatch_is_partial(self):
			observed_at = datetime(2026, 9, 9, tzinfo=UTC)
			interactions = [
				{"name": "INT-NEW", "source_revision": 3, "evidence_digest": "a" * 64, "interaction_datetime": observed_at},
				{"name": "INT-OLD", "source_revision": 2, "evidence_digest": "b" * 64, "interaction_datetime": observed_at},
			]
			runs = [{"name": "RUN-NEW", "interaction": "INT-NEW"}, {"name": "RUN-OLD", "interaction": "INT-OLD"}]
			results = [
				{
					"name": "RES-NEW", "analysis_run": "RUN-NEW", "state": "unknown", "creation": observed_at,
					"source_revision": 3, "source_digest": "a" * 64, "model_revision": "model",
					"decision_signals": {"schema_revision": "nba-decision-signals-v1", "observations": [self._observation()]},
				},
				{
					"name": "RES-OLD", "analysis_run": "RUN-OLD", "state": "unknown", "creation": observed_at,
					"source_revision": 1, "source_digest": "c" * 64, "model_revision": "model",
					"decision_signals": {"schema_revision": "nba-decision-signals-v1", "observations": [self._observation("EVID-OLD")]},
				},
			]

			projected = self._run_projection(interactions=interactions, runs=runs, results=results)
			self.assertEqual(projected["coverage"], "partial")
			self.assertEqual(len(projected["observations"]), 1)
			self.assertEqual(projected["observations"][0]["source_interaction"], "INT-NEW")
			self.assertEqual(projected["observations"][0]["source_revision"], 3)

		def test_bounded_history_is_partial_and_malformed_only_is_unavailable(self):
			observed_at = datetime(2026, 9, 9, tzinfo=UTC)
			interactions = [
				{
					"name": f"INT-{index:02d}", "source_revision": 1, "evidence_digest": "a" * 64,
					"interaction_datetime": observed_at,
				}
				for index in range(21)
			]
			runs = [{"name": "RUN-00", "interaction": "INT-00"}]
			results = [{
				"name": "RES-00", "analysis_run": "RUN-00", "state": "unknown", "creation": observed_at,
				"source_revision": 1, "source_digest": "a" * 64, "model_revision": "model",
				"decision_signals": {"schema_revision": "nba-decision-signals-v1", "observations": [self._observation()]},
			}]
			projected = self._run_projection(interactions=interactions, runs=runs, results=results)
			self.assertEqual(projected["coverage"], "partial")
			self.assertEqual(len(projected["observations"]), 1)

			malformed = dict(results[0], decision_signals="{")
			projected = self._run_projection(
				interactions=interactions[:1],
				runs=runs,
				results=[malformed],
			)
			self.assertEqual(projected["coverage"], "unavailable")
			self.assertEqual(projected["observations"], [])

			malformed = dict(
				results[0],
				decision_signals={"schema_revision": "nba-decision-signals-v1", "observations": [{"raw": "bad"}]},
			)
			projected = self._run_projection(
				interactions=interactions[:1],
				runs=runs,
				results=[malformed],
			)
			self.assertEqual(projected["coverage"], "unavailable")
			self.assertEqual(projected["observations"], [])
