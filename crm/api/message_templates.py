"""Permission-aware CRUD APIs for Lead Sale email message templates."""

from __future__ import annotations

import html
import re
from typing import Any

import frappe
from frappe import _

from crm.api.snippets import resolve_snippet_references
from crm.fcrm.lead_identity import resolve_lead_name

MESSAGE_TEMPLATE = "CRM Message Template"
MESSAGE_TEMPLATE_LIBRARY = "CRM Message Template Library"
MESSAGE_TEMPLATE_FIELDS = (
	"name",
	"template_name",
	"is_public",
	"is_system_template",
	"library_category",
	"description",
	"owner",
	"creation",
	"modified",
	"subject",
	"body",
)
MESSAGE_TEMPLATE_DATA_FIELDS = frozenset({"name", "subject", "body", "sharing"})
MESSAGE_TEMPLATE_LIBRARY_DATA_FIELDS = frozenset(
	{"name", "subject", "body", "category", "description", "isActive"}
)
MESSAGE_TEMPLATE_PREVIEW_FIELDS = frozenset({"subject", "body"})
TOKEN_PATTERN = re.compile(r"\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}")
PROCESSING_STATUS_LABELS = {
	"NEW": "Mới",
	"PROCESSING": "Đang xử lý",
	"PROCESSED": "Đã xử lý",
	"ASSIGNED": "Đã phân công",
	"CLOSED": "Đã đóng",
}


def _require_authentication() -> None:
	if not frappe.session.user or frappe.session.user == "Guest":
		frappe.throw(_("Authentication is required."), frappe.AuthenticationError)


def _require_admin() -> None:
	_require_authentication()
	actor = frappe.session.user
	if actor != "Administrator" and "System Manager" not in frappe.get_roles(actor):
		frappe.throw(_("Only administrators can manage the template library."), frappe.PermissionError)


def _parse_data(value: dict[str, Any] | str | None) -> dict[str, Any]:
	if isinstance(value, str):
		try:
			value = frappe.parse_json(value)
		except (TypeError, ValueError):
			value = None
	if not isinstance(value, dict):
		frappe.throw(_("Template data must be an object."), frappe.ValidationError)
	return value


def _text(value: Any, fieldname: str, *, optional: bool = False) -> str:
	result = str(value or "").strip()
	if not result and not optional:
		frappe.throw(_("{0} is required.").format(fieldname), frappe.ValidationError)
	return result


def _sharing_value(value: Any) -> str:
	sharing = str(value or "public").strip().lower()
	if sharing not in {"public", "private"}:
		frappe.throw(_("Sharing must be either public or private."), frappe.ValidationError)
	return sharing


def _is_truthy(value: Any) -> bool:
	return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _normalize_data(data: dict[str, Any]) -> dict[str, Any]:
	unknown = set(data) - MESSAGE_TEMPLATE_DATA_FIELDS
	if unknown:
		frappe.throw(
			_("Unsupported template fields: {0}.").format(", ".join(sorted(unknown))),
			frappe.ValidationError,
		)
	values = {
		"template_name": _text(data.get("name"), _("Template name")),
		"subject": _text(data.get("subject"), _("Subject")),
		"body": _text(data.get("body"), _("Body")),
		"is_public": 1 if _sharing_value(data.get("sharing")) == "public" else 0,
	}
	return values


