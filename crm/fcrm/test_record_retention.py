from datetime import datetime, timedelta, timezone
from unittest import TestCase

from crm.fcrm.record_retention import eligible_for_retention, redacted_identifier, redacted_manifest


class TestRecordRetention(TestCase):
	def test_only_expired_terminal_unheld_records_are_eligible(self):
		now = datetime.now(timezone.utc)
		self.assertTrue(eligible_for_retention({"outcome": "applied", "retention_until": now - timedelta(seconds=1)}, kind="receipt", now=now))
		self.assertFalse(eligible_for_retention({"outcome": "pending", "retention_until": now - timedelta(seconds=1)}, kind="receipt", now=now))
		self.assertFalse(eligible_for_retention({"outcome": "applied", "legal_hold": 1, "retention_until": now - timedelta(seconds=1)}, kind="receipt", now=now))

	def test_outbox_pending_or_unexpired_rows_are_protected(self):
		now = datetime.now(timezone.utc)
		self.assertFalse(eligible_for_retention({"status": "pending", "retention_until": now - timedelta(seconds=1)}, kind="outbox", now=now))
		self.assertFalse(eligible_for_retention({"status": "delivered", "retention_until": now + timedelta(seconds=1)}, kind="outbox", now=now))
		self.assertTrue(eligible_for_retention({"status": "delivered", "retention_until": now - timedelta(seconds=1)}, kind="outbox", now=now))

	def test_manifest_identifier_is_stable_and_redacted(self):
		self.assertEqual(redacted_identifier("STUDENT-0001"), redacted_identifier("STUDENT-0001"))
		self.assertNotIn("STUDENT", redacted_identifier("STUDENT-0001"))
		self.assertEqual(
			redacted_manifest([{"name": "STUDENT-0001", "classification": "safe"}], safe_fields=("classification",)),
			[{"record": redacted_identifier("STUDENT-0001"), "classification": "safe"}],
		)
