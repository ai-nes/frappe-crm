"""Session-scoped, permission-filtered canonical CRM Action worklist."""

import base64
import binascii
import hashlib
import hmac
import json
import time

import frappe
from frappe import _
from frappe.exceptions import QueryDeadlockError, QueryTimeoutError
from frappe.utils.password import get_encryption_key
from pymysql import MySQLError

from crm.api.nba_recommendation_view import recommendation_view

_MAX_PAGE_SIZE = 50
_CURSOR_TTL_SECONDS = 300
_POLICY_VERSION = "worklist-v1"
_RECOMMENDATION_WORKLIST_POLICY_VERSION = "recommendation-worklist-v1"
_NBA_TERMINAL_STATES = ("completed", "cancelled", "rejected", "superseded")
_NBA_SOURCE_ERRORS = (QueryDeadlockError, QueryTimeoutError, MySQLError)


@frappe.whitelist()
def list_student_worklist(
	cursor: str | None = None,
	page_size: int | str = 20,
	student_id: str | None = None,
) -> dict:
	"""Return one deterministic page of the session's pending ``CRM Recommendation``
	review queue -- the immutable AI proposal awaiting a Sales decision, not a
	pending Action Item. Legacy rows with no ``evaluation`` link never appear.

	The optional ``student_id`` narrows the same permission-aware queue to one
	Student. It never widens scope: ``CRM Recommendation``'s own permission
	condition still applies through the target Student.
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication is required."), frappe.PermissionError)
	if frappe.conf.get("crm_student_worklist_enabled", 1) in (0, "0", False):
		frappe.throw(_("Student worklist is disabled by rollout policy."), frappe.PermissionError)
	if student_id is not None:
		if not isinstance(student_id, str) or not student_id.strip() or len(student_id.strip()) > 140:
			frappe.throw(_("Mã học sinh không hợp lệ."), frappe.ValidationError)
		student_id = student_id.strip()

	page_size = _parse_page_size(page_size)
	principal = frappe.session.user
	# The recommendation hook also scopes through CRM Lead, but keep the
	# aggregate permission explicit so this endpoint cannot become a side door
	# if recommendation storage or its hook changes later.
	frappe.has_permission("CRM Lead", "read", user=principal, throw=True)
	roles = sorted(frappe.get_roles(principal))
	last_sort_key = (
		_decode_cursor(cursor, principal, roles, policy_version=_RECOMMENDATION_WORKLIST_POLICY_VERSION)
		if cursor
		else None
	)

	candidates = _fetch_recommendation_page(
		principal,
		last_sort_key,
		page_size + 1,
		student_id=student_id,
	)
	page = candidates[:page_size]
	has_more = len(candidates) > len(page)
	evaluations = _recommendation_evaluation_lookup(page)
	return {
		"items": [_recommendation_dto(row, evaluations) for row in page],
		"next_cursor": (
			_encode_cursor(
				_recommendation_sort_key(page[-1]),
				principal,
				roles,
				policy_version=_RECOMMENDATION_WORKLIST_POLICY_VERSION,
			)
			if page and has_more
			else None
		),
		"policy_version": _RECOMMENDATION_WORKLIST_POLICY_VERSION,
	}


@frappe.whitelist()
def list_actions_for_record(doctype: str, name: str, page_size: int | str = 20) -> dict:
	"""Return permission-filtered canonical Actions for Student or Contact detail."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication is required."), frappe.PermissionError)
	if doctype not in {"CRM Lead", "CRM Student"} or not isinstance(name, str) or not name.strip():
		frappe.throw(_("A valid Student or Contact is required."), frappe.ValidationError)
	name = name.strip()
	page_size = _parse_page_size(page_size)
	if doctype == "CRM Lead":
		_ensure_visible_student(name)
	frappe.has_permission("CRM Action Item", "read", user=frappe.session.user, throw=True)
	# `get_list` applies CRM Action's permission query conditions; `get_all`
	# would allow a caller to probe another student's objective/evidence by name.
	rows = frappe.get_list("CRM Action Item", filters={"student" if doctype == "CRM Lead" else "contact": name}, fields=["name", "student", "action", "action_type", "objective", "state", "execution_status", "priority", "due_at", "action_owner", "origin", "action_revision"], order_by="creation desc", limit_page_length=page_size)
	now = frappe.utils.now_datetime()
	return {"items": [{"name": row.name, "student": row.student, "action": row.action, "action_type": row.action_type, "objective": row.objective, "state": row.state, "execution_status": row.execution_status, "priority": row.priority, "due_at": str(row.due_at) if row.due_at else None, "action_owner": row.action_owner, "origin": row.origin, "revision": int(row.action_revision or 1), "is_today": bool(row.due_at and row.due_at.date() == now.date()), "is_overdue": bool(row.due_at and row.due_at < now and row.state not in {"completed", "cancelled", "rejected", "superseded"})} for row in rows], "policy_version": _POLICY_VERSION}


