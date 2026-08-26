from frappe.tests.utils import FrappeTestCase

from crm.demo.seed_admissions_cohort import SCENARIOS


class TestSeedAdmissionsCohortDefinition(FrappeTestCase):
	def test_cohort_covers_the_current_lifecycle_with_two_sale_cases(self):
		self.assertEqual({scenario["target_stage"] for scenario in SCENARIOS}, {"Lead", "MQL", "Applicant", "Enrolled", "Lost"})
		self.assertEqual(sum(scenario["owner"] for scenario in SCENARIOS), 2)

	def test_sla_cases_are_the_two_supervisable_sale_cases(self):
		owned = {scenario["key"] for scenario in SCENARIOS if scenario["owner"]}
		self.assertEqual(owned, {"gia-han", "minh-khang"})
