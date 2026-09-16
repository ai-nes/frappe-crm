"""Permission-aware CRUD APIs for Lead Sale snippets."""

from __future__ import annotations

import re
from typing import Any

import frappe
from frappe import _

SNIPPET = "CRM Snippet"
SNIPPET_FIELDS = (
	"name",
	"internal_name",
	"snippet_text",
	"shortcut",
	"is_public",
	"owner",
	"creation",
	"modified",
)
SNIPPET_DATA_FIELDS = frozenset({"internalName", "snippetText", "shortcut", "sharing"})
SNIPPET_REFERENCE_PATTERN = re.compile(r"#\(\s*([^()\r\n]+?)\s*\)|#([A-Za-z0-9][A-Za-z0-9_.-]*)")
DEFAULT_PAGE_SIZE = 5
MAX_PAGE_SIZE = 100


def _require_authentication() -> None:
	if not frappe.session.user or frappe.session.user == "Guest":
		frappe.throw(_("Authentication is required."), frappe.AuthenticationError)


def _parse_data(value: dict[str, Any] | str | None) -> dict[str, Any]:
	if isinstance(value, str):
		try:
			value = frappe.parse_json(value)
		except (TypeError, ValueError):
			value = None
	if not isinstance(value, dict):
		frappe.throw(_("Snippet data must be an object."), frappe.ValidationError)
	return value


def _text(value: Any, fieldname: str) -> str:
	result = str(value or "").strip()
	if not result:
		frappe.throw(_("{0} is required.").format(fieldname), frappe.ValidationError)
	return result


def _positive_integer(
	value: Any,
	fieldname: str,
	default: int,
	maximum: int | None = None,
) -> int:
	text = "" if value is None else str(value).strip()
	if not text:
		return default
	try:
		parsed = int(text)
	except (TypeError, ValueError):
		frappe.throw(_("{0} must be an integer.").format(fieldname), frappe.ValidationError)
	if parsed < 1 or (maximum is not None and parsed > maximum):
		frappe.throw(_("{0} is out of range.").format(fieldname), frappe.ValidationError)
	return parsed


def _sharing_value(value: Any) -> str:
	sharing = str(value or "public").strip().lower()
	if sharing not in {"public", "private"}:
		frappe.throw(_("Sharing must be either public or private."), frappe.ValidationError)
	return sharing


def _normalize_data(data: dict[str, Any]) -> dict[str, Any]:
	unknown = set(data) - SNIPPET_DATA_FIELDS
	if unknown:
		frappe.throw(
			_("Unsupported snippet fields: {0}.").format(", ".join(sorted(unknown))),
			frappe.ValidationError,
		)
	return {
		"internal_name": _text(data.get("internalName"), _("Internal name")),
		"snippet_text": _text(data.get("snippetText"), _("Snippet text")),
		"shortcut": _normalize_shortcut(data.get("shortcut")),
		"is_public": 1 if _sharing_value(data.get("sharing")) == "public" else 0,
	}


def _normalize_shortcut(value: Any) -> str:
	shortcut = str(value or "").strip().lstrip("#").strip()
	if not shortcut:
		frappe.throw(_("Shortcut is required."), frappe.ValidationError)
	if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", shortcut):
		frappe.throw(
			_("Shortcut may contain only letters, numbers, dots, underscores, and hyphens."),
			frappe.ValidationError,
		)
	return shortcut


def _ensure_shortcut_is_available(shortcut: str, current_name: str | None = None) -> None:
	existing_name = frappe.db.get_value(SNIPPET, {"shortcut": shortcut}, "name")
	if existing_name and existing_name != current_name:
		frappe.throw(_("Shortcut must be unique."), frappe.ValidationError)


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
		"internalName": row.get("internal_name") or "",
		"snippetText": row.get("snippet_text") or "",
		"shortcut": row.get("shortcut") or "",
		"ownerId": owner,
		"owner": _owner_name(owner, owner_cache),
		"sharing": "public" if frappe.utils.cint(row.get("is_public")) else "private",
		"createdAt": row.get("creation"),
		"modifiedAt": row.get("modified"),
		"content": row.get("content") or "",
		"canEdit": _can_edit(owner),
	}


def _expected_modified(doc: Any, expected_modified: str | None) -> None:
	if expected_modified and str(doc.modified) != str(expected_modified):
		frappe.throw(
			_("This snippet changed while you were editing it. Reload and try again."),
			frappe.ValidationError,
		)


def _document_name(name: Any) -> str:
	return _text(name, _("Snippet name"))


def resolve_snippet_references(value: str) -> tuple[str, list[str]]:
	"""Expand visible `#snippet-name` and legacy `#(snippet name)` references.

	The lookup uses ``frappe.get_list`` so DocType permission query conditions
	continue to protect private snippets during template previews.
	"""
	missing: set[str] = set()
	cache: dict[str, Any | None] = {}

	def find_snippet(snippet_name: str, *, allow_internal_name: bool) -> Any | None:
		cache_key = f"{snippet_name}|{allow_internal_name}"
		if cache_key in cache:
			return cache[cache_key]

		lookup_fields = [["shortcut", "=", snippet_name]]
		if allow_internal_name:
			lookup_fields.extend([["internal_name", "=", snippet_name], ["name", "=", snippet_name]])

		rows = frappe.get_list(
			SNIPPET,
			or_filters=lookup_fields,
			fields=["name", "internal_name", "shortcut", "owner", "snippet_text"],
			order_by="modified desc, creation desc, name desc",
			limit_page_length=0,
		)
		actor = frappe.session.user
		owned = [row for row in rows if str(row.get("owner") or "") == actor]
		cache[cache_key] = (owned or rows or [None])[0]
		return cache[cache_key]

	def replace(match: re.Match[str]) -> str:
		snippet_name = (match.group(1) or match.group(2) or "").strip()
		snippet = find_snippet(snippet_name, allow_internal_name=bool(match.group(1)))
		if not snippet:
			missing.add(match.group(0))
			return match.group(0)
		return str(snippet.get("snippet_text") or "")

	return SNIPPET_REFERENCE_PATTERN.sub(replace, value), sorted(missing)


