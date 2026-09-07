"""Contract tests for the Lead processing and Student contact-stage commands."""

import json
import unittest
from pathlib import Path

try:
	import frappe
except ImportError:  # pragma: no cover - exercised by the no-bench CI lane
	frappe = None

if frappe is not None:
	from frappe.tests.utils import FrappeTestCase


@unittest.skipIf(frappe is None, "Lead/Student workflow tests require a Frappe bench")
class TestLeadStudentProcessingContract(unittest.TestCase):
	def test_processing_resolutions_are_exactly_the_six_business_outcomes(self):
		from crm.fcrm.lead_processing import RESOLUTIONS

		self.assertEqual(
			set(RESOLUTIONS) - {"PENDING"},
			{"MATCHED", "CREATED", "DUPLICATE", "INVALID", "SPAM", "FAILED"},
		)

	def test_identifier_gate_requires_cccd_high_school_and_major(self):
		from crm.fcrm.lead_processing import LeadProcessingError, _normalise_identifiers

		valid = {
			"id_number": " 012345678901 ",
			"high_school": " THPT A ",
			"major": " Công nghệ thông tin ",
			"email": " Student@Example.com ",
			"phone": "+84981000001",
			"province": " Ho Chi Minh ",
		}
		self.assertEqual(
			_normalise_identifiers(valid),
			{
				"id_number": "012345678901",
				"high_school": "thpt a",
				"major": "công nghệ thông tin",
				"email": "student@example.com",
				"phone": "0981000001",
				"province": "ho chi minh",
			},
		)

		invalid = {"id_number": "", "high_school": None, "major": None}
		with self.assertRaises(LeadProcessingError) as ctx:
			_normalise_identifiers(invalid)
		self.assertEqual(ctx.exception.code, "IDENTIFIER_GATE_FAILED")

	def test_student_contact_stage_edges_are_forward_only(self):
		from crm.fcrm.student_stage import StudentStageError, validate_transition

		for current, target in (
			("New", "Attempting"),
			("Attempting", "Connected"),
			("Connected", "Qualified"),
			("Connected", "Disqualified"),
		):
			self.assertEqual(validate_transition(current, target), (current, target))

		for current, target in (("Qualified", "Connected"), ("Disqualified", "New"), ("New", "Connected")):
			with self.assertRaises(StudentStageError) as ctx:
				validate_transition(current, target)
			self.assertEqual(ctx.exception.code, "INVALID_TRANSITION")

	def test_schema_contains_server_managed_workflow_fields(self):
		root = Path(__file__).resolve().parents[1]
		lead_schema = json.loads((root / "fcrm/doctype/crm_lead/crm_lead.json").read_text(encoding="utf-8"))
		student_schema = json.loads(
			(root / "fcrm/doctype/crm_student/crm_student.json").read_text(encoding="utf-8")
		)
		lead_fields = {field["fieldname"]: field for field in lead_schema["fields"]}
		student_fields = {field["fieldname"]: field for field in student_schema["fields"]}

		self.assertEqual(lead_fields["processing_status"]["default"], "NEW")
		self.assertTrue(lead_fields["processing_status"]["read_only"])
		self.assertIn("PROCESSING", lead_fields["processing_status"]["options"])
		self.assertEqual(lead_fields["matched_student"]["options"], "CRM Student")
		self.assertIn("MATCHED", lead_fields["resolution"]["options"])
		self.assertEqual(student_fields["student_stage"]["default"], "New")
		self.assertTrue(student_fields["student_stage"]["read_only"])


@unittest.skipIf(frappe is None, "Lead/Student workflow tests require a Frappe bench")
class TestLeadStudentProcessingRuntime(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		for name in frappe.db.get_all(
			"CRM Lead", filters={"student_name": ["like", "_Test Processing %"]}, pluck="name"
		):
			frappe.delete_doc("CRM Lead", name, force=True)
		for name in frappe.db.get_all(
			"CRM Student", filters={"full_name": ["like", "_Test Processing %"]}, pluck="name"
		):
			frappe.delete_doc("CRM Student", name, force=True)

	def _new_lead(self, suffix: str, **values):
		payload = {
			"doctype": "CRM Lead",
			"student_name": f"_Test Processing {suffix}",
			"phone": f"0981000{len(suffix):03d}",
			"email": f"processing-{suffix.lower()}@example.com",
			"enrollment_status": "NEW",
			**values,
		}
		return frappe.get_doc(payload).insert(ignore_permissions=True)

	def test_identifier_gate_closes_invalid_lead(self):
		from crm.fcrm.lead_processing import process_lead

		lead = self._new_lead("Invalid")
		result = process_lead(lead.name)

		self.assertEqual(result["status"], "CLOSED")
		self.assertEqual(result["resolution"], "INVALID")
		self.assertFalse(result["validation"]["id_number"])
		self.assertEqual(frappe.db.get_value("CRM Lead", lead.name, "processing_status"), "CLOSED")

	def test_valid_gate_classifies_new_student_path(self):
		from crm.fcrm.lead_processing import process_lead

		province = frappe.db.get_value("CRM Province", {}, "name")
		high_school = frappe.db.get_value("CRM High School", {}, "name")
		major = frappe.db.get_value("CRM Major", {}, "name")
		self.assertTrue(province)
		self.assertTrue(high_school)
		self.assertTrue(major)
		lead = self._new_lead(
			"Created", province=province, id_number="012345678901", high_school=high_school, major=major
		)
		result = process_lead(lead.name)

		self.assertEqual(result["status"], "PROCESSED")
		self.assertEqual(result["resolution"], "CREATED")
		self.assertEqual(frappe.db.get_value("CRM Lead", lead.name, "resolution"), "CREATED")
		self.assertEqual(frappe.db.get_value("CRM Lead", lead.name, "processing_status"), "PROCESSED")

	def test_student_stage_command_advances_one_edge(self):
		from crm.fcrm.student_stage import set_student_stage

		student = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"full_name": "_Test Processing Stage",
				"phone": "0902222333",
			}
		).insert(ignore_permissions=True)
		result = set_student_stage(student.name, "Attempting")

		self.assertEqual(result["student_stage"], "Attempting")
		self.assertEqual(frappe.db.get_value("CRM Student", student.name, "student_stage"), "Attempting")

	def test_workflow_fields_reject_direct_document_edits(self):
		lead = self._new_lead("Guard")
		lead.processing_status = "CLOSED"
		lead.resolution = "MATCHED"
		with self.assertRaises(frappe.PermissionError):
			lead.save(ignore_permissions=True)

		student = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"full_name": "_Test Processing Guard Student",
				"phone": "0902222444",
			}
		).insert(ignore_permissions=True)
		student.student_stage = "Attempting"
		with self.assertRaises(frappe.PermissionError):
			student.save(ignore_permissions=True)

	def test_new_lead_cannot_inject_processing_status(self):
		lead = self._new_lead("ServerDefaults", processing_status="ASSIGNED", resolution="CREATED")

		self.assertEqual(lead.processing_status, "NEW")
		self.assertEqual(lead.resolution, "PENDING")
