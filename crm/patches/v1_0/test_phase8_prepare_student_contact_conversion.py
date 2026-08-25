import unittest

from crm.patches.v1_0.phase8_prepare_student_contact_conversion import build_report, classify_legacy_link


class TestPhase8PrepareStudentContactConversion(unittest.TestCase):
	def _row(self, **overrides):
		row = {
			"name": "CONT-1",
			"student": "STU-1",
			"student_record": {
				"identity": "ID-1",
				"case_key": "CASE-1",
				"identity_state": "resolved",
				"lifecycle_stage": "Enrolled",
			},
			"contact_record": {"student_identity": None},
		}
		row.update(overrides)
		return row

	def test_only_evidence_backed_enrolled_link_is_backfillable(self):
		row = self._row()
		self.assertEqual(
			classify_legacy_link(row, student=row["student_record"], contact=row["contact_record"]),
			"backfillable",
		)
		self.assertEqual(
			classify_legacy_link(
				row,
				student={**row["student_record"], "lifecycle_stage": "Applicant"},
				contact=row["contact_record"],
			),
			"not_enrolled",
		)

	def test_identity_and_case_conflicts_are_quarantined(self):
		row = self._row()
		self.assertEqual(
			classify_legacy_link(
				row,
				student=row["student_record"],
				contact={"student_identity": "ID-OTHER"},
			),
			"identity_conflict",
		)
		self.assertEqual(
			classify_legacy_link(
				row,
				student={"identity": None, "case_key": None, "identity_state": "resolved", "lifecycle_stage": "Enrolled"},
				contact=row["contact_record"],
			),
			"missing_identity_or_case_key",
		)

	def test_report_is_deterministic_and_redacted_to_stable_ids(self):
		report = build_report([self._row()])
		self.assertEqual(report["rows_checked"], 1)
		self.assertEqual(report["counts"], {"backfillable": 1})
		self.assertNotIn("student_record", report["items"][0])
		self.assertNotIn("contact_record", report["items"][0])

	def test_identity_collisions_are_quarantined_before_apply(self):
		rows = [
			self._row(name="CONT-1", student="STU-1"),
			self._row(name="CONT-2", student="STU-2", student_record={
				"identity": "ID-1",
				"case_key": "CASE-2",
				"identity_state": "active",
				"lifecycle_stage": "Enrolled",
			}),
		]
		report = build_report(rows)
		self.assertEqual(report["counts"], {"identity_conflict": 2})

	def test_active_identity_and_resolved_case_key_are_backfillable(self):
		row = self._row()
		row["student_record"].update({
			"identity_state": "active",
			"identity_exists": True,
			"case_key_exists": True,
			"case_key_state": "resolved",
			"case_key_identity": "ID-1",
			"canonical_student": "STU-1",
		})
		self.assertEqual(classify_legacy_link(row, student=row["student_record"], contact=row["contact_record"]), "backfillable")
