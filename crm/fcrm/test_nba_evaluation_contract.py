# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

"""Producer-side parity for the NBA Evaluation v1 wire contract.

The fixtures under ``crm/fcrm/test_fixtures/nba-evaluation-v1`` are shared
byte-for-byte with the consumer suite in the ``crm-agents`` repository
(``tests/contract/test_nba_evaluation_shapes.py``). Each repository re-states
the shape rules and pins the expected canonical digests and raw-byte hashes as
fixed literals recorded on its own, so a drift on one side surfaces as a
mismatch instead of both sides agreeing on a wrong value.

Pure contract test -- no database, no ``frappe`` import -- so it runs both
under ``bench run-tests`` and standalone. The runtime DocTypes for this
contract are introduced by a later phase.
"""

import hashlib
import json
import pathlib
import unittest

_FIXTURES = pathlib.Path(__file__).parent / "test_fixtures" / "nba-evaluation-v1"

CONTRACT_VERSION = "nba-evaluation-v1"
_DISPOSITIONS = {"RECOMMEND", "WAIT", "NO_ACTION", "ABSTAIN"}
_RUN_STATUSES = {"completed", "failed"}
_MAX_EXPLANATION_FACT_CHARS = 800
_MAX_EXPLANATION_FACTS = 12
_MAX_RECOMMENDATIONS = 10
_RESULT_DIGEST_FIELD = "result_digest"

_INPUT_REQUIRED = (
	"contract_version",
	"evaluation_id",
	"evaluation_key",
	"evaluation_clock",
	"student",
	"context",
	"eligible_action_set",
	"policies",
)
_CONTEXT_REQUIRED = (
	"lifecycle",
	"intent",
	"engagement",
	"application_state",
	"blockers",
	"deadlines",
	"contactability",
	"work_in_flight",
	"owner_capacity",
	"evidence_refs",
	"signal_quality",
)
_ELIGIBLE_ACTION_REQUIRED = (
	"action_id",
	"action_revision",
	"action_digest",
	"action_code",
	"group",
	"purpose",
	"addresses_opportunities",
	"allowed_channels",
	"allowed_actors",
	"execution_parameter_schema",
	"default_parameters",
	"hard_constraints",
	"normalized_timing_domain",
	"cost_band",
	"risk_band",
	"effort_band",
	"conflict_keys",
)
_RESULT_REQUIRED = (
	"contract_version",
	"evaluation_id",
	"evaluation_key",
	"input_digest",
	"engine_revision",
	"run_status",
	"disposition",
	"reason_codes",
	"recommendations",
	"trace_ref",
	"result_digest",
)
_RECOMMENDATION_REQUIRED = (
	"recommendation_key",
	"rank",
	"action_ref",
	"opportunity_refs",
	"recommended_execution_params",
	"recommended_timing",
	"score",
	"confidence",
	"reason_codes",
	"evidence_refs",
	"explanation_facts",
	"conflict_keys",
	"expires_at",
)
_TIMING_REQUIRED = ("earliest_at", "latest_at", "scheduled_at", "timezone")

# Canonical digest (SHA-256 of canonical JSON of the parsed envelope).
_EXPECTED_DIGESTS = {
	"input-recommend.json": "e0442c00b495f7fb8e5b9fb60ec53da29faff73a7ef6d9cca5136aafa5e99b13",
	"result-recommend.json": "3c737749e6d41c403fccb6380afba83ab414643a4b331984ffb711e2c991ada5",
	"result-wait.json": "470e6935d164bb6f6f3ddd24d72f44bab1445d2295e3d030add4658ff2b343eb",
	"result-unknown-major.json": "1d1b40dcb0da911dc8eea6d2baf1efb692c1899e83ee280ebcf8d3eb49023a9c",
	"result-action-outside-eligible-set.json": "e62e018a51c7187eb894955ed54065ffd696f5b841eb333e57164f330326ac5f",
	"result-duplicate-recommendation-key.json": "cde4406bc2de97bbb79428f9c2cc52dd1dd947e44900f55c7e7018328b4bfe10",
}
# Raw file bytes.
_EXPECTED_RAW_SHA256 = {
	"input-recommend.json": "b4d2cc5f7886096e429f03f288f58cae8a7cb93903fb25ba56e875c2a0dace9d",
	"result-recommend.json": "1bc1b5f9b6a0a3badf631795a1e74733fdacac45d23aac08356fb601d07facbf",
	"result-wait.json": "5af53bbfcc8950d38d9540cedcd1b0f9781869ef53ffaa6ffced8acb957e7fc6",
	"result-unknown-major.json": "9d6cadf88f2cf071e876644e4a3346993dbc2168971d17142027bc68df0c49d9",
	"result-action-outside-eligible-set.json": "b7f3d00ff1174da68535dd369370fbe0e5ad54c7478b479bf107bb5154b48abc",
	"result-duplicate-recommendation-key.json": "12721836ab26445fb80e9d8e7aacc50e8b3aca7b9917794abba3f33628abbb2c",
}


