"""Portfolio and role-boundary contracts for school relationship records."""

from __future__ import annotations

import json
import sys
import types
from importlib import import_module
from pathlib import Path

import pytest


def _ensure_frappe_importable():
	try:
		import frappe
	except ModuleNotFoundError:
		frappe = types.ModuleType("frappe")
		sys.modules["frappe"] = frappe


_ensure_frappe_importable()

permissions = import_module("crm.fcrm.school_domain_permissions")
capabilities_for_roles = import_module("crm.fcrm.role_policy").capabilities_for_roles


ROOT = Path(__file__).parents[2]


class _PermissionError(Exception):
	pass


class _DB:
	def __init__(self):
		self.sql_rows = []

	def get_value(self, doctype, filters, _field):
		if doctype == "CRM Staff" and isinstance(filters, dict):
			return "STAFF-1" if filters.get("user") == "promoter@example.com" else None
		return None

	def escape(self, value):
		return "'" + str(value).replace("'", "''") + "'"

	def sql(self, *_args, **_kwargs):
		return self.sql_rows


class _Frappe:
	PermissionError = _PermissionError

	def __init__(self):
		self.db = _DB()
		self.session = types.SimpleNamespace(user="promoter@example.com")
		self.roles = ["Promoter"]
		self.teams = ["TEAM-A"]

	def get_roles(self, user):
		return self.roles

	def get_all(self, doctype, **_kwargs):
		if doctype == "CRM Team Membership":
			return self.teams
		return []

	def throw(self, message, exception=None):
		raise (exception or Exception)(message)


class _Doc:
	def __init__(self, **values):
		self.__dict__.update(values)

	def get(self, fieldname, default=None):
		return getattr(self, fieldname, default)

	def is_new(self):
		return not getattr(self, "name", None)

	def get_doc_before_save(self):
		return getattr(self, "_previous", None)


def _meta(relative_path: str) -> dict:
	return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def _verbs(meta: dict, role: str) -> set[str]:
	verbs = set()
	for permission in meta["permissions"]:
		if permission["role"] == role:
			verbs.update(key for key in ("read", "write", "create", "delete", "export") if permission.get(key))
	return verbs


def test_promoter_portfolio_condition_is_owner_or_assigned_team(monkeypatch):
	fake_frappe = _Frappe()
	monkeypatch.setattr(permissions, "frappe", fake_frappe)

	condition = permissions.portfolio_condition("CRM School Activity", "promoter@example.com")

	assert condition.startswith("(")
	assert "owner_staff" in condition
	assert "owning_team" in condition
	assert "STAFF-1" in condition
	assert "TEAM-A" in condition


def test_promoter_without_staff_scope_fails_closed(monkeypatch):
	fake_frappe = _Frappe()
	fake_frappe.db.get_value = lambda *_args, **_kwargs: None
	monkeypatch.setattr(permissions, "frappe", fake_frappe)

	assert permissions.person_portfolio_condition("promoter@example.com") == "1=0"
	assert permissions.school_portfolio_condition("CRM High School", "promoter@example.com") == "1=0"


def test_unscoped_roles_are_not_granted_relationship_rows(monkeypatch):
	fake_frappe = _Frappe()
	fake_frappe.roles = ["Unrelated Role"]
	monkeypatch.setattr(permissions, "frappe", fake_frappe)

	assert permissions.person_portfolio_condition("other@example.com") == "1=0"


def test_marketing_and_governance_roles_keep_explicit_full_row_contract(monkeypatch):
	fake_frappe = _Frappe()
	monkeypatch.setattr(permissions, "frappe", fake_frappe)

	for role in ("Marketing", "Sale", "Lead Sale", "Admissions Director"):
		fake_frappe.roles = [role]
		assert permissions.person_portfolio_condition("other@example.com") is None
		assert permissions.school_portfolio_condition("CRM High School", "other@example.com") is None


def test_promoter_school_and_snapshot_scope_follow_stakeholder_portfolio(monkeypatch):
	fake_frappe = _Frappe()
	monkeypatch.setattr(permissions, "frappe", fake_frappe)

	school_condition = permissions.school_portfolio_condition("CRM High School", "promoter@example.com")
	snapshot_condition = permissions.school_portfolio_condition(
		"CRM High School Annual Snapshot", "promoter@example.com", school_field="high_school"
	)

	assert "CRM School Stakeholder" in school_condition
	assert "`tabCRM High School`.`name`" in school_condition
	assert "`tabCRM High School Annual Snapshot`.`high_school`" in snapshot_condition
	assert "STAFF-1" in school_condition
	assert "TEAM-A" in snapshot_condition


