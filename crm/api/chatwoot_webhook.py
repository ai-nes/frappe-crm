"""Signed Chatwoot message webhook adapter for CRM Interaction."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import frappe
from werkzeug.wrappers import Response

from crm.fcrm.interaction_log import ingest_external_interaction
from crm.fcrm.student_intake import StudentIntakeError
from crm.utils import get_docs_by_phone, normalize_phone_for_lookup

TIMESTAMP_WINDOW_SECONDS = 300
SIGNATURE_HEADER = "X-Chatwoot-Signature"
TIMESTAMP_HEADER = "X-Chatwoot-Timestamp"
DELIVERY_HEADER = "X-Chatwoot-Delivery"
MAX_WEBHOOK_BODY_BYTES = 1_000_000
MAX_MESSAGE_CONTENT_BYTES = 60_000

CHATWOOT_CHANNELS = {
	"channel::api": "webchat",
	"channel::email": "email",
	"channel::facebookpage": "facebook",
	"channel::instagram": "instagram",
	"channel::line": "line",
	"channel::telegram": "telegram",
	"channel::twiliosms": "sms",
	"channel::webwidget": "webchat",
	"channel::whatsapp": "whatsapp",
	"channel::zalo": "zalo",
	"api": "webchat",
	"email": "email",
	"facebook": "facebook",
	"facebookpage": "facebook",
	"instagram": "instagram",
	"line": "line",
	"telegram": "telegram",
	"twiliosms": "sms",
	"webwidget": "webchat",
	"whatsapp": "whatsapp",
	"zalo": "zalo",
}


def _fail(code: str, message: str):
	raise StudentIntakeError(code, message)


def _json_response(payload: dict[str, Any], status: int = 200) -> Response:
	return Response(
		json.dumps(payload, ensure_ascii=False),
		status=status,
		content_type="application/json",
	)


def _validation_error(detail: str) -> Response:
	request_id = _header("X-Request-ID") or uuid.uuid4().hex
	return _json_response(
		{
			"error": "validation_error",
			"detail": detail,
			"session_id": None,
			"request_id": request_id,
		},
		status=422,
	)


def _text(value: Any) -> str | None:
	if value is None:
		return None
	value = str(value).strip()
	return value or None


def _header(name: str) -> str | None:
	try:
		return frappe.request.headers.get(name) or frappe.request.headers.get(name.lower())
	except Exception:
		return None


def _raw_body() -> bytes:
	try:
		body = frappe.request.get_data(cache=True, as_text=False)
	except Exception:
		body = b""
	if isinstance(body, str):
		return body.encode("utf-8")
	return body or b""


def _configured_secret() -> str | None:
	try:
		secret = frappe.conf.get("chatwoot_webhook_secret")
	except Exception:
		secret = None
	return _text(secret)


def _timestamp_window() -> int:
	try:
		configured = frappe.conf.get("chatwoot_webhook_timestamp_window")
		if configured:
			return max(1, int(configured))
	except (TypeError, ValueError, AttributeError):
		pass
	return TIMESTAMP_WINDOW_SECONDS


def verify_signature(
	raw_body: bytes, timestamp: str, provided_signature: str, secret: str | None = None
) -> bool:
	"""Verify Chatwoot's HMAC-SHA256 signature over ``timestamp.raw_body``."""
	if len(raw_body) > MAX_WEBHOOK_BODY_BYTES:
		_fail("INVALID_INPUT", "Chatwoot webhook payload exceeds the size limit.")
	if not timestamp or not provided_signature:
		_fail("REPLAY_REJECTED", "Chatwoot webhook signature headers are incomplete.")
	try:
		timestamp_value = int(timestamp)
	except (TypeError, ValueError):
		_fail("REPLAY_REJECTED", "Chatwoot webhook timestamp is invalid.")
	if abs(int(time.time()) - timestamp_value) > _timestamp_window():
		_fail("REPLAY_REJECTED", "Chatwoot webhook timestamp is outside the allowed window.")
	secret = _text(secret) or _configured_secret()
	if not secret:
		_fail("CONFIGURATION_ERROR", "chatwoot_webhook_secret is not configured.")

	message = str(timestamp).encode("utf-8") + b"." + raw_body
	expected = "sha256=" + hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
	provided = provided_signature.strip()
	if not provided.startswith("sha256="):
		provided = "sha256=" + provided
	if not hmac.compare_digest(expected, provided):
		_fail("REPLAY_REJECTED", "Chatwoot webhook signature is invalid.")
	return True


