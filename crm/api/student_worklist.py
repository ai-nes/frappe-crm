"""Session-scoped, permission-filtered CRM Recommendation worklist."""

import base64
import binascii
import hashlib
import hmac
import json
import time

import frappe
from frappe import _
from frappe.utils.password import get_encryption_key


_ACTIVE_STATUSES = ("new", "acknowledged")
_MAX_PAGE_SIZE = 50
_CURSOR_TTL_SECONDS = 300
_POLICY_VERSION = "worklist-v1"
_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


@frappe.whitelist()
def list_student_worklist(cursor: str | None = None, page_size: int | str = 20) -> dict:
	"""Return one deterministic page of recommendations visible to this session.

	This endpoint intentionally has no user, campus, or role arguments. Frappe's
	permission-aware list API applies the delegated session user's row scope.
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication is required."), frappe.PermissionError)
	if frappe.conf.get("crm_student_worklist_enabled", 1) in (0, "0", False):
		frappe.throw(_("Student worklist is disabled by rollout policy."), frappe.PermissionError)

	page_size = _parse_page_size(page_size)
	principal = frappe.session.user
	roles = sorted(frappe.get_roles(principal))
	last_sort_key = _decode_cursor(cursor, principal, roles) if cursor else None

	candidates = _fetch_page(principal, last_sort_key, page_size + 1)
	page = candidates[:page_size]
	has_more = len(candidates) > len(page)
	return {
		"items": [_minimal_dto(row) for row in page],
		"next_cursor": _encode_cursor(_sort_key(page[-1]), principal, roles) if page and has_more else None,
		"policy_version": _POLICY_VERSION,
	}


@frappe.whitelist()
def list_my_sales_actions(cursor: str | None = None, page_size: int | str = 20) -> dict:
	"""Durable executor queue; never accepts an assignee or scope from clients."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication is required."), frappe.PermissionError)
	page_size = _parse_page_size(page_size)
	staff = frappe.db.get_value("CRM Staff", {"user": frappe.session.user}, "name")
	if not staff:
		return {"items": [], "next_cursor": None, "policy_version": "phase6-worklist-v1"}
	# Action rows are scoped twice: by their immutable assignee and Frappe's
	# document permission hook (which is the canonical Student scope today).
	from frappe.model.db_query import DatabaseQuery
	permission_query = DatabaseQuery("CRM Sales Action", user=frappe.session.user).build_match_conditions(as_condition=True)
	conditions = ["a.assignee_staff = %(staff)s", "a.execution_status in ('planned', 'in_progress')"]
	if permission_query:
		conditions.append("(" + permission_query.replace("`tabCRM Sales Action`", "a") + ")")
	last_action = _decode_action_cursor(cursor, frappe.session.user) if cursor else None
	due_expr = "COALESCE(a.due_at, '9999-12-31 23:59:59.999999')"
	conditions.append(f"({due_expr} > %(after_due)s OR ({due_expr} = %(after_due)s AND a.creation > %(after_creation)s) OR ({due_expr} = %(after_due)s AND a.creation = %(after_creation)s AND a.name > %(after_name)s))") if last_action else None
	values = {"staff": staff, "limit": page_size + 1, "after_due": last_action[0] if last_action else "0001-01-01 00:00:00", "after_creation": last_action[1] if last_action else "0001-01-01 00:00:00", "after_name": last_action[2] if last_action else ""}
	rows = frappe.db.sql(
		"""select a.name, a.student, s.student_name, a.action_type, a.execution_status,
		a.due_at, {due_expr} as due_sort, a.assignee_staff, a.action_revision, a.linked_interaction, a.creation,
		a.outcome_code from `tabCRM Sales Action` a
		left join `tabCRM Student` s on s.name = a.student where {where}
		order by due_sort asc, a.creation asc, a.name asc limit %(limit)s""".format(where=" and ".join(conditions), due_expr=due_expr),
		values, as_dict=True,
	)
	has_more = len(rows) > page_size
	rows = rows[:page_size]
	now = frappe.utils.now_datetime()
	items = []
	for row in rows:
		items.append({"name": row.name, "student": row.student, "student_name": row.student_name,
			"action_type": row.action_type, "execution_status": row.execution_status, "due_at": str(row.due_at) if row.due_at else None,
			"assignee_staff": row.assignee_staff, "revision": int(row.action_revision or 1),
			"overdue": bool(row.due_at and row.due_at < now), "linked_interaction": row.linked_interaction,
			"outcome": row.outcome_code, "outcome_codes": [
				"NO_RESPONSE", "INTEREST_INCREASED", "NEEDS_MORE_INFORMATION", "CALL_BACK_LATER",
				"APPLICATION_STARTED", "APPLICATION_COMPLETED", "NOT_INTERESTED",
			], "permitted_transitions": sorted(_action_transitions(row.execution_status))})
	return {"items": items, "next_cursor": _encode_action_cursor(rows[-1], frappe.session.user) if has_more and rows else None, "policy_version": "phase6-worklist-v1"}


