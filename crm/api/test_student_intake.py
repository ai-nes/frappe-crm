import hashlib
import hmac
import uuid
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.student_intake import _intake_response, _normalize_contact_payload, _normalize_manual_payload
from crm.fcrm.student_intake import (
	_MEMORY_RECEIPTS,
	StudentIntakeError,
	_receipt_replay,
	decide_intake_review,
	encode_key,
	keyed_digest,
	normalize_email,
	normalize_national_id,
	normalize_phone,
	redact_provenance,
)


class TestStudentIntakeHelpers(FrappeTestCase):
	def test_prd_contact_payload_maps_to_canonical_command(self):
		payload = _normalize_contact_payload(
			{
				"source_system": "chatwoot",
				"external_id": "conversation-42",
				"idempotency_key": "idem-42",
				"full_name": "Nguyen Test",
				"phone": "+84 901 100 001",
				"province_code": "HCM",
				"high_school_code": "THPT-1",
				"major_code": "CS",
				"lead_source": "website",
				"consent": {"granted": True, "granted_at": "2026-08-29 09:00:00"},
			}
		)

		self.assertEqual(payload["source_namespace"], "chatwoot")
		self.assertEqual(payload["source_record_id"], "conversation-42")
		self.assertEqual(payload["student_name"], "Nguyen Test")
		self.assertEqual(payload["province"], "HCM")
		self.assertEqual(payload["high_school"], "THPT-1")
		self.assertEqual(payload["major"], "CS")
		self.assertEqual(payload["source"], "website")

	def test_prd_contact_response_is_stable_and_contact_stays_nullable(self):
		with patch("crm.api.student_intake._contact_for_student", return_value=None):
			response = _intake_response({"outcome": "created", "student": "STU-1", "receipt": "REC-1"})

		self.assertEqual(
			response,
			{"student_id": "STU-1", "contact_id": None, "status": "created", "receipt_id": "REC-1"},
		)

	def test_review_response_preserves_modal_context(self):
		response = _intake_response(
			{
				"outcome": "review_required",
				"receipt": "REC-2",
				"review_id": "REVIEW-1",
				"candidates": [{"identity_id": "IDENTITY-1", "masked_label": "Candidate identity"}],
				"proposed_identity": "IDENTITY-1",
				"error_code": "REVIEW_REQUIRED",
			}
		)
		self.assertEqual(response["review_id"], "REVIEW-1")
		self.assertEqual(response["candidates"][0]["identity_id"], "IDENTITY-1")
		self.assertEqual(response["proposed_identity"], "IDENTITY-1")
		self.assertEqual(response["error_code"], "REVIEW_REQUIRED")

	def test_prd_contact_payload_rejects_unknown_source_system(self):
		with self.assertRaises(StudentIntakeError) as error:
			_normalize_contact_payload(
				{
					"source_system": "unknown-provider",
					"external_id": "record-1",
					"idempotency_key": "idem-1",
				}
			)
		self.assertEqual(error.exception.code, "INVALID_INPUT")

	def test_manual_modal_payload_is_unwrapped_without_external_source_rules(self):
		canonical = _normalize_manual_payload(
			{
				"source_namespace": "crm.manual_intake",
				"source_record_id": "manual-42",
				"idempotency_key": "manual-idem-42",
				"correlation_id": "manual-correlation-42",
				"payload": {"student_name": "Manual Student", "owning_team": "untrusted-team"},
			}
		)
		self.assertEqual(canonical["source_namespace"], "crm.manual_intake")
		self.assertEqual(canonical["source_record_id"], "manual-42")
		self.assertEqual(canonical["student_name"], "Manual Student")
		self.assertEqual(canonical["owning_team"], "untrusted-team")

	def test_provenance_is_bounded_and_excludes_request_pii(self):
		provenance = redact_provenance(
			{
				"source_system": "chatwoot",
				"external_id": "conversation-43",
				"full_name": "Nguyen Sensitive",
				"phone": "0901000000",
				"email": "sensitive@example.com",
				"raw_payload": {"full_name": "Nguyen Sensitive", "notes": "x" * 20_000},
			}
		)

		self.assertLessEqual(len(str(provenance).encode("utf-8")), 4096)
		self.assertNotIn("full_name", provenance)
		self.assertNotIn("phone", provenance)
		self.assertNotIn("email", provenance)
		self.assertNotIn("raw_payload", provenance)
		self.assertIn("raw_payload_fingerprint", provenance)

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
		self.assertEqual(
			keyed_digest(secret, "crm.receipt.command.v1", "intake", "user@example.com", "idempotency-1"),
			expected,
		)

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
