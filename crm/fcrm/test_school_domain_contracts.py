"""Schema and controller contracts for the school-domain DocTypes."""

from __future__ import annotations

import json
import sys
import types
from datetime import datetime
from importlib import import_module
from pathlib import Path

import pytest


class _ValidationError(Exception):
	pass


class _PermissionError(Exception):
	pass


class _DuplicateEntryError(Exception):
	pass


def _ensure_frappe_modules():
	try:
		import frappe
	except ModuleNotFoundError:
		frappe = types.ModuleType("frappe")
		sys.modules["frappe"] = frappe
	if not hasattr(frappe, "ValidationError"):
		frappe.ValidationError = _ValidationError
		frappe.PermissionError = _PermissionError
		frappe.DuplicateEntryError = _DuplicateEntryError
	if "frappe.model.document" not in sys.modules:
		model = types.ModuleType("frappe.model")
		document = types.ModuleType("frappe.model.document")
		document.Document = type("Document", (), {})
		sys.modules["frappe.model"] = model
		sys.modules["frappe.model.document"] = document
		frappe.model = model
		model.document = document
	if "frappe.utils" not in sys.modules:
		utils = types.ModuleType("frappe.utils")
		utils.nowdate = lambda: "2026-08-30"
		utils.now_datetime = lambda: datetime(2026, 8, 30, 0, 0, 0)
		sys.modules["frappe.utils"] = utils
	if not hasattr(frappe, "throw"):
		def throw(message, exception=None):
			raise (exception or Exception)(message)

		frappe.throw = throw
	if not hasattr(frappe, "whitelist"):
		frappe.whitelist = lambda *_args, **_kwargs: (lambda func: func)


_ensure_frappe_modules()

ROOT = Path(__file__).parents[2]

high_school_module = import_module("crm.fcrm.doctype.crm_high_school.crm_high_school")
snapshot_module = import_module(
	"crm.fcrm.doctype.crm_high_school_annual_snapshot.crm_high_school_annual_snapshot"
)
import importlib.util
_school_domain_spec = importlib.util.spec_from_file_location(
	"crm_api_school_domain_under_test", ROOT / "crm/api/school_domain.py"
)
school_domain_module = importlib.util.module_from_spec(_school_domain_spec)
sys.modules[_school_domain_spec.name] = school_domain_module
_school_domain_spec.loader.exec_module(school_domain_module)

def _meta(relative_path: str) -> dict:
	return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def _fields(meta: dict) -> dict:
	return {field["fieldname"]: field for field in meta["fields"] if "fieldname" in field}


def _permission_verbs(meta: dict, role: str) -> set[str]:
	verbs = set()
	for row in meta["permissions"]:
		if row["role"] != role:
			continue
		verbs.update(key for key in ("read", "write", "create", "delete", "export") if row.get(key))
	return verbs


class _Doc:
	def __init__(self, **values):
		self.__dict__.update(values)

	def get(self, fieldname, default=None):
		return getattr(self, fieldname, default)

	def is_new(self):
		return not getattr(self, "name", None)

	def get_doc_before_save(self):
		return getattr(self, "_previous", None)


def _snapshot_doc(**values):
	doc = _Doc(**values)
	doc._validate_grain = lambda: snapshot_module.CRMHighSchoolAnnualSnapshot._validate_grain(doc)
	doc._validate_threshold = lambda: snapshot_module.CRMHighSchoolAnnualSnapshot._validate_threshold(doc)
	doc._validate_lock = lambda: snapshot_module.CRMHighSchoolAnnualSnapshot._validate_lock(doc)
	return doc


class _DB:
	def __init__(self):
		self.exists_result = False
		self.values = {}
		self.set_values = []

	def exists(self, doctype, _filters=None):
		return self.exists_result

	def get_value(self, doctype, name, fields, as_dict=False):
		value = self.values.get((doctype, name))
		if as_dict:
			return value
		return value.get(fields) if value else None

	def set_value(self, doctype, name, values, **kwargs):
		self.set_values.append((doctype, name, values, kwargs))


