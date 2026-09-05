from frappe.tests.utils import FrappeTestCase

from crm.fcrm.interaction_cutover import (
	CANONICAL_WRITER,
	compare_replay_receipts,
	evaluate_acceptance_gates,
	validate_routing_manifest,
)


class TestInteractionCutover(FrappeTestCase):
	def test_routing_manifest_requires_one_canonical_writer_and_explicit_cohort(self):
		result = validate_routing_manifest(
			{
				"sources": {
					"chatwoot": {
						"writer": CANONICAL_WRITER,
						"ledger_namespace": "chatwoot",
						"cohorts": {"pilot": {"enabled": False}},
					}
				}
			}
		)
		self.assertEqual(result["status"], "ready")

	def test_acceptance_requires_explicit_thresholds(self):
		result = evaluate_acceptance_gates({}, {})
		self.assertEqual(result["status"], "blocked")
		self.assertIn("missing_threshold:drop_rate", result["blockers"])
		self.assertIn("missing_metric:drop_rate", result["blockers"])

	def test_replay_comparison_exposes_counts_not_receipt_content(self):
		row = {
			"event_key": "opaque",
			"episode_key": "episode",
			"intent_term": "TERM-1",
			"intent_state": "intent_bearing",
			"score_components_digest": "digest",
			"authorized": True,
		}
		result = compare_replay_receipts([row], [row])
		self.assertEqual(
			result,
			{
				"canonical_receipts": 1,
				"shadow_receipts": 1,
				"unmatched_canonical": 0,
				"unmatched_shadow": 0,
				"status": "parity",
			},
		)
