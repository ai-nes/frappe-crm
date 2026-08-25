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
	# V2 is the canonical worklist after cutover. The legacy Recommendation
	# query helpers below remain import-compatible for historical/read-side
	# maintenance, but no runtime config selects them anymore.
	return _list_v2_student_worklist(cursor, page_size)


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
		"student_name": row.student_name,
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
	permission_query = DatabaseQuery("CRM Recommendation", user=principal).build_match_conditions(
		as_condition=True
	)
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
		values.update(dict(zip(("rank", "timing", "creation", "name"), last_sort_key, strict=True)))
	return frappe.db.sql(
		"""SELECT `tabCRM Recommendation`.name, `tabCRM Student`.student_name,
		`tabCRM Recommendation`.priority, `tabCRM Recommendation`.recommended_action,
		`tabCRM Recommendation`.recommended_timing, `tabCRM Recommendation`.reason,
		`tabCRM Recommendation`.modified, `tabCRM Recommendation`.creation
		FROM `tabCRM Recommendation`
		INNER JOIN `tabCRM Student` ON `tabCRM Student`.name = `tabCRM Recommendation`.student
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


_V2_POLICY_VERSION = "worklist-v2"


def _scope_version(principal: str) -> str:
	"""Deployment-controlled scope epoch; assignment/revocation jobs bump it."""
	return str(frappe.cache().get_value(f"crm:student-worklist-scope:{principal}") or "0")


def _list_v2_student_worklist(cursor: str | None, page_size: int | str) -> dict:
	page_size = _parse_page_size(page_size)
	principal = frappe.session.user
	roles = sorted(frappe.get_roles(principal))
	scope_version = _scope_version(principal)
	last = _decode_v2_cursor(cursor, principal, roles, scope_version) if cursor else None
	from frappe.model.db_query import DatabaseQuery

	permission_query = DatabaseQuery("CRM Student", user=principal).build_match_conditions(as_condition=True)
	conditions = [
		"task.current_slot = 'CURRENT'",
		"task.state IN ('PENDING', 'REQUIRES_REVIEW', 'ACCEPTED', 'IN_PROGRESS')",
	]
	if permission_query:
		conditions.append(f"({permission_query.replace('`tabCRM Student`', 'student')})")
	values = {"limit": page_size + 1}
	if last:
		conditions.append(
			"(task.creation > %(creation)s OR (task.creation = %(creation)s AND task.name > %(name)s))"
		)
		values.update({"creation": last[0], "name": last[1]})
	rows = frappe.db.sql(
		"""SELECT task.name, task.student, student.student_name, task.disposition, task.action_type,
			task.objective, task.state, task.requires_review, task.generation_status, task.generation_failed_at,
			task.source_context_revision, task.modified, task.creation,
			task.sales_action
			FROM `tabCRM Student Task` task INNER JOIN `tabCRM Student` student ON student.name = task.student
			WHERE {conditions} ORDER BY task.creation ASC, task.name ASC LIMIT %(limit)s""".format(
			conditions=" AND ".join(conditions)
		),
		values,
		as_dict=True,
	)
	page = rows[:page_size]
	return {
		"items": [
			{
				"task": row.name,
				"student": row.student,
				"student_name": row.student_name,
				"disposition": row.disposition,
				"action_type": row.action_type,
				"objective": row.objective,
				"state": row.state,
				"requires_review": bool(row.requires_review),
				"generation_status": row.generation_status,
				"generation_failed_at": str(row.generation_failed_at) if row.generation_failed_at else None,
				"source_context_revision": row.source_context_revision,
				"revision": str(row.modified),
				"sales_action": row.sales_action,
			}
			for row in page
		],
		"next_cursor": _encode_v2_cursor(
			(str(page[-1].creation), str(page[-1].name)), principal, roles, scope_version
		)
		if len(rows) > len(page) and page
		else None,
		"policy_version": _V2_POLICY_VERSION,
		"scope_version": scope_version,
	}


def _encode_v2_cursor(sort_key, principal: str, roles: list[str], scope_version: str) -> str:
	payload = {
		"expires_at": int(time.time()) + _CURSOR_TTL_SECONDS,
		"last_sort_key": list(sort_key),
		"policy_version": _V2_POLICY_VERSION,
		"principal": principal,
		"roles": roles,
		"scope_version": scope_version,
	}
	body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
	signature = hmac.new(_cursor_secret(), body, hashlib.sha256).digest()
	return f"{_urlsafe_encode(body)}.{_urlsafe_encode(signature)}"


def _decode_v2_cursor(cursor: str, principal: str, roles: list[str], scope_version: str) -> list:
	try:
		encoded_body, encoded_signature = cursor.split(".", 1)
		body, signature = _urlsafe_decode(encoded_body), _urlsafe_decode(encoded_signature)
		payload = json.loads(body)
		expected = hmac.new(_cursor_secret(), body, hashlib.sha256).digest()
		if (
			not hmac.compare_digest(signature, expected)
			or payload.get("principal") != principal
			or payload.get("roles") != roles
			or payload.get("scope_version") != scope_version
			or payload.get("policy_version") != _V2_POLICY_VERSION
			or payload.get("expires_at", 0) < time.time()
			or not _is_v2_sort_key(payload.get("last_sort_key"))
		):
			raise ValueError
		return payload["last_sort_key"]
	except (AttributeError, TypeError, ValueError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError):
		frappe.throw(_("Invalid or expired worklist cursor."), frappe.PermissionError)


def _is_v2_sort_key(value) -> bool:
	return isinstance(value, list) and len(value) == 2 and all(isinstance(part, str) for part in value)
