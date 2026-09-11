from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import admission_profile_templates


class TestAdmissionProfileTemplates(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self._cleanup = []

		document_type = frappe.get_doc(
			{
				"doctype": "CRM Document Type",
				"code": f"TEST_ADMIN_DOC_{frappe.generate_hash(length=8).upper()}",
				"label": "Test admin document",
				"category": "identity",
				"status": "Active",
				"is_active": 1,
			}
		).insert(ignore_permissions=True)
		self.document_type = document_type
		self._cleanup.append((document_type.doctype, document_type.name))

	def tearDown(self):
		for doctype, name in reversed(self._cleanup):
			if frappe.db.exists(doctype, name):
				frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
		super().tearDown()

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

	def test_catalog_search_filters_document_type_options(self):
		document_rows = [
			frappe._dict(
				name="DOC-ACHIEVEMENT",
				code="ACHIEVEMENT",
				label="Bản sao thành tích",
				category="special",
				description=None,
				status="Active",
				is_active=1,
			),
			frappe._dict(
				name="DOC-CITIZEN-ID",
				code="CITIZEN_ID",
				label="Căn cước công dân",
				category="identity",
				description=None,
				status="Active",
				is_active=1,
			),
		]
		document_queries = []

		def fake_get_list(doctype, **kwargs):
			return []

		def fake_get_all(doctype, **kwargs):
			if doctype != "CRM Document Type":
				return []
			document_queries.append(kwargs)
			return document_rows if not kwargs.get("or_filters") else [document_rows[0]]

		with (
			patch.object(admission_profile_templates.frappe, "get_list", side_effect=fake_get_list),
			patch.object(admission_profile_templates.frappe, "get_all", side_effect=fake_get_all),
		):
			result = admission_profile_templates.get_admission_profile_catalog(search="achievement")

		self.assertEqual([document["code"] for document in result["documentTypes"]], ["ACHIEVEMENT"])
		self.assertEqual(
			document_queries[1]["or_filters"],
			[
				["name", "like", "%achievement%"],
				["code", "like", "%achievement%"],
				["label", "like", "%achievement%"],
				["category", "like", "%achievement%"],
			],
		)

	def test_admin_can_create_update_transition_and_delete_templates(self):
		template_code = f"TEST_ADMIN_{frappe.generate_hash(length=8).upper()}"
		data = {
			"template_code": template_code,
			"template_name": "Test admin template",
			"profile_type": "academic_admission",
			"status": "Draft",
			"version": 1,
			"description": "Created through the admin API",
			"requirements": [
				{
					"section_code": "basic_admission",
					"document_type": self.document_type.name,
					"requirement_group": "BASIC_ADMISSION",
					"requirement_mode": "ALL",
					"is_required": True,
					"min_required": 1,
					"quantity": 1,
					"order_display": 1,
					"instruction": "Submit one certified copy.",
				}
			],
		}

		created = admission_profile_templates.create_admission_profile_template(data)
		self._cleanup.append(("CRM Admission Profile Template", created["id"]))
		self.assertEqual(created["code"], template_code)
		self.assertEqual(created["requirements"][0]["documentType"], self.document_type.name)

		with self.assertRaises(frappe.ValidationError):
			admission_profile_templates.update_admission_profile_template(
				created["id"],
				{**data, "template_kind": "special"},
				expected_modified=created["modified"],
			)

		data["template_name"] = "Updated admin template"
		data["description"] = "Updated through the admin API"
		updated = admission_profile_templates.update_admission_profile_template(
			created["id"], data, expected_modified=created["modified"]
		)
		self.assertEqual(updated["name"], "Updated admin template")

		active = admission_profile_templates.transition_admission_profile_template(
			created["id"], "Active", expected_modified=updated["modified"]
		)
		self.assertEqual(active["status"], "Active")
		archived = admission_profile_templates.transition_admission_profile_template(
			created["id"], "Archived", expected_modified=active["modified"]
		)
		self.assertEqual(archived["status"], "Archived")

		draft = admission_profile_templates.create_admission_profile_template(
			{
				"template_code": f"TEST_DELETE_{frappe.generate_hash(length=8).upper()}",
				"template_name": "Draft to delete",
				"profile_type": "academic_admission",
				"status": "Draft",
				"version": 1,
				"requirements": [],
			}
		)
		self._cleanup.append(("CRM Admission Profile Template", draft["id"]))
		result = admission_profile_templates.delete_admission_profile_template(
			draft["id"], expected_modified=draft["modified"]
		)
		self.assertTrue(result["deleted"])
		self._cleanup.remove(("CRM Admission Profile Template", draft["id"]))

	def test_delete_guard_checks_special_profile_selections(self):
		template = frappe._dict(name="SPECIAL-TEST", template_code="SPECIAL_TEST")

		def fake_exists(doctype, filters):
			return doctype == "CRM Admission Application Special Profile"

		with patch.object(admission_profile_templates.frappe.db, "exists", side_effect=fake_exists):
			with self.assertRaises(frappe.ValidationError):
				admission_profile_templates._assert_template_not_in_use(template)
