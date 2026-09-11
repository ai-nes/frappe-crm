"""Permission-only batch checks for opaque Copilot session dependencies."""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

import frappe


def _allowed_origins() -> set[str]:
	configured = frappe.conf.get("crm_chatbot_origins") or frappe.conf.get("crm_chatbot_origin") or "http://localhost:5173"
	if isinstance(configured, str):
		return {item.strip().rstrip("/") for item in configured.split(",") if item.strip()}
	if isinstance(configured, (list, tuple, set)):
		return {str(item).strip().rstrip("/") for item in configured if str(item).strip()}
	return set()


def _validate_origin(origin: str | None) -> str:
	value = origin.strip().rstrip("/") if isinstance(origin, str) else ""
	if not value or value not in _allowed_origins():
		frappe.throw("Copilot context origin is not configured.", frappe.PermissionError)
	return value


def _redis():
	cache = frappe.cache()
	# Frappe 15 exposes the Redis wrapper itself with ``set``/``eval``;
	# older deployments may expose a separate connection through
	# ``get_redis_conn``. Support both shapes without weakening the atomic
	# consume requirement below.
	get_redis_conn = getattr(cache, "get_redis_conn", None)
	redis = get_redis_conn() if callable(get_redis_conn) else cache
	if redis is None or not hasattr(redis, "eval") or not hasattr(redis, "set"):
		frappe.throw("Copilot context store is unavailable.", frappe.ValidationError)
	return redis


@frappe.whitelist(methods=["POST"])
def authorize_subject_refs(subjects=None) -> dict:
	"""Return only currently readable subject keys; never echo denied rows."""
	if isinstance(subjects, str):
		subjects = frappe.parse_json(subjects)
	if not isinstance(subjects, list) or len(subjects) > 100:
		frappe.throw("subjects must be a bounded list.", frappe.ValidationError)
	authorized: list[str] = []
	for item in subjects:
		if not isinstance(item, dict):
			continue
		kind = item.get("kind")
		subject_id = item.get("subject_id")
		if kind not in {"student", "school"} or not isinstance(subject_id, str) or not subject_id.strip() or len(subject_id) > 180:
			continue
		doctype = "CRM Student" if kind == "student" else "CRM High School"
		if not frappe.has_permission(doctype, "read", subject_id.strip(), user=frappe.session.user):
			continue
		expected_revision = item.get("source_revision")
		if kind == "student" and expected_revision not in (None, "", "unknown"):
			current_revision = str(frappe.db.get_value(doctype, subject_id.strip(), "student_context_revision") or 0)
			if current_revision != str(expected_revision):
				continue
		if frappe.has_permission(doctype, "read", subject_id.strip(), user=frappe.session.user):
			authorized.append(f"{kind}:{subject_id.strip()}")
	return {"contract_version": "copilot-subject-authorization-v1", "authorized": authorized}


@frappe.whitelist(methods=["POST"])
def issue_context_handle(student: str, mode: str = "chat", origin: str | None = None) -> dict:
	"""Mint a short-lived, one-time context handle without putting CRM state in a URL."""
	if mode != "chat":
		frappe.throw("Unsupported Copilot context mode.", frappe.ValidationError)
	if not isinstance(student, str) or not student.strip() or len(student) > 180:
		frappe.throw("student is required.", frappe.ValidationError)
	student = student.strip()
	if not frappe.has_permission("CRM Student", "read", student, user=frappe.session.user):
		frappe.throw("Student context is not permitted.", frappe.PermissionError)
	origin = _validate_origin(origin)
	revision = str(frappe.db.get_value("CRM Student", student, "student_context_revision") or 0)
	nonce = secrets.token_urlsafe(32)
	handle = f"ctx_{nonce}"
	payload = {
		"user": frappe.session.user,
		"subject_kind": "student",
		"subject_id": student,
		"context_revision": revision,
		"mode": mode,
		"origin": origin,
		"issued_at": datetime.now(timezone.utc).isoformat(),
		"expires_at": (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat(),
	}
	_redis().set(
		"copilot-context:" + hashlib.sha256(handle.encode()).hexdigest(),
		json.dumps(payload, separators=(",", ":")), ex=60, nx=True,
	)
	return {"contract_version": "copilot-context-handle-v1", "handle": handle, "expires_in": 60, "mode": mode}


@frappe.whitelist(methods=["POST"])
def redeem_context_handle(handle: str, origin: str | None = None) -> dict:
	"""Consume a handle once and recheck current row scope before returning it."""
	if not isinstance(handle, str) or not handle.startswith("ctx_") or len(handle) > 128:
		frappe.throw("Invalid Copilot context handle.", frappe.ValidationError)
	key = "copilot-context:" + hashlib.sha256(handle.encode()).hexdigest()
	origin = _validate_origin(origin)
	redis = _redis()
	# Compare-and-delete in one Redis script. A second redeemer cannot read a
	# usable payload after the first script has matched the bound principal and
	# origin; a wrong principal/origin does not consume the handle.
	value = redis.eval(
		"local value = redis.call('GET', KEYS[1]); "
		"if not value then return false end; "
		"local payload = cjson.decode(value); "
		"if payload.user ~= ARGV[1] or payload.origin ~= ARGV[2] then return 'DENIED' end; "
		"redis.call('DEL', KEYS[1]); return value",
		1, key, frappe.session.user, origin,
	)
	if not value or value is False:
		frappe.throw("Copilot context handle is expired or already used.", frappe.DoesNotExistError)
	if value in {b"DENIED", "DENIED"}:
		frappe.throw("Copilot context handle is not valid for this user.", frappe.PermissionError)
	payload = frappe.parse_json(value.decode() if isinstance(value, bytes) else value)
	if not isinstance(payload, dict):
		frappe.throw("Copilot context handle is invalid.", frappe.ValidationError)
	student = payload.get("subject_id")
	if not frappe.has_permission("CRM Student", "read", student, user=frappe.session.user):
		frappe.throw("Student context is not permitted.", frappe.PermissionError)
	current_revision = str(frappe.db.get_value("CRM Student", student, "student_context_revision") or 0)
	if current_revision != str(payload.get("context_revision")):
		frappe.throw("Copilot context is stale; select the Student again.", frappe.ValidationError)
	return {"contract_version": "copilot-context-handle-v1", "subject": {"kind": payload["subject_kind"], "id": student}, "context_revision": current_revision, "mode": payload["mode"]}
