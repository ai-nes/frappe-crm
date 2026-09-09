"""Consolidate temporary Action revision logs into the current rows.

The live control plane already fences on the scalar revision/digest fields on
``CRM Action`` and ``CRM Action Item``. This migration makes those rows the
sole default authority, preserving only the newest verified historical
snapshot/package before removing the two temporary revision DocTypes.

The patch is registered in ``pre_model_sync``. That ordering converts old
event links before Frappe changes the field to an integer and makes the patch
safe for sites that already contain decision events.
"""

from __future__ import annotations

import json
from typing import Any

import frappe

from crm.fcrm.action_type_catalog import ACTION_TYPE_METADATA
from crm.fcrm.nba_canonical import action_definition_snapshot, canonical_digest

DEFINITION_DOCTYPE = "CRM Action Definition Revision"
PACKAGE_DOCTYPE = "CRM Action Revision"
_DEFINITION_FIELDS = (
	"display_name",
	"purpose",
	"default_channel",
	"allowed_actors",
	"requires_approval",
	"requires_parent_authority",
	"academic_constraint",
	"auto_execute",
	"enabled",
)
_ACTION_CONTROL_COLUMNS = {
	"definition_revision": "int(11) NOT NULL DEFAULT 1",
	"definition_digest": "varchar(140) NULL",
}


def execute():
	# This patch intentionally runs in ``pre_model_sync`` so the historical
	# revision tables still exist.  The normal control-plane patch is registered
	# in ``post_model_sync``; create only the two scalar columns needed for the
	# consolidation here so a fresh/older site cannot fail on an unknown column.
	_ensure_action_definition_columns()
	unreconciled = []
	unreconciled.extend(_backfill_action_definitions())
	unreconciled.extend(_backfill_action_packages())
	# Event references are part of the same fail-closed gate.  Do this while
	# the legacy revision tables still exist, and never coerce an unresolved
	# reference to NULL before those tables are removed.
	unreconciled.extend(_backfill_event_revisions())
	if unreconciled:
		_warn_skipped("migration", unreconciled)
		frappe.throw(
			"Action revision consolidation stopped: unverifiable history remains; "
			"repair or quarantine it before dropping the revision tables.",
			frappe.ValidationError,
		)
	_drop_revision_doctype(DEFINITION_DOCTYPE)
	_drop_revision_doctype(PACKAGE_DOCTYPE)
	if not getattr(frappe.flags, "in_test", False):
		frappe.db.commit()


def _ensure_action_definition_columns() -> None:
	"""Make pre-model-sync backfill independent of post-sync field creation."""
	if not frappe.db.table_exists("CRM Action"):
		return
	table = "tabCRM Action"
	for name, ddl in _ACTION_CONTROL_COLUMNS.items():
		if not _columns_exist(table, (name,)):
			frappe.db.sql_ddl(f"ALTER TABLE `{table}` ADD COLUMN `{name}` {ddl}")
	# The checked-in DocType already declares these fields as scalar values.  A
	# reload makes get_all/set_value aware of the temporary columns before the
	# framework's model sync performs the regular schema reconciliation.
	frappe.reload_doc("fcrm", "doctype", "crm_action")


def _json_object(value: Any) -> dict | None:
	if isinstance(value, str):
		try:
			value = json.loads(value)
		except (TypeError, ValueError):
			return None
	return value if isinstance(value, dict) else None


