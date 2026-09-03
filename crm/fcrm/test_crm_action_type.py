import json
from pathlib import Path

from crm.fcrm.action_type_catalog import (
	ACTION_TYPE_CATALOG,
	ACTION_TYPE_CODES,
	LEGACY_ACTION_TYPE_ALIASES,
	canonicalize_action_type,
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
