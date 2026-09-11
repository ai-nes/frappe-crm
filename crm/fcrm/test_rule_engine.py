import json
from pathlib import Path

import pytest

from crm.fcrm.rule_engine import (
	ACTION_CATALOG,
	CATALOG_FEATURES,
	FEATURE_SCOPES,
	RUNTIME_FEATURES,
	active_rule_catalog,
	canonicalize_ruleset,
	normalize_condition,
	normalize_rule_data,
	normalize_rule_version_data,
	normalize_target_actions,
	ruleset_digest,
	validate_catalog,
)


def _rule(**overrides):
	value = {
		"rule_id": "CONTACT-CONSENT-001",
		"group_code": "contact_governance",
		"rule_name": "Block outbound contact after opt-out",
		"description": "Block contact recommendations when consent is withdrawn.",
		"feature": "nba",
		"rule_type": "GUARDRAIL",
		"outcome": "STOP",
		"precedence": 900,
		"action": "BLOCK_CONTACT",
		"target_actions": ["CALL", "SEND_EMAIL", "SEND_ZALO"],
		"condition": {
			"all": [
				{"fact": "student.is_opted_out", "op": "is_true"},
				{
					"fact": "requested_action.code",
					"op": "in",
					"value": ["CALL", "SEND_EMAIL", "SEND_ZALO"],
				},
			]
		},
		"status": "active",
		"enabled": 1,
		"revision": 1,
	}
	value.update(overrides)
	return value


def test_normalize_rule_data_accepts_document_contract():
	result = normalize_rule_data(_rule())

	assert result["rule_id"] == "CONTACT-CONSENT-001"
	assert result["condition"]["all"][0]["op"] == "is_true"
	assert result["target_actions"] == ["CALL", "SEND_EMAIL", "SEND_ZALO"]
	assert result["schema_version"] == "rule-catalog"


def test_feature_registry_has_five_capabilities_and_one_global_scope():
	assert RUNTIME_FEATURES == (
		"conversation_analysis",
		"student_360",
		"school_360",
		"nba",
		"copilot",
	)
	assert FEATURE_SCOPES == {"all", *RUNTIME_FEATURES}
	assert CATALOG_FEATURES == set(RUNTIME_FEATURES)
	assert "all" not in CATALOG_FEATURES


def test_rule_action_catalog_covers_the_canonical_crm_action_taxonomy():
	assert len(ACTION_CATALOG) == 79
	assert len(set(ACTION_CATALOG)) == 79
	assert "VIDEO_CALL" in ACTION_CATALOG
	assert "REQUEST_SUPERVISOR_REVIEW" in ACTION_CATALOG


@pytest.mark.parametrize("legacy", ("intent", "scoring_ai"))
def test_legacy_feature_aliases_are_rejected_at_the_authoring_boundary(legacy):
	with pytest.raises(ValueError, match="feature must be one of"):
		normalize_rule_data(_rule(feature=legacy))


def test_all_scope_matches_every_capability_when_filtering_catalogs():
	rows = [
		_rule(rule_id="ALL-RULE-001", feature="all"),
		_rule(rule_id="SCHOOL-RULE-001", feature="school_360"),
		_rule(rule_id="NBA-RULE-001", feature="nba"),
	]

	school_catalog = active_rule_catalog(rows, feature_scope="school_360")
	all_catalog = active_rule_catalog(rows, feature_scope="all")

	assert [rule["rule_id"] for rule in school_catalog["rules"]] == [
		"ALL-RULE-001",
		"SCHOOL-RULE-001",
	]
	assert [rule["rule_id"] for rule in all_catalog["rules"]] == [
		"ALL-RULE-001",
		"NBA-RULE-001",
		"SCHOOL-RULE-001",
	]


def test_condition_rejects_executable_or_unknown_values():
	with pytest.raises(ValueError, match="not allowed"):
		normalize_condition(
			{"all": [{"fact": "student.password", "op": "eq", "value": "x"}]}
		)
	with pytest.raises(ValueError, match="unsupported key"):
		normalize_condition(
			{"all": [{"fact": "student.stage", "op": "eq", "value": "New", "eval": "x"}]}
		)
	with pytest.raises(ValueError, match="both value and fact_ref"):
		normalize_condition(
			{
				"fact": "student.is_opted_out",
				"op": "eq",
				"value": True,
				"fact_ref": "student.is_opted_out",
			}
		)