class _Frappe:
	ValidationError = _ValidationError
	PermissionError = _PermissionError
	DuplicateEntryError = _DuplicateEntryError

	def __init__(self):
		self.db = _DB()
		self.session = types.SimpleNamespace(user="Administrator")
		self.snapshot_rows = []
		self.roles = []
		self.last_get_all_kwargs = None

	def get_all(self, *_args, **_kwargs):
		self.last_get_all_kwargs = _kwargs
		return self.snapshot_rows

	def get_roles(self, _user):
		return self.roles

	def throw(self, message, exception=None):
		raise (exception or Exception)(message)


def test_school_domain_schema_uses_canonical_links_and_minimal_fields():
	high_school = _meta("crm/fcrm/doctype/crm_high_school/crm_high_school.json")
	snapshot = _meta("crm/fcrm/doctype/crm_high_school_annual_snapshot/crm_high_school_annual_snapshot.json")
	activity = _meta("crm/fcrm/doctype/crm_school_activity/crm_school_activity.json")
	association = _meta("crm/fcrm/doctype/crm_school_stakeholder/crm_school_stakeholder.json")
	high_school_fields = _fields(high_school)
	snapshot_fields = _fields(snapshot)
	activity_fields = _fields(activity)
	association_fields = _fields(association)

	assert high_school_fields["school_type"]["options"] == "CRM School Type"
	assert high_school_fields["school_area"]["fieldtype"] == "Link"
	assert high_school_fields["school_area"]["options"] == "CRM School Area"
	assert high_school_fields["province"]["options"] == "CRM Province"
	assert high_school_fields["ward"]["options"] == "CRM Ward"
	assert high_school_fields["is_key_account"]["read_only"] == 1
	assert high_school_fields["is_key_account"]["fieldtype"] == "Check"
	assert not {"province_name", "ward_name", "source_identity"} & set(high_school_fields)

	assert snapshot_fields["high_school"] == {
		"fieldname": "high_school",
		"fieldtype": "Link",
		"in_list_view": 1,
		"in_standard_filter": 1,
		"label": "High School",
		"options": "CRM High School",
		"reqd": 1,
	}
	assert snapshot_fields["admission_year"]["options"] == "CRM Admission Year"
	assert snapshot_fields["admission_year"]["reqd"] == 1
	assert snapshot_fields["ne_actual"]["read_only"] == 1
	assert snapshot_fields["key_account_eligible"]["read_only"] == 1
	assert {"applicant_count", "enrolled_count", "contact_count", "student_count", "conversion_count"} <= set(
		snapshot_fields
	)
	assert {"context_raw_counts", "average_score", "conversion_rate", "enrollment_rate"} <= set(
		snapshot_fields
	)
	assert snapshot_fields["context_raw_counts"]["read_only"] == 1
	assert snapshot_fields["average_score"]["read_only"] == 1
	assert snapshot_fields["conversion_rate"]["read_only"] == 1
	assert snapshot_fields["enrollment_rate"]["read_only"] == 1

	assert activity_fields["stakeholder"]["options"] == "CRM School Stakeholder"
	assert activity_fields["activity_type"]["options"] == "CRM School Activity Type"
	assert activity_fields["status"]["options"].splitlines() == ["Planned", "Completed", "Cancelled"]
	assert {"contact_count", "application_count"} <= set(activity_fields)
	assert not {"ne_output", "source_record_id", "source_identity", "source_doctype", "source_docname"} & set(activity_fields)
	assert {"high_school", "person", "stakeholder_role", "position_title", "owner_staff", "owning_team"} <= set(association_fields)

	unique_indexes = [index for index in snapshot["indexes"] if index.get("unique")]
	assert any(
		set(index["fields"]) == {"high_school", "admission_year", "period_type", "period", "revision"}
		for index in unique_indexes
	)


