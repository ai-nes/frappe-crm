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
from crm.api.student_classification import create_need, create_tag, transition_need, transition_tag
from crm.api.student_segment import transition_segment


class TestCRMSegment(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.test_branch = self._make_campus("_Test Segment Setup Campus")
		self.segment_need = self._make_term("need")
		self.segment_tag = self._make_term("tag")
		self.contacts = []
		self.contacts.append(
			self._make_contact(
				"A",
				potential="HIGH",
				intent="HIGH",
				branch=self.test_branch,
				needs=[{"need": self.segment_need}],
				tags=[{"tag": self.segment_tag}],
			)
		)
		self.contacts.append(
			self._make_contact(
				"B",
				potential="MEDIUM",
				intent="MEDIUM",
				branch=self.test_branch,
				needs=[{"need": self.segment_need}],
			)
		)
		self.contacts.append(
			self._make_contact(
				"C",
				potential="LOW",
				intent="HIGH",
				branch=self.test_branch,
				needs=[{"need": self.segment_need}],
			)
		)
		self.contacts.append(
			self._make_contact(
				"D",
				potential="LOW",
				intent="LOW",
				branch=self.test_branch,
				needs=[{"need": self.segment_need}],
			)
		)

	def tearDown(self):
		frappe.set_user("Administrator")
		# attach_segment_to_campaign commits each batch; close any remaining test
		# transaction before deleting the linked Student fixtures, otherwise a
		# Frappe test connection can retain a row lock across teardown.
		frappe.db.commit()
		test_campaigns = frappe.db.get_all(
			"CRM Campaign", filters={"title": ["like", "_Test%"]}, pluck="name"
		)
		if test_campaigns:
			for name in frappe.db.get_all(
				"CRM Marketing Engagement", filters={"crm_campaign": ["in", test_campaigns]}, pluck="name"
			):
				frappe.delete_doc("CRM Marketing Engagement", name, force=True)
		for name in frappe.db.get_all("CRM Segment", filters={"title": ["like", "_Test%"]}, pluck="name"):
			frappe.db.delete("CRM Segment", {"name": name})
		for name in test_campaigns:
			frappe.delete_doc("CRM Campaign", name, force=True)
		for name in frappe.db.get_all(
			"CRM Campus", filters={"campus_name": ["like", "_Test%"]}, pluck="name"
		):
			frappe.delete_doc("CRM Campus", name, force=True)
		# Attribution attach commits in batches.  Use a direct bulk delete after
		# dependent touchpoints are gone; delete_doc's row-locking path can race
		# the test connection's just-committed batch and make teardown flaky.
		frappe.db.delete("CRM Lead", {"student_name": ["like", "_Test Segment%"]})
		frappe.db.commit()
		test_students = frappe.db.get_all(
			"CRM Student", filters={"full_name": ["like", "_Test%"]}, pluck="name"
		)
		if test_students:
			for doctype in ("CRM Student Need Assignment", "CRM Student Tag Assignment"):
				frappe.db.delete(doctype, {"parent": ["in", test_students]})
		for name in test_students:
			frappe.delete_doc("CRM Student", name, force=True)
		for doctype in ("CRM Need", "CRM Tag"):
			for name in frappe.db.get_all(
				doctype, filters={"code": ["like", "TEST_SEGMENT_%"]}, pluck="name"
			):
				frappe.db.delete(doctype, {"name": name})
		for name in frappe.db.get_all("User", filters={"first_name": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("User", name, force=True)

	def _make_campus(self, name):
		if frappe.db.exists("CRM Campus", name):
			frappe.delete_doc("CRM Campus", name, force=True)
		doc = frappe.get_doc(
			{"doctype": "CRM Campus", "campus_name": name, "campus_code": "TEST-SEGMENT"}
		)
		doc.insert(ignore_permissions=True)
		return doc.name

	def _make_campaign(self, title, campus):
		if frappe.db.exists("CRM Campaign", title):
			for name in frappe.db.get_all(
				"CRM Marketing Engagement", filters={"crm_campaign": title}, pluck="name"
			):
				frappe.delete_doc("CRM Marketing Engagement", name, force=True)
			frappe.delete_doc("CRM Campaign", title, force=True)
		doc = frappe.get_doc({"doctype": "CRM Campaign", "title": title, "campus": campus})
		doc.insert(ignore_permissions=True)
		return doc.name

	def _make_term(self, kind):
		create = create_need if kind == "need" else create_tag
		transition = transition_need if kind == "need" else transition_tag
		term = create(
			{
				"code": f"TEST_SEGMENT_{kind.upper()}_{frappe.generate_hash(length=8).upper()}",
				"label": f"Test Segment {kind}",
				"group_name": "Test Segment",
			}
		)
		return transition(term["name"], "active", term["revision"])["name"]

	def _scope_condition(self, term=None):
		return {"field": "need", "operator": "in", "value": [term or self.segment_need]}

	def _make_user(self, prefix, roles=("Lead Sale",)):
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

	_next_test_phone = 1

	def _make_contact(self, suffix, **kwargs):
		# phone must satisfy CRMContact._validate_phone_format() (0 + 9 digits, unique).
		# Real Vietnamese mobile numbers never start with two zeros, so a "00"-prefixed
		# counter can't collide with imported production-like data.
		TestCRMSegment._next_test_phone += 1
		phone = "00" + str(TestCRMSegment._next_test_phone).zfill(8)
		if "student" not in kwargs:
			kwargs["student"] = self._make_student(
				suffix, f"09{str(40000000 + TestCRMSegment._next_test_phone).zfill(8)}"
			)
		doc = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"full_name": f"_Test Segment {suffix}",
				"phone": phone,
				**kwargs,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc.name

	def _make_student(self, suffix, phone):
		student_name = f"_Test Segment {suffix} Student"
		if frappe.db.exists("CRM Lead", student_name):
			frappe.delete_doc("CRM Lead", student_name, force=True)
		doc = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"student_name": student_name,
				"phone": phone,
				"processing_status": "PROCESSING",
			}
		)
		previous_flag = getattr(frappe.flags, "student_intake_service", False)
		frappe.flags.student_intake_service = True
		try:
			doc.insert(ignore_permissions=True)
		finally:
			frappe.flags.student_intake_service = previous_flag
		return doc.name

	def _make_segment(self, title, filters):
		doc = frappe.get_doc(
			{
				"doctype": "CRM Segment",
				"title": title,
				"filters": filters,
				"purpose": "Regression test",
				"category": "admission_stage",
			}
		)
		doc.insert(ignore_permissions=True)
		transition_segment(doc.name, "active", doc.revision)
		return doc.reload()

	# ------------------------------------------------------------ OR-of-AND correctness

	def test_two_group_or_of_and_matches_hand_built_query(self):
		filters = {
			"groups": [
				{
					"logic": "AND",
					"conditions": [
						{"field": "potential", "operator": "=", "value": "HIGH"},
						self._scope_condition(),
					],
				},
				{
					"logic": "AND",
					"conditions": [
						{"field": "potential", "operator": "=", "value": "LOW"},
						{"field": "intent", "operator": "=", "value": "HIGH"},
						self._scope_condition(),
					],
				},
			]
		}
		matches = get_matching_contact_names(filters)

		expected = set(
			frappe.get_list(
				"CRM Student",
				filters=[["name", "in", self.contacts]],
				or_filters=[["potential", "=", "HIGH"]],
				pluck="name",
			)
		) | set(
			frappe.get_list(
				"CRM Student",
				filters=[
					["name", "in", self.contacts],
					["potential", "=", "LOW"],
					["intent", "=", "HIGH"],
				],
				pluck="name",
			)
		)

		self.assertEqual(matches & set(self.contacts), expected & set(self.contacts))

	def test_nested_and_or_logic_matches_expected_contacts(self):
		filters = {
			"logic": "AND",
			"groups": [
				{
					"logic": "OR",
					"conditions": [
						{"field": "potential", "operator": "=", "value": "HIGH"},
						{"field": "potential", "operator": "=", "value": "LOW"},
					],
				},
				{
					"logic": "OR",
					"conditions": [
						{"field": "intent", "operator": "=", "value": "HIGH"},
						{"field": "intent", "operator": "=", "value": "MEDIUM"},
					],
				},
			],
		}

		matches = set(get_matching_contact_names(filters)) & set(self.contacts)

		self.assertEqual(matches, {self.contacts[0], self.contacts[2]})

	def test_inner_or_logic_matches_classification_condition_branch(self):
		filters = {
			"groups": [
				{
					"logic": "OR",
					"conditions": [
						{"field": "potential", "operator": "=", "value": "HIGH"},
						{"field": "tag", "operator": "in", "value": [self.segment_tag]},
					],
				}
			]
		}

		matches = set(get_matching_contact_names(filters)) & set(self.contacts)

		self.assertEqual(matches, {self.contacts[0]})

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
			"groups": [
				{
					"logic": "AND",
					"conditions": [{"field": "email", "operator": "=", "value": "x@example.com"}],
				}
			]
		}
		with self.assertRaises(frappe.ValidationError):
			self._make_segment("_Test Segment Bad Field", filters)

	def test_non_allowlisted_field_rejected_at_matcher_directly(self):
		"""The matcher itself must reject, not just Document.validate() — this is
		what makes draft preview (which never calls validate()) safe."""
		filters = {
			"groups": [
				{
					"logic": "AND",
					"conditions": [{"field": "email", "operator": "=", "value": "x@example.com"}],
				}
			]
		}
		with self.assertRaises(frappe.ValidationError):
			get_matching_contact_names(filters)

	def test_group_cap_enforced(self):
		groups = [
			{"logic": "AND", "conditions": [{"field": "potential", "operator": "=", "value": "HIGH"}]}
			for _ in range(11)
		]
		with self.assertRaises(frappe.ValidationError):
			self._make_segment("_Test Segment Too Many Groups", {"groups": groups})

	# ------------------------------------------------------------ saved segment matches seeded contacts

	def test_saved_segment_matches_seeded_contacts(self):
		filters = {
			"groups": [
				{
					"logic": "AND",
					"conditions": [
						{"field": "potential", "operator": "=", "value": "MEDIUM"},
						self._scope_condition(),
					],
				}
			]
		}
		segment = self._make_segment("_Test Segment MQL", filters)
		matches = get_matching_contact_names(segment.filters)
		self.assertIn(self.contacts[1], matches)
		self.assertNotIn(self.contacts[0], matches)

	def test_tag_filter_matches_tag_assignments(self):
		filters = {
			"groups": [
				{
					"logic": "AND",
					"conditions": [{"field": "tag", "operator": "in", "value": [self.segment_tag]}],
				}
			]
		}
		matches = get_matching_contact_names(filters)
		self.assertIn(self.contacts[0], matches)
		self.assertNotIn(self.contacts[1], matches)

	# ------------------------------------------------------------ Phase 2: preview API + permissions

	def test_preview_draft_filters_matches_saved_segment(self):
		filters = {
			"groups": [
				{
					"logic": "AND",
					"conditions": [
						{"field": "potential", "operator": "=", "value": "MEDIUM"},
						self._scope_condition(),
					],
				}
			]
		}
		segment = self._make_segment("_Test Segment Preview Draft", filters)

		draft_result = preview_segment(filters=filters, page_length=50)
		saved_result = preview_segment(segment=segment.name, page_length=50)

		self.assertEqual(draft_result["total"], saved_result["total"])
		self.assertEqual(
			{c["name"] for c in draft_result["contacts"]}, {c["name"] for c in saved_result["contacts"]}
		)

	def test_preview_draft_filters_rejects_non_allowlisted_field(self):
		filters = {
			"groups": [
				{
					"logic": "AND",
					"conditions": [{"field": "email", "operator": "=", "value": "x@example.com"}],
				}
			]
		}
		with self.assertRaises(frappe.ValidationError):
			preview_segment(filters=filters)

	def test_preview_pagination(self):
		filters = {
			"groups": [
				{
					"logic": "AND",
					"conditions": [
						{"field": "potential", "operator": "=", "value": "HIGH"},
						self._scope_condition(),
					],
				},
				{
					"logic": "AND",
					"conditions": [
						{"field": "potential", "operator": "=", "value": "MEDIUM"},
						self._scope_condition(),
					],
				},
				{
					"logic": "AND",
					"conditions": [
						{"field": "potential", "operator": "=", "value": "LOW"},
						self._scope_condition(),
					],
				},
			]
		}
		result = preview_segment(filters=filters, start=0, page_length=2)
		self.assertGreaterEqual(result["total"], 4)
		self.assertEqual(len(result["contacts"]), 2)

	def test_preview_private_segment_visible_to_owner(self):
		owner_email = self._make_user("_Test Segment Owner", roles=("Lead Sale", "System Manager"))
		frappe.set_user(owner_email)
		try:
			filters = {
				"groups": [
					{
						"logic": "AND",
						"conditions": [
							{"field": "potential", "operator": "=", "value": "HIGH"},
							self._scope_condition(),
						],
					}
				]
			}
			segment = frappe.get_doc(
				{"doctype": "CRM Segment", "title": "_Test Segment Private", "filters": filters}
			)
			segment.insert()
			result = preview_segment(segment=segment.name)
			self.assertGreaterEqual(result["total"], 1)
			self.assertIn(self.contacts[0], {c["name"] for c in result["contacts"]})
		finally:
			frappe.set_user("Administrator")

	def test_preview_private_segment_denied_to_non_owner(self):
		owner_email = self._make_user("_Test Segment Owner2", roles=("Lead Sale", "System Manager"))
		other_email = self._make_user("_Test Segment Other")

		frappe.set_user(owner_email)
		filters = {
			"groups": [
				{
					"logic": "AND",
					"conditions": [
						{"field": "potential", "operator": "=", "value": "HIGH"},
						self._scope_condition(),
					],
				}
			]
		}
		segment = frappe.get_doc(
			{"doctype": "CRM Segment", "title": "_Test Segment Private2", "filters": filters}
		)
		segment.insert()

		frappe.set_user(other_email)
		try:
			with self.assertRaises(frappe.PermissionError):
				preview_segment(segment=segment.name)
		finally:
			frappe.set_user("Administrator")

	def test_preview_public_segment_visible_to_other_users(self):
		owner_email = self._make_user("_Test Segment PubOwner", roles=("Lead Sale", "System Manager"))
		other_email = self._make_user("_Test Segment PubOther", roles=("Lead Sale", "System Manager"))

		frappe.set_user(owner_email)
		filters = {
			"groups": [
				{
					"logic": "AND",
					"conditions": [
						{"field": "potential", "operator": "=", "value": "HIGH"},
						self._scope_condition(),
					],
				}
			]
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
			"groups": [
				{
					"logic": "AND",
					"conditions": [
						{"field": "potential", "operator": "=", "value": "HIGH"},
						self._scope_condition(),
					],
				}
			]
		}
		segment = self._make_segment("_Test Segment Attach", filters)

		result = attach_segment_to_campaign(segment.name, campaign)

		self.assertFalse(result["failed"])
		self.assertEqual(result["created"], 1)
		touchpoint = frappe.db.get_value(
			"CRM Marketing Engagement",
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
			"groups": [
				{
					"logic": "AND",
					"conditions": [
						{"field": "potential", "operator": "=", "value": "MEDIUM"},
						self._scope_condition(),
					],
				}
			]
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
			"groups": [
				{
					"logic": "AND",
					"conditions": [
						{"field": "potential", "operator": "=", "value": "HIGH"},
						self._scope_condition(),
					],
				}
			]
		}
		segment = self._make_segment("_Test Segment Retro", filters)

		attach_segment_to_campaign(segment.name, campaign)
		before = frappe.get_all(
			"CRM Marketing Engagement",
			filters={"crm_campaign": campaign},
			fields=["name", "crm_contact", "source", "crm_segment"],
		)

		segment.reload()
		segment.filters = {
			"groups": [
				{
					"logic": "AND",
					"conditions": [
						{"field": "potential", "operator": "=", "value": "LOW"},
						self._scope_condition(),
					],
				}
			]
		}
		segment.save()

		after = frappe.get_all(
			"CRM Marketing Engagement",
			filters={"crm_campaign": campaign},
			fields=["name", "crm_contact", "source", "crm_segment"],
		)
		self.assertEqual(before, after)

	def test_attach_skips_contact_with_existing_manual_touchpoint(self):
		campus = self._make_campus("_Test Segment SkipOther Campus")
		campaign = self._make_campaign("_Test Segment SkipOther Campaign", campus)
		frappe.get_doc(
			{
				"doctype": "CRM Marketing Engagement",
				"engagement_kind": "campaign_touch",
				"reference_doctype": "CRM Campaign",
				"reference_name": campaign,
				"crm_campaign": campaign,
				"crm_contact": self.contacts[0],
				"student": frappe.db.get_value("CRM Student", self.contacts[0], "student"),
				"source": "Manual",
			}
		).insert(ignore_permissions=True)

		filters = {
			"groups": [
				{
					"logic": "AND",
					"conditions": [
						{"field": "potential", "operator": "=", "value": "HIGH"},
						self._scope_condition(),
					],
				}
			]
		}
		segment = self._make_segment("_Test Segment SkipOther", filters)

		result = attach_segment_to_campaign(segment.name, campaign)
		self.assertEqual(result["created"], 0)
		self.assertEqual(result["skipped_other_source"], 1)

	def test_delete_segment_with_touchpoints_is_blocked(self):
		campus = self._make_campus("_Test Segment DeleteBlock Campus")
		campaign = self._make_campaign("_Test Segment DeleteBlock Campaign", campus)
		delete_need = self._make_term("need")
		self._make_contact(
			"DeleteBlock", potential="HIGH", intent="HIGH", branch=campus, needs=[{"need": delete_need}]
		)
		filters = {
			"groups": [
				{
					"logic": "AND",
					"conditions": [
						{"field": "potential", "operator": "=", "value": "HIGH"},
						self._scope_condition(delete_need),
					],
				}
			]
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
		batch_need = self._make_term("need")
		extra_contacts = []
		for i in range(6):
			student = self._make_student(f"Batch{i}", f"09{str(20000000 + i).zfill(8)}")
			extra_contacts.append(
				self._make_contact(
					f"Batch{i}",
					potential="HIGH",
					intent="HIGH",
					branch=campus,
					student=student,
					needs=[{"need": batch_need}],
				)
			)
		filters = {
			"groups": [
				{
					"logic": "AND",
					"conditions": [
						{"field": "potential", "operator": "=", "value": "HIGH"},
						self._scope_condition(batch_need),
					],
				}
			]
		}
		segment = self._make_segment("_Test Segment Batch", filters)
		expected_matches = get_matching_contact_names(segment.filters)
		# The unique Need term scopes the query to this test's own contacts.
		self.assertEqual(expected_matches, set(extra_contacts))

		with patch.object(segment_api, "ATTACH_BATCH_SIZE", 2):
			result = segment_api.attach_segment_to_campaign(segment.name, campaign)

		self.assertFalse(result["failed"])
		self.assertEqual(result["created"], len(expected_matches))
		touchpoints = frappe.get_all(
			"CRM Marketing Engagement", filters={"crm_campaign": campaign}, pluck="crm_contact"
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
		fail_need = self._make_term("need")
		extra_contacts = []
		for i in range(4):
			student = self._make_student(f"Fail{i}", f"09{str(30000000 + i).zfill(8)}")
			extra_contacts.append(
				self._make_contact(
					f"Fail{i}",
					potential="HIGH",
					intent="HIGH",
					branch=campus,
					student=student,
					needs=[{"need": fail_need}],
				)
			)
		filters = {
			"groups": [
				{
					"logic": "AND",
					"conditions": [
						{"field": "potential", "operator": "=", "value": "HIGH"},
						self._scope_condition(fail_need),
					],
				}
			]
		}
		segment = self._make_segment("_Test Segment Fail", filters)
		expected_matches = sorted(get_matching_contact_names(segment.filters))
		# The unique Need term scopes the query to this test's own contacts.
		self.assertEqual(set(expected_matches), set(extra_contacts))
		failing_contact = expected_matches[-1]

		original_get_doc = frappe.get_doc

		def flaky_get_doc(*args, **kwargs):
			arg = args[0] if args else kwargs.get("doc")
			if (
				isinstance(arg, dict)
				and arg.get("doctype") == "CRM Marketing Engagement"
				and arg.get("crm_contact") == failing_contact
			):
				raise frappe.ValidationError("Simulated batch failure")
			return original_get_doc(*args, **kwargs)

		with (
			patch.object(segment_api, "ATTACH_BATCH_SIZE", 2),
			patch.object(segment_api.frappe, "get_doc", side_effect=flaky_get_doc),
		):
			result = segment_api.attach_segment_to_campaign(segment.name, campaign)

		self.assertTrue(result["failed"])
		touchpoints_after_failure = frappe.get_all(
			"CRM Marketing Engagement", filters={"crm_campaign": campaign}, pluck="crm_contact"
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
			"CRM Marketing Engagement", filters={"crm_campaign": campaign}, pluck="crm_contact"
		)
		self.assertFalse(result2["failed"])
		self.assertEqual(len(touchpoints_final), len(set(touchpoints_final)))
		self.assertEqual(set(touchpoints_final), set(expected_matches))

	# ------------------------------------------------------------ condition validation details

	def test_condition_operator_not_allowed_for_fieldtype_rejected(self):
		filters = {
			"groups": [
				{"logic": "AND", "conditions": [{"field": "potential", "operator": "is", "value": "HIGH"}]}
			]
		}
		with self.assertRaises(frappe.ValidationError):
			validate_segment_filters(filters)

	def test_condition_in_operator_requires_nonempty_list(self):
		filters = {
			"groups": [
				{"logic": "AND", "conditions": [{"field": "potential", "operator": "in", "value": []}]}
			]
		}
		with self.assertRaises(frappe.ValidationError):
			validate_segment_filters(filters)

	def test_condition_check_field_rejects_non_boolean_value(self):
		filters = {
			"groups": [
				{"logic": "AND", "conditions": [{"field": "potential", "operator": "=", "value": "yes"}]}
			]
		}
		with self.assertRaises(frappe.ValidationError):
			validate_segment_filters(filters)

	def test_condition_cap_enforced(self):
		conditions = [
			{"field": "potential", "operator": "=", "value": "HIGH"}
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
		self.assertEqual(
			fieldnames,
			{"student_stage", "potential", "intent", "need", "tag"},
		)

	def test_preview_requires_segment_or_filters(self):
		with self.assertRaises(frappe.ValidationError):
			preview_segment()

	def test_preview_page_length_clamped_to_max(self):
		filters = {
			"groups": [
				{
					"logic": "AND",
					"conditions": [
						{"field": "potential", "operator": "=", "value": "HIGH"},
						self._scope_condition(),
					],
				},
				{
					"logic": "AND",
					"conditions": [
						{"field": "potential", "operator": "=", "value": "LOW"},
						self._scope_condition(),
					],
				},
			]
		}
		result = preview_segment(filters=filters, page_length=segment_api.MAX_PREVIEW_PAGE_LENGTH + 50)
		self.assertEqual(result["page_length"], segment_api.MAX_PREVIEW_PAGE_LENGTH)

	def test_attach_denied_for_role_without_campaign_or_segment_access(self):
		"""Marketing has no DocPerm row on CRM Segment and read-only on CRM
		Campaign, so it must be rejected before any Touchpoint is created."""
		campus = self._make_campus("_Test Segment Perm Campus")
		campaign = self._make_campaign("_Test Segment Perm Campaign", campus)
		filters = {
			"groups": [
				{
					"logic": "AND",
					"conditions": [
						{"field": "potential", "operator": "=", "value": "HIGH"},
						self._scope_condition(),
					],
				}
			]
		}
		segment = self._make_segment("_Test Segment Perm", filters)

		limited_email = self._make_user("_Test Segment Limited", roles=("Marketing",))
		frappe.set_user(limited_email)
		try:
			with self.assertRaises(frappe.PermissionError):
				attach_segment_to_campaign(segment.name, campaign)
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(frappe.db.count("CRM Marketing Engagement", {"crm_campaign": campaign}), 0)
