"""Server-only delegated credentials for the crm-agents Copilot boundary.

The browser authenticates to Frappe with its normal session cookie.  This
module is deliberately not whitelisted: the later Copilot BFF calls it on the
server and is the only component allowed to receive the generated OAuth bearer
and signed proof.
"""
from __future__ import annotations

import base64
from collections import Counter
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import frappe
import requests
from frappe.utils import now_datetime
from werkzeug.wrappers import Response

_AUDIENCE = "crm-agents"
_CLIENT_NAME = "CRM Agents BFF"
_TOKEN_TTL_SECONDS = 120
_AGENT_TIMEOUT = (5, 190)


def _utc_epoch_seconds() -> int:

	"""Return JWT timestamps in UTC, independent of Frappe's site timezone.

	``frappe.utils.now_datetime()`` is intentionally a timezone-naive local
	datetime. Calling ``.timestamp()`` on it makes Python reinterpret that
	local value using the host timezone, which invalidates proof lifetimes when
	the Frappe site timezone and container timezone differ.
	"""
	return int(datetime.now(timezone.utc).timestamp())


def _b64url(value: bytes) -> str:

	return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _token_digest(token: str) -> str:

	return _b64url(hashlib.sha256(token.encode()).digest())


def _keyring() -> tuple[str, dict[str, str]]:

	keys = frappe.conf.get("crm_agents_delegation_keys")
	active_kid = frappe.conf.get("crm_agents_delegation_active_kid")
	if not isinstance(keys, dict) or not isinstance(active_kid, str):
		frappe.throw("crm-agents delegation signing keys are not configured", frappe.PermissionError)
	if not isinstance(keys.get(active_kid), str) or not keys[active_kid]:
		frappe.throw("crm-agents active delegation key is not configured", frappe.PermissionError)
	return active_kid, keys


def _ensure_client() -> str:

	client = frappe.db.exists("OAuth Client", {"app_name": _CLIENT_NAME})
	if client:
		return client
	return frappe.get_doc(
		{
			"doctype": "OAuth Client",
			"app_name": _CLIENT_NAME,
			"scopes": "all",
			"default_redirect_uri": "http://localhost/crm-agents-server-only",
			"redirect_uris": "http://localhost/crm-agents-server-only",
			"grant_type": "Authorization Code",
			"response_type": "Code",
			"skip_authorization": 1,
		}
	).insert(ignore_permissions=True).name


def _mint_bearer(*, user: str, client: str) -> str:

	access_token = frappe.generate_hash(length=48)
	frappe.get_doc(
		{
			"doctype": "OAuth Bearer Token",
			"client": client,
			"user": user,
			"scopes": "all",
			"access_token": access_token,
			"expires_in": _TOKEN_TTL_SECONDS,
			"expiration_time": now_datetime() + timedelta(seconds=_TOKEN_TTL_SECONDS),
			"status": "Active",
		}
	).insert(ignore_permissions=True)
	return access_token


def _active_session_exists(session_id: str, user: str) -> bool:
	"""Check Frappe's internal Sessions table (not a DocType)."""
	return bool(
		frappe.db.sql(
			"""SELECT sid FROM `tabSessions`
			WHERE sid = %s AND user = %s AND status = 'Active'
			LIMIT 1""",
			(session_id, user),
		)
	)


