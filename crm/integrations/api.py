import os
import re
from urllib.parse import quote, urlencode, urljoin, urlparse

import frappe
import requests
from frappe import _
from frappe.query_builder import Order
from pypika.functions import Replace
from werkzeug.wrappers import Response

from crm.utils import are_same_phone_number, parse_phone_number

INTEGRATION_TYPES = frozenset({"call", "zalo"})
_WORLDFONE_CALLUUID_RE = re.compile(r"^\d+\.\d+$")
_WORLDFONE_BASE_URL = "https://apps.worldfone.cloud/externalcrm"


def _recording_range_header() -> str | None:
	request = getattr(frappe, "request", None)
	headers = getattr(request, "headers", None)
	if not headers:
		return None
	range_header = str(headers.get("Range") or "").strip()
	return range_header or None


def _parse_byte_range(range_header: str, total_length: int) -> tuple[int, int] | None:
	"""Parse one HTTP byte range, returning inclusive start/end offsets."""
	if total_length <= 0 or not range_header.lower().startswith("bytes="):
		return None

	specification = range_header[6:].strip()
	if not specification or "," in specification or "-" not in specification:
		return None
	start_text, end_text = (part.strip() for part in specification.split("-", 1))
	try:
		if start_text:
			start = int(start_text)
			end = int(end_text) if end_text else total_length - 1
		else:
			suffix_length = int(end_text)
			if suffix_length <= 0:
				return None
			start = max(total_length - suffix_length, 0)
			end = total_length - 1
	except ValueError:
		return None

	if start < 0 or start >= total_length or end < start:
		return None
	return start, min(end, total_length - 1)


def _worldfone_config(name: str, default: str = "") -> str:
	"""Read Worldfone settings without ever exposing them in API payloads."""
	config_key = f"crm_worldfone_{name}"
	env_key = f"WORLDFONE_{name.upper()}"
	return str(frappe.conf.get(config_key) or os.getenv(env_key) or default).strip()


def ensure_call_log_read_access(call_log) -> None:
	"""Require access to a Call Log and its linked CRM record."""
	if not call_log.has_permission("read"):
		frappe.throw(_("Call log not found"), frappe.DoesNotExistError)

	reference_doctype = str(call_log.get("reference_doctype") or "").strip()
	reference_docname = str(call_log.get("reference_docname") or "").strip()
	if not reference_doctype or not reference_docname:
		return
	try:
		reference_doc = frappe.get_doc(reference_doctype, reference_docname)
	except frappe.DoesNotExistError:
		frappe.throw(_("Call log not found"), frappe.DoesNotExistError)
	if not reference_doc.has_permission("read"):
		frappe.throw(_("Call log not found"), frappe.DoesNotExistError)


def _recording_host(value: str) -> str | None:
	try:
		parsed = urlparse(value if "://" in value else f"https://{value}")
		return parsed.hostname.lower().rstrip(".") if parsed.hostname else None
	except ValueError:
		return None


def _recording_allowed_hosts(telephony_medium: str, is_worldfone_call: bool) -> set[str]:
	hosts: set[str] = set()
	if is_worldfone_call or telephony_medium == "Manual":
		worldfone_host = _recording_host(_worldfone_config("base_url", _WORLDFONE_BASE_URL))
		if worldfone_host:
			hosts.add(worldfone_host)
	elif telephony_medium == "Twilio":
		hosts.add("api.twilio.com")
	elif telephony_medium == "Exotel":
		try:
			exotel_host = _recording_host(str(frappe.get_single("Exotel Settings").subdomain or ""))
		except Exception:
			exotel_host = None
		if exotel_host:
			hosts.add(exotel_host)

	extra_hosts = str(
		frappe.conf.get("crm_recording_allowed_hosts")
		or os.getenv("CRM_RECORDING_ALLOWED_HOSTS")
		or ""
	)
	hosts.update(
		host
		for host in (_recording_host(item.strip()) for item in extra_hosts.split(","))
		if host
	)
	return hosts


def _recording_url_allowed(url: str, telephony_medium: str, is_worldfone_call: bool) -> bool:
	try:
		parsed = urlparse(url)
		port = parsed.port
	except ValueError:
		return False
	if (
		parsed.scheme != "https"
		or parsed.username
		or parsed.password
		or port not in (None, 443)
	):
		return False
	host = parsed.hostname.lower().rstrip(".") if parsed.hostname else ""
	return bool(host and host in _recording_allowed_hosts(telephony_medium, is_worldfone_call))