def _json_body(raw_body: bytes) -> dict[str, Any]:
	try:
		payload = json.loads(raw_body.decode("utf-8"))
	except (UnicodeDecodeError, ValueError):
		_fail("INVALID_INPUT", "Chatwoot webhook payload is not valid JSON.")
	if not isinstance(payload, dict):
		_fail("INVALID_INPUT", "Chatwoot webhook payload must be a JSON object.")
	return payload


def _config_value(name: str) -> Any:
	try:
		return frappe.conf.get(name)
	except Exception:
		return None


def _as_list(value: Any) -> list[str]:
	if value in (None, ""):
		return []
	if isinstance(value, str):
		return [item.strip() for item in value.split(",") if item.strip()]
	if isinstance(value, (list, tuple, set)):
		return [str(item).strip() for item in value if str(item).strip()]
	return []


def _as_bool(value: Any) -> bool:
	return value is True or str(value).casefold() in {"1", "true", "yes", "on"}


def _account_id(payload: dict[str, Any]) -> str | None:
	account = payload.get("account")
	account_id = account.get("id") if isinstance(account, dict) else None
	return _text(account_id or payload.get("account_id"))


def _assert_account(payload: dict[str, Any]) -> str:
	account_id = _account_id(payload)
	configured = _text(_config_value("chatwoot_account_id"))
	if configured and account_id != configured:
		_fail("UNAUTHORIZED", "The Chatwoot account is not configured for this CRM site.")
	return account_id or "default"


def _has_contact_mapping_field() -> bool:
	try:
		return bool(frappe.get_meta("CRM Contact").get_field("chatwoot_contact_id"))
	except Exception:
		return False


def _contact_names_by_email(email: str) -> set[str]:
	names: set[str] = set()
	for value in {email, email.casefold()}:
		try:
			names.update(frappe.get_all("CRM Contact", filters={"email": value}, pluck="name"))
		except Exception:
			continue
	return names


def _contact_names_by_phone(phone: str) -> set[str]:
	names = {row["name"] for row in get_docs_by_phone("CRM Contact", phone, "phone") if row.get("name")}
	if not names:
		normalized = normalize_phone_for_lookup(phone)
		try:
			names.update(frappe.get_all("CRM Contact", filters={"phone": normalized}, pluck="name"))
		except Exception:
			pass
	return names


def _bind_chatwoot_contact(contact_name: str, chatwoot_contact_id: str) -> None:
	if not _has_contact_mapping_field():
		return
	current = frappe.db.get_value("CRM Contact", contact_name, "chatwoot_contact_id")
	if current and str(current) != chatwoot_contact_id:
		_fail("AMBIGUOUS_TARGET", "The CRM Contact is already linked to another Chatwoot contact.")
	if current:
		return
	try:
		frappe.db.set_value(
			"CRM Contact",
			contact_name,
			"chatwoot_contact_id",
			chatwoot_contact_id,
			update_modified=False,
		)
	except (frappe.UniqueValidationError, frappe.DuplicateEntryError):
		mapped = frappe.get_all(
			"CRM Contact", filters={"chatwoot_contact_id": chatwoot_contact_id}, pluck="name"
		)
		if mapped != [contact_name]:
			_fail("AMBIGUOUS_TARGET", "The Chatwoot contact is mapped to another CRM Contact.")


