from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import student_classification as labels
from crm.api import student_segment as segments
from crm.fcrm.segment_rules import validate_filters


class TestStudentSegment(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("classification_test")
		self.campus = frappe.get_doc(
			{"doctype": "CRM Campus", "campus_name": "Classification " + frappe.generate_hash(length=8)}
		).insert()
		self.student = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"full_name": "Classification Test",
				"branch": self.campus.name,
				"phone": "0019827364",
				"enrollment_status": "NEW",
			}
		).insert()
		self.rules = {
			"groups": [{"conditions": [{"field": "branch", "operator": "=", "value": self.campus.name}]}]
		}

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point="classification_test")

	def group(self, **kwargs):
		return segments.create_segment(
			{
				"title": "Classification group",
				"purpose": "Test classification",
				"category": "need",
				"filters": self.rules,
				**kwargs,
			}
		)

	def term(self, kind="need", status="active"):
		create = labels.create_need if kind == "need" else labels.create_tag
		transition = labels.transition_need if kind == "need" else labels.transition_tag
		term = create(
			{
				"code": "TEST_" + frappe.generate_hash(length=12).upper(),
				"label": "Test term",
				"group_name": "Test",
			}
		)
		return transition(term.name, status, term.revision) if status != "draft" else term

	def assign(self, **data):
		self.student.reload()
		return labels.update_classifications(self.student.name, data, str(self.student.modified))

	def user(self):
		return (
			frappe.get_doc(
				{
					"doctype": "User",
					"email": frappe.generate_hash(length=10) + "@example.com",
					"first_name": "Classification permission",
					"send_welcome_email": 0,
					"roles": [{"role": "Sale"}],
				}
			)
			.insert()
			.name
		)

	def test_four_statuses_and_revision_conflicts(self):
		doc = self.group()
		self.assertEqual(doc.status, "draft")
		for status in ("active", "inactive", "active", "archive"):
			doc = segments.transition_segment(doc.name, status, doc.revision)
			self.assertEqual(doc.status, status)
		with self.assertRaisesRegex(frappe.ValidationError, "REVISION_CONFLICT"):
			segments.update_segment(doc.name, {"title": "stale"}, 0)
		with self.assertRaises(frappe.ValidationError):
			segments.update_segment(doc.name, {"title": "Archived edit"}, doc.revision)
		with self.assertRaises(frappe.ValidationError):
			segments.transition_segment(doc.name, "active", doc.revision)

	def test_incomplete_draft_and_raw_lifecycle_bypass(self):
		doc = segments.create_segment({"title": "Incomplete"})
		with self.assertRaises(frappe.ValidationError):
			segments.transition_segment(doc.name, "active", 0)
		raw = frappe.get_doc("CRM Segment", doc.name)
		raw.status = "active"
		with self.assertRaises(frappe.PermissionError):
			raw.save()
		self.assertEqual(frappe.db.get_value("CRM Segment", doc.name, "status"), "draft")

	def test_dynamic_membership_tracks_current_data(self):
		self.rules["groups"][0]["conditions"].append({"field": "potential", "operator": "=", "value": "HIGH"})
		doc = self.group(category="potential")
		self.assertEqual(segments.preview_segment(segment=doc.name)["total"], 0)
		self.assign(potential="HIGH", intent="LOW")
		self.assertEqual(segments.preview_segment(segment=doc.name)["total"], 1)
		self.assign(potential="LOW")
		self.assertEqual(segments.preview_segment(segment=doc.name)["total"], 0)

	def test_static_capture_is_fixed_and_reactivation_preserves_members(self):
		doc = self.group(segment_type="static")
		doc = segments.transition_segment(doc.name, "active", 0)
		self.assertEqual(frappe.db.count("CRM Segment Member", {"segment": doc.name}), 1)
		frappe.db.set_value("CRM Student", self.student.name, "branch", None)
		self.assertEqual(segments.preview_segment(segment=doc.name)["total"], 1)
		doc = segments.transition_segment(doc.name, "inactive", doc.revision)
		doc = segments.transition_segment(doc.name, "active", doc.revision)
		self.assertEqual(frappe.db.count("CRM Segment Member", {"segment": doc.name}), 1)
		with self.assertRaises(frappe.ValidationError):
			segments.update_segment(
				doc.name,
				{
					"filters": {
						"groups": [{"conditions": [{"field": "intent", "operator": "=", "value": "LOW"}]}]
					}
				},
				doc.revision,
			)

	def test_snapshot_failure_is_atomic(self):
		doc = self.group(segment_type="static", purpose="")
		with self.assertRaises(frappe.ValidationError):
			segments.transition_segment(doc.name, "active", 0)
		self.assertEqual(frappe.db.count("CRM Segment Member", {"segment": doc.name}), 0)
		self.assertEqual(frappe.db.get_value("CRM Segment", doc.name, "status"), "draft")
		with patch("crm.fcrm.student_segments.MAX_SNAPSHOT", 0), self.assertRaises(frappe.ValidationError):
			segments.transition_segment(doc.name, "active", 0)

	def test_admin_can_manage_need_and_tag_without_erasing_assignments(self):
		need, tag = self.term(), self.term("tag")
		result = self.assign(needs=[need.name], tags=[tag.name], potential="HIGH", intent="LOW")
		self.assertEqual(result["admission_stage"], "NEW")
		self.assertEqual(result["potential"], "HIGH")
		self.assertEqual(result["intent"], "LOW")
		self.assertEqual(result["needs"][0]["assigned_by"], "Administrator")
		need = labels.update_need(
			need.name, {"label": "Renamed need", "group_name": "Changed group"}, need.revision
		)
		need = labels.transition_need(need.name, "inactive", need.revision)
		self.assertEqual(self.assign(intent="MEDIUM")["needs"][0]["term"], need.name)
		need = labels.transition_need(need.name, "archive", need.revision)
		self.assertEqual(len(labels.get_classifications(self.student.name)["needs"]), 1)
		self.assign(needs=[])
		with self.assertRaises(frappe.ValidationError):
			self.assign(needs=[need.name])

	def test_multiple_needs_and_tag_rules(self):
		a, b, tag = self.term(), self.term(), self.term("tag")
		self.assign(needs=[a.name, b.name], tags=[tag.name])
		self.rules["groups"][0]["conditions"].extend(
			[
				{"field": "need", "operator": "in", "value": [a.name, b.name]},
				{"field": "tag", "operator": "in", "value": [tag.name]},
			]
		)
		self.assertEqual(segments.preview_segment(filters=self.rules)["total"], 1)
		self.rules["groups"][0]["conditions"][-1]["operator"] = "not in"
		self.assertEqual(segments.preview_segment(filters=self.rules)["total"], 0)

	def test_reject_wrong_kind_duplicates_and_inactive_terms(self):
		tag = self.term("tag")
		draft = self.term(status="draft")
		for data in (
			{"needs": [tag.name]},
			{"tags": [tag.name, tag.name]},
			{"needs": [draft.name]},
			{"potential": "VIP"},
		):
			with self.subTest(data=data), self.assertRaises(frappe.ValidationError):
				self.assign(**data)

	def test_generic_student_writes_validate_and_cannot_spoof_provenance(self):
		term = self.term()
		self.student.append("needs", {"need": term.name, "assigned_by": "Guest", "source": "AI"})
		self.student.save(ignore_version=False)
		self.assertEqual(self.student.needs[0].assigned_by, "Administrator")
		self.assertEqual(self.student.needs[0].source, "manual")
		draft = self.term(status="draft")
		self.student.append("needs", {"need": draft.name})
		with self.assertRaises(frappe.ValidationError):
			self.student.save()

	def test_audit_and_student_stale_write(self):
		modified = str(self.student.modified)
		term = self.term()
		self.assign(needs=[term.name])
		self.assertTrue(
			frappe.db.exists("Version", {"ref_doctype": "CRM Student", "docname": self.student.name})
		)
		with self.assertRaisesRegex(frappe.ValidationError, "REVISION_CONFLICT"):
			labels.update_classifications(self.student.name, {"needs": []}, modified)
		self.assertEqual(len(labels.get_classifications(self.student.name)["needs"]), 1)

	def test_staff_cannot_manage_dictionary_or_other_students(self):
		term = self.term()
		user = self.user()
		frappe.set_user(user)
		self.assertTrue(labels.list_terms())
		with self.assertRaises(frappe.PermissionError):
			labels.update_need(term.name, {"label": "Bad edit"}, term.revision)
		with self.assertRaises(frappe.PermissionError):
			labels.update_classifications(self.student.name, {"potential": "LOW"}, str(self.student.modified))
		with self.assertRaises(frappe.PermissionError):
			labels.get_classifications(self.student.name)

	def test_staff_can_assign_owned_student_and_scope_updates_snapshot(self):
		term = self.term()
		user = self.user()
		department = frappe.get_doc(
			{
				"doctype": "CRM Department",
				"department_name": "Classification " + frappe.generate_hash(length=8),
				"campus": self.campus.name,
			}
		).insert()
		staff = frappe.get_doc(
			{
				"doctype": "CRM Staff",
				"full_name": "Classification " + frappe.generate_hash(length=8),
				"user": user,
				"department": department.name,
				"campus": self.campus.name,
			}
		).insert()
		self.student.assigned_to = staff.name
		self.student.save()
		doc = self.group(is_public=1, segment_type="static")
		doc = segments.transition_segment(doc.name, "active", 0)
		frappe.set_user(user)
		result = self.assign(needs=[term.name], intent="HIGH")
		self.assertEqual(result["needs"][0]["assigned_by"], user)
		self.assertEqual(segments.preview_segment(segment=doc.name)["total"], 1)
		frappe.set_user("Administrator")
		self.student.reload()
		self.student.assigned_to = None
		self.student.save()
		frappe.set_user(user)
		self.assertEqual(segments.preview_segment(segment=doc.name)["total"], 0)

	def test_context_revision_changes_with_classification(self):
		self.student.reload()
		before = self.student.student_context_revision
		self.assign(potential="HIGH")
		self.student.reload()
		self.assertGreater(self.student.student_context_revision, before)

	def test_term_referenced_by_rules_cannot_be_deleted(self):
		term = self.term(status="draft")
		self.rules["groups"][0]["conditions"].append(
			{"field": "need", "operator": "in", "value": [term.name]}
		)
		self.group()
		with self.assertRaises(frappe.ValidationError):
			labels.delete_need(term.name, term.revision)

	def test_public_group_never_grants_write_or_student_scope(self):
		doc = self.group(is_public=1, segment_type="static")
		doc = segments.transition_segment(doc.name, "active", 0)
		user = self.user()
		frappe.set_user(user)
		self.assertEqual(segments.get_segment(doc.name).name, doc.name)
		self.assertEqual(segments.preview_segment(segment=doc.name)["total"], 0)
		self.assertNotIn("members", segments.get_segment(doc.name))
		with self.assertRaises(frappe.PermissionError):
			segments.update_segment(doc.name, {"title": "Bad edit"}, doc.revision)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_list("CRM Segment Member")

	def test_reject_structured_classification_tags(self):
		for code in ("APPLIED", "HIGH_POTENTIAL", "HIGH_INTENT", "ENROLLED"):
			with self.subTest(code=code), self.assertRaises(frappe.ValidationError):
				labels.create_tag({"code": code, "label": code, "group_name": "Test"})

	def test_numeric_or_deduplication_and_pagination(self):
		frappe.db.set_value("CRM Student", self.student.name, "latest_score", 75)
		self.rules["groups"][0]["conditions"].append({"field": "latest_score", "operator": ">=", "value": 70})
		self.rules["groups"] *= 2
		result = segments.preview_segment(filters=self.rules, start=0, page_length=1)
		self.assertEqual(result["total"], 1)
		self.assertEqual(result["students"][0]["name"], self.student.name)
		self.assertEqual(segments.preview_segment(filters=self.rules, start=1)["students"], [])
		for value in (-1, "abc", True):
			with self.assertRaises(frappe.ValidationError):
				segments.preview_segment(filters=self.rules, start=value)

	def test_malformed_logic_and_numeric_values(self):
		for value in (float("nan"), float("inf"), 10**500, "70", True):
			with self.subTest(value=str(value)[:20]), self.assertRaises(frappe.ValidationError):
				validate_filters(
					{"groups": [{"conditions": [{"field": "latest_score", "operator": ">", "value": value}]}]}
				)
		self.rules["groups"][0]["logic"] = "OR"
		with self.assertRaises(frappe.ValidationError):
			validate_filters(self.rules)

	def test_only_draft_can_be_deleted(self):
		doc = self.group()
		segments.delete_segment(doc.name, doc.revision)
		self.assertFalse(frappe.db.exists("CRM Segment", doc.name))
		doc = self.group()
		doc = segments.transition_segment(doc.name, "active", 0)
		with self.assertRaises(frappe.ValidationError):
			segments.delete_segment(doc.name, doc.revision)

	def test_catalog_seed_preserves_admin_edits(self):
		from crm.fcrm.classification_catalog import seed_catalog

		name = frappe.db.get_value("CRM Tag", {"code": "VIP"}, "name")
		doc = frappe.get_doc("CRM Tag", name)
		doc.label = "Custom admin label"
		doc.save()
		seed_catalog()
		self.assertEqual(frappe.db.get_value("CRM Tag", name, "label"), "Custom admin label")