def test_school360_endpoint_is_named_bounded_and_redacted():
	source = (ROOT / "crm/api/school_domain.py").read_text(encoding="utf-8")
	endpoint = source.split("def get_school360_overview", 1)[1]
	assert "high_school: str, admission_year: str | None = None" in endpoint
	assert "method_name" not in endpoint
	assert '"phone"' not in endpoint
	assert '"email"' not in endpoint
	assert '"source_system"' not in endpoint
	assert '"ne_target"' not in endpoint
	assert '"adjusted_ne_threshold"' not in endpoint
	assert '"contact_count"' in endpoint  # explicitly redacted child metric
	assert "RECOMMENDATION_KILL_SWITCH_CONFIG_KEY" in endpoint
	assert 'rollout == "shadow"' in endpoint
	assert 'intelligence_section.get("status") != "available"' in endpoint
	assert 'potential.get("state") != "current"' in endpoint


def _recommendation_overview(*, freshness="fresh", intelligence_status="available", complete=True):
	proof = {"permitted": complete, "scope_proof": complete}
	return {
		"freshness": freshness,
		"identity": {"status": "available"},
		"intelligence": {"status": intelligence_status, "data": {
			"potential": {"value": "High", "state": "current"},
			"relationship": {"value": "Active", "state": "current"},
		}},
		"source_data_revision": "source-1", "principal_scope_revision": "scope-1",
		"scope_by_resource": {"Snapshot": proof, "Person": proof},
		"relationship_scope": proof,
	}


def test_recommendation_endpoint_rollout_and_sufficiency_branches(monkeypatch):
	class FakeFrappe:
		PermissionError = _PermissionError
		def __init__(self, conf, roles):
			self.conf, self._roles = conf, roles
		def get_roles(self):
			return self._roles

		def _set(self, conf, roles):
			self.conf, self._roles = conf, roles

	fake = FakeFrappe({}, [])
	monkeypatch.setattr(school_domain_module, "frappe", fake)
	monkeypatch.setattr(school_domain_module, "get_school360_overview", lambda _school: _recommendation_overview())
	with pytest.raises(_PermissionError):
		school_domain_module.get_school_recommendation_context("HS-1", "outreach")
	fake._set({school_domain_module.RECOMMENDATION_ROLLOUT_CONFIG_KEY: "shadow", school_domain_module.RECOMMENDATION_KILL_SWITCH_CONFIG_KEY: "0"}, [])
	assert school_domain_module.get_school_recommendation_context("HS-1", "outreach")["disposition"] == "REVIEW"
	fake._set({school_domain_module.RECOMMENDATION_ROLLOUT_CONFIG_KEY: "pilot", school_domain_module.RECOMMENDATION_KILL_SWITCH_CONFIG_KEY: "0"}, ["Sale"])
	with pytest.raises(_PermissionError):
		school_domain_module.get_school_recommendation_context("HS-1", "outreach")
	fake._set({school_domain_module.RECOMMENDATION_ROLLOUT_CONFIG_KEY: "pilot", school_domain_module.RECOMMENDATION_KILL_SWITCH_CONFIG_KEY: "0", school_domain_module.RECOMMENDATION_GATE_REVISION_CONFIG_KEY: "gate-1"}, ["Admissions Director"])
	monkeypatch.setattr(school_domain_module, "get_school360_overview", lambda _school: _recommendation_overview(intelligence_status="partial", complete=False))
	assert school_domain_module.get_school_recommendation_context("HS-1", "outreach")["disposition"] != "RECOMMEND"
	monkeypatch.setattr(school_domain_module, "get_school360_overview", lambda _school: _recommendation_overview(freshness="stale"))
	assert school_domain_module.get_school_recommendation_context("HS-1", "outreach")["disposition"] != "RECOMMEND"
	monkeypatch.setattr(school_domain_module, "get_school360_overview", lambda _school: _recommendation_overview())
	assert school_domain_module.get_school_recommendation_context("HS-1", "outreach")["disposition"] == "RECOMMEND"


