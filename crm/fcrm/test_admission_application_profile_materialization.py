"""Integration coverage for application-to-profile materialization."""

from __future__ import annotations

import uuid

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.admission_application import create_application, update_application
from crm.fcrm.admission_offering import approve_offering


class TestAdmissionApplicationProfileMaterialization(FrappeTestCase):
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

	def _catalog(self):
		year = frappe.db.get_value("CRM Admission Year", {}, "name")
		campus = frappe.db.get_value("CRM Campus", {}, "name")
		major = frappe.db.get_value("CRM Major", {}, "name")
		school = frappe.db.get_value("CRM High School", {}, ["name", "province", "ward"], as_dict=True)
		document_type = frappe.db.get_value("CRM Document Type", {"status": "Active", "is_active": 1}, "name")
		if not all((year, campus, major, school, document_type)):
			self.skipTest("Admission catalog fixtures are required")
		return year, campus, major, school, document_type

	def _create_method(self):
		method_code = "TRANSCRIPT_REVIEW_TEST"
		if frappe.db.exists("CRM Admission Method", method_code):
			return frappe.get_doc("CRM Admission Method", method_code)
		method = frappe.get_doc(
			{
				"doctype": "CRM Admission Method",
				"code": method_code,
				"display_name": "Test admission method",
			}
		).insert(ignore_permissions=True)
		self._cleanup.append(("CRM Admission Method", method.name))
		return method

	def test_application_creates_profile_and_template_checklist_idempotently(self):
		year, campus, major, school, document_type = self._catalog()
		method = self._create_method()
		student = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"full_name": f"_Test Application Profile {uuid.uuid4().hex[:8]}",
				"phone": f"098{uuid.uuid4().int % 10_000_000:07d}",
				"email": f"application-profile-{uuid.uuid4().hex[:8]}@example.com",
				"date_of_birth": "2008-01-01",
				"gender": "Nam",
				"province": school.province,
				"ward": school.ward,
				"high_school": school.name,
				"admission_year": year,
				"branch": campus,
				"major": major,
				"student_stage": "New",
			}
		).insert(ignore_permissions=True)
		self._cleanup.append(("CRM Student", student.name))

		template = frappe.get_doc(
			{
				"doctype": "CRM Admission Profile Template",
				"template_code": f"TEST-APP-{uuid.uuid4().hex[:8].upper()}",
				"template_name": "_Test application profile template",
				"profile_type": "academic_admission",
				"status": "Active",
				"version": 1,
				"admission_method": method.name,
				"document_types": [
					{
						"doctype": "CRM Profile Template Document Type",
						"section_code": "identity",
						"document_type": document_type,
						"requirement_group": "identity_proof",
						"requirement_mode": "ALL",
						"is_required": 1,
						"min_required": 1,
						"quantity": 1,
						"order_display": 1,
					}
				],
			}
		).insert(ignore_permissions=True)
		self._cleanup.append(("CRM Admission Profile Template", template.name))

		offering = frappe.get_doc(
			{
				"doctype": "CRM Admission Offering",
				"offering_key": f"TEST-APP-{uuid.uuid4().hex[:8].upper()}",
				"admission_year": year,
				"campus": campus,
				"major": major,
				"admission_method": method.name,
				"quota": 10,
				"effective_from": "2026-01-01",
				"effective_until": "2026-12-31",
				"status": "Draft",
				"policy_version": f"test-{uuid.uuid4().hex[:8]}",
			}
		).insert(ignore_permissions=True)
		self._cleanup.append(("CRM Admission Offering", offering.name))
		approve_offering(offering=offering.name, idempotency_key=f"test-{uuid.uuid4().hex}")

		result = create_application(
			student=student.name,
			values={
				"admission_method": method.name,
				"profile_template": template.template_code,
				"preference_order": 1,
				"preference": "Primary",
				"status": "Draft",
				"source_reference": f"test:application:{uuid.uuid4().hex}",
			},
			expected_revision=int(student.engagement_revision or 0),
			idempotency_key=f"test-application-{uuid.uuid4().hex}",
		)

		profile_name = result["admission_profile"]
		self._cleanup.append(("CRM Student Admission Profile", profile_name))
		self._cleanup.append(("CRM Admission Application", result["application"]))
		profile = frappe.get_doc("CRM Student Admission Profile", profile_name)
		self.assertEqual(profile.student, student.name)
		self.assertEqual(profile.profile_template, template.name)
		self.assertEqual(profile.application, result["application"])
		self.assertEqual(
			frappe.db.get_value("CRM Admission Application", result["application"], "offering"),
			offering.name,
		)
		self.assertEqual(
			frappe.db.get_value("CRM Admission Application", result["application"], "profile_template"),
			template.name,
		)
		self.assertEqual(result["profile_created"], True)
		self.assertEqual(frappe.db.get_value("CRM Student", student.name, "admission_method"), method.name)
		self.assertEqual(result["document_checklist"][0]["document_type"], document_type)
		self.assertEqual(result["document_checklist"][0]["order_display"], 1)
		self.assertEqual(result["document_completeness"]["total"], 1)
		self.assertEqual(result["document_completeness"]["completed"], 0)
		self.assertEqual(
			frappe.db.count("CRM Student Document", {"student_admission_profile": profile.name}),
			0,
		)

		updated_template = frappe.get_doc(
			{
				"doctype": "CRM Admission Profile Template",
				"template_code": f"TEST-APP-UPDATED-{uuid.uuid4().hex[:8].upper()}",
				"template_name": "_Test updated application profile template",
				"profile_type": "academic_admission",
				"status": "Active",
				"version": 1,
				"admission_method": method.name,
				"document_types": [
					{
						"doctype": "CRM Profile Template Document Type",
						"section_code": "updated",
						"document_type": document_type,
						"requirement_group": "updated_documents",
						"requirement_mode": "ALL",
						"is_required": 1,
						"min_required": 1,
						"quantity": 1,
						"order_display": 1,
					}
				],
			}
		).insert(ignore_permissions=True)
		self._cleanup.insert(0, ("CRM Admission Profile Template", updated_template.name))

		duplicate_application = frappe.get_doc(
			{
				"doctype": "CRM Admission Application",
				"student": student.name,
				"offering": offering.name,
				"profile_template": updated_template.name,
				"preference_order": 2,
				"preference": "Alternative",
				"status": "Draft",
				"source_reference": f"test:duplicate-application:{uuid.uuid4().hex}",
			}
		).insert(ignore_permissions=True)
		duplicate_profile_name = frappe.db.get_value(
			"CRM Student Admission Profile", {"application": duplicate_application.name}, "name"
		)
		self.assertTrue(duplicate_profile_name)
		self._cleanup.append(("CRM Student Admission Profile", duplicate_profile_name))
		self._cleanup.append(("CRM Admission Application", duplicate_application.name))

		updated = update_application(
			application=result["application"],
			values={
				"admission_method": method.name,
				"profile_template": updated_template.template_code,
				"preference": "Alternative",
			},
		)
		profile.reload()
		self.assertEqual(updated["application"], result["application"])
		self.assertEqual(updated["profile_created"], False)
		self.assertEqual(updated["profile_template"], updated_template.name)
		self.assertEqual(updated["admission_profile"], duplicate_profile_name)
		self.assertEqual(profile.profile_status, "Archived")
		self.assertEqual(
			frappe.db.get_value("CRM Student Admission Profile", duplicate_profile_name, "application"),
			result["application"],
		)
		self.assertEqual(
			frappe.db.get_value("CRM Admission Application", duplicate_application.name, "status"),
			"Withdrawn",
		)
		self.assertEqual(
			frappe.db.get_value("CRM Admission Application", result["application"], "profile_template"),
			updated_template.name,
		)
		self.assertEqual(
			frappe.db.get_value("CRM Admission Application", result["application"], "preference"),
			"Alternative",
		)
		self.assertEqual(updated["document_checklist"][0]["section_code"], "updated")

		replay = create_application(
			student=student.name,
			values={"offering": offering.name, "source_reference": profile.source_reference},
			expected_revision=0,
			idempotency_key=f"test-application-{uuid.uuid4().hex}",
		)
		self.assertEqual(replay["admission_profile"], duplicate_profile_name)
		self.assertEqual(replay["profile_created"], False)
		self.assertEqual(
			frappe.db.count("CRM Student Admission Profile", {"application": result["application"]}),
			1,
		)

		direct_application = frappe.get_doc(
			{
				"doctype": "CRM Admission Application",
				"student": student.name,
				"offering": offering.name,
				"preference_order": 2,
				"preference": "Alternative",
				"status": "Draft",
				"source_reference": f"test:direct-application:{uuid.uuid4().hex}",
			}
		).insert(ignore_permissions=True)
		direct_profile_name = frappe.db.get_value(
			"CRM Student Admission Profile", {"application": direct_application.name}, "name"
		)
		self.assertTrue(direct_profile_name)
		self._cleanup.append(("CRM Student Admission Profile", direct_profile_name))
		self._cleanup.append(("CRM Admission Application", direct_application.name))
