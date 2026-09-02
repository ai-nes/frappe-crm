from frappe.tests.utils import FrappeTestCase

from crm.demo import seed_director_regional_performance


class TestSeedDirectorRegionalPerformance(FrappeTestCase):
	def test_recommended_target_is_positive_and_above_current_enrollments(self):
		self.assertEqual(
			seed_director_regional_performance.recommended_target(applications=20, enrollments=8), 11
		)
		self.assertEqual(
			seed_director_regional_performance.recommended_target(applications=0, enrollments=0), 1
		)
		self.assertEqual(
			seed_director_regional_performance.recommended_target(applications=1, enrollments=12), 13
		)
