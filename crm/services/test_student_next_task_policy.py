from frappe.tests.utils import FrappeTestCase

from crm.services.student_next_task_policy import choose_next_task_policy

_VI_DIACRITICS = set("àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ")


def _has_vietnamese(text: str) -> bool:
	return any(character in _VI_DIACRITICS for character in text.casefold())


class TestStudentNextTaskPolicy(FrappeTestCase):
	def test_policy_maps_context_to_governed_action_and_objective(self):
		action, objective, actionable = choose_next_task_policy(
			"application documents", "Consulting", ["DOCUMENT_REQUEST", "CALL"]
		)

		self.assertEqual(action, "DOCUMENT_REQUEST")
		self.assertTrue(actionable)
		self.assertIn("application documents", objective)
		self.assertIn("đang tư vấn", objective)
		self.assertTrue(_has_vietnamese(objective))

	def test_parent_contact_requires_authority_and_never_falls_back_to_contact(self):
		action, objective, actionable = choose_next_task_policy(
			"parent contact", "Lead", ["CALL", "EMAIL"], parent_authorized=False
		)

		self.assertIsNone(action)
		self.assertFalse(actionable)
		self.assertIn("Chưa liên hệ phụ huynh", objective)
		self.assertTrue(_has_vietnamese(objective))

	def test_ineligible_lifecycle_is_monitor_only(self):
		action, objective, actionable = choose_next_task_policy(
			"program information", "Lost", ["CALL", "EMAIL"], eligible=False
		)

		self.assertIsNone(action)
		self.assertFalse(actionable)
		self.assertIn("chưa đủ điều kiện", objective)
		self.assertTrue(_has_vietnamese(objective))