def _backfill_action_definitions() -> list[str]:
	if not frappe.db.table_exists("CRM Action") or not _columns_exist(
		"tabCRM Action", ("definition_revision", "definition_digest")
	):
		return []
	history = _latest_verified_definition_rows()
	skipped: list[str] = []
	rows = frappe.get_all(
		"CRM Action",
		fields=[
			"name", "code", "display_name", "action_type", "purpose", "default_channel",
			"allowed_actors", "requires_approval", "requires_parent_authority",
			"academic_constraint", "auto_execute", "enabled", "definition_revision",
			"definition_digest",
		],
		limit_page_length=0,
	)
	for row in rows:
		code = row.get("code") or row.get("name")
		category = ACTION_TYPE_METADATA.get(code or "", {}).get("category")
		current_snapshot = action_definition_snapshot({**row, "category": category})
		current_digest = canonical_digest(current_snapshot)
		current_revision = max(int(row.get("definition_revision") or 0), 1)
		current_is_verified = bool(row.get("definition_digest")) and row.get("definition_digest") == current_digest
		verified = history.get(row["name"])

		# A verified history row wins only when the current default is missing or
		# stale. A newer, internally consistent default row is never downgraded.
		if (
			verified
			and (not current_is_verified or current_revision <= verified["revision"])
			and verified["snapshot"].get("code") in {None, code}
			and verified["snapshot"].get("category") in {None, category}
		):
			updates = _definition_updates(verified["snapshot"])
			updates["definition_revision"] = max(current_revision, verified["revision"])
			updates["definition_digest"] = verified["digest"]
			frappe.db.set_value("CRM Action", row["name"], updates, update_modified=False)
			continue

		# Rows without a valid history entry still need a deterministic default
		# digest so new NBA evaluations do not fail closed for an unrelated reason.
		if row.get("definition_digest") != current_digest:
			frappe.db.set_value(
				"CRM Action",
				row["name"],
				{"definition_revision": current_revision, "definition_digest": current_digest},
				update_modified=False,
			)
	skipped.extend(_invalid_definition_rows())
	_warn_skipped("definition", skipped)
	return skipped


def _latest_verified_definition_rows() -> dict[str, dict]:
	if not frappe.db.table_exists(DEFINITION_DOCTYPE):
		return {}
	rows = frappe.db.sql(
		f"""SELECT action, revision, digest, snapshot
		FROM `tab{DEFINITION_DOCTYPE}`
		ORDER BY action, revision DESC, creation DESC""",
		as_dict=True,
	)
	latest: dict[str, dict] = {}
	for row in rows:
		if row.action in latest:
			continue
		snapshot = _json_object(row.snapshot)
		if not snapshot or not row.digest or canonical_digest(snapshot) != row.digest:
			continue
		latest[row.action] = {
			"revision": max(int(row.revision or 0), 1),
			"digest": row.digest,
			"snapshot": snapshot,
		}
	return latest


def _invalid_definition_rows() -> list[str]:
	"""Return history rows that were not eligible for promotion to defaults."""
	if not frappe.db.table_exists(DEFINITION_DOCTYPE):
		return []
	rows = frappe.db.sql(
		f"SELECT action, revision, digest, snapshot FROM `tab{DEFINITION_DOCTYPE}`",
		as_dict=True,
	)
	invalid: list[str] = []
	for row in rows:
		snapshot = _json_object(row.snapshot)
		if not snapshot or not row.digest or canonical_digest(snapshot) != row.digest:
			invalid.append(f"{row.action}@{row.revision}")
	return invalid


def _columns_exist(table: str, columns: tuple[str, ...]) -> bool:
	rows = frappe.db.sql(
		"SELECT column_name FROM information_schema.columns "
		"WHERE table_schema = DATABASE() AND table_name = %s",
		(table,),
	)
	return set(columns).issubset({row[0] for row in rows})


def _definition_updates(snapshot: dict) -> dict[str, Any]:
	updates: dict[str, Any] = {}
	for fieldname in _DEFINITION_FIELDS:
		if fieldname not in snapshot:
			continue
		value = snapshot[fieldname]
		if fieldname in {"allowed_actors", "academic_constraint"}:
			value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
		updates[fieldname] = value
	return updates


def _backfill_action_packages() -> list[str]:
	if not frappe.db.table_exists(PACKAGE_DOCTYPE) or not frappe.db.table_exists("CRM Action Item"):
		return []
	rows = frappe.db.sql(
		f"""SELECT action, revision, package
		FROM `tab{PACKAGE_DOCTYPE}`
		ORDER BY action, revision DESC, creation DESC""",
		as_dict=True,
	)
	latest: dict[str, dict] = {}
	skipped: list[str] = []
	for row in rows:
		if row.action in latest:
			continue
		package = _json_object(row.package)
		if package is not None:
			latest[row.action] = {"revision": max(int(row.revision or 0), 0), "package": package}
		else:
			skipped.append(f"{row.action}@{row.revision}")
	if not latest:
		_warn_skipped("package", skipped)
		return skipped
	items = frappe.get_all(
		"CRM Action Item",
		fields=["name", "action", "action_type", "execution_package_version", "package_seed"],
		limit_page_length=0,
	)
	for item in items:
		candidate = latest.get(item.get("name"))
		if not candidate:
			continue
		if not _package_is_valid(item, candidate["package"]):
			skipped.append(f"{item.get('name')}@{candidate['revision']}")
			continue
		decision = _package_reconciliation(item, candidate["revision"])
		if decision == "preserve":
			continue
		if decision == "unreconciled":
			skipped.append(
				f"{item.get('name')}@current:{int(item.get('execution_package_version') or 0)}"
			)
			continue
		frappe.db.set_value(
			"CRM Action Item",
			item["name"],
			{"package_seed": candidate["package"], "execution_package_version": candidate["revision"]},
			update_modified=False,
		)
	_warn_skipped("package", skipped)
	return skipped


