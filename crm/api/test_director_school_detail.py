"""Contract tests for the Director school detail projection."""

from __future__ import annotations

from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from crm.api import director_school_detail as detail


class TestDirectorSchoolDetail(FrappeTestCase):
	def test_detail_returns_nullable_sections_and_approved_contact_fields(self):
		school = {
			"name": "school-1", "province": "province-1", "ward": "ward-1", "school_code": "062", "school_name": "THPT Test",
			"address": None, "school_area": None, "school_tier": None, "boarding_type": None,
			"is_key_account": 0, "latitude": None, "longitude": None,
		}
		stakeholders = [{
			"person": "person-1", "stakeholder_role": "role-1", "position_title": "Hiệu trưởng",
			"relationship_status": "Active", "relationship_score": 60, "last_touch_date": "2026-08-01",
			"next_touch_date": None, "is_primary": 1,
		}]
		sources = {
			"province": {"province_code": "01", "province_name": "Hà Nội", "region": "Bắc"},
			"ward": {"ward_code": "00123", "ward_name": "Phường Test"},
			"snapshot": None, "intelligence": {}, "stakeholders": stakeholders,
			"people": {"person-1": "Người phụ trách"}, "roles": {"role-1": "Ban giám hiệu"}, "activities": [], "activity_types": {},
		}
		with patch.object(detail, "require_director_access", return_value={"roleState": "canonical_profile"}), patch.object(
			detail, "resolve_admission_year", return_value="2026"
		), patch.object(detail, "resolve_school_id", return_value=school), patch.object(
			detail, "_load_supporting_sources", return_value=(sources, set(), set())
		):
			response = detail.get_director_school_detail("01-00123-062", 2026)

		self.assertEqual(response["school"]["id"], "01-00123-062")
		self.assertIsNone(response["potentialScore"])
		self.assertEqual(response["performance"]["year"], [])
		self.assertEqual(response["contacts"][0]["full_name"], "Người phụ trách")
		self.assertNotIn("phone", response["contacts"][0])
		self.assertNotIn("email", response["contacts"][0])
		self.assertEqual(response["dataAvailability"]["sections"]["snapshot"], "unavailable")

	def test_snapshot_selection_uses_requested_order(self):
		self.assertEqual(
			detail._SNAPSHOT_ORDER,
			"snapshot_date desc, recorded_at desc, revision desc, modified desc, name desc",
		)

	def test_activity_projection_excludes_free_text_and_internal_identity(self):
		row = {
			"activity_type": "term-1", "activity_date": "2026-08-01", "scheduled_datetime": None,
			"status": "Completed", "outcome": "Positive", "attendance": 10, "title": "private title",
			"owner_staff": "staff-1", "next_action": "private next action",
		}
		school = {"name": "school-1", "province": "province-1", "ward": "ward-1", "school_code": "062", "school_name": "Test", "is_key_account": 0}
		sources = {
			"province": {"province_code": "01", "province_name": "Hà Nội"}, "ward": {"ward_code": "00123", "ward_name": "Phường Test"},
			"snapshot": None, "intelligence": {}, "stakeholders": [], "people": {}, "roles": {},
			"activities": [row], "activity_types": {"term-1": "Career Talk"},
		}
		item = detail._build_detail(school, sources, set(), set(), "2026")["activities"][0]

		self.assertEqual(item["type"], "Career Talk")
		self.assertNotIn("title", item)
		self.assertNotIn("owner_staff", item)
		self.assertNotIn("next_action", item)

	def test_missing_labels_never_fall_back_to_internal_ids(self):
		school = {"name": "school-1", "school_code": "062", "school_name": "THPT Test", "is_key_account": 0}
		sources = {
			"province": {"province_code": "01", "province_name": "Hà Nội"},
			"ward": {"ward_code": "00123", "ward_name": "Phường Test"},
			"snapshot": None, "intelligence": {},
			"stakeholders": [{"person": "PERSON-INTERNAL", "stakeholder_role": "ROLE-INTERNAL", "relationship_status": "Active"}],
			"people": {}, "roles": {},
			"activities": [{"activity_type": "TYPE-INTERNAL", "status": "Completed"}], "activity_types": {},
		}
		response = detail._build_detail(school, sources, {"people", "roles", "activity_types"}, set(), "2026")
		serialized = detail.frappe.as_json(response)

		self.assertNotIn("PERSON-INTERNAL", serialized)
		self.assertNotIn("ROLE-INTERNAL", serialized)
		self.assertNotIn("TYPE-INTERNAL", serialized)

	def test_missing_snapshot_marks_detail_partial(self):
		school = {"name": "school-1", "school_code": "062", "school_name": "THPT Test", "is_key_account": 0}
		sources = {
			"province": {}, "ward": {}, "snapshot": None, "intelligence": {}, "stakeholders": [],
			"people": {}, "roles": {}, "activities": [], "activity_types": {},
		}
		response = detail._build_detail(school, sources, set(), set(), "2026")

		self.assertEqual(response["status"], "partial")
		self.assertEqual(response["dataAvailability"]["sections"]["snapshot"], "unavailable")

	def test_empty_supporting_collections_are_not_reported_as_source_outage(self):
		school = {"name": "school-1", "school_code": "062", "school_name": "THPT Test", "is_key_account": 0}
		sources = {
			"province": {}, "ward": {}, "snapshot": {}, "intelligence": {}, "stakeholders": [],
			"people": {}, "roles": {}, "activities": [], "activity_types": {},
		}
		response = detail._build_detail(school, sources, set(), set(), "2026")

		self.assertEqual(response["dataAvailability"]["sections"]["relationship"], "available")
		self.assertEqual(response["dataAvailability"]["sections"]["activities"], "available")

	def test_source_revision_changes_with_supporting_source_content_and_state(self):
		school = {"name": "school-1", "school_code": "062", "school_name": "THPT Test", "is_key_account": 0}
		sources = {
			"province": {"province_code": "01", "province_name": "Hà Nội"}, "ward": {"ward_code": "00123", "ward_name": "Phường Test"},
			"snapshot": None, "intelligence": {"potential": {"state": "current", "value": 50}}, "stakeholders": [],
			"people": {}, "roles": {}, "activities": [], "activity_types": {},
		}
		baseline = detail._build_detail(school, sources, set(), set(), "2026")["meta"]["sourceDataRevision"]
		changed_sources = {**sources, "province": {"province_code": "01", "province_name": "Hồ Chí Minh"}}
		changed = detail._build_detail(school, changed_sources, set(), set(), "2026")["meta"]["sourceDataRevision"]
		failed = detail._build_detail(school, sources, {"province"}, set(), "2026")["meta"]["sourceDataRevision"]

		self.assertNotEqual(baseline, changed)
		self.assertNotEqual(baseline, failed)

	def test_supporting_failure_is_partial_and_primary_failure_is_503(self):
		school = {"name": "school-1", "school_code": "062", "school_name": "THPT Test", "canonical_id": "01-00123-062", "is_key_account": 0}
		sources = {
			"province": {}, "ward": {}, "snapshot": None, "intelligence": {}, "stakeholders": [],
			"people": {}, "roles": {}, "activities": [], "activity_types": {},
		}
		with (
			patch.object(detail, "require_director_access", return_value={}),
			patch.object(detail, "resolve_admission_year", return_value="2026"),
			patch.object(detail, "resolve_school_id", return_value=school),
			patch.object(detail, "_load_supporting_sources", return_value=(sources, {"snapshot"}, set())),
		):
			response = detail.get_director_school_detail("01-00123-062", "2026")
		self.assertEqual(response["status"], "partial")
		self.assertEqual(response["school"]["id"], "01-00123-062")

		response_state = {}
		with (
			patch.object(detail, "require_director_access", return_value={}),
			patch.object(detail, "resolve_admission_year", return_value="2026"),
			patch.object(detail, "resolve_school_id", side_effect=detail.SchoolPrimarySourceUnavailable("school")),
			patch.object(detail.frappe.local, "response", response_state),
			self.assertRaises(detail.frappe.ValidationError),
		):
			detail.get_director_school_detail("01-00123-062", "2026")
		self.assertEqual(response_state["http_status_code"], 503)
		self.assertEqual(response_state["error"]["code"], "SCHOOL_DATA_UNAVAILABLE")

	def test_method_has_no_guest_or_permission_bypass(self):
		source = detail.__loader__.get_source(detail.__name__)
		self.assertNotIn("allow_guest=True", source)
		self.assertNotIn("get_all(", source)
		self.assertNotIn("ignore_permissions", source)
		for forbidden in ('"source_note"', '"notes"', '"title"', '"next_action"', '"owner_staff"'):
			self.assertNotIn(forbidden, source)

	def test_unexpected_resolver_defect_is_not_disguised_as_503(self):
		with (
			patch.object(detail, "require_director_access", return_value={}),
			patch.object(detail, "resolve_admission_year", return_value="2026"),
			patch.object(detail, "resolve_school_id", side_effect=RuntimeError("programming defect")),
			self.assertRaisesRegex(RuntimeError, "programming defect"),
		):
			detail.get_director_school_detail("01-00123-062", "2026")

	def test_unexpected_supporting_defect_is_not_disguised_as_partial(self):
		school = {"name": "school-1", "province": "province-1", "ward": "ward-1"}
		with patch.object(detail, "_one", side_effect=RuntimeError("programming defect")), self.assertRaisesRegex(
			RuntimeError, "programming defect"
		):
			detail._load_supporting_sources(school, "2026")
