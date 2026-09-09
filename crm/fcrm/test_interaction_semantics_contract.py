"""Bench-independent contract tests for crm/fcrm/interaction_semantics.py --
mirrors app/contracts/test_interaction_semantics_contract.py in the
crm-agents repo. See that module and this one's docstring for why parity is
enforced via a frozen content hash rather than a cross-repo import."""

import json
import pathlib
import unittest

from crm.fcrm.interaction_semantics import (
	CONTENT_HASH,
	CONTRACT_VERSION,
	DIRECT_TOUCHPOINT_TYPES,
	FROZEN_CONTENT_HASH,
	INTERACTION_TYPE_MAPPING,
	KNOWN_WRITER_INTERACTION_TYPES,
	OUTCOME_FIELD_MAPPING,
	INTERACTION_INTELLIGENCE_CONTRACT_VERSION,
	INTERACTION_ANALYSIS_RESULT_CONTRACT_VERSION,
	INTERACTION_INTELLIGENCE_POLICY,
	InteractionContractError,
	SILENCE_WINDOW_SECONDS,
	is_business_outcome_like,
	resolve_interaction_type,
	resolve_outcome,
	validate_analysis_result,
	validate_interaction_intake,
)

_FIXTURES = pathlib.Path(__file__).parent / "test_fixtures" / "interaction-intelligence-v1"


