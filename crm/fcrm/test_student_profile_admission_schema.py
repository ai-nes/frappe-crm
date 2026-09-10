"""Contract tests for the Student profile/admission ERD."""

from __future__ import annotations

import json
from pathlib import Path

from frappe.tests.utils import FrappeTestCase

from crm.fcrm.student_profile import unique_owner_catalog

DOCTYPES_PATH = Path(__file__).resolve().parent / "doctype"


def _doctype(name: str) -> dict:
	path = DOCTYPES_PATH / name / f"{name}.json"
	return json.loads(path.read_text(encoding="utf-8"))


def _fields(schema: dict) -> dict[str, dict]:
	return {field["fieldname"]: field for field in schema.get("fields", []) if field.get("fieldname")}


class TestStudentProfileAdmissionSchema(FrappeTestCase):
	def test_erd_relationships_are_canonical(self):
		template = _fields(_doctype("crm_admission_profile_template"))
		profile = _fields(_doctype("crm_student_admission_profile"))
		junction = _fields(_doctype("crm_profile_template_document_type"))
		document = _fields(_doctype("crm_student_document"))

		self.assertEqual(template["document_types"]["fieldtype"], "Table")
		self.assertEqual(template["document_types"]["options"], "CRM Profile Template Document Type")
		self.assertEqual(junction["document_type"]["options"], "CRM Document Type")
		self.assertEqual(profile["student"]["options"], "CRM Student")
		self.assertEqual(profile["profile_template"]["options"], "CRM Admission Profile Template")
		self.assertEqual(document["student"]["options"], "CRM Student")
		self.assertEqual(document["student_admission_profile"]["options"], "CRM Student Admission Profile")
		self.assertEqual(document["document_type"]["options"], "CRM Document Type")
		application = _fields(_doctype("crm_admission_application"))
		self.assertNotIn("case_key", application)

	def test_template_junction_owns_requiredness_and_display_order(self):
		junction = _fields(_doctype("crm_profile_template_document_type"))

		self.assertEqual(junction["section_code"]["fieldtype"], "Data")
		self.assertEqual(junction["requirement_group"]["fieldtype"], "Data")
		self.assertEqual(junction["requirement_mode"]["options"], "ALL\nANY")
		self.assertEqual(junction["is_required"]["fieldtype"], "Check")
		self.assertEqual(junction["min_required"]["fieldtype"], "Int")
		self.assertEqual(junction["quantity"]["fieldtype"], "Int")
		self.assertEqual(junction["order_display"]["fieldtype"], "Int")
		self.assertEqual(junction["instruction"]["fieldtype"], "Small Text")
		self.assertEqual(junction["is_required"]["default"], "1")
		self.assertEqual(junction["min_required"]["default"], "1")
		self.assertEqual(junction["quantity"]["default"], "1")
		self.assertEqual(junction["order_display"]["default"], "1")

	def test_operational_student_links_do_not_target_lead(self):
		allowed_legacy_links = {
			("CRM Admission Application", "source_lead"),
			("CRM Lead Assignment Batch Item", "lead"),
			("CRM Student", "source_lead"),
			("CRM Student", "student"),
			("CRM Student Case Key", "canonical_student"),
			("CRM Student Case Key", "source_student"),
			("CRM Student Contact Conversion", "lead"),
			("CRM Student Contact Conversion", "student"),
			("CRM Student Intake Review", "candidate_student"),
		}
		violations = []
		for schema_path in DOCTYPES_PATH.rglob("*.json"):
			try:
				schema = json.loads(schema_path.read_text(encoding="utf-8"))
			except json.JSONDecodeError:
				continue
			if not isinstance(schema, dict):
				continue
			doctype = schema.get("name")
			for field in schema.get("fields", []):
				if (
					field.get("options") == "CRM Lead"
					and (doctype, field.get("fieldname")) not in allowed_legacy_links
				):
					violations.append((doctype, field.get("fieldname")))
		self.assertEqual(violations, [])

	def test_sensitive_bank_account_is_a_separate_doctype(self):
		student = _fields(_doctype("crm_student"))
		account = _fields(_doctype("crm_student_payment_account"))

		self.assertNotIn("bank_name", student)
		self.assertNotIn("account_number", student)
		self.assertNotIn("account_holder", student)
		self.assertEqual(account["student"]["options"], "CRM Student")
		self.assertEqual(account["account_number"]["permlevel"], 1)
		self.assertEqual(account["account_holder_name"]["permlevel"], 1)
		self.assertEqual(account["is_primary"]["fieldtype"], "Check")

	def test_field_owner_catalog_has_one_owner_per_field(self):
		catalog = unique_owner_catalog()
		self.assertEqual(len(catalog), len(set(catalog)))
		with self.assertRaises(ValueError):
			unique_owner_catalog(({"full_name": "CRM Student"}, {"full_name": "CRM Lead"}))
