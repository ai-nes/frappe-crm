"""Transactional Student pool routing service.

The worker owns request leases and policy/cursor resolution.  Ownership still
flows through the Phase 3 command; this module never writes Student ownership
fields directly.
"""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from typing import Any

import frappe
from frappe.utils import add_to_date, now_datetime

from crm.fcrm.permissions import has_permission as has_student_permission
from crm.fcrm.role_policy import capabilities_for_roles, resolve_crm_profile
from crm.fcrm.student_assignment import (
	ENRICHMENT_QUEUE,
	MANUAL_QUEUE,
	capacity_eligible,
	frozen_mapping_is_current,
	resolve_student_zone,
	score_member,
	zone_team_pool,
)
from crm.fcrm.student_feature_flags import enabled
from crm.fcrm.student_lead_operations import deliver_ctv_student
from crm.fcrm.student_ownership import StudentOwnershipError, change_student_ownership
from crm.fcrm.utils.effective import is_effective

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
		"CRM Student Pool",
		filters=filters,
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


def _eligible_team_members(
	team_name: str,
	campus: str,
	*,
	staff_ids: set[str] | None = None,
	prefer_sale: bool = True,
) -> list[dict[str, Any]]:
	team = frappe.db.get_value(
		"CRM Team", team_name, ["name", "campus", "is_active", "team_type"], as_dict=True
	)
	if not team or not team.is_active or team.team_type != "Sales" or team.campus != campus:
		_error("INVALID_TOPOLOGY", "Student Pool Team is not an active Sales Team at the Campus.")
	memberships = frappe.get_all(
		"CRM Team Membership",
		filters={"team": team.name, "parenttype": "CRM Staff"},
		fields=["parent", "team", "function", "name", "effective_from", "effective_until"],
	)
	memberships = [row for row in memberships if is_effective(row)]
	if staff_ids is not None:
		memberships = [row for row in memberships if row.get("parent") in staff_ids]
	sale_rows = [row for row in memberships if row.get("parent") and row.get("function") in (None, "", "Sale")]
	ctv_rows = [row for row in memberships if row.get("parent") and row.get("function") == "CTV Sale"]
	selected_rows = sale_rows or ctv_rows if prefer_sale else sale_rows + ctv_rows
	staff_ids = sorted({row.parent for row in selected_rows})
	if not staff_ids:
		return []
	staff_rows = frappe.get_all(
		"CRM Staff",
		filters={"name": ["in", staff_ids], "is_active": 1},
		fields=["name", "user", "campus"],
	)
	result = []
	for staff in staff_rows:
		if staff.get("campus") and staff.campus != campus:
			continue
		if (
			not staff.get("user")
			or not frappe.db.get_value("User", staff.user, "enabled")
			or resolve_crm_profile(frappe.get_roles(staff.user)) not in {"sales", "ctv_sale"}
		):
			continue
		function = next(
			(row.get("function") for row in selected_rows if row.get("parent") == staff.name), "Sale"
		)
		result.append({"staff": staff.name, "team": team.name, "user": staff.user, "function": function})
	return sorted(result, key=lambda row: row["staff"])


def _eligible_members(pool: dict[str, Any]) -> list[dict[str, Any]]:
	return _eligible_team_members(pool.team, pool.campus)


def _routing_context(student, pool):
	geo = resolve_student_zone(student)
	if geo.get("tier") in {3, 4}:
		mapped_team = pool.get("team") and frappe.db.exists(
			"CRM Team Zone Assignment", {"team": pool["team"], "status": "Active"}
		)
		if not mapped_team:
			return {"tier": 0, "legacy": True}
	if geo.get("tier") == 1:
		return {
			"tier": 1,
			"school_owner": geo["school_owner"],
			"school_owners": geo.get("school_owners") or [geo["school_owner"]],
			"school_owner_team": geo.get("school_owner_team"),
			"zone": geo.get("zone"),
		}
	if geo.get("tier") == 2:
		mapping = zone_team_pool(geo["zone"], pool["campus"])
		if mapping:
			return {"tier": 2, "zone": geo["zone"], "mapping": mapping}
	if geo.get("tier") == 3:
		return {"tier": 3, "queue": MANUAL_QUEUE}
	return {"tier": 4, "queue": ENRICHMENT_QUEUE}


