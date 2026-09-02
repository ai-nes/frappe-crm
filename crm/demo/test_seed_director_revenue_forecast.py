from frappe.tests.utils import FrappeTestCase

from crm.demo import seed_director_revenue_forecast


class TestSeedDirectorRevenueForecast(FrappeTestCase):
	def test_fixture_amounts_are_deterministic_and_increasing(self):
		self.assertEqual(
			seed_director_revenue_forecast.sample_amounts(3), [300_000_000, 325_000_000, 350_000_000]
		)