def _sign(payload: dict, *, kid: str, secret: str) -> str:

	header = _b64url(json.dumps({"alg": "HS256", "kid": kid, "typ": "JWT"}, separators=(",", ":")).encode())
	body = _b64url(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
	signature = _b64url(hmac.new(secret.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest())
	return f"{header}.{body}.{signature}"


def mint_delegated_credential() -> dict[str, str]:
	"""Return a one-use proof plus a short OAuth bearer for the current session.

	This function is intentionally callable only from Python server code.  Do
	not decorate it with ``frappe.whitelist`` and do not return its output to a
	browser response.
	"""
	if frappe.session.user in ("", "Guest") or not frappe.session.sid:
		frappe.throw("Authentication is required.", frappe.PermissionError)
	if not _active_session_exists(frappe.session.sid, frappe.session.user):
		frappe.throw("The current session is no longer active.", frappe.PermissionError)
	kid, keys = _keyring()
	bearer = _mint_bearer(user=frappe.session.user, client=_ensure_client())
	# The agent verifies this OAuth row in a separate HTTP transaction. Commit
	# the credential before opening that server-to-server request.
	frappe.db.commit()
	now = _utc_epoch_seconds()
	proof = _sign(
		{
			"aud": _AUDIENCE,
			"bth": _token_digest(bearer),
			"exp": now + _TOKEN_TTL_SECONDS,
			"iat": now,
			"iss": frappe.conf.get("crm_agents_delegation_issuer", frappe.utils.get_url()),
			"jti": frappe.generate_hash(length=32),
			"sid": frappe.session.sid,
			"sub": frappe.session.user,
		},
		kid=kid,
		secret=keys[kid],
	)
	return {"bearer": bearer, "proof": proof}


@frappe.whitelist()
def validate_delegated_session(session_id: str):
	"""Let crm-agents recheck that a proof-bound Frappe session remains live."""
	if not isinstance(session_id, str) or not session_id:
		frappe.throw("A session ID is required.", frappe.PermissionError)
	if frappe.session.user in ("", "Guest") or not _active_session_exists(
		session_id, frappe.session.user
	):
		frappe.throw("Delegated session is no longer active.", frappe.PermissionError)
	return {"user": frappe.session.user}


def _require_copilot_user() -> None:
	"""Require a current canonical CRM business profile for the BFF."""
	if frappe.session.user in ("", "Guest") or not frappe.session.sid:
		frappe.throw("Authentication is required.", frappe.PermissionError)
	from crm.api.session import get_session_role_flags

	get_session_role_flags()
	if not _is_copilot_authorized(frappe.get_roles()):
		frappe.throw("A canonical CRM business role is required.", frappe.PermissionError)


def _is_copilot_authorized(roles) -> bool:
	"""Keep BFF eligibility aligned with the session role contract."""
	from crm.api.session import resolve_copilot_profile

	return bool(resolve_copilot_profile(roles))


def _agent_config() -> tuple[str, str]:
	base_url = frappe.conf.get("crm_agents_url")
	api_key = frappe.conf.get("crm_agents_api_key")
	if not isinstance(base_url, str) or not base_url.strip() or not isinstance(api_key, str) or not api_key:
		frappe.throw("crm-agents BFF is not configured.", frappe.ValidationError)
	return base_url.rstrip("/"), api_key


def _delegated_headers() -> dict[str, str]:
	credential = mint_delegated_credential()
	return {
		"X-API-Key": _agent_config()[1],
		"Authorization": f"Bearer {credential['bearer']}",
		"X-Frappe-Delegation": credential["proof"],
		"Accept": "text/event-stream",
	}


def _request_payload(payload):
	if payload is None:
		payload = frappe.request.get_json(silent=True)
	if isinstance(payload, str):
		try:
			payload = json.loads(payload)
		except json.JSONDecodeError:
			payload = None
	if not isinstance(payload, dict) or not isinstance(payload.get("messages"), list):
		frappe.throw("A valid Copilot message payload is required.", frappe.ValidationError)
	payload = {key: value for key, value in payload.items() if key != "fixture_run_id"}
	fixture_run_id = frappe.conf.get("crm_e2e_fixture_run_id")
	if frappe.conf.get("e2e_live_test_enabled") and isinstance(fixture_run_id, str) and fixture_run_id:
		payload["fixture_run_id"] = fixture_run_id
	return payload


def _safe_error_response(status: int, message: str) -> Response:
	return Response(
		json.dumps({"message": message}),
		status=status,
		content_type="application/json",
		headers={"Cache-Control": "no-store"},
	)


def _agent_json(path: str, *, params: dict | None = None) -> Response:
	_require_copilot_user()
	base_url, _api_key = _agent_config()
	try:
		credential = mint_delegated_credential()
		response = requests.get(
			f"{base_url}{path}",
			params=params,
			headers={
				"X-API-Key": _api_key,
				"Authorization": f"Bearer {credential['bearer']}",
				"X-Frappe-Delegation": credential["proof"],
				"Accept": "application/json",
			},
			timeout=_AGENT_TIMEOUT,
		)
		if response.status_code >= 400:
			return _safe_error_response(response.status_code, "Copilot history is unavailable.")
		data = response.json()
	except (requests.RequestException, ValueError, TypeError):
		return _safe_error_response(503, "Copilot history is temporarily unavailable.")
	return Response(
		json.dumps({"message": data}, default=str),
		content_type="application/json",
		headers={"Cache-Control": "no-store"},
	)


def _relay_upstream(upstream):
	"""Relay SSE bytes promptly and make an unexpected EOF observable."""
	terminal_type = None
	event_counts = Counter()
	try:
		for raw_line in upstream.iter_lines(chunk_size=1, decode_unicode=True):
			if raw_line is None:
				continue
			line = (
				raw_line.decode("utf-8", errors="replace")
				if isinstance(raw_line, bytes)
				else raw_line
			)
			if line.startswith("data:"):
				try:
					event_type = json.loads(line[5:].strip()).get("type")
				except (ValueError, TypeError, AttributeError):
					event_type = None
				if isinstance(event_type, str):
					event_counts[event_type] += 1
					if event_type in {"start", "data-envelope", "finish", "error"}:
						frappe.logger("copilot").info("Copilot SSE relay received event=%s", event_type)
				if event_type in {"finish", "error", "data-approval-required"}:
					if terminal_type is not None:
						break
					terminal_type = event_type
			yield f"{line}\n".encode()
		yield b"\n"
		if terminal_type is None:
			yield b'data: {"type":"error","error":"upstream_stream_incomplete"}\n\n'
	except requests.RequestException:
		if terminal_type is None:
			yield b'data: {"type":"error","error":"upstream_stream_unavailable"}\n\n'
	finally:
		# Event names/counts are safe operational metadata; response content,
		# bearer tokens, proofs, and session identifiers never enter this log.
		frappe.logger("copilot").info(
			"Copilot SSE relay terminal=%s events=%s",
			terminal_type or "incomplete",
			dict(event_counts),
		)
		# WSGI servers close a returned generator when the browser aborts;
		# closing requests' response propagates cancellation upstream.
		upstream.close()


def _collect_upstream(upstream) -> bytes:
	"""Return one complete, browser-deliverable SSE response from crm-agents.

	Frappe's development WSGI server can retain a generator-backed response on
	a keep-alive socket even after crm-agents has produced its terminal event.
	The UI stream contract is event-framed rather than transport-chunk-framed,
	so a finite body preserves every event while guaranteeing the browser gets
	the terminal response.
	"""
	return b"".join(_relay_upstream(upstream))


@frappe.whitelist(methods=["POST"])
def stream_chat(payload=None):
	"""Proxy real crm-agents SSE without exposing either server credential."""
	_require_copilot_user()
	body = _request_payload(payload)
	base_url, api_key = _agent_config()
	credential = mint_delegated_credential()
	try:
		upstream = requests.post(
			f"{base_url}/api/v1/chat",
			json=body,
			headers={
				"X-API-Key": api_key,
				"Authorization": f"Bearer {credential['bearer']}",
				"X-Frappe-Delegation": credential["proof"],
				"Accept": "text/event-stream",
			},
			stream=True,
			timeout=_AGENT_TIMEOUT,
		)
	except requests.RequestException:
		return _safe_error_response(503, "Copilot is temporarily unavailable.")

	if upstream.status_code >= 400:
		upstream.close()
		return _safe_error_response(upstream.status_code, "Copilot request was rejected.")

	# Return the generator directly so production WSGI/ASGI servers forward the
	# first event immediately and bound memory to the upstream chunk size.  The
	# relay's finally block closes the upstream if the browser disconnects.
	return Response(
		_relay_upstream(upstream),
		content_type="text/event-stream",
		headers={
			"Cache-Control": "no-cache, no-store",
			"X-Accel-Buffering": "no",
		},
	)


@frappe.whitelist(methods=["GET"])
def list_conversations():
	return _agent_json("/api/v1/chat")


@frappe.whitelist(methods=["GET"])
def get_conversation(session_id: str):
	if not isinstance(session_id, str) or not session_id or len(session_id) > 128:
		frappe.throw("A valid conversation ID is required.", frappe.ValidationError)
	return _agent_json("/api/v1/chat", params={"sessionId": session_id})


@frappe.whitelist(methods=["POST"])
def run_student_nba_evaluation(
	student_id: str,
	force_rerun_reason: str | None = None,
):
	"""Run the caller-scoped NBA evaluation without exposing agent credentials."""
	_require_copilot_user()
	student = str(student_id or "").strip()
	if not student or len(student) > 140:
		frappe.throw("A valid student ID is required.", frappe.ValidationError)
	if force_rerun_reason is not None:
		force_rerun_reason = str(force_rerun_reason).strip()
		if len(force_rerun_reason) < 10 or len(force_rerun_reason) > 500:
			frappe.throw("The rerun reason must be between 10 and 500 characters.", frappe.ValidationError)

	idempotency_key = frappe.get_request_header("Idempotency-Key")
	if not isinstance(idempotency_key, str) or not (8 <= len(idempotency_key) <= 140):
		frappe.throw("A valid Idempotency-Key is required.", frappe.ValidationError)

	base_url, api_key = _agent_config()
	credential = mint_delegated_credential()
	body = {"student_id": student}
	if force_rerun_reason:
		body["force_rerun_reason"] = force_rerun_reason

	try:
		upstream = requests.post(
			f"{base_url}/api/v1/nba-evaluations/student/run",
			json=body,
			headers={
				"X-API-Key": api_key,
				"Authorization": f"Bearer {credential['bearer']}",
				"X-Frappe-Delegation": credential["proof"],
				"Idempotency-Key": idempotency_key,
				"Accept": "application/json",
			},
			timeout=_AGENT_TIMEOUT,
		)
	except requests.RequestException:
		return _safe_error_response(503, "NBA evaluation is temporarily unavailable.")

	if upstream.status_code >= 400:
		if upstream.status_code in {401, 403}:
			message = "The NBA evaluation target is not permitted."
		elif upstream.status_code in {409, 422}:
			message = "The NBA evaluation request was not accepted."
		else:
			message = "NBA evaluation is temporarily unavailable."
		return _safe_error_response(
			upstream.status_code if upstream.status_code in {401, 403, 409, 422} else 503,
			message,
		)

	try:
		payload = upstream.json()
	except ValueError:
		return _safe_error_response(502, "NBA evaluation returned an invalid response.")
	if not isinstance(payload, dict):
		return _safe_error_response(502, "NBA evaluation returned an invalid response.")
	return payload
