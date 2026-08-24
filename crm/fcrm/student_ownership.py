"""Authoritative ownership command for CRM Student.

Ownership is deliberately implemented as a command rather than as a writable
field convention.  The command is the only supported application writer for
the Student ownership projection.  Routing, workload balancing, and SLA
behaviour do not belong here.

The data surfaces used by this module are created by the Phase 3.1 data
contract: ``CRM Student Command Receipt`` and ``CRM Student Ownership Event``.
Failing closed when those surfaces have not been migrated is important; an
in-memory idempotency guard would make retries unsafe across workers.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import struct
import uuid
from typing import Any

import frappe
from frappe.utils import now_datetime

from crm.fcrm.permissions import has_permission as has_student_permission
from crm.fcrm.role_policy import (
	POLICY_VERSION,
	capabilities_for_roles,
	resolve_crm_profile,
)


RECEIPT_DOCTYPE = "CRM Student Command Receipt"
OWNERSHIP_EVENT_DOCTYPE = "CRM Student Ownership Event"
RECEIPT_DOMAIN = "crm.receipt.command"
RECEIPT_KEY_VERSION = "v1"
OWNERSHIP_CAPABILITY = "student.ownership.manage"
SCHEMA_VERSION = "phase3-v1"


class StudentOwnershipError(frappe.ValidationError):
	"""Stable machine-readable command failure.

	Frappe serializes the exception message for RPC callers.  ``code`` remains
	available to direct Python callers and lets the API adapter preserve stable
	error names without leaking implementation details.
	"""

	def __init__(self, code: str, message: str | None = None):
		self.code = code
		self.error_code = code
		super().__init__(message or code)


def _error(code: str, message: str | None = None):
	raise StudentOwnershipError(code, message)


def _required_text(value: Any, code: str, label: str, *, max_length: int = 255) -> str:
	if not isinstance(value, str) or not value.strip():
		_error(code, f"{label} is required.")
	value = value.strip()
	if len(value) > max_length:
		_error(code, f"{label} is too long.")
	return value


def _canonical_json(value: Any) -> str:
	return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _fingerprint(value: Any) -> str:
	return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _length_delimited(domain: str, *parts: str) -> bytes:
	"""Return the Phase 3 domain-separated UTF-8 encoding.

	The domain is fixed by the caller; every user-controlled component has an
	unsigned 32-bit big-endian byte length, so concatenation collisions cannot
	turn one command key into another.
	"""

	encoded_domain = domain.encode("utf-8")
	values = [part.encode("utf-8") for part in parts]
	return encoded_domain + b"".join(struct.pack(">I", len(value)) + value for value in values)


def _configured_secret(version: str) -> str | None:
	conf = getattr(frappe, "conf", {})
	keys = (
		f"crm_receipt_hmac_secret_{version}",
		f"crm_command_hmac_secret_{version}",
		f"crm_receipt_hmac_key_{version}",
	)
	for key in keys:
		value = conf.get(key) if hasattr(conf, "get") else None
		if value:
			return str(value)
	# ``encryption_key`` is Frappe's site-level secret and is the safe fallback
	# for installations that have not yet added the dedicated receipt secret.
	for key in ("crm_receipt_hmac_secret", "crm_command_hmac_secret", "encryption_key"):
		value = conf.get(key) if hasattr(conf, "get") else None
		if value:
			return str(value)
	return None


def _key_versions() -> list[str]:
	conf = getattr(frappe, "conf", {})
	current = str(conf.get("crm_receipt_hmac_key_version", RECEIPT_KEY_VERSION))
	prior = conf.get("crm_receipt_hmac_previous_key_version")
	versions = [current]
	if prior and str(prior) not in versions:
		versions.append(str(prior))
	return versions


def ownership_command_keys(principal: str, idempotency_key: str) -> list[str]:
	"""Return current then rotation-previous command receipt keys."""

	principal = _required_text(principal, "INVALID_INPUT", "principal")
	idempotency_key = _required_text(idempotency_key, "INVALID_INPUT", "idempotency_key")
	keys = []
	for version in _key_versions():
		secret = _configured_secret(version)
		if not secret:
			_error("SCHEMA_NOT_READY", "Receipt HMAC secret is not configured.")
		payload = _length_delimited(
			f"{RECEIPT_DOMAIN}.{version}", "ownership", principal, idempotency_key
		)
		keys.append(hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest())
	return keys


def ownership_command_key(principal: str, idempotency_key: str) -> str:
	return ownership_command_keys(principal, idempotency_key)[0]


def _doctype_fields(doctype: str) -> set[str]:
	try:
		return {field.fieldname for field in frappe.get_meta(doctype).fields}
	except Exception:
		return set()


def _ensure_schema() -> None:
	missing = [
		doctype
		for doctype in (RECEIPT_DOCTYPE, OWNERSHIP_EVENT_DOCTYPE)
		if not frappe.db.exists("DocType", doctype)
	]
	if missing:
		_error("SCHEMA_NOT_READY", f"Phase 3 ownership schema is not installed: {', '.join(missing)}.")


def _get_value(doctype: str, name: str, fieldname: str, default=None):
	try:
		value = frappe.db.get_value(doctype, name, fieldname)
	except Exception:
		return default
	return default if value is None else value


def _set_supported(doc, values: dict[str, Any]) -> None:
	fields = _doctype_fields(doc.doctype)
	for fieldname, value in values.items():
		if fieldname in fields:
			doc.set(fieldname, value)


def _insert_audit_doc(doctype: str, values: dict[str, Any]):
	doc = frappe.get_doc({"doctype": doctype})
	_set_supported(doc, values)
	doc.insert(ignore_permissions=True)
	return doc


def _lock(doctype: str, name: str) -> None:
	if not name:
		return
	# All command locks are row locks.  ``get_doc`` is intentionally separate so
	# the subsequent read sees the locked, authoritative values.
	frappe.db.sql(
		f"select name from `tab{doctype}` where name = %s for update",
		(name,),
	)


def _lock_receipt(keys: list[str]):
	for key in keys:
		name = frappe.db.get_value(RECEIPT_DOCTYPE, {"command_key": key}, "name")
		if name:
			_lock(RECEIPT_DOCTYPE, name)
			return frappe.get_doc(RECEIPT_DOCTYPE, name)
	return None


def _receipt_value(receipt, *fieldnames, default=None):
	for fieldname in fieldnames:
		value = receipt.get(fieldname)
		if value not in (None, ""):
			return value
	return default


def _replay_receipt(receipt, request_fingerprint: str):
	stored_fingerprint = _receipt_value(receipt, "request_fingerprint", "fingerprint")
	if stored_fingerprint and stored_fingerprint != request_fingerprint:
		_error("IDEMPOTENCY_KEY_REUSED", "Idempotency key was already used for a different request.")
	result = _receipt_value(receipt, "result_json", "result", default=None)
	if isinstance(result, str):
		try:
			result = json.loads(result)
		except (TypeError, ValueError):
			result = None
	if isinstance(result, dict):
		result = dict(result)
		result.setdefault("receipt", receipt.name)
		return result
	try:
		events = frappe.get_all(
			OWNERSHIP_EVENT_DOCTYPE,
			filters={"command_receipt": receipt.name},
			fields=["name", "student", "next_owner_staff", "next_owning_team", "aggregate_revision"],
			order_by="event_at desc",
			limit_page_length=1,
			ignore_permissions=True,
		)
	except Exception:
		events = []
	if events:
		event = events[0]
		pool_name = event.get("next_owning_team")
		team_name = (
			frappe.db.get_value("CRM Student Pool", pool_name, "team") if pool_name else None
		)
		return {
			"status": "applied",
			"student": event.get("student") or _receipt_value(receipt, "target_student"),
			"target_kind": "owner" if event.get("next_owner_staff") else "pool",
			"target_id": event.get("next_owner_staff") or pool_name,
			"owner_staff": event.get("next_owner_staff"),
			"owning_team": team_name,
			"revision": event.get("aggregate_revision") or _receipt_value(receipt, "result_revision"),
			"event": event.get("name"),
			"receipt": receipt.name,
			"replayed": True,
		}
	return {
		"receipt": receipt.name,
		"student": _receipt_value(receipt, "target_student", "student", "student_name", "aggregate_name"),
		"status": _receipt_value(receipt, "status", "outcome", default="applied"),
		"revision": _receipt_value(receipt, "result_revision", "revision"),
		"replayed": True,
	}


def _current_actor() -> str:
	actor = getattr(getattr(frappe, "session", None), "user", None)
	return _required_text(actor, "UNAUTHORIZED", "authenticated user")


def _authorize(actor: str) -> tuple[str, dict[str, Any]]:
	if actor in ("", "Guest", "None", None):
		_error("UNAUTHORIZED", "Authentication is required.")
	if actor == "Administrator":
		# Administrator is Frappe's platform break-glass identity, distinct from
		# a routine System Manager business user.  It is retained for migrations,
		# recovery, and isolated test fixtures.
		return "platform_superuser", {"roles": [], "profile": "platform_superuser"}
	roles = set(frappe.get_roles(actor))
	profile = resolve_crm_profile(roles)
	capabilities = capabilities_for_roles(roles, administrator=actor == "Administrator")
	if OWNERSHIP_CAPABILITY not in capabilities or profile not in {"lead_sales", "admissions_director"}:
		_error("UNAUTHORIZED", "You are not permitted to manage Student ownership.")
	return profile, {"roles": sorted(roles), "profile": profile}


def _team_rows_for_actor(actor: str) -> list[dict[str, Any]]:
	staff = frappe.db.get_value("CRM Staff", {"user": actor}, ["name", "campus", "is_active"], as_dict=True)
	if not staff or not staff.get("name") or not staff.get("is_active"):
		return []
	memberships = frappe.get_all(
		"CRM Team Membership",
		filters={"parent": staff.name, "parenttype": "CRM Staff"},
		fields=["team", "function", "is_primary"],
	)
	team_ids = [row.team for row in memberships if row.get("team")]
	if not team_ids:
		return []
	return frappe.get_all(
		"CRM Team",
		filters={"name": ["in", team_ids], "team_type": "Sales", "is_active": 1},
		fields=["name", "campus", "team_type", "is_active"],
	)


def _assert_actor_target_scope(actor: str, profile: str, team_name: str) -> list[dict[str, Any]]:
	if profile in {"admissions_director", "platform_superuser"}:
		return []
	teams = _team_rows_for_actor(actor)
	if team_name not in {team.get("name") for team in teams}:
		_error("OUT_OF_SCOPE", "Target Team is outside the actor's current Team/Campus scope.")
	return teams


def _student_is_active(student) -> bool:
	if student.get("lifecycle_stage") == "Lost":
		return False
	status = student.get("enrollment_status")
	if status:
		stage_category = _get_value("CRM Enrollment Status", status, "stage_category")
		if stage_category in {"closed", "lost", "terminal"}:
			return False
	return True


def _validate_current_topology(student) -> tuple[str | None, str | None]:
	owner = student.get("owner_staff") or None
	pool = student.get("owning_team") or None
	assigned = student.get("assigned_to") or None
	if not _student_is_active(student):
		_error("STUDENT_NOT_ACTIVE", "Only active Student cases may change ownership.")
	if bool(owner) == bool(pool):
		_error("INVALID_CURRENT_OWNERSHIP", "Active Student must have exactly one owner or pool.")
	if owner and assigned != owner:
		_error("INVALID_CURRENT_OWNERSHIP", "Student assigned_to must match owner_staff.")
	return owner, pool


def _load_team(team_name: str) -> dict[str, Any]:
	team = frappe.db.get_value(
		"CRM Team", team_name, ["name", "team_type", "campus", "is_active"], as_dict=True
	)
	if not team or not team.get("name"):
		_error("INVALID_TARGET", "Target Team does not exist.")
	if not team.get("is_active") or team.get("team_type") != "Sales":
		_error("INVALID_TARGET", "Target Team must be an active Sales Team.")
	return team


def _load_pool(pool_name: str, branch: str) -> tuple[dict[str, Any], dict[str, Any]]:
	"""Resolve a named Student Pool and its authoritative Sales Team."""

	pool = frappe.db.get_value(
		"CRM Student Pool",
		pool_name,
		["name", "pool_name", "team", "campus", "is_active"],
		as_dict=True,
	)
	# During the rollout, a few clients still submit a Team name.  Resolve it
	# only when it maps to one named active pool; current Student state remains
	# the Team compatibility projection.
	if not pool:
		pool = frappe.db.get_value(
			"CRM Student Pool",
			{"team": pool_name, "campus": branch, "is_active": 1},
			["name", "pool_name", "team", "campus", "is_active"],
			as_dict=True,
		)
	if not pool or not pool.get("name") or not pool.get("is_active"):
		_error("INVALID_TARGET", "Target pool does not exist or is inactive.")
	if pool.get("campus") != branch:
		_error("CAMPUS_MISMATCH", "Target pool Campus must match the Student Campus.")
	team = _load_team(pool.get("team"))
	if team.get("campus") != branch:
		_error("CAMPUS_MISMATCH", "Target pool Team Campus must match the Student Campus.")
	return pool, team


def _pool_name_for_team(team_name: str | None, branch: str | None) -> str | None:
	if not team_name:
		return None
	try:
		return frappe.db.get_value(
			"CRM Student Pool",
			{"team": team_name, "campus": branch, "is_active": 1},
			"name",
		)
	except Exception:
		return None


def resolve_student_operational_target(
	student, target_kind: str, target_id: str, target_team_id: str | None = None, *, actor: str | None = None
) -> dict[str, Any]:
	"""Resolve and validate one owner-or-pool topology from authoritative fields."""

	target_kind = _required_text(target_kind, "INVALID_TARGET", "target_kind")
	target_id = _required_text(target_id, "INVALID_TARGET", "target_id")
	if target_kind not in {"owner", "pool"}:
		_error("INVALID_TARGET", "target_kind must be owner or pool.")
	branch = student.get("branch")
	if not branch:
		_error("INVALID_TARGET", "Student Campus is required for ownership.")
	profile = None
	if actor:
		profile, _ = _authorize(actor)

	if target_kind == "pool":
		pool, team = _load_pool(target_id, branch)
		if target_team_id and target_team_id != team.name:
			_error("INVALID_TARGET", "Pool target_team_id must match the pool Team.")
		if actor and profile:
			_assert_actor_target_scope(actor, profile, team.name)
		return {
			"target_kind": "pool",
			"target_id": pool.name,
			"owner_staff": None,
			"owning_team": team.name,
			"pool": pool,
			"team": team,
		}

	if not target_team_id:
		_error("INVALID_TARGET", "target_team_id is required for an owner target.")
	team = _load_team(target_team_id)
	if team.get("campus") != branch:
		_error("CAMPUS_MISMATCH", "Target Team Campus must match the Student Campus.")
	staff = frappe.db.get_value(
		"CRM Staff", target_id, ["name", "user", "is_active", "campus"], as_dict=True
	)
	if not staff or not staff.get("name") or not staff.get("is_active"):
		_error("INVALID_TARGET", "Target Staff must be active.")
	if staff.get("campus") and staff.get("campus") != branch:
		_error("CAMPUS_MISMATCH", "Target Staff Campus must match the Student Campus.")
	if not staff.get("user") or resolve_crm_profile(frappe.get_roles(staff.user)) != "sales":
		_error("INVALID_TARGET", "Target Staff must have exactly the canonical Sale profile.")
	memberships = frappe.get_all(
		"CRM Team Membership",
		filters={"parent": staff.name, "parenttype": "CRM Staff", "team": team.name},
		fields=["name", "team", "function"],
	)
	active_memberships = [row for row in memberships if not row.get("function") or row.function == "Sale"]
	if len(active_memberships) != 1:
		_error("INVALID_TARGET", "Target Staff must have exactly one active Sale membership in target Team.")
	if actor and profile:
		_assert_actor_target_scope(actor, profile, team.name)
	return {
		"target_kind": "owner",
		"target_id": staff.name,
		"owner_staff": staff.name,
		# Student topology is XOR: an owner target keeps the Team as event/scope
		# context but does not also populate the pool projection.
		"owning_team": None,
		"team": team,
		"staff": staff,
		"membership": active_memberships[0],
	}


def _revision_field() -> str | None:
	fields = _doctype_fields("CRM Student")
	for fieldname in ("ownership_revision", "revision"):
		if fieldname in fields:
			return fieldname
	return None


def _current_revision(student) -> Any:
	fieldname = _revision_field()
	if fieldname:
		return student.get(fieldname) or 0
	return student.get("modified")


def _next_revision(student, current):
	if _revision_field():
		try:
			return int(current or 0) + 1
		except (TypeError, ValueError):
			_error("INVALID_REVISION", "Student ownership revision is invalid.")
	# Phase 3.1 adds ownership_revision.  The fallback keeps the command
	# diagnosable on an un-migrated checkout but cannot pretend modified is a
	# durable integer revision.
	return current


def _actor_scope_snapshot(actor: str, profile: str, teams: list[dict[str, Any]]) -> str:
	snapshot = {
		"profile": profile,
		"teams": sorted(team.get("name") for team in teams if team.get("name")),
		"campuses": sorted({team.get("campus") for team in teams if team.get("campus")}),
	}
	return _canonical_json(snapshot)


def _receipt_values(
	*,
	command_key: str,
	actor: str,
	idempotency_key: str,
	fingerprint: str,
	student_name: str,
	correlation_id: str,
	status: str,
	result: dict[str, Any] | None = None,
	error_code: str | None = None,
	scope_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
	result_json = _canonical_json(result) if result is not None else None
	now = now_datetime()
	return {
		"receipt_key": command_key,
		"command_key": command_key,
		"command_key_version": 1,
		"command_kind": "ownership",
		"kind": "ownership",
		"principal": actor,
		"actor": actor,
		"idempotency_key": idempotency_key,
		"request_fingerprint": fingerprint,
		"fingerprint": fingerprint,
		"target_student": student_name,
		"student": student_name,
		"aggregate_name": student_name,
		"correlation_id": correlation_id,
		"correlation_token": correlation_id,
		"scope_snapshot": scope_snapshot or {},
		"policy_version": POLICY_VERSION,
		"schema_version": SCHEMA_VERSION,
		"request_received_at": now,
		"completed_at": now if status != "processing" else None,
		"status": status,
		"outcome": status,
		"error_code": error_code,
		"result_json": result_json,
		"result": result_json,
		"result_revision": result.get("revision") if result else None,
	}


def _event_values(
	*,
	student_name: str,
	actor: str,
	actor_scope: str,
	previous_owner: str | None,
	previous_pool: str | None,
	target: dict[str, Any],
	previous_revision: Any,
	next_revision: Any,
	command_key: str,
	idempotency_key: str,
	reason: str,
	correlation_id: str,
	receipt_name: str,
) -> dict[str, Any]:
	before = {"owner_staff": previous_owner, "owning_team": previous_pool}
	after = {"owner_staff": target.get("owner_staff"), "owning_team": target.get("owning_team")}
	if target.get("owner_staff"):
		event_type = "reassigned" if previous_owner else "owner_assigned"
	elif previous_owner:
		event_type = "released"
	else:
		event_type = "pool_assigned"
	return {
		"event_id": str(uuid.uuid4()),
		"event_type": event_type,
		"student": student_name,
		"aggregate_name": student_name,
		"aggregate_doctype": "CRM Student",
		"previous_revision": previous_revision,
		"revision": next_revision,
		"aggregate_revision": next_revision,
		"prior_owner_staff": previous_owner,
		"next_owner_staff": target.get("owner_staff"),
		"prior_owning_team": previous_pool,
		"next_owning_team": target.get("pool", {}).get("name") if target.get("pool") else None,
		"from_owner_staff": previous_owner,
		"to_owner_staff": target.get("owner_staff"),
		"from_owning_team": previous_pool,
		"to_owning_team": target.get("owning_team") or target.get("team", {}).get("name"),
		"before_state": before,
		"after_state": after,
		"before_json": _canonical_json(before),
		"after_json": _canonical_json(after),
		"before": _canonical_json(before),
		"after": _canonical_json(after),
		"actor": actor,
		"changed_by": actor,
		"actor_scope_snapshot": actor_scope,
		"scope_snapshot": json.loads(actor_scope),
		"policy_version": POLICY_VERSION,
		"schema_version": SCHEMA_VERSION,
		"command_receipt": receipt_name,
		"command_key": command_key,
		"idempotency_key": idempotency_key,
		"correlation_id": correlation_id,
		"correlation_token": correlation_id,
		"reason": reason,
		"reason_sensitivity": "operational",
		"event_at": now_datetime(),
		"occurred_at": now_datetime(),
	}


def change_student_ownership(
	student: str,
	target_kind: str,
	target_id: str,
	target_team_id: str | None,
	reason: str,
	idempotency_key: str,
	expected_revision: Any,
	correlation_id: str,
) -> dict[str, Any]:
	"""Atomically change one Student's owner/pool and append one event.

	The command locks receipt → Student → target Team/membership.  Receipt and
	event writes are rolled back together with the Student projection on every
	error, so a retry cannot observe a half-applied ownership transition.
	"""

	student_name = _required_text(student, "INVALID_INPUT", "student")
	target_kind = _required_text(target_kind, "INVALID_INPUT", "target_kind")
	target_id = _required_text(target_id, "INVALID_INPUT", "target_id")
	reason = _required_text(reason, "INVALID_INPUT", "reason", max_length=2000)
	idempotency_key = _required_text(idempotency_key, "INVALID_INPUT", "idempotency_key")
	correlation_id = _required_text(correlation_id, "INVALID_INPUT", "correlation_id")
	if expected_revision in (None, ""):
		_error("INVALID_INPUT", "expected_revision is required.")

	actor = _current_actor()
	profile, actor_policy = _authorize(actor)
	_ensure_schema()

	request = {
		"student": student_name,
		"target_kind": target_kind,
		"target_id": target_id,
		"target_team_id": target_team_id,
		"reason": reason,
		"correlation_id": correlation_id,
		"expected_revision": str(expected_revision),
	}
	fingerprint = _fingerprint(request)
	keys = ownership_command_keys(actor, idempotency_key)
	command_key = keys[0]

	try:
		# Scope is checked from the current Student before any target Staff/Team
		# lookup.  A historic event snapshot is never an authorization grant.
		student_doc = frappe.get_doc("CRM Student", student_name)
		if not has_student_permission(student_doc, user=actor, permission_type="read"):
			_error("OUT_OF_SCOPE", "Student is outside the actor's current scope.")

		receipt = _lock_receipt(keys)
		if receipt:
			return _replay_receipt(receipt, fingerprint)

		# Receipt is inserted before the aggregate lock to reserve the unique
		# idempotency key.  A duplicate insert is handled as a replay below.
		try:
			receipt = _insert_audit_doc(
				RECEIPT_DOCTYPE,
				_receipt_values(
					command_key=command_key,
					actor=actor,
					idempotency_key=idempotency_key,
					fingerprint=fingerprint,
					student_name=student_name,
					correlation_id=correlation_id,
					status="pending",
				),
			)
		except Exception as exc:
			# Two workers may pass the read before either inserts the unique key.
			# MariaDB reports that race as a duplicate insert; re-read the locked
			# receipt and apply the normal fingerprint/replay contract.
			if exc.__class__.__name__ != "DuplicateEntryError":
				raise
			frappe.db.rollback()
			receipt = _lock_receipt(keys)
			if receipt:
				return _replay_receipt(receipt, fingerprint)
			raise
		_lock("CRM Student", student_name)
		student_doc = frappe.get_doc("CRM Student", student_name)
		if not has_student_permission(student_doc, user=actor, permission_type="read"):
			_error("OUT_OF_SCOPE", "Student is outside the actor's current scope.")
		current_revision = _current_revision(student_doc)
		if str(current_revision) != str(expected_revision):
			_error("STALE_OWNERSHIP_REVISION", "Student ownership changed; refresh before retrying.")
		previous_owner, previous_pool = _validate_current_topology(student_doc)
		# Resolve only after the Student lock.  The authoritative branch and the
		# actor's current Team/Campus scope must be evaluated against the same
		# snapshot that will be mutated.
		target = resolve_student_operational_target(
			student_doc, target_kind, target_id, target_team_id, actor=actor
		)
		_lock("CRM Team", target["owning_team"])
		if target.get("staff"):
			_lock("CRM Staff", target["staff"]["name"])
		if target.get("membership"):
			_lock("CRM Team Membership", target["membership"]["name"])

		# The projection is deliberately a narrow db update: calling Student.save()
		# would append the legacy child-table assignment log and create a second,
		# non-canonical ownership history.  Every supported writer enters here.
		next_revision = _next_revision(student_doc, current_revision)
		updates = {
			"owner_staff": target.get("owner_staff"),
			"owning_team": target.get("owning_team"),
			"assigned_to": target.get("owner_staff"),
		}
		if _revision_field():
			updates[_revision_field()] = next_revision
		frappe.db.set_value("CRM Student", student_name, updates, update_modified=True)

		teams = _team_rows_for_actor(actor)
		actor_scope = _actor_scope_snapshot(actor, profile, teams)
		previous_pool_name = _pool_name_for_team(previous_pool, student_doc.get("branch"))
		event = _insert_audit_doc(
			OWNERSHIP_EVENT_DOCTYPE,
			_event_values(
				student_name=student_name,
				actor=actor,
				actor_scope=actor_scope,
				previous_owner=previous_owner,
				previous_pool=previous_pool_name,
				target=target,
				previous_revision=current_revision,
				next_revision=next_revision,
				command_key=command_key,
				idempotency_key=idempotency_key,
				reason=reason,
				correlation_id=correlation_id,
				receipt_name=receipt.name,
			),
		)

		result = {
			"status": "applied",
			"student": student_name,
			"target_kind": target["target_kind"],
			"target_id": target["target_id"],
			"owner_staff": target.get("owner_staff"),
			"owning_team": target.get("owning_team"),
			"previous_owner_staff": previous_owner,
			"previous_owning_team": previous_pool,
			"revision": next_revision,
			"event": event.name,
			"correlation_id": correlation_id,
			"policy_version": POLICY_VERSION,
			"replayed": False,
		}
		result["receipt"] = receipt.name
		completion_values = _receipt_values(
			command_key=command_key,
			actor=actor,
			idempotency_key=idempotency_key,
			fingerprint=fingerprint,
			student_name=student_name,
			correlation_id=correlation_id,
			status="applied",
			result=result,
			scope_snapshot=json.loads(actor_scope),
		)
		# These request-identity fields are immutable once the reservation row is
		# inserted; only completion/result fields may be updated.
		for fieldname in ("command_kind", "command_key", "request_fingerprint", "actor", "request_received_at"):
			completion_values.pop(fieldname, None)
		_set_supported(receipt, completion_values)
		# Receipt is append-only evidence.  Updating its initially reserved
		# processing row is the one supported completion mutation.
		receipt.save(ignore_permissions=True)
		frappe.db.commit()
		return result
	except StudentOwnershipError:
		frappe.db.rollback()
		raise
	except Exception:
		frappe.db.rollback()
		raise


def _read_actor() -> tuple[str, str, set[str]]:
	actor = _current_actor()
	if actor in ("Guest", "None"):
		_error("UNAUTHORIZED", "Authentication is required.")
	if actor == "Administrator":
		return actor, "platform_superuser", {"student.audit.reason.read"}
	roles = set(frappe.get_roles(actor))
	profile = resolve_crm_profile(roles)
	if not profile:
		_error("UNAUTHORIZED", "You are not permitted to view Student ownership.")
	return actor, profile, set(capabilities_for_roles(roles))


def _student_for_read(student_name: str):
	student_name = _required_text(student_name, "INVALID_INPUT", "student")
	actor, profile, capabilities = _read_actor()
	student_doc = frappe.get_doc("CRM Student", student_name)
	if not has_student_permission(student_doc, user=actor, permission_type="read"):
		_error("OUT_OF_SCOPE", "Student is outside the actor's current scope.")
	return student_doc, actor, profile, capabilities


def _label(doctype: str, name: str | None, fieldname: str) -> str | None:
	if not name:
		return None
	return _get_value(doctype, name, fieldname, default=name) or name


def get_student_ownership(student: str) -> dict[str, Any]:
	"""Return the current ownership projection and scoped append-only history."""

	student_doc, actor, profile, capabilities = _student_for_read(student)
	result = {
		"student": student_doc.name,
		"owner_staff": student_doc.get("owner_staff"),
		"owner_staff_label": _label("CRM Staff", student_doc.get("owner_staff"), "full_name"),
		"owning_team": student_doc.get("owning_team"),
		"owning_team_label": _label("CRM Team", student_doc.get("owning_team"), "team_name"),
		"revision": _current_revision(student_doc),
		"events": [],
	}
	if not frappe.db.exists("DocType", OWNERSHIP_EVENT_DOCTYPE):
		return result
	fields = _doctype_fields(OWNERSHIP_EVENT_DOCTYPE)
	student_field = "student" if "student" in fields else "aggregate_name"
	projection = [
		field
		for field in (
			"name",
			"event_type",
			"student",
			"prior_owner_staff",
			"next_owner_staff",
			"prior_owning_team",
			"next_owning_team",
			"aggregate_name",
			"from_owner_staff",
			"to_owner_staff",
			"from_owning_team",
			"to_owning_team",
			"previous_revision",
			"revision",
			"aggregate_revision",
			"actor",
			"changed_by",
			"reason",
			"reason_sensitivity",
			"correlation_id",
			"correlation_token",
			"event_at",
			"occurred_at",
			"creation",
		)
		if field in fields or field in {"name", "creation"}
	]
	rows = frappe.get_all(
		OWNERSHIP_EVENT_DOCTYPE,
		filters={student_field: student_doc.name},
		fields=projection,
		order_by="creation asc",
		ignore_permissions=True,
	)
	can_read_reason = "student.audit.reason.read" in capabilities
	for row in rows:
		event = dict(row)
		event.setdefault("from_owner_staff", event.get("prior_owner_staff"))
		event.setdefault("to_owner_staff", event.get("next_owner_staff"))
		event.setdefault("from_owning_team", event.get("prior_owning_team"))
		event.setdefault("to_owning_team", event.get("next_owning_team"))
		event.setdefault("occurred_at", event.get("event_at"))
		if not can_read_reason:
			event.pop("reason", None)
			event.pop("correlation_id", None)
		elif event.get("reason_sensitivity") == "restricted":
			# Restricted reasons need a separately approved audit workflow.  The
			# ownership read projection never returns them to routine operators.
			event["reason"] = None
		result["events"].append(event)
	result["history"] = result["events"]
	return result


def get_eligible_ownership_targets(student: str) -> dict[str, list[dict[str, Any]]]:
	"""Return only server-resolved owner/pool choices allowed for this Student."""

	student_doc, actor, profile, _ = _student_for_read(student)
	_authorize(actor)
	branch = student_doc.get("branch")
	if not branch:
		_error("INVALID_TARGET", "Student Campus is required for ownership.")
	actor_teams = _team_rows_for_actor(actor) if profile == "lead_sales" else None
	allowed_team_names = {team.get("name") for team in actor_teams or []}
	team_filters = {"campus": branch, "team_type": "Sales", "is_active": 1}
	teams = frappe.get_all("CRM Team", filters=team_filters, fields=["name", "team_name", "campus", "is_active"])
	if profile == "lead_sales":
		teams = [team for team in teams if team.name in allowed_team_names]
	team_names = {team.name for team in teams}
	pool_rows = frappe.get_all(
		"CRM Student Pool",
		filters={"campus": branch, "is_active": 1},
		fields=["name", "pool_name", "team", "campus", "is_active"],
	)
	pool_rows = [pool for pool in pool_rows if pool.get("team") in team_names]
	pools = [
		{"name": pool.name, "label": pool.get("pool_name") or pool.name, "campus": pool.get("campus"), "team": pool.get("team")}
		for pool in pool_rows
	]

	team_by_name = {team.name: team for team in teams}
	owners = []
	staff_rows = frappe.get_all(
		"CRM Staff",
		filters={"is_active": 1},
		fields=["name", "full_name", "user", "campus"],
	)
	for staff in staff_rows:
		if staff.get("campus") and staff.campus != branch:
			continue
		if not staff.get("user") or resolve_crm_profile(frappe.get_roles(staff.user)) != "sales":
			continue
		memberships = frappe.get_all(
			"CRM Team Membership",
			filters={"parent": staff.name, "parenttype": "CRM Staff"},
			fields=["name", "team", "function"],
		)
		eligible = [
			row
			for row in memberships
			if row.get("team") in team_by_name and (not row.get("function") or row.function == "Sale")
		]
		if len(eligible) != 1:
			continue
		team = team_by_name[eligible[0].team]
		owners.append(
			{
				"name": staff.name,
				"label": staff.get("full_name") or staff.name,
				"team": team.name,
				"campus": team.get("campus"),
			}
		)
	return {"owners": owners, "pools": pools}
