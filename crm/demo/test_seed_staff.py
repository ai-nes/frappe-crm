from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from crm.demo import seed_staff


class TestSeedPhase2Staff(FrappeTestCase):
	def test_existing_named_fixture_department_is_reused(self):
		with patch.object(seed_staff.frappe.db, "exists", return_value=seed_staff.FIXTURE_DEPARTMENT_NAME), patch.object(
			seed_staff.frappe.db, "get_value", return_value="Demo Campus"
		):
			self.assertEqual(
				seed_staff._ensure_fixture_department("Demo Campus"), seed_staff.FIXTURE_DEPARTMENT_NAME
			)

	def test_fixture_accounts_are_named_reserved_identities(self):
		self.assertEqual(
			set(seed_staff.CANONICAL_FIXTURE_USERS),
			{
				"nguyen-minh-khoi.sale@example.test",
				"le-thanh-huong.leadsales@example.test",
				"pham-bao-chau.marketing@example.test",
				"tran-quoc-duy.director@example.test",
			},
		)
