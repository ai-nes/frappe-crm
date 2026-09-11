from unittest.mock import Mock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.campaign_source import (
	campaign_source,
	sync_campaign_source,
	sync_student_campaign_source,
)


class TestCampaignSource(FrappeTestCase):
	def test_campaign_channel_type_resolves_to_governed_source(self):
		with patch.object(
			frappe.db,
			"get_value",
			side_effect=[
				"OPEN_DAY",
				frappe._dict(code="OPEN_DAY", display_name="Open Day"),
				"Open Day",
				"Approved",
			],
		):
			self.assertEqual(campaign_source("Campaign 1"), "Open Day")

	def test_campaign_source_overrides_stale_source(self):
		doc = Mock()
		doc.get.side_effect = lambda fieldname: {"campaign": "Campaign 1"}.get(fieldname)
		with patch(
			"crm.fcrm.campaign_source.campaign_source",
			return_value="Open Day",
		) as resolve_source:
			self.assertEqual(sync_campaign_source(doc), "Open Day")

		resolve_source.assert_called_once_with("Campaign 1")
		doc.set.assert_called_once_with("source", "Open Day")

	def test_student_uses_its_own_campaign(self):
		doc = Mock()
		doc.get.side_effect = lambda fieldname: {"campaign": "Campaign 1"}.get(fieldname)
		with (
			patch("crm.fcrm.campaign_source.campaign_source", return_value="Open Day") as resolve_source,
		):
			self.assertEqual(sync_student_campaign_source(doc), "Open Day")

		doc.set.assert_any_call("source", "Open Day")
		resolve_source.assert_called_once_with("Campaign 1")

	def test_campaign_without_channel_type_is_rejected(self):
		with patch.object(frappe.db, "get_value", return_value=None):
			with self.assertRaises(frappe.ValidationError):
				campaign_source("Campaign 1")