def _action_transitions(status):
	return {"planned": {"in_progress", "cancelled"}, "in_progress": {"completed", "failed", "cancelled"}}.get(status, set())


def _encode_action_cursor(row, principal):
	payload = {"principal": principal, "policy": "phase6-worklist-v1", "due": str(row.due_sort), "creation": str(row.creation), "name": row.name}
	body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
	signature = hmac.new(_cursor_secret(), body, hashlib.sha256).digest()
	return f"{_urlsafe_encode(body)}.{_urlsafe_encode(signature)}"


def _decode_action_cursor(cursor, principal):
	try:
		body_token, signature_token = cursor.split(".", 1)
		body = _urlsafe_decode(body_token)
		signature = _urlsafe_decode(signature_token)
		if not hmac.compare_digest(signature, hmac.new(_cursor_secret(), body, hashlib.sha256).digest()):
			raise ValueError
		payload = json.loads(body)
		if payload.get("principal") != principal or payload.get("policy") != "phase6-worklist-v1":
			raise ValueError
		return str(payload["due"]), str(payload["creation"]), str(payload["name"])
	except (AttributeError, TypeError, ValueError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError):
		frappe.throw(_("Invalid or expired Sales Action cursor."), frappe.PermissionError)


def _parse_page_size(value: int | str) -> int:
	try:
		page_size = int(value)
	except (TypeError, ValueError):
		frappe.throw(_("page_size must be an integer."), frappe.ValidationError)
	if page_size < 1 or page_size > _MAX_PAGE_SIZE:
		frappe.throw(_("page_size must be between 1 and {0}.").format(_MAX_PAGE_SIZE), frappe.ValidationError)
	return page_size


def _sort_key(row) -> tuple[int, str, str, str]:
	"""Explicit ordering: priority, due timing, creation, then stable ID."""
	priority = _PRIORITY_ORDER.get(row.priority, len(_PRIORITY_ORDER))
	# A missing recommendation time is not fabricated as urgency; it sorts after
	# scheduled work at the same priority, then creation provides a stable tie.
	timing = str(
		getattr(row, "worklist_timing_sort", None)
		or row.recommended_timing
		or "9999-12-31 23:59:59.999999"
	)
	return priority, timing, str(row.creation), str(row.name)


def _minimal_dto(row) -> dict:
	return {
		"recommendation": row.name,
		"student": row.student,
		"student_name": row.student_name,
		"priority": row.priority,
		"action": row.recommended_action,
		"timing": str(row.recommended_timing) if row.recommended_timing else None,
		"reason": row.reason,
		"revision": int(row.decision_revision or 0) if getattr(row, "decision_revision", None) is not None else str(row.modified),
		"permitted_decisions": ["accepted", "deferred", "rejected"],
	}


def _cursor_secret() -> bytes:
	# The Frappe site encryption key is per-site and never returned to callers.
	return f"crm-worklist-cursor:{get_encryption_key()}".encode()


