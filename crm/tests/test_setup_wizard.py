import frappe
from frappe.tests.utils import FrappeTestCase

from crm.install import complete_setup, merge_cors_origins


class TestSetupWizardCompletion(FrappeTestCase):
	def test_completion_hook_does_not_seed_demo_data(self):
		self.assertEqual(frappe.get_hooks("setup_wizard_complete"), ["crm.install.complete_setup"])
		self.assertIsNone(complete_setup())
		self.assertIn("crm.install.after_migrate", frappe.get_hooks("after_migrate"))

	def test_merge_cors_origins_preserves_existing_values(self):
		required = ("https://app.chatwoot.com", "http://54.66.53.9:5173")

		self.assertEqual(
			merge_cors_origins("https://existing.example", required),
			"https://existing.example,https://app.chatwoot.com,http://54.66.53.9:5173",
		)
		self.assertEqual(
			merge_cors_origins(["https://existing.example"], required),
			["https://existing.example", "https://app.chatwoot.com", "http://54.66.53.9:5173"],
		)
		self.assertEqual(merge_cors_origins("*", required), "*")
