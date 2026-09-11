from io import BytesIO
from unittest.mock import patch
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import student_documents


class UploadedFile:
	def __init__(self, filename: str, content: bytes):
		self.filename = filename
		self.stream = BytesIO(content)


class UploadRequest:
	def __init__(self, filename: str, content: bytes):
		self.files = {"file": UploadedFile(filename, content)}


class TestStudentDocuments(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._cleanup = []

	def tearDown(self):
		for doctype, name in reversed(self._cleanup):
			if not frappe.db.exists(doctype, name):
				continue
			if doctype == "CRM Student Document":
				frappe.db.delete(doctype, {"name": name})
			else:
				frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)

	def _student_and_year(self):
		school = frappe.db.get_value("CRM High School", {}, ["name", "province", "ward"], as_dict=True)
		year = frappe.db.get_value("CRM Admission Year", {}, "name")
		self.assertTrue(school and year)
		student = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"full_name": f"_Test Student Document {uuid4().hex[:8]}",
				"phone": f"098{uuid4().int % 10_000_000:07d}",
				"email": f"student-document-{uuid4().hex[:8]}@example.com",
				"date_of_birth": "2008-01-01",
				"gender": "Nam",
				"province": school.province,
				"ward": school.ward,
				"high_school": school.name,
				"admission_year": year,
				"student_stage": "New",
			}
		).insert(ignore_permissions=True)
		self._cleanup.append(("CRM Student", student.name))
		return student, year

	def _profile(self, student, year):
		document_type = frappe.db.get_value(
			"CRM Document Type", {"code": "ENROLLMENT_FORM", "status": "Active"}, "name"
		)
		self.assertTrue(document_type)
		template = frappe.get_doc(
			{
				"doctype": "CRM Admission Profile Template",
				"template_code": f"TEST-UPLOAD-{uuid4().hex[:8].upper()}",
				"template_name": "_Test Student Document Upload",
				"profile_type": "academic_admission",
				"status": "Active",
				"version": 1,
				"document_types": [
					{
						"doctype": "CRM Profile Template Document Type",
						"document_type": document_type,
						"requirement_group": "basic_admission",
						"requirement_mode": "ALL",
						"is_required": 1,
						"order_display": 1,
					}
				],
			}
		).insert(ignore_permissions=True)
		self._cleanup.append(("CRM Admission Profile Template", template.name))
		profile = frappe.get_doc(
			{
				"doctype": "CRM Student Admission Profile",
				"student": student.name,
				"profile_template": template.name,
				"admission_year": year,
				"attempt_number": 1,
				"profile_status": "Active",
			}
		).insert(ignore_permissions=True)
		self._cleanup.append(("CRM Student Admission Profile", profile.name))
		return profile, document_type

	def test_upload_creates_private_document_and_increments_version(self):
		student, year = self._student_and_year()
		profile, document_type = self._profile(student, year)

		with patch.object(
			student_documents.frappe,
			"request",
			UploadRequest("enrollment-form.txt", b"first-file"),
		):
			first = student_documents.upload_document(student.name, profile.name, document_type)

		first_document = frappe.get_doc("CRM Student Document", first["document"]["id"])
		self._cleanup.extend([("CRM Student Document", first_document.name), ("File", first["file"]["id"])])
		self.assertEqual(first_document.version, 1)
		self.assertEqual(first_document.status, "Uploaded")
		self.assertEqual(first_document.is_private, 1)
		self.assertEqual(first["documentCompleteness"]["completed"], 1)

		with patch.object(
			student_documents.frappe,
			"request",
			UploadRequest("enrollment-form-v2.txt", b"second-file"),
		):
			second = student_documents.upload_document(student.name, profile.name, document_type)

		second_document = frappe.get_doc("CRM Student Document", second["document"]["id"])
		self._cleanup.extend([("CRM Student Document", second_document.name), ("File", second["file"]["id"])])
		self.assertEqual(second_document.version, 2)
		self.assertEqual(
			frappe.db.count("CRM Student Document", {"student_admission_profile": profile.name}),
			2,
		)