def test_promoter_can_operate_relationship_records_but_not_snapshot_governance():
	activity = _meta("crm/fcrm/doctype/crm_school_activity/crm_school_activity.json")
	person = _meta("crm/fcrm/doctype/crm_person/crm_person.json")
	snapshot = _meta("crm/fcrm/doctype/crm_high_school_annual_snapshot/crm_high_school_annual_snapshot.json")

	assert {"read", "write", "create"} <= _permission_verbs(activity, "Promoter")
	assert {"read", "write", "create"} <= _permission_verbs(person, "Promoter")
	assert _permission_verbs(snapshot, "Promoter") == {"read"}


def test_annual_snapshot_defaults_threshold_and_derives_eligibility(monkeypatch):
	fake_frappe = _Frappe()
	monkeypatch.setattr(snapshot_module, "frappe", fake_frappe)

	default_doc = _Doc(
		adjusted_ne_threshold=None,
		snapshot_date="2026-08-30",
		high_school=None,
		admission_year=None,
	)
	snapshot_module.CRMHighSchoolAnnualSnapshot.before_validate(default_doc)
	assert default_doc.adjusted_ne_threshold == 10

	for actual, threshold, expected in ((10, 10, 1), (9, 10, 0), (9, 8, 1), (None, 10, 0)):
		doc = _snapshot_doc(
			high_school="HS-1",
			admission_year="2026",
			ne_actual=actual,
			adjusted_ne_threshold=threshold,
			verification_status="Review Required",
			verified_by=None,
			verified_at=None,
			is_locked=0,
			locked_by=None,
			locked_at=None,
			name=None,
		)
		fake_frappe.db.exists_result = False
		snapshot_module.CRMHighSchoolAnnualSnapshot.validate(doc)
		assert doc.key_account_eligible == expected


def test_annual_snapshot_lock_field_bypasses_frappe_document_lock_property(monkeypatch):
	fake_frappe = _Frappe()
	monkeypatch.setattr(snapshot_module, "frappe", fake_frappe)

	class _FrameworkLockedDoc:
		is_locked = property(lambda self: True)

		def __init__(self):
			self.ne_actual = 0
			self.adjusted_ne_threshold = 10
			self.verification_status = "Review Required"
			self.verified_by = None
			self._values = {
				"high_school": "HS-1",
				"admission_year": "2026",
				"ne_actual": 0,
				"adjusted_ne_threshold": 10,
				"verification_status": "Review Required",
				"verified_by": None,
				"verified_at": None,
				"is_locked": 0,
				"locked_by": None,
				"locked_at": None,
				"name": None,
			}

		def get(self, fieldname, default=None):
			return self._values.get(fieldname, default)

		def set(self, fieldname, value):
			self._values[fieldname] = value

		def is_new(self):
			return True

		def get_doc_before_save(self):
			return None

	doc = _FrameworkLockedDoc()
	doc._validate_grain = lambda: None
	doc._validate_threshold = lambda: None
	doc._validate_lock = lambda: snapshot_module.CRMHighSchoolAnnualSnapshot._validate_lock(doc)
	snapshot_module.CRMHighSchoolAnnualSnapshot.validate(doc)
	assert doc.get("locked_by") is None
	assert doc.get("locked_at") is None


def test_annual_snapshot_duplicate_school_year_is_rejected(monkeypatch):
	fake_frappe = _Frappe()
	fake_frappe.db.exists_result = True
	monkeypatch.setattr(snapshot_module, "frappe", fake_frappe)
	doc = _Doc(high_school="HS-1", admission_year="2026", name=None)

	with pytest.raises(_DuplicateEntryError):
		snapshot_module.CRMHighSchoolAnnualSnapshot._validate_grain(doc)


