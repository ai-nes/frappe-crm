"""Cross-command contract inventory for admissions progression.

These assertions intentionally keep the append-only handoff explicit: an
outcome is lifecycle evidence, but it is not by itself a verified SLA reply.
"""

from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]


class TestLeadProcessingProgressionIntegrationInventory(TestCase):
	def test_progression_commands_keep_independent_revision_fences(self):
		lifecycle = (ROOT / "fcrm/student_lifecycle.py").read_text(encoding="utf-8")
		engagement = (ROOT / "fcrm/student_engagement.py").read_text(encoding="utf-8")
		conversion = (ROOT / "fcrm/student_conversion.py").read_text(encoding="utf-8")
		self.assertIn('"lifecycle_revision"', lifecycle)
		self.assertIn('"engagement_revision"', engagement)
		self.assertIn("expected_lifecycle_revision", conversion)

	def test_outcome_and_sla_are_not_the_same_mutation_path(self):
		engagement = (ROOT / "fcrm/student_engagement.py").read_text(encoding="utf-8")
		sla = (ROOT / "fcrm/student_sla.py").read_text(encoding="utf-8")
		self.assertIn("CRM Student Outcome", engagement)
		self.assertIn("qualifying", sla.lower())
		self.assertNotIn("close_sla", engagement)
