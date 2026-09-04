from contextlib import contextmanager
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import director_next_best_action as nba
from crm.fcrm import student_decision as sd


def _row(**overrides):
	base = {
		"name": "ACT-2026-0001",
		"student": "STU-1",
		"contact": "CON-1",
		"action_type": "CALL",
		"objective": "Gọi phụ huynh xác nhận nguyện vọng",
		"state": "pending",
		"priority": "medium",
		"plan_rank": 1,
		"due_at": None,
		"action_owner": None,
		"source_context_revision": 7,
		"evidence_references": ["EV-1", "EV-2"],
		"package_seed": {"talking_points": ["Chốt lịch tư vấn"]},
		"action_revision": 3,
		"decision_revision": 2,
		"creation": "2026-09-01 08:00:00",
		"modified": "2026-09-01 08:00:00",
	}
	base.update(overrides)
	return frappe._dict(base)


class TestDirectorNextBestActionMappers(FrappeTestCase):
	def test_priority_follows_plan_rank_then_falls_back_to_priority_field(self):
		self.assertEqual(nba._priority_of(_row(plan_rank=1)), "high")
		self.assertEqual(nba._priority_of(_row(plan_rank=2)), "medium")
		self.assertEqual(nba._priority_of(_row(plan_rank=3)), "low")
		self.assertEqual(nba._priority_of(_row(plan_rank=0, priority="high")), "high")

	def test_status_from_due_at(self):
		now = frappe.utils.get_datetime("2026-09-01 12:00:00")
		self.assertEqual(nba._status_of(_row(due_at=None), now), "soon")
		self.assertEqual(nba._status_of(_row(due_at="2026-08-30 09:00:00"), now), "overdue")
		self.assertEqual(nba._status_of(_row(due_at="2026-09-01 18:00:00"), now), "today")
		self.assertEqual(nba._status_of(_row(due_at="2026-09-05 09:00:00"), now), "soon")

	def test_control_level_covers_all_eleven_v2_types(self):
		policy_types = {t for row in nba.STATIC_CONTROL_POLICY["rows"] for t in row["actionTypes"]}
		self.assertEqual(policy_types, set(nba._CONTROL_LEVEL_BY_TYPE))
		self.assertEqual(len(nba._CONTROL_LEVEL_BY_TYPE), 11)
		for row in nba.STATIC_CONTROL_POLICY["rows"]:
			for action_type in row["actionTypes"]:
				self.assertEqual(nba._CONTROL_LEVEL_BY_TYPE[action_type], row["level"])

	def test_item_mapping_does_not_fabricate_probability_or_confidence_source(self):
		lookups = {
			"students": {"STU-1": {"student_name": "Nguyễn Văn An", "high_school": "HS-1", "interest_level": "Cao"}},
			"schools": {"HS-1": "THPT Trưng Vương"},
			"majors": {},
			"owners": {},
		}
		now = frappe.utils.get_datetime("2026-09-01 12:00:00")
		item = nba._map_item(_row(), lookups, now)

		self.assertEqual(item["id"], "ACT-2026-0001")
		self.assertEqual(item["studentName"], "Nguyễn Văn An")
		self.assertEqual(item["initials"], "VA")
		self.assertEqual(item["school"], "THPT Trưng Vương")
		self.assertEqual(item["priority"], "high")
		self.assertEqual(item["controlLevel"], "review")
		self.assertEqual(item["state"], "proposed")
		self.assertEqual(item["version"], 2)
		self.assertEqual(item["evidence"], ["EV-1", "EV-2"])
		self.assertEqual(item["talkingPoints"], ["Chốt lịch tư vấn"])
		self.assertIsNone(item["currentProbability"])
		self.assertIsNone(item["projectedProbability"])
		self.assertIsNone(item["schoolId"])

	def test_camelize_keys_transforms_only_top_level_keys(self):
		out = nba._camelize_keys(
			{"talking_points": ["a"], "desired_outcome": "x", "objective": "o", "nested_dict": {"keep_me": 1}}
		)
		self.assertEqual(
			set(out), {"talkingPoints", "desiredOutcome", "objective", "nestedDict"}
		)
		self.assertEqual(out["nestedDict"], {"keep_me": 1})

	def test_item_mapping_surfaces_typed_package_and_rationale(self):
		lookups = {"students": {}, "schools": {}, "majors": {}, "owners": {}}
		now = frappe.utils.get_datetime("2026-09-01 12:00:00")
		row = _row(
			action_type="DOCUMENT_REQUEST",
			package_seed={
				"package_version": "action-package:v2",
				"objective": "Yêu cầu bổ sung CCCD",
				"missing_documents": ["CCCD"],
				"deadline": "Còn 2 ngày",
				"rationale": {
					"why_now": "Hạn nộp còn 2 ngày",
					"approach": "Gửi tin nhắn kèm checklist",
					"expected_outcome": "Nhận đủ giấy tờ trước hạn",
					"evidence_ref_ids": ["EV-1"],
				},
			},
		)
		item = nba._map_item(row, lookups, now)

		self.assertEqual(item["actionType"], "DOCUMENT_REQUEST")
		self.assertEqual(item["disposition"], "ACT")
		self.assertEqual(item["packageSeed"]["missingDocuments"], ["CCCD"])
		self.assertEqual(item["packageSeed"]["deadline"], "Còn 2 ngày")
		self.assertNotIn("rationale", item["packageSeed"])
		self.assertEqual(item["whyNow"], "Hạn nộp còn 2 ngày")
		self.assertEqual(item["approach"], "Gửi tin nhắn kèm checklist")
		self.assertEqual(item["expectedOutcome"], "Nhận đủ giấy tờ trước hạn")
		self.assertEqual(item["evidenceRefIds"], ["EV-1"])

	def test_item_mapping_strips_pointer_fields_from_the_package_seed(self):
		lookups = {"students": {}, "schools": {}, "majors": {}, "owners": {}}
		now = frappe.utils.get_datetime("2026-09-01 12:00:00")
		row = _row(
			action_type="EMAIL",
			package_seed={
				"subject": "Bước tiếp theo cho hồ sơ của bạn",
				"body": "Nội dung thư",
				"recipient_ref": "phuhuynh@example.com",
				"template_version": "EmailPackageV1",
			},
		)
		seed = nba._map_item(row, lookups, now)["packageSeed"]

		self.assertEqual(set(seed), {"subject", "body"})
		self.assertNotIn("recipientRef", seed)
		self.assertNotIn("templateVersion", seed)

	def test_item_mapping_tolerates_a_non_dict_package_seed(self):
		lookups = {"students": {}, "schools": {}, "majors": {}, "owners": {}}
		now = frappe.utils.get_datetime("2026-09-01 12:00:00")
		item = nba._map_item(_row(package_seed=["not", "a", "dict"]), lookups, now)

		self.assertIsNone(item["packageSeed"])
		self.assertEqual(item["talkingPoints"], [])

	def test_item_mapping_tolerates_a_bare_package_without_rationale(self):
		lookups = {"students": {}, "schools": {}, "majors": {}, "owners": {}}
		now = frappe.utils.get_datetime("2026-09-01 12:00:00")
		item = nba._map_item(_row(), lookups, now)

		self.assertEqual(item["actionType"], "CALL")
		self.assertEqual(item["packageSeed"], {"talkingPoints": ["Chốt lịch tư vấn"]})
		self.assertIsNone(item["whyNow"])
		self.assertIsNone(item["approach"])
		self.assertIsNone(item["expectedOutcome"])
		self.assertEqual(item["evidenceRefIds"], [])

	def test_status_buckets_shares_sum_to_a_sane_range(self):
		buckets = nba._status_buckets({"all": 4, "urgent": 2, "today": 1, "overdue": 1, "soon": 2})
		self.assertEqual([b["id"] for b in buckets], ["within-sla", "due-soon", "overdue"])
		for bucket in buckets:
			self.assertIn(bucket["tone"], {"success", "warning", "error"})
			self.assertGreaterEqual(bucket["share"], 0)