def build_worldfone_recording_url(calluuid: str | None) -> str | None:
	"""Build a Worldfone playback URL from a canonical call UUID.

	The secret is required from site config/environment and is only used by the
	server-side proxy; callers should return :func:`get_recording_url_path`
	instead of this URL.
	"""
	calluuid = str(calluuid or "").strip()
	secret = _worldfone_config("secret")
	if not calluuid or not secret or not _WORLDFONE_CALLUUID_RE.fullmatch(calluuid):
		return None

	base_url = _worldfone_config("base_url", _WORLDFONE_BASE_URL)
	playback_path = _worldfone_config("playback_path", "/playback2.php")
	secret_param = _worldfone_config("secret_param", "secrect")
	api_version = _worldfone_config("api_version", "3")
	base = urljoin(f"{base_url.rstrip('/')}/", playback_path.lstrip('/'))
	query = urlencode(
		{
			"calluuid": calluuid,
			secret_param: secret,
			"version": api_version,
		}
	)
	return f"{base}?{query}"


def _is_worldfone_call(call_log_name: str | None, telephony_medium: str | None, medium: str | None) -> bool:
	return bool(
		_WORLDFONE_CALLUUID_RE.fullmatch(str(call_log_name or "").strip())
		and (telephony_medium == "Manual" or medium == "Worldfone")
	)


def get_recording_url_path(
	call_log_name: str | None,
	recording_url: str | None = None,
	telephony_medium: str | None = None,
	medium: str | None = None,
) -> str | None:
	"""Return the same-origin audio proxy path for a Call Log.

	For imported Worldfone rows the URL may be absent because only the UUID was
	seeded. In that case the proxy will build the provider URL lazily.
	"""
	call_log_name = str(call_log_name or "").strip()
	if not call_log_name:
		return None
	if not str(recording_url or "").strip() and not (
		_is_worldfone_call(call_log_name, telephony_medium, medium)
		and build_worldfone_recording_url(call_log_name)
	):
		return None
	return (
		"/api/method/crm.integrations.api.get_recording_url?call_log_name="
		f"{quote(call_log_name, safe='')}"
	)


def _integration_status(enabled: bool, configured: bool = True) -> str:
	if not configured:
		return "not_configured"
	return "enabled" if enabled else "disabled"


def _call_integration(provider: str, label: str, enabled: bool) -> dict:
	return {
		"type": "call",
		"provider": provider,
		"label": label,
		"enabled": enabled,
		"status": _integration_status(enabled),
	}


def _zalo_integration() -> dict:
	"""Return Zalo OA status without exposing any provider credentials.

	The core CRM does not ship a Zalo Settings DocType yet. Sites that install
	one can opt in by exposing an ``enabled`` field on that single DocType.
	"""
	if not frappe.db.exists("DocType", "Zalo Settings"):
		return {
			"type": "zalo",
			"provider": "zalo_oa",
			"label": "Zalo OA",
			"enabled": False,
			"status": "not_configured",
		}

	meta = frappe.get_meta("Zalo Settings")
	if not meta.has_field("enabled"):
		enabled = False
		configured = False
	else:
		enabled = bool(frappe.db.get_single_value("Zalo Settings", "enabled"))
		configured = True

	return {
		"type": "zalo",
		"provider": "zalo_oa",
		"label": "Zalo OA",
		"enabled": enabled,
		"status": _integration_status(enabled, configured),
	}


def _normalize_integration_type(integration_type: str | None) -> str | None:
	if integration_type is None or not str(integration_type).strip():
		return None

	normalized = str(integration_type).strip().lower()
	if normalized not in INTEGRATION_TYPES:
		frappe.throw(
			_("Unsupported integration type: {0}. Use 'call' or 'zalo'.").format(normalized),
			frappe.ValidationError,
		)
	return normalized


@frappe.whitelist(methods=["GET"])
def get_integrations(type: str | None = None):
	"""Return configured integration providers filtered by type.

	Supported types are ``call`` and ``zalo``. The response only contains
	provider metadata and connection state; secrets are never returned.
	"""
	requested_type = _normalize_integration_type(type)
	integrations = []

	if requested_type in (None, "call"):
		integrations.extend(
			[
				_call_integration(
					"twilio",
					"Twilio",
					bool(frappe.db.get_single_value("Twilio Settings", "enabled")),
				),
				_call_integration(
					"exotel",
					"Exotel",
					bool(frappe.db.get_single_value("Exotel Settings", "enabled")),
				),
			]
		)

	if requested_type in (None, "zalo"):
		integrations.append(_zalo_integration())

	return {
		"data": integrations,
		"meta": {
			"requested_type": requested_type,
			"returned_types": sorted({item["type"] for item in integrations}),
			"total": len(integrations),
		},
	}