def _normalize_library_data(data: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
	unknown = set(data) - MESSAGE_TEMPLATE_LIBRARY_DATA_FIELDS
	if unknown:
		frappe.throw(
			_("Unsupported library template fields: {0}.").format(", ".join(sorted(unknown))),
			frappe.ValidationError,
		)
	values: dict[str, Any] = {}
	if not partial or "name" in data:
		values["template_name"] = _text(data.get("name"), _("Template name"))
	if not partial or "category" in data:
		values["category"] = _text(data.get("category") or "general", _("Template category"))
	if not partial or "subject" in data:
		values["subject"] = _text(data.get("subject"), _("Subject"))
	if not partial or "body" in data:
		values["body"] = _text(data.get("body"), _("Body"))
	if "description" in data:
		values["description"] = str(data.get("description") or "").strip()
	if "isActive" in data:
		values["is_active"] = 1 if _is_truthy(data.get("isActive")) else 0
	elif not partial:
		values["is_active"] = 1
	return values


def _owner_name(owner: str, cache: dict[str, str]) -> str:
	if owner not in cache:
		cache[owner] = frappe.db.get_value("User", owner, "full_name") or owner
	return cache[owner]


def _can_edit(owner: str) -> bool:
	actor = frappe.session.user
	return bool(actor == "Administrator" or "System Manager" in frappe.get_roles(actor) or owner == actor)


def _payload(row: Any, owner_cache: dict[str, str] | None = None) -> dict[str, Any]:
	owner_cache = owner_cache if owner_cache is not None else {}
	owner = str(row.get("owner") or "")
	return {
		"id": row.get("name"),
		"code": row.get("name"),
		"name": row.get("template_name"),
		"ownerId": owner,
		"owner": _owner_name(owner, owner_cache),
		"sharing": "public" if int(row.get("is_public") or 0) else "private",
		"isSystemTemplate": bool(int(row.get("is_system_template") or 0)),
		"libraryCategory": row.get("library_category") or "",
		"description": row.get("description") or "",
		"isActive": True,
		"createdAt": row.get("creation"),
		"modifiedAt": row.get("modified"),
		"subject": row.get("subject") or "",
		"body": row.get("body") or "",
		"canEdit": _can_edit(owner),
	}


def _library_payload(row: Any, owner_cache: dict[str, str] | None = None) -> dict[str, Any]:
	owner_cache = owner_cache if owner_cache is not None else {}
	owner = str(row.get("owner") or "")
	return {
		"id": row.get("name"),
		"code": row.get("name"),
		"name": row.get("template_name"),
		"ownerId": owner,
		"owner": _owner_name(owner, owner_cache),
		"sharing": "public",
		"isSystemTemplate": True,
		"libraryCategory": row.get("category") or "general",
		"description": row.get("description") or "",
		"isActive": bool(int(row.get("is_active") or 0)),
		"createdAt": row.get("creation"),
		"modifiedAt": row.get("modified"),
		"subject": row.get("subject") or "",
		"body": row.get("body") or "",
		"canEdit": _can_edit(owner),
	}


def _expected_modified(doc: Any, expected_modified: str | None) -> None:
	if expected_modified and str(doc.modified) != str(expected_modified):
		frappe.throw(
			_("This template changed while you were editing it. Reload and try again."),
			frappe.ValidationError,
		)


def _document_name(name: Any) -> str:
	return _text(name, _("Template name"))


def _normalize_preview_data(data: dict[str, Any]) -> dict[str, str]:
	unknown = set(data) - MESSAGE_TEMPLATE_PREVIEW_FIELDS
	if unknown:
		frappe.throw(
			_("Unsupported preview fields: {0}.").format(", ".join(sorted(unknown))),
			frappe.ValidationError,
		)
	return {
		"subject": _text(data.get("subject"), _("Subject")),
		"body": _text(data.get("body"), _("Body")),
	}


def _label(doctype: str, name: Any, fieldname: str) -> str:
	value = str(name or "").strip()
	if not value:
		return ""
	return str(frappe.db.get_value(doctype, value, fieldname) or value)


def _user_context() -> dict[str, str]:
	user = (
		frappe.db.get_value(
			"User",
			frappe.session.user,
			["email", "full_name", "mobile_no", "phone"],
			as_dict=True,
		)
		or {}
	)
	return {
		"full_name": str(user.get("full_name") or frappe.session.user or ""),
		"email": str(user.get("email") or frappe.session.user or ""),
		"phone": str(user.get("mobile_no") or user.get("phone") or ""),
	}


def _preview_context(lead: Any) -> dict[str, Any]:
	full_name = str(lead.get("student_name") or "").strip()
	name_parts = full_name.split()
	first_name = name_parts[-1] if name_parts else ""
	last_name = " ".join(name_parts[:-1])
	processing_status = str(lead.get("processing_status") or "").strip().upper()
	created_at = lead.get("creation")
	if created_at:
		created_at = frappe.utils.get_datetime(created_at).strftime("%d/%m/%Y")
	campaign_name = _label("CRM Campaign", lead.get("campaign"), "title")
	school_name = _label("CRM High School", lead.get("high_school"), "school_name")
	program_name = _label("CRM Major", lead.get("major"), "major_name")
	program_name = program_name or str(lead.get("major") or lead.get("aspiration") or "")
	status = PROCESSING_STATUS_LABELS.get(processing_status, processing_status)

	return {
		"student": {
			"first_name": first_name,
			"last_name": last_name,
			"full_name": full_name,
			"email": str(lead.get("email") or lead.get("other_email") or ""),
			"phone": str(lead.get("phone") or ""),
			"interested_program": program_name,
		},
		"lead": {
			"source": _label("CRM Lead Source", lead.get("source"), "source_name"),
			"status": status,
			"campaign": campaign_name,
			"created_at": str(created_at or ""),
		},
		"owner": _user_context(),
		"school": {"name": school_name},
		"program": {
			"name": program_name,
			"link": "",
			"interest_area": program_name,
			"career_direction": "",
		},
		"application": {
			"status": status,
			"next_step": "",
			"missing_documents": "",
			"link": "",
		},
		"event": {
			"name": "",
			"datetime": "",
			"location": "",
			"registration_link": "",
		},
		"tuition": {"amount": ""},
		"scholarship": {"name": "", "link": ""},
	}


def _context_value(context: dict[str, Any], token: str) -> str:
	value: Any = context
	for part in token.split("."):
		if not isinstance(value, dict):
			return ""
		value = value.get(part)
		if value is None:
			return ""
	return str(value)


def _resolve_tokens(
	value: str, context: dict[str, Any], *, escape_html: bool = False
) -> tuple[str, list[str]]:
	missing: set[str] = set()

	def replace(match: re.Match[str]) -> str:
		token = match.group(1).strip()
		resolved = _context_value(context, token)
		if not resolved:
			missing.add(token)
		return html.escape(resolved, quote=True) if escape_html else resolved

	return TOKEN_PATTERN.sub(replace, value), sorted(missing)


def _preview_contact_payload(row: Any) -> dict[str, str]:
	name = str(row.get("student_name") or row.get("name") or "").strip()
	code = str(row.get("lead_code") or row.get("name") or "").strip()
	label = f"{name} · {code}" if name and code and name != code else name or code
	return {
		"id": str(row.get("name") or ""),
		"label": label,
		"email": str(row.get("email") or row.get("other_email") or ""),
		"phone": str(row.get("phone") or ""),
	}


@frappe.whitelist()
def list_message_templates(
	search: str | None = None,
	owner: str | None = None,
	system_only: bool | int | str = False,
) -> dict[str, Any]:
	"""Return all templates visible to the authenticated user."""
	_require_authentication()
	filters: dict[str, Any] = {"is_system_template": 0}
	owner_value = str(owner or "").strip()
	if owner_value:
		filters["owner"] = owner_value
	if _is_truthy(system_only):
		filters["is_system_template"] = 1
		filters["is_public"] = 1
	search_value = str(search or "").strip()
	or_filters = None
	if search_value:
		like = f"%{search_value}%"
		or_filters = [[fieldname, "like", like] for fieldname in ("name", "template_name", "subject")]
	rows = frappe.get_list(
		MESSAGE_TEMPLATE,
		filters=filters,
		or_filters=or_filters,
		fields=list(MESSAGE_TEMPLATE_FIELDS),
		order_by=(
			"library_category asc, creation asc, name asc"
			if _is_truthy(system_only)
			else "modified desc, creation desc, name desc"
		),
		limit_page_length=0,
	)
	owner_cache: dict[str, str] = {}
	templates = [_payload(row, owner_cache) for row in rows]
	owners_by_id = {
		row["ownerId"]: {"id": row["ownerId"], "name": row["owner"]} for row in templates if row["ownerId"]
	}
	owners = sorted(
		owners_by_id.values(),
		key=lambda value: (value["name"].casefold(), value["id"]),
	)
	return {"templates": templates, "owners": owners, "total": len(templates)}


@frappe.whitelist()
def list_message_template_library() -> dict[str, Any]:
	"""Return active admin-managed templates available to users."""
	_require_authentication()
	rows = frappe.get_list(
		MESSAGE_TEMPLATE_LIBRARY,
		filters={"is_active": 1},
		fields=[
			"name",
			"template_name",
			"category",
			"description",
			"subject",
			"body",
			"is_active",
			"owner",
			"creation",
			"modified",
		],
		order_by="category asc, creation asc, name asc",
		limit_page_length=0,
	)
	owner_cache: dict[str, str] = {}
	templates = [_library_payload(row, owner_cache) for row in rows]
	return {"templates": templates, "owners": [], "total": len(templates)}


@frappe.whitelist()
def list_admin_message_template_library() -> dict[str, Any]:
	"""Return all library templates for the admin management screen."""
	_require_admin()
	rows = frappe.get_list(
		MESSAGE_TEMPLATE_LIBRARY,
		fields=[
			"name",
			"template_name",
			"category",
			"description",
			"subject",
			"body",
			"is_active",
			"owner",
			"creation",
			"modified",
		],
		order_by="modified desc, creation desc, name desc",
		limit_page_length=0,
	)
	owner_cache: dict[str, str] = {}
	templates = [_library_payload(row, owner_cache) for row in rows]
	return {"templates": templates, "owners": [], "total": len(templates)}


@frappe.whitelist()
def list_message_template_preview_contacts(
	search: str | None = None, page_length: int | str = 100
) -> dict[str, Any]:
	"""Return readable Leads for the real template preview contact selector."""
	_require_authentication()
	search_value = str(search or "").strip()
	try:
		limit = max(1, min(int(page_length or 100), 100))
	except (TypeError, ValueError):
		frappe.throw(_("page_length must be a positive integer."), frappe.ValidationError)
	or_filters = None
	if search_value:
		like = f"%{search_value}%"
		or_filters = [
			[fieldname, "like", like] for fieldname in ("name", "lead_code", "student_name", "email", "phone")
		]
	rows = frappe.get_list(
		"CRM Lead",
		fields=["name", "lead_code", "student_name", "email", "other_email", "phone"],
		or_filters=or_filters,
		order_by="modified desc, name desc",
		limit_page_length=limit,
	)
	contacts = [_preview_contact_payload(row) for row in rows]
	return {"contacts": contacts, "total": len(contacts)}


@frappe.whitelist(methods=["POST"])
def preview_message_template(lead_id: str, data: dict[str, Any] | str) -> dict[str, Any]:
	"""Resolve a draft template against one readable Lead without persisting changes."""
	_require_authentication()
	lead_name = str(lead_id or "").strip()
	if not lead_name:
		frappe.throw(_("Lead is required."), frappe.ValidationError)
	try:
		lead_name = resolve_lead_name(lead_name)
		doc = frappe.get_doc("CRM Lead", lead_name)
		doc.check_permission("read")
	except frappe.DoesNotExistError:
		frappe.throw(_("Lead not found."), frappe.DoesNotExistError)

	values = _normalize_preview_data(_parse_data(data))
	context = _preview_context(doc)
	subject, missing_subject = _resolve_tokens(values["subject"], context)
	expanded_body, missing_snippets = resolve_snippet_references(values["body"])
	body, missing_body = _resolve_tokens(expanded_body, context, escape_html=True)
	return {
		"lead": _preview_contact_payload(doc),
		"subject": subject,
		"body": body,
		"missingTokens": sorted(set(missing_subject + missing_body + missing_snippets)),
	}


@frappe.whitelist(methods=["POST"])
def create_message_template_library(data: dict[str, Any] | str) -> dict[str, Any]:
	_require_admin()
	values = _normalize_library_data(_parse_data(data))
	doc = frappe.get_doc(
		{
			"doctype": MESSAGE_TEMPLATE_LIBRARY,
			"naming_series": "MSG-LIB-.###",
			**values,
		}
	)
	doc.insert()
	return _library_payload(doc)


@frappe.whitelist(methods=["POST", "PUT"])
def update_message_template_library(
	name: str, data: dict[str, Any] | str, expected_modified: str | None = None
) -> dict[str, Any]:
	_require_admin()
	doc = frappe.get_doc(MESSAGE_TEMPLATE_LIBRARY, _document_name(name))
	doc.check_permission("write")
	_expected_modified(doc, expected_modified)
	for fieldname, value in _normalize_library_data(_parse_data(data), partial=True).items():
		doc.set(fieldname, value)
	doc.save()
	return _library_payload(doc)


@frappe.whitelist(methods=["DELETE", "POST"])
def delete_message_template_library(name: str, expected_modified: str | None = None) -> dict[str, Any]:
	_require_admin()
	doc = frappe.get_doc(MESSAGE_TEMPLATE_LIBRARY, _document_name(name))
	doc.check_permission("delete")
	_expected_modified(doc, expected_modified)
	doc.delete()
	return {"name": doc.name, "deleted": True}


@frappe.whitelist()
def get_message_template(name: str) -> dict[str, Any]:
	_require_authentication()
	doc = frappe.get_doc(MESSAGE_TEMPLATE, _document_name(name))
	doc.check_permission("read")
	return _payload(doc)


@frappe.whitelist(methods=["POST"])
def create_message_template(data: dict[str, Any] | str) -> dict[str, Any]:
	_require_authentication()
	values = _normalize_data(_parse_data(data))
	doc = frappe.get_doc(
		{
			"doctype": MESSAGE_TEMPLATE,
			"naming_series": "MSG-.###",
			**values,
		}
	)
	doc.insert()
	return _payload(doc)


@frappe.whitelist(methods=["POST", "PUT"])
def update_message_template(
	name: str, data: dict[str, Any] | str, expected_modified: str | None = None
) -> dict[str, Any]:
	_require_authentication()
	doc = frappe.get_doc(MESSAGE_TEMPLATE, _document_name(name))
	doc.check_permission("write")
	_expected_modified(doc, expected_modified)
	values = _normalize_data(_parse_data(data))
	for fieldname, value in values.items():
		doc.set(fieldname, value)
	doc.save()
	return _payload(doc)


@frappe.whitelist(methods=["DELETE", "POST"])
def delete_message_template(name: str, expected_modified: str | None = None) -> dict[str, Any]:
	_require_authentication()
	doc = frappe.get_doc(MESSAGE_TEMPLATE, _document_name(name))
	doc.check_permission("delete")
	_expected_modified(doc, expected_modified)
	doc.delete()
	return {"name": doc.name, "deleted": True}
