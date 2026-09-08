"""Frappe-owned gateway for AI summaries of persisted call transcripts."""

from __future__ import annotations

import json
import re
from typing import Any

import frappe
import requests
from frappe import _

_CALLUUID_RE = re.compile(r"^\d+\.\d+$")
_MAX_TRANSCRIPT_CHARS = 40_000
_MAX_SEGMENTS = 2_000
_DEFAULT_TIMEOUT_SECONDS = 55


def _raise(message: str, exception: type[Exception], status: int) -> None:
	try:
		if isinstance(getattr(frappe.local, "response", None), dict):
			frappe.local.response["http_status_code"] = status
	except (AttributeError, TypeError):
		pass
	frappe.throw(_(message), exception)


def _parse_segments(value: Any) -> list[dict[str, Any]]:
	if value in (None, ""):
		return []
	if isinstance(value, str):
		try:
			value = frappe.parse_json(value)
		except Exception as exc:
			raise ValueError("segments must be a JSON array") from exc
	if not isinstance(value, list) or len(value) > _MAX_SEGMENTS:
		raise ValueError("segments must be an array")
	if any(not isinstance(item, dict) for item in value):
		raise ValueError("segments must contain objects")
	return value


def _agent_config() -> tuple[str, str]:
	base_url = frappe.conf.get("crm_agents_url")
	api_key = frappe.conf.get("crm_agents_api_key")
	if not isinstance(base_url, str) or not base_url.strip():
		_raise("crm-agents URL chưa được cấu hình.", frappe.ValidationError, 503)
	if not isinstance(api_key, str) or not api_key:
		_raise("crm-agents API key chưa được cấu hình.", frappe.ValidationError, 503)
	return base_url.rstrip("/"), api_key


def _timeout_seconds() -> int:
	try:
		value = int(frappe.conf.get("crm_agents_call_summary_timeout_seconds", _DEFAULT_TIMEOUT_SECONDS))
	except (TypeError, ValueError):
		return _DEFAULT_TIMEOUT_SECONDS
	return max(5, min(value, 120))


def _validate_call_log_access(calluuid: str) -> None:
	if frappe.session.user in (None, "", "Guest"):
		_raise("Authentication is required.", frappe.AuthenticationError, 401)
	if not frappe.db.exists("Call Log", calluuid):
		_raise("Call log not found.", frappe.DoesNotExistError, 404)
	if not frappe.has_permission("Call Log", "read", calluuid):
		_raise("You do not have permission to read this call log.", frappe.PermissionError, 403)


def _upstream_payload(response: requests.Response) -> dict[str, Any]:
	try:
		payload = response.json()
	except ValueError as exc:
		raise ValueError("crm-agents returned invalid JSON") from exc
	if isinstance(payload, dict) and isinstance(payload.get("message"), dict):
		payload = payload["message"]
	if not isinstance(payload, dict):
		raise ValueError("crm-agents returned an invalid summary")
	return payload


@frappe.whitelist()
def summarize_call(
	calluuid: str, transcript: str, segments: Any = None, language: str = "vi"
) -> dict[str, Any]:
	"""Return a structured AI summary for one readable Call Log.

	The endpoint deliberately does not write the summary. The STT bridge owns
	the idempotent FCRM Note write so a transient AI failure cannot mark a call
	as failed after its transcript has already been stored.
	"""
	if not isinstance(calluuid, str) or not _CALLUUID_RE.fullmatch(calluuid.strip()):
		_raise("Invalid calluuid.", frappe.ValidationError, 422)
	calluuid = calluuid.strip()
	if not isinstance(transcript, str) or not transcript.strip() or len(transcript) > _MAX_TRANSCRIPT_CHARS:
		_raise("Transcript is invalid or too long.", frappe.ValidationError, 422)
	if not isinstance(language, str) or not 2 <= len(language.strip()) <= 16:
		_raise("Language is invalid.", frappe.ValidationError, 422)
	try:
		parsed_segments = _parse_segments(segments)
	except ValueError as exc:
		_raise(str(exc), frappe.ValidationError, 422)

	_validate_call_log_access(calluuid)
	base_url, api_key = _agent_config()
	payload = {
		"calluuid": calluuid,
		"transcript": transcript,
		"segments": parsed_segments,
		"language": language.strip(),
	}
	try:
		response = requests.post(
			f"{base_url}/api/v1/call-summary",
			headers={"X-API-Key": api_key, "Accept": "application/json"},
			json=payload,
			timeout=_timeout_seconds(),
		)
		response.raise_for_status()
		return _upstream_payload(response)
	except requests.Timeout:
		frappe.logger("crm.api.call_summary").warning("crm-agents call summary timed out call=%s", calluuid)
		_raise("AI call summary service timed out.", frappe.ValidationError, 504)
	except requests.RequestException as exc:
		frappe.logger("crm.api.call_summary").warning(
			"crm-agents call summary unavailable call=%s error=%s", calluuid, type(exc).__name__
		)
		_raise("AI call summary service is unavailable.", frappe.ValidationError, 503)
	except ValueError as exc:
		frappe.logger("crm.api.call_summary").warning(
			"crm-agents call summary invalid response call=%s error=%s", calluuid, str(exc)
		)
		_raise("AI call summary response is invalid.", frappe.ValidationError, 502)