class TestDirectorNextBestActionEnvelope(FrappeTestCase):
	def test_envelope_has_all_five_blocks_with_real_rows(self):
		queue_rows = [_row(), _row(name="ACT-2026-0002", plan_rank=2, action_type="PARENT_CONTACT", state="deferred")]

		def fake_get_list(doctype, **kwargs):
			if doctype == "CRM Student" and kwargs.get("filters", {}).get("admission_year"):
				return [{"name": "STU-1"}]
			if doctype == "CRM Student":
				return [{"name": "STU-1", "student_name": "Nguyễn Văn An", "high_school": "HS-1", "major": None, "interest_level": "Cao"}]
			if doctype == "CRM Action" and kwargs.get("fields") == ["action_type", "state"]:
				return [{"action_type": "CALL", "state": "completed"}, {"action_type": "CALL", "state": "pending"}]
			if doctype == "CRM Action":
				return list(queue_rows)
			if doctype == "CRM High School":
				return [{"name": "HS-1", "school_name": "THPT Trưng Vương"}]
			return []

		with patch.object(nba, "require_director_access", return_value={"user": "director@example.com"}), patch.object(
			nba, "resolve_admission_year", return_value="2026"
		), patch("frappe.get_list", side_effect=fake_get_list):
			result = nba.get_director_next_best_action(admissionYear="2026", page=1, pageSize=20)

		self.assertEqual(set(result), {"meta", "queue", "sla", "outcomes", "controlPolicy"})
		self.assertEqual(result["meta"]["admissionYear"], 2026)
		self.assertEqual(result["meta"]["policyVersion"], nba.POLICY_VERSION)
		self.assertEqual(len(result["queue"]["actions"]), 2)
		self.assertEqual(result["queue"]["actions"][0]["priority"], "high")
		self.assertEqual(result["queue"]["actions"][1]["priority"], "medium")
		self.assertEqual(result["queue"]["pagination"]["total"], 2)
		self.assertFalse(result["queue"]["pagination"]["hasNext"])
		self.assertEqual(result["outcomes"]["rows"][0]["submitted"], 2)
		self.assertEqual(result["outcomes"]["rows"][0]["executed"], 1)
		self.assertEqual(result["outcomes"]["rows"][0]["transitionRate"], 50.0)
		self.assertEqual(result["controlPolicy"]["version"], nba.POLICY_VERSION)
		# Metrics are descriptive, never a causal or predictive claim.
		self.assertEqual(result["meta"]["metricKind"], nba.METRIC_KIND_OBSERVATIONAL)
		self.assertTrue(result["meta"]["metricDisclaimer"])
		self.assertEqual(result["outcomes"]["metricKind"], nba.METRIC_KIND_OBSERVATIONAL)

	def test_urgent_filter_keeps_only_high_or_overdue(self):
		rows = [
			_row(name="A1", plan_rank=1),
			_row(name="A2", plan_rank=2, due_at="2030-01-01 09:00:00"),
			_row(name="A3", plan_rank=3, due_at="2020-01-01 09:00:00"),
		]

		def fake_get_list(doctype, **kwargs):
			if doctype == "CRM Student" and kwargs.get("filters", {}).get("admission_year"):
				return [{"name": "STU-1"}]
			if doctype == "CRM Student":
				return [{"name": "STU-1", "student_name": "An", "high_school": None, "major": None, "interest_level": None}]
			if doctype == "CRM Action" and kwargs.get("fields") == ["action_type", "state"]:
				return []
			if doctype == "CRM Action":
				return list(rows)
			return []

		with patch.object(nba, "require_director_access", return_value={}), patch.object(
			nba, "resolve_admission_year", return_value="2026"
		), patch("frappe.get_list", side_effect=fake_get_list):
			result = nba.get_director_next_best_action(queueFilter="urgent")

		ids = {action["id"] for action in result["queue"]["actions"]}
		self.assertEqual(ids, {"A1", "A3"})

	def test_queue_defaults_to_a_single_page_of_eight(self):
		rows = [_row(name=f"A{index:02d}", plan_rank=2) for index in range(14)]

		def fake_get_list(doctype, **kwargs):
			if doctype == "CRM Student" and kwargs.get("filters", {}).get("admission_year"):
				return [{"name": "STU-1"}]
			if doctype == "CRM Student":
				return [{"name": "STU-1", "student_name": "An", "high_school": None, "major": None, "interest_level": None}]
			if doctype == "CRM Action" and kwargs.get("fields") == ["action_type", "state"]:
				return []
			if doctype == "CRM Action":
				return list(rows)
			return []

		with patch.object(nba, "require_director_access", return_value={}), patch.object(
			nba, "resolve_admission_year", return_value="2026"
		), patch("frappe.get_list", side_effect=fake_get_list):
			result = nba.get_director_next_best_action()

		pagination = result["queue"]["pagination"]
		self.assertEqual(pagination["pageSize"], 8)
		self.assertEqual(pagination["total"], 14)
		self.assertTrue(pagination["hasNext"])
		self.assertEqual(len(result["queue"]["actions"]), 8)


