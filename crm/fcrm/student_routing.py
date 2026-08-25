"""Transactional Student pool routing service.

The worker owns request leases and policy/cursor resolution.  Ownership still
flows through the Phase 3 command; this module never writes Student ownership
fields directly.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Any

import frappe
from frappe.utils import add_to_date, now_datetime

from crm.fcrm.permissions import has_permission as has_student_permission
from crm.fcrm.role_policy import capabilities_for_roles, resolve_crm_profile
from crm.fcrm.student_ownership import StudentOwnershipError, change_student_ownership
from crm.fcrm.student_feature_flags import enabled


REQUEST_DOCTYPE = "CRM Student Routing Request"
SERVICE_FLAG = "student_routing_service"
LEASE_MINUTES = 5


class StudentRoutingError(frappe.ValidationError):
	def __init__(self, code: str, message: str | None = None):
		self.code = code
		self.error_code = code
		super().__init__(message or code)


def _error(code: str, message: str | None = None):
	raise StudentRoutingError(code, message)


@contextmanager
def service_context():
	flags = frappe.flags
	previous = getattr(flags, SERVICE_FLAG, False)
	flags.student_routing_service = True
	try:
		yield
	finally:
		flags.student_routing_service = previous


def _canonical_pool(student) -> dict[str, Any]:
	"""Resolve exactly one active pool for a Student's Campus."""
	branch = student.get("branch")
	if not branch:
		_error("INVALID_TOPOLOGY", "Student Campus is required for routing.")
	filters = {"campus": branch, "is_active": 1}
	if student.get("owning_pool"):
		filters["name"] = student.get("owning_pool")
	elif student.get("owning_team"):
		filters["team"] = student.get("owning_team")
	else:
		_error("NOT_POOL_OWNED", "Student is not currently owned by a pool.")
	rows = frappe.get_all(
		"CRM Student Pool", filters=filters,
		fields=["name", "pool_name", "team", "campus", "is_active"],
		limit_page_length=2,
	)
	if len(rows) > 1:
		_error("AMBIGUOUS_POOL", "Student maps to multiple active Student Pools.")
	if not rows:
		_error("INVALID_TOPOLOGY", "Student pool is missing, inactive, or outside the Campus.")
	if student.get("owner_staff") or student.get("assigned_to"):
		_error("INVALID_TOPOLOGY", "A routed Student must be exclusively pool-owned.")
	if student.get("owning_team") != rows[0].team:
		_error("INVALID_TOPOLOGY", "Student Pool Team does not match the ownership projection.")
	return rows[0]


def _active_policy(pool: dict[str, Any], at=None):
	at = at or now_datetime()
	rows = frappe.get_all(
		"CRM Student Routing Policy",
		filters={
			"campus": pool.campus,
			"student_pool": pool.name,
			"status": "active",
			"effective_from": ["<=", at],
		},
		fields="*",
		order_by="policy_version desc",
		limit_page_length=2,
	)
	rows = [row for row in rows if not row.get("effective_until") or row.effective_until > at]
	if len(rows) > 1:
		_error("OVERLAPPING_POLICY", "More than one active routing policy covers this pool.")
	return rows[0] if rows else None


def _eligible_members(pool: dict[str, Any]) -> list[dict[str, Any]]:
	team = frappe.db.get_value(
		"CRM Team", pool.team, ["name", "campus", "is_active", "team_type"], as_dict=True
	)
	if not team or not team.is_active or team.team_type != "Sales" or team.campus != pool.campus:
		_error("INVALID_TOPOLOGY", "Student Pool Team is not an active Sales Team at the Campus.")
	memberships = frappe.get_all(
		"CRM Team Membership",
		filters={"team": team.name, "parenttype": "CRM Staff"},
		fields=["parent", "team", "function", "name"],
	)
	staff_ids = sorted({row.parent for row in memberships if row.get("parent") and (not row.get("function") or row.function == "Sale")})
	if not staff_ids:
		return []
	staff_rows = frappe.get_all(
		"CRM Staff", filters={"name": ["in", staff_ids], "is_active": 1},
		fields=["name", "user", "campus"],
	)
	result = []
	for staff in staff_rows:
		if staff.get("campus") and staff.campus != pool.campus:
			continue
		if not staff.get("user") or resolve_crm_profile(frappe.get_roles(staff.user)) != "sales":
			continue
		result.append({"staff": staff.name, "team": team.name, "user": staff.user})
	return sorted(result, key=lambda row: row["staff"])


