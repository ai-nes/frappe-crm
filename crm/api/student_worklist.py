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
	timing = str(row.recommended_timing or "9999-12-31 23:59:59.999999")
	return priority, timing, str(row.creation), str(row.name)


def _minimal_dto(row) -> dict:
	return {
		"recommendation": row.name,
		"student": row.student,
		"priority": row.priority,
		"action": row.recommended_action,
		"timing": str(row.recommended_timing) if row.recommended_timing else None,
		"reason": row.reason,
		"revision": str(row.modified),
	}


def _cursor_secret() -> bytes:
	# The Frappe site encryption key is per-site and never returned to callers.
	return f"crm-worklist-cursor:{get_encryption_key()}".encode()


def _fetch_page(principal: str, last_sort_key: list | None, limit: int) -> list:
	"""Keyset query with Frappe's own permission condition, never an offset scan."""
	from frappe.model.db_query import DatabaseQuery

	frappe.has_permission("CRM Recommendation", "read", user=principal, throw=True)
	permission_query = DatabaseQuery("CRM Recommendation", user=principal).build_match_conditions(as_condition=True)
	conditions = ["status IN %(statuses)s"]
	values = {"statuses": _ACTIVE_STATUSES, "limit": limit}
	if permission_query:
		conditions.append(f"({permission_query})")
	if last_sort_key:
		conditions.append(
			"""(
				worklist_priority_rank > %(rank)s
				OR (worklist_priority_rank = %(rank)s AND worklist_timing_sort > %(timing)s)
				OR (worklist_priority_rank = %(rank)s AND worklist_timing_sort = %(timing)s AND creation > %(creation)s)
				OR (worklist_priority_rank = %(rank)s AND worklist_timing_sort = %(timing)s AND creation = %(creation)s AND name > %(name)s)
			)"""
		)
		values.update(dict(zip(("rank", "timing", "creation", "name"), last_sort_key)))
	return frappe.db.sql(
		"""SELECT name, student, priority, recommended_action, recommended_timing, reason, modified, creation
		FROM `tabCRM Recommendation`
		WHERE {conditions}
		ORDER BY worklist_priority_rank ASC, worklist_timing_sort ASC, creation ASC, name ASC
		LIMIT %(limit)s""".format(conditions=" AND ".join(conditions)),
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
