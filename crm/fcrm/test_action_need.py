import pytest

from crm.fcrm.action_need import (
	ACTION_NEED_CODE_BY_ACTION,
	need_code_for_action,
	need_group_for_action_category,
	need_group_matches_action,
)
from crm.fcrm.action_type_catalog import ACTION_TYPE_CODES


@pytest.mark.parametrize(
	("action_category", "expected_group"),
	[
		("CONTACT", "NEED_CONTACT"),
		("information", "NEED_INFORMATION"),
		("PARENT", "NEED_PARENT"),
		("INTERNAL", None),
		(None, None),
	],
)
def test_action_category_maps_to_need_group(action_category, expected_group):
	assert need_group_for_action_category(action_category) == expected_group


def test_internal_actions_do_not_accept_a_need_group():
	assert need_group_matches_action("INTERNAL", None)
	assert not need_group_matches_action("INTERNAL", "NEED_INFORMATION")


def test_one_need_group_accepts_many_actions():
	assert need_group_matches_action("INFORMATION", "NEED_INFORMATION")


def test_all_canonical_actions_have_a_detailed_need_mapping():
	assert set(ACTION_NEED_CODE_BY_ACTION) == set(ACTION_TYPE_CODES)
	assert need_code_for_action("SEND_PROGRAM_INFO") == "PROGRAM_INFORMATION"
	assert need_code_for_action("CREATE_TASK") is None
