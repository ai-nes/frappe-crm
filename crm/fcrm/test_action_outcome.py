import unittest

from crm.services.action_outcome import (
	DecisionEffect,
	allowed_outcomes,
	derive_decision_effects,
	derive_progress,
	validate_outcome,
)


class TestActionOutcome(unittest.TestCase):
	def test_progress_is_bounded_and_type_aware(self):
		self.assertEqual(derive_progress("CALL", "INTEREST_INCREASED"), "POSITIVE_PROGRESS")
		self.assertEqual(derive_progress("REQUEST_MISSING_DOCUMENT", "APPLICATION_BLOCKED"), "NEGATIVE_PROGRESS")
		self.assertEqual(derive_progress("NOT_A_REAL_ACTION", "INTEREST_INCREASED"), "UNKNOWN")

	def test_unknown_outcome_is_rejected_globally(self):
		with self.assertRaises(ValueError):
			validate_outcome("converted")

	def test_outcome_is_rejected_when_not_valid_for_action(self):
		with self.assertRaises(ValueError):
			validate_outcome("APPLICATION_COMPLETED", action_code="CALL")

	def test_outcome_accepted_when_valid_for_action(self):
		self.assertEqual(validate_outcome("NOT_INTERESTED", action_code="CALL"), "NOT_INTERESTED")

	def test_not_interested_yields_interest_and_contact_effects(self):
		effects = derive_decision_effects("CALL", "NOT_INTERESTED")
		self.assertIn(DecisionEffect("interest_disposition", "not_interested"), effects)
		self.assertIn(DecisionEffect("contact_attempt_signal", "succeeded"), effects)

	def test_interest_confirmed_sets_confirmed_disposition(self):
		effects = derive_decision_effects("CALL", "INTEREST_CONFIRMED")
		self.assertIn(DecisionEffect("interest_disposition", "confirmed"), effects)

	def test_decision_pending_is_its_own_dimension(self):
		effects = derive_decision_effects("CALL", "DECISION_PENDING")
		self.assertIn(DecisionEffect("decision_status", "pending"), effects)
		self.assertNotIn(DecisionEffect("interest_disposition", "pending"), effects)

	def test_application_completed_yields_application_assessment(self):
		effects = derive_decision_effects("CHECK_APPLICATION", "APPLICATION_COMPLETED")
		self.assertEqual(effects, (DecisionEffect("application_assessment", "completed_confirmed"),))

	def test_application_in_progress_yields_application_assessment(self):
		effects = derive_decision_effects("CHECK_APPLICATION", "APPLICATION_IN_PROGRESS")
		self.assertEqual(effects, (DecisionEffect("application_assessment", "in_progress"),))

	def test_enrollment_confirmed_is_not_merged_into_application_assessment(self):
		effects = derive_decision_effects("ADVISE_MAJOR", "ENROLLMENT_CONFIRMED")
		self.assertEqual(effects, (DecisionEffect("enrollment_assessment", "confirmed"),))

	def test_parent_supportive_sets_parent_disposition(self):
		effects = derive_decision_effects("CONTACT_PARENT", "PARENT_SUPPORTIVE")
		self.assertEqual(effects, (DecisionEffect("parent_disposition", "supportive"),))

	def test_no_response_yields_contact_attempt_failure(self):
		effects = derive_decision_effects("CALL", "NO_RESPONSE")
		self.assertEqual(effects, (DecisionEffect("contact_attempt_signal", "failed"),))

	def test_internal_action_has_no_decision_effect(self):
		self.assertEqual(derive_decision_effects("CREATE_TASK", "COMPLETED"), ())

	def test_unmapped_action_has_no_allowed_outcomes(self):
		self.assertEqual(allowed_outcomes("NOT_A_REAL_ACTION"), frozenset())

	def test_not_ready_sets_decision_status_not_ready_not_interest_disposition(self):
		effects = derive_decision_effects("REENGAGE_LEAD", "NOT_READY")
		self.assertIn(DecisionEffect("decision_status", "not_ready"), effects)
		self.assertNotIn(DecisionEffect("interest_disposition", "needs_info"), effects)

	def test_lost_confirmed_sets_decision_status_lost_and_not_interested(self):
		effects = derive_decision_effects("REENGAGE_LEAD", "LOST_CONFIRMED")
		self.assertIn(DecisionEffect("decision_status", "lost"), effects)
		self.assertIn(DecisionEffect("interest_disposition", "not_interested"), effects)

	def test_no_show_has_no_contact_attempt_effect(self):
		effects = derive_decision_effects("INVITE_OPEN_DAY", "NO_SHOW")
		self.assertEqual(effects, ())

	def test_handoff_actions_are_overridden_to_internal_profile_but_keep_category(self):
		for action_code in ("REASSIGN_ADVISOR", "ESCALATE_SUPERVISOR", "ESCALATE_HIGH_INTENT", "ESCALATE_TO_SENIOR"):
			self.assertEqual(allowed_outcomes(action_code), frozenset({"COMPLETED", "FAILED", "CANCELLED"}))
			self.assertEqual(derive_decision_effects(action_code, "COMPLETED"), ())
			with self.assertRaises(ValueError):
				validate_outcome("NOT_INTERESTED", action_code=action_code)
