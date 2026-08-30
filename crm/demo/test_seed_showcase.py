"""Offline contract tests for the curated CRM demo seed.

These exercise only the pure, data-shaped parts of ``seed_showcase`` -- the
scenario / contact tables, the coverage matrix and the deterministic key
builders. They never touch a site or database and run under plain ``pytest``.
"""

from __future__ import annotations

import unittest

from crm.demo import seed_showcase
from crm.demo.seed_showcase import (
	BULK_CONTACT_ROWS,
	BULK_SCENARIOS,
	CONTACT_ROWS,
	COVERAGE_MATRIX,
	KNOWN_GAPS,
	NAMESPACE,
	SCENARIOS,
	_ACTIVITY_STATUS,
	_ADMISSION_METHODS,
	_CONSENT_EVENTS,
	_KEY_ACCOUNT_SLOTS,
	_PERSON_INF,
	_PERSON_REL,
	_READINESS_LABELS,
	_SCHOOL_AREAS,
	_SHOWCASE_KEY_ACCOUNT_COUNT,
	TARGET_SHOWCASE_CONTACTS,
	TARGET_SHOWCASE_STUDENTS,
	_idempotency_key,
	_rng,
	_showcase_key_account_schools,
)

_SERVICE_SLA_TARGETS = {
	"open", "warned", "breached", "escalated", "paused", "responded", "superseded",
}
_ACTION_STATE_TARGETS = {"accepted", "in-progress", "completed", "cancelled", "requires-review"}


class TestSeedShowcaseData(unittest.TestCase):
	def test_namespace_is_stable(self):
		self.assertEqual(NAMESPACE, "crm-demo-showcase")

	def test_scenarios_use_synthetic_contact_data_only(self):
		for scenario in SCENARIOS:
			self.assertTrue(scenario["email"].endswith("@example.test"), scenario["key"])
			self.assertTrue(scenario["phone"].startswith("090"), scenario["key"])
			self.assertIn(scenario["gender"], {"Nam", "Nữ"})
			self.assertIn(scenario["admission_method"], _ADMISSION_METHODS)

	def test_scenario_keys_are_unique(self):
		keys = [scenario["key"] for scenario in SCENARIOS]
		self.assertEqual(len(keys), len(set(keys)))

	def test_contact_rows_are_synthetic_and_unique(self):
		keys = [row["key"] for row in CONTACT_ROWS]
		self.assertEqual(len(keys), len(set(keys)))
		for row in CONTACT_ROWS:
			self.assertIn(row["consent"], _CONSENT_EVENTS)

	def test_volume_is_curated_not_bulk(self):
		self.assertEqual(len(SCENARIOS) + 5, TARGET_SHOWCASE_STUDENTS)
		self.assertEqual(len(CONTACT_ROWS) + len(BULK_CONTACT_ROWS), TARGET_SHOWCASE_CONTACTS)

	def test_bulk_contacts_have_stable_student_counterparts(self):
		self.assertEqual(
			[row["student_key"] for row in BULK_CONTACT_ROWS],
			[scenario["key"] for scenario in BULK_SCENARIOS[:len(BULK_CONTACT_ROWS)]],
		)
		self.assertEqual(
			[row["full_name"] for row in BULK_CONTACT_ROWS],
			[scenario["student_name"] for scenario in BULK_SCENARIOS[:len(BULK_CONTACT_ROWS)]],
		)

	def test_declared_sla_targets_are_reachable_by_a_service_path(self):
		for scenario in SCENARIOS:
			target = scenario.get("sla_target")
			if target is not None:
				self.assertIn(target, _SERVICE_SLA_TARGETS, scenario["key"])

	def test_declared_action_targets_are_reachable_by_a_service_path(self):
		for scenario in SCENARIOS:
			for action_type, target_state in scenario.get("action_specs", ()):  # noqa: B007
				self.assertIn(target_state, _ACTION_STATE_TARGETS, scenario["key"])

	def test_only_enrolled_scenarios_request_conversion(self):
		for scenario in SCENARIOS:
			if scenario.get("convert"):
				self.assertEqual(scenario["target_stage"], "Enrolled", scenario["key"])

	def test_lifecycle_stage_targets_cover_every_stage(self):
		targets = {scenario["target_stage"] for scenario in SCENARIOS}
		self.assertEqual(targets, {"Lead", "MQL", "Applicant", "Enrolled", "Lost"})


