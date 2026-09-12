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
	"custom_values",
)
MESSAGE_TEMPLATE_DATA_FIELDS = frozenset({"name", "subject", "body", "sharing", "customValues"})
MESSAGE_TEMPLATE_LIBRARY_DATA_FIELDS = frozenset(
	{"name", "subject", "body", "category", "description", "isActive", "customValues"}
)
MESSAGE_TEMPLATE_PREVIEW_FIELDS = frozenset({"subject", "body", "customValues"})
TOKEN_PATTERN = re.compile(r"\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}")
MESSAGE_TEMPLATE_TOKEN_CATALOG = (
	{
		"id": "student-first-name",
		"value": "student.first_name",
		"label": "Tên",
		"group": "student",
		"groupLabel": "Học sinh",
		"sourceType": "database",
		"sourceDoctype": "CRM Student",
		"sourceField": "full_name",
	},
	{
		"id": "student-last-name",
		"value": "student.last_name",
		"label": "Họ",
		"group": "student",
		"groupLabel": "Học sinh",
		"sourceType": "database",
		"sourceDoctype": "CRM Student",
		"sourceField": "full_name",
	},
	{
		"id": "student-full-name",
		"value": "student.full_name",
		"label": "Họ và tên",
		"group": "student",
		"groupLabel": "Học sinh",
		"sourceType": "database",
		"sourceDoctype": "CRM Student",
		"sourceField": "full_name",
	},
	{
		"id": "student-email",
		"value": "student.email",
		"label": "Email",
		"group": "student",
		"groupLabel": "Học sinh",
		"sourceType": "database",
		"sourceDoctype": "CRM Student",
		"sourceField": "email",
	},
	{
		"id": "student-phone",
		"value": "student.phone",
		"label": "Số điện thoại",
		"group": "student",
		"groupLabel": "Học sinh",
		"sourceType": "database",
		"sourceDoctype": "CRM Student",
		"sourceField": "phone",
	},
	{
		"id": "student-interested-program",
		"value": "student.interested_program",
		"label": "Chương trình quan tâm",
		"group": "student",
		"groupLabel": "Học sinh",
		"sourceType": "database",
		"sourceDoctype": "CRM Student",
		"sourceField": "major",
	},
	{
		"id": "lead-source",
		"value": "lead.source",
		"label": "Nguồn",
		"group": "lead",
		"groupLabel": "Lead",
		"sourceType": "database",
		"sourceDoctype": "CRM Lead",
		"sourceField": "source",
	},
	{
		"id": "lead-status",
		"value": "lead.status",
		"label": "Trạng thái",
		"group": "lead",
		"groupLabel": "Lead",
		"sourceType": "database",
		"sourceDoctype": "CRM Lead",
		"sourceField": "processing_status",
	},
	{
		"id": "lead-campaign",
		"value": "lead.campaign",
		"label": "Chiến dịch",
		"group": "lead",
		"groupLabel": "Lead",
		"sourceType": "database",
		"sourceDoctype": "CRM Lead",
		"sourceField": "campaign",
	},
	{
		"id": "lead-created-at",
		"value": "lead.created_at",
		"label": "Ngày tạo",
		"group": "lead",
		"groupLabel": "Lead",
		"sourceType": "database",
		"sourceDoctype": "CRM Lead",
		"sourceField": "creation",
	},
	{
		"id": "sender-full-name",
		"value": "owner.full_name",
		"label": "Họ và tên",
		"group": "sender",
		"groupLabel": "Người gửi",
		"sourceType": "database",
		"sourceDoctype": "User",
		"sourceField": "full_name",
	},
	{
		"id": "sender-email",
		"value": "owner.email",
		"label": "Email",
		"group": "sender",
		"groupLabel": "Người gửi",
		"sourceType": "database",
		"sourceDoctype": "User",
		"sourceField": "email",
	},
	{
		"id": "sender-phone",
		"value": "owner.phone",
		"label": "Số điện thoại",
		"group": "sender",
		"groupLabel": "Người gửi",
		"sourceType": "database",
		"sourceDoctype": "User",
		"sourceField": "mobile_no",
	},
	{
		"id": "school-name",
		"value": "school.name",
		"label": "Tên trường",
		"group": "common",
		"groupLabel": "Thông tin chung",
		"sourceType": "admin_value",
		"adminValue": "Đại học FPT",
	},
	{
		"id": "program-name",
		"value": "program.name",
		"label": "Tên chương trình",
		"group": "custom",
		"groupLabel": "Thông tin nhập thêm",
		"sourceType": "context",
		"inputLabel": "Tên chương trình",
		"inputPlaceholder": "Ví dụ: Kỹ thuật phần mềm",
		"inputDescription": "Tên chương trình sẽ được chèn vào email.",
	},
	{
		"id": "program-link",
		"value": "program.link",
		"label": "Liên kết chương trình",
		"group": "custom",
		"groupLabel": "Thông tin nhập thêm",
		"sourceType": "context",
		"inputLabel": "Liên kết chương trình",
		"inputPlaceholder": "Dán liên kết chương trình",
		"inputDescription": "Người nhận có thể bấm vào liên kết này trong email.",
		"inputType": "url",
	},
	{
		"id": "program-interest-area",
		"value": "program.interest_area",
		"label": "Lĩnh vực quan tâm",
		"group": "program",
		"groupLabel": "Chương trình",
		"sourceType": "database",
		"sourceDoctype": "CRM Lead",
		"sourceField": "major",
	},
	{
		"id": "program-career-direction",
		"value": "program.career_direction",
		"label": "Định hướng nghề nghiệp",
		"group": "custom",
		"groupLabel": "Thông tin nhập thêm",
		"sourceType": "context",
		"inputLabel": "Định hướng nghề nghiệp",
		"inputPlaceholder": "Ví dụ: Phát triển phần mềm",
		"inputDescription": "Thông tin sẽ được chèn nguyên văn vào email.",
	},
	{
		"id": "application-status",
		"value": "application.status",
		"label": "Trạng thái hồ sơ",
		"group": "application",
		"groupLabel": "Hồ sơ",
		"sourceType": "database",
		"sourceDoctype": "CRM Lead",
		"sourceField": "processing_status",
	},
	{
		"id": "application-next-step",
		"value": "application.next_step",
		"label": "Bước tiếp theo",
		"group": "custom",
		"groupLabel": "Thông tin nhập thêm",
		"sourceType": "context",
		"inputLabel": "Bước tiếp theo",
		"inputPlaceholder": "Ví dụ: Hoàn tất hồ sơ trước 30/09",
		"inputDescription": "Hướng dẫn tiếp theo dành cho người nhận.",
	},
	{
		"id": "application-missing-documents",
		"value": "application.missing_documents",
		"label": "Hồ sơ còn thiếu",
		"group": "custom",
		"groupLabel": "Thông tin nhập thêm",
		"sourceType": "context",
		"inputLabel": "Hồ sơ còn thiếu",
		"inputPlaceholder": "Ví dụ: Bản sao CCCD, học bạ",
		"inputDescription": "Liệt kê các giấy tờ người nhận cần bổ sung.",
	},
	{
		"id": "application-link",
		"value": "application.link",
		"label": "Liên kết hồ sơ",
		"group": "custom",
		"groupLabel": "Thông tin nhập thêm",
		"sourceType": "context",
		"inputLabel": "Liên kết hồ sơ",
		"inputPlaceholder": "Dán liên kết hồ sơ",
		"inputDescription": "Liên kết mở trang hồ sơ hoặc bước đăng ký.",
		"inputType": "url",
	},
	{
		"id": "event-name",
		"value": "event.name",
		"label": "Tên sự kiện",
		"group": "custom",
		"groupLabel": "Thông tin nhập thêm",
		"sourceType": "context",
		"inputLabel": "Tên sự kiện",
		"inputPlaceholder": "Ví dụ: Open Day 2026",
		"inputDescription": "Tên sự kiện sẽ hiển thị trong email.",
	},
	{
		"id": "event-datetime",
		"value": "event.datetime",
		"label": "Thời gian sự kiện",
		"group": "custom",
		"groupLabel": "Thông tin nhập thêm",
		"sourceType": "context",
		"inputLabel": "Thời gian sự kiện",
		"inputPlaceholder": "Ví dụ: 09:00, ngày 20/09/2026",
		"inputDescription": "Nhập theo định dạng muốn gửi cho người nhận.",
	},
	{
		"id": "event-location",
		"value": "event.location",
		"label": "Địa điểm sự kiện",
		"group": "custom",
		"groupLabel": "Thông tin nhập thêm",
		"sourceType": "context",
		"inputLabel": "Địa điểm sự kiện",
		"inputPlaceholder": "Ví dụ: Campus Hoà Lạc",
		"inputDescription": "Địa điểm sẽ hiển thị trong email.",
	},
	{
		"id": "event-registration-link",
		"value": "event.link",
		"label": "Liên kết sự kiện",
		"group": "custom",
		"groupLabel": "Thông tin nhập thêm",
		"sourceType": "context",
		"inputLabel": "Liên kết đăng ký",
		"inputPlaceholder": "Dán liên kết đăng ký sự kiện",
		"inputDescription": "Người nhận có thể bấm vào để đăng ký.",
		"inputType": "url",
	},
	{
		"id": "tuition-amount",
		"value": "tuition.amount",
		"label": "Mức học phí",
		"group": "custom",
		"groupLabel": "Thông tin nhập thêm",
		"sourceType": "context",
		"inputLabel": "Mức học phí",
		"inputPlaceholder": "Ví dụ: 50.000.000 VNĐ",
		"inputDescription": "Nhập theo đúng cách bạn muốn hiển thị trong email.",
	},
	{
		"id": "scholarship-name",
		"value": "scholarship.name",
		"label": "Tên học bổng",
		"group": "custom",
		"groupLabel": "Thông tin nhập thêm",
		"sourceType": "context",
		"inputLabel": "Tên học bổng",
		"inputPlaceholder": "Ví dụ: Học bổng tài năng",
		"inputDescription": "Tên học bổng sẽ hiển thị trong email.",
	},
	{
		"id": "scholarship-link",
		"value": "scholarship.link",
		"label": "Liên kết học bổng",
		"group": "custom",
		"groupLabel": "Thông tin nhập thêm",
		"sourceType": "context",
		"inputLabel": "Liên kết học bổng",
		"inputPlaceholder": "Dán liên kết thông tin học bổng",
		"inputDescription": "Liên kết mở trang thông tin học bổng.",
		"inputType": "url",
	},
)
MESSAGE_TEMPLATE_TOKEN_BY_VALUE = {item["value"]: item for item in MESSAGE_TEMPLATE_TOKEN_CATALOG}
TEMPLATE_CUSTOM_VALUE_KEYS = frozenset(
	item["value"]
	for item in MESSAGE_TEMPLATE_TOKEN_CATALOG
	if item["sourceType"] in {"user_value", "context"}
)
PREVIEW_CONTEXT_TYPES = frozenset({"lead", "student"})
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


