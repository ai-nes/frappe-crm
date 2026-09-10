from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import admission_profile_templates


class TestAdmissionProfileTemplates(FrappeTestCase):
	def test_catalog_exposes_only_supported_admission_methods(self):
		method_rows = [
			frappe._dict(
				name="COMBINED",
				code="COMBINED",
				display_name="Xét tuyển kết hợp",
				description=None,
				sort_order=10,
				enabled=1,
			),
			frappe._dict(
				name="THPT_SCORE",
				code="THPT_SCORE",
				display_name="Xét điểm thi tốt nghiệp THPT",
				description=None,
				sort_order=40,
				enabled=1,
			),
			frappe._dict(
				name="NATIONAL_HIGH_SCHOOL_EXAM",
				code="NATIONAL_HIGH_SCHOOL_EXAM",
				display_name="Điểm thi tốt nghiệp THPT",
				description=None,
				sort_order=40,
				enabled=1,
			),
			frappe._dict(
				name="DIRECT_ADMISSION",
				code="DIRECT_ADMISSION",
				display_name="Tuyển thẳng",
				description=None,
				sort_order=50,
				enabled=1,
			),
		]

		def fake_get_list(doctype, **kwargs):
			if doctype == "CRM Admission Method":
				return method_rows
			return []

		with patch.object(admission_profile_templates.frappe, "get_list", side_effect=fake_get_list):
			result = admission_profile_templates.get_admission_profile_catalog()

		self.assertEqual(
			[(method["code"], method["name"]) for method in result["methods"]],
			[
				("THPT_SCORE", "Xét điểm thi tốt nghiệp THPT"),
				("DIRECT_ADMISSION", "Tuyển thẳng"),
			],
		)
