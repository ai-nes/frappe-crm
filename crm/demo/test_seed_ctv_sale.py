"""Offline contract tests for the local CTV Sale fixture."""

from __future__ import annotations

import unittest

from crm.demo import seed_ctv_sale


class TestSeedCtvSaleData(unittest.TestCase):
	def test_account_uses_the_documented_canonical_sale_role(self):
		self.assertEqual(seed_ctv_sale.ACCOUNT_EMAIL, "ctvsale@gmail.com")
		self.assertEqual(seed_ctv_sale.ACCOUNT_ROLE, "CTV Sale")
		self.assertEqual(seed_ctv_sale.ACCOUNT_FULL_NAME, "CTV Sale")
		self.assertEqual(seed_ctv_sale.TEAM_MEMBERSHIP_FUNCTION, "CTV Sale")

	def test_fixture_contains_three_unique_students(self):
		self.assertEqual(len(seed_ctv_sale.STUDENT_SCENARIOS), 3)
		for scenario in seed_ctv_sale.STUDENT_SCENARIOS:
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
			len({row["key"] for row in seed_ctv_sale.STUDENT_SCENARIOS}),
			3,
		)
		self.assertEqual(
			len({row["email"] for row in seed_ctv_sale.STUDENT_SCENARIOS}),
			3,
		)
		self.assertTrue(
			all(row["email"].endswith("@example.test") for row in seed_ctv_sale.STUDENT_SCENARIOS)
		)


if __name__ == "__main__":
	unittest.main()
