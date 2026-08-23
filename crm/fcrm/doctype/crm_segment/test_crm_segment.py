# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

import crm.api.segment as segment_api
from crm.api.segment import (
	attach_segment_to_campaign,
	get_matching_contact_names,
	preview_segment,
	validate_segment_filters,
)


class TestCRMSegment(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.contacts = []
		self.contacts.append(self._make_contact("A", lifecycle_stage="Lead", is_opted_out=0))
		self.contacts.append(self._make_contact("B", lifecycle_stage="MQL", is_opted_out=0))
		self.contacts.append(self._make_contact("C", lifecycle_stage="Applicant", is_opted_out=1))
		self.contacts.append(self._make_contact("D", lifecycle_stage="Lost", is_opted_out=1))

	def tearDown(self):
		frappe.set_user("Administrator")
		test_campaigns = frappe.db.get_all("CRM Campaign", filters={"title": ["like", "_Test%"]}, pluck="name")
		if test_campaigns:
			for name in frappe.db.get_all(
				"CRM Campaign Touchpoint", filters={"crm_campaign": ["in", test_campaigns]}, pluck="name"
			):
				frappe.delete_doc("CRM Campaign Touchpoint", name, force=True)
		for name in frappe.db.get_all("CRM Segment", filters={"title": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Segment", name, force=True)
		for name in test_campaigns:
			frappe.delete_doc("CRM Campaign", name, force=True)
		for name in frappe.db.get_all("CRM Campus", filters={"campus_name": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Campus", name, force=True)
		for name in frappe.db.get_all("CRM Contact", filters={"last_name": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Contact", name, force=True)
		for name in frappe.db.get_all("User", filters={"first_name": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("User", name, force=True)

	def _make_campus(self, name):
		if frappe.db.exists("CRM Campus", name):
			frappe.delete_doc("CRM Campus", name, force=True)
		doc = frappe.get_doc({"doctype": "CRM Campus", "campus_name": name})
		doc.insert(ignore_permissions=True)
		return doc.name

	def _make_campaign(self, title, campus):
		doc = frappe.get_doc({"doctype": "CRM Campaign", "title": title, "campus": campus})
		doc.insert(ignore_permissions=True)
		return doc.name

	def _make_user(self, prefix, roles=("Counseller",)):
		email = f"{frappe.scrub(prefix)}@example.com"
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, force=True)
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": prefix,
				"send_welcome_email": 0,
				"roles": [{"role": role} for role in roles],
			}
		)
		user.insert(ignore_permissions=True)
		return email

	def _make_contact(self, suffix, **kwargs):
		doc = frappe.get_doc(
			{
				"doctype": "CRM Contact",
				"first_name": "_Test",
				"last_name": f"_Test Segment {suffix}",
				"phone": f"_Test-Segment-{suffix}",
				**kwargs,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc.name

	def _make_segment(self, title, filters):
		doc = frappe.get_doc({"doctype": "CRM Segment", "title": title, "filters": filters})
		doc.insert(ignore_permissions=True)
		return doc

	# ------------------------------------------------------------ OR-of-AND correctness

	def test_two_group_or_of_and_matches_hand_built_query(self):
		filters = {
			"groups": [
				{"logic": "AND", "conditions": [{"field": "lifecycle_stage", "operator": "=", "value": "Lead"}]},
				{
					"logic": "AND",
					"conditions": [
						{"field": "lifecycle_stage", "operator": "=", "value": "Applicant"},
						{"field": "is_opted_out", "operator": "=", "value": 1},
					],
				},
			]
		}
		matches = get_matching_contact_names(filters)

		expected = set(
			frappe.get_list(
				"CRM Contact",
				filters=[["name", "in", self.contacts]],
				or_filters=[["lifecycle_stage", "=", "Lead"]],
				pluck="name",
			)
		) | set(
			frappe.get_list(
				"CRM Contact",
				filters=[
					["name", "in", self.contacts],
					["lifecycle_stage", "=", "Applicant"],
					["is_opted_out", "=", 1],
				],
				pluck="name",
			)
		)

		self.assertEqual(matches & set(self.contacts), expected & set(self.contacts))

	# ------------------------------------------------------------ zero-groups / zero-condition

	def test_zero_groups_rejected_not_all_matches(self):
		with self.assertRaises(frappe.ValidationError):
			validate_segment_filters({"groups": []})
		with self.assertRaises(frappe.ValidationError):
			get_matching_contact_names({"groups": []})

	def test_zero_condition_group_rejected_not_all_matches(self):
		filters = {"groups": [{"logic": "AND", "conditions": []}]}
		with self.assertRaises(frappe.ValidationError):
			validate_segment_filters(filters)
		with self.assertRaises(frappe.ValidationError):
			get_matching_contact_names(filters)

	def test_malformed_filters_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			get_matching_contact_names(None)
		with self.assertRaises(frappe.ValidationError):
			get_matching_contact_names({})

	# ------------------------------------------------------------ allow-list enforcement

	def test_non_allowlisted_field_rejected_at_save(self):
		filters = {
			"groups": [{"logic": "AND", "conditions": [{"field": "email", "operator": "=", "value": "x@example.com"}]}]
		}
		with self.assertRaises(frappe.ValidationError):
			self._make_segment("_Test Segment Bad Field", filters)

	def test_non_allowlisted_field_rejected_at_matcher_directly(self):
		"""The matcher itself must reject, not just Document.validate() — this is
		what makes draft preview (which never calls validate()) safe."""
		filters = {
			"groups": [{"logic": "AND", "conditions": [{"field": "email", "operator": "=", "value": "x@example.com"}]}]
		}
		with self.assertRaises(frappe.ValidationError):
			get_matching_contact_names(filters)

	def test_group_cap_enforced(self):
		groups = [
			{"logic": "AND", "conditions": [{"field": "is_opted_out", "operator": "=", "value": 0}]}
			for _ in range(11)
		]
		with self.assertRaises(frappe.ValidationError):
			self._make_segment("_Test Segment Too Many Groups", {"groups": groups})

	# ------------------------------------------------------------ saved segment matches seeded contacts

	def test_saved_segment_matches_seeded_contacts(self):
		filters = {
			"groups": [{"logic": "AND", "conditions": [{"field": "lifecycle_stage", "operator": "=", "value": "MQL"}]}]
		}
		segment = self._make_segment("_Test Segment MQL", filters)
		matches = get_matching_contact_names(segment.filters)
		self.assertIn(self.contacts[1], matches)
		self.assertNotIn(self.contacts[0], matches)

	# ------------------------------------------------------------ Phase 2: preview API + permissions

	def test_preview_draft_filters_matches_saved_segment(self):
		filters = {
			"groups": [{"logic": "AND", "conditions": [{"field": "lifecycle_stage", "operator": "=", "value": "MQL"}]}]
		}
		segment = self._make_segment("_Test Segment Preview Draft", filters)

		draft_result = preview_segment(filters=filters, page_length=50)
		saved_result = preview_segment(segment=segment.name, page_length=50)

		self.assertEqual(draft_result["total"], saved_result["total"])
		self.assertEqual({c["name"] for c in draft_result["contacts"]}, {c["name"] for c in saved_result["contacts"]})

	def test_preview_draft_filters_rejects_non_allowlisted_field(self):
		filters = {
			"groups": [{"logic": "AND", "conditions": [{"field": "email", "operator": "=", "value": "x@example.com"}]}]
		}
		with self.assertRaises(frappe.ValidationError):
			preview_segment(filters=filters)

	def test_preview_pagination(self):
		filters = {
			"groups": [{"logic": "AND", "conditions": [{"field": "is_opted_out", "operator": "in", "value": [0, 1]}]}]
		}
		result = preview_segment(filters=filters, start=0, page_length=2)
		self.assertGreaterEqual(result["total"], 4)
		self.assertEqual(len(result["contacts"]), 2)

	def test_preview_private_segment_visible_to_owner(self):
		owner_email = self._make_user("_Test Segment Owner")
		frappe.set_user(owner_email)
		try:
			filters = {
				"groups": [
					{"logic": "AND", "conditions": [{"field": "lifecycle_stage", "operator": "=", "value": "Lead"}]}
				]
			}
			segment = frappe.get_doc({"doctype": "CRM Segment", "title": "_Test Segment Private", "filters": filters})
			segment.insert()
			result = preview_segment(segment=segment.name)
			self.assertGreaterEqual(result["total"], 1)
			self.assertIn(self.contacts[0], {c["name"] for c in result["contacts"]})
		finally:
			frappe.set_user("Administrator")

	def test_preview_private_segment_denied_to_non_owner(self):
		owner_email = self._make_user("_Test Segment Owner2")
		other_email = self._make_user("_Test Segment Other")

		frappe.set_user(owner_email)
		filters = {
			"groups": [{"logic": "AND", "conditions": [{"field": "lifecycle_stage", "operator": "=", "value": "Lead"}]}]
		}
		segment = frappe.get_doc({"doctype": "CRM Segment", "title": "_Test Segment Private2", "filters": filters})
		segment.insert()

		frappe.set_user(other_email)
		try:
			with self.assertRaises(frappe.PermissionError):
				preview_segment(segment=segment.name)
		finally:
			frappe.set_user("Administrator")

	def test_preview_public_segment_visible_to_other_users(self):
		owner_email = self._make_user("_Test Segment PubOwner")
		other_email = self._make_user("_Test Segment PubOther")

		frappe.set_user(owner_email)
		filters = {
			"groups": [{"logic": "AND", "conditions": [{"field": "lifecycle_stage", "operator": "=", "value": "Lead"}]}]
		}
		segment = frappe.get_doc(
			{"doctype": "CRM Segment", "title": "_Test Segment Public", "is_public": 1, "filters": filters}
		)
		segment.insert()

		frappe.set_user(other_email)
		try:
			result = preview_segment(segment=segment.name)
			self.assertGreaterEqual(result["total"], 1)
			self.assertIn(self.contacts[0], {c["name"] for c in result["contacts"]})
		finally:
			frappe.set_user("Administrator")

	# ------------------------------------------------------------ Phase 3: campaign attach backend

	def test_attach_creates_touchpoints_for_matches(self):
		campus = self._make_campus("_Test Segment Attach Campus")
		campaign = self._make_campaign("_Test Segment Attach Campaign", campus)
		filters = {
			"groups": [{"logic": "AND", "conditions": [{"field": "lifecycle_stage", "operator": "=", "value": "Lead"}]}]
		}
		segment = self._make_segment("_Test Segment Attach", filters)

		result = attach_segment_to_campaign(segment.name, campaign)

		self.assertFalse(result["failed"])
		self.assertEqual(result["created"], 1)
		touchpoint = frappe.db.get_value(
			"CRM Campaign Touchpoint",
			{"crm_campaign": campaign, "crm_contact": self.contacts[0]},
			["source", "crm_segment"],
			as_dict=True,
		)
		self.assertEqual(touchpoint.source, "Segment")
		self.assertEqual(touchpoint.crm_segment, segment.name)

	def test_attach_reattach_creates_zero_additional_rows(self):
		campus = self._make_campus("_Test Segment Reattach Campus")
		campaign = self._make_campaign("_Test Segment Reattach Campaign", campus)
		filters = {
			"groups": [{"logic": "AND", "conditions": [{"field": "lifecycle_stage", "operator": "=", "value": "MQL"}]}]
		}
		segment = self._make_segment("_Test Segment Reattach", filters)

		first = attach_segment_to_campaign(segment.name, campaign)
		second = attach_segment_to_campaign(segment.name, campaign)

		self.assertEqual(first["created"], 1)
		self.assertEqual(second["created"], 0)
		self.assertEqual(second["skipped_same_segment"], 1)

	def test_attach_then_edit_segment_leaves_existing_touchpoints_unchanged(self):
		campus = self._make_campus("_Test Segment Retro Campus")
		campaign = self._make_campaign("_Test Segment Retro Campaign", campus)
		filters = {
			"groups": [{"logic": "AND", "conditions": [{"field": "lifecycle_stage", "operator": "=", "value": "Lead"}]}]
		}
		segment = self._make_segment("_Test Segment Retro", filters)

		attach_segment_to_campaign(segment.name, campaign)
		before = frappe.get_all(
			"CRM Campaign Touchpoint",
			filters={"crm_campaign": campaign},
			fields=["name", "crm_contact", "source", "crm_segment"],
		)

		segment.reload()
		segment.filters = {
			"groups": [{"logic": "AND", "conditions": [{"field": "lifecycle_stage", "operator": "=", "value": "Lost"}]}]
		}
		segment.save()

		after = frappe.get_all(
			"CRM Campaign Touchpoint",
			filters={"crm_campaign": campaign},
			fields=["name", "crm_contact", "source", "crm_segment"],
		)
		self.assertEqual(before, after)

	def test_attach_skips_contact_with_existing_manual_touchpoint(self):
		campus = self._make_campus("_Test Segment SkipOther Campus")
		campaign = self._make_campaign("_Test Segment SkipOther Campaign", campus)
		frappe.get_doc(
			{
				"doctype": "CRM Campaign Touchpoint",
				"crm_campaign": campaign,
				"crm_contact": self.contacts[0],
				"source": "Manual",
			}
		).insert(ignore_permissions=True)

		filters = {
			"groups": [{"logic": "AND", "conditions": [{"field": "lifecycle_stage", "operator": "=", "value": "Lead"}]}]
		}
		segment = self._make_segment("_Test Segment SkipOther", filters)

		result = attach_segment_to_campaign(segment.name, campaign)
		self.assertEqual(result["created"], 0)
		self.assertEqual(result["skipped_other_source"], 1)

	def test_delete_segment_with_touchpoints_is_blocked(self):
		campus = self._make_campus("_Test Segment DeleteBlock Campus")
		campaign = self._make_campaign("_Test Segment DeleteBlock Campaign", campus)
		filters = {
			"groups": [{"logic": "AND", "conditions": [{"field": "lifecycle_stage", "operator": "=", "value": "Lead"}]}]
		}
		segment = self._make_segment("_Test Segment DeleteBlock", filters)
		attach_segment_to_campaign(segment.name, campaign)

		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("CRM Segment", segment.name)

	# ------------------------------------------------------------ Phase 6: batching under load / partial failure

	def test_attach_batches_large_volume_without_drops_or_duplicates(self):
		"""Spans several batches (ATTACH_BATCH_SIZE patched down to 2) with a
		match count that isn't a multiple of the batch size, to exercise the
		boundary between batches."""
		campus = self._make_campus("_Test Segment Batch Campus")
		campaign = self._make_campaign("_Test Segment Batch Campaign", campus)
		extra_contacts = [
			self._make_contact(f"Batch{i}", lifecycle_stage="Lead", is_opted_out=0) for i in range(6)
		]
		filters = {
			"groups": [{"logic": "AND", "conditions": [{"field": "lifecycle_stage", "operator": "=", "value": "Lead"}]}]
		}
		segment = self._make_segment("_Test Segment Batch", filters)
		expected_matches = get_matching_contact_names(segment.filters)
		self.assertEqual(len(expected_matches), len(extra_contacts) + 1)  # + seeded contact A

		with patch.object(segment_api, "ATTACH_BATCH_SIZE", 2):
			result = segment_api.attach_segment_to_campaign(segment.name, campaign)

		self.assertFalse(result["failed"])
		self.assertEqual(result["created"], len(expected_matches))
		touchpoints = frappe.get_all(
			"CRM Campaign Touchpoint", filters={"crm_campaign": campaign}, pluck="crm_contact"
		)
		self.assertEqual(len(touchpoints), len(set(touchpoints)))
		self.assertEqual(set(touchpoints), expected_matches)

	def test_attach_mid_batch_failure_reports_partial_and_reruns_cleanly(self):
		"""One row in the last batch fails to insert. Earlier committed batches
		must stay committed, the failing batch's rows must not be partially
		persisted, counts must be accurate, and re-running must finish the
		remaining rows without duplicating anything already committed."""
		campus = self._make_campus("_Test Segment Fail Campus")
		campaign = self._make_campaign("_Test Segment Fail Campaign", campus)
		extra_contacts = [
			self._make_contact(f"Fail{i}", lifecycle_stage="Lead", is_opted_out=0) for i in range(3)
		]
		filters = {
			"groups": [{"logic": "AND", "conditions": [{"field": "lifecycle_stage", "operator": "=", "value": "Lead"}]}]
		}
		segment = self._make_segment("_Test Segment Fail", filters)
		expected_matches = sorted(get_matching_contact_names(segment.filters))
		self.assertEqual(len(expected_matches), len(extra_contacts) + 1)  # + seeded contact A
		failing_contact = expected_matches[-1]

		original_get_doc = frappe.get_doc

		def flaky_get_doc(*args, **kwargs):
			arg = args[0] if args else kwargs.get("doc")
			if (
				isinstance(arg, dict)
				and arg.get("doctype") == "CRM Campaign Touchpoint"
				and arg.get("crm_contact") == failing_contact
			):
				raise frappe.ValidationError("Simulated batch failure")
			return original_get_doc(*args, **kwargs)

		with patch.object(segment_api, "ATTACH_BATCH_SIZE", 2), patch.object(
			segment_api.frappe, "get_doc", side_effect=flaky_get_doc
		):
			result = segment_api.attach_segment_to_campaign(segment.name, campaign)

		self.assertTrue(result["failed"])
		touchpoints_after_failure = frappe.get_all(
			"CRM Campaign Touchpoint", filters={"crm_campaign": campaign}, pluck="crm_contact"
		)
		self.assertLess(result["created"], len(expected_matches))
		self.assertEqual(result["created"], len(touchpoints_after_failure))
		self.assertEqual(len(touchpoints_after_failure), len(set(touchpoints_after_failure)))
		self.assertNotIn(failing_contact, touchpoints_after_failure)
		# The failing contact's batch-mate (same 2-row batch, ATTACH_BATCH_SIZE=2)
		# must also be absent — proof the whole batch rolled back, not just the
		# one row that raised.
		batch_mate = expected_matches[-2]
		self.assertNotIn(batch_mate, touchpoints_after_failure)
		# Earlier, unrelated batches must stay committed.
		for contact in expected_matches[:-2]:
			self.assertIn(contact, touchpoints_after_failure)

		# Re-run without the flakiness: remaining rows complete, nothing duplicated.
		result2 = attach_segment_to_campaign(segment.name, campaign)
		touchpoints_final = frappe.get_all(
			"CRM Campaign Touchpoint", filters={"crm_campaign": campaign}, pluck="crm_contact"
		)
		self.assertFalse(result2["failed"])
		self.assertEqual(len(touchpoints_final), len(set(touchpoints_final)))
		self.assertEqual(set(touchpoints_final), set(expected_matches))

	# ------------------------------------------------------------ condition validation details

	def test_condition_operator_not_allowed_for_fieldtype_rejected(self):
		filters = {
			"groups": [{"logic": "AND", "conditions": [{"field": "is_opted_out", "operator": "in", "value": [0]}]}]
		}
		with self.assertRaises(frappe.ValidationError):
			validate_segment_filters(filters)

	def test_condition_in_operator_requires_nonempty_list(self):
		filters = {
			"groups": [{"logic": "AND", "conditions": [{"field": "lifecycle_stage", "operator": "in", "value": []}]}]
		}
		with self.assertRaises(frappe.ValidationError):
			validate_segment_filters(filters)

	def test_condition_check_field_rejects_non_boolean_value(self):
		filters = {
			"groups": [{"logic": "AND", "conditions": [{"field": "is_opted_out", "operator": "=", "value": "yes"}]}]
		}
		with self.assertRaises(frappe.ValidationError):
			validate_segment_filters(filters)

	def test_condition_cap_enforced(self):
		conditions = [
			{"field": "is_opted_out", "operator": "=", "value": 0}
			for _ in range(segment_api.MAX_CONDITIONS_PER_GROUP + 1)
		]
		filters = {"groups": [{"logic": "AND", "conditions": conditions}]}
		with self.assertRaises(frappe.ValidationError):
			validate_segment_filters(filters)

	# ------------------------------------------------------------ endpoint edge cases

	def test_get_segment_fields_matches_allowlist(self):
		fields = segment_api.get_segment_fields()
		fieldnames = {f["fieldname"] for f in fields}
		self.assertEqual(fieldnames, set(segment_api.ALLOWED_SEGMENT_FIELDS.keys()))

	def test_preview_requires_segment_or_filters(self):
		with self.assertRaises(frappe.ValidationError):
			preview_segment()

	def test_preview_page_length_clamped_to_max(self):
		filters = {
			"groups": [{"logic": "AND", "conditions": [{"field": "is_opted_out", "operator": "in", "value": [0, 1]}]}]
		}
		result = preview_segment(filters=filters, page_length=segment_api.MAX_PREVIEW_PAGE_LENGTH + 50)
		self.assertEqual(result["page_length"], segment_api.MAX_PREVIEW_PAGE_LENGTH)

	def test_attach_denied_for_role_without_campaign_or_segment_access(self):
		"""Promoter-PR has no DocPerm row on CRM Segment and read-only on CRM
		Campaign, so it must be rejected before any Touchpoint is created."""
		campus = self._make_campus("_Test Segment Perm Campus")
		campaign = self._make_campaign("_Test Segment Perm Campaign", campus)
		filters = {
			"groups": [{"logic": "AND", "conditions": [{"field": "lifecycle_stage", "operator": "=", "value": "Lead"}]}]
		}
		segment = self._make_segment("_Test Segment Perm", filters)

		limited_email = self._make_user("_Test Segment Limited", roles=("Promoter-PR",))
		frappe.set_user(limited_email)
		try:
			with self.assertRaises(frappe.PermissionError):
				attach_segment_to_campaign(segment.name, campaign)
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(frappe.db.count("CRM Campaign Touchpoint", {"crm_campaign": campaign}), 0)
