"""Permission-aware CRUD APIs for Lead Sale snippets."""

from __future__ import annotations

import re
from typing import Any

import frappe
from frappe import _

SNIPPET = "CRM Snippet"
SNIPPET_FIELDS = (
	"name",
	"snippet_name",
	"is_public",
	"owner",
	"creation",
	"modified",
	"content",
)
SNIPPET_DATA_FIELDS = frozenset({"name", "content", "sharing"})
SNIPPET_REFERENCE_PATTERN = re.compile(r"#\(\s*([^()\r\n]+?)\s*\)|#([A-Za-z0-9][A-Za-z0-9_.-]*)")


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
		"snippet_name": _text(data.get("name"), _("Snippet name")),
		"content": _text(data.get("content"), _("Content")),
		"is_public": 1 if _sharing_value(data.get("sharing")) == "public" else 0,
	}


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
		"name": row.get("snippet_name"),
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

	def find_snippet(snippet_name: str) -> Any | None:
		if snippet_name in cache:
			return cache[snippet_name]

		rows = frappe.get_list(
			SNIPPET,
			or_filters=[
				["snippet_name", "=", snippet_name],
				["name", "=", snippet_name],
			],
			fields=["name", "snippet_name", "owner", "content"],
			order_by="modified desc, creation desc, name desc",
			limit_page_length=0,
		)
		actor = frappe.session.user
		owned = [row for row in rows if str(row.get("owner") or "") == actor]
		cache[snippet_name] = (owned or rows or [None])[0]
		return cache[snippet_name]

	def replace(match: re.Match[str]) -> str:
		snippet_name = (match.group(1) or match.group(2) or "").strip()
		snippet = find_snippet(snippet_name)
		if not snippet:
			missing.add(match.group(0))
			return match.group(0)
		return str(snippet.get("content") or "")

	return SNIPPET_REFERENCE_PATTERN.sub(replace, value), sorted(missing)


@frappe.whitelist()
def list_snippets(
	search: str | None = None,
	owner: str | None = None,
	sharing: str | None = None,
) -> dict[str, Any]:
	"""Return snippets visible to the authenticated user."""
	_require_authentication()
	filters: dict[str, Any] = {}
	owner_value = str(owner or "").strip()
	if owner_value:
		filters["owner"] = owner_value
	sharing_value = str(sharing or "").strip().lower()
	if sharing_value:
		if sharing_value not in {"public", "private"}:
			frappe.throw(_("Sharing must be either public or private."), frappe.ValidationError)
		filters["is_public"] = 1 if sharing_value == "public" else 0
	search_value = str(search or "").strip()
	or_filters = None
	if search_value:
		like = f"%{search_value}%"
		or_filters = [[fieldname, "like", like] for fieldname in ("name", "snippet_name", "content")]
	rows = frappe.get_list(
		SNIPPET,
		filters=filters,
		or_filters=or_filters,
		fields=list(SNIPPET_FIELDS),
		order_by="modified desc, creation desc, name desc",
		limit_page_length=0,
	)
	owner_cache: dict[str, str] = {}
	snippets = [_payload(row, owner_cache) for row in rows]
	owners_by_id = {
		row["ownerId"]: {"id": row["ownerId"], "name": row["owner"]} for row in snippets if row["ownerId"]
	}
	owners = sorted(
		owners_by_id.values(),
		key=lambda value: (value["name"].casefold(), value["id"]),
	)
	return {"snippets": snippets, "owners": owners, "total": len(snippets)}


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
	for fieldname, value in _normalize_data(_parse_data(data)).items():
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
