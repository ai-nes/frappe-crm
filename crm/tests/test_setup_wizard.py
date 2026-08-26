import frappe
from frappe.tests.utils import FrappeTestCase

from crm.install import complete_setup


class TestSetupWizardCompletion(FrappeTestCase):
	def test_completion_hook_does_not_seed_demo_data(self):
		self.assertEqual(frappe.get_hooks("setup_wizard_complete"), ["crm.install.complete_setup"])
		self.assertIsNone(complete_setup())