def _select_member(members: list[dict[str, Any]], cursor_staff: str | None):
	if not members:
		return None
	if not cursor_staff:
		return members[0]
	for index, member in enumerate(members):
		if member["staff"] == cursor_staff:
			return members[(index + 1) % len(members)]
	return members[0]


def _select_routing_member(members, student, policy, cursor_staff, context):
	eligible = []
	for member in members:
		ok, capacity = capacity_eligible(member, student, direct=context.get("tier") == 1)
		if ok:
			member = dict(member)
			member["capacity"] = capacity
			eligible.append(member)
	if not eligible:
		return None, []
	if policy.get("strategy") == "weighted_score":
		scored = [score_member(member, student, policy) for member in eligible]
		winner = max(scored, key=lambda row: (row["score"], row["staff"]))
		return next(member for member in eligible if member["staff"] == winner["staff"]), scored
	return _select_member(eligible, cursor_staff), []


def route_pool_owned_student(
	student: str,
	*,
	trigger: str = "pool_entry",
	correlation_id: str | None = None,
	expected_revision: int | None = None,
) -> dict[str, Any]:
	"""Synchronously route one currently pool-owned Student in the caller transaction.

	No request, lease, retry, or cursor advancement is persisted unless the
	ownership transition commits. Unresolved policy/member state remains the
	Student's current pool ownership rather than becoming a business record.
	"""
	if not enabled("routing"):
		return {"status": "deferred", "reason": "ROUTING_DISABLED", "student": student}
	frappe.db.sql("select name from `tabCRM Lead` where name = %s for update", (student,))
	student_doc = frappe.get_doc("CRM Lead", student)
	# Keep the command compatible with lightweight dict doubles used by the
	# offline contract tests as well as real Frappe documents.
	student_name = student_doc.get("name") if isinstance(student_doc, dict) else student_doc.name
	current_revision = int(student_doc.get("ownership_revision") or 0)
	if expected_revision is not None and current_revision != int(expected_revision):
		return {"status": "superseded", "reason": "STALE_OWNERSHIP_REVISION", "student": student_name}
	pool = _canonical_pool(student_doc)
	context = _routing_context(student_doc, pool)
	if context.get("tier") in {3, 4}:
		return {
			"status": "queued",
			"tier": context["tier"],
			"queue": context["queue"],
			"student": student_name,
		}
	if context.get("tier") == 1:
		team = context.get("school_owner_team")
		if not team:
			return {
				"status": "queued",
				"tier": 4,
				"queue": ENRICHMENT_QUEUE,
				"student": student_name,
			}
		school_owners = set(context.get("school_owners") or [context["school_owner"]])
		members = _eligible_team_members(team, pool["campus"], staff_ids=school_owners, prefer_sale=False)
		if not members:
			return {
				"status": "queued",
				"tier": 3,
				"queue": MANUAL_QUEUE,
				"student": student_name,
			}
		policy = _active_policy(pool)
		member, scored = _select_routing_member(members, student_doc, policy or {}, None, {"tier": 1})
		if not member:
			return {
				"status": "deferred",
				"reason": "CAPACITY_BLOCKED",
				"student": student_name,
				"tier": 1,
			}
		ok, snapshot = capacity_eligible(member, student_doc, direct=True)
		if not ok:
			return {
				"status": "deferred",
				"reason": "CAPACITY_BLOCKED",
				"student": student_name,
				"capacity": snapshot,
			}
		policy = _active_policy(pool)
		result = change_student_ownership(
			student=student_name,
			target_kind="owner",
			target_id=member["staff"],
			target_team_id=team,
			reason="Automatic school-owner routing",
			idempotency_key=f"route:{student_name}:{current_revision}",
			expected_revision=current_revision,
			correlation_id=correlation_id or str(uuid.uuid4()),
			_internal_service=True,
			_commit=False,
			_route_trigger=trigger,
			_routing_policy_version=policy.policy_version if policy else None,
		)
		return {
			"status": "applied",
			"tier": 1,
			"student": student_name,
			"owner_staff": member["staff"],
			"scoring": scored,
			"ownership": result,
		}
	if context.get("tier") == 2 and context.get("mapping", {}).get("pool") != pool.get("name"):
		# Move the pool projection through the canonical ownership command before
		# selecting a member.  This is idempotent under the Student lock.
		change_student_ownership(
			student=student_name,
			target_kind="pool",
			target_id=context["mapping"]["pool"],
			target_team_id=None,
			reason="Zone pool migration",
			idempotency_key=f"zone-pool:{student_name}:{current_revision}",
			expected_revision=current_revision,
			correlation_id=correlation_id or str(uuid.uuid4()),
			_internal_service=True,
			_commit=False,
			_route_trigger=trigger,
		)
		student_doc.reload()
		current_revision = int(student_doc.get("ownership_revision") or 0)
		pool = _canonical_pool(student_doc)
	policy = _active_policy(pool)
	if not policy:
		return {"status": "deferred", "reason": "NO_ACTIVE_POLICY", "student": student_name}
	# The Student lock is acquired first. The policy lock serializes cursor
	# advancement and is retained through the ownership command.
	frappe.db.sql(
		"select name from `tabCRM Student Routing Policy` where name = %s for update", (policy.name,)
	)
	policy = frappe.get_doc("CRM Student Routing Policy", policy.name)
	members = _eligible_members(pool)
	member, scored = _select_routing_member(members, student_doc, policy, policy.get("cursor_staff"), context)
	if not member:
		return {
			"status": "deferred",
			"reason": "CAPACITY_BLOCKED",
			"student": student_name,
			"tier": context.get("tier"),
		}
	if member.get("function") == "CTV Sale":
		batch = deliver_ctv_student(student_doc, member, policy=policy)
		if not batch:
			return {
				"status": "deferred",
				"reason": "CTV_BATCH_UNAVAILABLE_OR_LEAD_COMPLEX",
				"student": student_name,
			}
	route_key = f"route:{student_name}:{current_revision}"
	try:
		result = change_student_ownership(
			student=student_name,
			target_kind="owner",
			target_id=member["staff"],
			target_team_id=member["team"],
			reason=f"Automatic {policy.get('strategy') or 'round_robin'} routing; tier={context.get('tier')}; scoring={scored}; mechanism={'ctv_batch' if member.get('function') == 'CTV Sale' else 'individual'}",
			idempotency_key=route_key,
			expected_revision=current_revision,
			correlation_id=correlation_id or str(uuid.uuid4()),
			_internal_service=True,
			_commit=False,
			_route_trigger=trigger,
			_routing_policy_version=policy.policy_version,
		)
	except StudentOwnershipError:
		raise
	cursor_revision = int(policy.get("cursor_revision") or 0)
	frappe.db.set_value(
		"CRM Student Routing Policy",
		policy.name,
		{"cursor_staff": member["staff"], "cursor_revision": cursor_revision + 1},
		update_modified=False,
	)
	return {
		"status": "applied",
		"student": student_name,
		"owner_staff": member["staff"],
		"tier": context.get("tier"),
		"scoring": scored,
		"ownership": result,
		"replayed": bool(result.get("replayed")),
	}


