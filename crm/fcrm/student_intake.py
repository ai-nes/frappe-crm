"""Authoritative Student intake command.

The intake boundary is deliberately small. It resolves a phone/email identity
and an admission cycle, then creates one Student case and its Case Key in the
same transaction. National ID remains an optional strong observation and
conflict signal; it never establishes an identity by itself.

The module does not create Contacts.  The small amount of metadata probing in
this file is intentional: the data-contract migration and this command can be
deployed in separate bench migrations, while the command still fails closed
when its durable surfaces are unavailable.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import struct
import uuid
from contextlib import contextmanager
from typing import Any

import frappe
from frappe.utils import now_datetime

from crm.fcrm.role_policy import resolve_crm_profile
from crm.utils import normalize_phone_for_lookup

POLICY_VERSION = "student-intake"
HMAC_VERSION = "v1"
REVIEW_OPEN = "open"
REVIEW_APPLIED = "applied"
SUBMIT_CAPABILITY = "student.intake.submit"
INTERACTION_CAPABILITY = "student.interaction.ingest"
REVIEW_CAPABILITY = "student.intake.review.decide"

IDENTITY_DOCTYPE = "CRM Student Identity"
CASE_KEY_DOCTYPE = "CRM Student Case Key"
RECEIPT_DOCTYPE = "CRM Student Command Receipt"
REVIEW_DOCTYPE = "CRM Student Intake Review"
IDENTIFIER_DOCTYPES = (
	"CRM Student Identity Identifier",
	"CRM Identity Identifier",
	"CRM Student Identifier",
)

_MEMORY_RECEIPTS: dict[str, dict[str, Any]] = {}
_MISSING = object()


class StudentIntakeError(getattr(frappe, "ValidationError", Exception)):
	"""Stable, machine-readable command error.

	Frappe serializes the message for REST callers; ``code`` remains available to
	Python callers and to the API adapter without exposing candidate PII.
	"""

	def __init__(self, code: str, message: str | None = None, **details: Any):
		self.code = code
		self.error_code = code
		self.details = details
		super().__init__(message or code)


def _fail(code: str, message: str | None = None, **details: Any):
	raise StudentIntakeError(code, message, **details)


def _text(value: Any) -> str | None:
	if value is None:
		return None
	if not isinstance(value, str):
		value = str(value)
	value = value.strip()
	return value or None


def normalize_email(value: Any) -> str | None:
	"""Normalize an email for an observation lookup, never for display."""
	value = _text(value)
	if not value or "@" not in value or value.startswith("@") or value.endswith("@"):
		return None
	return value.casefold()


def normalize_phone(value: Any) -> str | None:
	"""Return the project's canonical Vietnamese national phone form."""
	value = _text(value)
	if not value:
		return None
	value = normalize_phone_for_lookup(value)
	return value if re.fullmatch(r"0\d{9}", value or "") else None


def normalize_national_id(value: Any) -> str | None:
	"""Normalize an approved Vietnamese national identifier.

	Both legacy nine-digit IDs and twelve-digit CCCDs are accepted.  Formatting
	characters are discarded only after the value has been converted to text;
	letters and arbitrary long values are rejected rather than used as a weak
	match.
	"""
	value = _text(value)
	if not value:
		return None
	digits = re.sub(r"[ .-]", "", value)
	return digits if re.fullmatch(r"\d{9}|\d{12}", digits) else None


def encode_key(domain: str, *parts: Any) -> bytes:
	"""Encode a domain-separated, length-delimited HMAC input.

	A delimiter-free concatenation is unsafe (``ab`` + ``c`` equals ``a`` +
	``bc``); every value therefore carries an unsigned 32-bit big-endian byte
	length.  The domain is fixed by the caller and is not client-controlled.
	"""

	if not isinstance(domain, str) or not domain:
		raise ValueError("domain is required")
	out = bytearray(domain.encode("utf-8"))
	for part in parts:
		if part is None:
			part = ""
		if not isinstance(part, bytes):
			part = str(part).encode("utf-8")
		if len(part) > 0xFFFFFFFF:
			raise ValueError("key component is too large")
		out.extend(struct.pack(">I", len(part)))
		out.extend(part)
	return bytes(out)


def keyed_digest(secret: str | bytes, domain: str, *parts: Any) -> str:
	if isinstance(secret, str):
		secret = secret.encode("utf-8")
	return hmac.new(secret, encode_key(domain, *parts), hashlib.sha256).hexdigest()


def body_fingerprint(body: bytes | str | dict[str, Any]) -> str:
	if isinstance(body, bytes):
		value = body
	elif isinstance(body, str):
		value = body.encode("utf-8")
	else:
		value = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
	return hashlib.sha256(value).hexdigest()


def _json(value: Any) -> str:
	return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


PROVENANCE_SCHEMA_VERSION = "student-intake-provenance"
MAX_PROVENANCE_BYTES = 4096
PROVENANCE_ALLOWED_KEYS = frozenset(
	{
		"source_system",
		"source_namespace",
		"external_id",
		"source_record_id",
		"idempotency_key",
		"captured_at",
		"lead_source",
		"campaign_code",
		"event_code",
		"province_code",
		"high_school_code",
		"major_code",
		"study_stage",
		"consent",
		"raw_payload",
	}
)


def redact_provenance(payload: dict[str, Any] | None) -> dict[str, Any]:
	"""Return bounded provenance metadata without retaining request PII."""
	if not isinstance(payload, dict):
		return {"schema_version": PROVENANCE_SCHEMA_VERSION}

	redacted: dict[str, Any] = {"schema_version": PROVENANCE_SCHEMA_VERSION}
	for fieldname in PROVENANCE_ALLOWED_KEYS - {"raw_payload", "consent"}:
		value = payload.get(fieldname)
		if isinstance(value, str):
			value = value[:256]
		if value is not None and isinstance(value, (str, int, float, bool)):
			redacted[fieldname] = value

	consent = payload.get("consent")
	if isinstance(consent, dict):
		redacted["consent"] = {
			"granted": consent.get("granted") if isinstance(consent.get("granted"), bool) else None,
			"granted_at": str(consent.get("granted_at"))[:64] if consent.get("granted_at") else None,
			"purpose": str(consent.get("purpose"))[:128] if consent.get("purpose") else None,
			"scope": str(consent.get("scope"))[:128] if consent.get("scope") else None,
		}

	raw_payload = payload.get("raw_payload")
	if raw_payload is not None:
		try:
			redacted["raw_payload_fingerprint"] = body_fingerprint(raw_payload)
		except (TypeError, ValueError):
			redacted["raw_payload_fingerprint"] = "unavailable"

	try:
		if len(_json(redacted).encode("utf-8")) <= MAX_PROVENANCE_BYTES:
			return redacted
	except (TypeError, ValueError):
		pass
	return {"schema_version": PROVENANCE_SCHEMA_VERSION, "truncated": True}


def encrypt_provenance(payload: dict[str, Any]) -> str:
	"""Encrypt already-redacted provenance with the site-owned Frappe key."""
	try:
		from frappe.utils.password import encrypt

		expected = encrypt(_json(payload))
	except (ImportError, AttributeError, TypeError, ValueError) as exc:
		_fail("CONFIGURATION_ERROR", "Receipt provenance encryption is unavailable.", cause=str(exc))
	if not expected:
		_fail("CONFIGURATION_ERROR", "Receipt provenance encryption returned no value.")
	return str(expected)


def _doctype_exists(doctype: str) -> bool:
	try:
		return bool(frappe.db.exists("DocType", doctype))
	except Exception:
		return False


def _meta(doctype: str):
	try:
		return frappe.get_meta(doctype)
	except Exception:
		return None


def _has_field(doctype: str, fieldname: str) -> bool:
	meta = _meta(doctype)
	if not meta:
		return False
	try:
		return bool(meta.get_field(fieldname))
	except Exception:
		try:
			return fieldname in meta.get_valid_columns()
		except Exception:
			return False


