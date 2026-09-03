"""Frappe-owned next-task policy for the bounded Student decision projection."""

from __future__ import annotations


_KEYWORD_ACTIONS = (
	(("parent", "phụ huynh", "guardian"), "PARENT_CONTACT"),
	(("document", "documents", "hồ sơ", "giấy tờ"), "DOCUMENT_REQUEST"),
	(("application", "apply", "nộp đơn", "đăng ký"), "APPLICATION_SUPPORT"),
	(("campus", "visit", "tham quan"), "CAMPUS_VISIT"),
	(("open day", "event", "sự kiện", "ngày hội"), "EVENT_INVITE"),
	(("counsel", "tư vấn"), "COUNSELING"),
	(("meeting", "hẹn", "appointment"), "MEETING"),
	(("message", "zalo", "whatsapp"), "MESSAGE"),
	(("email", "mail"), "EMAIL"),
)


_STAGE_LABELS_VI = {
	"lead": "khách hàng tiềm năng",
	"mql": "quan tâm sơ bộ",
	"sql": "đã đủ điều kiện tư vấn",
	"qualified": "đã đủ điều kiện tư vấn",
	"consulting": "đang tư vấn",
	"lost": "đã ngừng theo đuổi",
	"lost opportunity": "đã ngừng theo đuổi",
	"enrolled": "đã nhập học",
	"closed": "đã đóng",
}


def _label(value, fallback: str) -> str:
	value = " ".join(str(value or "").split())
	return value[:140] or fallback


def _journey_label(stage) -> str:
	"""Friendly Vietnamese stage label; falls back to the raw stage string."""
	raw = _label(stage, "hiện tại")
	return _STAGE_LABELS_VI.get(raw.casefold(), raw)


def choose_next_task_policy(
	intent_type: str | None,
	stage: str | None,
	allowed_actions: list[str],
	*,
	eligible: bool = True,
	parent_authorized: bool = False,
) -> tuple[str | None, str, bool]:
	"""Return ``(action, objective, actionable)`` from Frappe-owned facts.

	The service identity receives the result, but does not invent the action
	ordering. Keyword matching is intentionally conservative and falls back to
	CALL only when the policy registry permits it. Parent contact is never a
	fallback and is only selected when authority is already present.
	"""
	# Bare noun phrase: every template below prepends its own noun ("nhu cầu
	# {intent}" / "yêu cầu {intent}"), so the fallback must not repeat it.
	intent = _label(intent_type, "tuyển sinh hiện tại")
	journey = _journey_label(stage)
	if not eligible:
		return None, (
			f"Theo dõi nhu cầu {intent} của học sinh; giai đoạn {journey} chưa đủ điều kiện để chủ động liên hệ."
		), False

	requested = None
	lower_intent = intent.casefold()
	for keywords, action in _KEYWORD_ACTIONS:
		if any(keyword in lower_intent for keyword in keywords):
			requested = action
			break
	if requested == "PARENT_CONTACT" and not parent_authorized:
		return None, (
			f"Chưa liên hệ phụ huynh cho yêu cầu {intent} của học sinh cho đến khi có Thẩm quyền Liên hệ Phụ huynh đã được xác minh."
		), False

	if requested not in allowed_actions:
		requested = "CALL" if "CALL" in allowed_actions else (allowed_actions[0] if allowed_actions else None)
	if requested is None:
		return None, (
			f"Theo dõi nhu cầu {intent} của học sinh ở giai đoạn {journey} cho đến khi có hành động được cho phép."
		), False
	return (
		requested,
		f"Giải quyết nhu cầu {intent} của học sinh ở giai đoạn {journey} và thống nhất một bước tiếp theo được kiểm soát.",
		True,
	)
