from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import director_students


class TestDirectorStudents(FrappeTestCase):
	def test_student_projection_fields_match_crm_student_schema(self):
		available_fields = {field.fieldname for field in frappe.get_meta("CRM Student").fields}
		available_fields.update({"name", "creation", "modified"})
		missing_fields = set(director_students.STUDENT_FIELDS) - available_fields

		self.assertEqual(missing_fields, set())

	def test_student_order_groups_stage_before_requested_sort(self):
		self.assertEqual(
			director_students._student_order_by("latest_score", "desc"),
			"CASE student_stage WHEN 'New' THEN 1 WHEN 'Attempting' THEN 2 "
			"WHEN 'Connected' THEN 3 WHEN 'Qualified' THEN 4 WHEN 'Disqualified' THEN 5 "
			"ELSE 99 END asc, latest_score desc, name desc",
		)

	def test_computed_student_sort_keeps_workflow_stage_order(self):
		rows = [
			frappe._dict(name="QUALIFIED", student_stage="Qualified"),
			frappe._dict(name="NEW", student_stage="New"),
			frappe._dict(name="CONNECTED", student_stage="Connected"),
			frappe._dict(name="ATTEMPTING", student_stage="Attempting"),
			frappe._dict(name="DISQUALIFIED", student_stage="Disqualified"),
		]
		query = {"sort": "priority", "order": "asc", "page": 1, "page_size": 10}

		with (
			patch.object(
				director_students, "_student_list_reader", return_value=lambda *args, **kwargs: rows
			),
			patch.object(director_students, "_normalize_student_rows", side_effect=lambda value: value),
			patch.object(director_students, "_latest_by_student", return_value={}),
		):
			result = director_students._fetch_computed_sort_rows(query, {}, [])

		self.assertEqual(
			[row["name"] for row in result],
			["NEW", "ATTEMPTING", "CONNECTED", "QUALIFIED", "DISQUALIFIED"],
		)

	def test_query_normalization_accepts_contract_values(self):
		query = director_students._parse_query(
			admissionYear="2026",
			page="2",
			pageSize="50",
			q="  Nguyen  ",
			stage="counselling",
			province="can-tho",
			assignmentStatus="assigned",
			lifecycleStatus="MQL",
			sort="lastActivityAt",
			order="asc",
		)

		self.assertEqual(
			query,
			{
				"admission_year": "2026",
				"page": 2,
				"page_size": 50,
				"query": "Nguyen",
				"stage": "counselling",
				"province": "can-tho",
				"owner_id": None,
				"assignment_status": "assigned",
			"lifecycle_status": "Attempting",
				"sort": "lastActivityAt",
				"order": "asc",
			},
		)

	def test_query_normalization_rejects_invalid_values(self):
		for kwargs in (
			{"page": "0"},
			{"pageSize": "101"},
			{"stage": "unknown"},
			{"assignmentStatus": "unknown"},
			{"lifecycleStatus": "unknown"},
			{"sort": "name"},
			{"order": "sideways"},
			{"admissionYear": "2026.5"},
		):
			with self.subTest(kwargs=kwargs):
				with self.assertRaises(frappe.ValidationError):
					director_students._parse_query(**kwargs)

	def test_student_row_mapping_uses_related_read_models_without_fabricating_values(self):
		row = frappe._dict(
			{
				"name": "ENR-2026-00001",
				"student": "CRMC-2026-00001",
				"student_name": "Nguyễn Minh An",
				"case_key": "CK-ID-2026",
				"high_school": "HS-1",
				"province": "P-1",
				"major": "M-1",
				"student_stage": "Attempting",
				"assessment_status": "confirmed",
				"latest_score": 82,
				"owner_staff": "STAFF-1",
				"ownership_revision": 4,
				"source": "SRC-1",
			}
		)
		item = director_students._map_student_row(
			row,
			lookups={
				"schools": {"HS-1": "THPT Châu Văn Liêm"},
				"provinces": {"P-1": "Cần Thơ"},
				"majors": {"M-1": "Trí tuệ nhân tạo"},
				"owners": {"STAFF-1": "Trần Quốc Bảo"},
				"sources": {"SRC-1": "Career Talk 28/05"},
			},
			activity=frappe._dict(
				interaction_datetime="2026-08-31 09:56:00",
				next_follow_up_action="Gọi phụ huynh về học phí",
			),
			action=frappe._dict(
				objective="Gọi phụ huynh về học phí",
				priority="high",
				due_at="2026-08-31 16:00:00",
			),
			score_history=frappe._dict(score_change=13),
		)

		self.assertEqual(item["id"], "ENR-2026-00001")
		self.assertEqual(item["studentId"], "CRMC-2026-00001")
		self.assertEqual(item["code"], "HS-2026-HCM-000001")
		self.assertEqual(item["initials"], "MA")
		self.assertEqual(item["school"], "THPT Châu Văn Liêm")
		self.assertEqual(item["province"], "Cần Thơ")
		self.assertEqual(item["major"], "Trí tuệ nhân tạo")
		self.assertEqual(item["stage"], "Tư vấn")
		self.assertEqual(item["provinceId"], "P-1")
		self.assertEqual(item["studentStage"], "Attempting")
		self.assertEqual(item["assignmentStatus"], "assigned")
		self.assertEqual(item["stageCode"], "counselling")
		self.assertEqual(item["score"], 82)
		self.assertEqual(item["scoreDelta"], 13)
		self.assertEqual(item["nextAction"], "Gọi phụ huynh về học phí")
		self.assertEqual(item["revision"], 4)
		self.assertEqual(item["priority"], "Cao")
		self.assertEqual(item["priorityCode"], "high")
		self.assertEqual(item["lastActivityAt"], "2026-08-31T09:56:00+07:00")

	def test_student_row_mapping_rejects_missing_ownership_revision(self):
		with self.assertRaises(frappe.ValidationError):
			director_students._map_student_row(frappe._dict(name="ENR-1"))

	def test_list_endpoint_returns_dashboard_envelope_and_server_applied_filters(self):
		row = frappe._dict(name="ENR-1", student_name="Nguyễn Minh An", ownership_revision=4)
		with (
			patch.object(director_students, "_resolve_admission_year", return_value="2026"),
			patch.object(director_students, "_resolve_province", return_value="Cần Thơ"),
			patch.object(director_students, "_count_students", side_effect=[1, 8]),
			patch.object(director_students, "_fetch_student_rows", return_value=[row]),
			patch.object(director_students, "_hydrate_rows", return_value=[{"id": "ENR-1", "revision": 4}]),
			patch.object(
				director_students,
				"_build_summary",
				return_value={
					"trackedStudents": 8,
					"trackedStudentsDeltaPercent": 0.0,
					"highIntentStudents": 1,
					"highIntentRate": 12.5,
					"actionsDueToday": 0,
					"averageEnrollmentProbability": None,
					"averageEnrollmentProbabilityDelta": None,
				},
			),
			patch.object(
				director_students,
				"_build_action_summary",
				return_value={
					"actionsDueToday": 0,
					"decliningInteractionStudents": None,
					"familyReadyStudents": None,
				},
			),
		):
			response = director_students.get_director_students(
				admissionYear="2026",
				page="2",
				pageSize="1",
				q=" nguyen ",
				stage="counselling",
				province="can-tho",
				assignmentStatus="assigned",
				lifecycleStatus="MQL",
				sort="score",
				order="desc",
			)

		self.assertEqual(response["data"], [{"id": "ENR-1", "revision": 4}])
		self.assertEqual(response["meta"]["total"], 1)
		self.assertEqual(response["meta"]["totalAll"], 8)
		self.assertEqual(response["meta"]["page"], 2)
		self.assertEqual(response["meta"]["pageSize"], 1)
		self.assertEqual(response["meta"]["totalPages"], 1)
		self.assertFalse(response["meta"]["hasNextPage"])
		self.assertEqual(
			response["meta"]["filters"],
			{
				"stage": "Tư vấn",
				"assignmentStatus": "assigned",
				"lifecycleStatus": "Attempting",
				"province": "Cần Thơ",
			},
		)
		self.assertEqual(response["meta"]["sort"], {"field": "score", "order": "desc"})

	def test_student_filters_support_assignment_and_lifecycle_status(self):
		query = director_students._parse_query(
			assignmentStatus="Đã phân công",
			lifecycle_status="applicant",
			provinceId="01",
		)

		filters, or_filters = director_students._student_filters(query, "PROVINCE-01")

		self.assertEqual(filters["owner_staff"], ["is", "set"])
		self.assertEqual(filters["student_stage"], "Qualified")
		self.assertEqual(filters["province"], "PROVINCE-01")
		self.assertEqual(or_filters, [])

		unassigned = director_students._parse_query(assignment_status="unassigned")
		unassigned_filters, _ = director_students._student_filters(unassigned, None)
		self.assertEqual(unassigned_filters["owner_staff"], ["is", "set"])
		self.assertEqual(unassigned_filters["name"], "__student_without_owner__")

		all_statuses = director_students._parse_query(assignmentStatus="all", lifecycleStatus="all")
		self.assertIsNone(all_statuses["assignment_status"])
		self.assertIsNone(all_statuses["lifecycle_status"])

	def test_student_filters_match_dashboard_display_code(self):
		query = director_students._parse_query(
			admissionYear="2026",
			q="HS-2026-HCM-000018",
		)
		with patch.object(
			director_students.frappe,
			"get_all",
			return_value=[
				frappe._dict(name="ENR-2026-000018", admission_year="2026"),
				frappe._dict(name="ENR-2026-000019", admission_year="2026"),
			],
		):
			_filters, or_filters = director_students._student_filters(query, None)

		self.assertIn(["name", "in", ["ENR-2026-000018"]], or_filters)

	def test_stage_filters_keep_exploring_and_counselling_distinct(self):
		exploring = director_students._parse_query(stage="exploring")
		counselling = director_students._parse_query(stage="counselling")

		exploring_filters, _ = director_students._student_filters(exploring, None)
		counselling_filters, _ = director_students._student_filters(counselling, None)

		self.assertEqual(exploring_filters["student_stage"], "Attempting")
		self.assertEqual(exploring_filters["assessment_status"], ["!=", "confirmed"])
		self.assertEqual(counselling_filters["assessment_status"], "confirmed")

	def test_detail_projection_contains_contract_sections(self):
		row = frappe._dict(
			name="ENR-1",
			student="CRMC-1",
			student_name="Nguyễn Minh An",
			phone="0900000000",
			email="an@example.com",
			province="P-1",
			ward="W-1",
			current_grade="12",
			study_stage="grade_12_h2",
			aspiration="ASP-1",
			date_of_birth="2007-07-20",
			gender="Nữ",
			admission_year="2026",
			student_stage="Attempting",
			assessment_status="confirmed",
			campaign="Campaign 1",
		)
		item = {
			"id": "ENR-1",
			"initials": "MA",
			"name": "Nguyễn Minh An",
			"code": "ENR-1",
			"school": "THPT Châu Văn Liêm",
			"province": "Cần Thơ",
			"ward": "Phường An Bình",
			"major": "Trí tuệ nhân tạo",
			"aspiration": "ASP-1",
			"stage": "Tư vấn",
			"score": 82,
			"scoreDelta": 13,
			"lastActivity": "4 phút trước",
			"lastActivityAt": "2026-08-31T09:56:00+07:00",
			"nextAction": "Gọi phụ huynh về học phí",
			"owner": "Trần Quốc Bảo",
			"revision": 4,
			"source": "Career Talk 28/05",
			"priority": "Cao",
		}
		with (
			patch.object(director_students, "_latest_assessment", return_value=frappe._dict()),
			patch.object(director_students, "_student_interactions", return_value=[]),
			patch.object(director_students, "_student_probability_trend", return_value=[]),
			patch.object(
				director_students,
				"_student_guardian",
				return_value={
					"name": None,
					"relation": None,
					"involvement": "Chưa xác định",
					"role": None,
					"concerns": [],
					"preferredChannel": None,
					"bestContactTime": None,
					"consentStatus": None,
					"lastInteraction": None,
				},
			),
			patch.object(director_students, "_student_applications", return_value=[]),
			patch.object(director_students, "_student_admission_profiles", return_value=[]),
		):
			response = director_students._build_student_360(row, item)

		self.assertEqual(response["student"]["phone"], "0900000000")
		self.assertEqual(response["student"]["studentId"], "CRMC-1")
		self.assertEqual(response["student"]["email"], "an@example.com")
		self.assertEqual(response["student"]["provinceId"], "P-1")
		self.assertEqual(response["student"]["ward"], "Phường An Bình")
		self.assertEqual(response["student"]["wardId"], "W-1")
		self.assertEqual(response["student"]["currentGrade"], "12")
		self.assertEqual(response["student"]["studyStage"], "grade_12_h2")
		self.assertEqual(response["student"]["aspiration"], "ASP-1")
		self.assertEqual(response["student"]["revision"], 4)
		self.assertEqual(response["student"]["grade"], "Lớp 12")
		self.assertEqual(response["student"]["priority"], "Cao")
		self.assertEqual(response["student"]["verificationStatus"], "Đã xác thực")
		self.assertEqual(response["acquisition"]["campaign"], "Campaign 1")
		self.assertEqual(response["insight"]["priorityThreshold"], 70)
		self.assertEqual(
			set(response),
			{
				"student",
				"readiness",
				"profile",
				"academics",
				"family",
				"classification",
				"acquisition",
				"segmentation",
				"parentProfile",
				"insight",
				"journey",
				"engagement",
				"application",
				"admissionProfiles",
				"probabilityTrend",
				"channelPerformance",
				"zaloMessages",
				"calls",
			},
		)

	def test_chart_projections_use_real_supported_interactions(self):
		assessments = [
			frappe._dict(status="confirmed", assessed_at="2026-06-01 09:00:00", enrollment_probability=41),
			frappe._dict(status="confirmed", assessed_at="2026-06-03 09:00:00", enrollment_probability=76),
		]
		interactions = [
			frappe._dict(
				interaction_datetime="2026-05-28 09:00:00",
				channel="Website",
				summary="Đăng ký tư vấn",
				outcome="Captured",
			),
			frappe._dict(
				interaction_datetime="2026-05-30 09:00:00",
				channel="Phone",
				summary="Gọi tư vấn",
				outcome="Resolved",
			),
			frappe._dict(
				interaction_datetime="2026-06-02 09:00:00",
				channel="Event",
				summary="Ngày hội tuyển sinh",
				outcome="No Response",
			),
			frappe._dict(
				interaction_datetime="2026-06-02 10:00:00",
				channel="Zalo",
				summary="Tin nhắn tư vấn",
				outcome="Captured",
			),
		]

		trend = director_students._build_probability_trend(assessments, interactions)
		channels = director_students._channel_performance(interactions)

		self.assertEqual([point["score"] for point in trend], [41, 76])
		self.assertEqual([point["touches"] for point in trend], [1, 2])
		self.assertEqual([item["channel"] for item in channels], ["Website", "Sự kiện"])
		self.assertEqual(channels[0]["response"], 100.0)
		self.assertEqual(channels[1]["response"], 0.0)

	def test_journey_keeps_milestones_and_excludes_activity_noise(self):
		interactions = [
			frappe._dict(
				name="INTX-STAGE",
				interaction_datetime="2026-09-05 09:00:00",
				interaction_type="STAGE_CHANGED",
				summary="Stage changed to Applicant",
			),
			frappe._dict(
				name="INTX-NOTE",
				interaction_datetime="2026-09-04 12:51:40",
				interaction_type="NOTE",
				summary="Hoàn tất hồ sơ nhập học (ghi chú nội bộ)",
			),
			frappe._dict(
				name="INTX-WEBCHAT",
				interaction_datetime="2026-09-04 12:47:31",
				interaction_type="MESSAGE",
				summary="webchat inbound",
				channel="webchat",
			),
			frappe._dict(
				name="INTX-ENROLLED",
				interaction_datetime="2026-08-27 19:33:43",
				interaction_type="COUNSELING",
				summary="Hoàn tất hồ sơ nhập học ngành Kỹ thuật phần mềm",
			),
			frappe._dict(
				name="INTX-TEST",
				interaction_datetime="2026-08-26 10:00:00",
				interaction_type="COUNSELING",
				summary="test",
			),
		]

		journey = director_students._journey(interactions, item={})

		self.assertEqual([event["id"] for event in journey], ["INTX-ENROLLED", "INTX-STAGE"])
		self.assertEqual(journey[0]["status"], "completed")
		self.assertEqual(journey[1]["status"], "current")

	def test_guardian_projection_reads_contact_as_a_permission_aware_row(self):
		with (
			patch.object(director_students, "_table_exists", return_value=True),
			patch.object(
				director_students.frappe,
				"get_all",
				side_effect=[
					[
						frappe._dict(
							contact="CON-1",
							relationship="Parent",
							involvement="Primary",
							preferred_channel="Phone",
						)
					],
					[frappe._dict(name="CON-1", full_name="Nguyễn Văn Minh")],
				],
			),
		):
			guardian = director_students._student_guardian("ENR-1")

		self.assertEqual(guardian["name"], "Nguyễn Văn Minh")
		self.assertEqual(guardian["preferredChannel"], "Phone")

	def test_assessment_confidence_uses_existing_confidence_fields(self):
		assessment = frappe._dict(interest_confidence=80, fit_confidence=70, barrier_confidence=60)

		self.assertEqual(director_students._assessment_confidence(assessment), 70.0)

	def test_empty_detail_id_is_invalid_request(self):
		with patch.object(director_students, "_require_access"), self.assertRaises(frappe.ValidationError):
			director_students.get_director_student("")

	def test_detail_endpoint_checks_student_permission_before_building_projection(self):
		doc = frappe._dict(name="ENR-1", owner_staff="STAFF-1")
		doc.has_permission = lambda permission_type: True
		with (
			patch.object(director_students, "_require_access", return_value=None),
			patch.object(director_students.frappe, "get_doc", return_value=doc),
			patch.object(director_students, "_hydrate_rows", return_value=[{"id": "ENR-1"}]),
			patch.object(director_students, "_build_student_360", return_value={"student": {"name": "An"}}),
		):
			response = director_students.get_director_student("ENR-1")

		self.assertEqual(response, {"student": {"name": "An"}})

	def test_detail_endpoint_hides_student_without_permission(self):
		doc = frappe._dict(name="ENR-1", owner_staff="STAFF-2")
		doc.has_permission = lambda permission_type: False
		with (
			patch.object(director_students, "_require_access", return_value=None),
			patch.object(director_students.frappe, "get_doc", return_value=doc),
			self.assertRaises(frappe.DoesNotExistError),
		):
			director_students.get_director_student("ENR-1")

	def test_student_count_uses_permission_aware_list_query(self):
		with patch.object(
			director_students.frappe,
			"get_list",
			return_value=[frappe._dict(total=3)],
		) as get_list:
			self.assertEqual(
				director_students._count_students({"admission_year": "2026"}),
				3,
			)

		get_list.assert_called_once_with(
			"CRM Student",
			filters={"admission_year": "2026"},
			or_filters=[],
			fields=["count(name) as total"],
			limit_page_length=1,
		)

	def test_sale_list_scope_uses_the_student_projection_table(self):
		condition = "`tabCRM Student`.owner_staff = 'STAFF-1'"
		with (
			patch.object(director_students, "can_read_full_lead_board", return_value=False),
			patch.object(director_students, "get_student_list_read_condition", return_value=condition) as get_condition,
			patch.object(director_students.frappe.db, "sql", return_value=[{"name": "ENR-1"}]) as sql,
		):
			result = director_students._list_scope_student_ids()

		self.assertEqual(result, ["ENR-1"])
		get_condition.assert_called_once_with(doctype="CRM Student")
		sql.assert_called_once_with(
			"select name from `tabCRM Student` where (`tabCRM Student`.owner_staff = 'STAFF-1')",
			as_dict=True,
		)

	def test_lead_sale_student_list_scope_is_unrestricted(self):
		with (
			patch.object(director_students, "can_read_full_lead_board", return_value=True),
			patch.object(director_students, "get_student_list_read_condition") as get_condition,
		):
			self.assertIsNone(director_students._list_scope_student_ids())

		get_condition.assert_not_called()

	def test_lead_sale_student_list_uses_unrestricted_reader(self):
		with patch.object(director_students, "can_read_full_lead_board", return_value=True):
			self.assertIs(director_students._student_list_reader(None), director_students.frappe.get_all)

	def test_student_zalo_messages_mapping(self):
		interactions = [
			frappe._dict(
				name="INTX-ZALO-1",
				interaction_datetime="2026-06-06 16:42:00",
				channel="Zalo",
				direction="inbound",
				summary="Hỏi học phí & học bổng",
				notes="Em gửi giúp anh bảng học phí theo từng học kỳ.",
				outcome="Resolved",
			),
			frappe._dict(
				name="INTX-ZALO-2",
				interaction_datetime="2026-06-06 16:49:00",
				channel="Zalo",
				direction="outbound",
				summary="Hỏi học phí & học bổng",
				notes="Dạ được anh. Đính kèm: Bang-hoc-phi-2026.pdf",
				outcome="Follow Up Needed",
			),
		]
		row = frappe._dict(student_name="Nguyễn Minh An", phone="0901234412", assigned_to="Trần Quốc Bảo")
		guardian = {"name": "Nguyễn Văn Minh", "relation": "Bố của học sinh"}

		messages = director_students._student_zalo_messages("ENR-1", interactions, row, guardian)

		self.assertEqual(len(messages), 2)
		self.assertEqual(messages[0]["id"], "INTX-ZALO-1")
		self.assertEqual(messages[0]["direction"], "inbound")
		self.assertEqual(messages[0]["senderName"], "Nguyễn Văn Minh")
		self.assertEqual(messages[0]["status"], "read")
		self.assertEqual(messages[1]["id"], "INTX-ZALO-2")
		self.assertEqual(messages[1]["direction"], "outbound")
		self.assertEqual(messages[1]["attachmentName"], "Bang-hoc-phi-2026.pdf")
		self.assertEqual(messages[1]["status"], "delivered")

	def test_student_call_records_mapping(self):
		interactions = [
			frappe._dict(
				name="INTX-CALL-1",
				interaction_datetime="2026-06-06 16:42:00",
				channel="Phone",
				direction="outbound",
				summary="Tư vấn lần 2",
				notes="Đã xác nhận ngành phù hợp.",
				outcome="Connected",
			)
		]
		row = frappe._dict(student_name="Nguyễn Minh An", phone="0901234412", assigned_to="Trần Quốc Bảo")
		guardian = {"name": "Nguyễn Văn Minh", "relation": "Bố của học sinh"}

		with patch.object(director_students, "_table_exists", return_value=False):
			calls = director_students._student_call_records("ENR-1", interactions, row, guardian)

		self.assertEqual(len(calls), 1)
		self.assertEqual(calls[0]["id"], "INTX-CALL-1")
		self.assertEqual(calls[0]["direction"], "outbound")
		self.assertEqual(calls[0]["outcome"], "connected")
		self.assertEqual(calls[0]["receiverName"], "Nguyễn Văn Minh")
		self.assertEqual(calls[0]["phoneNumber"], "0901234412")

	def test_display_code_resolves_against_students_not_leads(self):
		"""The display code is built from the Student name, so no Lead can match it."""
		captured = {}

		def fake_get_all(doctype, **kwargs):
			captured["doctype"] = doctype
			captured["filters"] = kwargs.get("filters")
			return [frappe._dict(name="CRMC-2026-00063", admission_year="2026")]

		with patch.object(director_students.frappe, "get_all", side_effect=fake_get_all):
			names = director_students._display_code_student_ids("HS-2026-HCM-000063", "2026")

		self.assertEqual(names, ["CRMC-2026-00063"])
		self.assertEqual(captured["doctype"], "CRM Student")
		self.assertEqual(captured["filters"]["admission_year"], "2026")
		self.assertEqual(captured["filters"]["name"], ["like", "%63"])

	def test_display_code_ignores_students_of_another_sequence(self):
		with patch.object(
			director_students.frappe,
			"get_all",
			return_value=[frappe._dict(name="CRMC-2026-00163", admission_year="2026")],
		):
			self.assertEqual(director_students._display_code_student_ids("HS-2026-HCM-000063", "2026"), [])

	def test_student_call_records_degrade_when_call_log_read_is_denied(self):
		"""Sale has no Call Log grant; the 360 detail must still render."""
		row = frappe._dict(student_name="Nguyễn Minh An", phone="0901234412")
		with (
			patch.object(director_students, "_table_exists", return_value=True),
			patch.object(director_students.frappe, "get_list", side_effect=frappe.PermissionError),
		):
			calls = director_students._student_call_records("CRMC-2026-00063", [], row, None)

		self.assertEqual(calls, [])

	def test_call_note_projection_extracts_transcript_and_summary(self):
		result = director_students._call_note_projection(
			"""
			<p>[AI_CALL_SUMMARY_V1]</p>
			{&quot;summary&quot;:&quot;Lead quan tâm học phí &amp; học bổng.&quot;,&quot;key_points&quot;:[]}
			<p>[/AI_CALL_SUMMARY_V1]</p>
			<p>[TRANSCRIPT]</p>
			[00:01] TƯ VẤN VIÊN: Em quan tâm ngành thiết kế.
			<br>[00:08] HỌC SINH: Dạ, em muốn biết thêm học phí.
			<p>[/TRANSCRIPT]</p>
			"""
		)

		self.assertEqual(result["summary"], "Lead quan tâm học phí & học bổng.")
		self.assertIn("TƯ VẤN VIÊN: Em quan tâm ngành thiết kế.", result["transcript"])
		self.assertIn("HỌC SINH: Dạ, em muốn biết thêm học phí.", result["transcript"])

	def test_student_call_records_build_worldfone_proxy_from_calluuid(self):
		call_log = frappe._dict(
			name="1788077950.625384",
			type="Incoming",
			status="Completed",
			from_number="0901234412",
			to="1200",
			duration=28,
			start_time="2026-08-30 16:20:58",
			creation="2026-08-30 16:20:58",
			recording_url=None,
			telephony_medium="Manual",
			medium="Worldfone",
			caller=None,
			receiver=None,
			note=None,
		)
		with (
			patch.object(director_students, "_table_exists", return_value=True),
			patch.object(director_students.frappe, "get_list", return_value=[call_log]),
			patch.dict(
				director_students.frappe.conf,
				{"crm_worldfone_secret": "test-secret"},
				clear=False,
			),
		):
			calls = director_students._student_call_records(
				"ENR-1",
				[],
				frappe._dict(student_name="Student Demo", phone="0901234412"),
				{},
			)

		self.assertEqual(
			calls[0]["recordingUrl"],
			"/api/method/crm.integrations.api.get_recording_url?call_log_name=1788077950.625384",
		)
		self.assertFalse(calls[0]["summaryAvailable"])

	def test_student_call_records_include_transcript_from_linked_note(self):
		call_log = frappe._dict(
			name="CALL-TRANSCRIPT-1",
			type="Outgoing",
			status="Completed",
			from_number="0901234412",
			to="1200",
			duration=48,
			start_time="2026-08-30 16:20:58",
			creation="2026-08-30 16:20:58",
			recording_url=None,
			telephony_medium="Manual",
			medium="Worldfone",
			caller="Administrator",
			receiver=None,
			note="NOTE-TRANSCRIPT-1",
		)
		note = frappe._dict(
			name="NOTE-TRANSCRIPT-1",
			content=(
				"[AI_CALL_SUMMARY_V1]\nsummary: Quan tâm học phí.\n[/AI_CALL_SUMMARY_V1]\n"
				"[TRANSCRIPT]\nTƯ VẤN VIÊN: Em cần tư vấn.\n[/TRANSCRIPT]"
			),
		)

		def get_list(doctype, **kwargs):
			return [call_log] if doctype == "Call Log" else [note]

		with (
			patch.object(
				director_students,
				"_table_exists",
				side_effect=lambda doctype: doctype in {"Call Log", "FCRM Note"},
			),
			patch.object(director_students.frappe, "get_list", side_effect=get_list),
		):
			calls = director_students._student_call_records(
				"ENR-1",
				[],
				frappe._dict(student_name="Student Demo", phone="0901234412"),
				{},
			)

		self.assertEqual(calls[0]["summary"], "Quan tâm học phí.")
		self.assertTrue(calls[0]["summaryAvailable"])
		self.assertEqual(calls[0]["transcript"], "TƯ VẤN VIÊN: Em cần tư vấn.")

	def test_get_student_interactions_endpoint(self):
		doc = frappe._dict(name="STU-1", full_name="Nguyễn Minh An", owner_staff="STAFF-1")
		doc.has_permission = lambda permission_type: permission_type == "read"
		with (
			patch.object(director_students, "_require_access", return_value=None),
			patch.object(
				director_students,
				"_resolve_canonical_activity_target",
				return_value=("STU-1", "STU-1"),
			),
			patch.object(director_students.frappe, "get_doc", return_value=doc),
			patch.object(director_students, "_student_interactions", return_value=[]),
			patch.object(director_students, "_student_guardian", return_value={}),
		):
			result = director_students.get_student_interactions("STU-1")

		self.assertEqual(result["student_id"], "STU-1")
		self.assertEqual(result["zalo_messages"], [])
		self.assertEqual(result["calls"], [])
		self.assertEqual(result["total_interactions"], 0)

	def test_get_student_interactions_uses_canonical_student_id(self):
		doc = frappe._dict(name="STU-1", full_name="Nguyễn Minh An", owner_staff="STAFF-1")
		doc.has_permission = lambda permission_type: permission_type == "read"
		with (
			patch.object(director_students, "_require_access", return_value=None),
			patch.object(
				director_students,
				"_resolve_canonical_activity_target",
				return_value=("CRMC-1", "STU-1"),
			),
			patch.object(director_students.frappe, "get_doc", return_value=doc),
			patch.object(director_students.frappe, "has_permission", return_value=True),
			patch.object(director_students, "_student_interactions", return_value=[]),
			patch.object(director_students, "_student_guardian", return_value={}),
		):
			result = director_students.get_student_interactions("CRMC-1")

		self.assertEqual(result["student_id"], "CRMC-1")
		self.assertEqual(result["zalo_messages"], [])
		self.assertEqual(result["calls"], [])

	def test_get_lead_call_logs_endpoint(self):
		with patch.object(
			director_students,
			"get_student_interactions",
			return_value={"student_id": "LEAD-1", "calls": [{"id": "CALL-1"}]},
		):
			result = director_students.get_lead_call_logs("LEAD-1")

		self.assertEqual(result, {"lead_id": "LEAD-1", "calls": [{"id": "CALL-1"}], "total": 1})

	def test_student_zalo_messages_include_chatwoot_interactions(self):
		messages = director_students._student_zalo_messages(
			"ENR-1",
			[
				frappe._dict(
					name="INTX-CHATWOOT-1",
					interaction_type="TIN_NHAN_CHATWOOT",
					interaction_datetime="2026-09-04 12:47:31",
					direction="inbound",
					notes="Em muốn hỏi học phí.",
					channel="webchat",
				)
			],
			frappe._dict(student_name="Nguyễn Minh An"),
			{},
		)

		self.assertEqual(len(messages), 1)
		self.assertEqual(messages[0]["id"], "INTX-CHATWOOT-1")
		self.assertEqual(messages[0]["content"], "Em muốn hỏi học phí.")

	def test_get_student_chatwoot_interactions_filters_type_and_paginates(self):
		doc = frappe._dict(name="STU-1", full_name="Nguyễn Minh An", owner_staff="STAFF-1")
		doc.has_permission = lambda permission_type: permission_type == "read"
		rows = [
			frappe._dict(
				name="INTX-CHATWOOT-2",
				student="ENR-1",
				interaction_type="TIN_NHAN_CHATWOOT",
				interaction_datetime="2026-09-04 12:47:31",
				direction="inbound",
				notes="Tin nhắn mới",
			),
		]
		calls = []

		def get_list(doctype, **kwargs):
			calls.append((doctype, kwargs))
			if kwargs.get("pluck") == "name":
				return ["INTX-CHATWOOT-1", "INTX-CHATWOOT-2", "INTX-CHATWOOT-3"]
			return rows

		with (
			patch.object(director_students, "_require_access", return_value=None),
			patch.object(
				director_students,
				"_resolve_canonical_activity_target",
				return_value=("CRMC-1", "STU-1"),
			),
			patch.object(director_students, "_student_query_ids", return_value=["STU-1"]),
			patch.object(director_students.frappe, "get_doc", return_value=doc),
			patch.object(director_students.frappe, "has_permission", return_value=True),
			patch.object(director_students.frappe, "get_list", side_effect=get_list),
			patch.object(director_students, "_student_guardian", return_value={}),
			patch.object(
				director_students, "_student_zalo_messages", return_value=[{"id": "INTX-CHATWOOT-2"}]
			),
		):
			result = director_students.get_student_chatwoot_interactions("CRMC-1", page="2", page_size="1")

		self.assertEqual(result["student_id"], "CRMC-1")
		self.assertEqual(result["data"], rows)
		self.assertEqual(result["zalo_messages"], [{"id": "INTX-CHATWOOT-2"}])
		self.assertEqual(result["meta"], {"page": 2, "page_size": 1, "total": 3, "has_next_page": True})
		self.assertEqual(len(calls), 2)
		self.assertEqual(calls[0][0], "CRM Interaction")
		self.assertEqual(
			calls[0][1]["filters"],
			{
				"student": ["in", ["STU-1"]],
				"interaction_type": ["in", ("MESSAGE", "TIN_NHAN_CHATWOOT")],
			},
		)
		self.assertEqual(calls[0][1]["limit_start"], 1)
		self.assertEqual(calls[0][1]["limit_page_length"], 1)
		self.assertEqual(calls[1][1]["limit_page_length"], 0)

	def test_get_student_chatwoot_interactions_rejects_missing_student(self):
		with patch.object(director_students, "_require_access", return_value=None):
			with self.assertRaises(frappe.ValidationError):
				director_students.get_student_chatwoot_interactions("")