def _first_field(doctype: str, candidates: tuple[str, ...]) -> str | None:
	for candidate in candidates:
		if _has_field(doctype, candidate):
			return candidate
	return None


def _set_supported(doc, values: dict[str, Any]):
	for fieldname, value in values.items():
		if value is None:
			continue
		if _has_field(doc.doctype, fieldname):
			doc.set(fieldname, value)


def _supported_values(doctype: str, values: dict[str, Any]) -> dict[str, Any]:
	# Child-table linkage fields are mandatory even when older metadata snapshots
	# do not expose them through ``get_meta``.
	link_fields = {"parent", "parenttype", "parentfield"}
	return {
		key: value
		for key, value in values.items()
		if value is not None and (key in link_fields or _has_field(doctype, key))
	}


def _get_doc(doctype: str, name: str):
	return frappe.get_doc(doctype, name)


def _safe_get(doc: Any, *names: str, default: Any = None):
	for name in names:
		try:
			value = doc.get(name)
		except Exception:
			value = getattr(doc, name, None)
		if value is not None and value != "":
			return value
	return default


def _current_user() -> str:
	return _text(getattr(getattr(frappe, "session", None), "user", None)) or "Guest"


def _roles(user: str | None = None) -> set[str]:
	try:
		return set(frappe.get_roles(user or _current_user()))
	except Exception:
		return set()


def _resolve_authority(capability: str, *, signed_context: dict[str, Any] | None = None) -> dict[str, Any]:
	"""Resolve authority from server state, never from payload fields."""

	if signed_context:
		# A signed source is an explicitly provisioned integration principal.  The
		# adapter has already authenticated its namespace and supplies only the
		# configured scope; no request body value is trusted here.
		return {
			"actor_user": signed_context.get("actor_user") or "Signed Ingress",
			"actor_staff": signed_context.get("actor_staff"),
			"profile": "signed_ingress",
			"campus_scope": list(signed_context.get("campus_scope") or []),
			"team_scope": list(signed_context.get("team_scope") or []),
			"scope_all": bool(signed_context.get("scope_all")),
			"capability": capability,
			"signed": True,
		}

	user = _current_user()
	configured_service_user = _text(frappe.conf.get("crm_agents_service_user"))
	if configured_service_user and user == configured_service_user and capability == INTERACTION_CAPABILITY:
		return {
			"actor_user": user,
			"actor_staff": None,
			"profile": "service",
			"campus_scope": [],
			"team_scope": [],
			"scope_all": True,
			"capability": capability,
			"signed": False,
		}
	roles = _roles(user)
	# Administrator is the platform break-glass account, not a routine System
	# Manager profile.  It remains useful for migrations and isolated tests.
	if user == "Administrator":
		return {
			"actor_user": user,
			"actor_staff": None,
			"profile": "platform_superuser",
			"campus_scope": [],
			"team_scope": [],
			"capability": capability,
			"signed": False,
		}
	profile = resolve_crm_profile(roles)
	allowed = (
		profile in {"sales", "lead_sales", "admissions_director"}
		and capability in {SUBMIT_CAPABILITY, INTERACTION_CAPABILITY}
	) or (profile in {"lead_sales", "admissions_director"} and capability == REVIEW_CAPABILITY)
	if not allowed:
		_fail("UNAUTHORIZED", "The current CRM profile cannot execute this command.")
	staff = None
	try:
		staff = frappe.db.get_value("CRM Staff", {"user": user}, ["name", "campus"], as_dict=True) or {}
	except Exception:
		staff = {}
	team_scope = _staff_team_scope(staff.get("name"), staff.get("campus"), profile)
	return {
		"actor_user": user,
		"actor_staff": staff.get("name"),
		"profile": profile,
		"campus_scope": [staff.get("campus")] if staff.get("campus") else [],
		"team_scope": team_scope,
		"capability": capability,
		"signed": False,
	}


def _staff_team_scope(staff_name: str | None, campus: str | None, profile: str | None) -> list[str]:
	if profile == "admissions_director":
		filters = {"is_active": 1, "team_type": "Sales"}
		try:
			return sorted(frappe.get_all("CRM Team", filters=filters, pluck="name"))
		except Exception:
			return []
	if not staff_name:
		return []
	try:
		memberships = frappe.get_all(
			"CRM Team Membership",
			filters={"parent": staff_name, "parenttype": "CRM Staff"},
			pluck="team",
		)
		if not memberships:
			return []
		filters = {"name": ["in", memberships], "is_active": 1, "team_type": "Sales"}
		if campus:
			filters["campus"] = campus
		return sorted(frappe.get_all("CRM Team", filters=filters, pluck="name"))
	except Exception:
		return []


def _is_first_party_manual_intake(authority: dict[str, Any]) -> bool:
	"""Whether initial ownership must be derived from the signed-in CRM user."""
	return not authority.get("signed") and authority.get("profile") in {"sales", "lead_sales"}


def _resolve_manual_initial_ownership(authority: dict[str, Any]) -> tuple[str, str, str | None]:
	"""Resolve the only permitted initial ownership for a manual Sale/Lead intake.

	The client never selects a staff member or pool.  Both the Campus and the
	primary eligible Sales Team are authoritative CRM topology.  A Sale owns the
	new case directly; a Lead Sale creates it in their primary pool for normal
	routing.  Missing or ambiguous topology fails closed with a stable code.
	"""
	staff_name = _text(authority.get("actor_staff"))
	campuses = [_text(value) for value in authority.get("campus_scope") or []]
	campuses = [value for value in campuses if value]
	if not staff_name or len(set(campuses)) != 1:
		_fail("INVALID_TOPOLOGY", "The current CRM Staff record needs one Campus.")
	campus = campuses[0]
	try:
		memberships = frappe.get_all(
			"CRM Team Membership",
			filters={"parent": staff_name, "parenttype": "CRM Staff", "is_primary": 1},
			fields=["team", "is_primary"],
		)
	except Exception:
		_fail("INVALID_TOPOLOGY", "The current CRM Staff team membership is unavailable.")

	eligible_teams = []
	for membership in memberships:
		team_name = _text(membership.get("team"))
		if not team_name:
			continue
		team = frappe.db.get_value(
			"CRM Team", team_name, ["name", "campus", "team_type", "is_active"], as_dict=True
		)
		if team and team.is_active and team.team_type == "Sales" and team.campus == campus:
			eligible_teams.append(team.name)
	if not eligible_teams:
		_fail("NO_ELIGIBLE_POOL", "The current CRM Staff has no primary active Sales Team at their Campus.")
	if len(set(eligible_teams)) != 1:
		_fail("AMBIGUOUS_POOL", "The current CRM Staff has multiple primary eligible Sales Teams.")

	pool = _resolve_case_pool(eligible_teams[0], campus)
	assigned_to = staff_name if authority.get("profile") == "sales" else None
	return campus, pool.name, assigned_to


