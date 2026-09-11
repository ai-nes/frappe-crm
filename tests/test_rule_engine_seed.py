import pytest

pytest.importorskip("frappe")

from crm.fcrm.rule_engine import catalog_from_rows
from crm.fcrm.rule_engine_seed import (
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

	assert len(catalog["rules"]) == len(RULES)
	assert {group["code"] for group in catalog["rule_groups"]} == {
		"student_eligibility",
		"communication",
		"funnel",
		"action",
	}
	assert len(catalog["ruleset_digest"]) == 64
