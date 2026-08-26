from frappe.tests.utils import FrappeTestCase


class TestCRMStudentDecisionEvent(FrappeTestCase):
	def test_event_type_vocabulary_is_closed(self):
		from crm.fcrm.doctype.crm_student_decision_event.crm_student_decision_event import CRMStudentDecisionEvent

		self.assertIn("recommendation_decided", CRMStudentDecisionEvent._EVENT_TYPES)
		self.assertIn("action_completed", CRMStudentDecisionEvent._EVENT_TYPES)
		self.assertNotIn("recommendation.accepted", CRMStudentDecisionEvent._EVENT_TYPES)

	def test_event_is_append_only(self):
		from crm.fcrm.doctype.crm_student_decision_event.crm_student_decision_event import CRMStudentDecisionEvent

		self.assertTrue(callable(CRMStudentDecisionEvent.on_trash))
