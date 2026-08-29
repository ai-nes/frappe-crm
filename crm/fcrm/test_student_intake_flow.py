"""Phase-2 intake flow contracts; executed by ``bench run-tests``."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.student_intake import (
	_assign_initial_manual_owner,
	_resolve_manual_initial_ownership,
	_resolve_phone_email_identity,
)


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

	@patch("crm.fcrm.student_intake._resolve_case_pool")
	@patch("crm.fcrm.student_intake.frappe.db.get_value")
	@patch("crm.fcrm.student_intake.frappe.get_all")
	def test_sale_manual_intake_is_assigned_to_authenticated_staff(self, get_all, get_value, resolve_pool):
		get_all.return_value = [{"team": "TEAM-1", "is_primary": 1}]
		get_value.return_value = frappe._dict(
			name="TEAM-1", campus="CAMPUS-1", team_type="Sales", is_active=1
		)
		resolve_pool.return_value = frappe._dict(name="POOL-1")

		campus, pool, assigned_to = _resolve_manual_initial_ownership(
			{
				"signed": False,
				"profile": "sales",
				"actor_staff": "STAFF-SELF",
				"campus_scope": ["CAMPUS-1"],
			}
		)

		self.assertEqual((campus, pool, assigned_to), ("CAMPUS-1", "POOL-1", "STAFF-SELF"))

	@patch("crm.fcrm.student_intake._resolve_case_pool")
	@patch("crm.fcrm.student_intake.frappe.db.get_value")
	@patch("crm.fcrm.student_intake.frappe.get_all")
	def test_lead_sales_manual_intake_stays_in_primary_pool(self, get_all, get_value, resolve_pool):
		get_all.return_value = [{"team": "TEAM-1", "is_primary": 1}]
		get_value.return_value = frappe._dict(
			name="TEAM-1", campus="CAMPUS-1", team_type="Sales", is_active=1
		)
		resolve_pool.return_value = frappe._dict(name="POOL-1")

		campus, pool, assigned_to = _resolve_manual_initial_ownership(
			{
				"signed": False,
				"profile": "lead_sales",
				"actor_staff": "STAFF-LEAD",
				"campus_scope": ["CAMPUS-1"],
			}
		)

		self.assertEqual((campus, pool, assigned_to), ("CAMPUS-1", "POOL-1", None))

	@patch("crm.fcrm.student_ownership.change_student_ownership")
	def test_sale_initial_owner_uses_canonical_ownership_command(self, change_ownership):
		_assign_initial_manual_owner(
			"STU-1", "STAFF-SELF", "TEAM-1", "correlation-1", "sale@example.com"
		)

		change_ownership.assert_called_once_with(
			"STU-1",
			"owner",
			"STAFF-SELF",
			"TEAM-1",
			"Manual intake self-assignment",
			"intake-initial-owner:STU-1",
			expected_revision=0,
			correlation_id="correlation-1",
			_internal_service=True,
			_internal_actor="sale@example.com",
			_commit=False,
		)
