"""Normalize legacy NBA actor labels to the canonical CRM role names.

Older production action rows used ``Lead Sales`` while the canonical role is
``Lead Sale``. The patch preserves actor order, removes duplicates, refreshes
the action definition digest/revision, and is safe to run more than once.
"""

from __future__ import annotations

import json

import frappe

LEGACY_ROLE = "Lead Sales"
CANONICAL_ROLE = "Lead Sale"


def execute():
	changed = False
	for doctype in ("CRM Action", "CRM Action Definition"):
		if not frappe.db.exists("DocType", doctype):
			continue
		for row in frappe.get_all(doctype, fields=["name", "allowed_actors"], limit_page_length=0):
			actors = _normalize_actors(row.get("allowed_actors"))
			if actors is None or LEGACY_ROLE not in actors:
				continue
			updated = []
			for actor in actors:
				actor = CANONICAL_ROLE if actor == LEGACY_ROLE else actor
				if actor not in updated:
					updated.append(actor)
			frappe.db.set_value(
				doctype,
				row["name"],
				"allowed_actors",
				json.dumps(updated, ensure_ascii=False),
				update_modified=False,
			)
			changed = True

	# The digest/revision is part of the NBA control plane and must describe the
	# normalized actor set, otherwise an action can pass the role check while its
	# immutable definition snapshot still advertises the legacy role.
	if changed and frappe.db.exists("DocType", "CRM Action Definition Revision"):
		from crm.patches.v1_0.add_nba_control_plane import _backfill_actions

		_backfill_actions()
	if changed and not getattr(frappe.flags, "in_test", False):
		frappe.db.commit()
		frappe.clear_cache()


def _normalize_actors(value) -> list[str] | None:
	if isinstance(value, str):
		try:
			value = json.loads(value)
		except (TypeError, ValueError):
			return None
	if not isinstance(value, (list, tuple)):
		return None
	return [str(actor).strip() for actor in value if str(actor).strip()]
