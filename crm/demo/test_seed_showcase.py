"""Offline contract tests for the curated CRM demo seed.

These exercise only the pure, data-shaped parts of ``seed_showcase`` -- the
scenario / contact tables, the coverage matrix and the deterministic key
builders. They never touch a site or database and run under plain ``pytest``.
"""

from __future__ import annotations

import unittest

from crm.demo import seed_showcase
from crm.demo.seed_showcase import (
	_ACTIVITY_STATUS,
	_ADMISSION_METHODS,
	_CONSENT_EVENTS,
	_FEATURED_SCHOOLS_PER_PROVINCE,
	_KEY_ACCOUNT_SLOTS,
	_PERSON_INF,
	_PERSON_REL,
	_READINESS_LABELS,
	_SCHOOL_AREAS,
	_SHOWCASE_CAMPAIGN_TITLES,
	_SHOWCASE_CAMPAIGNS,
	_SHOWCASE_KEY_ACCOUNT_COUNT,
	_SHOWCASE_LEAD_CAMPAIGN_ASSIGNMENTS,
	BULK_CONTACT_ROWS,
	BULK_SCENARIOS,
	CONTACT_ROWS,
	COVERAGE_MATRIX,
	KNOWN_GAPS,
	NAMESPACE,
	SCENARIOS,
	TARGET_SHOWCASE_CONTACTS,
	TARGET_SHOWCASE_STUDENTS,
	_dashboard_spotlight_school_rows,
	_featured_school_rows,
	_idempotency_key,
	_rng,
	_showcase_key_account_schools,
)

_SERVICE_SLA_TARGETS = {
	"open", "warned", "breached", "escalated", "paused", "responded", "superseded",
}
_ACTION_STATE_TARGETS = {"accepted", "in-progress", "completed", "cancelled", "requires-review"}


