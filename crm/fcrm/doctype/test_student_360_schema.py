"""Pure schema contracts for the Student 360 stable-fact boundary."""

import json
import ast
from pathlib import Path
from unittest import TestCase


SCHEMA_PATH = Path(__file__).parent / "crm_student" / "crm_student.json"
CONTEXT_SERVICE_PATH = Path(__file__).parents[2] / "services" / "student_context.py"


class TestStudent360Schema(TestCase):
	def test_current_grade_is_nullable_and_controlled(self):
		with SCHEMA_PATH.open(encoding="utf-8") as schema_file:
			schema = json.load(schema_file)

		fields = {field["fieldname"]: field for field in schema["fields"]}
		current_grade = fields["current_grade"]

		self.assertEqual(current_grade["fieldtype"], "Select")
		self.assertEqual(current_grade["options"], "10\n11\n12\npost_exam")
		self.assertFalse(current_grade.get("reqd", 0))
		self.assertNotIn("default", current_grade)
		self.assertIn("current_grade", schema["field_order"])

	def test_study_stage_is_nullable_and_covers_pdf_phases(self):
		with SCHEMA_PATH.open(encoding="utf-8") as schema_file:
			schema = json.load(schema_file)
		fields = {field["fieldname"]: field for field in schema["fields"]}
		study_stage = fields["study_stage"]
		self.assertEqual(study_stage["fieldtype"], "Select")
		self.assertEqual(study_stage["options"], "grade_10\ngrade_11\ngrade_12_h1\ngrade_12_h2\npost_exam")
		self.assertFalse(study_stage.get("reqd", 0))
		self.assertNotIn("default", study_stage)

	def test_student_schema_has_read_only_assessment_projections(self):
		with SCHEMA_PATH.open(encoding="utf-8") as schema_file:
			schema = json.load(schema_file)

		fields = {field["fieldname"]: field for field in schema["fields"]}
		for fieldname in ("assessment_status", "assessment_revision", "interest_level", "fit_level", "primary_barrier", "privacy_status"):
			self.assertTrue(fields[fieldname]["read_only"])
		for fieldname in (
			"assessment_source", "assessment_reason", "assessment_evidence_references",
			"assessment_assessed_at", "assessment_confirmed_by", "assessment_confirmed_at",
			"privacy_consent_at", "privacy_retention_until",
		):
			self.assertNotIn(fieldname, fields)

	def test_assessment_doctype_is_versioned_and_explainable(self):
		assessment_path = SCHEMA_PATH.parent.parent / "crm_student_assessment" / "crm_student_assessment.json"
		with assessment_path.open(encoding="utf-8") as schema_file:
			schema = json.load(schema_file)
		fields = {field["fieldname"]: field for field in schema["fields"]}
		self.assertEqual(schema["name"], "CRM Student Assessment")
		for fieldname in ("assessment_revision", "assessment_source", "reason", "evidence_references", "confirmed_by", "confirmed_at"):
			self.assertIn(fieldname, fields)

	def test_geography_snapshot_is_append_only_and_dated(self):
		snapshot_path = SCHEMA_PATH.parent.parent / "crm_student_geography_snapshot" / "crm_student_geography_snapshot.json"
		with snapshot_path.open(encoding="utf-8") as schema_file:
			schema = json.load(schema_file)
		fields = {field["fieldname"]: field for field in schema["fields"]}
		self.assertEqual(schema["name"], "CRM Student Geography Snapshot")
		for fieldname in ("student", "captured_at", "province", "ward", "high_school", "change_reason"):
			self.assertIn(fieldname, fields)
			self.assertTrue(fields[fieldname].get("read_only"))

	def test_current_grade_invalidates_student_context(self):
		tree = ast.parse(CONTEXT_SERVICE_PATH.read_text(encoding="utf-8"))
		assignment = next(
			node
			for node in ast.walk(tree)
			if isinstance(node, ast.Assign)
			and any(isinstance(target, ast.Name) and target.id == "MATERIAL_STUDENT_FIELDS" for target in node.targets)
		)
		fields = set(ast.literal_eval(assignment.value.args[0]))
		self.assertIn("current_grade", fields)
		self.assertIn("study_stage", fields)
