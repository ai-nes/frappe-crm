from frappe.tests.utils import FrappeTestCase

from crm.fcrm.student_intake import _resolve_phone_email_identity


class TestPhoneEmailIdentityResolution(FrappeTestCase):
	def test_phone_or_email_root_can_attach_without_national_id(self):
		self.assertEqual(
			_resolve_phone_email_identity({"IDENTITY-1"}, set(), retracted=False),
			("IDENTITY-1", None),
		)

	def test_national_id_does_not_change_phone_email_resolution(self):
		self.assertEqual(
			_resolve_phone_email_identity({"IDENTITY-1"}, {"IDENTITY-2"}, retracted=True),
			("IDENTITY-1", None),
		)

	def test_conflicting_phone_email_roots_require_review(self):
		self.assertEqual(
			_resolve_phone_email_identity({"IDENTITY-1", "IDENTITY-2"}, set(), retracted=False),
			(None, "identity_conflict"),
		)
