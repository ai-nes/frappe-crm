"""Regression checks that production readers use the conversion resolver."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
READER_FILES = (
	"fcrm/student_attribution.py",
	"fcrm/interaction_log.py",
	"fcrm/student_engagement.py",
	"fcrm/attribution.py",
	"fcrm/student_context.py",
	"api/student_dashboard.py",
	"api/admissions_dashboard.py",
	"api/segment.py",
	"fcrm/doctype/crm_marketing_engagement/crm_marketing_engagement.py",
)


class TestStudentContactConversionReaderInventory(unittest.TestCase):
	def test_readers_do_not_query_legacy_contact_student_directly(self):
		for relative in READER_FILES:
			text = (ROOT / relative).read_text(encoding="utf-8")
			self.assertNotIn('get_value("CRM Student", {"student":', text, relative)
			self.assertNotIn('get_all("CRM Student", filters={"student":', text, relative)

	def test_resolver_is_the_only_legacy_fallback_boundary(self):
		resolver = (ROOT / "fcrm/student_contact_conversion.py").read_text(encoding="utf-8")
		self.assertIn('get_value("CRM Student", {"student": lead or student}', resolver)
		self.assertIn('get_value("CRM Student", contact, "student")', resolver)

	def test_conversion_service_keeps_contact_reads_behind_scope_checks(self):
		conversion = (ROOT / "fcrm/student_conversion.py").read_text(encoding="utf-8")
		self.assertIn("has_student_permission", conversion)
		self.assertIn("OUT_OF_SCOPE", conversion)
		self.assertIn("expected_lifecycle_revision", conversion)