class _FakeAction:
	def __init__(self, decision_revision, action_revision):
		self.name = "ACT-2026-0001"
		self.student = "STU-1"
		self._values = {"decision_revision": decision_revision, "action_revision": action_revision}

	def get(self, key, default=None):
		return self._values.get(key, default)

	def has_permission(self, _perm):
		return True


@contextmanager
def _command_harness(*, decision_revision=2, action_revision=1):
	action = _FakeAction(decision_revision, action_revision)
	calls: dict[str, dict] = {}
	real_get_doc = frappe.get_doc
	real_exists = frappe.db.exists

	def fake_get_doc(doctype, *args, **kwargs):
		if doctype == "CRM Action":
			return action
		return real_get_doc(doctype, *args, **kwargs)

	def fake_exists(doctype, *args, **kwargs):
		if doctype == "CRM Action":
			return True
		return real_exists(doctype, *args, **kwargs)

	def fake_reassign(**kwargs):
		calls["reassign"] = kwargs
		action._values["action_revision"] += 1
		return {"status": "reassigned", "revision": action._values["action_revision"]}

	def fake_decide(**kwargs):
		calls["decide"] = kwargs
		action._values["decision_revision"] += 1
		return {"status": kwargs["status"], "revision": action._values["decision_revision"]}

	with patch.object(nba, "require_director_access", return_value={}), patch(
		"frappe.db.exists", side_effect=fake_exists
	), patch("frappe.get_doc", side_effect=fake_get_doc), patch.object(
		sd, "reassign_action", side_effect=fake_reassign
	), patch.object(sd, "decide_student_task", side_effect=fake_decide), patch.object(
		nba, "_safe_exists", return_value=False
	), patch.object(nba, "_latest_event_id", return_value="EVT-1"):
		yield calls


