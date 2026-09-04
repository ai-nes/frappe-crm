"""Offline contract tests for the local Sale fixture."""

from __future__ import annotations

import unittest

from crm.demo import seed_sale


class TestSeedSaleData(unittest.TestCase):
	def test_account_uses_the_sale_role(self):
		self.assertEqual(seed_sale.ACCOUNT_EMAIL, "sale@gmail.com")
		self.assertEqual(seed_sale.ACCOUNT_ROLE, "Sale")
		self.assertEqual(seed_sale.TEAM_MEMBERSHIP_FUNCTION, "Sale")
		self.assertEqual(seed_sale.PASSWORD, "123456")

	def test_fixture_contains_three_unique_students(self):
		self.assertEqual(len(seed_sale.STUDENT_SCENARIOS), 3)
		for scenario in seed_sale.STUDENT_SCENARIOS:
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
			len({row["key"] for row in seed_sale.STUDENT_SCENARIOS}),
			3,
		)
		self.assertEqual(
			len({row["email"] for row in seed_sale.STUDENT_SCENARIOS}),
			3,
		)
		self.assertTrue(all(row["email"].endswith("@example.test") for row in seed_sale.STUDENT_SCENARIOS))


if __name__ == "__main__":
	unittest.main()