def _assert_campus_and_pool(payload: dict[str, Any], authority: dict[str, Any]) -> tuple[str, str]:
	campus = _text(payload.get("campus") or payload.get("branch"))
	configured_campuses = list(authority.get("campus_scope") or [])
	if not campus and len(configured_campuses) == 1:
		campus = _text(configured_campuses[0])
	if not campus:
		_fail("INVALID_INPUT", "Campus is required for Student intake.")
	if _doctype_exists("CRM Campus") and not frappe.db.exists("CRM Campus", campus):
		_fail("INVALID_INPUT", "Campus is not a valid CRM Campus.")
	allowed_campuses = set(authority.get("campus_scope") or [])
	if not authority.get("signed") and authority.get("profile") not in {
		"platform_superuser",
		"admissions_director",
	}:
		if campus not in allowed_campuses:
			_fail("UNAUTHORIZED", "The requested Campus is outside the current scope.")
	requested_pool = _text(payload.get("owning_team") or payload.get("pool") or payload.get("team"))
	eligible = set(authority.get("team_scope") or [])
	eligible_for_campus = set()
	for team_name in eligible:
		try:
			team = frappe.db.get_value(
				"CRM Team", team_name, ["name", "campus", "team_type", "is_active"], as_dict=True
			)
			if team and team.is_active and team.team_type == "Sales" and team.campus == campus:
				eligible_for_campus.add(team.name)
		except Exception:
			continue
	if authority.get("signed"):
		if not configured_campuses or campus not in set(configured_campuses):
			_fail("UNAUTHORIZED", "The signed source is not configured for this Campus.")
	if requested_pool:
		team_name = requested_pool
		try:
			if not frappe.db.exists("CRM Team", team_name):
				team_name = frappe.db.get_value("CRM Student Pool", requested_pool, "team") or team_name
			team = frappe.db.get_value(
				"CRM Team", team_name, ["name", "campus", "team_type", "is_active"], as_dict=True
			)
			if not team or not team.is_active or team.team_type != "Sales" or team.campus != campus:
				_fail(
					"NO_ELIGIBLE_POOL",
					"The requested pool does not match an active Sales Team at this Campus.",
				)
		except StudentIntakeError:
			raise
		except Exception:
			_fail("NO_ELIGIBLE_POOL", "The requested pool cannot be resolved.")
		if authority.get("signed") and team_name not in eligible_for_campus:
			_fail("NO_ELIGIBLE_POOL", "The requested pool is not eligible in this scope.")
		if (
			not authority.get("signed")
			and authority.get("profile") not in {"platform_superuser", "admissions_director"}
			and team_name not in eligible_for_campus
		):
			_fail("NO_ELIGIBLE_POOL", "The requested pool is not eligible in this scope.")
		return campus, team_name
	if eligible_for_campus:
		return campus, sorted(eligible_for_campus)[0]
	_fail("NO_ELIGIBLE_POOL", "No eligible Sales Team pool is available.")


def _parse_payload(payload: dict[str, Any] | str | None) -> dict[str, Any]:
	if payload is None:
		try:
			payload = frappe.request.get_json(silent=True)
		except Exception:
			payload = None
	if isinstance(payload, str):
		try:
			payload = json.loads(payload)
		except (TypeError, ValueError):
			_fail("INVALID_INPUT", "Payload must be a valid JSON object.")
	if not isinstance(payload, dict):
		_fail("INVALID_INPUT", "Payload must be a JSON object.")
	return payload


def _identity_candidate(payload: dict[str, Any]) -> dict[str, Any]:
	strong = normalize_national_id(
		payload.get("national_id")
		or payload.get("id_number")
		or payload.get("cccd")
		or payload.get("citizen_id")
	)
	phone = normalize_phone(payload.get("phone") or payload.get("mobile") or payload.get("telephone"))
	email = normalize_email(payload.get("email") or payload.get("email_id"))
	name = _text(payload.get("student_name") or payload.get("full_name"))
	if not name:
		name = " ".join(
			part for part in (_text(payload.get("firstname")), _text(payload.get("lastname"))) if part
		)
	return {"strong": strong, "phone": phone, "email": email, "name": name}


def _secret_versions() -> list[tuple[str, bytes]]:
	configured = None
	try:
		configured = frappe.conf.get("student_intake_hmac_secrets") or frappe.conf.get(
			"student_intake_hmac_secret"
		)
	except Exception:
		configured = None
	if not configured:
		configured = os.environ.get("CRM_STUDENT_INTAKE_HMAC_SECRET")
	if isinstance(configured, dict):
		return [
			(str(version), str(secret).encode("utf-8")) for version, secret in configured.items() if secret
		]
	if isinstance(configured, (list, tuple)):
		return [
			(HMAC_VERSION if idx == 0 else f"v{idx + 1}", str(value).encode("utf-8"))
			for idx, value in enumerate(configured)
			if value
		]
	if configured:
		return [(HMAC_VERSION, str(configured).encode("utf-8"))]
	try:
		# Every Frappe site has an encryption key. It is a safe deployment default
		# for local benches; production may still rotate a dedicated intake key.
		fallback = frappe.conf.get("encryption_key")
	except Exception:
		fallback = None
	if fallback:
		return [(HMAC_VERSION, str(fallback).encode("utf-8"))]
	return []


def receipt_keys(
	source_namespace: str,
	source_record_id: str,
	idempotency_key: str,
	principal: str,
	nonce: str | None = None,
	command_kind: str = "intake",
	source_revision: int | None = None,
):
	keys = []
	for version, secret in _secret_versions():
		source_parts = [source_namespace, source_record_id]
		if source_revision is not None:
			source_parts.append(str(source_revision))
		keys.append(
			{
				"version": version,
				"command_key": keyed_digest(
					secret, f"crm.receipt.command.{version}", command_kind, principal, idempotency_key
				),
				"source_key": keyed_digest(secret, f"crm.receipt.source.{version}", *source_parts),
				"nonce_key": keyed_digest(secret, f"crm.receipt.nonce.{version}", source_namespace, nonce)
				if nonce
				else None,
			}
		)
	return keys


def _lookup_receipt(keys: list[dict[str, Any]]) -> dict[str, Any] | None:
	for key_set in keys:
		for key_name in ("command_key", "source_key", "nonce_key"):
			key = key_set.get(key_name)
			if not key:
				continue
			cached = _MEMORY_RECEIPTS.get(key)
			if cached:
				return dict(cached)
			if not _doctype_exists(RECEIPT_DOCTYPE):
				continue
			try:
				rows = frappe.get_all(RECEIPT_DOCTYPE, filters={key_name: key}, fields=["*"])
			except Exception:
				rows = []
			if rows:
				return dict(rows[0])
	return None


def _receipt_response(receipt: dict[str, Any]) -> dict[str, Any]:
	result = receipt.get("result_json") or receipt.get("result")
	if isinstance(result, str):
		try:
			result = json.loads(result)
		except ValueError:
			result = None
	response = dict(result or {})
	if not response.get("student") and receipt.get("target_student"):
		response["student"] = receipt.get("target_student")
	if not response.get("review_id") and receipt.get("review"):
		response["review_id"] = receipt.get("review")
	if not response.get("revision") and receipt.get("result_revision") is not None:
		response["revision"] = receipt.get("result_revision")
	response.setdefault("outcome", receipt.get("outcome"))
	response.setdefault("receipt", receipt.get("name") or receipt.get("receipt"))
	if receipt.get("error_code"):
		response.setdefault("error_code", receipt["error_code"])
	return response


def _persist_receipt(
	keys: list[dict[str, Any]],
	*,
	request_fp: str,
	result: dict[str, Any],
	principal: str,
	source_namespace: str,
	_source_record_id: str,
	idempotency_key: str,
	correlation_id: str,
	nonce: str | None = None,
	kind: str = "intake",
	provenance_payload: dict[str, Any] | None = None,
):
	key_set = keys[0] if keys else {}
	command_kind = "review_decision" if kind == "review" else kind
	receipt_outcome = result.get("outcome")
	if kind == "review":
		receipt_outcome = "rejected" if result.get("decision") == "reject" else "applied"
	try:
		actor_value = principal if frappe.db.exists("User", principal) else "Administrator"
	except Exception:
		actor_value = principal
	now = now_datetime()
	encrypted_payload = None
	if provenance_payload is not None:
		encrypted_payload = encrypt_provenance(redact_provenance(provenance_payload))
	values = {
		"receipt_key": key_set.get("command_key"),
		"command_key": key_set.get("command_key"),
		"command_key_version": 1,
		"source_key": key_set.get("source_key"),
		"nonce_key": key_set.get("nonce_key"),
		"request_fingerprint": request_fp,
		"fingerprint": request_fp,
		"command_type": command_kind,
		"command_kind": command_kind,
		"outcome": receipt_outcome,
		"error_code": result.get("error_code"),
		"target_student": result.get("student"),
		"target_contact": result.get("contact"),
		"student": result.get("student"),
		"review": result.get("review_id"),
		"review_id": result.get("review_id"),
		"result_revision": result.get("revision"),
		"result_json": _json(result),
		"result": _json(result),
		"idempotency_key": idempotency_key,
		"correlation_id": correlation_id,
		"source_namespace": source_namespace,
		"actor": actor_value,
		"policy_version": POLICY_VERSION,
		"nonce": nonce,
		"correlation_token": correlation_id,
		"request_received_at": now,
		"completed_at": now,
	}
	if encrypted_payload:
		values["encrypted_request_payload"] = encrypted_payload
	if _doctype_exists(RECEIPT_DOCTYPE):
		doc = frappe.get_doc({"doctype": RECEIPT_DOCTYPE, **_supported_values(RECEIPT_DOCTYPE, values)})
		doc.insert(ignore_permissions=True)
		result = dict(result)
		result["receipt"] = doc.name
		# The durable receipt stores the final response too; no second update is
		# needed for fields that are not available in the current schema.
		for key in (key_set.get("command_key"), key_set.get("source_key"), key_set.get("nonce_key")):
			if key:
				_MEMORY_RECEIPTS[key] = {**values, "name": doc.name, "result_json": _json(result)}
		return result
	result = dict(result)
	result["receipt"] = key_set.get("command_key")
	for key in (key_set.get("command_key"), key_set.get("source_key"), key_set.get("nonce_key")):
		if key:
			_MEMORY_RECEIPTS[key] = {**values, "name": result["receipt"], "result_json": _json(result)}
	return result