def _select_member(members: list[dict[str, Any]], cursor_staff: str | None):
	if not members:
		return None
	if not cursor_staff:
		return members[0]
	for index, member in enumerate(members):
		if member["staff"] == cursor_staff:
			return members[(index + 1) % len(members)]
	return members[0]


def _save_request(request, *, status: str, **values):
	request.status = status
	request.revision = int(request.revision or 0) + 1
	for fieldname, value in values.items():
		request.set(fieldname, value)
	with service_context():
		request.save(ignore_permissions=True)


def enqueue_student_routing(student: str, *, trigger: str = "pool_entry", correlation_id: str | None = None):
	"""Create one idempotent request for the Student's current pool revision."""
	student_doc = frappe.get_doc("CRM Student", student)
	pool = _canonical_pool(student_doc)
	revision = int(student_doc.get("ownership_revision") or 0)
	request_key = f"route:{student}:{revision}"
	existing = frappe.db.get_value(REQUEST_DOCTYPE, {"request_key": request_key}, "name")
	if existing:
		return frappe.get_doc(REQUEST_DOCTYPE, existing)
	values = {
		"doctype": REQUEST_DOCTYPE,
		"request_key": request_key,
		"status": "pending",
		"revision": 0,
		"student": student_doc.name,
		"ownership_revision": revision,
		"pool_revision_key": f"{pool.name}:{revision}",
		"campus": pool.campus,
		"student_pool": pool.name,
		"route_trigger": trigger,
		"correlation_token": correlation_id or str(uuid.uuid4()),
		"idempotency_key": request_key,
		"schema_version": "phase4-v1",
	}
	policy = _active_policy(pool)
	if policy:
		values.update({"routing_policy": policy.name, "routing_policy_version": policy.policy_version})
	with service_context():
		request = frappe.get_doc(values)
		request.insert(ignore_permissions=True)
	return request


def _lock_request(name: str):
	frappe.db.sql(f"select name from `tab{REQUEST_DOCTYPE}` where name = %s for update", (name,))
	return frappe.get_doc(REQUEST_DOCTYPE, name)


def process_routing_request(request_name: str, *, lease_token: str | None = None) -> dict[str, Any]:
	"""Claim and process one request inside one transaction."""
	if not enabled("routing"):
		_error("ROUTING_DISABLED", "Student routing is disabled during controlled rollout.")
	with service_context():
		request = _lock_request(request_name)
		if request.status in {"applied", "deferred", "superseded"} and not lease_token:
			return {"status": request.status, "request": request.name, "replayed": True}
		if request.status not in {"pending", "leased"}:
			return {"status": request.status, "request": request.name, "replayed": True}
		if request.status == "leased":
			if lease_token and request.lease_token != lease_token:
				_error("LEASE_LOST", "Routing request lease is no longer valid.")
			if not lease_token:
				if request.lease_expires_at and request.lease_expires_at > now_datetime():
					_error("LEASE_ACTIVE", "Routing request is currently leased by another worker.")
				_save_request(request, status="pending", lease_token=None, lease_expires_at=None)
				request = _lock_request(request.name)
		if request.status == "pending":
			lease_token = str(uuid.uuid4())
			_save_request(
				request,
				status="leased",
				lease_token=lease_token,
				lease_expires_at=add_to_date(now_datetime(), minutes=LEASE_MINUTES),
				attempt_count=int(request.attempt_count or 0) + 1,
			)

		student = frappe.get_doc("CRM Student", request.student)
		frappe.db.sql("select name from `tabCRM Student` where name = %s for update", (student.name,))
		student.reload()
		current_revision = int(student.get("ownership_revision") or 0)
		if current_revision != int(request.ownership_revision or 0):
			_save_request(request, status="superseded", last_error_code="STALE_OWNERSHIP_REVISION", completed_at=now_datetime())
			frappe.db.commit()
			return {"status": "superseded", "request": request.name, "replayed": False}
		pool = _canonical_pool(student)
		policy = _active_policy(pool)
		if not policy:
			_save_request(request, status="deferred", last_error_code="NO_ACTIVE_POLICY", completed_at=None)
			frappe.db.commit()
			return {"status": "deferred", "request": request.name, "reason": "NO_ACTIVE_POLICY"}
		# Serialize all candidates and cursor advancement for one pool on the
		# immutable policy row.  The lock is held until ownership + request commit.
		frappe.db.sql("select name from `tabCRM Student Routing Policy` where name = %s for update", (policy.name,))
		policy = frappe.get_doc("CRM Student Routing Policy", policy.name)
		members = _eligible_members(pool)
		member = _select_member(members, policy.get("cursor_staff"))
		if not member:
			_save_request(request, status="deferred", last_error_code="NO_ELIGIBLE_MEMBER", completed_at=None)
			frappe.db.commit()
			return {"status": "deferred", "request": request.name, "reason": "NO_ELIGIBLE_MEMBER"}
		try:
			result = change_student_ownership(
				student=student.name,
				target_kind="owner",
				target_id=member["staff"],
				target_team_id=member["team"],
				reason=f"Automatic round-robin routing ({request.name})",
				idempotency_key=request.idempotency_key or request.request_key,
				expected_revision=current_revision,
				correlation_id=request.correlation_token,
				_internal_service=True,
				_commit=False,
				_route_trigger=request.route_trigger or "pool_entry",
				_routing_policy_version=policy.policy_version,
			)
		except StudentOwnershipError:
			_save_request(request, status="failed", last_error_code="OWNERSHIP_TRANSITION_FAILED", completed_at=now_datetime())
			raise
		cursor_revision = int(policy.get("cursor_revision") or 0)
		frappe.db.set_value(
			"CRM Student Routing Policy", policy.name,
			{"cursor_staff": member["staff"], "cursor_revision": cursor_revision + 1},
			update_modified=False,
		)
		_save_request(request, status="applied", completed_at=now_datetime(), last_error_code=None)
		frappe.db.commit()
		return {"status": "applied", "request": request.name, "student": student.name, "owner_staff": member["staff"], "ownership": result}