@frappe.whitelist(methods=["GET"])
def get_next_best_action_for_student(student_id: str | None = None) -> dict:
	"""Return the newest active CRM Action for one permission-visible Student.

	This is a read-only Student detail projection. The Student lookup deliberately
	uses ``get_list`` so an out-of-scope Student is indistinguishable from a
	non-existent one, while the Action lookup applies CRM Action row permissions.
	"""
	if frappe.session.user == "Guest":
		_raise_api_error("UNAUTHENTICATED", "Authentication is required.", frappe.AuthenticationError, 401)
	if not isinstance(student_id, str) or not student_id.strip():
		_raise_api_error("INVALID_STUDENT_ID", "Mã học sinh không hợp lệ.", frappe.ValidationError, 400)

	student_id = student_id.strip()
	try:
		_ensure_visible_student(student_id)
		frappe.has_permission("CRM Action Item", "read", user=frappe.session.user, throw=True)
		rows = frappe.get_list(
			"CRM Action Item",
			filters={
				"student": student_id,
				"state": ["not in", list(_NBA_TERMINAL_STATES)],
			},
			fields=[
				"name",
				"student",
				"action",
				"action_type",
				"objective",
				"state",
				"execution_status",
				"priority",
				"due_at",
				"action_owner",
				"origin",
				"action_revision",
			],
			order_by="creation desc, modified desc",
			limit_page_length=1,
		)
	except frappe.PermissionError:
		_raise_api_error(
			"FORBIDDEN",
			"Bạn không có quyền đọc dữ liệu học sinh hoặc action.",
			frappe.PermissionError,
			403,
		)
	except _NBA_SOURCE_ERRORS:
		_raise_api_error(
			"STUDENT_NBA_UNAVAILABLE",
			"Không thể tải NBA của học sinh.",
			frappe.ValidationError,
			503,
		)

	return {
		"student_id": student_id,
		"nba": _serialize_nba(rows[0] if rows else None),
		"policy_version": _POLICY_VERSION,
	}


_ACTION_QUEUE_CONTRACT = "action-queue-row-v1"