def _save_request(request, *, status: str, **values):
	request.status = status
	request.revision = int(request.revision or 0) + 1
	for fieldname, value in values.items():
		request.set(fieldname, value)
	with service_context():
		request.save(ignore_permissions=True)


def enqueue_student_routing(student: str, *, trigger: str = "pool_entry", correlation_id: str | None = None):
	"""Create one idempotent request for the Student's current pool revision."""
	student_doc = frappe.get_doc("CRM Lead", student)
	pool = _canonical_pool(student_doc)
	context = _routing_context(student_doc, pool)
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
		"student": student_doc.get("name") if isinstance(student_doc, dict) else student_doc.name,
		"ownership_revision": revision,
		"pool_revision_key": f"{pool.name}:{revision}",
		"campus": pool.campus,
		"student_pool": pool.name,
		"tier": context.get("tier"),
		"queue": context.get("queue"),
		"zone": context.get("zone"),
		"zone_team": context.get("mapping", {}).get("team"),
		"frozen_mapping": context.get("mapping"),
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

		student = frappe.get_doc("CRM Lead", request.student)
		frappe.db.sql("select name from `tabCRM Lead` where name = %s for update", (student.name,))
		student.reload()
		current_revision = int(student.get("ownership_revision") or 0)
		if current_revision != int(request.ownership_revision or 0):
			_save_request(
				request,
				status="superseded",
				last_error_code="STALE_OWNERSHIP_REVISION",
				completed_at=now_datetime(),
			)
			frappe.db.commit()
			return {"status": "superseded", "request": request.name, "replayed": False}
		pool = _canonical_pool(student)
		frozen = request.get("frozen_mapping")
		if isinstance(frozen, str):
			try:
				frozen = json.loads(frozen)
			except (TypeError, ValueError):
				frozen = None
		if frozen and not frozen_mapping_is_current(frozen, pool["campus"]):
			_save_request(request, status="deferred", last_error_code="STALE_ZONE_MAPPING", completed_at=None)
			frappe.db.commit()
			return {"status": "deferred", "request": request.name, "reason": "STALE_ZONE_MAPPING"}
		result = route_pool_owned_student(
			student.name,
			trigger=request.route_trigger or "pool_entry",
			correlation_id=request.correlation_token,
			expected_revision=current_revision,
		)
		if result.get("status") in {"deferred", "queued"}:
			_save_request(
				request,
				status="deferred",
				last_error_code=result.get("reason") or result.get("queue"),
				completed_at=None,
			)
			frappe.db.commit()
			return dict(result, request=request.name)
		_save_request(request, status="applied", completed_at=now_datetime(), last_error_code=None)
		frappe.db.commit()
		return dict(result, request=request.name)