def _receipt_replay(
	keys: list[dict[str, Any]], request_fp: str, *, source_namespace: str, idempotency_key: str
) -> dict[str, Any] | None:
	# A source record is globally idempotent for intake ingress, where retries
	# represent the same provider event.  Review decisions are commands against
	# one mutable review row: only the command key (or explicit nonce) identifies
	# a replay, so a fresh decision can receive the proper stale/CAS error.
	lookup_keys = keys
	if source_namespace == "review":
		lookup_keys = [
			{key: value for key, value in key_set.items() if key in {"version", "command_key", "nonce_key"}}
			for key_set in keys
		]
	receipt = _lookup_receipt(lookup_keys)
	if not receipt:
		return None
	previous_fp = receipt.get("request_fingerprint") or receipt.get("fingerprint")
	if previous_fp and previous_fp != request_fp:
		_fail("IDEMPOTENCY_KEY_REUSED", "The idempotency key was already used with another request.")
	# A source key is global to a provider record.  A retry with a fresh command
	# key therefore returns the first source result as well.
	return _receipt_response(receipt)


def _assert_replay_scope(result: dict[str, Any], authority: dict[str, Any]) -> None:
	"""Re-check current Student/review scope before returning a source replay."""
	student_name = _text(result.get("student"))
	if student_name:
		student = frappe.db.get_value(
			"CRM Lead", student_name, ["branch", "owning_team", "owner_staff"], as_dict=True
		)
		if not student:
			_fail("UNAUTHORIZED", "The replay target is no longer available in the current scope.")
		campuses = set(authority.get("campus_scope") or [])
		teams = set(authority.get("team_scope") or [])
		if authority.get("profile") not in {
			"platform_superuser",
			"admissions_director",
		} and not authority.get("scope_all"):
			if campuses and student.branch not in campuses:
				_fail("UNAUTHORIZED", "The replay target is outside the current Campus scope.")
			if authority.get("signed"):
				if not teams or student.owning_team not in teams:
					_fail("UNAUTHORIZED", "The signed source is not scoped to the replay target.")
			elif student.owning_team not in teams and student.owner_staff != authority.get("actor_staff"):
				_fail("UNAUTHORIZED", "The replay target is outside the current Team scope.")
	review_id = _text(result.get("review_id"))
	if review_id and _doctype_exists(REVIEW_DOCTYPE):
		try:
			review = frappe.get_doc(REVIEW_DOCTYPE, review_id)
		except Exception:
			_fail("UNAUTHORIZED", "The replay review is no longer available in the current scope.")
		campuses = set(authority.get("campus_scope") or [])
		teams = set(authority.get("team_scope") or [])
		if authority.get("profile") not in {
			"platform_superuser",
			"admissions_director",
		} and not authority.get("scope_all"):
			proposed_campus = _text(_safe_get(review, "proposed_campus", "campus"))
			anchor = _text(_safe_get(review, "scope_anchor"))
			if campuses and proposed_campus not in campuses:
				_fail("UNAUTHORIZED", "The replay review is outside the current Campus scope.")
			if not teams or (anchor and anchor not in teams):
				_fail("UNAUTHORIZED", "The replay review is outside the current Team scope.")


def _identifier_rows(identifier_type: str, digest: str) -> list[dict[str, Any]]:
	rows: list[dict[str, Any]] = []
	for doctype in IDENTIFIER_DOCTYPES:
		if not _doctype_exists(doctype):
			continue
		digest_field = _first_field(doctype, ("keyed_digest", "digest", "identifier_digest", "hmac_digest"))
		type_field = _first_field(doctype, ("identifier_type", "type", "kind"))
		if not digest_field:
			continue
		filters = {digest_field: digest}
		if type_field:
			filters[type_field] = identifier_type
		try:
			for row in frappe.get_all(doctype, filters=filters, fields=["*"]):
				row = dict(row)
				row["_doctype"] = doctype
				row["_identity"] = row.get("parent") or row.get("identity") or row.get("identity_root")
				row["_lifecycle"] = row.get("lifecycle") or row.get("status") or "active"
				rows.append(row)
		except Exception:
			continue
	# A few early data-contract migrations placed the strong digest on the root.
	if _doctype_exists(IDENTITY_DOCTYPE):
		for field in ("strong_digest", "national_id_digest", "id_digest"):
			if not _has_field(IDENTITY_DOCTYPE, field):
				continue
			try:
				for row in frappe.get_all(IDENTITY_DOCTYPE, filters={field: digest}, fields=["*"]):
					row = dict(row)
					row["_doctype"] = IDENTITY_DOCTYPE
					row["_identity"] = row.get("name")
					row["_lifecycle"] = row.get("lifecycle") or row.get("status") or "active"
					rows.append(row)
			except Exception:
				pass
	return rows


def _find_observation_roots(identifier_type: str, value: str) -> list[dict[str, Any]]:
	if not value:
		return []
	roots: list[dict[str, Any]] = []
	for version, secret in _secret_versions() or [(HMAC_VERSION, b"")]:
		domain = (
			f"crm.identity.strong.{version}"
			if identifier_type == "national_id"
			else f"crm.identity.weak.{version}"
		)
		digest = (
			keyed_digest(secret, domain, value)
			if identifier_type == "national_id"
			else keyed_digest(secret, domain, identifier_type, value)
		)
		for row in _identifier_rows(identifier_type, digest):
			if row.get("_identity"):
				roots.append(
					{
						"identity": row["_identity"],
						"lifecycle": row.get("_lifecycle", "active"),
						"digest": digest,
					}
				)
	# Compatibility with pre-keyed test fixtures and the migration's encrypted
	# lookup columns.  This path is multimap for weak values by design.
	if _doctype_exists(IDENTIFIER_DOCTYPES[0]):
		return roots
	return roots


def _resolve_phone_email_identity(
	weak_roots: set[str], strong_roots: set[str], *, retracted: bool
) -> tuple[str | None, str | None]:
	"""Resolve identity from phone/email roots only.

	The extra arguments remain for compatibility with older callers, but CCCD
	is deliberately ignored and cannot establish, confirm or block a match.
	"""
	if len(weak_roots) > 1:
		return None, "identity_conflict"
	if weak_roots:
		return next(iter(weak_roots)), None
	return None, None


def _case_key(identity: str, admission_year: str) -> dict[str, Any] | None:
	if not _doctype_exists(CASE_KEY_DOCTYPE):
		return None
	identity_field = _first_field(CASE_KEY_DOCTYPE, ("identity", "identity_root"))
	year_field = _first_field(CASE_KEY_DOCTYPE, ("admission_year", "admission_cycle"))
	if not identity_field or not year_field:
		return None
	try:
		rows = frappe.get_all(
			CASE_KEY_DOCTYPE, filters={identity_field: identity, year_field: admission_year}, fields=["*"]
		)
	except Exception:
		rows = []
	return dict(rows[0]) if rows else None