def _package_reconciliation(item: dict, candidate_revision: int) -> str:
	"""Return whether a current package is safe to preserve or promote over."""
	current = _json_object(item.get("package_seed"))
	current_revision = int(item.get("execution_package_version") or 0)
	# A newer current revision is authoritative only when its payload is valid;
	# never lower the CAS/version fence to an older historical row.
	if current_revision > candidate_revision:
		if current is not None and _package_is_valid(item, current):
			return "preserve"
		return "unreconciled"
	if current_revision == candidate_revision and current:
		return "preserve"
	return "promote"


def _package_is_valid(item: dict, package: dict) -> bool:
	"""Validate a historical package without rejecting advisory envelope keys."""
	action_code = item.get("action") or item.get("action_type")
	if action_code in {"CALL", "EMAIL", "SEND_EMAIL"}:
		from crm.services.sales_action_dispatch import validate_execution_package

		payload = {key: value for key, value in package.items() if key not in {"rationale", "package_version"}}
		try:
			validate_execution_package("EMAIL" if action_code == "SEND_EMAIL" else action_code, payload)
		except (TypeError, ValueError):
			return False
	return True


def _backfill_event_revisions() -> list[str]:
	if not frappe.db.table_exists("CRM Student Decision Event"):
		return []
	definition_names: dict[str, int] = {}
	if frappe.db.table_exists(DEFINITION_DOCTYPE):
		definition_names = {
			row["name"]: int(row["revision"] or 0)
			for row in frappe.db.sql(
				f"SELECT name, revision FROM `tab{DEFINITION_DOCTYPE}`", as_dict=True
			)
		}
	action_revisions = {
		row["name"]: int(row["definition_revision"] or 0)
		for row in frappe.get_all("CRM Action", fields=["name", "definition_revision"], limit_page_length=0)
	}
	unresolved: list[str] = []
	for event in frappe.get_all(
		"CRM Student Decision Event",
		fields=["name", "action_definition_revision", "action"],
		limit_page_length=0,
	):
		value = event.get("action_definition_revision")
		action_code = None
		if event.get("action") and frappe.db.table_exists("CRM Action Item"):
			action_code = frappe.db.get_value("CRM Action Item", event.action, "action")
		revision = _resolve_event_revision(value, definition_names, action_code, action_revisions)
		if revision is None:
			unresolved.append(f"{event.name}:{value or 'missing'}")
			continue
		frappe.db.set_value(
			"CRM Student Decision Event",
			event.name,
			"action_definition_revision",
			revision,
			update_modified=False,
		)
	return unresolved


def _resolve_event_revision(
	value: Any,
	definition_names: dict[str, int],
	action_code: str | None,
	action_revisions: dict[str, int],
) -> int | None:
	"""Resolve one legacy event reference without inventing a revision."""
	raw_value = str(value or "").strip()
	if raw_value.isdigit():
		return int(raw_value)
	if raw_value and raw_value in definition_names:
		return definition_names[raw_value]
	if action_code:
		return action_revisions.get(action_code)
	return None


def _drop_revision_doctype(doctype: str) -> None:
	if frappe.db.table_exists(doctype):
		frappe.db.sql_ddl(f"DROP TABLE `tab{doctype}`")
	if frappe.db.exists("DocType", doctype):
		frappe.db.delete("DocType", {"name": doctype})
	frappe.clear_cache(doctype=doctype)


def _warn_skipped(kind: str, rows: list[str]) -> None:
	if not rows:
		return
	frappe.log_error(
		message=(
			f"Action revision consolidation skipped {len(rows)} unverifiable {kind} row(s): "
			+ ", ".join(rows[:50])
		),
		title="NBA action revision consolidation",
	)
