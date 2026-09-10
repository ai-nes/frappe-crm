import unittest

from crm.operations_reconcile_account_roles import ROLE_BY_EMAIL


class TestOperationsReconcileAccountRoles(unittest.TestCase):
	def test_local_lead_sale_account_keeps_lead_sale_role(self):
		self.assertEqual(ROLE_BY_EMAIL["leadsale@gmail.com"], "Lead Sale")
