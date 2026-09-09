from unittest.mock import patch

from crm.fcrm import segment_rules


def test_need_predicate_includes_action_item_chain():
	condition = {"field": "need", "operator": "in", "value": ["NEED-001"]}
	with patch.object(segment_rules.frappe.db, "escape", side_effect=lambda value: f"'{value}'"):
		predicate = segment_rules._classification_predicate(condition)

	assert "`tabCRM Student Need Assignment`" in predicate
	assert "`tabCRM Action Item` action_item" in predicate
	assert "INNER JOIN `tabCRM Action` action" in predicate
	assert "COALESCE(action_item.legacy_task_deleted, 0) = 0" in predicate
	assert "action.need IN ('NEED-001')" in predicate


def test_negative_need_predicate_excludes_action_item_chain():
	condition = {"field": "need", "operator": "not in", "value": ["NEED-001"]}
	with patch.object(segment_rules.frappe.db, "escape", side_effect=lambda value: f"'{value}'"):
		predicate = segment_rules._classification_predicate(condition)

	assert predicate.startswith("NOT (")
	assert "action_item.student = allowed.name" in predicate