class TestDirectorNextBestActionCommand(FrappeTestCase):
	def test_assign_routes_to_reassign_action_with_action_revision(self):
		with _command_harness() as calls:
			result = nba.apply_action_command(
				actionId="ACT-2026-0001",
				command="assign",
				assigneeId="STAFF-9",
				expectedVersion=2,
				idempotencyKey="dnba:test-assign",
			)
		self.assertEqual(calls["reassign"]["assignee_staff"], "STAFF-9")
		self.assertEqual(calls["reassign"]["expected_revision"], 1)
		self.assertEqual(result["state"], "assigned")
		self.assertEqual(result["command"], "assign")
		self.assertEqual(result["audit"]["eventId"], "EVT-1")

	def test_defer_routes_to_decide_student_task_with_revisit_at(self):
		with _command_harness() as calls:
			result = nba.apply_action_command(
				actionId="ACT-2026-0001",
				command="defer",
				deferUntil="2026-09-10 09:00:00",
				reason="Chờ phụ huynh phản hồi",
				expectedVersion=2,
				idempotencyKey="dnba:test-defer",
			)
		self.assertEqual(calls["decide"]["status"], "deferred")
		self.assertEqual(calls["decide"]["revisit_at"], "2026-09-10 09:00:00")
		self.assertEqual(result["state"], "deferred")
		self.assertEqual(result["version"], 3)

	def test_dismiss_routes_to_rejected(self):
		with _command_harness() as calls:
			result = nba.apply_action_command(
				actionId="ACT-2026-0001",
				command="dismiss",
				expectedVersion=2,
				idempotencyKey="dnba:test-dismiss",
			)
		self.assertEqual(calls["decide"]["status"], "rejected")
		self.assertTrue(calls["decide"]["decision_reason"])
		self.assertEqual(result["state"], "dismissed")

	def test_stale_expected_version_returns_409(self):
		with _command_harness(decision_revision=5):
			with self.assertRaises(frappe.ValidationError):
				nba.apply_action_command(
					actionId="ACT-2026-0001",
					command="dismiss",
					expectedVersion=2,
					idempotencyKey="dnba:test-stale",
				)

	def test_primitive_forbidden_is_translated(self):
		with _command_harness() as calls:  # noqa: F841
			with patch.object(sd, "decide_student_task", side_effect=sd.StudentDecisionError("FORBIDDEN", "nope")):
				with self.assertRaises(frappe.PermissionError):
					nba.apply_action_command(
						actionId="ACT-2026-0001",
						command="dismiss",
						expectedVersion=2,
						idempotencyKey="dnba:test-forbidden",
					)


