"""Read-only reconciliation helpers for governance evidence.

The registered patch calls ``build_report`` only. Applying a repair requires an
explicit operator command and a separate feature flag; site migration never
mutates governed values or audit history implicitly.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable


def classify_governed_row(row: dict) -> str:
	if not row.get("name"):
		return "missing_name"
	if not row.get("owner_role"):
		return "missing_owner"
	if row.get("approval_state") not in ("Approved", "Retired", "Proposed"):
		return "invalid_approval_state"
	if not row.get("version"):
		return "missing_version"
	if not row.get("effective_date"):
		return "missing_effective_date"
	return "ok"


def build_report(rows: Iterable[dict], *, registry_revision: str = "governance-registry") -> dict:
	items = []
	for row in rows:
		item = {
			"doctype": row.get("doctype"),
			"name": row.get("name"),
			"classification": classify_governed_row(row),
		}
		items.append(item)
	counts = Counter(item["classification"] for item in items)
	return {
		"schema_version": "governance-reconciliation",
		"registry_revision": registry_revision,
		"rows_checked": len(items),
		"counts": dict(sorted(counts.items())),
		"items": items,
		"write_mode": "dry_run",
	}


def collect_rows():
	try:
		import frappe
		from crm.fcrm.governed_reference_registry import governed_doctypes
	except ImportError as exc:  # pragma: no cover - requires a Frappe bench
		raise RuntimeError("Governance reconciliation requires a Frappe bench") from exc

	rows = []
	for doctype in governed_doctypes():
		if not frappe.db.exists("DocType", doctype):
			continue
		for row in frappe.db.get_all(
			doctype,
			fields=["name", "owner_role", "approval_state", "version", "effective_date"],
			ignore_permissions=True,
		):
			row["doctype"] = doctype
			rows.append(row)
	return rows


def execute(*, mode: str = "dry_run") -> dict:
	if mode != "dry_run":
		raise ValueError("Governance reconciliation is dry-run only until an explicit apply command is approved")
	return build_report(collect_rows())