class ContractShapeError(ValueError):
	pass


def canonical_digest(value) -> str:
	body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
	return hashlib.sha256(body.encode("utf-8")).hexdigest()


def recompute_result_digest(result_payload) -> str:
	if not isinstance(result_payload, dict):
		raise ContractShapeError("evaluation result must be an object")
	return canonical_digest({k: v for k, v in result_payload.items() if k != _RESULT_DIGEST_FIELD})


def _load(name: str) -> dict:
	return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _is_hex64(value) -> bool:
	return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _require(mapping, keys, where):
	if not isinstance(mapping, dict):
		raise ContractShapeError(f"{where} must be an object")
	missing = [k for k in keys if k not in mapping]
	if missing:
		raise ContractShapeError(f"{where} missing required fields: {sorted(missing)}")


def _reject_unknown_contract_version(payload):
	if not isinstance(payload, dict):
		raise ContractShapeError("payload must be an object")
	if payload.get("contract_version") != CONTRACT_VERSION:
		raise ContractShapeError(f"unknown contract_version {payload.get('contract_version')!r}")


def assert_input_shape(payload):
	_reject_unknown_contract_version(payload)
	_require(payload, _INPUT_REQUIRED, "evaluation input")
	if not _is_hex64(payload["evaluation_key"]):
		raise ContractShapeError("evaluation_key must be a 64-char lowercase hex digest")
	_require(
		payload["student"],
		("student_id", "context_revision", "context_digest", "observed_at", "timezone"),
		"student",
	)
	if not isinstance(payload["student"]["context_revision"], int):
		raise ContractShapeError("student.context_revision must be an integer")
	if not _is_hex64(payload["student"]["context_digest"]):
		raise ContractShapeError("student.context_digest must be a 64-char lowercase hex digest")
	_require(payload["context"], _CONTEXT_REQUIRED, "context")
	eligible = payload["eligible_action_set"]
	_require(eligible, ("set_revision", "set_digest", "actions"), "eligible_action_set")
	if not _is_hex64(eligible["set_digest"]):
		raise ContractShapeError("eligible_action_set.set_digest must be a 64-char lowercase hex digest")
	if not isinstance(eligible["actions"], list) or not eligible["actions"]:
		raise ContractShapeError("eligible_action_set.actions must be a non-empty list")
	seen = set()
	for index, action in enumerate(eligible["actions"]):
		where = f"eligible_action_set.actions[{index}]"
		_require(action, _ELIGIBLE_ACTION_REQUIRED, where)
		if not _is_hex64(action["action_digest"]):
			raise ContractShapeError(f"{where}.action_digest must be a 64-char lowercase hex digest")
		if action["action_id"] in seen:
			raise ContractShapeError(f"{where}.action_id is duplicated in the eligible set")
		seen.add(action["action_id"])
	_require(
		payload["policies"],
		(
			"library_revision",
			"library_digest",
			"eligibility_revision",
			"eligibility_digest",
			"decision_revision",
			"decision_digest",
			"timing_revisions",
			"timing_digest",
		),
		"policies",
	)
	for field in ("library_digest", "eligibility_digest", "decision_digest", "timing_digest"):
		if not _is_hex64(payload["policies"][field]):
			raise ContractShapeError(f"policies.{field} must be a 64-char lowercase hex digest")


