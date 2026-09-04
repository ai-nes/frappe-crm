from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import director_students


class TestDirectorStudents(FrappeTestCase):
	def test_query_normalization_accepts_contract_values(self):
		query = director_students._parse_query(
			admissionYear="2026",
			page="2",
			pageSize="50",
			q="  Nguyen  ",
			stage="counselling",
			province="can-tho",
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
				"sort": "lastActivityAt",
				"order": "asc",
			},
		)

	def test_query_normalization_rejects_invalid_values(self):
		for kwargs in (
			{"page": "0"},
			{"pageSize": "101"},
			{"stage": "unknown"},
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
				"student_name": "Nguyễn Minh An",
				"case_key": "CK-ID-2026",
				"high_school": "HS-1",
				"province": "P-1",
				"major": "M-1",
				"lifecycle_stage": "MQL",
				"assessment_status": "confirmed",
				"latest_score": 82,
				"owner_staff": "STAFF-1",
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
		self.assertEqual(item["code"], "CK-ID-2026")
		self.assertEqual(item["initials"], "MA")
		self.assertEqual(item["school"], "THPT Châu Văn Liêm")
		self.assertEqual(item["province"], "Cần Thơ")
		self.assertEqual(item["major"], "Trí tuệ nhân tạo")
		self.assertEqual(item["stage"], "Tư vấn")
		self.assertEqual(item["stageCode"], "counselling")
		self.assertEqual(item["score"], 82)
		self.assertEqual(item["scoreDelta"], 13)
		self.assertEqual(item["nextAction"], "Gọi phụ huynh về học phí")
		self.assertEqual(item["priority"], "Cao")
		self.assertEqual(item["priorityCode"], "high")
		self.assertEqual(item["lastActivityAt"], "2026-08-31T09:56:00+07:00")

	def test_list_endpoint_returns_dashboard_envelope_and_server_applied_filters(self):
		row = frappe._dict(name="ENR-1", student_name="Nguyễn Minh An")
		with (
			patch.object(director_students, "_resolve_admission_year", return_value="2026"),
			patch.object(director_students, "_resolve_province", return_value="Cần Thơ"),
			patch.object(director_students, "_count_students", side_effect=[1, 8]),
			patch.object(director_students, "_fetch_student_rows", return_value=[row]),
			patch.object(director_students, "_hydrate_rows", return_value=[{"id": "ENR-1"}]),
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
				sort="score",
				order="desc",
			)

		self.assertEqual(response["data"], [{"id": "ENR-1"}])
		self.assertEqual(response["meta"]["total"], 1)
		self.assertEqual(response["meta"]["totalAll"], 8)
		self.assertEqual(response["meta"]["page"], 2)
		self.assertEqual(response["meta"]["pageSize"], 1)
		self.assertEqual(response["meta"]["totalPages"], 1)
		self.assertFalse(response["meta"]["hasNextPage"])
		self.assertEqual(response["meta"]["filters"], {"stage": "Tư vấn", "province": "Cần Thơ"})
		self.assertEqual(response["meta"]["sort"], {"field": "score", "order": "desc"})

	def test_stage_filters_keep_exploring_and_counselling_distinct(self):
		exploring = director_students._parse_query(stage="exploring")
		counselling = director_students._parse_query(stage="counselling")

		exploring_filters, _ = director_students._student_filters(exploring, None)
		counselling_filters, _ = director_students._student_filters(counselling, None)

		self.assertEqual(exploring_filters["lifecycle_stage"], "MQL")
		self.assertEqual(exploring_filters["assessment_status"], ["!=", "confirmed"])
		self.assertEqual(counselling_filters["assessment_status"], "confirmed")

	def test_detail_projection_contains_contract_sections(self):
		row = frappe._dict(
			name="ENR-1",
			student_name="Nguyễn Minh An",
			phone="0900000000",
			email="an@example.com",
			current_grade="12",
			date_of_birth="2007-07-20",
			gender="Nữ",
			admission_year="2026",
			lifecycle_stage="MQL",
			assessment_status="confirmed",
		)
		item = {
			"id": "ENR-1",
			"initials": "MA",
			"name": "Nguyễn Minh An",
			"code": "ENR-1",
			"school": "THPT Châu Văn Liêm",
			"province": "Cần Thơ",
			"major": "Trí tuệ nhân tạo",
			"stage": "Tư vấn",
			"score": 82,
			"scoreDelta": 13,
			"lastActivity": "4 phút trước",
			"lastActivityAt": "2026-08-31T09:56:00+07:00",
			"nextAction": "Gọi phụ huynh về học phí",
			"owner": "Trần Quốc Bảo",
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
		):
			response = director_students._build_student_360(row, item)

		self.assertEqual(response["student"]["phone"], "0900000000")
		self.assertEqual(response["student"]["email"], "an@example.com")
		self.assertEqual(response["student"]["grade"], "Lớp 12")
		self.assertEqual(response["student"]["priority"], "Cao")
		self.assertEqual(response["student"]["verificationStatus"], "Đã xác thực")
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
				"probabilityTrend",
				"channelPerformance",
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

	def test_detail_endpoint_is_public_without_student_permission(self):
		doc = frappe._dict(name="ENR-1", owner_staff="STAFF-2")
		doc.has_permission = lambda permission_type: False
		with (
			patch.object(director_students, "_require_access", return_value=None),
			patch.object(director_students.frappe, "get_doc", return_value=doc),
			patch.object(director_students, "_hydrate_rows", return_value=[{"id": "ENR-1"}]),
			patch.object(director_students, "_build_student_360", return_value={"student": {"name": "An"}}),
		):
			response = director_students.get_director_student("ENR-1")

		self.assertEqual(response, {"student": {"name": "An"}})

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

	def test_get_student_interactions_endpoint(self):
		doc = frappe._dict(name="ENR-1", student_name="Nguyễn Minh An", owner_staff="STAFF-1")
		with (
			patch.object(director_students, "_require_access", return_value=None),
			patch.object(director_students.frappe, "get_doc", return_value=doc),
			patch.object(director_students, "_student_interactions", return_value=[]),
			patch.object(director_students, "_student_guardian", return_value={}),
		):
			result = director_students.get_student_interactions("ENR-1")

		self.assertEqual(result["student_id"], "ENR-1")
		self.assertEqual(result["zalo_messages"], [])
		self.assertEqual(result["calls"], [])
		self.assertEqual(result["total_interactions"], 0)
