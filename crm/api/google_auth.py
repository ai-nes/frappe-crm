"""Google OAuth for CRM users.

This module intentionally does not use Frappe's ``Social Login Key`` flow.
Frappe's generic OAuth flow creates website users and derives their role from
Portal Settings, while CRM access is governed by the canonical CRM role policy.
"""

from __future__ import annotations

import json
import os
from urllib.parse import urlencode

import frappe
import requests
from frappe import _

from crm.api.user import set_canonical_crm_profile
from crm.fcrm.role_policy import CANONICAL_SELECTABLE_ROLES, CRM_BUSINESS_ROLES


GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
CONFIG_KEY = "crm_google_oauth"
STATE_PREFIX = "crm_google_oauth"
DEFAULT_REDIRECT_TO = "/crm"
DEFAULT_ROLE = "Sale"
STATE_TTL_SECONDS = 600


def _config() -> dict:
	value = frappe.conf.get(CONFIG_KEY) or {}
	config = dict(value) if isinstance(value, dict) else {}
	env_config = {
		"client_id": os.getenv("CRM_GOOGLE_OAUTH_CLIENT_ID"),
		"client_secret": os.getenv("CRM_GOOGLE_OAUTH_CLIENT_SECRET"),
		"redirect_uri": os.getenv("CRM_GOOGLE_OAUTH_REDIRECT_URI"),
		"default_role": os.getenv("CRM_GOOGLE_OAUTH_DEFAULT_ROLE"),
		"allowed_domains": os.getenv("CRM_GOOGLE_OAUTH_ALLOWED_DOMAINS"),
		"dashboard_url": os.getenv("CRM_GOOGLE_OAUTH_DASHBOARD_URL"),
	}
	for key, env_value in env_config.items():
		if not config.get(key) and env_value:
			config[key] = env_value

	if isinstance(config.get("allowed_domains"), str):
		config["allowed_domains"] = [domain for domain in config["allowed_domains"].split(",") if domain.strip()]
	if isinstance(config.get("dashboard_url"), str):
		config["dashboard_url"] = [url for url in config["dashboard_url"].split(",") if url.strip()]
	return config


def _client_credentials() -> tuple[str, str]:
	config = _config()
	client_id = str(config.get("client_id") or "").strip()
	client_secret = str(config.get("client_secret") or "").strip()
	if not client_id or not client_secret:
		frappe.throw(
			_("Google OAuth is not configured. Set crm_google_oauth.client_id and client_secret."),
			frappe.ValidationError,
		)
	return client_id, client_secret


def _redirect_uri() -> str:
	return str(
		_config().get("redirect_uri")
		or frappe.utils.get_url("/api/method/crm.api.google_auth.callback")
	).strip()


def _default_role() -> str:
	role = str(_config().get("default_role") or DEFAULT_ROLE).strip()
	if role not in CANONICAL_SELECTABLE_ROLES or role == "System Manager":
		frappe.throw(_("Invalid CRM role configured for Google OAuth: {0}").format(role), frappe.ValidationError)
	return role


def _allowed_redirect_bases() -> list[str]:
	"""External origins (the admissions dashboard) allowed as a post-login target."""
	bases = _config().get("dashboard_url") or []
	if isinstance(bases, str):
		bases = [bases]
	return [str(base).strip().rstrip("/") for base in bases if str(base).strip()]


def _safe_redirect_to(value: str | None) -> str:
	"""Allow a local application path, or an absolute URL under a configured dashboard origin.

	Any other absolute URL falls back to the local default so an attacker cannot
	turn the login flow into an open redirect.
	"""
	value = (value or DEFAULT_REDIRECT_TO).strip()

	if value.startswith(("http://", "https://")):
		for base in _allowed_redirect_bases():
			if value == base or value.startswith(f"{base}/"):
				return value
		return DEFAULT_REDIRECT_TO

	if not value.startswith("/") or value.startswith("//"):
		return DEFAULT_REDIRECT_TO
	return value


def _state_key(state: str) -> str:
	return f"{STATE_PREFIX}:{state}"


def _create_state(redirect_to: str) -> str:
	state = frappe.generate_hash(length=32)
	frappe.cache.set_value(
		_state_key(state),
		json.dumps({"redirect_to": _safe_redirect_to(redirect_to), "sid": frappe.session.sid}),
		expires_in_sec=STATE_TTL_SECONDS,
	)
	return state


def _consume_state(state: str) -> str | None:
	if not state:
		return None

	key = _state_key(state)
	payload = frappe.cache.get_value(key)
	frappe.cache.delete_value(key)
	if not payload:
		return None

	try:
		payload = json.loads(payload) if isinstance(payload, str) else payload
	except (TypeError, ValueError):
		return None

	if payload.get("sid") != frappe.session.sid:
		return None
	return _safe_redirect_to(payload.get("redirect_to"))


def _authorize_url(redirect_to: str) -> str:
	client_id, _ = _client_credentials()
	state = _create_state(redirect_to)
	return "{}?{}".format(
		GOOGLE_AUTHORIZE_URL,
		urlencode(
			{
				"client_id": client_id,
				"redirect_uri": _redirect_uri(),
				"response_type": "code",
				"scope": "openid email profile",
				"state": state,
				"access_type": "online",
				"prompt": "select_account",
			}
		),
	)