def _create_identity(candidate: dict[str, Any]):
	if not _doctype_exists(IDENTITY_DOCTYPE):
		_fail("CONFIGURATION_ERROR", "Student identity data contract is not installed.")
	strong = candidate.get("strong")
	secrets = _secret_versions() or [(HMAC_VERSION, b"")]
	secret_version, secret = secrets[0]
	# Identity names are opaque and do not expose normalized identifiers.
	identity_material = uuid.uuid4().hex
	identity_key = f"ID-{keyed_digest(secret, 'crm.identity.root.v1', identity_material)[:32]}"
	values = {
		"doctype": IDENTITY_DOCTYPE,
		"identity_key": identity_key,
		"identity_status": "active",
		"source_system": "student-intake",
		"strong_identifier_digest_version": secret_version.lstrip("v") or 1,
		"national_id_digest_version": secret_version.lstrip("v") or 1,
	}
	if strong:
		digest = keyed_digest(secret, f"crm.identity.strong.{secret_version}", "national_id", strong)
		values.update(
			{
				"strong_identifier_digest": digest,
				"national_id_digest": digest,
				"evidence_reference": f"student-intake:{digest[:24]}",
			}
		)
	doc = frappe.get_doc({"doctype": IDENTITY_DOCTYPE, **_supported_values(IDENTITY_DOCTYPE, values)})
	doc.insert(ignore_permissions=True)
	if strong:
		_add_identifier(doc, "national_id", strong, strong=True)
	return doc.name


def _add_identifier(identity_doc_or_name: Any, identifier_type: str, value: str, *, strong: bool = False):
	identity = identity_doc_or_name.name if hasattr(identity_doc_or_name, "name") else identity_doc_or_name
	secrets = _secret_versions() or [(HMAC_VERSION, b"")]
	for version, secret in secrets:
		domain = (
			f"crm.identity.strong.{version}"
			if identifier_type == "national_id"
			else f"crm.identity.weak.{version}"
		)
		digest = (
			keyed_digest(secret, domain, value)
			if identifier_type == "national_id"
			else keyed_digest(secret, domain, identifier_type, value)
		)
		for doctype in IDENTIFIER_DOCTYPES:
			if not _doctype_exists(doctype):
				continue
			values = {
				"doctype": doctype,
				"parent": identity,
				"parenttype": IDENTITY_DOCTYPE,
				"parentfield": "identifiers",
				"identity": identity,
				"identifier_type": identifier_type,
				"type": identifier_type,
				"keyed_digest": digest,
				"digest": digest,
				"digest_version": version,
				"key_version": version,
				"lifecycle": "active",
				"status": "active",
			}
			try:
				doc = frappe.get_doc({"doctype": doctype, **_supported_values(doctype, values)})
				doc.insert(ignore_permissions=True)
				return
			except Exception as exc:
				if _is_duplicate_error(exc):
					return
				continue


def _is_duplicate_error(exc: Exception) -> bool:
	message = str(exc).casefold()
	return any(token in message for token in ("duplicate", "unique", "already exists"))


def _add_weak_observations(identity: str, candidate: dict[str, Any]):
	for identifier_type, value in (("phone", candidate.get("phone")), ("email", candidate.get("email"))):
		if not value:
			continue
		# Never collapse a shared observation. The physical child uniqueness is
		# `(identity, type, digest)`, so `_add_identifier` can safely add a new
		# phone/email alias and ignore only an exact duplicate.
		_add_identifier(identity, identifier_type, value)


def _resolve_case_team(pool_or_team: str, campus: str) -> str:
	"""Return the active Sales Team projection for one canonical Student Pool."""
	return _resolve_case_pool(pool_or_team, campus).team


def _resolve_case_pool(pool_or_team: str, campus: str):
	"""Resolve exactly one active pool; Team names are compatibility input only."""
	pool_or_team = _text(pool_or_team)
	if not pool_or_team:
		_fail("NO_ELIGIBLE_POOL", "A named pool is required for a Student case.")
	pool = frappe.db.get_value(
		"CRM Student Pool",
		pool_or_team,
		["name", "team", "campus", "is_active"],
		as_dict=True,
	)
	if not pool:
		candidates = frappe.get_all(
			"CRM Student Pool",
			filters={"team": pool_or_team, "campus": campus, "is_active": 1},
			fields=["name", "team", "campus", "is_active"],
			limit_page_length=2,
		)
		if len(candidates) > 1:
			_fail("AMBIGUOUS_POOL", "The Team maps to multiple active Student Pools.")
		pool = candidates[0] if candidates else None
	if not pool or not pool.is_active or pool.campus != campus or not pool.team:
		_fail("NO_ELIGIBLE_POOL", "The review pool is not active at the Student Campus.")
	team = frappe.db.get_value(
		"CRM Team", pool.team, ["name", "campus", "team_type", "is_active"], as_dict=True
	)
	if not team or not team.is_active or team.team_type != "Sales" or team.campus != campus:
		_fail("NO_ELIGIBLE_POOL", "The Student case Team must be an active Sales Team at the Campus.")
	return pool


def _create_case(
	identity: str,
	candidate: dict[str, Any],
	payload: dict[str, Any],
	campus: str,
	pool: str,
	*,
	correlation_id: str | None = None,
) -> str:
	admission_year = _text(
		payload.get("admission_year") or payload.get("admission_cycle") or payload.get("year")
	)
	if not admission_year:
		_fail("REVIEW_REQUIRED", "Admission cycle is required before a Student case can be created.")
	pool = _resolve_case_pool(pool, campus)
	values = {
		"doctype": "CRM Lead",
		"student_name": candidate.get("name") or "Unnamed Student",
		"phone": candidate.get("phone"),
		"email": candidate.get("email"),
		"id_number": candidate.get("strong"),
		"admission_year": admission_year,
		"branch": campus,
		"owning_team": pool.team,
		"owning_pool": pool.name,
		"identity": identity,
		"intake_integrity_state": "resolved",
		"ownership_revision": 0,
		"enrollment_status": payload.get("enrollment_status") or "NEW",
		"source": payload.get("source"),
		"advertising_channel": payload.get("advertising_channel"),
		"current_grade": payload.get("current_grade"),
		"study_stage": payload.get("study_stage"),
		"province": payload.get("province"),
		"high_school": payload.get("high_school"),
		"major": payload.get("major"),
	}
	values.update(
		{
			key: value
			for key, value in payload.items()
			if key
			in {
				"gender",
				"date_of_birth",
				"high_school",
				"province",
				"ward",
				"major",
				"aspiration",
				"current_grade",
				"study_stage",
				"alt_name",
				"alt_phone",
			}
		}
	)

	@contextmanager
	def service_context():
		flags = getattr(frappe, "flags", None)
		previous = None
		if flags is not None:
			previous = getattr(flags, "student_intake_service", None)
			flags.student_intake_service = True
		try:
			yield
		finally:
			if flags is not None:
				flags.student_intake_service = previous

	with service_context():
		student = frappe.get_doc({"doctype": "CRM Lead", **_supported_values("CRM Lead", values)})
		student.insert(ignore_permissions=True)
	initial_owner = _text(payload.get("assigned_to"))
	if initial_owner:
		_assign_initial_manual_owner(
			student.name,
			initial_owner,
			pool.team,
			correlation_id,
			_text(payload.get("_intake_actor_user")),
		)
	from crm.fcrm.student_feature_flags import (
		automatic_assignment_on_create_enabled,
		enabled,
	)
	from crm.fcrm.student_routing import enqueue_student_routing, route_pool_owned_student

	# A Sale's manual intake is now staff-owned through the canonical ownership
	# command. Only pool-owned cases are eligible for the routing worker.
	if not initial_owner and automatic_assignment_on_create_enabled():
		if enabled("synchronous_routing"):
			route_pool_owned_student(student.name, trigger="pool_entry")
		elif _doctype_exists("CRM Student Routing Request"):
			enqueue_student_routing(student.name, trigger="pool_entry")
	if not _doctype_exists(CASE_KEY_DOCTYPE):
		_fail("CONFIGURATION_ERROR", "Student Case Key data contract is not installed.")
	from crm.fcrm.admission_case_key import ensure_case_key

	ensure_case_key(
		identity=identity,
		admission_year=admission_year,
		canonical_student=student.name,
		source_reference=correlation_id,
		correlation_token=correlation_id,
	)
	return student.name


