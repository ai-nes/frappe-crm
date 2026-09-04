import frappe
import requests
from frappe import _
from frappe.query_builder import Order
from pypika.functions import Replace
from werkzeug.wrappers import Response

from crm.utils import are_same_phone_number, parse_phone_number


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
			doctype = "CRM Contact"
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

	if not log.recording_url:
		frappe.throw(_("Recording URL not found"), frappe.DoesNotExistError)

	auth = _get_recording_credentials(log.telephony_medium)
	with requests.get(log.recording_url, auth=auth, stream=True, timeout=10) as r:
		r.raise_for_status()
		response = Response()
		response.data = r.content
		response.mimetype = "audio/mpeg"
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

	CRMContact = frappe.qb.DocType("CRM Contact")
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
			contact["doctype"] = "CRM Contact"
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
		Replace(
			Replace(Replace(Replace(ContactPhone.phone, " ", ""), "-", ""), "(", ""), ")", ""), "+", ""
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
