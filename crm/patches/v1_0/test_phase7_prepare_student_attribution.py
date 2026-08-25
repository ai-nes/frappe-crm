import unittest

from crm.patches.v1_0.phase7_prepare_student_attribution import build_backfill_report, classify_evidence_row


class TestPhase7PrepareStudentAttribution(unittest.TestCase):
	def test_backfill_only_uses_existing_contact_student_link(self):
		rows = [
			{"doctype": "CRM Campaign Touchpoint", "name": "CTP-1", "crm_contact": "CONTACT-1", "student": None},
			{"doctype": "CRM Event Participation", "name": "EVT-1", "crm_contact": None, "student": None},
		]
		report = build_backfill_report(rows, {"CONTACT-1": "STUDENT-1"})
		self.assertEqual(report["backfillable"], 1)
		self.assertEqual(report["quarantined"], 1)
		self.assertEqual(report["items"][0]["resolved_student"], "STUDENT-1")

	def test_existing_student_is_never_overwritten_and_mismatch_is_quarantined(self):
		self.assertEqual(
			classify_evidence_row({"student": "STUDENT-1", "crm_contact": "CONTACT-1"}, {"CONTACT-1": "STUDENT-2"}),
			"conflict",
		)
		self.assertEqual(
			classify_evidence_row({"student": "STUDENT-1", "crm_contact": "CONTACT-1"}, {"CONTACT-1": "STUDENT-1"}),
			"preserved",
		)
