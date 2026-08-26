"""Create a redacted, private preflight manifest before technical-record retirement."""

from __future__ import annotations

import json
from collections import Counter

try:
	import frappe
except ImportError:  # pragma: no cover - pure manifest tests run outside bench
	frappe = None

from crm.fcrm.record_retention import persist_private_artifact, redacted_manifest


RETIRED_DOCTYPES = (
	"CRM Student Routing Request",
	"CRM Student SLA Delivery",
	"CRM Student SLA Delivery Attempt",
	"CRM Student Contact Conversion Reconciliation",
)


def build_manifest(rows_by_doctype: dict[str, list[dict]]) -> dict:
	"""Build a deterministic non-PII retirement preflight payload."""
	items = []
	for doctype in RETIRED_DOCTYPES:
		for row in rows_by_doctype.get(doctype, []):
			items.append({"name": row.get("name"), "doctype": doctype, "created": str(row.get("creation") or "")})
	return {
		"kind": "admissions_technical_record_retirement_preflight",
		"counts": dict(sorted(Counter(item["doctype"] for item in items).items())),
		"items": redacted_manifest(items, safe_fields=("doctype", "created")),
	}


def execute():
	"""Registered additive patch: report only. It neither deletes nor rewrites rows."""
	if frappe is None:
		raise RuntimeError("Technical-record consolidation requires a Frappe bench")
	rows_by_doctype = {
		doctype: frappe.get_all(doctype, fields=["name", "creation"], order_by="creation asc")
		for doctype in RETIRED_DOCTYPES
		if frappe.db.exists("DocType", doctype)
	}
	manifest = build_manifest(rows_by_doctype)
	artifact = persist_private_artifact(
		filename=f"admissions-technical-record-preflight-{frappe.generate_hash(length=12)}.json",
		content=json.dumps(manifest, sort_keys=True, separators=(",", ":")),
	)
	return {"artifact": artifact, **manifest}
