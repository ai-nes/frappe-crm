from datetime import date

from frappe.tests.utils import FrappeTestCase

from crm.fcrm.doctype.crm_target.crm_target import CRMTarget


class TestCRMTarget(FrappeTestCase):
	def test_empty_legacy_scope_fields_do_not_conflict_with_document_scope_method(self):
		doc = CRMTarget(
			{
				"doctype": "CRM Target",
				"planning_scope": "province:P-1",
				"scope_type": "National",
				"scope": None,
				"period_start": date(2026, 1, 1),
				"period_end": date(2026, 12, 31),
				"target_value": 1,
				"status": "Draft",
			}
		)

		self.assertEqual(doc.get("scope_type"), "National")
		self.assertIsNone(doc.get("scope"))
		doc.validate()