def retry_student_routing(request_name: str) -> dict[str, Any]:
	request = frappe.get_doc(REQUEST_DOCTYPE, request_name)
	student = frappe.get_doc("CRM Lead", request.student)
	if not has_student_permission(student, user=frappe.session.user, permission_type="read"):
		_error("OUT_OF_SCOPE", "Routing request is outside the current Student scope.")
	if request.status in {"deferred", "failed"}:
		with service_context():
			_save_request(
				request,
				status="pending",
				last_error_code=None,
				completed_at=None,
				lease_token=None,
				lease_expires_at=None,
			)
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
			REQUEST_DOCTYPE,
			filters={"status": "pending"},
			pluck="name",
			order_by="creation asc",
			limit_page_length=page_limit,
		)
	)
	rows.extend(
		row
		for row in frappe.get_all(
			REQUEST_DOCTYPE,
			filters={"status": "leased", "lease_expires_at": ["<", now]},
			pluck="name",
			order_by="creation asc",
			limit_page_length=page_limit,
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


def repair_orphan_routing_requests(limit: int = 1000) -> dict[str, int]:
	"""Close routing requests whose Student was removed, preserving the audit row.

	Old production imports can leave pending requests for Students that no longer
	exist. The normal worker intentionally fails closed on those rows, so this
	one-time maintenance command classifies them as permanently failed instead
	of deleting history or retrying them forever. It is idempotent and does not
	touch applied, superseded, or already-failed requests.
	"""
	page_limit = min(max(int(limit), 1), 5000)
	rows = frappe.get_all(
		REQUEST_DOCTYPE,
		filters={"status": ["in", ["pending", "leased", "deferred"]]},
		fields=["name", "student", "status", "revision"],
		order_by="creation asc",
		limit_page_length=page_limit,
	)
	repaired = 0
	with service_context():
		for row in rows:
			if frappe.db.exists("CRM Lead", row.get("student")):
				continue
			# The Student link is intentionally orphaned. Updating through a Document
			# would re-run Frappe link validation and prevent us from closing the
			# audit row, so this maintenance path writes only the terminal fields.
			frappe.db.set_value(
				REQUEST_DOCTYPE,
				row["name"],
				{
					"status": "failed",
					"revision": int(row.get("revision") or 0) + 1,
					"last_error_code": "STUDENT_NOT_FOUND",
					"completed_at": now_datetime(),
					"lease_token": None,
					"lease_expires_at": None,
				},
			)
			repaired += 1
	if repaired and not getattr(frappe.flags, "in_test", False):
		frappe.db.commit()
	return {"checked": len(rows), "repaired": repaired}


def get_student_routing_status(request_name: str) -> dict[str, Any]:
	request = frappe.get_doc(REQUEST_DOCTYPE, request_name)
	student = frappe.get_doc("CRM Lead", request.student)
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
