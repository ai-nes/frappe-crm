"""Runtime coverage for Student admission profiles and payment accounts."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase


class TestStudentProfileAdmissionRuntime(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._cleanup = []

	def tearDown(self):
		for doctype, name in reversed(self._cleanup):
			if frappe.db.exists(doctype, name):
				if doctype == "CRM Student Document":
					frappe.db.delete(doctype, {"name": name})
				else:
					frappe.delete_doc(doctype, name, force=True)

	def _student(self, *, complete=True):
		school = frappe.db.get_value(
			"CRM High School",
			{},
			["name", "province", "ward"],
			as_dict=True,
		)
		year = frappe.db.get_value("CRM Admission Year", {}, "name")
		self.assertTrue(school and year)
		values = {
			"doctype": "CRM Student",
			"full_name": f"_Test Admission Profile {frappe.generate_hash(length=8)}",
			"phone": f"098{frappe.db.count('CRM Student') % 10_000_000:07d}",
			"student_stage": "New",
		}
		if complete:
			values.update(
				{
					"date_of_birth": "2008-01-01",
					"gender": "Nam",
					"email": f"profile-{frappe.generate_hash(length=8)}@example.com",
					"province": school.province,
					"ward": school.ward,
					"high_school": school.name,
					"admission_year": year,
				}
			)
		student = frappe.get_doc(values).insert(ignore_permissions=True)
		self._cleanup.append(("CRM Student", student.name))
		return student, year

	def _template(self, document_type="PERSONAL_ID"):
		document_type = frappe.db.get_value("CRM Document Type", {"code": document_type}, "name")
		self.assertTrue(document_type)
		template = frappe.get_doc(
			{
				"doctype": "CRM Admission Profile Template",
				"template_code": f"TEST-{frappe.generate_hash(length=8)}",
				"template_name": "_Test Admission Profile Template",
				"profile_type": "academic_admission",
				"status": "Active",
				"version": 1,
				"document_types": [
					{
						"doctype": "CRM Profile Template Document Type",
						"document_type": document_type,
						"is_required": 1,
						"order_display": 1,
					}
				],
			}
		).insert(ignore_permissions=True)
		self._cleanup.append(("CRM Admission Profile Template", template.name))
		return template

	def _profile(self, student, year, template, **values):
		profile = frappe.get_doc(
			{
				"doctype": "CRM Student Admission Profile",
				"student": student.name,
				"profile_template": template.name,
				"admission_year": year,
				"attempt_number": 1,
				"profile_status": "Active",
				**values,
			}
		).insert(ignore_permissions=True)
		self._cleanup.append(("CRM Student Admission Profile", profile.name))
		return profile

	def test_active_profile_requires_complete_canonical_student(self):
		student, year = self._student(complete=False)
		template = self._template()
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "CRM Student Admission Profile",
					"student": student.name,
					"profile_template": template.name,
					"admission_year": year,
					"attempt_number": 1,
					"profile_status": "Active",
				}
			).insert(ignore_permissions=True)

	def test_active_profile_projects_document_completeness(self):
		student, year = self._student()
		template = self._template()
		profile = self._profile(student, year, template)
		profile.reload()
		self.assertEqual(
			frappe.parse_json(profile.document_completeness),
			{
				"total": 1,
				"completed": 0,
				"missing": [template.document_types[0].document_type],
				"groups": [
					{
						"group": f"document:{template.document_types[0].document_type}",
						"section_code": "general",
						"mode": "ALL",
						"total": 1,
						"completed": 0,
						"missing": [template.document_types[0].document_type],
						"document_types": [template.document_types[0].document_type],
						"instruction": "",
					}
				],
			},
		)

	def test_any_requirement_is_completed_by_one_alternative(self):
		student, year = self._student()
		personal_id = frappe.db.get_value("CRM Document Type", {"code": "PERSONAL_ID"}, "name")
		birth_certificate = frappe.db.get_value("CRM Document Type", {"code": "BIRTH_CERTIFICATE"}, "name")
		self.assertTrue(personal_id and birth_certificate)
		template = frappe.get_doc(
			{
				"doctype": "CRM Admission Profile Template",
				"template_code": f"TEST-ANY-{frappe.generate_hash(length=8)}",
				"template_name": "_Test Any Admission Profile Template",
				"profile_type": "academic_admission",
				"status": "Active",
				"version": 1,
				"document_types": [
					{
						"doctype": "CRM Profile Template Document Type",
						"section_code": "identity",
						"requirement_group": "identity_proof",
						"requirement_mode": "ANY",
						"document_type": personal_id,
						"is_required": 1,
						"min_required": 1,
						"quantity": 1,
						"order_display": 1,
					},
					{
						"doctype": "CRM Profile Template Document Type",
						"section_code": "identity",
						"requirement_group": "identity_proof",
						"requirement_mode": "ANY",
						"document_type": birth_certificate,
						"is_required": 1,
						"min_required": 1,
						"quantity": 1,
						"order_display": 2,
					},
				],
			}
		).insert(ignore_permissions=True)
		self._cleanup.append(("CRM Admission Profile Template", template.name))
		profile = self._profile(student, year, template)
		profile.reload()
		initial = frappe.parse_json(profile.document_completeness)
		self.assertEqual(initial["total"], 1)
		self.assertEqual(initial["completed"], 0)
		self.assertEqual(initial["missing"], ["identity_proof"])

		document = frappe.get_doc(
			{
				"doctype": "CRM Student Document",
				"student": student.name,
				"student_admission_profile": profile.name,
				"document_type": birth_certificate,
				"file": "/private/files/_test-birth-certificate.pdf",
				"status": "Uploaded",
				"version": 1,
			}
		).insert(ignore_permissions=True)
		self._cleanup.append(("CRM Student Document", document.name))
		profile.reload()
		completed = frappe.parse_json(profile.document_completeness)
		self.assertEqual(completed["total"], 1)
		self.assertEqual(completed["completed"], 1)
		self.assertEqual(completed["missing"], [])
		self.assertEqual(completed["groups"][0]["mode"], "ANY")

		rejected = frappe.get_doc(
			{
				"doctype": "CRM Student Document",
				"student": student.name,
				"student_admission_profile": profile.name,
				"document_type": birth_certificate,
				"file": "/private/files/_test-birth-certificate-v2.pdf",
				"status": "Rejected",
				"version": 2,
				"rejection_reason": "Unreadable copy",
			}
		).insert(ignore_permissions=True)
		self._cleanup.append(("CRM Student Document", rejected.name))
		profile.reload()
		rejected_completeness = frappe.parse_json(profile.document_completeness)
		self.assertEqual(rejected_completeness["completed"], 0)
		self.assertEqual(rejected_completeness["missing"], ["identity_proof"])

	def test_false_condition_excludes_document_requirement(self):
		student, year = self._student()
		document_type = frappe.db.get_value("CRM Document Type", {"code": "SCHOLARSHIP_PROOF"}, "name")
		self.assertTrue(document_type)
		template = frappe.get_doc(
			{
				"doctype": "CRM Admission Profile Template",
				"template_code": f"TEST-CONDITION-{frappe.generate_hash(length=8)}",
				"template_name": "_Test Conditional Admission Profile Template",
				"profile_type": "academic_admission",
				"status": "Active",
				"version": 1,
				"document_types": [
					{
						"doctype": "CRM Profile Template Document Type",
						"document_type": document_type,
						"condition_key": "field:profile.is_first_generation=true",
						"is_required": 1,
						"order_display": 1,
					}
				],
			}
		).insert(ignore_permissions=True)
		self._cleanup.append(("CRM Admission Profile Template", template.name))
		profile = self._profile(student, year, template, is_first_generation=0)
		profile.reload()
		self.assertEqual(
			frappe.parse_json(profile.document_completeness),
			{"total": 0, "completed": 0, "missing": [], "groups": []},
		)

	def test_payment_account_primary_is_unique_per_purpose(self):
		student, _ = self._student(complete=False)
		values = {
			"doctype": "CRM Student Payment Account",
			"student": student.name,
			"bank_name": "Test Bank",
			"account_number": f"9704{frappe.db.count('CRM Student Payment Account') + 1:08d}",
			"account_holder_name": "Test Student",
			"account_purpose": "Tuition",
			"is_primary": 1,
		}
		first = frappe.get_doc(values).insert(ignore_permissions=True)
		self._cleanup.append(("CRM Student Payment Account", first.name))
		with self.assertRaises(frappe.DuplicateEntryError):
			frappe.get_doc({**values, "account_number": "970400000001"}).insert(ignore_permissions=True)