@frappe.whitelist()
def list_action_queue(page_size: int | str = 20, student: str | None = None) -> dict:
	"""Permission-aware care-queue read-model (``ActionQueueRowV1``).

	Returns one page of current-slot canonical Actions the session may see, with
	a derived ``queue_status`` and the ``can_*`` action hints. Out-of-scope
	students never appear -- ``get_list`` applies CRM Action's permission query.

	The ``can_*`` flags are **display hints only**. Every dispatch
	(claim / decide / transition / reassign) independently re-checks the caller's
	permission and the Action's current ``action_revision`` / ``decision_revision``
	server-side, regardless of what a row here reported.
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication is required."), frappe.PermissionError)
	if frappe.conf.get("crm_student_action_queue_enabled", 1) in (0, "0", False):
		frappe.throw(_("Action queue is disabled by rollout policy."), frappe.PermissionError)
	page_size = _parse_page_size(page_size)
	if student is not None and (not isinstance(student, str) or not student.strip()):
		frappe.throw(_("student must be a Student name."), frappe.ValidationError)
	frappe.has_permission("CRM Lead", "read", user=frappe.session.user, throw=True)
	frappe.has_permission("CRM Action Item", "read", user=frappe.session.user, throw=True)

	from crm.fcrm.role_policy import capabilities_for_roles
	from crm.fcrm.student_decision import claim_grants_execute

	actor = frappe.session.user
	caps = set(
		capabilities_for_roles(frappe.get_roles(actor), administrator=actor == "Administrator")
	)
	is_admin = actor == "Administrator"
	my_staff = frappe.db.get_value("CRM Staff", {"user": actor}, "name")

	filters = {"current_slot": "CURRENT"}
	if student:
		filters["student"] = student
	rows = frappe.get_list(
		"CRM Action Item",
		filters=filters,
		fields=[
			"name", "student", "action", "action_type", "state", "execution_status", "action_owner",
			"risk_tier", "action_revision", "decision_revision", "source_context_revision",
			"revisit_at", "modified",
		],
		order_by="worklist_priority_rank asc, modified desc",
		limit_page_length=page_size,
	)
	student_names = {row.student for row in rows}
	context_revisions = {
		r.name: int(r.student_context_revision or 0)
		for r in frappe.get_list(
			"CRM Lead",
			filters={"name": ["in", list(student_names)]} if student_names else {"name": ["in", [""]]},
			fields=["name", "student_context_revision"],
			limit_page_length=0,
		)
	}
	# `can_claim` is the real _valid_executor rule; resolve it once per Student.
	claimable = {name: claim_grants_execute(name, actor) for name in student_names}
	now = frappe.utils.now_datetime()
	items = [
		_action_queue_row(row, caps, is_admin, my_staff, now, context_revisions, claimable)
		for row in rows
	]
	return {"items": items, "contract_version": _ACTION_QUEUE_CONTRACT, "policy_version": _POLICY_VERSION}


_ACTION_VIEW_MODEL_CONTRACT = "actionviewmodel:v1"
_SAFE_PACKAGE_KEYS = {
	"CALL": {"objective", "opening", "talking_points", "questions", "objections", "desired_outcome", "next_step"},
	"EMAIL": {"template_version", "cta"},
}


@frappe.whitelist()
def get_action_workbench(action: str, expected_action_revision: int | str | None = None) -> dict:
	"""Return one permission-scoped, Frappe-owned ActionViewModelV1 card.

	The queue identity is the only client-selected lookup.  Package and outcome
	fields are projected here, never through generic Action/Revision reads.
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication is required."), frappe.PermissionError)
	if not isinstance(action, str) or not action.strip():
		frappe.throw(_("A valid Action is required."), frappe.ValidationError)
	frappe.has_permission("CRM Action Item", "read", user=frappe.session.user, throw=True)
	try:
		doc = frappe.get_doc("CRM Action Item", action.strip())
	except Exception:
		frappe.throw(_("Action is not available."), frappe.PermissionError)
	if not doc.has_permission("read") or doc.current_slot != "CURRENT":
		frappe.throw(_("Action is not available."), frappe.PermissionError)
	action_revision = int(doc.action_revision or 1)
	if expected_action_revision is not None and int(expected_action_revision) != action_revision:
		frappe.throw(_("Action changed; refresh before opening."), frappe.ValidationError)

	from crm.services.sales_action_policy import allowed_operations

	roles = set(frappe.get_roles(frappe.session.user))
	package_revision = int(doc.execution_package_version or 0)
	package = _latest_safe_package(doc, package_revision) if frappe.conf.get("crm_action_pii_controls_enabled", 0) in (1, "1", True) else {}
	action_code = doc.get("action") or doc.action_type
	action_type = action_code if action_code in _SAFE_PACKAGE_KEYS else "UNKNOWN"
	return {
		"contract_version": _ACTION_VIEW_MODEL_CONTRACT,
		"action_id": doc.name,
		"student": doc.student,
		"action_revision": action_revision,
		"package_revision": package_revision,
		"freshness": _action_freshness(doc),
		"what": {"title": action_code or "Action", "body": doc.objective},
		"why": {"title": "Why this action", "body": doc.objective},
		"how": {"title": "How", "body": "Use the Frappe-approved action workflow."},
		"goal": {"title": "Goal", "body": doc.objective},
		"action": {"title": "Action", "body": "Review the current action and choose an allowed operation."},
		"allowed_operations": allowed_operations(doc, actor_roles=roles),
		"package": {"schema": _package_schema(action_type), "revision": package_revision, "data": package},
	}


