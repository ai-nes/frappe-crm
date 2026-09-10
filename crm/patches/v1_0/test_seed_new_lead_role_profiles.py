import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.role_policy import CANONICAL_PERMISSION_MATRIX
from crm.patches.v1_0.seed_new_lead_role_profiles import (
	_NEW_ROLE_PERMISSIONS,
	CTV_SALE_DIRECTOR_READ_DOCTYPES,
	execute,
)


class TestSeedNewLeadRoleProfiles(FrappeTestCase):
	def setUp(self):
		execute()

	def tearDown(self):
		frappe.db.rollback()

	def _profile(self, role):
		name = frappe.db.get_value("CRM Permission Profile", {"role": role}, "name")
		self.assertTrue(name, f"expected a seeded CRM Permission Profile for role {role!r}")
		return frappe.get_doc("CRM Permission Profile", name)

	def test_new_roles_are_created(self):
		for role in ("CTV Sale", "Promoter", "Lead Promoter", "Lead Marketing", "Administrator"):
			self.assertTrue(frappe.db.exists("Role", role), f"expected Role {role!r} to exist")

	def test_new_profiles_match_prd_crud_matrix(self):
		doctypes = CANONICAL_PERMISSION_MATRIX["admissions_case"]["doctypes"]
		roles = {
			"ctv_sale": "CTV Sale",
			"pr": "Promoter",
			"pr_manager": "Lead Promoter",
			"lead_marketing": "Lead Marketing",
			"ceo": "Administrator",
		}
		for profile_key, role in roles.items():
			flags = _NEW_ROLE_PERMISSIONS[profile_key]
			profile = self._profile(role)
			self.assertEqual(profile.row_scope, flags["row_scope"])
			self.assertEqual(profile.delete_requires_ownership, 1)
			self.assertEqual(profile.is_system_managed, 1)
			seeded = {row.document_type: row for row in profile.applicable_doctypes}
			extra_doctypes = set(CTV_SALE_DIRECTOR_READ_DOCTYPES) if profile_key == "ctv_sale" else set()
			self.assertEqual(set(seeded), set(doctypes) | extra_doctypes)
			for doctype, row in seeded.items():
				if doctype in extra_doctypes:
					self.assertTrue(row.read)
					self.assertFalse(row.write)
					self.assertFalse(row.create)
					self.assertFalse(row.delete)
					self.assertFalse(row.export)
					continue
				self.assertEqual(bool(row.read), bool(flags["read"]))
				self.assertEqual(bool(row.write), bool(flags["write"]))
				self.assertEqual(bool(row.create), bool(flags["create"]))
				self.assertEqual(bool(row.delete), bool(flags["delete"]))

	def test_lead_sales_and_marketing_updated_by_the_same_deploy(self):
		doctypes = CANONICAL_PERMISSION_MATRIX["admissions_case"]["doctypes"]

		lead_sales = self._profile("Lead Sale")
		lead_sales_flags = {row.document_type: row for row in lead_sales.applicable_doctypes}
		for doctype in doctypes:
			self.assertTrue(lead_sales_flags[doctype].delete)

		marketing = self._profile("Marketing")
		self.assertEqual(marketing.row_scope, "campus_assigned")
		marketing_flags = {row.document_type: row for row in marketing.applicable_doctypes}
		for doctype in doctypes:
			row = marketing_flags[doctype]
			self.assertTrue(row.read)
			self.assertFalse(row.write)
			self.assertFalse(row.create)
			self.assertFalse(row.delete)

	def test_seed_is_idempotent(self):
		execute()
		execute()
		profile = self._profile("Administrator")
		doctypes = [row.document_type for row in profile.applicable_doctypes]
		self.assertEqual(len(doctypes), len(set(doctypes)))