def _count_snippets(filters: dict[str, Any], or_filters: list[list[str]] | None = None) -> int:
	rows = frappe.get_list(
		SNIPPET,
		filters=filters,
		or_filters=or_filters,
		fields=["name"],
		limit_page_length=0,
	)
	return len(rows)


def _owner_options(filters: dict[str, Any], owner_cache: dict[str, str]) -> list[dict[str, str]]:
	rows = frappe.get_list(
		SNIPPET,
		filters=filters,
		fields=["owner"],
		order_by="owner asc",
		limit_page_length=0,
	)
	owner_ids = {str(row.get("owner") or "") for row in rows}
	owner_ids.discard("")
	return [
		{"id": owner_id, "name": _owner_name(owner_id, owner_cache)}
		for owner_id in sorted(
			owner_ids,
			key=lambda value: (_owner_name(value, owner_cache).casefold(), value),
		)
	]


@frappe.whitelist()
def list_snippets(
	search: str | None = None,
	owner: str | None = None,
	sharing: str | None = None,
	scope: str | None = None,
	page: str | int = 1,
	pageSize: str | int = DEFAULT_PAGE_SIZE,
) -> dict[str, Any]:
	"""Return a permission-scoped, paginated snippet list."""
	_require_authentication()
	page_number = _positive_integer(page, "page", 1)
	page_size = _positive_integer(pageSize, "pageSize", DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE)
	actor = frappe.session.user
	scope_value = str(scope or "all").strip().lower()
	if scope_value not in {"all", "mine"}:
		frappe.throw(_("scope must be all or mine."), frappe.ValidationError)

	base_filters: dict[str, Any] = {}
	owner_value = str(owner or "").strip()
	if owner_value.lower() == "all":
		owner_value = ""
	sharing_value = str(sharing or "").strip().lower()
	if sharing_value and sharing_value != "all":
		if sharing_value not in {"public", "private"}:
			frappe.throw(_("Sharing must be either public or private."), frappe.ValidationError)
		base_filters["is_public"] = 1 if sharing_value == "public" else 0
	query_filters = dict(base_filters)
	if scope_value == "mine":
		query_filters["owner"] = actor
	elif owner_value:
		query_filters["owner"] = owner_value
	search_value = str(search or "").strip()
	or_filters = None
	if search_value:
		like = f"%{search_value}%"
		or_filters = [
			[fieldname, "like", like] for fieldname in ("name", "internal_name", "shortcut", "snippet_text")
		]
	total_all = _count_snippets(base_filters)
	total_mine = _count_snippets({**base_filters, "owner": actor})
	total = _count_snippets(query_filters, or_filters)
	total_pages = max(1, (total + page_size - 1) // page_size)
	owner_filters = dict(base_filters)
	if scope_value == "mine":
		owner_filters["owner"] = actor
	owner_cache: dict[str, str] = {}
	owners = _owner_options(owner_filters, owner_cache)
	rows = frappe.get_list(
		SNIPPET,
		filters=query_filters,
		or_filters=or_filters,
		fields=list(SNIPPET_FIELDS),
		order_by="modified desc, creation desc, name desc",
		limit_start=(page_number - 1) * page_size,
		limit_page_length=page_size,
	)
	snippets = [_payload(row, owner_cache) for row in rows]
	return {
		"snippets": snippets,
		"owners": owners,
		"total": total,
		"totalAll": total_all,
		"totalMine": total_mine,
		"page": page_number,
		"pageSize": page_size,
		"totalPages": total_pages,
		"hasNextPage": page_number < total_pages,
	}


@frappe.whitelist()
def get_snippet(name: str) -> dict[str, Any]:
	_require_authentication()
	doc = frappe.get_doc(SNIPPET, _document_name(name))
	doc.check_permission("read")
	return _payload(doc)


@frappe.whitelist(methods=["POST"])
def create_snippet(data: dict[str, Any] | str) -> dict[str, Any]:
	_require_authentication()
	values = _normalize_data(_parse_data(data))
	_ensure_shortcut_is_available(values["shortcut"])
	doc = frappe.get_doc({"doctype": SNIPPET, "naming_series": "SNP-.###", **values})
	doc.insert()
	return _payload(doc)


@frappe.whitelist(methods=["POST", "PUT"])
def update_snippet(
	name: str, data: dict[str, Any] | str, expected_modified: str | None = None
) -> dict[str, Any]:
	_require_authentication()
	doc = frappe.get_doc(SNIPPET, _document_name(name))
	doc.check_permission("write")
	_expected_modified(doc, expected_modified)
	values = _normalize_data(_parse_data(data))
	_ensure_shortcut_is_available(values["shortcut"], current_name=doc.name)
	for fieldname, value in values.items():
		doc.set(fieldname, value)
	doc.save()
	return _payload(doc)


@frappe.whitelist(methods=["DELETE", "POST"])
def delete_snippet(name: str, expected_modified: str | None = None) -> dict[str, Any]:
	_require_authentication()
	doc = frappe.get_doc(SNIPPET, _document_name(name))
	doc.check_permission("delete")
	_expected_modified(doc, expected_modified)
	doc.delete()
	return {"name": doc.name, "deleted": True}