def _assign_initial_manual_owner(
	student_name: str,
	staff_name: str,
	team_name: str,
	correlation_id: str | None,
	actor_user: str | None = None,
) -> dict[str, Any]:
	"""Create the first direct owner through the canonical ownership transaction.

	Inserting ``assigned_to`` directly skips the immutable ownership event, SLA
	opening and notification outbox. The new case is therefore inserted pool-owned
	at revision 0, then atomically moved to the authenticated Sale at revision 1.
	The enclosing intake command can roll both writes back together.
	"""
	from crm.fcrm.student_ownership import change_student_ownership

	return change_student_ownership(
		student_name,
		"owner",
		staff_name,
		team_name,
		"Manual intake self-assignment",
		f"intake-initial-owner:{student_name}",
		expected_revision=0,
		correlation_id=correlation_id or f"intake:{student_name}",
		_internal_service=True,
		_internal_actor=actor_user,
		_commit=False,
	)


def _create_review(
	candidate: dict[str, Any],
	payload: dict[str, Any],
	reason: str,
	*,
	source_receipt: str | None,
	pool: str | None = None,
	candidate_identity: str | None = None,
):
	review_type = {
		"weak_only": "identity_conflict",
		"retracted_identifier": "identity_conflict",
		"quarantined_case_key": "duplicate_case",
		"identity_conflict": "identity_conflict",
		"missing_admission_cycle": "missing_admission_cycle",
	}.get(reason, "malformed_identifier")
	pool_name = pool
	try:
		pool_name = (
			frappe.db.get_value(
				"CRM Student Pool",
				{
					"team": pool,
					"campus": _text(payload.get("campus") or payload.get("branch")),
					"is_active": 1,
				},
				"name",
			)
			or pool
		)
	except Exception:
		pass
	values = {
		"doctype": REVIEW_DOCTYPE,
		"review_key": f"RV-{uuid.uuid4().hex}",
		"review_status": REVIEW_OPEN,
		"revision": 0,
		"review_type": review_type,
		"source_receipt": source_receipt,
		"proposed_student_name": candidate.get("name"),
		"proposed_identity": candidate_identity,
		"proposed_campus": _text(payload.get("campus") or payload.get("branch")),
		"proposed_owning_team": pool_name,
		"proposed_admission_year": _normalize_admission_year(payload),
		"scope_anchor": pool,
		"evidence_reference": keyed_digest(
			(_secret_versions() or [(HMAC_VERSION, b"")])[0][1],
			"crm.review.proposed.v1",
			candidate.get("strong") or candidate.get("phone") or candidate.get("email") or "",
		),
		"reason_sensitivity": "operational",
	}
	if not _doctype_exists(REVIEW_DOCTYPE):
		_fail("CONFIGURATION_ERROR", "Student intake review data contract is not installed.")
	doc = frappe.get_doc({"doctype": REVIEW_DOCTYPE, **_supported_values(REVIEW_DOCTYPE, values)})
	doc.insert(ignore_permissions=True)
	return doc.name


def _link_review_receipt(review_id: str, receipt: str | None):
	if not review_id or not receipt or not _doctype_exists(REVIEW_DOCTYPE):
		return
	try:
		doc = frappe.get_doc(REVIEW_DOCTYPE, review_id)
		_set_supported(doc, {"source_receipt": receipt, "source_command_receipt": receipt})
		doc.save(ignore_permissions=True)
	except Exception:
		# Receipt/review linkage is best-effort only for legacy transitional
		# schemas; the immutable receipt still carries the review ID.
		return


def _normalize_admission_year(payload: dict[str, Any]) -> str | None:
	value = _text(payload.get("admission_year") or payload.get("admission_cycle") or payload.get("year"))
	if not value or not _doctype_exists("CRM Admission Year"):
		return value
	if frappe.db.exists("CRM Admission Year", value):
		return value
	# Integrations commonly send the display year while the Link name may be a
	# generated key.  Resolve by the canonical year field without accepting
	# arbitrary free text as a Student Link.
	try:
		return frappe.db.get_value("CRM Admission Year", {"year_name": value}, "name") or value
	except Exception:
		return value


def _normalize_consent(value: Any) -> dict[str, Any] | None:
	if value is None:
		return None
	if not isinstance(value, dict):
		_fail("INVALID_INPUT", "consent must be a JSON object.")
	granted = value.get("granted")
	if not isinstance(granted, bool):
		_fail("INVALID_INPUT", "consent.granted must be boolean.")
	if not granted:
		return {"granted": False}
	granted_at = _text(value.get("granted_at"))
	if not granted_at:
		_fail("INVALID_INPUT", "consent.granted_at is required when consent is granted.")
	try:
		parsed_granted_at = frappe.utils.get_datetime(granted_at)
	except (TypeError, ValueError):
		_fail("INVALID_INPUT", "consent.granted_at must be a valid datetime.")
	if not parsed_granted_at:
		_fail("INVALID_INPUT", "consent.granted_at must be a valid datetime.")
	granted_at = str(parsed_granted_at)
	for fieldname in ("purpose", "scope", "source"):
		field_value = _text(value.get(fieldname))
		if field_value and len(field_value) > 140:
			_fail("INVALID_INPUT", f"consent.{fieldname} exceeds its size limit.")
	return {
		"granted": True,
		"granted_at": granted_at,
		"purpose": _text(value.get("purpose")) or "student_intake",
		"scope": _text(value.get("scope")) or "admissions_processing",
		"source": _text(value.get("source")),
	}


def _persist_consent_grant(
	student: str | None,
	consent: dict[str, Any] | None,
	*,
	receipt: str | None,
	source_namespace: str,
):
	if not student or not consent or not consent.get("granted"):
		return None
	if not _doctype_exists("CRM Contact Consent Event"):
		_fail("CONFIGURATION_ERROR", "Consent event data contract is not installed.")
	values = {
		"doctype": "CRM Contact Consent Event",
		"student": student,
		"event_type": "Granted",
		"occurred_at": consent["granted_at"],
		"granted_at": consent["granted_at"],
		"purpose": consent.get("purpose") or "student_intake",
		"scope": consent.get("scope") or "admissions_processing",
		"source": consent.get("source") or source_namespace,
		"command_receipt": receipt,
	}
	doc = frappe.get_doc({key: value for key, value in values.items() if value is not None})
	consent_event_name = None
	try:
		doc.insert(ignore_permissions=True)
	except (frappe.UniqueValidationError, frappe.DuplicateEntryError):
		if receipt and _has_field("CRM Contact Consent Event", "command_receipt"):
			consent_event_name = frappe.db.get_value(
				"CRM Contact Consent Event", {"command_receipt": receipt}, "name"
			)
		else:
			raise
	return consent_event_name or doc.name


def _persist_intake_result(
	result: dict[str, Any],
	*,
	keys: list[dict[str, Any]],
	fingerprint: str,
	principal: str,
	source_namespace: str,
	source_record_id: str,
	idempotency_key: str,
	correlation_id: str,
	nonce: str | None,
	provenance_payload: dict[str, Any],
	consent: dict[str, Any] | None,
) -> dict[str, Any]:
	persisted = _persist_receipt(
		keys,
		request_fp=fingerprint,
		result=result,
		principal=principal,
		source_namespace=source_namespace,
		_source_record_id=source_record_id,
		idempotency_key=idempotency_key,
		correlation_id=correlation_id,
		nonce=nonce,
		provenance_payload=provenance_payload,
	)
	_persist_consent_grant(
		persisted.get("student"),
		consent,
		receipt=persisted.get("receipt"),
		source_namespace=source_namespace,
	)
	return persisted


