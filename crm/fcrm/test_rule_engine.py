import pytest

from crm.fcrm.rule_engine import (
	active_rule_catalog,
	normalize_condition,
	normalize_rule_data,
	normalize_rule_version_data,
	normalize_target_actions,
)


def _rule(**overrides):
	value = {
		"rule_id": "CONTACT-CONSENT-001",
		"rule_group": "CONTACT_GOVERNANCE",
		"rule_name": "Block outbound contact after opt-out",
		"description": "Block contact recommendations when consent is withdrawn.",
		"feature_scope": "nba",
		"rule_type": "GUARDRAIL",
		"gate_outcome": "STOP",
		"priority": 900,
		"action": "BLOCK_CONTACT",
		"target_actions": ["CALL", "SEND_EMAIL", "SEND_ZALO"],
		"condition": {
			"all": [
				{"fact": "student.is_opted_out", "op": "is_true"},
				{
					"fact": "requested_action.channel",
					"op": "in",
					"value": ["CALL", "EMAIL", "MESSAGE"],
				},
			]
		},
		"status": "published",
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
	assert result["schema_version"] == "crm-rule-v1"


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
				"fact": "application.status",
				"op": "eq",
				"value": "Draft",
				"fact_ref": "student.stage",
			}
		)


def test_target_actions_reject_duplicates_and_invalid_codes():
	with pytest.raises(ValueError, match="duplicates"):
		normalize_target_actions(["CALL", "CALL"])
	with pytest.raises(ValueError, match="uppercase action codes"):
		normalize_target_actions(["CALL NOW"])


def test_active_catalog_is_sorted_and_digest_bound():
	first = _rule(rule_id="B-RULE-001", priority=10, revision=2)
	second = _rule(rule_id="A-RULE-001", priority=10, revision=1)

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