def _get_recording_credentials(telephony_medium: str) -> tuple:
	"""Return (api_key, secret) for the given telephony medium."""
	if telephony_medium == "Twilio":
		s = frappe.get_single("Twilio Settings")
		return s.api_key, s.get_password("api_secret")
	elif telephony_medium == "Exotel":
		s = frappe.get_single("Exotel Settings")
		return s.api_key, s.get_password("api_token")
	elif telephony_medium == "Manual":
		# Recording URL already carries its own auth in the query string
		# (e.g. the Worldfone STT bridge's playback link) — no Basic Auth needed.
		return None
	frappe.throw(_("Unknown telephony medium: {0}").format(telephony_medium))


@frappe.whitelist()
def is_call_integration_enabled():
	return {
		"integrations": {
			"twilio": bool(frappe.db.get_single_value("Twilio Settings", "enabled")),
			"exotel": bool(frappe.db.get_single_value("Exotel Settings", "enabled")),
		},
		"default_calling_medium": get_user_default_calling_medium(),
	}


def get_user_default_calling_medium():
	if not frappe.db.exists("Telephony Agent", frappe.session.user):
		return None

	default_medium = frappe.db.get_value("Telephony Agent", frappe.session.user, "default_medium")

	if not default_medium:
		return None

	return default_medium


@frappe.whitelist()
def set_default_calling_medium(medium: str):
	if not frappe.db.exists("Telephony Agent", frappe.session.user):
		frappe.get_doc(
			{
				"doctype": "Telephony Agent",
				"user": frappe.session.user,
				"default_medium": medium,
			}
		).insert(ignore_permissions=True)
	else:
		frappe.db.set_value("Telephony Agent", frappe.session.user, "default_medium", medium)

	return get_user_default_calling_medium()


@frappe.whitelist()
def add_note_to_call_log(call_sid: str, note: dict):
	"""Add/Update note to call log based on call sid."""
	content = note.get("content") or note.get("title")
	_note = None
	if not note.get("name"):
		_note = frappe.get_doc(
			{
				"doctype": "FCRM Note",
				"content": content or "Call Note",
			}
		).insert(ignore_permissions=True)
	else:
		_note = frappe.set_value("FCRM Note", note.get("name"), "content", content)

	call_log = frappe.get_cached_doc("Call Log", call_sid)
	call_log.link_with_reference_doc("FCRM Note", _note.name)
	call_log.save(ignore_permissions=True)

	return _note


@frappe.whitelist()
def add_task_to_call_log(call_sid: str, task: dict):
	"""Add/Update task to call log based on call sid."""
	_task = None
	if not task.get("name"):
		_task = frappe.get_doc(
			{
				"doctype": "Task",
				"title": task.get("title"),
				"description": task.get("description"),
				"assigned_to": task.get("assigned_to"),
				"due_date": task.get("due_date"),
				"status": task.get("status"),
				"priority": task.get("priority"),
			}
		).insert(ignore_permissions=True)
	else:
		_task = frappe.get_doc("Task", task.get("name"))
		_task.update(
			{
				"title": task.get("title"),
				"description": task.get("description"),
				"assigned_to": task.get("assigned_to"),
				"due_date": task.get("due_date"),
				"status": task.get("status"),
				"priority": task.get("priority"),
			}
		)
		_task.save(ignore_permissions=True)

	call_log = frappe.get_doc("Call Log", call_sid)
	call_log.link_with_reference_doc("Task", _task.name)
	call_log.save(ignore_permissions=True)

	return _task


@frappe.whitelist()
def get_contact_reference_from_number(number: str):
	"""Get Contact or CRM Contact from the given number."""
	contact = get_contact_by_phone_number(number)
	if contact.get("name"):
		doctype = "Contact"
		docname = contact.get("name")
		if contact.get("crm_contact"):
			doctype = "CRM Student"
			docname = contact.get("crm_contact")
		return docname, doctype
	return None, None


@frappe.whitelist()
def get_contact_by_phone_number(phone_number: str):
	"""Get contact by phone number."""
	number = parse_phone_number(phone_number)

	if number.get("is_valid"):
		return get_contact(number.get("national_number"), number.get("country"))
	else:
		return get_contact(phone_number, number.get("country"), exact_match=True)


