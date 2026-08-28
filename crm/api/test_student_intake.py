import hashlib
import hmac
import uuid

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.student_intake import (
	StudentIntakeError,
	_MEMORY_RECEIPTS,
	_receipt_replay,
	decide_intake_review,
	encode_key,
	keyed_digest,
	normalize_email,
	normalize_national_id,
	normalize_phone,
)


class TestStudentIntakeHelpers(FrappeTestCase):
	def test_normalizers_keep_weak_values_canonical_without_global_identity_policy(self):
		self.assertEqual(normalize_phone("+84 901-100-001"), "0901100001")
		self.assertEqual(normalize_email("  Student@Example.COM "), "student@example.com")
		self.assertEqual(normalize_national_id("079-123 456 789"), "079123456789")
		self.assertIsNone(normalize_national_id("name-only"))

	def test_domain_separated_encoding_prevents_concatenation_collisions(self):
		self.assertNotEqual(encode_key("crm.test", "ab", "c"), encode_key("crm.test", "a", "bc"))
		self.assertNotEqual(encode_key("crm.test.one", "value"), encode_key("crm.test.two", "value"))

	def test_keyed_digest_matches_standard_hmac(self):
		secret = b"test-secret"
		message = encode_key("crm.receipt.command.v1", "intake", "user@example.com", "idempotency-1")
		expected = hmac.new(secret, message, hashlib.sha256).hexdigest()
		self.assertEqual(keyed_digest(secret, "crm.receipt.command.v1", "intake", "user@example.com", "idempotency-1"), expected)

	def test_command_error_exposes_stable_machine_code(self):
		error = StudentIntakeError("REVIEW_REQUIRED", "manual review")
		self.assertEqual(error.code, "REVIEW_REQUIRED")
		self.assertEqual(error.error_code, "REVIEW_REQUIRED")

	def test_replay_returns_the_immutable_receipt_projection(self):
		key = {"version": "v1", "command_key": "command-a", "source_key": "source-a", "nonce_key": None}
		_MEMORY_RECEIPTS["command-a"] = {
			"name": "RECEIPT-1",
			"request_fingerprint": "same-body",
			"result_json": '{"outcome":"created","student":"STU-1"}',
		}
		try:
			result = _receipt_replay([key], "same-body", source_namespace="provider", idempotency_key="key-a")
		finally:
			_MEMORY_RECEIPTS.pop("command-a", None)
		self.assertEqual(result, {"outcome": "created", "student": "STU-1", "receipt": "RECEIPT-1"})

	def test_reused_idempotency_key_with_different_body_is_denied(self):
		key = {"version": "v1", "command_key": "command-b", "source_key": "source-b", "nonce_key": None}
		_MEMORY_RECEIPTS["command-b"] = {"name": "RECEIPT-2", "request_fingerprint": "first"}
		try:
			with self.assertRaises(StudentIntakeError) as error:
				_receipt_replay([key], "second", source_namespace="provider", idempotency_key="key-b")
		finally:
			_MEMORY_RECEIPTS.pop("command-b", None)
		self.assertEqual(error.exception.code, "IDEMPOTENCY_KEY_REUSED")


class TestStudentIntakeReviewCAS(FrappeTestCase):
	def test_decision_replay_returns_original_receipt_and_stale_revision_fails(self):
		review = frappe.get_doc(
			{
				"doctype": "CRM Student Intake Review",
				"review_key": f"TEST-RV-{uuid.uuid4().hex}",
				"review_status": "open",
				"revision": 0,
				"review_type": "malformed_identifier",
			}
		).insert(ignore_permissions=True)
		first = decide_intake_review(
			review.name,
			"reject",
			["test-evidence"],
			"test rejection",
			"review-cas-1",
			expected_revision=0,
		)
		self.assertEqual(first["outcome"], "review_applied")
		self.assertEqual(first["revision"], 1)
		# Durable replay must not depend on the process-local cache.
		_MEMORY_RECEIPTS.clear()

		replay = decide_intake_review(
			review.name,
			"reject",
			["test-evidence"],
			"test rejection",
			"review-cas-1",
			expected_revision=0,
		)
		self.assertEqual(replay["receipt"], first["receipt"])
		self.assertEqual(replay["revision"], 1)
		self.assertEqual(replay["outcome"], "review_applied")

		with self.assertRaises(StudentIntakeError) as error:
			decide_intake_review(
				review.name,
				"reject",
				["different-evidence"],
				"stale rejection",
				"review-cas-2",
				expected_revision=0,
			)
		self.assertEqual(error.exception.code, "STALE_REVISION")
