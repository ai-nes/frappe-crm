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


def _label(value, fallback: str) -> str:
	value = " ".join(str(value or "").split())
	return value[:140] or fallback


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
	intent = _label(intent_type, "current admission")
	journey = _label(stage, "current")
	if not eligible:
		return None, f"Monitor the student's {intent} need while the {journey} lifecycle is not eligible for outreach.", False

	requested = None
	lower_intent = intent.casefold()
	for keywords, action in _KEYWORD_ACTIONS:
		if any(keyword in lower_intent for keyword in keywords):
			requested = action
			break
	if requested == "PARENT_CONTACT" and not parent_authorized:
		return None, (
			f"Do not contact a parent for the student's {intent} request until verified Parent Contact Authority is available."
		), False

	if requested not in allowed_actions:
		requested = "CALL" if "CALL" in allowed_actions else (allowed_actions[0] if allowed_actions else None)
	if requested is None:
		return None, f"Monitor the student's {intent} need at the {journey} stage until an authorized action is available.", False
	return (
		requested,
		f"Resolve the student's {intent} need at the {journey} stage and agree one governed next step.",
		True,
	)
