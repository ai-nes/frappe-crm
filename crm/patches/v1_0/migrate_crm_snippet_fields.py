"""Backfill CRM Snippet fields after separating name, text, and shortcut."""

from __future__ import annotations

import re
import unicodedata

import frappe

SNIPPET = "CRM Snippet"


def _fallback_shortcut(value: str, name: str) -> str:
	value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
	shortcut = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-._").lower()
	return shortcut or f"snippet-{name.lower().replace('-', '')}"


def execute():
	if not frappe.db.exists("DocType", SNIPPET):
		return

	fields = ["name", "internal_name", "snippet_text", "shortcut"]
	for fieldname in ("snippet_name", "content"):
		if frappe.db.has_column(SNIPPET, fieldname):
			fields.append(fieldname)

	rows = frappe.get_all(SNIPPET, fields=fields, limit_page_length=0, ignore_permissions=True)
	used_shortcuts: set[str] = set()
	for row in rows:
		internal_name = str(row.get("internal_name") or row.get("snippet_name") or row.name).strip()
		snippet_text = row.get("snippet_text") or row.get("content") or ""
		shortcut = str(row.get("shortcut") or "").strip().lstrip("#").strip()
		shortcut = shortcut or _fallback_shortcut(internal_name, row.name)
		base_shortcut = shortcut
		suffix = 2
		while shortcut.casefold() in used_shortcuts:
			shortcut = f"{base_shortcut}-{suffix}"
			suffix += 1
		used_shortcuts.add(shortcut.casefold())
		frappe.db.set_value(
			SNIPPET,
			row.name,
			{
				"internal_name": internal_name,
				"snippet_text": snippet_text,
				"shortcut": shortcut,
			},
			update_modified=False,
		)
