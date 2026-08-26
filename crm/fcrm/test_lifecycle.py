# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

"""Pure-function unit tests for crm/fcrm/lifecycle.py — the highest-value test
surface here since lifecycle_rank/is_backward_or_reopen/user_can_override_lifecycle
are plain logic with no DB writes required. get_lifecycle_stage/enforce_lifecycle_change_policy
still need frappe.db / frappe.session and are covered indirectly through
CRM Contact / CRM Student save-path tests (test_crm_contact.py / test_crm_student.py)."""

import frappe
from frappe.tests.utils import FrappeTestCase
from unittest.mock import patch

from crm.fcrm.lifecycle import (
	LIFECYCLE_ORDER,
	LOST_STAGE,
	is_backward_or_reopen,
	lifecycle_rank,
	user_can_override_lifecycle,
)
from crm.fcrm.student_lifecycle import StudentLifecycleError, lifecycle_targets, validate_transition


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


class TestLifecycleJumps(FrappeTestCase):
	def setUp(self):
		self.capabilities = {"lifecycle.transition"}
		self.evidence = [
			{"category": "outcome", "doctype": "CRM Student Outcome", "name": "OUT-1"},
			{"category": "intent", "doctype": "CRM Intent", "name": "INT-1"},
			{"category": "document", "doctype": "CRM Student Document", "name": "DOC-1"},
		]

	def test_active_stage_lists_every_later_stage_when_writes_enabled(self):
		with patch("crm.fcrm.student_lifecycle.enabled", return_value=True):
			targets = lifecycle_targets("Lead", self.capabilities)
		self.assertEqual([target["stage"] for target in targets], ["MQL", "Applicant", "Enrolled"])

	def test_each_forward_target_requires_its_cumulative_qualification_evidence(self):
		for target in ("MQL", "Applicant", "Enrolled"):
			transition = validate_transition(
				"Lead", target, outcome_code="qualified", evidence=self.evidence, capabilities=self.capabilities
			)
			self.assertEqual(transition["to_stage"], target)

	def test_lost_and_reopen_require_a_reason_and_capability(self):
		with self.assertRaises(StudentLifecycleError) as lost:
			validate_transition("Applicant", "Lost", capabilities={"lifecycle.lost"})
		self.assertEqual(lost.exception.code, "REASON_REQUIRED")
		self.assertEqual(
			validate_transition("Applicant", "Lost", reason="Candidate withdrew", capabilities={"lifecycle.lost"})[
				"transition_kind"
			],
			"lost",
		)
		with self.assertRaises(StudentLifecycleError) as reopen:
			validate_transition("Lost", "Reopen", reason="Re-engaged", capabilities=set())
		self.assertEqual(reopen.exception.code, "FORBIDDEN")
		self.assertEqual(
			validate_transition("Lost", "Reopen", reason="Re-engaged", capabilities={"lifecycle.reopen"})[
				"transition_kind"
			],
			"reopen",
		)

	def test_forward_transition_rejects_missing_or_mislabeled_evidence(self):
		with self.assertRaises(StudentLifecycleError) as missing:
			validate_transition("Lead", "Applicant", outcome_code="qualified", evidence=[], capabilities=self.capabilities)
		self.assertEqual(missing.exception.code, "INVALID_EVIDENCE")
		foreign_kind = [
			{"category": "outcome", "doctype": "CRM Student Outcome", "name": "OUT-1"},
			{"category": "document", "doctype": "CRM Intent", "name": "INT-1"},
		]
		with self.assertRaises(StudentLifecycleError) as mislabeled:
			validate_transition("Lead", "MQL", outcome_code="qualified", evidence=foreign_kind, capabilities=self.capabilities)
		self.assertEqual(mislabeled.exception.code, "INVALID_EVIDENCE")

	def test_direct_jump_uses_cumulative_evidence(self):
		transition = validate_transition(
			"Lead", "Enrolled", outcome_code="qualified", evidence=self.evidence, capabilities=self.capabilities
		)
		self.assertEqual(transition["transition_kind"], "forward")
		self.assertEqual(transition["to_stage"], "Enrolled")
		self.assertEqual(
			validate_transition("MQL", "Enrolled", outcome_code="qualified", evidence=self.evidence, capabilities=self.capabilities)["to_stage"],
			"Enrolled",
		)

	def test_direct_jump_rejects_missing_skipped_stage_evidence(self):
		with self.assertRaises(StudentLifecycleError) as error:
			validate_transition(
				"Lead",
				"Enrolled",
				outcome_code="qualified",
				evidence=[{"category": "intent", "doctype": "CRM Intent", "name": "INT-1"}],
				capabilities=self.capabilities,
			)
		self.assertEqual(error.exception.code, "INVALID_EVIDENCE")

	def test_direct_jump_rejects_mislabeled_or_missing_outcome_record(self):
		with self.assertRaises(StudentLifecycleError) as error:
			validate_transition(
				"Lead",
				"Enrolled",
				outcome_code="qualified",
				evidence=[
					{"category": "outcome", "doctype": "CRM Student Outcome", "name": "OUT-1"},
					{"category": "document", "doctype": "CRM Intent", "name": "INT-1"},
				],
				capabilities=self.capabilities,
			)
		self.assertEqual(error.exception.code, "INVALID_EVIDENCE")