def _fetch_page(principal: str, last_sort_key: list | None, limit: int) -> list:
	"""Keyset query with Frappe's own permission condition, never an offset scan."""
	from frappe.model.db_query import DatabaseQuery

	frappe.has_permission("CRM Recommendation", "read", user=principal, throw=True)
	permission_query = DatabaseQuery("CRM Recommendation", user=principal).build_match_conditions(as_condition=True)
	fields = {field.fieldname for field in frappe.get_meta("CRM Recommendation").fields}
	values = {"statuses": _ACTIVE_STATUSES, "limit": limit, "now": frappe.utils.now_datetime()}
	if "revisit_at" in fields:
		conditions = [
			"(`tabCRM Recommendation`.status IN %(statuses)s OR ("
			"`tabCRM Recommendation`.status = 'deferred' AND "
			"`tabCRM Recommendation`.revisit_at IS NOT NULL AND "
			"`tabCRM Recommendation`.revisit_at <= %(now)s))"
		]
		timing_expr = "COALESCE(`tabCRM Recommendation`.revisit_at, `tabCRM Recommendation`.worklist_timing_sort)"
	else:
		conditions = ["`tabCRM Recommendation`.status IN %(statuses)s"]
		timing_expr = "`tabCRM Recommendation`.worklist_timing_sort"
	if permission_query:
		conditions.append(f"({permission_query})")
	if last_sort_key:
		conditions.append(
			"""(
				`tabCRM Recommendation`.worklist_priority_rank > %(rank)s
				OR (`tabCRM Recommendation`.worklist_priority_rank = %(rank)s AND {timing_expr} > %(timing)s)
				OR (`tabCRM Recommendation`.worklist_priority_rank = %(rank)s AND {timing_expr} = %(timing)s AND `tabCRM Recommendation`.creation > %(creation)s)
				OR (`tabCRM Recommendation`.worklist_priority_rank = %(rank)s AND {timing_expr} = %(timing)s AND `tabCRM Recommendation`.creation = %(creation)s AND `tabCRM Recommendation`.name > %(name)s)
			)"""
			.format(timing_expr=timing_expr)
		)
		values.update(dict(zip(("rank", "timing", "creation", "name"), last_sort_key)))
	return frappe.db.sql(
		"""SELECT `tabCRM Recommendation`.name, `tabCRM Recommendation`.student, `tabCRM Student`.student_name,
		`tabCRM Recommendation`.priority, `tabCRM Recommendation`.recommended_action,
		`tabCRM Recommendation`.recommended_timing, `tabCRM Recommendation`.reason,
		`tabCRM Recommendation`.modified, `tabCRM Recommendation`.decision_revision, `tabCRM Recommendation`.creation,
		{timing_expr} AS worklist_timing_sort
		FROM `tabCRM Recommendation`
		INNER JOIN `tabCRM Student` ON `tabCRM Student`.name = `tabCRM Recommendation`.student
		WHERE {conditions}
		ORDER BY `tabCRM Recommendation`.worklist_priority_rank ASC, {timing_expr} ASC,
		`tabCRM Recommendation`.creation ASC, `tabCRM Recommendation`.name ASC
		LIMIT %(limit)s""".format(conditions=" AND ".join(conditions), timing_expr=timing_expr),
		values,
		as_dict=True,
	)


def _encode_cursor(sort_key: tuple[int, str, str, str], principal: str, roles: list[str]) -> str:
	payload = {
		"expires_at": int(time.time()) + _CURSOR_TTL_SECONDS,
		"last_sort_key": list(sort_key),
		"policy_version": _POLICY_VERSION,
		"principal": principal,
		"roles": roles,
	}
	body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
	signature = hmac.new(_cursor_secret(), body, hashlib.sha256).digest()
	return f"{_urlsafe_encode(body)}.{_urlsafe_encode(signature)}"


def _decode_cursor(cursor: str, principal: str, roles: list[str]) -> list:
	try:
		encoded_body, encoded_signature = cursor.split(".", 1)
		body = _urlsafe_decode(encoded_body)
		signature = _urlsafe_decode(encoded_signature)
		# Reject non-canonical base64 too: changing ignored trailing bits must
		# not turn a tampered textual cursor into the same decoded signature.
		if _urlsafe_encode(body) != encoded_body or _urlsafe_encode(signature) != encoded_signature:
			raise ValueError
		expected = hmac.new(_cursor_secret(), body, hashlib.sha256).digest()
		payload = json.loads(body)
		if not hmac.compare_digest(signature, expected):
			raise ValueError
		if (
			payload.get("principal") != principal
			or payload.get("roles") != roles
			or payload.get("policy_version") != _POLICY_VERSION
			or payload.get("expires_at", 0) < time.time()
			or not _is_sort_key(payload.get("last_sort_key"))
		):
			raise ValueError
		return payload["last_sort_key"]
	except (AttributeError, TypeError, ValueError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError):
		frappe.throw(_("Invalid or expired worklist cursor."), frappe.PermissionError)


def _urlsafe_encode(value: bytes) -> str:
	return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _urlsafe_decode(value: str) -> bytes:
	return base64.urlsafe_b64decode(f"{value}{'=' * (-len(value) % 4)}")


def _is_sort_key(value) -> bool:
	return (
		isinstance(value, list)
		and len(value) == 4
		and isinstance(value[0], int)
		and not isinstance(value[0], bool)
		and all(isinstance(part, str) for part in value[1:])
	)
