"""Canonical CRM action-type catalog and compatibility vocabulary.

The catalog is intentionally pure data so it can be used by migrations,
controllers, APIs, and tests without importing Frappe.  The 79 canonical
codes are the source supplied by the admissions action taxonomy.
"""

from __future__ import annotations

import re
from typing import Final

ACTION_TYPE_CATALOG: Final[tuple[tuple[str, str, str], ...]] = (
	("CALL", "Gọi điện", "CONTACT"),
	("SEND_ZALO", "Gửi Zalo", "CONTACT"),
	("SEND_EMAIL", "Gửi Email", "CONTACT"),
	("SEND_SMS", "Gửi SMS", "CONTACT"),
	("VIDEO_CALL", "Gọi video", "CONTACT"),
	("CALL_BACK", "Gọi lại", "CONTACT"),
	("REASSIGN_ADVISOR", "Chuyển tư vấn viên", "CONTACT"),
	("ESCALATE_SUPERVISOR", "Chuyển cấp quản lý", "CONTACT"),
	("SEND_MAJOR_INFO", "Gửi thông tin ngành", "INFORMATION"),
	("SEND_PROGRAM_INFO", "Gửi thông tin chương trình", "INFORMATION"),
	("SEND_TUITION_INFO", "Gửi thông tin học phí", "INFORMATION"),
	("SEND_SCHOLARSHIP_INFO", "Gửi thông tin học bổng", "INFORMATION"),
	("SEND_PROMOTION_INFO", "Gửi thông tin ưu đãi", "INFORMATION"),
	("SEND_ADMISSION_INFO", "Gửi thông tin tuyển sinh", "INFORMATION"),
	("SEND_DORM_INFO", "Gửi thông tin ký túc xá", "INFORMATION"),
	("SEND_CAREER_INFO", "Gửi thông tin nghề nghiệp", "INFORMATION"),
	("SEND_BROCHURE", "Gửi brochure", "INFORMATION"),
	("SEND_MAJOR_VIDEO", "Gửi video ngành", "INFORMATION"),
	("SEND_RELEVANT_FAQ", "Gửi FAQ phù hợp", "INFORMATION"),
	("INVITE_OPEN_DAY", "Mời Open Day", "ENGAGEMENT"),
	("INVITE_CAMPUS_TOUR", "Mời tham quan campus", "ENGAGEMENT"),
	("INVITE_WEBINAR", "Mời webinar", "ENGAGEMENT"),
	("INVITE_WORKSHOP", "Mời workshop", "ENGAGEMENT"),
	("INVITE_CLASS_EXPERIENCE", "Mời trải nghiệm lớp học", "ENGAGEMENT"),
	("INVITE_STEM_EVENT", "Mời sự kiện STEM", "ENGAGEMENT"),
	("INVITE_MOCK_TEST", "Mời thi thử", "ENGAGEMENT"),
	("BOOK_1ON1_CONSULTATION", "Đặt lịch tư vấn 1-1", "ENGAGEMENT"),
	("SEND_PERSONALIZED_CONTENT", "Gửi nội dung cá nhân hóa", "ENGAGEMENT"),
	("SEND_TESTIMONIAL", "Gửi câu chuyện sinh viên", "ENGAGEMENT"),
	("REMIND_APPLICATION", "Nhắc nộp hồ sơ", "APPLICATION"),
	("REMIND_COMPLETE_APPLICATION", "Nhắc hoàn tất hồ sơ", "APPLICATION"),
	("REQUEST_MISSING_DOCUMENT", "Yêu cầu bổ sung hồ sơ", "APPLICATION"),
	("GUIDE_NEXT_STEP", "Hướng dẫn bước tiếp theo", "APPLICATION"),
	("CHECK_APPLICATION", "Kiểm tra hồ sơ", "APPLICATION"),
	("SEND_APPLICATION_CHECKLIST", "Gửi checklist hồ sơ", "APPLICATION"),
	("REMIND_APPLICATION_DEADLINE", "Nhắc hạn hồ sơ", "APPLICATION"),
	("ASSIST_APPLICATION_FEE", "Hỗ trợ phí hồ sơ", "APPLICATION"),
	("CONFIRM_APPLICATION_RECEIVED", "Xác nhận đã nhận hồ sơ", "APPLICATION"),
	("ADVISE_MAJOR", "Tư vấn chọn ngành", "CONVERSION"),
	("ADVISE_TUITION", "Tư vấn học phí", "CONVERSION"),
	("ADVISE_SCHOLARSHIP", "Tư vấn học bổng", "CONVERSION"),
	("ADVISE_CAREER", "Tư vấn nghề nghiệp", "CONVERSION"),
	("ADVISE_PARENT", "Tư vấn phụ huynh", "CONVERSION"),
	("COMPARE_MAJORS", "So sánh ngành", "CONVERSION"),
	("COMPARE_CAMPUSES", "So sánh campus", "CONVERSION"),
	("SEND_OFFER", "Gửi offer", "CONVERSION"),
	("REMIND_ENROLLMENT_DEADLINE", "Nhắc hạn nhập học", "CONVERSION"),
	("INVITE_CAMPUS_VISIT", "Mời đến campus", "CONVERSION"),
	("ESCALATE_HIGH_INTENT", "Chuyển lead intent cao", "CONVERSION"),
	("CONTACT_PARENT", "Liên hệ phụ huynh", "PARENT"),
	("SEND_PARENT_TUITION", "Gửi học phí cho phụ huynh", "PARENT"),
	("SEND_PARENT_SCHOLARSHIP", "Gửi học bổng cho phụ huynh", "PARENT"),
	("SEND_TRAINING_ROADMAP", "Gửi lộ trình đào tạo", "PARENT"),
	("SEND_PARENT_CAREER_INFO", "Gửi thông tin nghề nghiệp cho phụ huynh", "PARENT"),
	("INVITE_PARENT_EVENT", "Mời phụ huynh tham dự sự kiện", "PARENT"),
	("BOOK_PARENT_CONSULTATION", "Đặt lịch tư vấn phụ huynh", "PARENT"),
	("SEND_FINANCIAL_PLAN", "Gửi kế hoạch tài chính", "PARENT"),
	("FOLLOW_UP_SILENT_LEAD", "Theo dõi lead im lặng", "RECOVERY"),
	("REENGAGE_LEAD", "Tái tương tác lead", "RECOVERY"),
	("ASK_DECISION_REASON", "Hỏi lý do chưa quyết định", "RECOVERY"),
	("SEND_OBJECTION_CONTENT", "Gửi nội dung xử lý phản đối", "RECOVERY"),
	("ESCALATE_TO_SENIOR", "Chuyển tư vấn viên cấp cao", "RECOVERY"),
	("SCHEDULE_LATER_FOLLOWUP", "Lên lịch follow-up sau", "RECOVERY"),
	("ADD_TO_NURTURE", "Đưa vào nurture", "RECOVERY"),
	("MARK_NOT_READY", "Đánh dấu chưa sẵn sàng", "RECOVERY"),
	("MARK_LOST", "Đánh dấu lost", "RECOVERY"),
	("ACTIVATE_WINBACK", "Kích hoạt win-back", "RECOVERY"),
	("CREATE_TASK", "Tạo task", "INTERNAL"),
	("ASSIGN_LEAD", "Phân lead", "INTERNAL"),
	("REASSIGN_LEAD", "Chuyển lead", "INTERNAL"),
	("CREATE_REMINDER", "Tạo nhắc việc", "INTERNAL"),
	("CREATE_APPOINTMENT", "Tạo lịch hẹn", "INTERNAL"),
	("CREATE_CAMPAIGN", "Tạo campaign", "INTERNAL"),
	("UPDATE_LEAD_STATUS", "Cập nhật trạng thái lead", "INTERNAL"),
	("UPDATE_LEAD_SCORE", "Cập nhật lead score", "INTERNAL"),
	("ADD_TAG", "Thêm tag", "INTERNAL"),
	("CREATE_NOTE", "Tạo note", "INTERNAL"),
	("ESCALATE_CASE", "Chuyển case", "INTERNAL"),
	("REQUEST_SUPERVISOR_REVIEW", "Yêu cầu quản lý duyệt", "INTERNAL"),
)

