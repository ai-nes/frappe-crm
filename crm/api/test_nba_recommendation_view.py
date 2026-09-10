import unittest

from crm.api.nba_recommendation_view import recommendation_view


class TestRecommendationViewTiming(unittest.TestCase):
	def _view(self, recommended_timing):
		return recommendation_view(
			recommendation_id="REC-1",
			target_type="CRM Lead",
			target_id="LEAD-1",
			action_code="CALL",
			priority="high",
			rank=1,
			reason="",
			explanation=None,
			ai_payload={"recommended_timing": recommended_timing},
			expires_at_iso=None,
			lifecycle_status=None,
			decision_status=None,
			execution_status=None,
		)

	def test_selected_window_passes_through_from_ai_payload(self):
		view = self._view(
			{
				"scheduled_at": "2026-09-07T11:00:00+00:00",
				"selected_window": {"code": "18-24", "from": "18:00", "to": "00:00"},
				"timezone": "Asia/Ho_Chi_Minh",
			}
		)
		self.assertEqual(
			view["timing"]["selected_window"],
			{"code": "18-24", "from": "18:00", "to": "00:00"},
		)

	def test_selected_window_is_none_when_absent(self):
		view = self._view({"scheduled_at": "2026-09-07T11:00:00+00:00", "timezone": "UTC"})
		self.assertIsNone(view["timing"]["selected_window"])


class TestRecommendationViewTitle(unittest.TestCase):
	def _view(self, explanation):
		return recommendation_view(
			recommendation_id="REC-1",
			target_type="CRM Lead",
			target_id="LEAD-1",
			action_code="CALL",
			priority="high",
			rank=1,
			reason="",
			explanation=explanation,
			ai_payload=None,
			expires_at_iso=None,
			lifecycle_status=None,
			decision_status=None,
			execution_status=None,
		)

	def test_title_passes_through_from_the_rendered_explanation(self):
		view = self._view({"title": "Gọi lại về học phí"})
		self.assertEqual(view["title"], "Gọi lại về học phí")

	def test_title_falls_back_to_the_generic_action_title_when_absent(self):
		view = self._view(None)
		self.assertEqual(view["title"], view["action"]["title"])


class TestRecommendationViewObjective(unittest.TestCase):
	def _view(self, *, explanation, reason):
		return recommendation_view(
			recommendation_id="REC-1",
			target_type="CRM Lead",
			target_id="LEAD-1",
			action_code="CALL",
			priority="high",
			rank=1,
			reason=reason,
			explanation=explanation,
			ai_payload=None,
			expires_at_iso=None,
			lifecycle_status=None,
			decision_status=None,
			execution_status=None,
		)

	def test_objective_passes_through_from_the_rendered_explanation(self):
		view = self._view(explanation={"objective": "Xác nhận học phí."}, reason="6 ngày chưa có tương tác")
		self.assertEqual(view["objective"], "Xác nhận học phí.")

	def test_objective_falls_back_to_the_kernel_reason_when_narration_failed(self):
		"""Narration is best-effort and fails closed to no explanation -- every
		card must still carry an objective so the FE contract stays consistent
		across cards, whether or not the model rendered one."""
		view = self._view(explanation=None, reason="6 ngày chưa có tương tác")
		self.assertEqual(view["objective"], "6 ngày chưa có tương tác")

	def test_objective_is_none_when_neither_explanation_nor_reason_exist(self):
		view = self._view(explanation=None, reason="")
		self.assertIsNone(view["objective"])
