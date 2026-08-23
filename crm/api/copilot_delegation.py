"""Server-only delegated credentials for the crm-agents Copilot boundary.

The browser authenticates to Frappe with its normal session cookie.  This
module is deliberately not whitelisted: the later Copilot BFF calls it on the
server and is the only component allowed to receive the generated OAuth bearer
and signed proof.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import timedelta

import frappe
from frappe.utils import now_datetime

_AUDIENCE = "crm-agents"
_CLIENT_NAME = "CRM Agents BFF"
_TOKEN_TTL_SECONDS = 120


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
	if not frappe.db.exists("Sessions", {"sid": frappe.session.sid, "user": frappe.session.user}):
		frappe.throw("The current session is no longer active.", frappe.PermissionError)
	kid, keys = _keyring()
	bearer = _mint_bearer(user=frappe.session.user, client=_ensure_client())
	now = int(now_datetime().timestamp())
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
	if frappe.session.user in ("", "Guest") or not frappe.db.exists(
		"Sessions", {"sid": session_id, "user": frappe.session.user}
	):
		frappe.throw("Delegated session is no longer active.", frappe.PermissionError)
	return {"user": frappe.session.user}