def resolve_contact(contact: dict[str, Any]) -> str:
	"""Resolve a Chatwoot contact by durable ID, then unique email/phone evidence."""
	chatwoot_contact_id = _text(contact.get("id") or contact.get("contact_id"))
	if not chatwoot_contact_id:
		_fail("INVALID_INPUT", "Chatwoot contact.id is required.")

	candidates: set[str] = set()
	if _has_contact_mapping_field():
		try:
			candidates.update(
				frappe.get_all(
					"CRM Contact",
					filters={"chatwoot_contact_id": chatwoot_contact_id},
					pluck="name",
				)
			)
		except Exception:
			pass
	if len(candidates) > 1:
		_fail("AMBIGUOUS_TARGET", "The Chatwoot contact maps to multiple CRM Contacts.")
	if candidates:
		return next(iter(candidates))

	email = _text(contact.get("email") or contact.get("email_id"))
	phone = _text(contact.get("phone_number") or contact.get("phone"))
	if email:
		candidates.update(_contact_names_by_email(email))
	if phone:
		candidates.update(_contact_names_by_phone(phone))
	if len(candidates) != 1:
		_fail(
			"AMBIGUOUS_TARGET" if candidates else "INVALID_TARGET",
			"The Chatwoot contact does not resolve to exactly one CRM Contact.",
		)
	contact_name = next(iter(candidates))
	_bind_chatwoot_contact(contact_name, chatwoot_contact_id)
	return contact_name


def _channel(payload: dict[str, Any]) -> str:
	conversation = payload.get("conversation")
	inbox = payload.get("inbox")
	raw = None
	if isinstance(conversation, dict):
		raw = conversation.get("channel")
	if not raw and isinstance(inbox, dict):
		raw = inbox.get("channel_type") or inbox.get("name")
	key = str(raw or "channel::api").casefold().replace(" ", "").replace("_", "").replace("-", "")
	return CHATWOOT_CHANNELS.get(key, "webchat")


def _direction(message_type: Any) -> str:
	value = str(message_type).casefold()
	if value in {"incoming", "received", "0"}:
		return "inbound"
	if value in {"outgoing", "sent", "template", "1", "3"}:
		return "outbound"
	_fail("INVALID_INPUT", "Chatwoot message_type is not supported.")


def _occurred_at(value: Any) -> str:
	if value in (None, ""):
		return str(datetime.now(timezone.utc).replace(tzinfo=None))
	if isinstance(value, (int, float)):
		try:
			parsed = datetime.fromtimestamp(value, timezone.utc).replace(tzinfo=None)
		except (OverflowError, OSError, ValueError):
			parsed = None
	else:
		try:
			parsed = frappe.utils.get_datetime(value)
		except (TypeError, ValueError):
			parsed = None
	if not parsed:
		_fail("INVALID_INPUT", "Chatwoot created_at must be a valid datetime.")
	if parsed.tzinfo:
		parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
	return str(parsed)


