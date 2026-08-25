from crm.fcrm.doctype.crm_sales_action.crm_sales_action import CRMSalesAction


def test_action_transition_table_keeps_terminal_states_closed():
	assert CRMSalesAction._ALLOWED_TRANSITIONS["planned"] == {"in_progress", "cancelled"}
	assert "completed" not in CRMSalesAction._ALLOWED_TRANSITIONS.get("completed", set())


def test_assignment_snapshot_is_immutable_but_history_is_command_owned():
	assert "assignee_snapshot" in CRMSalesAction._IMMUTABLE_FIELDS
	assert "assignment_revision" not in CRMSalesAction._IMMUTABLE_FIELDS