ACTION_TYPE_CODES: Final[frozenset[str]] = frozenset(row[0] for row in ACTION_TYPE_CATALOG)
ACTION_TYPE_CATEGORIES: Final[frozenset[str]] = frozenset(row[2] for row in ACTION_TYPE_CATALOG)
CONFIGURATION_CODE_PATTERN: Final = re.compile(r"^[A-Z][A-Z0-9_]{1,49}$")
ACTION_TYPE_METADATA: Final[dict[str, dict[str, str]]] = {
	code: {"action_type": code, "display_name": display_name, "category": category}
	for code, display_name, category in ACTION_TYPE_CATALOG
}

# These values exist in pre-catalog CRM Action/Action Definition records.
# They remain accepted for backward compatibility but are deliberately not
# added to the 79-row canonical catalog.
LEGACY_ACTION_TYPE_ALIASES: Final[frozenset[str]] = frozenset(
	{
		"CALL",
		"EMAIL",
		"MESSAGE",
		"COUNSELING",
		"MEETING",
		"EVENT_INVITE",
		"CAMPUS_VISIT",
		"DOCUMENT_REQUEST",
		"APPLICATION_SUPPORT",
		"PARENT_CONTACT",
		"HANDOFF",
	}
)
# WAIT/FOLLOW_UP are recommendation-only outcomes, never a CRM Action: they
# represent "do nothing yet" rather than a task to execute. They stay
# supported for recommendations only (see SUPPORTED_RECOMMENDATION_ACTION_TYPES
# below) as long as `crm/fcrm/nba.py` can still emit them; removing them here
# is tech debt tied to retiring that WAIT/FOLLOW_UP branch in nba.py, not a
# standalone cleanup.
LEGACY_RECOMMENDATION_ONLY: Final[frozenset[str]] = frozenset({"WAIT", "FOLLOW_UP"})
# Maps each alias above to its canonical catalog code at write boundaries
# (see canonicalize_action_type()). CALL is intentionally absent: it is
# already a canonical catalog code (see ACTION_TYPE_CATALOG above), listed
# in LEGACY_ACTION_TYPE_ALIASES only because pre-catalog records also used it.
LEGACY_ACTION_TYPE_CANONICAL: Final[dict[str, str]] = {
	"EMAIL": "SEND_EMAIL",
	"MESSAGE": "SEND_ZALO",
	"COUNSELING": "ADVISE_MAJOR",
	"MEETING": "BOOK_1ON1_CONSULTATION",
	"EVENT_INVITE": "INVITE_OPEN_DAY",
	"CAMPUS_VISIT": "INVITE_CAMPUS_TOUR",
	"DOCUMENT_REQUEST": "REQUEST_MISSING_DOCUMENT",
	"APPLICATION_SUPPORT": "GUIDE_NEXT_STEP",
	"PARENT_CONTACT": "CONTACT_PARENT",
	"HANDOFF": "ESCALATE_TO_SENIOR",
}