def assert_result_shape(payload):
	_reject_unknown_contract_version(payload)
	_require(payload, _RESULT_REQUIRED, "evaluation result")
	for field in ("evaluation_key", "input_digest", "result_digest"):
		if not _is_hex64(payload[field]):
			raise ContractShapeError(f"{field} must be a 64-char lowercase hex digest")
	if recompute_result_digest(payload) != payload["result_digest"]:
		raise ContractShapeError("result_digest does not bind the result envelope")
	if payload["run_status"] not in _RUN_STATUSES:
		raise ContractShapeError(f"unknown run_status {payload['run_status']!r}")
	disposition = payload["disposition"]
	if disposition not in _DISPOSITIONS:
		raise ContractShapeError(f"unknown disposition {disposition!r}")
	recommendations = payload["recommendations"]
	if not isinstance(recommendations, list) or len(recommendations) > _MAX_RECOMMENDATIONS:
		raise ContractShapeError("recommendations is not a bounded list")
	if disposition == "RECOMMEND" and not recommendations:
		raise ContractShapeError("RECOMMEND requires at least one recommendation")
	if disposition != "RECOMMEND" and recommendations:
		raise ContractShapeError(f"{disposition} must not carry recommendations")
	if disposition == "WAIT" and not (payload.get("revisit_at") or payload.get("reevaluation_trigger")):
		raise ContractShapeError("WAIT requires a revisit_at or a reevaluation_trigger")

	seen = set()
	ranks = []
	claimed_conflicts = set()
	for index, rec in enumerate(recommendations):
		where = f"recommendations[{index}]"
		_require(rec, _RECOMMENDATION_REQUIRED, where)
		if rec["recommendation_key"] in seen:
			raise ContractShapeError(f"{where}.recommendation_key is duplicated")
		seen.add(rec["recommendation_key"])
		if not isinstance(rec["rank"], int) or rec["rank"] < 1:
			raise ContractShapeError(f"{where}.rank must be a 1-based integer")
		ranks.append(rec["rank"])
		_require(rec["action_ref"], ("action_id", "action_revision", "action_digest"), f"{where}.action_ref")
		if not _is_hex64(rec["action_ref"]["action_digest"]):
			raise ContractShapeError(
				f"{where}.action_ref.action_digest must be a 64-char lowercase hex digest"
			)
		_require(rec["recommended_timing"], _TIMING_REQUIRED, f"{where}.recommended_timing")
		if not isinstance(rec["score"], dict) or "total" not in rec["score"]:
			raise ContractShapeError(f"{where}.score must be an object with a total")
		confidence = rec["confidence"]
		if not isinstance(confidence, (int, float)) or not 0.0 <= float(confidence) <= 1.0:
			raise ContractShapeError(f"{where}.confidence must be within [0, 1]")
		facts = rec["explanation_facts"]
		if not isinstance(facts, list) or len(facts) > _MAX_EXPLANATION_FACTS:
			raise ContractShapeError(f"{where}.explanation_facts is not a bounded list")
		if any(not isinstance(f, str) or len(f) > _MAX_EXPLANATION_FACT_CHARS for f in facts):
			raise ContractShapeError(f"{where}.explanation_facts has an oversized entry")
		conflicts = rec["conflict_keys"]
		if not isinstance(conflicts, list):
			raise ContractShapeError(f"{where}.conflict_keys must be a list")
		overlap = claimed_conflicts.intersection(conflicts)
		if overlap:
			raise ContractShapeError(
				f"{where} shares a hard conflict key with a higher rank: {sorted(overlap)}"
			)
		claimed_conflicts.update(conflicts)

	if sorted(ranks) != list(range(1, len(ranks) + 1)):
		raise ContractShapeError("recommendation ranks must be a dense 1-based sequence")


