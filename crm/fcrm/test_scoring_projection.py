from unittest import TestCase

from crm.fcrm.scoring_projection import score_band, score_trend


class TestScoringProjection(TestCase):
	def test_band_is_owned_by_the_scoring_projection(self):
		self.assertEqual(score_band(80), "HIGH")
		self.assertEqual(score_band(50), "MEDIUM")
		self.assertEqual(score_band(10), "LOW")
		self.assertIsNone(score_band(None))

	def test_trend_uses_the_persisted_score_change(self):
		self.assertEqual(score_trend(4), {"direction": "UP", "delta": 4})
		self.assertEqual(score_trend(-2), {"direction": "DOWN", "delta": -2})
		self.assertEqual(score_trend(0), {"direction": "FLAT", "delta": 0})
		self.assertEqual(score_trend(None), {"direction": "UNKNOWN", "delta": None})