def _latest_safe_package(doc, revision: int) -> dict:
	action_code = doc.get("action") or doc.action_type
	if not revision or action_code not in _SAFE_PACKAGE_KEYS:
		return {}
	rows = frappe.get_all(
		"CRM Action Revision", filters={"action": doc.name, "revision": revision},
		fields=["package"], limit_page_length=1,
	)
	value = rows[0].package if rows else doc.package_seed
	if isinstance(value, str):
		value = frappe.parse_json(value) if value else {}
	if not isinstance(value, dict):
		return {}
	return {key: value[key] for key in _SAFE_PACKAGE_KEYS[action_code] if key in value}


def _package_schema(action_type: str) -> str | None:
	return {"CALL": "call-package:v1", "EMAIL": "email-package:v1"}.get(action_type)


def _action_freshness(doc) -> dict:
	modified = getattr(doc, "modified", None)
	if not modified:
		return {"label": "unknown", "as_of": None, "age_seconds": None, "context_current": None}
	age = max(0, int((frappe.utils.now_datetime() - modified).total_seconds()))
	return {"label": "fresh" if age < 86400 else "aging" if age < 259200 else "stale", "as_of": str(modified), "age_seconds": age, "context_current": True}


def _queue_status(state: str, action_owner: str | None, execution_status: str | None) -> str:
	if state == "in-progress" or execution_status == "in_progress":
		return "in_progress"
	if action_owner:
		return "claimed"
	return "unassigned"


def _primary_command(queue_status: str, state: str) -> str:
	if queue_status == "unassigned":
		return "claim"
	if queue_status == "in_progress":
		return "complete"
	if state in {"pending", "requires-review"}:
		return "accept"
	if state == "accepted":
		return "start"
	return "view"


def _action_queue_row(
	row, caps: set, is_admin: bool, my_staff: str | None, now, context_revisions: dict, claimable: dict
) -> dict:
	queue_status = _queue_status(row.state, row.action_owner, row.execution_status)
	mine = bool(my_staff and row.action_owner == my_staff)
	context_current = int(row.source_context_revision or 0) >= context_revisions.get(row.student, 0)
	age_seconds = int((now - row.modified).total_seconds()) if row.modified else None
	freshness = {
		"as_of": str(row.modified) if row.modified else None,
		"age_seconds": age_seconds,
		"context_current": context_current,
		"label": _freshness_label(age_seconds, context_current),
	}
	# Real _valid_executor rule (unowned or already in the caller's execute
	# scope), not just "unassigned". A Student already assigned to someone else,
	# with the caller outside the owning team, is not claimable -- the claim
	# would not widen assigned_to and the caller still could not execute.
	can_claim = bool(queue_status == "unassigned" and claimable.get(row.student, False))
	can_approve = bool(is_admin or ({"student.execute", "recommendation.decide"} & caps))
	can_execute = bool((is_admin or ({"student.execute", "action.execute"} & caps)) and (mine or is_admin))
	can_reassign = bool(
		is_admin or ({"action.reassign", "team.oversee", "admissions.oversee"} & caps)
	)
	action_code = row.get("action") or row.action_type
	return {
		"name": row.name,
		"action": row.name,
		"action_code": action_code,
		"student": row.student,
		"action_type": row.action_type,
		"state": row.state,
		"queue_status": queue_status,
		"assignee_ref": row.action_owner,
		"risk_tier": row.risk_tier or "high",
		"revision": int(row.decision_revision or 0),
		"action_revision": int(row.action_revision or 1),
		"can_claim": can_claim,
		"can_approve": can_approve,
		"can_execute": can_execute,
		"can_reassign": can_reassign,
		"primary_command": _primary_command(queue_status, row.state),
		"freshness": freshness,
	}


