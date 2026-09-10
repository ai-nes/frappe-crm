"""Offline contract tests for the local Lead Sale fixture."""

from __future__ import annotations

import unittest

from crm.demo import seed_lead_sales


class TestSeedLeadSalesData(unittest.TestCase):
	def test_fixture_source_ids_are_namespaced_and_stable(self):
		self.assertEqual(
			seed_lead_sales._fixture_source_ids(),
			(
				"crm-demo-lead-sales:student-01",
				"crm-demo-lead-sales:student-02",
				"crm-demo-lead-sales:student-03",
			),
		)

	def test_account_uses_the_lead_sales_role(self):
		self.assertEqual(seed_lead_sales.ACCOUNT_EMAIL, "leadsale@gmail.com")
		self.assertEqual(seed_lead_sales.ACCOUNT_ROLE, "Lead Sale")
		self.assertEqual(seed_lead_sales.TEAM_MEMBERSHIP_FUNCTION, "Lead Sale")
		self.assertEqual(seed_lead_sales.PASSWORD, "123456")
		self.assertFalse(seed_lead_sales.SEED_SPEC.assign_students_to_account)
		self.assertTrue(seed_lead_sales.SEED_SPEC.is_team_lead)

	def test_fixture_contains_three_unique_students(self):
		self.assertEqual(len(seed_lead_sales.STUDENT_SCENARIOS), 3)
		for scenario in seed_lead_sales.STUDENT_SCENARIOS:
			self.assertTrue(
				{
					"date_of_birth",
					"id_number",
					"id_issued_date",
					"graduation_score",
					"transcript_score",
					"english_converted_score",
					"total_score",
					"notes",
					"parent",
				}
				<= scenario.keys()
			)
			self.assertEqual(set(scenario["parent"]), {"name", "phone", "address"})
		self.assertEqual(
			len({row["key"] for row in seed_lead_sales.STUDENT_SCENARIOS}),
			3,
		)
		self.assertEqual(
			len({row["email"] for row in seed_lead_sales.STUDENT_SCENARIOS}),
			3,
		)
		self.assertTrue(
			all(row["email"].endswith("@example.test") for row in seed_lead_sales.STUDENT_SCENARIOS)
		)


if __name__ == "__main__":
	unittest.main()
