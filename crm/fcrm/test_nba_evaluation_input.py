import json
import pathlib

from crm.fcrm.nba_evaluation_input import assemble_evaluation_input, input_digest
from crm.fcrm.test_nba_evaluation_contract import (
	assert_input_shape,
	assert_result_consistent_with_input,
	canonical_digest,
)

_FIXTURES = pathlib.Path(__file__).parent / "test_fixtures" / "nba-evaluation-v1"


def _load(name):
	return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _assemble_from_reference():
	reference = _load("input-recommend.json")
	return (
		assemble_evaluation_input(
			reference["student"],
			reference["context"],
			reference["eligible_action_set"],
			reference["policies"],
			now=reference["evaluation_clock"],
		),
		reference,
	)


def test_assembled_envelope_passes_the_shared_contract_shape():
	envelope, _ = _assemble_from_reference()
	assert_input_shape(envelope)
	assert envelope["contract_version"] == "nba-evaluation-v1"


def test_evaluation_key_is_a_deterministic_hex_digest():
	first, _ = _assemble_from_reference()
	second, _ = _assemble_from_reference()
	assert first["evaluation_key"] == second["evaluation_key"]
	assert len(first["evaluation_key"]) == 64
	assert all(c in "0123456789abcdef" for c in first["evaluation_key"])


def test_evaluation_key_changes_with_the_context_revision():
	envelope, reference = _assemble_from_reference()
	shifted_student = dict(
		reference["student"], context_revision=reference["student"]["context_revision"] + 1
	)
	shifted = assemble_evaluation_input(
		shifted_student,
		reference["context"],
		reference["eligible_action_set"],
		reference["policies"],
		now=reference["evaluation_clock"],
	)
	assert shifted["evaluation_key"] != envelope["evaluation_key"]


def test_evaluation_key_changes_with_the_policy_digests():
	envelope, reference = _assemble_from_reference()
	shifted_policies = dict(reference["policies"], decision_digest="f" * 64)
	shifted = assemble_evaluation_input(
		reference["student"],
		reference["context"],
		reference["eligible_action_set"],
		shifted_policies,
		now=reference["evaluation_clock"],
	)
	assert shifted["evaluation_key"] != envelope["evaluation_key"]


def test_evaluation_id_is_derived_from_the_key_and_sub_documents_pass_through():
	envelope, reference = _assemble_from_reference()
	assert envelope["evaluation_id"] == f"NBAEVAL-{envelope['evaluation_key'][:16]}"
	assert envelope["context"] == reference["context"]
	assert envelope["eligible_action_set"] == reference["eligible_action_set"]


def test_assembled_envelope_is_consistent_with_a_matching_result_fixture():
	envelope, _ = _assemble_from_reference()
	result = _load("result-recommend.json")
	result["evaluation_key"] = envelope["evaluation_key"]
	result["input_digest"] = input_digest(envelope)
	result["result_digest"] = canonical_digest({k: v for k, v in result.items() if k != "result_digest"})
	assert_result_consistent_with_input(envelope, result)