def _freshness_label(age_seconds: int | None, context_current: bool) -> str:
	if not context_current:
		return "context_moved"
	if age_seconds is None:
		return "unknown"
	if age_seconds < 86400:
		return "fresh"
	if age_seconds < 259200:
		return "aging"
	return "stale"


@frappe.whitelist()
def _list_my_actions(cursor: str | None = None, page_size: int | str = 20) -> dict:
	"""Permission-filtered canonical Action executor queue."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication is required."), frappe.PermissionError)
	page_size = _parse_page_size(page_size)
	frappe.has_permission("CRM Lead", "read", user=frappe.session.user, throw=True)
	frappe.has_permission("CRM Action Item", "read", user=frappe.session.user, throw=True)
	staff = frappe.db.get_value("CRM Staff", {"user": frappe.session.user}, "name")
	if not staff:
		return {"items": [], "next_cursor": None, "policy_version": _POLICY_VERSION}
	from frappe.model.db_query import DatabaseQuery
	permission_query = DatabaseQuery("CRM Action Item", user=frappe.session.user).build_match_conditions(as_condition=True)
	conditions = ["a.action_owner = %(staff)s", "a.state in ('accepted', 'in-progress')"]
	if permission_query:
		conditions.append("(" + permission_query.replace("`tabCRM Action Item`", "a") + ")")
	last_action = _decode_action_cursor(cursor, frappe.session.user) if cursor else None
	due_expr = "COALESCE(a.due_at, '9999-12-31 23:59:59.999999')"
	conditions.append(f"({due_expr} > %(after_due)s OR ({due_expr} = %(after_due)s AND a.creation > %(after_creation)s) OR ({due_expr} = %(after_due)s AND a.creation = %(after_creation)s AND a.name > %(after_name)s))") if last_action else None
	values = {"staff": staff, "limit": page_size + 1, "after_due": last_action[0] if last_action else "0001-01-01 00:00:00", "after_creation": last_action[1] if last_action else "0001-01-01 00:00:00", "after_name": last_action[2] if last_action else ""}
	rows = frappe.db.sql(
		"""select a.name, a.student, s.student_name, a.action, a.action_type, a.execution_status,
		a.due_at, {due_expr} as due_sort, a.action_owner as assignee_staff, a.action_revision, a.linked_interaction, a.creation,
		a.outcome_code from `tabCRM Action Item` a
		left join `tabCRM Lead` s on s.name = a.student where {where}
		order by due_sort asc, a.creation asc, a.name asc limit %(limit)s""".format(where=" and ".join(conditions), due_expr=due_expr),
		values, as_dict=True,
	)
	has_more = len(rows) > page_size
	rows = rows[:page_size]
	now = frappe.utils.now_datetime()
	items = []
	for row in rows:
		items.append({"name": row.name, "action": row.name, "action_code": row.action, "student": row.student, "student_name": row.student_name,
			"action_type": row.action_type, "execution_status": row.execution_status, "due_at": str(row.due_at) if row.due_at else None,
			"assignee_staff": row.assignee_staff, "revision": int(row.action_revision or 1),
			"overdue": bool(row.due_at and row.due_at < now), "linked_interaction": row.linked_interaction,
			"outcome": row.outcome_code, "outcome_codes": [
				"NO_RESPONSE", "INTEREST_INCREASED", "NEEDS_MORE_INFORMATION", "CALL_BACK_LATER",
				"APPLICATION_STARTED", "APPLICATION_COMPLETED", "NOT_INTERESTED",
			], "permitted_transitions": sorted(_action_transitions(row.execution_status))})
	return {"items": items, "next_cursor": _encode_action_cursor(rows[-1], frappe.session.user) if has_more and rows else None, "policy_version": _POLICY_VERSION}


@frappe.whitelist()
def list_my_actions(cursor: str | None = None, page_size: int | str = 20) -> dict:
	"""Canonical Action worklist endpoint for all admissions clients."""
	return _list_my_actions(cursor=cursor, page_size=page_size)


def _action_transitions(status):
	return {"planned": {"in_progress", "cancelled"}, "in_progress": {"completed", "failed", "cancelled"}}.get(status, set())


def _ensure_visible_student(student_id: str) -> None:
	"""Make a named Student lookup obey the current session's row scope."""
	frappe.has_permission("CRM Lead", "read", user=frappe.session.user, throw=True)
	if not frappe.get_list(
		"CRM Lead",
		filters={"name": student_id},
		fields=["name"],
		limit_page_length=1,
	):
		_raise_api_error(
			"STUDENT_NOT_FOUND",
			"Không tìm thấy hồ sơ học sinh.",
			frappe.DoesNotExistError,
			404,
		)


