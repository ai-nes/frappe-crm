"""Canonical seed vocabulary for the flat controlled-vocabulary lookups.

Pure data (no ``frappe`` import) so migrations, seeds, and tests can consume it
directly. Each key is a lookup DocType; each row is the immutable UPPER_SNAKE
``code`` plus its Vietnamese ``display_name`` and ordering. These replace the
former ``CRM Term`` categories one-for-one.

Values are gathered verbatim from the pre-cutover seeds they supersede:
``unify_contact_status_fields`` (legacy contact status), ``install.add_default_lost_reasons``
(lost reason), ``seed_demo.INTENT_TYPES`` + ``seed_crm_intent_type_dashboard_expansion``
(intent type), ``seed_crm_aspiration`` (aspiration), ``seed_showcase`` (admission
method), ``install.add_default_enrollment_statuses`` (enrollment status),
``seed_dashboard_data_foundation`` (region), ``prepare_school_domain.SCHOOL_DOMAIN_TERMS``
(school type / area, stakeholder role, school activity type) and the union of the
interaction-type seeds.

``CRM Campaign Type`` and ``CRM Major Group`` never had a repo seed — they were
always operator-managed lookups — so they ship empty and System Manager fills them
from Desk.
"""

from __future__ import annotations

from typing import Final

# doctype -> tuple of row dicts. Common keys: code, display_name, sort_order,
# description (optional). CRM Enrollment Status rows also carry stage_category,
# lifecycle_stage, stage_order. CRM Intent Type rows also carry importance.
REFERENCE_CATALOG: Final[dict[str, tuple[dict, ...]]] = {
	"CRM Lost Reason": (
		{
			"code": "PRICING",
			"display_name": "Giá",
			"sort_order": 10,
			"description": "The prospect found the pricing to be too high or not competitive.",
		},
		{
			"code": "COMPETITION",
			"display_name": "Đối thủ cạnh tranh",
			"sort_order": 20,
			"description": "The prospect chose a competitor's product or service.",
		},
		{
			"code": "BUDGET_CONSTRAINTS",
			"display_name": "Hạn chế ngân sách",
			"sort_order": 30,
			"description": "The prospect did not have the budget to proceed with the purchase.",
		},
		{
			"code": "MISSING_FEATURES",
			"display_name": "Thiếu tính năng",
			"sort_order": 40,
			"description": "The prospect felt that the product or service was missing key features they needed.",
		},
		{
			"code": "LONG_SALES_CYCLE",
			"display_name": "Chu kỳ bán hàng dài",
			"sort_order": 50,
			"description": "The sales process took too long, leading to loss of interest.",
		},
		{
			"code": "NO_DECISION_MAKER",
			"display_name": "Không phải người quyết định",
			"sort_order": 60,
			"description": "The prospect was not the decision-maker and could not proceed.",
		},
		{
			"code": "UNRESPONSIVE_PROSPECT",
			"display_name": "Khách hàng không phản hồi",
			"sort_order": 70,
			"description": "The prospect did not respond to follow-ups.",
		},
		{
			"code": "POOR_FIT",
			"display_name": "Không phù hợp",
			"sort_order": 80,
			"description": "The prospect was not a good fit for the product or service.",
		},
		{"code": "OTHER", "display_name": "Khác", "sort_order": 90},
	),
	"CRM Campaign Type": (),
	"CRM Intent Type": (
		{
			"code": "PROGRAM_INTEREST",
			"display_name": "Quan tâm ngành học",
			"sort_order": 10,
			"importance": "Medium",
		},
		{
			"code": "ADMISSION_REQUIREMENT",
			"display_name": "Điều kiện tuyển sinh",
			"sort_order": 20,
			"importance": "High",
		},
		{"code": "TUITION_FEE", "display_name": "Học phí", "sort_order": 30, "importance": "High"},
		{"code": "SCHOLARSHIP", "display_name": "Học bổng", "sort_order": 40, "importance": "High"},
		{
			"code": "APPLICATION_GUIDANCE",
			"display_name": "Hướng dẫn đăng ký",
			"sort_order": 50,
			"importance": "High",
		},
		{
			"code": "APPLICATION_STATUS",
			"display_name": "Tình trạng hồ sơ",
			"sort_order": 60,
			"importance": "Medium",
		},
		{
			"code": "DOCUMENT_REQUIREMENT",
			"display_name": "Yêu cầu hồ sơ",
			"sort_order": 70,
			"importance": "Medium",
		},
		{"code": "DEADLINE", "display_name": "Thời hạn tuyển sinh", "sort_order": 80, "importance": "High"},
		{
			"code": "CAREER_COUNSELING",
			"display_name": "Tư vấn định hướng",
			"sort_order": 90,
			"importance": "High",
		},
		{
			"code": "CAMPUS_INFORMATION",
			"display_name": "Thông tin trường",
			"sort_order": 100,
			"importance": "Medium",
		},
		{
			"code": "STUDENT_LIFE",
			"display_name": "Đời sống sinh viên",
			"sort_order": 110,
			"importance": "Medium",
		},
		{
			"code": "ENROLLMENT_CONFIRMATION",
			"display_name": "Xác nhận nhập học",
			"sort_order": 120,
			"importance": "Very High",
		},
		{
			"code": "WITHDRAWAL_OR_HESITATION",
			"display_name": "Do dự hoặc từ chối",
			"sort_order": 130,
			"importance": "Medium",
		},
		{
			"code": "REQUEST_CONTACT",
			"display_name": "Yêu cầu liên hệ",
			"sort_order": 140,
			"importance": "High",
		},
		{"code": "OTHER", "display_name": "Khác", "sort_order": 150, "importance": "Medium"},
		# Compatibility vocabulary retained for existing interaction/intake
		# integrations. New UI flows should prefer the admissions labels above.
		{
			"code": "MAJOR_INQUIRY",
			"display_name": "Hỏi về ngành học",
			"sort_order": 1010,
			"importance": "Medium",
		},
		{
			"code": "ENVIRONMENT",
			"display_name": "Môi trường học tập",
			"sort_order": 1020,
			"importance": "Medium",
		},
		{"code": "TUITION", "display_name": "Học phí", "sort_order": 1030, "importance": "High"},
		{"code": "DORMITORY", "display_name": "Ký túc xá", "sort_order": 1040, "importance": "Medium"},
		{
			"code": "ADMISSION_PROCESS",
			"display_name": "Quy trình tuyển sinh",
			"sort_order": 1050,
			"importance": "High",
		},
		{
			"code": "ENROLLMENT_INTENT",
			"display_name": "Ý định nhập học",
			"sort_order": 1060,
			"importance": "Very High",
		},
		{
			"code": "DEPOSIT_INTENT",
			"display_name": "Ý định đặt cọc",
			"sort_order": 1070,
			"importance": "Very High",
		},
		{
			"code": "NOT_INTERESTED",
			"display_name": "Không quan tâm",
			"sort_order": 1080,
			"importance": "Medium",
		},
	),
	"CRM Interaction Type": (
		{"code": "PHONE_CALL", "display_name": "Cuộc gọi", "sort_order": 10},
		{"code": "MESSAGE", "display_name": "Tin nhắn", "sort_order": 20},
		{"code": "EMAIL", "display_name": "Email", "sort_order": 30},
		{"code": "MEETING", "display_name": "Cuộc gặp tư vấn", "sort_order": 40},
		{"code": "FORM_SUBMISSION", "display_name": "Gửi biểu mẫu", "sort_order": 50},
		{"code": "APPLICATION_UPDATE", "display_name": "Cập nhật hồ sơ", "sort_order": 60},
		{"code": "DOCUMENT_SUBMISSION", "display_name": "Nộp tài liệu", "sort_order": 70},
		{"code": "EVENT_PARTICIPATION", "display_name": "Tham gia sự kiện", "sort_order": 80},
		{"code": "PAYMENT", "display_name": "Thanh toán", "sort_order": 90},
		{"code": "SYSTEM_ACTIVITY", "display_name": "Hoạt động hệ thống", "sort_order": 100},
		{"code": "NOTE", "display_name": "Ghi chú tư vấn", "sort_order": 110},
		{"code": "OTHER", "display_name": "Khác", "sort_order": 120},
		# Operational event codes remain valid because routing, scoring and
		# historical records use them even when the UI displays a friendlier
		# activity label.
		{"code": "LEAD_CAPTURED", "display_name": "Tiếp nhận Lead", "sort_order": 1010},
		{"code": "MQL_QUALIFIED", "display_name": "Đủ điều kiện tư vấn", "sort_order": 1020},
		{"code": "MQL_REJECTED", "display_name": "Không đủ điều kiện tư vấn", "sort_order": 1030},
		{"code": "LEAD_ASSIGNED", "display_name": "Gán Lead", "sort_order": 1040},
		{"code": "LEAD_REASSIGNED", "display_name": "Gán lại Lead", "sort_order": 1050},
		{"code": "OUTREACH", "display_name": "Chủ động liên hệ", "sort_order": 1060},
		{"code": "CONNECTED", "display_name": "Đã kết nối", "sort_order": 1070},
		{"code": "STAGE_CHANGED", "display_name": "Đổi giai đoạn", "sort_order": 1080},
		{"code": "APPLICATION_SUBMITTED", "display_name": "Đã nộp hồ sơ", "sort_order": 1090},
		{"code": "ADMITTED", "display_name": "Đã trúng tuyển", "sort_order": 1100},
		{"code": "ENROLLMENT_CONFIRMED", "display_name": "Đã xác nhận nhập học", "sort_order": 1110},
		{"code": "REGISTERED", "display_name": "Đã đăng ký", "sort_order": 1120},
		{"code": "CHECKED_IN", "display_name": "Đã đến làm thủ tục", "sort_order": 1130},
		{"code": "NO_SHOW", "display_name": "Không đến hẹn", "sort_order": 1140},
		{"code": "FEEDBACK", "display_name": "Phản hồi", "sort_order": 1150},
		{"code": "OPT_IN", "display_name": "Đồng ý nhận liên hệ", "sort_order": 1160},
		{"code": "OPT_OUT", "display_name": "Từ chối nhận liên hệ", "sort_order": 1170},
		{"code": "BOUNCE", "display_name": "Gửi không thành công", "sort_order": 1180},
		{"code": "DATA_ERROR", "display_name": "Lỗi dữ liệu", "sort_order": 1190},
		{"code": "CAMPAIGN_TOUCHED", "display_name": "Đã tương tác chiến dịch", "sort_order": 1200},
		{"code": "MESSAGE_CHATWOOT", "display_name": "Tin nhắn Chatwoot", "sort_order": 1210},
		{"code": "IN_PERSON", "display_name": "Tư vấn trực tiếp", "sort_order": 1220},
		{"code": "COUNSELING", "display_name": "Tư vấn tuyển sinh", "sort_order": 1230},
	),
	"CRM School Type": (
		{"code": "PUBLIC", "display_name": "Công lập", "sort_order": 10},
		{"code": "PRIVATE", "display_name": "Tư thục", "sort_order": 20},
	),
	"CRM School Area": (
		{"code": "KV1", "display_name": "Khu vực 1", "sort_order": 10},
		{"code": "KV2", "display_name": "Khu vực 2", "sort_order": 20},
		{"code": "KV2_NT", "display_name": "Khu vực 2 nông thôn", "sort_order": 30},
		{"code": "KV3", "display_name": "Khu vực 3", "sort_order": 40},
	),
	"CRM Stakeholder Role": (
		{"code": "BGH", "display_name": "Ban giám hiệu", "sort_order": 10},
		{"code": "TEACHER", "display_name": "Giáo viên", "sort_order": 20},
		{"code": "CAREER_COUNSELOR", "display_name": "Cán bộ hướng nghiệp", "sort_order": 30},
		{"code": "ADMISSIONS_CONTACT", "display_name": "Đầu mối tuyển sinh", "sort_order": 40},
	),
	"CRM School Activity Type": (
		{"code": "SCHOOL_VISIT", "display_name": "Thăm trường", "sort_order": 10},
		{"code": "CAREER_TALK", "display_name": "Nói chuyện hướng nghiệp", "sort_order": 20},
		{"code": "COUNSELING", "display_name": "Tư vấn", "sort_order": 30},
		{"code": "SEMINAR", "display_name": "Hội thảo", "sort_order": 40},
		{"code": "OPEN_DAY", "display_name": "Ngày hội tuyển sinh", "sort_order": 50},
		{"code": "AWARENESS", "display_name": "Nhận diện thương hiệu", "sort_order": 60},
		{"code": "RELATIONSHIP_TOUCH", "display_name": "Chăm sóc quan hệ", "sort_order": 70},
		{"code": "NCDT", "display_name": "Nghiên cứu địa bàn", "sort_order": 80},
		{"code": "PRINCIPAL_MEETING", "display_name": "Gặp gỡ ban giám hiệu", "sort_order": 90},
		{
			"code": "CAREER_EXPERIENCE_PROGRAM",
			"display_name": "Chương trình trải nghiệm hướng nghiệp",
			"sort_order": 100,
		},
		{"code": "PARENT_MEETING", "display_name": "Họp phụ huynh", "sort_order": 110},
	),
	"CRM Major Group": (),
	"CRM Aspiration": (
		{"code": "UNDECIDED", "display_name": "Chưa quyết định", "sort_order": 10},
		{"code": "NV1", "display_name": "Nguyện vọng 1", "sort_order": 20},
		{"code": "NV2", "display_name": "Nguyện vọng 2", "sort_order": 30},
		{"code": "NV3", "display_name": "Nguyện vọng 3", "sort_order": 40},
		{"code": "NV4", "display_name": "Nguyện vọng 4", "sort_order": 50},
		{"code": "NV5", "display_name": "Nguyện vọng 5", "sort_order": 60},
		{"code": "NV6", "display_name": "Nguyện vọng 6", "sort_order": 70},
		{"code": "NOT_APPLYING_FPT", "display_name": "Không xét tuyển FPT", "sort_order": 80},
	),
	"CRM Region": (
		{"code": "MB", "display_name": "Miền Bắc", "sort_order": 10},
		{"code": "MT", "display_name": "Miền Trung", "sort_order": 20},
		{"code": "MN", "display_name": "Miền Nam", "sort_order": 30},
	),
	"CRM Enrollment Status": (
		{
			"code": "NEW",
			"display_name": "Mới",
			"stage_category": "open",
			"lifecycle_stage": "Lead",
			"stage_order": 1,
			"sort_order": 10,
		},
		{
			"code": "PROSPECT",
			"display_name": "Có triển vọng",
			"stage_category": "open",
			"lifecycle_stage": "MQL",
			"stage_order": 2,
			"sort_order": 20,
		},
		{
			"code": "CONFIRMED",
			"display_name": "Đã xác nhận",
			"stage_category": "open",
			"lifecycle_stage": "Applicant",
			"stage_order": 3,
			"sort_order": 30,
		},
		{
			"code": "ENROLLED",
			"display_name": "Đã nhập học",
			"stage_category": "enrolled",
			"lifecycle_stage": "Enrolled",
			"stage_order": 4,
			"sort_order": 40,
		},
		{
			"code": "CONVERTED",
			"display_name": "Đã chuyển đổi",
			"stage_category": "enrolled",
			"lifecycle_stage": "Enrolled",
			"stage_order": 5,
			"sort_order": 50,
		},
		{
			"code": "REFUSED",
			"display_name": "Từ chối",
			"stage_category": "lost",
			"lifecycle_stage": "Lost",
			"stage_order": 6,
			"sort_order": 60,
		},
	),
	"CRM Admission Method": (
		{"code": "COMBINED", "display_name": "Xét tuyển kết hợp", "sort_order": 10},
		{"code": "LANGUAGE_CERTIFICATE_REVIEW", "display_name": "Xét chứng chỉ ngoại ngữ", "sort_order": 20},
		{"code": "TRANSCRIPT_REVIEW", "display_name": "Xét học bạ", "sort_order": 30},
		{"code": "NATIONAL_HIGH_SCHOOL_EXAM", "display_name": "Điểm thi tốt nghiệp THPT", "sort_order": 40},
		{"code": "DIRECT_ADMISSION", "display_name": "Tuyển thẳng", "sort_order": 50},
	),
}