def normalize_message_payload(
	payload: dict[str, Any], crm_contact: str | None, account_id: str
) -> dict[str, Any]:
	message_id = _text(payload.get("id") or payload.get("message_id"))
	if not message_id:
		_fail("INVALID_INPUT", "Chatwoot message.id is required.")
	if len(message_id) > 120:
		_fail("INVALID_INPUT", "Chatwoot message.id exceeds the size limit.")
	conversation = payload.get("conversation")
	conversation = conversation if isinstance(conversation, dict) else {}
	sender = payload.get("sender")
	sender = sender if isinstance(sender, dict) else {}
	direction = _direction(payload.get("message_type"))
	content = payload.get("content")
	if not isinstance(content, str) or not content.strip():
		if payload.get("attachments") or payload.get("attachment"):
			content = "[Chatwoot attachment]"
		else:
			_fail("INVALID_INPUT", "Chatwoot message content is required.")
	if len(content.encode("utf-8")) > MAX_MESSAGE_CONTENT_BYTES:
		_fail("INVALID_INPUT", "Chatwoot message content exceeds the size limit.")
	conversation_id = _text(conversation.get("id") or conversation.get("display_id"))
	sender_type = str(sender.get("type") or sender.get("sender_type") or "").casefold()
	agent_id = _text(sender.get("id")) if sender_type in {"user", "agent", "agent_bot", "captain"} else None
	speaker_role = "student" if direction == "inbound" else "advisor"
	occurred_at = _occurred_at(payload.get("created_at"))
	source_record_id = f"{account_id}:message:{message_id}"
	return {
		"source_namespace": "chatwoot",
		"source_record_id": source_record_id,
		"idempotency_key": source_record_id,
		"contact_id": crm_contact,
		"channel": _channel(payload),
		"direction": direction,
		"occurred_at": occurred_at,
		"conversation_id": conversation_id,
		"agent_id": agent_id,
		"evidence_kind": "message",
		"evidence_state": "final",
		"source_revision": 1,
		"turns": [
			{
				"speaker_role": speaker_role,
				"content": content,
				"occurred_at": occurred_at,
			}
		],
	}


def _signed_context() -> dict[str, Any]:
	actor_user = _text(_config_value("chatwoot_webhook_actor_user")) or "Administrator"
	if not frappe.db.exists("User", actor_user):
		_fail("CONFIGURATION_ERROR", "chatwoot_webhook_actor_user is not a valid User.")
	campus_scope = _as_list(_config_value("chatwoot_webhook_campus_scope"))
	team_scope = _as_list(_config_value("chatwoot_webhook_team_scope"))
	scope_all = _as_bool(_config_value("chatwoot_webhook_allow_all_contacts"))
	if not scope_all and (not campus_scope or not team_scope):
		_fail(
			"CONFIGURATION_ERROR",
			"Configure Chatwoot Campus/Team scopes or explicitly allow all contacts.",
		)
	return {
		"actor_user": actor_user,
		"campus_scope": campus_scope,
		"team_scope": team_scope,
		"scope_all": scope_all,
	}


def _response(payload: dict[str, Any]) -> dict[str, Any]:
	return {
		"status": "ignored",
		"event": payload.get("event"),
		"delivery_id": _header(DELIVERY_HEADER),
	}


def _conversation_sender(payload: dict[str, Any]) -> dict[str, Any] | None:
	conversation = payload.get("conversation")
	if not isinstance(conversation, dict):
		return None
	meta = conversation.get("meta")
	if not isinstance(meta, dict):
		return None
	sender = meta.get("sender")
	return sender if isinstance(sender, dict) else None


@frappe.whitelist(allow_guest=True, methods=["POST"])
def receive() -> Response | dict[str, Any]:
	"""Receive one signed Chatwoot webhook event."""
	raw_body = _raw_body()
	verify_signature(raw_body, _header(TIMESTAMP_HEADER) or "", _header(SIGNATURE_HEADER) or "")
	payload = _json_body(raw_body)
	account_id = _assert_account(payload)
	event = _text(payload.get("event"))
	if not event:
		_fail("INVALID_INPUT", "Chatwoot webhook event is required.")
	if event != "message_created":
		return _response(payload)
	if _as_bool(payload.get("private")) or _as_bool(payload.get("is_private")):
		return _response(payload)
	if str(payload.get("message_type")).casefold() in {"activity", "2"}:
		return _response(payload)
	contact = _conversation_sender(payload)
	if not contact or not _text(contact.get("phone_number")):
		return _validation_error("Missing phone_number in conversation.meta.sender")
	signed_context = _signed_context()
	canonical_payload = normalize_message_payload(payload, None, account_id)
	crm_contact = resolve_contact(contact)
	canonical_payload["contact_id"] = crm_contact
	ingest_external_interaction(
		canonical_payload,
		signed_context=signed_context,
	)
	return _json_response({"status": "ok"})


handle_webhook = receive
webhook = receive