def _serialize_nba(row, now=None) -> dict | None:
	"""Project only the fields required by the Student detail NBA contract."""
	if not row:
		return None

	now = now or frappe.utils.now_datetime()
	due_at = _coerce_nba_datetime(row.get("due_at"))
	return {
		"name": row.get("name"),
		"student": row.get("student"),
		"action": row.get("action") or None,
		"action_type": row.get("action_type") or None,
		"objective": str(row.get("objective") or ""),
		"state": row.get("state"),
		"execution_status": row.get("execution_status") or None,
		"priority": row.get("priority") or "medium",
		"due_at": due_at.strftime("%Y-%m-%d %H:%M:%S") if due_at else None,
		"action_owner": row.get("action_owner") or None,
		"origin": row.get("origin") or None,
		"revision": int(row.get("action_revision") or 1),
		"is_today": bool(due_at and due_at.date() == now.date()),
		"is_overdue": bool(
			due_at and due_at < now and row.get("state") not in _NBA_TERMINAL_STATES
		),
	}


def _coerce_nba_datetime(value):
	if not value:
		return None
	try:
		return frappe.utils.get_datetime(value)
	except (AttributeError, TypeError, ValueError, OverflowError):
		return None


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
		frappe.throw(_("Invalid or expired Action cursor."), frappe.PermissionError)


def _parse_page_size(value: int | str) -> int:
	try:
		page_size = int(value)
	except (TypeError, ValueError):
		frappe.throw(_("page_size must be an integer."), frappe.ValidationError)
	if page_size < 1 or page_size > _MAX_PAGE_SIZE:
		frappe.throw(_("page_size must be between 1 and {0}.").format(_MAX_PAGE_SIZE), frappe.ValidationError)
	return page_size


def _raise_api_error(code: str, message: str, exception, status: int) -> None:
	try:
		if getattr(frappe, "local", None) and isinstance(getattr(frappe.local, "response", None), dict):
			frappe.local.response["error"] = {"code": code, "message": message}
			frappe.local.response["http_status_code"] = status
	except (AttributeError, TypeError):
		pass
	frappe.throw(_(message), exception)


_RECOMMENDATION_SORT_DEFAULT_RANK = 999
_RECOMMENDATION_TIMING_SENTINEL = "9999-12-31 23:59:59.999999"


def _recommendation_sort_key(row) -> tuple[int, str, str, str]:
	"""Explicit ordering: kernel rank, recommended-at timing, creation, then id.

	Must read the same ``rank``/``recommended_at`` columns the SQL ORDER
	BY/keyset predicate in `_fetch_recommendation_page` uses, with the same
	defaults, or the cursor desyncs from the SQL comparison across pages.
	"""
	rank = int(row.rank if row.rank is not None else _RECOMMENDATION_SORT_DEFAULT_RANK)
	timing = str(row.recommended_at or _RECOMMENDATION_TIMING_SENTINEL)
	return rank, timing, str(row.creation), str(row.name)