@frappe.whitelist(allow_guest=True)
def login(redirect_to: str = DEFAULT_REDIRECT_TO):
	"""Top-level entry point that redirects the browser straight to Google.

	The SPA login screen (including an external dashboard origin) navigates here
	so the guest session cookie is issued in a first-party context before the
	Google round trip, and ``callback`` can return the browser to ``redirect_to``.
	"""
	frappe.local.response["type"] = "redirect"
	frappe.local.response["location"] = _authorize_url(redirect_to)


@frappe.whitelist(allow_guest=True)
def providers(redirect_to: str = DEFAULT_REDIRECT_TO):
	"""Return the CRM-owned Google login button configuration."""
	config = _config()
	if not config.get("client_id") or not config.get("client_secret"):
		return []

	return [
		{
			"name": "google",
			"provider_name": "Google",
			"auth_url": _authorize_url(redirect_to),
			"icon": "/assets/frappe/icons/social/google.svg",
		}
	]


def _exchange_code(code: str) -> dict:
	client_id, client_secret = _client_credentials()
	response = requests.post(
		GOOGLE_TOKEN_URL,
		data={
			"code": code,
			"client_id": client_id,
			"client_secret": client_secret,
			"redirect_uri": _redirect_uri(),
			"grant_type": "authorization_code",
		},
		timeout=10,
	)
	if response.status_code >= 400:
		frappe.throw(_("Google authorization code could not be exchanged."), frappe.AuthenticationError)

	try:
		payload = response.json()
	except ValueError:
		frappe.throw(_("Google returned an invalid token response."), frappe.AuthenticationError)

	if not payload.get("access_token"):
		frappe.throw(_("Google did not return an access token."), frappe.AuthenticationError)
	return payload


def _fetch_google_identity(access_token: str) -> dict:
	response = requests.get(
		GOOGLE_USERINFO_URL,
		headers={"Authorization": f"Bearer {access_token}"},
		timeout=10,
	)
	if response.status_code >= 400:
		frappe.throw(_("Google identity could not be verified."), frappe.AuthenticationError)

	try:
		identity = response.json()
	except ValueError:
		frappe.throw(_("Google returned an invalid identity response."), frappe.AuthenticationError)

	email = str(identity.get("email") or "").strip().lower()
	if not identity.get("sub") or not email or identity.get("email_verified") is not True:
		frappe.throw(_("A verified Google email is required."), frappe.AuthenticationError)

	allowed_domains = _config().get("allowed_domains") or []
	if allowed_domains:
		allowed_domains = {str(domain).strip().lower().lstrip("@") for domain in allowed_domains}
		if email.rsplit("@", 1)[-1] not in allowed_domains:
			frappe.throw(_("This Google account is not allowed to access CRM."), frappe.PermissionError)

	identity["email"] = email
	return identity


def _get_or_create_crm_user(identity: dict):
	email = identity["email"]
	user_name = frappe.db.exists("User", email)

	if user_name:
		user = frappe.get_doc("User", user_name)
		if not user.enabled:
			frappe.throw(_("User {0} is disabled.").format(email), frappe.PermissionError)
	else:
		user = frappe.new_doc("User")
		user.update(
			{
				"email": email,
				"first_name": identity.get("given_name") or identity.get("name") or email.split("@", 1)[0],
				"last_name": identity.get("family_name"),
				"enabled": 1,
				"user_type": "System User",
				"new_password": frappe.generate_hash(length=32),
				"send_welcome_email": 0,
				"user_image": identity.get("picture"),
			}
		)
		user.flags.ignore_permissions = True
		user.flags.no_welcome_mail = True
		user.insert(ignore_permissions=True)

	roles = set(frappe.get_roles(user.name))
	if user.user_type != "System User":
		user.user_type = "System User"
		user.flags.ignore_permissions = True
		user.save(ignore_permissions=True)

	# Preserve an already assigned CRM profile. Only accounts without one get the
	# explicitly configured onboarding role; Google never supplies a role.
	if not roles & CRM_BUSINESS_ROLES and "System Manager" not in roles:
		set_canonical_crm_profile(user, _default_role())
		user.flags.ignore_permissions = True
		user.save(ignore_permissions=True)

	return user


def _redirect_error(message: str):
	frappe.respond_as_web_page(_("Google Login Failed"), message, success=False, http_status_code=403)


@frappe.whitelist(allow_guest=True)
def callback(code: str | None = None, state: str | None = None, error: str | None = None):
	"""Consume Google's callback, establish the Frappe session, and redirect to CRM."""
	redirect_to = _consume_state(state or "")
	if redirect_to is None:
		return _redirect_error(_("Your Google login attempt is invalid or has expired."))
	if error:
		return _redirect_error(_("Google cancelled the login attempt."))
	if not code:
		return _redirect_error(_("Google did not return an authorization code."))

	try:
		token = _exchange_code(code)
		identity = _fetch_google_identity(token["access_token"])
		user = _get_or_create_crm_user(identity)
		frappe.local.login_manager.login_as(user.name)
		frappe.db.commit()
	except (frappe.AuthenticationError, frappe.PermissionError, frappe.ValidationError, requests.RequestException):
		return _redirect_error(_("Google authentication was not accepted."))

	location = (
		redirect_to
		if redirect_to.startswith(("http://", "https://"))
		else frappe.utils.get_url(redirect_to)
	)
	frappe.local.response["type"] = "redirect"
	frappe.local.response["location"] = location
