# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

"""Pure-function unit tests for crm/fcrm/lifecycle.py — the highest-value test
surface here since lifecycle_rank/is_backward_or_reopen/user_can_override_lifecycle
are plain logic with no DB writes required. get_lifecycle_stage/enforce_lifecycle_change_policy
still need frappe.db / frappe.session and are covered indirectly through
CRM Contact / CRM Student save-path tests (test_crm_contact.py / test_crm_student.py)."""

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.lifecycle import (
	LIFECYCLE_ORDER,
	LOST_STAGE,
	is_backward_or_reopen,
	lifecycle_rank,
	user_can_override_lifecycle,
)


class TestLifecycleRank(FrappeTestCase):
	def test_rank_matches_position_in_order(self):
		for index, stage in enumerate(LIFECYCLE_ORDER):
			self.assertEqual(lifecycle_rank(stage), index)

	def test_lost_has_no_rank(self):
		self.assertIsNone(lifecycle_rank(LOST_STAGE))

	def test_unmapped_stage_has_no_rank(self):
		self.assertIsNone(lifecycle_rank("Some Unknown Stage"))
		self.assertIsNone(lifecycle_rank(None))
		self.assertIsNone(lifecycle_rank(""))


class TestIsBackwardOrReopen(FrappeTestCase):
	def test_forward_move_is_not_backward(self):
		self.assertFalse(is_backward_or_reopen("Lead", "MQL"))
		self.assertFalse(is_backward_or_reopen("MQL", "Applicant"))
		self.assertFalse(is_backward_or_reopen("Lead", "Enrolled"))

	def test_same_stage_is_not_backward(self):
		self.assertFalse(is_backward_or_reopen("MQL", "MQL"))

	def test_backward_move_within_main_track(self):
		self.assertTrue(is_backward_or_reopen("Applicant", "MQL"))
		self.assertTrue(is_backward_or_reopen("Enrolled", "Lead"))

	def test_entering_lost_is_not_backward(self):
		# Entering Lost from any stage is deliberately not gated — only
		# *leaving* Lost (reopening) is.
		self.assertFalse(is_backward_or_reopen("Lead", LOST_STAGE))
		self.assertFalse(is_backward_or_reopen("Enrolled", LOST_STAGE))

	def test_reopen_from_lost_is_backward(self):
		self.assertTrue(is_backward_or_reopen(LOST_STAGE, "Lead"))
		self.assertTrue(is_backward_or_reopen(LOST_STAGE, "MQL"))
		self.assertTrue(is_backward_or_reopen(LOST_STAGE, "Enrolled"))

	def test_lost_to_lost_is_not_backward(self):
		self.assertFalse(is_backward_or_reopen(LOST_STAGE, LOST_STAGE))

	def test_blank_stages_are_not_backward(self):
		self.assertFalse(is_backward_or_reopen(None, "MQL"))
		self.assertFalse(is_backward_or_reopen("MQL", None))
		self.assertFalse(is_backward_or_reopen(None, None))

	def test_unmapped_stage_is_not_backward(self):
		# If either side isn't in the main track (and isn't Lost), there is no
		# ordering to compare, so it must not be flagged as backward.
		self.assertFalse(is_backward_or_reopen("Unknown", "MQL"))
		self.assertFalse(is_backward_or_reopen("MQL", "Unknown"))


class TestUserCanOverrideLifecycle(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def test_administrator_can_override(self):
		self.assertTrue(user_can_override_lifecycle("Administrator"))

	def test_user_without_override_role_cannot_override(self):
		email = "_test_lifecycle_no_override@example.com"
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, force=True)
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "_Test",
				"send_welcome_email": 0,
				"roles": [{"role": "Sale"}],
			}
		)
		user.insert(ignore_permissions=True)
		try:
			self.assertFalse(user_can_override_lifecycle(user.name))
		finally:
			frappe.delete_doc("User", user.name, force=True)

	def test_user_with_team_leader_role_can_override(self):
		email = "_test_lifecycle_team_leader@example.com"
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, force=True)
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "_Test",
				"send_welcome_email": 0,
				"roles": [{"role": "Lead Sales"}],
			}
		)
		user.insert(ignore_permissions=True)
		try:
			self.assertTrue(user_can_override_lifecycle(user.name))
		finally:
			frappe.delete_doc("User", user.name, force=True)