def retry_student_routing(request_name: str) -> dict[str, Any]:
	request = frappe.get_doc(REQUEST_DOCTYPE, request_name)
	student = frappe.get_doc("CRM Student", request.student)
	if not has_student_permission(student, user=frappe.session.user, permission_type="read"):
		_error("OUT_OF_SCOPE", "Routing request is outside the current Student scope.")
	if request.status in {"deferred", "failed"}:
		with service_context():
			_save_request(request, status="pending", last_error_code=None, completed_at=None, lease_token=None, lease_expires_at=None)
		frappe.db.commit()
	return process_routing_request(request_name)


def process_pending_routing_requests(limit: int = 50) -> dict[str, int]:
	"""Bounded worker entry point; expired leases are safely reclaimed."""
	if not enabled("routing"):
		return {"processed": 0, "failed": 0, "disabled": 1}
	now = now_datetime()
	page_limit = min(max(int(limit), 1), 100)
	rows = list(
		frappe.get_all(
			REQUEST_DOCTYPE, filters={"status": "pending"}, pluck="name",
			order_by="creation asc", limit_page_length=page_limit,
		)
	)
	rows.extend(
		row
		for row in frappe.get_all(
			REQUEST_DOCTYPE,
			filters={"status": "leased", "lease_expires_at": ["<", now]},
			pluck="name", order_by="creation asc", limit_page_length=page_limit,
		)
		if row not in rows
	)
	rows = rows[:page_limit]
	processed = failed = 0
	for name in rows:
		try:
			process_routing_request(name)
			processed += 1
		except Exception:
			frappe.db.rollback()
			failed += 1
	return {"processed": processed, "failed": failed}


def get_student_routing_status(request_name: str) -> dict[str, Any]:
	request = frappe.get_doc(REQUEST_DOCTYPE, request_name)
	student = frappe.get_doc("CRM Student", request.student)
	if not has_student_permission(student, user=frappe.session.user, permission_type="read"):
		_error("OUT_OF_SCOPE", "Routing request is outside the current Student scope.")
	return {
		"request": request.name,
		"status": request.status,
		"student": request.student,
		"campus": request.campus,
		"student_pool": request.student_pool,
		"ownership_revision": request.ownership_revision,
		"revision": request.revision,
		"last_error_code": request.last_error_code,
		"capabilities": _request_capabilities(),
	}


def _request_capabilities() -> dict[str, bool]:
	actor = frappe.session.user
	roles = frappe.get_roles(actor)
	caps = capabilities_for_roles(roles, administrator=actor == "Administrator")
	return {"read": "student.routing.read" in caps, "retry": "student.routing.retry" in caps}