class TestSeedShowcaseData(unittest.TestCase):
	def test_market_snapshot_values_create_two_non_key_accounts_per_three_schools(self):
		values = [
			seed_showcase._market_snapshot_key_account_values(index, threshold=15, ne_actual=30)
			for index in range(6)
		]

		self.assertEqual(values, [(15, 30), (31, 30), (31, 30), (15, 30), (31, 30), (31, 30)])

	def test_market_snapshot_school_count_stays_bounded(self):
		self.assertEqual(seed_showcase._MARKET_SNAPSHOT_SCHOOL_COUNT, 35)

	def test_namespace_is_stable(self):
		self.assertEqual(NAMESPACE, "crm-demo-showcase")

	def test_scenarios_use_synthetic_contact_data_only(self):
		names = [scenario["student_name"] for scenario in SCENARIOS]
		emails = [scenario["email"] for scenario in SCENARIOS]
		self.assertEqual(len(names), len(set(names)))
		self.assertEqual(len(emails), len(set(emails)))
		for scenario in SCENARIOS:
			self.assertRegex(scenario["email"], r"^[a-z0-9]+(?:\.[a-z0-9]+)*@[a-z0-9.-]+\.[a-z]{2,}$")
			self.assertNotIn("showcase", scenario["email"])
			self.assertNotIn("example.test", scenario["email"])
			self.assertNotIn("Học sinh showcase", scenario["student_name"])
			self.assertNotIn("Edge", scenario["student_name"])
			self.assertTrue(scenario["phone"].startswith("090"), scenario["key"])
			self.assertIn(scenario["gender"], {"Nam", "Nữ"})
			self.assertIn(scenario["admission_method"], _ADMISSION_METHODS)

	def test_scenario_keys_are_unique(self):
		keys = [scenario["key"] for scenario in SCENARIOS]
		self.assertEqual(len(keys), len(set(keys)))

	def test_seed_campaign_assignments_target_known_curated_leads(self):
		keys = {scenario["key"] for scenario in SCENARIOS}
		self.assertEqual(
			set(_SHOWCASE_LEAD_CAMPAIGN_ASSIGNMENTS),
			{"thao-an", "gia-han", "minh-khang"},
		)
		self.assertTrue(set(_SHOWCASE_LEAD_CAMPAIGN_ASSIGNMENTS).issubset(keys))
		self.assertTrue(
			set(_SHOWCASE_LEAD_CAMPAIGN_ASSIGNMENTS.values()).issubset(_SHOWCASE_CAMPAIGN_TITLES)
		)

	def test_seed_campaign_statuses_match_current_doctype_contract(self):
		self.assertEqual(
			{status for _, status, _ in _SHOWCASE_CAMPAIGNS},
			{"DRAFT", "UPCOMING", "ACTIVE", "CLOSED"},
		)

	def test_seed_campaign_links_are_written_to_leads_idempotently(self):
		students = [
			{"key": student_key, "student": f"lead-{student_key}"}
			for student_key in ("thao-an", "minh-khang")
		]
		campaigns = {
			title: f"campaign-{index}"
			for index, title in enumerate(_SHOWCASE_CAMPAIGN_TITLES, start=1)
		}
		seed_source_leads = {"crm-demo-showcase:gia-han": "lead-gia-han"}
		lead_campaigns = {}
		writes = []
		original_get_value = seed_showcase.frappe.db.get_value
		original_set_value = seed_showcase.frappe.db.set_value

		def fake_get_value(doctype, filters, fieldname, **kwargs):
			if doctype == "CRM Campaign":
				return campaigns[filters["title"]]
			if doctype == "CRM Lead":
				if isinstance(filters, dict) and "import_source_id" in filters:
					name = seed_source_leads.get(filters["import_source_id"])
					if kwargs.get("as_dict"):
						return (
							{
								"name": name,
								"student_name": "Võ Gia Hân",
								"email": "vo.gia.han@gmail.com",
							}
							if name
							else None
						)
					return name
				return lead_campaigns.get(filters)
			raise AssertionError(f"Unexpected lookup: {doctype} {filters} {fieldname}")

		def fake_set_value(doctype, name, fieldname, value, **kwargs):
			self.assertEqual(doctype, "CRM Lead")
			self.assertEqual(fieldname, "campaign")
			self.assertFalse(kwargs["update_modified"])
			lead_campaigns[name] = value
			writes.append((name, value))

		seed_showcase.frappe.db.get_value = fake_get_value
		seed_showcase.frappe.db.set_value = fake_set_value
		try:
			first = seed_showcase._link_seed_leads_to_campaigns(
				students, {"campaigns": list(campaigns.values())}
			)
			second = seed_showcase._link_seed_leads_to_campaigns(
				students, {"campaigns": list(campaigns.values())}
			)
		finally:
			seed_showcase.frappe.db.get_value = original_get_value
			seed_showcase.frappe.db.set_value = original_set_value

		self.assertEqual(first, second)
		self.assertEqual(len(writes), len(_SHOWCASE_LEAD_CAMPAIGN_ASSIGNMENTS))
		self.assertEqual(
			{value for _, value in writes},
			{campaigns[title] for title in _SHOWCASE_LEAD_CAMPAIGN_ASSIGNMENTS.values()},
		)

	def test_contact_rows_have_natural_display_identity(self):
		keys = [row["key"] for row in CONTACT_ROWS]
		self.assertEqual(len(keys), len(set(keys)))
		emails = [seed_showcase._contact_email(row) for row in CONTACT_ROWS + BULK_CONTACT_ROWS]
		self.assertEqual(len(emails), len(set(emails)))
		for row in CONTACT_ROWS + BULK_CONTACT_ROWS:
			self.assertNotIn("showcase", row["full_name"])
			self.assertNotIn("Học sinh showcase", row["full_name"])
			self.assertRegex(seed_showcase._contact_email(row), r"^[a-z0-9]+(?:\.[a-z0-9]+)*@[a-z0-9.-]+\.[a-z]{2,}$")
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
			set(COVERAGE_MATRIX["CRM Lead"]["admission_method"]), set(_ADMISSION_METHODS)
		)

	def test_curated_data_targets_every_reachable_student_lifecycle_value(self):
		expected = set(COVERAGE_MATRIX["CRM Lead"]["lifecycle_stage"])
		self.assertTrue({s["target_stage"] for s in SCENARIOS}.issuperset(expected))

	def test_contact_rows_cover_readiness_quality_channel_and_decision_maker(self):
		for field in ("readiness_level", "quality_bucket", "decision_maker", "preferred_contact_channel"):
			matrix = set(COVERAGE_MATRIX["CRM Student"][field])
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
	def test_dashboard_spotlight_follows_the_detail_fixture_order(self):
		rows = [
			{"name": f"school-{code}", "province": "Khánh Hoà", "school_code": code}
			for code in ("17", "15", "28", "20", "22", "16")
		]

		spotlight = _dashboard_spotlight_school_rows(rows)

		self.assertEqual([row["school_code"] for row in spotlight], ["15", "20", "22", "28", "16", "17"])

	def test_featured_school_slice_is_stable_and_skips_unknown_province(self):
		rows = [
			{"name": f"a-{index}", "province": "A Province", "school_code": f"{index:03d}"}
			for index in range(1, _FEATURED_SCHOOLS_PER_PROVINCE + 2)
		] + [
			{"name": f"b-{index}", "province": "B Province", "school_code": f"{index:03d}"}
			for index in range(1, _FEATURED_SCHOOLS_PER_PROVINCE + 1)
		] + [{"name": "unknown", "province": None, "school_code": "001"}]

		featured = _featured_school_rows(rows)

		self.assertEqual(len(featured), _FEATURED_SCHOOLS_PER_PROVINCE * 2)
		self.assertEqual(featured[0]["name"], "a-1")
		self.assertNotIn("unknown", {row["name"] for row in featured})

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