def _custom_values(value: Any, *, optional: bool = True) -> dict[str, str]:
	if value in (None, "") and optional:
		return {}
	if isinstance(value, str):
		try:
			value = frappe.parse_json(value)
		except (TypeError, ValueError):
			value = None
	if not isinstance(value, dict):
		frappe.throw(_("Custom template values must be an object."), frappe.ValidationError)
	unknown = set(value) - TEMPLATE_CUSTOM_VALUE_KEYS
	if unknown:
		frappe.throw(
			_("Unsupported custom template tokens: {0}.").format(", ".join(sorted(unknown))),
			frappe.ValidationError,
		)
	return {str(key): str(item or "") for key, item in value.items()}


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
		"custom_values": _custom_values(data.get("customValues")),
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
	if "customValues" in data:
		values["custom_values"] = _custom_values(data.get("customValues"))
	elif not partial:
		values["custom_values"] = {}
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
		"customValues": _custom_values(row.get("custom_values")),
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
		"customValues": _custom_values(row.get("custom_values")),
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


def _normalize_preview_data(data: dict[str, Any]) -> dict[str, Any]:
	unknown = set(data) - MESSAGE_TEMPLATE_PREVIEW_FIELDS
	if unknown:
		frappe.throw(
			_("Unsupported preview fields: {0}.").format(", ".join(sorted(unknown))),
			frappe.ValidationError,
		)
	return {
		"subject": _text(data.get("subject"), _("Subject")),
		"body": _text(data.get("body"), _("Body")),
		"customValues": _custom_values(data.get("customValues")),
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


def _set_context_value(context: dict[str, Any], token: str, value: Any) -> None:
	parts = token.split(".")
	current = context
	for part in parts[:-1]:
		child = current.get(part)
		if not isinstance(child, dict):
			return
		current = child
	current[parts[-1]] = str(value or "")


def _preview_context_type(value: Any, *, default: str = "lead") -> str:
	context_type = str(value or default).strip().lower()
	if context_type not in PREVIEW_CONTEXT_TYPES:
		frappe.throw(
			_("Preview context must be either Lead or Student."),
			frappe.ValidationError,
		)
	return context_type


def _preview_context(lead: Any | None = None, student: Any | None = None) -> dict[str, Any]:
	lead = lead or {}
	student = student or {}
	full_name = str(student.get("full_name") or lead.get("student_name") or "").strip()
	name_parts = full_name.split()
	first_name = name_parts[-1] if name_parts else ""
	last_name = " ".join(name_parts[:-1])
	processing_status = (
		str(lead.get("processing_status") or student.get("student_stage") or "").strip().upper()
	)
	created_at = lead.get("creation") or student.get("creation")
	if created_at:
		created_at = frappe.utils.get_datetime(created_at).strftime("%d/%m/%Y")
	campaign_name = _label("CRM Campaign", student.get("campaign") or lead.get("campaign"), "title")
	program_reference = (
		student.get("major") or student.get("aspiration") or lead.get("major") or lead.get("aspiration")
	)
	program_name = _label("CRM Major", program_reference, "major_name")
	program_name = program_name or str(program_reference or "")
	status = PROCESSING_STATUS_LABELS.get(processing_status, processing_status)

	context = {
		"student": {
			"first_name": first_name,
			"last_name": last_name,
			"full_name": full_name,
			"email": str(
				student.get("email")
				or student.get("other_email")
				or lead.get("email")
				or lead.get("other_email")
				or ""
			),
			"phone": str(student.get("phone") or lead.get("phone") or ""),
			"interested_program": program_name,
		},
		"lead": {
			"source": _label("CRM Lead Source", lead.get("source"), "source_name"),
			"status": status,
			"campaign": campaign_name,
			"created_at": str(created_at or ""),
		},
		"owner": _user_context(),
		"school": {"name": "Đại học FPT"},
		"program": {
			"name": "",
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
			"link": "",
		},
		"tuition": {"amount": ""},
		"scholarship": {"name": "", "link": ""},
	}
	for token in MESSAGE_TEMPLATE_TOKEN_CATALOG:
		if token["sourceType"] == "admin_value":
			_set_context_value(context, token["value"], token.get("adminValue", ""))
	return context


def _context_value(context: dict[str, Any], token: str) -> str:
	value: Any = context
	for part in token.split("."):
		if not isinstance(value, dict):
			return ""
		value = value.get(part)
		if value is None:
			return ""
	return str(value)


def _preview_fallback(token: str) -> str:
	definition = MESSAGE_TEMPLATE_TOKEN_BY_VALUE.get(token)
	if not definition or definition["sourceType"] != "context":
		return ""
	label = str(definition.get("label") or "")
	return f"[{label}]" if label else ""


def _resolve_tokens(
	value: str, context: dict[str, Any], *, escape_html: bool = False
) -> tuple[str, list[str]]:
	missing: set[str] = set()

	def replace(match: re.Match[str]) -> str:
		token = match.group(1).strip()
		resolved = _context_value(context, token)
		if not resolved:
			missing.add(token)
		resolved = resolved or _preview_fallback(token)
		return html.escape(resolved, quote=True) if escape_html else resolved

	return TOKEN_PATTERN.sub(replace, value), sorted(missing)


def _preview_contact_payload(row: Any, context_type: str = "lead") -> dict[str, str]:
	if context_type == "student":
		name = str(row.get("full_name") or row.get("name") or "").strip()
		code = str(row.get("name") or "").strip()
	else:
		name = str(row.get("student_name") or row.get("name") or "").strip()
		code = str(row.get("lead_code") or row.get("name") or "").strip()
	label = f"{name} · {code}" if name and code and name != code else name or code
	return {
		"id": str(row.get("name") or ""),
		"label": label,
		"email": str(row.get("email") or row.get("other_email") or ""),
		"phone": str(row.get("phone") or ""),
		"contextType": context_type,
	}


def _load_preview_records(reference: str, context_type: str) -> tuple[Any | None, Any | None]:
	if context_type == "student":
		if not frappe.db.exists("CRM Student", reference):
			frappe.throw(_("Student not found."), frappe.DoesNotExistError)
		student = frappe.get_doc("CRM Student", reference)
		student.check_permission("read")
		lead_name = student.get("source_lead") or student.get("student")
		lead = None
		if lead_name and frappe.db.exists("CRM Lead", lead_name):
			try:
				lead = frappe.get_doc("CRM Lead", lead_name)
				lead.check_permission("read")
			except frappe.PermissionError:
				lead = None
		return lead, student

	lead_name = resolve_lead_name(reference)
	if not lead_name or not frappe.db.exists("CRM Lead", lead_name):
		frappe.throw(_("Lead not found."), frappe.DoesNotExistError)
	lead = frappe.get_doc("CRM Lead", lead_name)
	lead.check_permission("read")
	student_name = (
		lead.get("converted_student")
		or lead.get("matched_student")
		or lead.get("student")
		or frappe.db.get_value("CRM Student", {"source_lead": lead.name}, "name")
	)
	student = None
	if student_name and frappe.db.exists("CRM Student", student_name):
		try:
			student = frappe.get_doc("CRM Student", student_name)
			student.check_permission("read")
		except frappe.PermissionError:
			student = None
	return lead, student


@frappe.whitelist()
def list_message_template_tokens() -> dict[str, Any]:
	"""Return the active personalization catalog used by template editors."""
	_require_authentication()
	return {
		"tokens": [dict(token) for token in MESSAGE_TEMPLATE_TOKEN_CATALOG],
		"total": len(MESSAGE_TEMPLATE_TOKEN_CATALOG),
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
			"custom_values",
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
			"custom_values",
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
	search: str | None = None,
	page_length: int | str = 100,
	context: str | None = None,
) -> dict[str, Any]:
	"""Return readable Lead or Student records for template preview."""
	_require_authentication()
	context_type = _preview_context_type(context)
	search_value = str(search or "").strip()
	try:
		limit = max(1, min(int(page_length or 100), 100))
	except (TypeError, ValueError):
		frappe.throw(_("page_length must be a positive integer."), frappe.ValidationError)
	or_filters = None
	if search_value:
		like = f"%{search_value}%"
		search_fields = (
			("name", "lead_code", "full_name", "email", "phone")
			if context_type == "student"
			else ("name", "lead_code", "student_name", "email", "phone")
		)
		or_filters = [[fieldname, "like", like] for fieldname in search_fields]
	doctype = "CRM Student" if context_type == "student" else "CRM Lead"
	fields = (
		["name", "lead_code", "full_name", "email", "other_email", "phone"]
		if context_type == "student"
		else ["name", "lead_code", "student_name", "email", "other_email", "phone"]
	)
	rows = frappe.get_list(
		doctype,
		fields=fields,
		or_filters=or_filters,
		order_by="modified desc, name desc",
		limit_page_length=limit,
	)
	contacts = [_preview_contact_payload(row, context_type) for row in rows]
	return {"contacts": contacts, "total": len(contacts), "contextType": context_type}


@frappe.whitelist(methods=["POST"])
def preview_message_template(
	lead_id: str | None = None,
	data: dict[str, Any] | str | None = None,
	context: str | None = None,
	record_id: str | None = None,
) -> dict[str, Any]:
	"""Resolve a draft template against one readable Lead or Student."""
	_require_authentication()
	context_type = _preview_context_type(context)
	reference = str(record_id or lead_id or "").strip()
	if not reference:
		frappe.throw(
			_("Student is required." if context_type == "student" else "Lead is required."),
			frappe.ValidationError,
		)
	lead, student = _load_preview_records(reference, context_type)

	values = _normalize_preview_data(_parse_data(data or {}))
	preview_context = _preview_context(lead, student)
	subject, missing_subject = _resolve_tokens(values["subject"], preview_context)
	expanded_body, missing_snippets = resolve_snippet_references(values["body"])
	body, missing_body = _resolve_tokens(expanded_body, preview_context, escape_html=True)
	record = student if context_type == "student" else lead
	return {
		"lead": _preview_contact_payload(record, context_type),
		"record": _preview_contact_payload(record, context_type),
		"contextType": context_type,
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
