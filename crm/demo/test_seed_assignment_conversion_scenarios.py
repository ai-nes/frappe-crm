from unittest import TestCase

from crm.demo import seed_team_management
from crm.demo.seed_assignment_conversion_scenarios import (
	DUPLICATE_PHONE,
	SCENARIOS,
	UNMANAGED_PROVINCE,
	_canonical_province_name,
	_intake_namespace,
	_team_by_province,
)


class TestSeedAssignmentConversionScenarios(TestCase):
	def test_fixture_contains_twenty_five_uniquely_identified_leads(self):
		self.assertEqual(len(SCENARIOS), 25)
		self.assertEqual(len({row["phone"] for row in SCENARIOS}), 25)
		# Intake must accept every Lead, so the seeded phone numbers stay unique;
		# the duplicate is only created afterwards by a phone mutation.
		for row in SCENARIOS:
			self.assertTrue(row["province"])
			self.assertTrue(row["school"])
			self.assertTrue(row["major"])
			self.assertNotIn("id", row)

	def test_twenty_one_leads_are_assignable_and_thirteen_carry_one_defect(self):
		happy = [row for row in SCENARIOS if "defect" not in row or row["defect"]["expected"] == "assigned"]
		defects = [row for row in SCENARIOS if "defect" in row]
		self.assertEqual(len(happy), 21)
		self.assertEqual(len(defects), 13)
		self.assertEqual(
			{row["defect"]["code"] for row in defects},
			{
				"MISSING_MAJOR_OPTIONAL",
				"INVALID_MISSING_HIGH_SCHOOL",
				"INVALID_MISSING_PHONE",
				"MISSING_PROVINCE",
				"MISSING_CAMPUS",
				"TEAM_NOT_FOUND_FOR_PROVINCE",
				"DUPLICATE_PRIMARY",
				"DUPLICATE_RESUBMIT",
				"NO_ELIGIBLE_RECIPIENT_FALLBACK",
				"OPTIONAL_FIELDS_MISSING",
				"PHONE_FORMAT_NORMALIZED",
				"PROVINCE_ALIAS_RESOLVED",
			},
		)
		for row in defects:
			self.assertIn(row["defect"]["expected"], {"manual_review", "assigned"})
			self.assertTrue(row["defect"]["note"])

	def test_fallback_case_is_seeded_twice_for_a_bulk_run(self):
		fallback_rows = [
			row for row in SCENARIOS if row.get("defect", {}).get("code") == "NO_ELIGIBLE_RECIPIENT_FALLBACK"
		]
		self.assertEqual(len(fallback_rows), 2)
		self.assertTrue(all(row["province"] == "Bình Dương" for row in fallback_rows))

	def test_duplicate_pair_collapses_onto_one_lead_phone(self):
		"""The resubmission is closed by the previously processed Lead phone."""
		primary = next(row for row in SCENARIOS if row.get("defect", {}).get("code") == "DUPLICATE_PRIMARY")
		resubmit = next(row for row in SCENARIOS if row.get("defect", {}).get("code") == "DUPLICATE_RESUBMIT")
		self.assertEqual(primary["phone"], DUPLICATE_PHONE)
		self.assertEqual(primary["defect"]["fields"], {})
		self.assertEqual(resubmit["defect"]["fields"], {"phone": DUPLICATE_PHONE})
		self.assertNotIn("id_number", primary)
		self.assertNotIn("id_number", resubmit)

	def test_every_scenario_province_has_a_seeded_team(self):
		"""Intake needs an active Team pool per province, or no Lead can be created.

		A scenario may spell its province as an everyday alias (e.g. "TP Hồ Chí
		Minh") on purpose, so membership is checked on the resolved docname, the
		same way ``execute()`` looks the pool up.
		"""
		teams = {_canonical_province_name(province): team for province, team in _team_by_province().items()}
		self.assertEqual(
			set(teams),
			{
				_canonical_province_name(fixture["province"])
				for fixture in seed_team_management.GROUP_FIXTURES
			},
		)
		for row in SCENARIOS:
			self.assertIn(_canonical_province_name(row["province"]), teams)

	def test_each_fixture_run_uses_a_distinct_intake_namespace(self):
		first = _intake_namespace("first-run")
		second = _intake_namespace("second-run")

		self.assertNotEqual(first, second)
		self.assertTrue(first.startswith("local-assignment-conversion-20260908:run:"))

	def test_the_unmanaged_province_defect_targets_a_province_without_a_team(self):
		"""The routing defect only fires while no seeded Team covers that province."""
		self.assertNotIn(UNMANAGED_PROVINCE, _team_by_province())