def submit_intake(
	payload: dict[str, Any] | str | None = None,
	*,
	source_namespace: str | None = None,
	source_record_id: str | None = None,
	idempotency_key: str | None = None,
	correlation_id: str | None = None,
	expected_review_id: str | None = None,
	nonce: str | None = None,
	signed_context: dict[str, Any] | None = None,
	request_payload: dict[str, Any] | str | None = None,
	request_fingerprint: str | None = None,
) -> dict[str, Any]:
	"""Submit one deterministic Student intake command.

	The function returns exactly one of ``created``, ``attached`` or
	``review_required``.  Replays return the original response, including its
	receipt, and never update a Student.
	"""
	payload = _parse_payload(payload)
	original_payload = _parse_payload(request_payload) if request_payload is not None else payload
	consent = _normalize_consent(payload.get("consent"))
	source_namespace = _text(source_namespace) or _text(payload.get("source_namespace"))
	source_record_id = _text(source_record_id) or _text(payload.get("source_record_id"))
	idempotency_key = _text(idempotency_key) or _text(payload.get("idempotency_key"))
	correlation_id = _text(correlation_id) or _text(payload.get("correlation_id")) or uuid.uuid4().hex
	if not source_namespace or not source_record_id or not idempotency_key:
		_fail("INVALID_INPUT", "source_namespace, source_record_id and idempotency_key are required.")
	authority = _resolve_authority(SUBMIT_CAPABILITY, signed_context=signed_context)
	candidate = _identity_candidate(payload)
	if not candidate["phone"] and not candidate["email"]:
		_fail("INVALID_INPUT", "At least one valid phone or email is required.")
	admission_year = _normalize_admission_year(payload)
	if not admission_year:
		# Missing cycle is ambiguous work and is therefore reviewable, but it must
		# still have a durable source receipt before a review is opened.
		pass
	if _is_first_party_manual_intake(authority):
		campus, pool, assigned_to = _resolve_manual_initial_ownership(authority)
		# Explicit assignment/pool fields are client input, never authority.  The
		# server-owned value is only used inside this command after validation.
		payload = {
			**payload,
			"campus": campus,
			"branch": campus,
			"owning_team": pool,
			"_intake_actor_user": authority.get("actor_user"),
		}
		if assigned_to:
			payload["assigned_to"] = assigned_to
		else:
			payload.pop("assigned_to", None)
	else:
		campus, pool = _assert_campus_and_pool(payload, authority)
	principal = authority.get("actor_user") or source_namespace
	keys = receipt_keys(source_namespace, source_record_id, idempotency_key, principal, nonce)
	fingerprint_payload = {
		"payload": original_payload,
		"source_namespace": source_namespace,
		"source_record_id": source_record_id,
		"expected_review_id": expected_review_id,
	}
	fingerprint = request_fingerprint or body_fingerprint(fingerprint_payload)
	provenance_payload = {**original_payload, **payload}
	replay = _receipt_replay(
		keys, fingerprint, source_namespace=source_namespace, idempotency_key=idempotency_key
	)
	if replay:
		_assert_replay_scope(replay, authority)
		return replay
	if not admission_year:
		result = {"outcome": "review_required", "error_code": "REVIEW_REQUIRED"}
		review_id = _create_review(
			candidate,
			{**payload, "campus": campus},
			"missing_admission_cycle",
			source_receipt=None,
			pool=pool,
		)
		result["review_id"] = review_id
		persisted = _persist_intake_result(
			result,
			keys=keys,
			fingerprint=fingerprint,
			principal=principal,
			source_namespace=source_namespace,
			source_record_id=source_record_id,
			idempotency_key=idempotency_key,
			correlation_id=correlation_id,
			nonce=nonce,
			provenance_payload=provenance_payload,
			consent=consent,
		)
		_link_review_receipt(review_id, persisted.get("receipt"))
		return persisted

	weak_rows = []
	for identifier_type, value in (("phone", candidate.get("phone")), ("email", candidate.get("email"))):
		for row in _find_observation_roots(identifier_type, value):
			row["identifier_type"] = identifier_type
			weak_rows.append(row)
	# Phone/email are the only identifiers that establish an identity root. A
	# national ID is retained only as optional Student data and is never looked up.
	weak_roots = {row["identity"] for row in weak_rows if row.get("identity")}
	identity, reason = _resolve_phone_email_identity(weak_roots, set(), retracted=False)
	if not identity and not reason:
		identity = _create_identity(candidate)
	if identity and not reason:
		key = _case_key(identity, admission_year)
		if key:
			_add_weak_observations(identity, candidate)
			student_name = key.get("canonical_student") or key.get("student")
			if student_name:
				result = {"outcome": "attached", "student": student_name}
				return _persist_intake_result(
					result,
					keys=keys,
					fingerprint=fingerprint,
					principal=principal,
					source_namespace=source_namespace,
					source_record_id=source_record_id,
					idempotency_key=idempotency_key,
					correlation_id=correlation_id,
					nonce=nonce,
					provenance_payload=provenance_payload,
					consent=consent,
				)
			reason = "quarantined_case_key"
	if reason:
		result = {"outcome": "review_required", "error_code": "REVIEW_REQUIRED"}
		candidate_identity = None
		if len(weak_roots) == 1:
			candidate_identity = next(iter(weak_roots))
		review_id = _create_review(
			candidate,
			{**payload, "campus": campus},
			reason,
			source_receipt=None,
			pool=pool,
			candidate_identity=candidate_identity,
		)
		result["review_id"] = review_id
		result["candidates"] = (
			[{"identity_id": candidate_identity, "masked_label": "Candidate identity"}]
			if candidate_identity
			else []
		)
		persisted = _persist_intake_result(
			result,
			keys=keys,
			fingerprint=fingerprint,
			principal=principal,
			source_namespace=source_namespace,
			source_record_id=source_record_id,
			idempotency_key=idempotency_key,
			correlation_id=correlation_id,
			nonce=nonce,
			provenance_payload=provenance_payload,
			consent=consent,
		)
		_link_review_receipt(review_id, persisted.get("receipt"))
		return persisted
	_add_weak_observations(identity, candidate)
	student_name = _create_case(
		identity,
		candidate,
		{**payload, "admission_year": admission_year},
		campus,
		pool,
		correlation_id=correlation_id,
	)
	result = {"outcome": "created", "student": student_name}
	return _persist_intake_result(
		result,
		keys=keys,
		fingerprint=fingerprint,
		principal=principal,
		source_namespace=source_namespace,
		source_record_id=source_record_id,
		idempotency_key=idempotency_key,
		correlation_id=correlation_id,
		nonce=nonce,
		provenance_payload=provenance_payload,
		consent=consent,
	)


def _review_doc(review_id: str):
	if not _doctype_exists(REVIEW_DOCTYPE):
		_fail("INVALID_INPUT", "The requested review does not exist.")
	try:
		frappe.db.sql(
			"select name from `tabCRM Student Intake Review` where name = %s for update", (review_id,)
		)
		return frappe.get_doc(REVIEW_DOCTYPE, review_id)
	except Exception:
		_fail("INVALID_INPUT", "The requested review does not exist.")