def _recommendation_dto(row, evaluations: dict[str, dict] | None = None) -> dict:
	"""Project one pending, evaluation-epoch ``CRM Recommendation`` for review.

	The immutable ``ai_payload`` kernel object is surfaced verbatim, matching
	the director read model. ``expected_revision`` carries ``modified`` so the
	client can guard the append-only decision command.
	"""
	payload = _parse_worklist_json(row.get("ai_payload"))
	if not isinstance(payload, dict):
		payload = {}
	explanation = _parse_worklist_json(row.get("explanation"))
	if not isinstance(explanation, dict):
		explanation = None
	evaluation = (evaluations or {}).get(row.get("evaluation")) or {}
	view = recommendation_view(
		recommendation_id=row.name,
		target_type="CRM Lead",
		target_id=row.student,
		action_code=row.get("action") or None,
		priority=row.priority,
		rank=int(row.rank) if row.rank is not None else None,
		reason=row.get("reason"),
		explanation=explanation,
		ai_payload=payload,
		expires_at_iso=str(row.get("expires_at")) if row.get("expires_at") else None,
		lifecycle_status=row.get("lifecycle_status"),
		decision_status=row.get("decision_status"),
		execution_status=row.get("execution_status"),
	)
	return {
		**view,
		# Stable wire compatibility: both keys identify the same recommendation.
		"recommendation": row.name,
		"recommendationKey": row.get("recommendation_key") or None,
		"studentId": row.student,
		"student": row.student,
		"studentName": row.student_name or row.student,
		"actionId": row.get("action") or None,
		"channel": row.get("channel") or None,
		# Immutable kernel recommendation object, surfaced verbatim so the
		# accept/edit decision flow's identity/diff logic keeps its existing
		# source of truth. Not for display -- use the nested view fields above.
		"aiPayload": payload,
		"explanation": explanation,
		"evaluation": {
			"id": row.get("evaluation") or None,
			"disposition": evaluation.get("disposition") or None,
			"status": evaluation.get("status") or None,
		},
		"generatedAt": str(row.recommended_at) if row.recommended_at else str(row.creation),
		# CAS guard for `decide_recommendation`'s `expected_modified` check.
		"expected_revision": str(row.modified) if row.modified else None,
		"revision": str(row.modified) if row.modified else "",
		"permitted_decisions": ["accepted", "deferred", "rejected", "dismissed"],
	}


def _recommendation_evaluation_lookup(rows: list) -> dict[str, dict]:
	"""Parent evaluation disposition/status keyed by evaluation id.

	``CRM NBA Evaluation`` grants row ``read`` to System Manager only, so a real
	Sale / Lead Sale / Director caller has no doctype permission on it at all.
	This is a deliberate service-internal enrichment read, not a fresh access
	grant: every ``evaluation_id`` here was sourced from a ``CRM Recommendation``
	row the caller already passed permission on in ``_fetch_recommendation_page``,
	and only the non-sensitive ``disposition``/``status`` pair is projected. Use
	``get_all`` with ``ignore_permissions`` rather than gating on the caller's
	(absent) doctype permission.
	"""
	evaluation_ids = sorted({row.get("evaluation") for row in rows if row.get("evaluation")})
	if not evaluation_ids:
		return {}
	try:
		found = frappe.get_all(
			"CRM NBA Evaluation",
			filters={"name": ["in", evaluation_ids]},
			fields=["name", "disposition", "status"],
			limit_page_length=0,
			ignore_permissions=True,
		)
	except frappe.DoesNotExistError:
		return {}
	return {row["name"]: row for row in found}


def _parse_worklist_json(value) -> object:
	if value in (None, ""):
		return None
	if isinstance(value, (dict, list)):
		return value
	try:
		return json.loads(value)
	except (TypeError, ValueError):
		return None


def _cursor_secret() -> bytes:
	# The Frappe site encryption key is per-site and never returned to callers.
	return f"crm-worklist-cursor:{get_encryption_key()}".encode()


