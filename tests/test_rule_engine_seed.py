import pytest

pytest.importorskip("frappe")

from crm.fcrm.rule_engine import catalog_from_rows
from crm.fcrm.rule_engine_seed import (
	DOCUMENT_RULE_COUNT,
	PROTECTED_POLICIES,
	RULE_VERSION_ID,
	RULES,
	_canonical_seed_rule,
	_group_catalog_for,
)


def test_default_seed_builds_a_valid_current_rule_catalog():
	rows = [_canonical_seed_rule(row, RULE_VERSION_ID) for row in RULES]
	catalog = catalog_from_rows(
		rows,
		version_id=RULE_VERSION_ID,
		technical_revision=1,
		group_catalog=_group_catalog_for(RULES),
	)

	assert len(RULES) + len(PROTECTED_POLICIES) == DOCUMENT_RULE_COUNT
	assert len(catalog["rules"]) == len(RULES) == 83
	assert {group["code"] for group in catalog["rule_groups"]} == {
		"student_lifecycle",
		"application_admission",
		"program_offering",
		"communication",
		"timing_frequency",
		"scholarship_finance",
		"action_eligibility",
		"ai_admission",
		"ai_reliability",
		"nba_decision",
		"business_policy",
		"explainability",
	}
	assert len(catalog["ruleset_digest"]) == 64