class TestCoverageMatrixConsistency(unittest.TestCase):
	def test_matrix_entries_are_non_empty_string_lists(self):
		for doctype, fields in COVERAGE_MATRIX.items():
			self.assertIsInstance(fields, dict, doctype)
			for field, values in fields.items():
				self.assertTrue(values, f"{doctype}.{field}")
				self.assertEqual(len(values), len(set(values)), f"{doctype}.{field}")
				for value in values:
					self.assertIsInstance(value, str)

	def test_student_admission_methods_match_the_shared_tuple(self):
		self.assertEqual(
			set(COVERAGE_MATRIX["CRM Student"]["admission_method"]), set(_ADMISSION_METHODS)
		)

	def test_curated_data_targets_every_reachable_student_lifecycle_value(self):
		expected = set(COVERAGE_MATRIX["CRM Student"]["lifecycle_stage"])
		self.assertTrue({s["target_stage"] for s in SCENARIOS}.issuperset(expected))

	def test_contact_rows_cover_every_lead_status_in_the_matrix(self):
		matrix = set(COVERAGE_MATRIX["CRM Contact"]["lead_status"])
		seeded = {row["lead_status"] for row in CONTACT_ROWS}
		self.assertTrue(matrix.issubset(seeded), matrix - seeded)

	def test_contact_rows_cover_readiness_quality_channel_and_decision_maker(self):
		for field in ("readiness_level", "quality_bucket", "decision_maker", "preferred_contact_channel"):
			matrix = set(COVERAGE_MATRIX["CRM Contact"][field])
			seeded = {row[field] for row in CONTACT_ROWS}
			if field == "readiness_level":
				# CONTACT_ROWS carry the short key; the seed expands it to the
				# full bilingual Select label before insert.
				seeded = {_READINESS_LABELS[value] for value in seeded}
			self.assertTrue(matrix.issubset(seeded), f"{field}: {matrix - seeded}")

	def test_consent_events_cover_every_matrix_event_type(self):
		matrix = set(COVERAGE_MATRIX["CRM Contact Consent Event"]["event_type"])
		self.assertEqual(matrix, set(_CONSENT_EVENTS))
		seeded = {row["consent"] for row in CONTACT_ROWS}
		self.assertEqual(seeded, matrix)

	def test_sla_attempt_matrix_lists_all_nine_states(self):
		self.assertEqual(len(COVERAGE_MATRIX["CRM Student SLA Attempt"]["status"]), 9)

	def test_known_gaps_are_documented_strings(self):
		self.assertTrue(all(isinstance(gap, str) and gap for gap in KNOWN_GAPS))


class TestKeyAccountSlots(unittest.TestCase):
	def test_slots_cover_every_school_matrix_value(self):
		areas = {area for area, _, _ in _KEY_ACCOUNT_SLOTS}
		tiers = {tier for _, tier, _ in _KEY_ACCOUNT_SLOTS if tier}
		self.assertEqual(areas, set(_SCHOOL_AREAS))
		self.assertEqual(tiers, set(COVERAGE_MATRIX["CRM High School"]["key_account_tier"]))
		self.assertEqual(_SHOWCASE_KEY_ACCOUNT_COUNT, len(_KEY_ACCOUNT_SLOTS))

	def test_slots_reach_every_key_account_status(self):
		modes = {mode for _, _, mode in _KEY_ACCOUNT_SLOTS}
		# eligible_* -> "Eligible", no_snapshot -> "Review Required",
		# below_threshold -> "Not Eligible"
		self.assertTrue(any(m.startswith("eligible") for m in modes))
		self.assertIn("no_snapshot", modes)
		self.assertIn("below_threshold", modes)

	def test_person_and_activity_vocab_fits_the_slot_count(self):
		self.assertGreaterEqual(len(_PERSON_REL), 4)
		self.assertGreaterEqual(len(_PERSON_INF), 4)
		self.assertEqual(len(_ACTIVITY_STATUS), 3)


class TestKeyAccountSchoolSelection(unittest.TestCase):
	def _patch(self, activity_schools, snapshot_schools):
		def fake_get_all(doctype, **kwargs):
			if doctype == "CRM School Activity":
				return list(activity_schools)
			if doctype == "CRM High School Annual Snapshot":
				return list(snapshot_schools)
			return []
		return fake_get_all

	def test_selection_is_stable_once_curated(self):
		curated = [f"school-{i}" for i in range(_SHOWCASE_KEY_ACCOUNT_COUNT)]
		original = seed_showcase.frappe.get_all
		seed_showcase.frappe.get_all = self._patch(curated, ["other-a", "other-b"])
		try:
			first = _showcase_key_account_schools(_ImportShim())
		finally:
			seed_showcase.frappe.get_all = original
		self.assertEqual(first, sorted(curated))

	def test_empty_slots_fill_from_snapshot_candidates(self):
		original = seed_showcase.frappe.get_all
		seed_showcase.frappe.get_all = self._patch(
			["school-2"], ["school-9", "school-2", "school-1", "school-7", "school-4", "school-6"]
		)
		try:
			out = _showcase_key_account_schools(_ImportShim())
		finally:
			seed_showcase.frappe.get_all = original
		self.assertEqual(len(out), _SHOWCASE_KEY_ACCOUNT_COUNT)
		self.assertIn("school-2", out)
		self.assertEqual(len(set(out)), len(out))


class _ImportShim:
	PRIMARY_TS_SHEET = "Địa bàn TĐ THPT 2026"


class TestDeterminism(unittest.TestCase):
	def test_idempotency_key_is_stable_and_namespaced(self):
		self.assertEqual(_idempotency_key("intake", "thao-an"), f"{NAMESPACE}:intake:thao-an")
		self.assertEqual(
			_idempotency_key("a", 1, "b"), _idempotency_key("a", 1, "b")
		)

	def test_rng_is_seeded_and_reproducible(self):
		first = [_rng("score", "gia-han").randint(0, 1_000) for _ in range(5)]
		second = [_rng("score", "gia-han").randint(0, 1_000) for _ in range(5)]
		self.assertEqual(first, second)
		self.assertNotEqual(
			_rng("score", "gia-han").random(), _rng("score", "minh-khang").random()
		)


if __name__ == "__main__":
	unittest.main()