def _fetch_recommendation_page(
	principal: str,
	last_sort_key: list | None,
	limit: int,
	student_id: str | None = None,
) -> list:
	"""Keyset query with Frappe's own permission condition, never an offset scan.

	Only evaluation-epoch, undecided, unexpired recommendations addressed to a
	Student are returned; legacy pre-cutover rows (no ``evaluation`` link) are
	excluded. ``CRM Recommendation``'s own permission query condition scopes
	rows through the target Student's row-level permissions.
	"""
	from frappe.model.db_query import DatabaseQuery

	frappe.has_permission("CRM Recommendation", "read", user=principal, throw=True)
	permission_query = DatabaseQuery("CRM Recommendation", user=principal).build_match_conditions(
		as_condition=True
	)
	values = {"limit": limit, "now": frappe.utils.now_datetime()}
	conditions = [
		"`tabCRM Recommendation`.target_type = 'CRM Lead'",
		"`tabCRM Recommendation`.decision_status = 'pending'",
		"`tabCRM Recommendation`.evaluation IS NOT NULL AND `tabCRM Recommendation`.evaluation != ''",
		"(`tabCRM Recommendation`.expires_at IS NULL OR `tabCRM Recommendation`.expires_at > %(now)s)",
	]
	if student_id:
		conditions.append("`tabCRM Recommendation`.target_id = %(student_id)s")
		values["student_id"] = student_id
	if permission_query:
		conditions.append(f"({permission_query})")
	if last_sort_key:
		conditions.append(
			"""(
				COALESCE(`tabCRM Recommendation`.rank, 999) > %(rank)s
				OR (COALESCE(`tabCRM Recommendation`.rank, 999) = %(rank)s AND COALESCE(`tabCRM Recommendation`.recommended_at, '9999-12-31 23:59:59.999999') > %(timing)s)
				OR (COALESCE(`tabCRM Recommendation`.rank, 999) = %(rank)s AND COALESCE(`tabCRM Recommendation`.recommended_at, '9999-12-31 23:59:59.999999') = %(timing)s AND `tabCRM Recommendation`.creation > %(creation)s)
				OR (COALESCE(`tabCRM Recommendation`.rank, 999) = %(rank)s AND COALESCE(`tabCRM Recommendation`.recommended_at, '9999-12-31 23:59:59.999999') = %(timing)s AND `tabCRM Recommendation`.creation = %(creation)s AND `tabCRM Recommendation`.name > %(name)s)
			)"""
		)
		values.update(dict(zip(("rank", "timing", "creation", "name"), last_sort_key, strict=True)))
	return frappe.db.sql(
		"""SELECT `tabCRM Recommendation`.name, `tabCRM Recommendation`.target_id AS student,
		`tabCRM Lead`.student_name, `tabCRM Recommendation`.rank, `tabCRM Recommendation`.priority,
		`tabCRM Recommendation`.channel, `tabCRM Recommendation`.reason, `tabCRM Recommendation`.action,
		`tabCRM Recommendation`.recommendation_key, `tabCRM Recommendation`.ai_payload,
		`tabCRM Recommendation`.explanation, `tabCRM Recommendation`.expires_at,
		`tabCRM Recommendation`.lifecycle_status, `tabCRM Recommendation`.decision_status,
		`tabCRM Recommendation`.execution_status,
		`tabCRM Recommendation`.evaluation, `tabCRM Recommendation`.recommended_at,
		`tabCRM Recommendation`.modified, `tabCRM Recommendation`.creation
		FROM `tabCRM Recommendation`
		LEFT JOIN `tabCRM Lead` ON `tabCRM Lead`.name = `tabCRM Recommendation`.target_id
		WHERE {conditions}
		ORDER BY COALESCE(`tabCRM Recommendation`.rank, 999) ASC,
		COALESCE(`tabCRM Recommendation`.recommended_at, '9999-12-31 23:59:59.999999') ASC,
		`tabCRM Recommendation`.creation ASC, `tabCRM Recommendation`.name ASC
		LIMIT %(limit)s""".format(conditions=" AND ".join(conditions)),
		values,
		as_dict=True,
	)


def _encode_cursor(
	sort_key: tuple[int, str, str, str],
	principal: str,
	roles: list[str],
	policy_version: str = _POLICY_VERSION,
) -> str:
	payload = {
		"expires_at": int(time.time()) + _CURSOR_TTL_SECONDS,
		"last_sort_key": list(sort_key),
		"policy_version": policy_version,
		"principal": principal,
		"roles": roles,
	}
	body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
	signature = hmac.new(_cursor_secret(), body, hashlib.sha256).digest()
	return f"{_urlsafe_encode(body)}.{_urlsafe_encode(signature)}"


def _decode_cursor(
	cursor: str, principal: str, roles: list[str], policy_version: str = _POLICY_VERSION
) -> list:
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
			or payload.get("policy_version") != policy_version
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

