"""Additive, rerunnable Phase 8 conversion preflight and backfill."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable

try:
	import frappe
except ImportError:  # pragma: no cover
	frappe = None

from crm.fcrm.record_retention import persist_private_artifact, redacted_manifest


def classify_legacy_link(row: dict, *, student: dict | None, contact: dict | None) -> str:
	if row.get("identity_conflict"):
		return "identity_conflict"
	if row.get("student_conflict"):
		return "duplicate_student_contact"
	if not row.get("student"):
		return "unresolvable_no_student" if not student else "missing_student_link"
	if not student:
		return "missing_student"
	if not student.get("identity") or not student.get("case_key"):
		return "missing_identity_or_case_key"
	if student.get("intake_integrity_state") not in (None, "", "resolved"):
		return "student_integrity_quarantined"
	if student.get("identity_exists") is False:
		return "missing_identity"
	if student.get("identity_state") not in (None, "", "resolved", "active"):
		return "identity_quarantined"
	if student.get("case_key_exists") is False:
		return "missing_case_key"
	if student.get("case_key_state") not in (None, "", "resolved"):
		return "case_key_quarantined"
	if student.get("case_key_identity") not in (None, "", student.get("identity")):
		return "case_key_identity_mismatch"
	if student.get("canonical_student") not in (None, "", row.get("student")):
		return "non_canonical_case_key"
	if not contact:
		return "missing_contact"
	if contact.get("student_identity") and contact.get("student_identity") != student.get("identity"):
		return "identity_conflict"
	if student.get("lifecycle_stage") != "Enrolled":
		return "not_enrolled"
	return "backfillable"


def build_report(rows: Iterable[dict]) -> dict:
	rows = list(rows)
	identity_contacts = {}
	student_contacts = {}
	for row in rows:
		student = row.get("student_record") or {}
		identity = student.get("identity")
		if identity:
			identity_contacts.setdefault(identity, set()).add(row.get("name"))
			identity_contacts[identity].update(row.get("existing_identity_contacts") or [])
		if row.get("student"):
			student_contacts.setdefault(row.get("student"), set()).add(row.get("name"))
	items = []
	for row in rows:
		row = dict(row)
		student = row.get("student_record") or {}
		row["identity_conflict"] = bool(
			student.get("identity")
			and len(identity_contacts.get(student.get("identity"), set())) > 1
		)
		row["student_conflict"] = bool(
			row.get("student") and len(student_contacts.get(row.get("student"), set())) > 1
		)
		item = dict(row)
		item["classification"] = classify_legacy_link(
			row,
			student=row.get("student_record"),
			contact=row.get("contact_record"),
		)
		item.pop("student_record", None)
		item.pop("contact_record", None)
		item.pop("existing_identity_contacts", None)
		item.pop("identity_conflict", None)
		item.pop("student_conflict", None)
		items.append(item)
	counts = Counter(item["classification"] for item in items)
	return {"rows_checked": len(items), "counts": dict(sorted(counts.items())), "items": items}


def _legacy_rows():
	if frappe is None:
		raise RuntimeError("Phase 8 migration requires a Frappe bench")
	rows = frappe.db.get_all("CRM Contact", filters={"student": ["is", "set"]}, fields=["name", "student", "student_identity"])
	for row in rows:
		student = frappe.db.get_value(
			"CRM Student",
			row.get("student"),
			["name", "identity", "case_key", "lifecycle_stage", "intake_integrity_state"],
			as_dict=True,
		)
		if student:
			identity_exists = bool(
				student.identity
				and frappe.db.exists("CRM Student Identity", student.identity)
			)
			student["identity_exists"] = identity_exists
			student["identity_state"] = (
				frappe.db.get_value("CRM Student Identity", student.identity, "identity_status")
				if identity_exists
				else None
			)
			case = None
			if student.case_key and frappe.db.exists("CRM Student Case Key", student.case_key):
				case = frappe.db.get_value(
					"CRM Student Case Key",
					student.case_key,
					["identity", "canonical_student", "integrity_state"],
					as_dict=True,
				)
			student["case_key_exists"] = bool(case)
			student["case_key_identity"] = case.identity if case else None
			student["canonical_student"] = case.canonical_student if case else None
			student["case_key_state"] = case.integrity_state if case else None
		row["student_record"] = student
		row["contact_record"] = {"student_identity": row.get("student_identity")}
		row["existing_identity_contacts"] = (
			frappe.db.get_all(
				"CRM Contact",
				filters={"student_identity": student.identity},
				pluck="name",
				ignore_permissions=True,
			)
			if student and student.identity
			else []
		)
		yield row


def _persist_report(report: dict, *, mode: str = "dry_run"):
	if frappe is None:
		raise RuntimeError("Phase 8 migration requires a Frappe bench")
	artifact = {
		"kind": "student_contact_conversion_reconciliation",
		"mode": mode,
		"rows_checked": report["rows_checked"],
		"counts": report["counts"],
		"items": redacted_manifest(
			[{"name": item.get("name"), "classification": item.get("classification")} for item in report["items"]],
			safe_fields=("classification",),
		),
		"notes": "Preflight only; no source rows were mutated." if mode == "dry_run" else "Approved apply run.",
	}
	return persist_private_artifact(
		filename=f"student-contact-conversion-{mode}-{frappe.generate_hash(length=12)}.json",
		content=json.dumps(artifact, sort_keys=True, separators=(",", ":")),
	)


IDENTITY_UNIQUE_INDEX = "crm_contact_student_identity_uniq"


def _add_unique_identity_index() -> bool:
	"""Install the post-reconciliation identity fence idempotently."""
	if not frappe.db.table_exists("CRM Contact"):
		return False
	physical = "tabCRM Contact"
	if frappe.db.sql(f"SHOW INDEX FROM `{physical}` WHERE Key_name = %s", IDENTITY_UNIQUE_INDEX):
		return True
	duplicates = frappe.db.sql(
		f"""
		select `student_identity`, count(*) as row_count
		from `{physical}`
		where `student_identity` is not null and `student_identity` != ''
		group by `student_identity`
		having row_count > 1
		limit 1
		""",
		as_dict=True,
	)
	if duplicates:
		frappe.log_error(
			"Phase 8 identity unique index blocked by duplicate Contact identities.",
			"phase8_prepare_student_contact_conversion",
		)
		return False
	# Frappe Link fields may persist an empty string.  Normalize only blanks so
	# MariaDB's unique index retains the intended multiple-NULL semantics.
	frappe.db.sql(
		f"UPDATE `{physical}` SET `student_identity` = NULL WHERE `student_identity` = ''"
	)
	frappe.db.sql_ddl(
		f"ALTER TABLE `{physical}` ADD UNIQUE INDEX `{IDENTITY_UNIQUE_INDEX}` (`student_identity`)"
	)
	return True


def _apply_rows(rows: list[dict], report: dict) -> tuple[list[str], list[str]]:
	updated, skipped = [], []
	classifications = {item.get("name"): item.get("classification") for item in report["items"]}
	for row in rows:
		if classifications.get(row.get("name")) != "backfillable":
			skipped.append(row.get("name"))
			continue
		# Backfill only safe evidence; never overwrite identity or legacy source.
		if frappe.db.exists("CRM Student Contact Conversion", {"student": row.get("student")}):
			continue
		student_record = row.get("student_record") or {}
		identity = student_record.get("identity")
		case_key = student_record.get("case_key")
		previous_flags = {
			"contact_migration_service": getattr(frappe.flags, "contact_migration_service", False),
			"student_contact_conversion_service": getattr(frappe.flags, "student_contact_conversion_service", False),
		}
		frappe.flags.contact_migration_service = True
		frappe.flags.student_contact_conversion_service = True
		try:
			frappe.db.set_value("CRM Contact", row.get("name"), "student_identity", identity, update_modified=False)
			receipt_key = "legacy-conversion:" + hashlib.sha256(f"{row.get('student')}:{row.get('name')}".encode()).hexdigest()
			receipt = frappe.get_doc(
				{
					"doctype": "CRM Student Command Receipt",
					"receipt_key": receipt_key,
					"command_key": receipt_key,
					"command_kind": "conversion",
					"request_fingerprint": hashlib.sha256(f"legacy:{row.get('student')}:{row.get('name')}".encode()).hexdigest(),
					"outcome": "attached",
					"target_student": row.get("student"),
					"target_case_key": case_key,
					"target_contact": row.get("name"),
					"actor": getattr(getattr(frappe, "session", None), "user", None) or "Administrator",
					"scope_snapshot": json.dumps({"actor": "migration", "provenance": "legacy_migration"}),
					"policy_version": "phase8-conversion-v1",
					"schema_version": "phase8-v1",
					"correlation_token": receipt_key,
					"request_received_at": frappe.utils.now_datetime(),
					"completed_at": frappe.utils.now_datetime(),
					"result_json": json.dumps({"status": "attached", "student": row.get("student"), "contact": row.get("name")}),
				}
			).insert(ignore_permissions=True)
			frappe.get_doc(
				{
					"doctype": "CRM Student Contact Conversion",
					"student": row.get("student"),
					"student_identity": identity,
					"case_key": case_key,
					"contact": row.get("name"),
					"actor": getattr(getattr(frappe, "session", None), "user", None) or "Administrator",
					"actor_scope": json.dumps({"provenance": "legacy_migration"}),
					"converted_at": frappe.utils.now_datetime(),
					"command_receipt": receipt.name,
					"idempotency_key": receipt_key,
					"correlation_id": receipt_key,
					"policy_version": "phase8-conversion-v1",
					"schema_version": "phase8-v1",
				}
			).insert(ignore_permissions=True)
		finally:
			frappe.flags.contact_migration_service = previous_flags["contact_migration_service"]
			frappe.flags.student_contact_conversion_service = previous_flags["student_contact_conversion_service"]
		updated.append(row.get("name"))
	return updated, skipped


def execute():
	"""Registered patch: persist a dry-run report only.

	Mutation is deliberately separated into :func:`apply_migration`, which
	requires an explicit approval token and a privileged actor.  A site migrate
	must never create Contacts or append conversion history implicitly.
	"""
	rows = list(_legacy_rows())
	report = build_report(rows)
	reconciliation = _persist_report(report, mode="dry_run")
	return {
		**report,
		"reconciliation": reconciliation,
		"updated": [],
		"skipped": [row.get("name") for row in rows],
		"mode": "dry_run",
	}


def apply_migration(*, approval_token: str) -> dict:
	"""Explicitly apply a previously reviewed preflight report.

	The token is provisioned in site config by an operator after backup and
	reconciliation review.  It is intentionally not accepted by ``execute``.
	"""
	if frappe is None:
		raise RuntimeError("Phase 8 migration requires a Frappe bench")
	actor = getattr(getattr(frappe, "session", None), "user", None) or "Guest"
	roles = set(frappe.get_roles(actor))
	configured_token = getattr(frappe, "conf", {}).get("crm_phase8_conversion_migration_approval")
	if actor != "Administrator" and "System Manager" not in roles:
		raise frappe.PermissionError("Only a System Manager may apply the conversion migration.")
	if not configured_token or approval_token != configured_token:
		raise frappe.PermissionError("A matching migration approval token is required.")
	rows = list(_legacy_rows())
	report = build_report(rows)
	if any(item.get("classification") in {"identity_conflict", "duplicate_student_contact"} for item in report["items"]):
		return {
			**report,
			"reconciliation": _persist_report(report, mode="dry_run"),
			"updated": [],
			"skipped": [row.get("name") for row in rows],
			"mode": "dry_run",
			"blocked": "identity_collision",
		}
	if not _add_unique_identity_index():
		return {
			**report,
			"reconciliation": _persist_report(report, mode="dry_run"),
			"updated": [],
			"skipped": [row.get("name") for row in rows],
			"mode": "dry_run",
			"blocked": "identity_index_collision",
		}
	reconciliation = _persist_report(report, mode="apply")
	updated, skipped = _apply_rows(rows, report)
	return {**report, "reconciliation": reconciliation, "updated": updated, "skipped": skipped, "mode": "apply"}