class TestInteractionSemanticsContract(unittest.TestCase):
	def test_content_hash_matches_frozen_value(self):
		self.assertEqual(CONTENT_HASH, FROZEN_CONTENT_HASH)
		self.assertEqual(CONTRACT_VERSION, 4)

	def test_analysis_result_decision_signals_are_optional_legacy_and_bounded_v2(self):
		result = json.loads((_FIXTURES / "result-no-intent.json").read_text(encoding="utf-8"))
		result["contract_version"] = INTERACTION_ANALYSIS_RESULT_CONTRACT_VERSION
		result["decision_signals"] = {"schema_revision": "nba-decision-signals-v1", "observations": []}
		validate_analysis_result(result)
		result["decision_signals"]["observations"] = [{"raw": "must reject"}]
		with self.assertRaises(InteractionContractError):
			validate_analysis_result(result)

	def test_failed_result_cannot_carry_meaningful_decision_signals(self):
		result = json.loads((_FIXTURES / "result-no-intent.json").read_text(encoding="utf-8"))
		result["state"] = "failed"
		result["contract_version"] = INTERACTION_ANALYSIS_RESULT_CONTRACT_VERSION
		result["decision_signals"] = {
			"schema_revision": "nba-decision-signals-v1",
			"observations": [{
				"need_code": "RESOLVE_MAJOR_UNCERTAINTY",
				"status": "open",
				"basis": "explicit",
				"confidence": "high",
				"blocks_progress": True,
				"explicit_request": True,
				"advice_readiness": "ready",
				"application_readiness": "hesitant",
				"parent_influence": "unknown",
				"evidence_refs": ["EVID-1"],
			}],
		}
		with self.assertRaises(InteractionContractError):
			validate_analysis_result(result)

	def test_every_known_writer_type_has_a_mapping_entry(self):
		unmapped = KNOWN_WRITER_INTERACTION_TYPES - set(INTERACTION_TYPE_MAPPING)
		self.assertFalse(unmapped, f"unmapped legacy interaction_type values: {unmapped}")

	def test_mapping_entries_are_unambiguous(self):
		for name, entry in INTERACTION_TYPE_MAPPING.items():
			self.assertEqual(
				{"channel", "purpose", "disposition", "is_direct_touchpoint", "evidence_kind"}, set(entry)
			)
			self.assertIsInstance(entry["is_direct_touchpoint"], bool, name)

	def test_lifecycle_assignment_and_evidence_types_are_not_direct_touchpoints(self):
		for name in (
			"STAGE_CHANGED",
			"LEAD_ASSIGNED",
			"LEAD_REASSIGNED",
			"OPT_OUT",
			"OPT_IN",
			"BOUNCE",
			"DATA_ERROR",
			"REGISTERED",
			"CHECKED_IN",
			"NO_SHOW",
			"FEEDBACK",
			"CAMPAIGN_TOUCHED",
		):
			self.assertNotIn(name, DIRECT_TOUCHPOINT_TYPES)

	def test_genuine_touchpoints_are_direct(self):
		for name in ("OUTREACH", "CONNECTED", "COUNSELING"):
			self.assertIn(name, DIRECT_TOUCHPOINT_TYPES)

	def test_resolve_interaction_type_returns_none_for_unmapped_value(self):
		self.assertIsNone(resolve_interaction_type("_Test Phone Call"))

	def test_resolve_outcome_returns_none_for_empty_value(self):
		self.assertIsNone(resolve_outcome(None))
		self.assertIsNone(resolve_outcome(""))

	def test_resolved_business_outcome_like_values_are_flagged(self):
		self.assertTrue(is_business_outcome_like("Resolved"))
		self.assertTrue(is_business_outcome_like("Converted"))

	def test_true_dispositions_are_not_business_outcome_like(self):
		for value in ("Captured", "Follow Up Needed", "No Response", "Data Error", "Uncontactable"):
			self.assertFalse(is_business_outcome_like(value))

	def test_outcome_mapping_covers_full_legacy_select_enum(self):
		# crm_interaction.json's `outcome` Select options, minus the blank default.
		legacy_options = {
			"Captured",
			"Follow Up Needed",
			"Resolved",
			"Converted",
			"No Response",
			"Data Error",
			"Uncontactable",
		}
		self.assertEqual(legacy_options, set(OUTCOME_FIELD_MAPPING))

	def test_phase_one_policy_is_explicit_and_minimal(self):
		self.assertEqual(INTERACTION_INTELLIGENCE_CONTRACT_VERSION, "interaction-intelligence-v1")
		self.assertEqual(SILENCE_WINDOW_SECONDS, 15 * 60)
		self.assertEqual(INTERACTION_INTELLIGENCE_POLICY["episode"]["late_event"], "new_source_revision_and_reanalysis")
		self.assertEqual(INTERACTION_INTELLIGENCE_POLICY["evidence"]["raw_content_destinations"], "evidence_only")
		self.assertEqual(INTERACTION_INTELLIGENCE_POLICY["service_auth"]["writer_boundary"], "existing_frappe_authenticated_api")
		self.assertEqual(INTERACTION_INTELLIGENCE_POLICY["term"]["semantic_key"], "immutable")

	def test_intelligence_block_is_additive_bounded_and_state_gated(self):
		result = json.loads((_FIXTURES / "result-intent-bearing.json").read_text(encoding="utf-8"))
		result["intelligence"] = {
			"summary": "Học sinh hỏi học phí ngành AI; tư vấn viên gửi bảng học phí.",
			"sentiment": "neutral",
			"entities": {"program": ["AI"]},
			"readiness": "hesitant",
			"concerns": ["financial"],
		}
		validate_analysis_result(result)
		# Omitting it keeps the legacy shape valid.
		del result["intelligence"]
		validate_analysis_result(result)
		# Malformed shapes fail closed.
		for bad in (
			{"summary": "a\nb"},
			{"summary": "x" * 601},
			{"sentiment": "furious"},
			{"entities": {"content": ["x"]}},
			{"concerns": ["x" * 65]},
			{"unexpected": "x"},
		):
			result["intelligence"] = {"summary": "ok", **bad}
			with self.assertRaises(InteractionContractError):
				validate_analysis_result(result)
		# Not allowed on unknown/failed.
		no_intent = json.loads((_FIXTURES / "result-no-intent.json").read_text(encoding="utf-8"))
		no_intent["state"] = "unknown"
		no_intent["intelligence"] = {"summary": "x"}
		with self.assertRaises(InteractionContractError):
			validate_analysis_result(no_intent)

	def test_shared_fixtures_are_accepted(self):
		intake = json.loads((_FIXTURES / "intake-final-message.json").read_text(encoding="utf-8"))
		intent_bearing = json.loads((_FIXTURES / "result-intent-bearing.json").read_text(encoding="utf-8"))
		no_intent = json.loads((_FIXTURES / "result-no-intent.json").read_text(encoding="utf-8"))
		validate_interaction_intake(intake)
		validate_analysis_result(intent_bearing)
		validate_analysis_result(no_intent)

	def test_only_calls_may_be_drafts_and_only_students_substantiate_intent(self):
		intake = json.loads((_FIXTURES / "intake-final-message.json").read_text(encoding="utf-8"))
		intake["source"]["state"] = "draft"
		intake["source"]["kind"] = "call"
		with self.assertRaises(InteractionContractError):
			validate_interaction_intake(intake)
		result = json.loads((_FIXTURES / "result-intent-bearing.json").read_text(encoding="utf-8"))
		result["intent"]["evidence_refs"][0]["actor_role"] = "advisor"
		with self.assertRaises(InteractionContractError):
			validate_analysis_result(result)

	def test_raw_content_boolean_revisions_and_unknown_versions_fail_closed(self):
		intake = json.loads((_FIXTURES / "intake-final-message.json").read_text(encoding="utf-8"))
		intake["raw_content"] = "sensitive transcript"
		with self.assertRaises(InteractionContractError):
			validate_interaction_intake(intake)
		intake.pop("raw_content")
		intake["sequence"] = True
		with self.assertRaises(InteractionContractError):
			validate_interaction_intake(intake)
		intake["sequence"] = 1
		intake["contract_version"] = "interaction-intelligence-v2"
		with self.assertRaises(InteractionContractError):
			validate_interaction_intake(intake)

	def test_unknown_fields_and_incomplete_intent_evidence_fail_closed(self):
		intake = json.loads((_FIXTURES / "intake-final-message.json").read_text(encoding="utf-8"))
		intake["body"] = "sensitive transcript"
		with self.assertRaises(InteractionContractError):
			validate_interaction_intake(intake)
		result = json.loads((_FIXTURES / "result-intent-bearing.json").read_text(encoding="utf-8"))
		result["intent"]["evidence_refs"] = [{"actor_role": "student"}]
		with self.assertRaises(InteractionContractError):
			validate_analysis_result(result)