def _recommendation_row(**overrides):
	rank = overrides.get("rank", 1)
	base = {
		"name": f"NBA-EVAL-1-{rank}",
		"target_type": "CRM Student",
		"target_id": "STU-1",
		"action": f"ACT-2026-000{rank}",
		"evaluation": "NBA-EVAL-1",
		"ai_payload": {
			"recommendation_key": f"key-{rank}",
			"rank": rank,
			"action_ref": {"action_type": "CALL"},
			"rationale": {"why_now": "Hạn nộp gần"},
		},
		"recommendation_key": f"key-{rank}",
		"rank": rank,
		"recommended_at": "2026-09-03 09:00:00",
		"creation": "2026-09-03 09:00:00",
	}
	base.update(overrides)
	return frappe._dict(base)


class TestDirectorRecommendationsMapper(FrappeTestCase):
	def test_maps_the_review_queue_shape_without_work_item_semantics(self):
		item = nba._map_recommendation(
			_recommendation_row(rank=2),
			{"NBA-EVAL-1": {"name": "NBA-EVAL-1", "disposition": "RECOMMEND", "status": "completed"}},
		)

		self.assertEqual(
			set(item),
			{
				"id",
				"rank",
				"recommendationKey",
				"studentId",
				"actionId",
				"aiPayload",
				"evaluation",
				"generatedAt",
			},
		)
		self.assertEqual(item["rank"], 2)
		self.assertEqual(item["recommendationKey"], "key-2")
		self.assertEqual(item["studentId"], "STU-1")
		self.assertEqual(item["actionId"], "ACT-2026-0002")
		self.assertEqual(
			item["evaluation"], {"id": "NBA-EVAL-1", "disposition": "RECOMMEND", "status": "completed"}
		)
		for forbidden in (
			"state",
			"status",
			"dueAt",
			"dueLabel",
			"assignee",
			"assigneeId",
			"priority",
			"version",
		):
			self.assertNotIn(forbidden, item)

	def test_ai_payload_is_surfaced_verbatim_with_no_key_rewriting(self):
		payload = {
			"recommendation_key": "key-1",
			"rank": 1,
			"talking_points": ["Chốt lịch"],
			"rationale": {"why_now": "Hạn nộp", "evidence_ref_ids": ["EV-1"]},
		}
		item = nba._map_recommendation(_recommendation_row(ai_payload=payload), {})

		self.assertEqual(item["aiPayload"], payload)
		self.assertIn("talking_points", item["aiPayload"])
		self.assertEqual(item["aiPayload"]["rationale"], {"why_now": "Hạn nộp", "evidence_ref_ids": ["EV-1"]})

	def test_missing_parent_evaluation_degrades_to_null_disposition(self):
		item = nba._map_recommendation(_recommendation_row(), {})
		self.assertEqual(item["evaluation"], {"id": "NBA-EVAL-1", "disposition": None, "status": None})

	def test_tolerates_a_stringified_or_non_dict_payload(self):
		self.assertEqual(
			nba._map_recommendation(_recommendation_row(ai_payload='{"rank": 1}'), {})["aiPayload"],
			{"rank": 1},
		)
		self.assertEqual(nba._map_recommendation(_recommendation_row(ai_payload=["x"]), {})["aiPayload"], {})