def is_valid_configuration_code(value: str | None) -> bool:
	"""Return whether a custom catalog code is safe for a DocType name/key."""
	return bool(value and CONFIGURATION_CODE_PATTERN.fullmatch(value))
SUPPORTED_ACTION_TYPES: Final[frozenset[str]] = ACTION_TYPE_CODES | LEGACY_ACTION_TYPE_ALIASES
SUPPORTED_RECOMMENDATION_ACTION_TYPES: Final[frozenset[str]] = (
	SUPPORTED_ACTION_TYPES | LEGACY_RECOMMENDATION_ONLY
)


def is_supported_action_type(action_type: str | None) -> bool:
	return bool(action_type and action_type in SUPPORTED_ACTION_TYPES)


def is_supported_recommendation_action(action_type: str | None) -> bool:
	return bool(action_type and action_type in SUPPORTED_RECOMMENDATION_ACTION_TYPES)


def canonicalize_action_type(action_type: str | None) -> str | None:
	"""Map a legacy value to the canonical catalog code at write boundaries."""
	if not action_type:
		return action_type
	return LEGACY_ACTION_TYPE_CANONICAL.get(action_type, action_type)


def action_category(action_code: str | None) -> str | None:
	"""Return the category for a canonical CRM Action code."""
	canonical = canonicalize_action_type(action_code)
	return ACTION_TYPE_METADATA.get(canonical or "", {}).get("category")


def metadata_for_action_type(action_type: str | None) -> dict[str, str] | None:
	return ACTION_TYPE_METADATA.get(action_type or "")


def display_name_for_wire_action_code(code: str | None) -> str | None:
	"""The canonical Vietnamese display name for a wire action code.

	``code`` may carry the ``ACT-<CODE>`` wire prefix (see
	``crm.fcrm.nba_policy.wire_action_id``); this strips it before the
	catalog lookup. Falls back to the raw code when the catalog has no entry,
	rather than failing over an unmapped/legacy code.
	"""
	if not code:
		return code
	catalog_code = code[4:] if code.startswith("ACT-") else code
	metadata = metadata_for_action_type(canonicalize_action_type(catalog_code))
	return metadata["display_name"] if metadata else code
