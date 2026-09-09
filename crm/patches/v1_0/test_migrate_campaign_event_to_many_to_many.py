# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from unittest import skipUnless

from crm.patches.v1_0.migrate_campaign_event_to_many_to_many import (
	_backfill_event_start_datetime,
	_migrate_campaigns,
	_migrate_events,
)


@skipUnless(
	frappe.db.exists("DocType", "CRM Campaign Touchpoint")
	and frappe.db.exists("DocType", "CRM Event Participation"),
	"Legacy marketing DocTypes are already migrated to CRM Marketing Engagement",
)
class TestMigrateCampaignEventToManyToMany(FrappeTestCase):
	"""Idempotency coverage for the Phase 5 backfill patch. The migration reads
	the deprecated CRM Student.crm_campaign / crm_event singular Link fields
	and creates CRM Campaign Touchpoint / CRM Event Participation rows,
	skipping any (campaign, contact) / (event, contact) pair that already has
	one -- see the frappe.db.exists guards in _migrate_campaigns/_migrate_events.
	"""

	def setUp(self):
		frappe.set_user("Administrator")
		self.campus = self._make_campus("_Test Migrate Campus")
		self.campaign = self._make_campaign("_Test Migrate Campaign", self.campus)
		self.event = self._make_event("_Test Migrate Event", self.campaign)
		# The migration only reads the deprecated singular fields, so the
		# contact must be created with them set (they're no longer written
		# by normal CRM Contact flows post-Phase-5).
		self.contact = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"full_name": "_Test Migrate Contact",
				"phone": "0977000003",
				"enrollment_status": "PROSPECT",
				"crm_campaign": self.campaign,
				"crm_event": self.event,
			}
		)
		self.contact.insert(ignore_permissions=True)

	def tearDown(self):
		for name in frappe.db.get_all("CRM Marketing Engagement", filters={"crm_campaign": self.campaign}, pluck="name"):
			frappe.delete_doc("CRM Marketing Engagement", name, force=True)
		for name in frappe.db.get_all("CRM Marketing Engagement", filters={"crm_event": self.event}, pluck="name"):
			frappe.delete_doc("CRM Marketing Engagement", name, force=True)
		for name in frappe.db.get_all("CRM Student", filters={"full_name": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Student", name, force=True)
		for name in frappe.db.get_all("CRM Event", filters={"title": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Event", name, force=True)
		for name in frappe.db.get_all("CRM Campaign", filters={"title": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Campaign", name, force=True)
		for name in frappe.db.get_all("CRM Campus", filters={"campus_name": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Campus", name, force=True)

	def _make_campus(self, name):
		if frappe.db.exists("CRM Campus", name):
			frappe.delete_doc("CRM Campus", name, force=True)
		doc = frappe.get_doc(
			{"doctype": "CRM Campus", "campus_name": name, "campus_code": "TEST-MIGRATE"}
		)
		doc.insert(ignore_permissions=True)
		return doc.name

	def _make_campaign(self, title, campus):
		if frappe.db.exists("CRM Campaign", title):
			frappe.delete_doc("CRM Campaign", title, force=True)
		doc = frappe.get_doc({"doctype": "CRM Campaign", "title": title, "campus": campus})
		doc.insert(ignore_permissions=True)
		return doc.name

	def _make_event(self, title, campaign):
		if frappe.db.exists("CRM Event", title):
			frappe.delete_doc("CRM Event", title, force=True)
		doc = frappe.get_doc(
			{
				"doctype": "CRM Event",
				"title": title,
				"crm_campaign": campaign,
				"start_datetime": "2026-09-01 09:00:00",
			}
		)
		doc.insert(ignore_permissions=True)
		return doc.name

	def test_migrate_campaigns_is_idempotent(self):
		frappe.flags.in_patch = True
		try:
			_migrate_campaigns()
			_migrate_campaigns()
		finally:
			frappe.flags.in_patch = False

		count = frappe.db.count("CRM Marketing Engagement", {"engagement_kind": "campaign_touch", "crm_campaign": self.campaign, "crm_contact": self.contact.name})
		self.assertEqual(count, 1)

	def test_migrate_events_is_idempotent(self):
		frappe.flags.in_patch = True
		try:
			_migrate_events()
			_migrate_events()
		finally:
			frappe.flags.in_patch = False

		count = frappe.db.count("CRM Marketing Engagement", {"engagement_kind": "event_participation", "crm_event": self.event, "crm_contact": self.contact.name})
		self.assertEqual(count, 1)

	def test_migrated_touchpoint_is_marked_as_migrated_source(self):
		frappe.flags.in_patch = True
		try:
			_migrate_campaigns()
		finally:
			frappe.flags.in_patch = False

		source = frappe.db.get_value("CRM Marketing Engagement", {"engagement_kind": "campaign_touch", "crm_campaign": self.campaign, "crm_contact": self.contact.name}, "source")
		self.assertEqual(source, "Migrated")

	def test_backfill_event_start_datetime_only_fills_null_values(self):
		# Simulate a pre-Phase-5 row where start_datetime was never set.
		frappe.db.set_value("CRM Event", self.event, "start_datetime", None)
		frappe.db.set_value("CRM Event", self.event, "event_date", "2026-09-01")

		_backfill_event_start_datetime()

		start_datetime = frappe.db.get_value("CRM Event", self.event, "start_datetime")
		self.assertTrue(start_datetime)
