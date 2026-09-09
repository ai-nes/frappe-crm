import json
from pathlib import Path

from crm.fcrm.action_constraints import defaults_for_action, validate_action_config
from crm.fcrm.action_type_catalog import (
	ACTION_TYPE_CATALOG,
	ACTION_TYPE_CODES,
	LEGACY_ACTION_TYPE_ALIASES,
	canonicalize_action_type,
	is_valid_configuration_code,
	metadata_for_action_type,
)
from crm.services.student_next_task_policy import choose_next_task_policy


def test_catalog_contains_exactly_79_unique_action_types():
	codes = [code for code, _display_name, _category in ACTION_TYPE_CATALOG]

	assert len(ACTION_TYPE_CATALOG) == 79
	assert len(codes) == len(set(codes)) == len(ACTION_TYPE_CODES)
	assert [sort_order for sort_order, _row in enumerate(ACTION_TYPE_CATALOG, start=1)] == list(range(1, 80))


def test_catalog_metadata_and_categories_are_complete():
	assert {category for _code, _display_name, category in ACTION_TYPE_CATALOG} == {
		"CONTACT",
		"INFORMATION",
		"ENGAGEMENT",
		"APPLICATION",
		"CONVERSION",
		"PARENT",
		"RECOVERY",
		"INTERNAL",
	}
	assert metadata_for_action_type("CALL") == {
		"action_type": "CALL",
		"display_name": "Gọi điện",
		"category": "CONTACT",
	}
	assert metadata_for_action_type("DOES_NOT_EXIST") is None


def test_legacy_action_types_are_aliases_not_catalog_rows():
	catalog_codes = {code for code, _display_name, _category in ACTION_TYPE_CATALOG}

	assert "CALL" in catalog_codes
	assert LEGACY_ACTION_TYPE_ALIASES - catalog_codes == {
		"EMAIL",
		"MESSAGE",
		"COUNSELING",
		"MEETING",
		"EVENT_INVITE",
		"CAMPUS_VISIT",
		"DOCUMENT_REQUEST",
		"APPLICATION_SUPPORT",
		"PARENT_CONTACT",
		"HANDOFF",
	}


def test_action_type_doctype_uses_reserved_name_safely():
	doctype_path = Path(__file__).parent / "doctype" / "crm_action_type" / "crm_action_type.json"
	doctype = json.loads(doctype_path.read_text(encoding="utf-8"))
	fields = {field["fieldname"]: field for field in doctype["fields"]}

	assert doctype["name"] == "CRM Action Type"
	assert doctype["autoname"] == "field:action_type"
	assert doctype["allow_import"] == 1
	assert "name" not in fields
	assert fields["action_type"]["unique"] == 1
	assert fields["display_name"]["reqd"] == 1


def test_next_task_policy_maps_legacy_names_to_catalog_codes():
	action, _objective, actionable = choose_next_task_policy(
		"application documents", "Consulting", ["REQUEST_MISSING_DOCUMENT", "CALL"]
	)

	assert action == "REQUEST_MISSING_DOCUMENT"
	assert actionable is True


def test_legacy_action_types_canonicalize_at_write_boundaries():
	assert canonicalize_action_type("EMAIL") == "SEND_EMAIL"
	assert canonicalize_action_type("PARENT_CONTACT") == "CONTACT_PARENT"
	assert canonicalize_action_type("WAIT") == "WAIT"


def test_parent_next_task_policy_uses_canonical_code_when_authorized():
	action, _objective, actionable = choose_next_task_policy(
		"parent contact", "Lead", ["CONTACT_PARENT", "CALL"], parent_authorized=True
	)

	assert action == "CONTACT_PARENT"
	assert actionable is True


def test_action_defaults_are_compatible_with_action_master_constraints():
	for code, _display_name, category in ACTION_TYPE_CATALOG:
		defaults = defaults_for_action(code, category)
		validate_action_config(code, category, **defaults, enabled=1)

	defaults = defaults_for_action("SEND_EMAIL", "CONTACT")

	assert defaults["default_channel"] == "EMAIL"
	assert defaults["execution_type"] == "AI_ASSISTED"
	assert defaults["ai_allowed"] == 1
	assert set(json.loads(defaults["allowed_actors"])) == {
		"CTV Sale",
		"Sale",
		"Lead Sale",
		"Admissions Director",
	}

	# A recipient-facing action with no channel in its code still resolves to a
	# concrete channel and carries the daytime contact windows.
	advise = defaults_for_action("ADVISE_CAREER", "CONVERSION")
	assert advise["default_channel"] == "CALL"
	assert json.loads(advise["allowed_time_slots"]) == ["6-12", "12-18", "18-24"]

	# An internal action stays NONE and unrestricted.
	internal = defaults_for_action("CREATE_TASK", "INTERNAL")
	assert internal["default_channel"] == "NONE"
	assert json.loads(internal["allowed_time_slots"]) == []


def test_action_constraints_reject_a_fixed_channel_mismatch():
	defaults = defaults_for_action("SEND_EMAIL", "CONTACT")

	try:
		validate_action_config(
			"SEND_EMAIL",
			"CONTACT",
			**{**defaults, "default_channel": "CALL"},
			enabled=1,
		)
	except ValueError as exc:
		assert "channel" in str(exc)
	else:
		raise AssertionError("SEND_EMAIL must not be configured with CALL")


def test_manager_actions_cannot_be_opened_to_sales_roles():
	defaults = defaults_for_action("ESCALATE_SUPERVISOR", "CONTACT")

	try:
		validate_action_config(
			"ESCALATE_SUPERVISOR",
			"CONTACT",
			**{**defaults, "allowed_actors": '["Sale"]'},
			enabled=1,
		)
	except ValueError as exc:
		assert "manager" in str(exc)
	else:
		raise AssertionError("manager-only action must not be executable by Sale")


def test_action_constraints_reject_conflicting_execution_configuration():
	defaults = defaults_for_action("CREATE_TASK", "INTERNAL")

	try:
		validate_action_config(
			"CREATE_TASK",
			"INTERNAL",
			**{**defaults, "requires_approval": 1, "auto_execute": 1},
			enabled=1,
		)
	except ValueError as exc:
		assert "approval" in str(exc)
	else:
		raise AssertionError("conflicting approval and auto-execute flags must be rejected")


def test_action_constraints_accept_allowed_time_slots_subset():
	defaults = defaults_for_action("CALL", "CONTACT")

	assert set(json.loads(defaults["allowed_time_slots"])) == {"6-12", "12-18", "18-24"}
	validate_action_config("CALL", "CONTACT", **defaults, enabled=1)


def test_custom_action_codes_use_the_same_safe_configuration_contract():
	assert is_valid_configuration_code("CUSTOM_FOLLOW_UP") is True
	assert is_valid_configuration_code("custom-follow-up") is False
	validate_action_config(
		"CUSTOM_FOLLOW_UP",
		"CUSTOM_SALES",
		"NONE",
		'["Sale"]',
		0,
		0,
		1,
		allow_custom=True,
	)


def test_action_constraints_reject_unknown_time_slot():
	defaults = defaults_for_action("CALL", "CONTACT")

	try:
		validate_action_config(
			"CALL", "CONTACT", **{**defaults, "allowed_time_slots": ["0-6", "midnight"]}, enabled=1
		)
	except ValueError as exc:
		assert "allowed_time_slots" in str(exc)
	else:
		raise AssertionError("an unsupported time slot code must be rejected")