def assert_result_consistent_with_input(input_payload, result_payload):
	assert_input_shape(input_payload)
	assert_result_shape(result_payload)
	if result_payload["evaluation_key"] != input_payload["evaluation_key"]:
		raise ContractShapeError("result.evaluation_key does not match the input")
	if result_payload["input_digest"] != canonical_digest(input_payload):
		raise ContractShapeError("result.input_digest does not bind this evaluation input")
	allowed = {a["action_id"] for a in input_payload["eligible_action_set"]["actions"]}
	for index, rec in enumerate(result_payload["recommendations"]):
		if rec["action_ref"]["action_id"] not in allowed:
			raise ContractShapeError(
				f"recommendations[{index}].action_ref.action_id is outside the eligible action set"
			)


class TestNbaEvaluationContract(unittest.TestCase):
	def test_every_golden_envelope_has_a_byte_stable_canonical_digest(self):
		for name, expected in _EXPECTED_DIGESTS.items():
			self.assertEqual(canonical_digest(_load(name)), expected, name)

	def test_every_golden_envelope_has_a_fixed_raw_byte_hash(self):
		for name, expected in _EXPECTED_RAW_SHA256.items():
			self.assertEqual(hashlib.sha256((_FIXTURES / name).read_bytes()).hexdigest(), expected, name)

	def test_all_shipped_fixtures_are_covered_by_fixed_digests(self):
		shipped = {p.name for p in _FIXTURES.glob("*.json")}
		self.assertEqual(shipped, set(_EXPECTED_DIGESTS))
		self.assertEqual(shipped, set(_EXPECTED_RAW_SHA256))

	def test_valid_input_and_result_are_accepted_and_consistent(self):
		assert_result_consistent_with_input(_load("input-recommend.json"), _load("result-recommend.json"))

	def test_result_digest_binds_the_result_envelope(self):
		payload = _load("result-recommend.json")
		self.assertEqual(payload["result_digest"], recompute_result_digest(payload))
		payload["disposition"] = "NO_ACTION"
		payload["recommendations"] = []
		with self.assertRaises(ContractShapeError):
			assert_result_shape(payload)

	def test_input_digest_binds_the_paired_evaluation_input(self):
		input_payload = _load("input-recommend.json")
		result_payload = _load("result-recommend.json")
		self.assertEqual(result_payload["input_digest"], canonical_digest(input_payload))
		input_payload["student"]["context_revision"] = 999
		with self.assertRaises(ContractShapeError):
			assert_result_consistent_with_input(input_payload, result_payload)

	def test_wait_disposition_carries_a_revisit_and_no_recommendations(self):
		payload = _load("result-wait.json")
		assert_result_shape(payload)
		self.assertEqual(payload["recommendations"], [])
		self.assertTrue(payload["revisit_at"])

	def test_unknown_contract_version_fails_closed(self):
		with self.assertRaises(ContractShapeError):
			assert_result_shape(_load("result-unknown-major.json"))

	def test_additive_field_on_the_known_version_is_tolerated(self):
		payload = _load("result-recommend.json")
		payload["renderer_hint"] = "advisory-prose-v1"
		payload["result_digest"] = recompute_result_digest(payload)
		assert_result_shape(payload)

	def test_oversized_free_text_is_rejected_before_persistence(self):
		payload = _load("result-recommend.json")
		payload["recommendations"][0]["explanation_facts"] = ["x" * 801]
		payload["result_digest"] = recompute_result_digest(payload)
		with self.assertRaises(ContractShapeError):
			assert_result_shape(payload)

	def test_recommended_action_outside_the_eligible_set_is_rejected(self):
		with self.assertRaises(ContractShapeError):
			assert_result_consistent_with_input(
				_load("input-recommend.json"), _load("result-action-outside-eligible-set.json")
			)

	def test_duplicate_recommendation_key_is_rejected(self):
		with self.assertRaises(ContractShapeError):
			assert_result_shape(_load("result-duplicate-recommendation-key.json"))

	def test_two_recommendations_cannot_share_a_hard_conflict_key(self):
		payload = _load("result-recommend.json")
		payload["recommendations"][1]["conflict_keys"] = payload["recommendations"][0]["conflict_keys"]
		payload["result_digest"] = recompute_result_digest(payload)
		with self.assertRaises(ContractShapeError):
			assert_result_shape(payload)


if __name__ == "__main__":
	unittest.main()
