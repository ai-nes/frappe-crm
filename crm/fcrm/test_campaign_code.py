from unittest import TestCase
from unittest.mock import patch

from crm.fcrm.campaign_code import (
	campaign_code_date,
	is_valid_campaign_code,
	next_campaign_code,
)


class TestCampaignCode(TestCase):
	def test_campaign_code_date_uses_creation_date_in_yymmdd_format(self):
		self.assertEqual(campaign_code_date("2026-09-09 12:30:00"), "260909")

	def test_next_campaign_code_includes_normalized_campus_and_date(self):
		with patch("crm.fcrm.campaign_code.secrets.choice", side_effect=list("K7M2")) as choice:
			code = next_campaign_code(" fptu-hcm ", "2026-09-09")

		self.assertEqual(code, "CMP-FPTU-HCM-260909-K7M2")
		self.assertEqual(choice.call_count, 4)

	def test_campaign_code_validation_accepts_new_and_legacy_codes(self):
		self.assertTrue(is_valid_campaign_code("CMP-FPTU-HCM-260909-K7M2"))
		self.assertTrue(is_valid_campaign_code("CAM-2026-00001"))
		self.assertFalse(is_valid_campaign_code("CMP-FPTU-HCM-260909-K7M"))
