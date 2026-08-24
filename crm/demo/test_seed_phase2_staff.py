from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from crm.demo import seed_phase2_staff


class TestSeedPhase2Staff(FrappeTestCase):
	def test_existing_named_fixture_department_is_reused(self):
		with patch.object(seed_phase2_staff.frappe.db, "exists", return_value="Demo Admissions"):
			self.assertEqual(seed_phase2_staff._ensure_fixture_department("Demo Campus"), "Demo Admissions")
