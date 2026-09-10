import hashlib
import hmac
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from crm.api.student_intake_webhook import signing_message, verify_signature
from crm.fcrm.student_intake import StudentIntakeError


class TestStudentIntakeWebhook(FrappeTestCase):
	def test_signature_message_is_bound_to_body_source_timestamp_and_nonce(self):
		secret = b"test-secret"
		message = signing_message(b'{"id":"1"}', "provider-a", "1700000000", "nonce-a")
		signature = hmac.new(secret, message, hashlib.sha256).hexdigest()
		self.assertEqual(len(signature), 64)
		self.assertNotEqual(
			signing_message(b'{"id":"2"}', "provider-a", "1700000000", "nonce-a"),
			message,
		)

	def test_source_bound_hmac_rejects_signature_from_another_source(self):
		body, stamp, nonce = b'{"id":"1"}', "1700000000", "nonce-a"
		with patch("crm.api.student_intake_webhook.time.time", return_value=1700000000), patch(
			"crm.api.student_intake_webhook._source_secret", return_value=[("v1", b"source-secret")]
		):
			signature = hmac.new(b"source-secret", signing_message(body, "provider-a", stamp, nonce), hashlib.sha256).hexdigest()
			self.assertEqual(verify_signature(body, "provider-a", stamp, nonce, signature), "v1")
			with self.assertRaises(StudentIntakeError) as error:
				verify_signature(body, "provider-b", stamp, nonce, signature)
		self.assertEqual(error.exception.code, "REPLAY_REJECTED")

	def test_stale_or_malformed_timestamp_is_rejected_before_intake_mutation(self):
		with patch("crm.api.student_intake_webhook.time.time", return_value=1700000000):
			for timestamp in ("not-a-timestamp", "1699990000"):
				with self.assertRaises(StudentIntakeError) as error:
					verify_signature(b"{}", "provider", timestamp, "nonce", "deadbeef")
				self.assertEqual(error.exception.code, "REPLAY_REJECTED")