def _review_scope(doc, authority: dict[str, Any]):
	# ``proposed_owning_team`` is a pool Link, while authority team_scope holds
	# Sales Team names.  The explicit scope anchor is the durable authorization
	# boundary; only resolve the pool as a compatibility fallback for old rows.
	anchor = _safe_get(doc, "scope_anchor")
	if not anchor:
		pool_name = _safe_get(doc, "proposed_owning_team")
		try:
			anchor = frappe.db.get_value("CRM Student Pool", pool_name, "team") or pool_name
		except Exception:
			anchor = pool_name
	if authority.get("profile") == "signed_ingress":
		campuses = set(authority.get("campus_scope") or [])
		teams = set(authority.get("team_scope") or [])
		proposed_campus = _text(_safe_get(doc, "proposed_campus", "campus"))
		if not campuses or proposed_campus not in campuses or (not teams or (anchor and anchor not in teams)):
			return False
	if anchor and authority.get("profile") not in {
		"platform_superuser",
		"admissions_director",
		"signed_ingress",
	}:
		if anchor not in set(authority.get("team_scope") or []):
			return False
	student = _safe_get(doc, "candidate_student", "resulting_student", "canonical_student")
	if not student:
		return True
	try:
		student_doc = frappe.get_doc("CRM Lead", student)
	except Exception:
		return False
	if authority.get("profile") in {"platform_superuser", "admissions_director", "signed_ingress"}:
		return True
	return bool(
		(_safe_get(student_doc, "owning_team") in set(authority.get("team_scope") or []))
		or (_safe_get(student_doc, "owner_staff") == authority.get("actor_staff"))
	)


def _validate_review_identity(doc, identity_id: str | None) -> str:
	"""Accept only the durable, active candidate attached to this review."""
	identity = _text(identity_id) or _text(
		_safe_get(doc, "proposed_identity", "candidate_identity", "identity")
	)
	proposed = _text(_safe_get(doc, "proposed_identity", "candidate_identity", "identity"))
	if not identity or not proposed or identity != proposed:
		_fail("INVALID_INPUT", "The selected identity is not an allowed review candidate.")
	if not _doctype_exists(IDENTITY_DOCTYPE) or not frappe.db.exists(IDENTITY_DOCTYPE, identity):
		_fail("INVALID_INPUT", "The selected identity does not exist.")
	try:
		identity_doc = frappe.get_doc(IDENTITY_DOCTYPE, identity)
	except Exception:
		_fail("INVALID_INPUT", "The selected identity does not exist.")
	status = str(
		_safe_get(identity_doc, "identity_status", "status", "lifecycle", default="active")
	).casefold()
	if status not in {"active", "verified"}:
		_fail("INVALID_INPUT", "The selected identity is not active.")
	return identity


def decide_intake_review(
	review_id: str,
	decision: str,
	evidence_refs: list[str] | str | None = None,
	reason: str | None = None,
	idempotency_key: str | None = None,
	correlation_id: str | None = None,
	expected_revision: int | str | None = None,
	*,
	signed_context: dict[str, Any] | None = None,
	identity_data: dict[str, Any] | None = None,
	identity_id: str | None = None,
) -> dict[str, Any]:
	authority = _resolve_authority(REVIEW_CAPABILITY, signed_context=signed_context)
	decision = {"attach_existing": "attach_identity", "approve_new": "approve_new_identity"}.get(
		decision, decision
	)
	if decision not in {"attach_identity", "approve_new_identity", "reject"}:
		_fail("INVALID_INPUT", "Unsupported intake review decision.")
	if not _text(reason):
		_fail("INVALID_INPUT", "A reason is required for an intake review decision.")
	if not idempotency_key:
		_fail("INVALID_INPUT", "idempotency_key is required.")
	doc = _review_doc(review_id)
	if not _review_scope(doc, authority):
		_fail("UNAUTHORIZED", "The review is outside the current Student scope.")
	current_revision = int(_safe_get(doc, "revision", "review_revision", default=0) or 0)
	try:
		submitted_revision = None if expected_revision in (None, "") else int(expected_revision)
	except (TypeError, ValueError):
		_fail("INVALID_INPUT", "expected_revision must be an integer.")
	evidence = evidence_refs
	if isinstance(evidence, str):
		try:
			evidence = json.loads(evidence)
		except ValueError:
			evidence = [evidence]
	evidence = [str(value) for value in (evidence or []) if str(value).strip()]
	if not evidence:
		_fail("INVALID_INPUT", "At least one evidence reference is required.")
	# Decision commands have their own receipt key.  A review cannot be applied
	# twice even if its source command is replayed.
	principal = authority.get("actor_user") or "reviewer"
	try:
		if not frappe.db.exists("User", principal):
			principal = "Administrator"
	except Exception:
		pass
	# Review decisions are one-shot commands, but a review may receive multiple
	# distinct decision attempts. Only the command key is idempotent here; the
	# intake source key must not turn a later stale-revision check into a reused
	# source-record error.
	keys = [
		{"version": key_set.get("version"), "command_key": key_set.get("command_key")}
		for key_set in receipt_keys("review", str(review_id), str(idempotency_key), principal)
	]
	fingerprint = body_fingerprint(
		{
			"review": review_id,
			"decision": decision,
			"evidence": evidence,
			"reason": reason,
			"revision": submitted_revision,
		}
	)
	replay = _receipt_replay(
		keys, fingerprint, source_namespace="review", idempotency_key=str(idempotency_key)
	)
	if replay:
		return replay
	if submitted_revision is not None and submitted_revision != current_revision:
		_fail("STALE_REVISION", "The review revision is stale.")
	status = str(_safe_get(doc, "review_status", "status", "state", default=REVIEW_OPEN)).casefold()
	if status != REVIEW_OPEN:
		_fail("REVIEW_ALREADY_APPLIED", "This intake review has already been decided.")
	result: dict[str, Any] = {"outcome": "review_applied", "review_id": review_id, "decision": decision}
	if decision == "attach_identity":
		identity = _validate_review_identity(doc, identity_id)
		admission_year = _text(_safe_get(doc, "proposed_admission_year", "admission_year"))
		campus = _text(_safe_get(doc, "proposed_campus", "campus"))
		pool = _text(_safe_get(doc, "proposed_owning_team", "proposed_pool", "owning_team", "pool"))
		if not admission_year or not campus or not pool:
			_fail("INVALID_INPUT", "The review is missing its cycle, Campus, or pool.")
		if _case_key(identity, admission_year):
			result["outcome"] = "attached"
			result["student"] = _case_key(identity, admission_year).get("canonical_student")
		else:
			student_name = _text(_safe_get(doc, "proposed_student_name", "proposed_name", "student_name"))
			if not student_name:
				_fail("INVALID_INPUT", "The review is missing a verified Student name.")
			candidate = {"name": student_name}
			result["student"] = _create_case(
				identity, candidate, {"admission_year": admission_year}, campus, pool
			)
	elif decision == "approve_new_identity":
		identity_data = identity_data or {}
		candidate = _identity_candidate(identity_data)
		if not candidate.get("name") or not (candidate.get("phone") or candidate.get("email")):
			_fail("INVALID_INPUT", "approve_new_identity requires a verified name and phone or email.")
		admission_year = _text(_safe_get(doc, "proposed_admission_year", "admission_year"))
		campus = _text(_safe_get(doc, "proposed_campus", "campus"))
		pool = _text(_safe_get(doc, "proposed_owning_team", "proposed_pool", "owning_team", "pool"))
		if not admission_year or not campus or not pool:
			_fail("INVALID_INPUT", "The review is missing its cycle, Campus, or pool.")
		identity = _create_identity(candidate)
		_add_weak_observations(identity, candidate)
		result["student"] = _create_case(
			identity, candidate, {"admission_year": admission_year}, campus, pool
		)
	# ``reject`` intentionally creates no Student or Identity.
	new_revision = current_revision + 1
	result["revision"] = new_revision
	_set_supported(
		doc,
		{
			"review_status": decision if decision != "reject" else "reject",
			"revision": new_revision,
			"decision_actor": principal,
			"decision_reason": reason,
			"evidence_reference": "; ".join(evidence),
			"decision_at": now_datetime(),
			"correlation_token": correlation_id or uuid.uuid4().hex,
			"resulting_student": result.get("student"),
		},
	)
	doc.save(ignore_permissions=True)
	return _persist_receipt(
		keys,
		request_fp=fingerprint,
		result=result,
		principal=principal,
		source_namespace="review",
		_source_record_id=str(review_id),
		idempotency_key=str(idempotency_key),
		correlation_id=correlation_id or uuid.uuid4().hex,
		kind="review",
	)