def test_target_actions_reject_duplicates_and_invalid_codes():
	with pytest.raises(ValueError, match="duplicates"):
		normalize_target_actions(["CALL", "CALL"])
	with pytest.raises(ValueError, match="uppercase action codes"):
		normalize_target_actions(["CALL NOW"])


def test_active_catalog_is_sorted_and_digest_bound():
	first = _rule(rule_id="B-RULE-001", precedence=10, revision=2)
	second = _rule(rule_id="A-RULE-001", precedence=10, revision=1)

	catalog = active_rule_catalog([first, second], feature_scope="nba")

	assert [rule["rule_id"] for rule in catalog["rules"]] == ["A-RULE-001", "B-RULE-001"]
	assert catalog["ruleset_revision"].startswith("crm-rule-set-r2-")
	assert len(catalog["ruleset_digest"]) == 64


def test_rule_revision_must_be_a_non_negative_integer():
	with pytest.raises(ValueError, match="revision"):
		normalize_rule_data(_rule(revision="not-an-integer"))


def test_rule_version_requires_non_empty_id_and_name():
	with pytest.raises(ValueError, match="version_id is required"):
		normalize_rule_version_data({"version_id": "", "version_name": "Rules"})
	with pytest.raises(ValueError, match="version_name is required"):
		normalize_rule_version_data({"version_id": "V1.0.0", "version_name": ""})


def test_active_catalog_uses_published_version_metadata():
	catalog = active_rule_catalog(
		[_rule(rule_version="V2.0.0")],
		feature_scope="nba",
		metadata={
			"version_id": "V2.0.0",
			"version_name": "Current",
			"ruleset_revision": "crm-rule-set-V2.0.0-r7-test",
			"ruleset_digest": "a" * 64,
		},
	)

	assert catalog["version_id"] == "V2.0.0"
	assert catalog["ruleset_revision"] == "crm-rule-set-V2.0.0-r7-test"
	assert catalog["ruleset_digest"] == "a" * 64


def _golden_catalog():
	path = Path(__file__).parents[1] / "tests" / "fixtures" / "rule-catalog" / "valid.json"
	return json.loads(path.read_text(encoding="utf-8"))


def _golden_fixture(name):
	path = Path(__file__).parents[1] / "tests" / "fixtures" / "rule-catalog" / f"{name}.json"
	return json.loads(path.read_text(encoding="utf-8"))


def test_golden_catalog_has_a_stable_cross_repository_digest():
	catalog = _golden_catalog()
	manifest_path = Path(__file__).parents[1] / "tests" / "fixtures" / "rule-catalog" / "manifest.json"
	expected = json.loads(manifest_path.read_text(encoding="utf-8"))["valid"]
	assert ruleset_digest(catalog) == expected
	assert validate_catalog({**catalog, "ruleset_digest": expected})["ruleset_digest"] == expected
	assert canonicalize_ruleset(catalog) == canonicalize_ruleset(dict(reversed(list(catalog.items()))))


@pytest.mark.parametrize("fixture_name", ("duplicate-id", "unknown-registry", "digest-mismatch", "invalid-template"))
def test_catalog_rejects_each_named_negative_fixture(fixture_name):
	catalog = _golden_fixture(fixture_name)
	with pytest.raises(ValueError):
		validate_catalog(catalog)


def test_unordered_input_fixture_has_a_stable_rule_order_and_digest():
	catalog = _golden_fixture("unordered-input")
	manifest_path = Path(__file__).parents[1] / "tests" / "fixtures" / "rule-catalog" / "manifest.json"
	expected = json.loads(manifest_path.read_text(encoding="utf-8"))["unordered-input"]
	assert ruleset_digest(catalog) == expected
	assert canonicalize_ruleset(catalog) == canonicalize_ruleset({**catalog, "rules": list(reversed(catalog["rules"]))})
