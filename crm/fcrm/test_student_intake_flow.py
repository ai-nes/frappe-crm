"""Phase-2 intake flow contracts; executed by ``bench run-tests``."""

from frappe.tests.utils import FrappeTestCase

from crm.fcrm.student_intake import _resolve_phone_email_identity


class TestStudentIntakeFlow(FrappeTestCase):
	def test_single_phone_or_email_identity_is_reused(self):
		self.assertEqual(
			_resolve_phone_email_identity({"IDENTITY-EXISTING"}, set(), retracted=False),
			("IDENTITY-EXISTING", None),
		)

	def test_conflicting_phone_and_email_identities_open_review_not_merge(self):
		identity, review_reason = _resolve_phone_email_identity(
			{"IDENTITY-PHONE", "IDENTITY-EMAIL"}, set(), retracted=False
		)
		self.assertIsNone(identity)
		self.assertEqual(review_reason, "identity_conflict")