def test_create_is_allowed_to_docperm_but_existing_rows_use_portfolio_ceiling(monkeypatch):
	fake_frappe = _Frappe()
	monkeypatch.setattr(permissions, "frappe", fake_frappe)

	new_doc = _Doc(doctype="CRM School Activity", name=None)
	assert permissions.has_portfolio_permission(new_doc, "promoter@example.com", ptype="create") is True

	fake_frappe.db.sql_rows = [("ACT-1",)]
	existing_doc = _Doc(doctype="CRM School Activity", name="ACT-1")
	assert permissions.has_portfolio_permission(existing_doc, "promoter@example.com") is True
	fake_frappe.db.sql_rows = []
	assert permissions.has_portfolio_permission(existing_doc, "promoter@example.com") is False


def test_new_relationship_record_defaults_to_current_staff_and_team(monkeypatch):
	fake_frappe = _Frappe()
	monkeypatch.setattr(permissions, "frappe", fake_frappe)
	doc = _Doc(owner_staff=None, owning_team=None)

	permissions.default_portfolio(doc, "promoter@example.com")

	assert doc.owner_staff == "STAFF-1"
	assert doc.owning_team == "TEAM-A"


def test_promoter_cannot_grant_another_portfolio_scope_on_create(monkeypatch):
	fake_frappe = _Frappe()
	monkeypatch.setattr(permissions, "frappe", fake_frappe)
	doc = _Doc(owner_staff="STAFF-OTHER", owning_team="TEAM-OTHER", name=None)

	with pytest.raises(_PermissionError):
		permissions.validate_portfolio_update(doc, "promoter@example.com")


def test_promoter_cannot_update_record_outside_portfolio(monkeypatch):
	fake_frappe = _Frappe()
	fake_frappe.db.sql_rows = []
	monkeypatch.setattr(permissions, "frappe", fake_frappe)
	doc = _Doc(
		doctype="CRM School Activity",
		name="ACT-OTHER",
		owner_staff="STAFF-OTHER",
		owning_team="TEAM-OTHER",
		_previous=_Doc(owner_staff="STAFF-OTHER", owning_team="TEAM-OTHER"),
	)

	with pytest.raises(_PermissionError):
		permissions.validate_portfolio_update(doc, "promoter@example.com")


def test_docperm_and_role_policy_keep_promoter_in_marketing_boundary():
	activity = _meta("crm/fcrm/doctype/crm_school_activity/crm_school_activity.json")
	person = _meta("crm/fcrm/doctype/crm_person/crm_person.json")
	association = _meta("crm/fcrm/doctype/crm_school_stakeholder/crm_school_stakeholder.json")
	snapshot = _meta("crm/fcrm/doctype/crm_high_school_annual_snapshot/crm_high_school_annual_snapshot.json")
	high_school = _meta("crm/fcrm/doctype/crm_high_school/crm_high_school.json")

	assert {"read", "write", "create"} <= _verbs(activity, "Promoter")
	assert {"read", "write", "create"} <= _verbs(person, "Promoter")
	assert {"read", "write", "create"} <= _verbs(association, "Promoter")
	assert _verbs(snapshot, "Promoter") == {"read"}
	assert "read" in _verbs(high_school, "Promoter")

	promoter_capabilities = capabilities_for_roles(["Promoter"])
	assert {"school.activity.manage", "school.person.manage"} <= promoter_capabilities
	assert not promoter_capabilities & {
		"student.execute",
		"conversion.execute",
		"lifecycle.transition",
		"lifecycle.lost",
		"student.ownership.manage",
	}


def test_permission_hooks_are_registered_for_both_relationship_doctypes():
	from crm import hooks

	assert hooks.permission_query_conditions["CRM Person"].endswith("crm_person.get_permission_query_conditions")
	assert hooks.permission_query_conditions["CRM School Stakeholder"].endswith(
		"crm_school_stakeholder.get_permission_query_conditions"
	)
	assert hooks.permission_query_conditions["CRM School Activity"].endswith(
		"crm_school_activity.get_permission_query_conditions"
	)
	assert hooks.permission_query_conditions["CRM High School"].endswith(
		"crm_high_school.get_permission_query_conditions"
	)
	assert hooks.permission_query_conditions["CRM High School Annual Snapshot"].endswith(
		"crm_high_school_annual_snapshot.get_permission_query_conditions"
	)
	assert hooks.has_permission["CRM Person"].endswith("crm_person.has_permission")
	assert hooks.has_permission["CRM School Stakeholder"].endswith("crm_school_stakeholder.has_permission")
	assert hooks.has_permission["CRM School Activity"].endswith("crm_school_activity.has_permission")
	assert hooks.has_permission["CRM High School"].endswith("crm_high_school.has_permission")
	assert hooks.has_permission["CRM High School Annual Snapshot"].endswith(
		"crm_high_school_annual_snapshot.has_permission"
	)