@frappe.whitelist()
def get_recording_url(call_log_name: str):
	"""Fetch and stream a call recording, authenticating with the provider's credentials."""
	if not call_log_name or not frappe.db.exists("Call Log", call_log_name):
		frappe.throw(_("Call log not found"), frappe.DoesNotExistError)

	log = frappe.get_doc("Call Log", call_log_name)
	ensure_call_log_read_access(log)
	recording_url = str(log.recording_url or "").strip()
	is_worldfone_call = _is_worldfone_call(
		log.name,
		log.telephony_medium,
		log.medium,
	)
	if not recording_url and is_worldfone_call:
		recording_url = build_worldfone_recording_url(log.name) or ""

	if not recording_url:
		frappe.throw(_("Recording URL not found"), frappe.DoesNotExistError)

	telephony_medium = log.telephony_medium or ("Manual" if is_worldfone_call else "")
	if not _recording_url_allowed(recording_url, telephony_medium, is_worldfone_call):
		frappe.throw(_("Recording provider is not allowed"), frappe.DoesNotExistError)
	auth = _get_recording_credentials(telephony_medium)
	range_header = _recording_range_header()
	with requests.get(
		recording_url,
		auth=auth,
		headers={"Range": range_header} if range_header else None,
		stream=True,
		timeout=10,
		allow_redirects=False,
	) as r:
		if 300 <= r.status_code < 400:
			frappe.throw(_("Recording provider redirect is not allowed"), frappe.DoesNotExistError)
		if r.status_code not in {200, 206, 416}:
			r.raise_for_status()

		body = r.content
		status = r.status_code
		content_range = r.headers.get("Content-Range")
		try:
			content_length = int(r.headers.get("Content-Length") or len(body))
		except (TypeError, ValueError):
			content_length = len(body)
		if range_header and status == 200:
			byte_range = _parse_byte_range(range_header, content_length)
			if byte_range:
				start, end = byte_range
				body = body[start : end + 1]
				status = 206
				content_range = f"bytes {start}-{end}/{content_length}"

		content_type = (r.headers.get("Content-Type") or "audio/mpeg").split(";", 1)[0]
		response = Response(body, status=status, mimetype=content_type)
		response.headers["Accept-Ranges"] = r.headers.get("Accept-Ranges", "bytes")
		response.headers["Content-Length"] = str(len(body))
		if content_range:
			response.headers["Content-Range"] = content_range
	return response


def get_contact(phone_number: str, country: str = "IN", exact_match: bool = False):
	if not phone_number:
		return {"mobile_no": phone_number}

	cleaned_number = (
		phone_number.strip()
		.replace(" ", "")
		.replace("-", "")
		.replace("(", "")
		.replace(")", "")
		.replace("+", "")
	)

	CRMContact = frappe.qb.DocType("CRM Student")
	normalized_phone = Replace(
		Replace(Replace(Replace(Replace(CRMContact.phone, " ", ""), "-", ""), "(", ""), ")", ""), "+", ""
	)

	query = (
		frappe.qb.from_(CRMContact)
		.select(
			CRMContact.name,
			CRMContact.full_name,
			CRMContact.phone.as_("mobile_no"),
			CRMContact.email,
		)
		.where(normalized_phone.like(f"%{cleaned_number}%"))
		.orderby("modified", order=Order.desc)
	)
	crm_contacts = query.run(as_dict=True)

	for contact in crm_contacts:
		if are_same_phone_number(contact.mobile_no, phone_number, country, validate=not exact_match):
			contact["crm_contact"] = contact.name
			contact["doctype"] = "CRM Student"
			return contact

	Contact = frappe.qb.DocType("Contact")
	normalized_phone = Replace(
		Replace(Replace(Replace(Replace(Contact.mobile_no, " ", ""), "-", ""), "(", ""), ")", ""), "+", ""
	)

	query = (
		frappe.qb.from_(Contact)
		.select(Contact.name, Contact.full_name, Contact.image, Contact.mobile_no)
		.where(normalized_phone.like(f"%{cleaned_number}%"))
		.orderby("modified", order=Order.desc)
	)
	contacts = query.run(as_dict=True)

	if len(contacts) and are_same_phone_number(
		contacts[0].mobile_no, phone_number, country, validate=not exact_match
	):
		return contacts[0]

	# Frappe's current Contact schema stores numbers in the Contact Phone child
	# table; older sites may still expose a denormalized mobile_no column. Keep
	# both paths so telephony lookup works across migrated sites.
	ContactPhone = frappe.qb.DocType("Contact Phone")
	normalized_phone_child = Replace(
		Replace(Replace(Replace(Replace(ContactPhone.phone, " ", ""), "-", ""), "(", ""), ")", ""), "+", ""
	)
	phone_query = (
		frappe.qb.from_(Contact)
		.join(ContactPhone)
		.on((ContactPhone.parent == Contact.name) & (ContactPhone.parenttype == "Contact"))
		.select(Contact.name, Contact.full_name, Contact.image, ContactPhone.phone.as_("mobile_no"))
		.where(ContactPhone.parentfield == "phone_nos")
		.where(normalized_phone_child.like(f"%{cleaned_number}%"))
		.orderby("modified", order=Order.desc)
	)
	phone_contacts = phone_query.run(as_dict=True)
	if len(phone_contacts) and are_same_phone_number(
		phone_contacts[0].mobile_no, phone_number, country, validate=not exact_match
	):
		return phone_contacts[0]

	return {"mobile_no": phone_number}
