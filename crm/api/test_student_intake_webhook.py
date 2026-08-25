import hashlib
import hmac

from frappe.tests.utils import FrappeTestCase

from crm.api.student_intake_webhook import signing_message


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
