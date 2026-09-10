"""Deterministic contracts for authoritative School intelligence."""

from __future__ import annotations

import sys
import types
from importlib import import_module


try:
	import frappe  # noqa: F401
except ModuleNotFoundError:
	frappe = types.ModuleType("frappe")
	sys.modules["frappe"] = frappe
	utils = types.ModuleType("frappe.utils")
	utils.now_datetime = lambda: "2026-08-31 00:00:00"
	utils.nowdate = lambda: "2026-08-31"
	sys.modules["frappe.utils"] = utils

intelligence = import_module("crm.fcrm.school_intelligence")


class _Frappe:
	def __init__(self, snapshots=None, stakeholders=None):
		self.snapshots = snapshots or []
		self.stakeholders = stakeholders or []

	def get_list(self, doctype, **_kwargs):
		if doctype == "CRM High School Annual Snapshot":
			return self.snapshots
		if doctype == "CRM School Stakeholder":
			return self.stakeholders
		return []


def test_potential_is_school_level_and_revisioned(monkeypatch):
	monkeypatch.setattr(intelligence, "frappe", _Frappe(snapshots=[{
		"name": "SNAP-1", "revision": 2, "snapshot_date": "2026-08-30",
		"ne_actual": 20, "adjusted_ne_threshold": 10,
		"applicant_count": 100, "enrolled_count": 20,
	}]))

	result = intelligence.calculate_school_potential("HS-1", "2026")

	assert result["value"] == "High"
	assert result["policy_version"] == intelligence.POLICY_VERSION
	assert result["source_data_revision"]
	assert result["inputs"]["ne_actual"] == 20


def test_missing_verified_snapshot_is_unknown(monkeypatch):
	monkeypatch.setattr(intelligence, "frappe", _Frappe())

	result = intelligence.calculate_school_potential("HS-1")

	assert result["value"] == "Unknown"
	assert result["reason"] == "verified_snapshot_required"


def test_invalid_school_outcome_input_is_unknown_not_zero_filled(monkeypatch):
	monkeypatch.setattr(intelligence, "frappe", _Frappe(snapshots=[{
		"name": "SNAP-INVALID", "revision": 1, "snapshot_date": "2026-08-30",
		"ne_actual": None, "adjusted_ne_threshold": 0,
	}]))

	result = intelligence.calculate_school_potential("HS-1")

	assert result["value"] == "Unknown"
	assert result["reason"] == "school_outcome_input_incomplete"


def test_relationship_uses_stakeholder_association_not_person(monkeypatch):
	monkeypatch.setattr(intelligence, "frappe", _Frappe(stakeholders=[
		{"name": "ST-1", "relationship_status": "Active", "modified": "2026-08-30"},
	]))

	result = intelligence.derive_school_relationship("HS-1")

	assert result["value"] == "Active"
	assert result["evidence"][0]["source_class"] == "observation"


def test_do_not_contact_relationship_takes_precedence(monkeypatch):
	monkeypatch.setattr(intelligence, "frappe", _Frappe(stakeholders=[
		{"name": "ST-1", "relationship_status": "Active", "modified": "2026-08-30"},
		{"name": "ST-2", "relationship_status": "Do Not Contact", "modified": "2026-08-29"},
	]))

	assert intelligence.derive_school_relationship("HS-1")["value"] == "Do Not Contact"


def test_segment_is_four_quadrant_and_unknown_is_fail_closed():
	potential = {"value": "High", "source_data_revision": "p", "as_of": "2026-08-30", "freshness": "as_of", "evidence": []}
	relationship = {"value": "Dormant", "source_data_revision": "r", "as_of": "2026-08-30", "freshness": "live", "evidence": []}

	assert intelligence.derive_school_segment(potential, relationship)["value"] == "High Potential / Developing"
	assert intelligence.derive_school_segment({"value": "Unknown"}, relationship)["value"] == "Unknown"
	assert intelligence.derive_school_segment({"value": "Medium"}, relationship)["value"] == "Unknown"


def test_relationship_transition_is_idempotent_and_evidence_backed(monkeypatch):
	class _DB:
		def __init__(self):
			self.locks = []

		def sql(self, query, params):
			self.locks.append((query, params))

		def exists(self, _doctype, _filters):
			return False

		def get_value(self, *_args, **_kwargs):
			return "ACTIVITY-1"

	class _Doc:
		name = "ST-1"
		high_school = "HS-1"
		owner_staff = "STAFF-1"
		owning_team = "TEAM-A"
		values = {"relationship_status": "New", "relationship_revision": 1, "relationship_last_idempotency_key": None}

		def get(self, key, default=None):
			return self.values.get(key, default)

		def save(self, **_kwargs):
			return self

	class _Activity:
		def insert(self, **_kwargs):
			return self

	class _Frappe:
		PermissionError = PermissionError
		session = types.SimpleNamespace(user="owner@example.com")
		flags = types.SimpleNamespace()

		def __init__(self):
			self.db = _DB()
			self.doc = _Doc()
			self.docs = 0

		def get_doc(self, *args):
			if isinstance(args[0], dict):
				return _Activity()
			self.docs += 1
			return self.doc

		def has_permission(self, *_args, **_kwargs):
			return True

	fake = _Frappe()
	monkeypatch.setattr(intelligence, "frappe", fake)
	first = intelligence.transition_school_relationship("ST-1", "Active", "key-1", "evidence-1")
	assert first["status"] == "applied"
	assert first["revision"] == 2
	fake.doc.values["relationship_last_idempotency_key"] = "key-1"
	second = intelligence.transition_school_relationship("ST-1", "Active", "key-1", "evidence-1")
	assert second["status"] == "duplicate"
	assert "for update" in fake.db.locks[0][0]