def test_latest_snapshot_projects_derived_key_account_to_school(monkeypatch):
	fake_frappe = _Frappe()
	fake_frappe.db.exists_result = True
	fake_frappe.snapshot_rows = [
		types.SimpleNamespace(
			admission_year="2026",
			key_account_eligible=1,
			ne_actual=10,
			adjusted_ne_threshold=10,
			snapshot_date="2026-08-01",
		)
	]
	monkeypatch.setattr(high_school_module, "frappe", fake_frappe)
	doc = _Doc(name="HS-1", is_key_account=0)

	high_school_module.CRMHighSchool._sync_derived_key_account(doc)

	assert doc.is_key_account == 1
	assert fake_frappe.last_get_all_kwargs["filters"]["verification_status"] == "Verified"


def test_removing_last_verified_snapshot_clears_key_account_projection(monkeypatch):
	fake_frappe = _Frappe()
	fake_frappe.db.exists_result = True
	monkeypatch.setattr(snapshot_module, "frappe", fake_frappe)

	snapshot_module.refresh_school_key_account("HS-1")

	assert fake_frappe.db.set_values == [
		("CRM High School", "HS-1", {"is_key_account": 0}, {"update_modified": False})
	]


def test_snapshot_reprojects_key_account_only_after_delete(monkeypatch):
	refreshed = []
	monkeypatch.setattr(snapshot_module, "refresh_school_key_account", refreshed.append)

	snapshot_module.CRMHighSchoolAnnualSnapshot.after_delete(_Doc(high_school="HS-1"))

	assert refreshed == ["HS-1"]
	assert not hasattr(snapshot_module.CRMHighSchoolAnnualSnapshot, "on_trash")


@pytest.mark.parametrize("fieldname, value", [("ne_actual", 12), ("high_school", "HS-2"), ("admission_year", "2027")])
def test_verified_snapshot_identity_and_source_outcome_are_immutable(monkeypatch, fieldname, value):
	fake_frappe = _Frappe()
	monkeypatch.setattr(snapshot_module, "frappe", fake_frappe)
	doc = _snapshot_doc(
		high_school="HS-1",
		admission_year="2026",
		ne_actual=12,
		adjusted_ne_threshold=10,
		verification_status="Verified",
		verified_by="owner@example.com",
		verified_at="2026-08-30 00:00:00",
		is_locked=0,
		locked_by=None,
		locked_at=None,
		name="HS-1 - 2026",
		_previous=_Doc(verification_status="Verified", ne_actual=10, is_locked=0),
	)
	setattr(doc, fieldname, value)
	setattr(doc._previous, "high_school", "HS-1")
	setattr(doc._previous, "admission_year", "2026")

	with pytest.raises(_PermissionError):
		snapshot_module.CRMHighSchoolAnnualSnapshot._validate_lock(doc)


def test_promoter_cannot_change_key_account_governance_fields(monkeypatch):
	fake_frappe = _Frappe()
	fake_frappe.session.user = "promoter@example.com"
	fake_frappe.roles = ["Promoter"]
	monkeypatch.setattr(high_school_module, "frappe", fake_frappe)
	doc = _Doc(
		name="HS-1",
		key_account_tier="Tier 2",
		key_account_owner=None,
		key_account_team=None,
		is_key_account=0,
		_previous=_Doc(
			key_account_tier="Tier 1",
			key_account_owner=None,
			key_account_team=None,
			is_key_account=0,
		),
	)

	with pytest.raises(_PermissionError):
		high_school_module.CRMHighSchool._validate_key_account_governance(doc)


def test_stakeholder_primary_uniqueness_check_is_guarded_by_primary_flag():
	source = Path(ROOT / "crm/fcrm/doctype/crm_school_stakeholder/crm_school_stakeholder.py").read_text(
		encoding="utf-8"
	)
	assert "\t\tif self.is_primary:\n\t\t\tprimary_filters" in source
	assert "\t\t\tif frappe.db.exists(\"CRM School Stakeholder\", primary_filters):" in source
	assert "if not previous and self.relationship_status not in (None, \"\", \"New\")" in source