class TestDirectorRecommendationsReadModel(FrappeTestCase):
	def _run(self, queue_rows, *, admission_year="2026", **kwargs):
		seen: dict[str, dict] = {}

		def fake_get_list(doctype, **call):
			seen[doctype] = call
			if doctype == "CRM Student":
				return [{"name": "STU-1"}]
			if doctype == "CRM Recommendation":
				return list(queue_rows)
			if doctype == "CRM NBA Evaluation":
				return [{"name": "NBA-EVAL-1", "disposition": "RECOMMEND", "status": "completed"}]
			return []

		with patch.object(nba, "require_director_access", return_value={}), patch.object(
			nba, "resolve_admission_year", return_value=admission_year
		), patch("frappe.get_list", side_effect=fake_get_list):
			result = nba.get_director_recommendations(**kwargs)
		return result, seen

	def test_orders_by_rank_ascending_and_projects_each_row(self):
		rows = [_recommendation_row(rank=1), _recommendation_row(rank=2), _recommendation_row(rank=3)]
		result, seen = self._run(rows)

		self.assertEqual(
			seen["CRM Recommendation"]["order_by"], "`rank` asc, recommended_at desc, creation asc"
		)
		self.assertEqual([item["rank"] for item in result["recommendations"]], [1, 2, 3])
		self.assertEqual(result["meta"]["status"], "available")
		self.assertEqual(result["meta"]["count"], 3)
		self.assertEqual(result["meta"]["admissionYear"], 2026)

	def test_only_epoch_rows_are_requested_legacy_rows_are_excluded(self):
		result, seen = self._run([_recommendation_row()])
		self.assertEqual(seen["CRM Recommendation"]["filters"]["evaluation"], ["is", "set"])
		self.assertEqual(seen["CRM Recommendation"]["filters"]["target_type"], "CRM Student")
		self.assertEqual(seen["CRM Recommendation"]["filters"]["target_id"], ["in", ["STU-1"]])
		self.assertEqual(len(result["recommendations"]), 1)

	def test_ai_payload_surfaced_immutable_end_to_end(self):
		payload = {"recommendation_key": "key-1", "rank": 1, "missing_documents": ["CCCD"]}
		result, _ = self._run([_recommendation_row(ai_payload=payload)])
		self.assertEqual(result["recommendations"][0]["aiPayload"], payload)

	def test_no_task_semantics_fields_in_the_envelope(self):
		result, _ = self._run([_recommendation_row()])
		self.assertEqual(set(result), {"meta", "recommendations"})
		self.assertEqual(
			set(result["meta"]),
			{
				"admissionYear",
				"asOf",
				"timezone",
				"status",
				"count",
				"limit",
				"metricKind",
				"metricDisclaimer",
			},
		)
		self.assertEqual(result["meta"]["metricKind"], nba.METRIC_KIND_OBSERVATIONAL)
		item = result["recommendations"][0]
		self.assertNotIn("queue", result)
		for forbidden in (
			"state",
			"dueAt",
			"priority",
			"assigneeId",
			"suggestedAssigneeId",
			"version",
			"controlLevel",
		):
			self.assertNotIn(forbidden, item)

	def test_empty_when_no_epoch_rows_exist(self):
		result, _ = self._run([])
		self.assertEqual(result["recommendations"], [])
		self.assertEqual(result["meta"]["status"], "empty")
		self.assertEqual(result["meta"]["count"], 0)

	def test_permission_failure_is_fail_closed_and_never_reads_rows(self):
		calls: list[str] = []

		def fake_get_list(doctype, **_call):
			calls.append(doctype)
			return []

		with patch.object(
			nba, "require_director_access", side_effect=frappe.PermissionError("nope")
		), patch("frappe.get_list", side_effect=fake_get_list):
			with self.assertRaises(frappe.PermissionError):
				nba.get_director_recommendations(admissionYear="2026")
		self.assertEqual(calls, [])

	def test_limit_is_bounded_and_passed_through(self):
		with self.assertRaises(frappe.ValidationError):
			self._run([_recommendation_row()], limit="999")
		result, seen = self._run([_recommendation_row()], limit="5")
		self.assertEqual(seen["CRM Recommendation"]["limit_page_length"], 5)
		self.assertEqual(result["meta"]["limit"], 5)
