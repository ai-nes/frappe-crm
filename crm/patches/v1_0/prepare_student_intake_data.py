"""Prepare the Phase 3 Student intake topology.

The patch is deliberately conservative: a strong, valid national identifier and
an explicit admission cycle are required before an identity/case key is created.
Weak observations, malformed values, duplicate identity/cycle pairs, and
ambiguous ownership are quarantined for an explicit review.  No legacy Student
is merged, deleted, or silently selected as canonical.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import struct
import unicodedata
from collections import defaultdict

try:  # Keep the pure migration classifiers importable outside a bench process.
	import frappe
	from frappe.utils import now_datetime
except ImportError:  # pragma: no cover - only used by local unit tests
	frappe = None
	now_datetime = None


SCHEMA_VERSION = "phase3-v1"
KEY_VERSION = 1
STRONG_ID_PATTERN = re.compile(r"^(?:\d{9}|\d{12})$")


def normalize_identifier(value) -> str:
	"""Normalize an identifier without ever returning it in migration evidence."""
	if value is None:
		return ""
	value = unicodedata.normalize("NFKC", str(value)).strip().casefold()
	return re.sub(r"[\s.\-()]+", "", value)


def normalize_admission_year(value) -> str:
	"""Return only an explicit four-digit admission cycle."""
	value = normalize_identifier(value)
	return value if re.fullmatch(r"\d{4}", value) else ""


def encode_lookup_key(domain: str, *parts: str) -> bytes:
	"""Encode a domain-separated, length-delimited HMAC input."""
	values = [domain.encode("utf-8")]
	for part in parts:
		encoded = str(part).encode("utf-8")
		values.extend((struct.pack(">I", len(encoded)), encoded))
	return b"".join(values)


def keyed_digest(domain: str, *parts: str, key: bytes | None = None) -> str:
	"""Return a deterministic HMAC lookup token for migration/reindexing."""
	if key is None:
		if frappe is None:
			key = b"phase3-test-key"
		else:
			configured = frappe.conf.get("crm_identity_hmac_key") or frappe.conf.get("encryption_key")
			key = str(configured or frappe.local.site).encode("utf-8")
	return hmac.new(key, encode_lookup_key(domain, *parts), hashlib.sha256).hexdigest()


def _encrypt_identifier(value: str | None) -> str | None:
	"""Use Frappe's site encryption; never put normalized PII in audit fields."""
	if not value:
		return None
	try:
		from frappe.utils.password import encrypt

		return encrypt(value)
	except (ImportError, AttributeError):
		# Older Frappe versions encrypt Password fields during document insert.
		# Returning the value here would make that assumption unsafe, so leave the
		# reindex source empty rather than persist plaintext.
		return None


def classify_student(student: dict) -> str:
	"""Classify legacy input without making an identity decision from weak data."""
	cycle = normalize_admission_year(student.get("admission_year"))
	if not student.get("admission_year"):
		return "missing_admission_cycle"
	if not cycle:
		return "invalid_admission_cycle"

	national_id = normalize_identifier(student.get("id_number"))
	if not national_id:
		return "weak_only_shared_identifier" if student.get("phone") or student.get("email") else "missing_strong_identifier"
	if not STRONG_ID_PATTERN.fullmatch(national_id):
		return "malformed_national_id"
	return "resolvable"


def _student_is_active(student: dict) -> bool:
	stage = normalize_identifier(student.get("lifecycle_stage"))
	status = normalize_identifier(student.get("enrollment_status"))
	return stage != "lost" and status not in {"lost", "converted"}


def _ownership_issue(student: dict) -> str | None:
	"""Identify only an unowned active topology; owner wins over projections."""
	if not _student_is_active(student):
		return None
	owner = student.get("owner_staff") or student.get("assigned_to")
	pool = student.get("owning_team")
	if owner or pool:
		return None
	return "no_owner_or_pool"


def _redacted_fingerprint(student_name: str, category: str) -> str:
	return keyed_digest("crm.receipt.command.v1", "phase3-migration", student_name, category)


def _safe_exists(doctype: str, filters: dict) -> bool:
	try:
		return bool(frappe.db.exists(doctype, filters))
	except Exception:
		return False


def _ensure_review(student: dict, category: str) -> str | None:
	"""Create one durable, redacted review and receipt for a quarantined row."""
	if not frappe.db.table_exists("CRM Student Intake Review"):
		return None
	student_name = student["name"]
	fingerprint = _redacted_fingerprint(student_name, category)
	receipt_key = f"MIGRATION-{fingerprint[:32]}"
	review_key = f"MIGRATION-{fingerprint[:24]}"
	if _safe_exists("CRM Student Intake Review", {"review_key": review_key}):
		return review_key

	receipt = frappe.db.get_value("CRM Student Command Receipt", {"receipt_key": receipt_key}, "name")
	if not receipt:
		receipt_doc = frappe.get_doc(
			{
				"doctype": "CRM Student Command Receipt",
				"receipt_key": receipt_key,
				"command_kind": "review_decision",
				"command_key": fingerprint,
				"command_key_version": KEY_VERSION,
				"request_fingerprint": fingerprint,
				"outcome": "review_required",
				"actor": frappe.session.user or "Administrator",
				"scope_snapshot": {"source": "phase3_migration", "student": student_name},
				"policy_version": "phase2-v1",
				"schema_version": SCHEMA_VERSION,
				"correlation_token": fingerprint[:24],
				"request_received_at": now_datetime(),
			}
		)
		receipt_doc.insert(ignore_permissions=True)
		receipt = receipt_doc.name

	review_type = {
		"weak_only_shared_identifier": "malformed_identifier",
		"missing_strong_identifier": "malformed_identifier",
		"malformed_national_id": "malformed_identifier",
		"missing_admission_cycle": "missing_admission_cycle",
		"invalid_admission_cycle": "missing_admission_cycle",
		"duplicate_identity_cycle": "duplicate_case",
		"no_owner_or_pool": "ownership_topology",
	}.get(category, "identity_conflict")
	review_doc = frappe.get_doc(
		{
			"doctype": "CRM Student Intake Review",
			"review_key": review_key,
			"review_status": "open",
			"revision": 0,
			"review_type": review_type,
			"candidate_student": student_name,
			"source_receipt": receipt,
			"scope_anchor": student_name,
			"evidence_reference": f"phase3-migration:{fingerprint[:24]}",
			"correlation_token": fingerprint[:24],
			"reason_sensitivity": "operational",
		}
	)
	review_doc.insert(ignore_permissions=True)
	return review_doc.name


def _ensure_identity(student: dict, digest: str) -> str:
	identity = frappe.db.get_value("CRM Student Identity", {"strong_identifier_digest": digest}, "name")
	identity = identity or frappe.db.get_value(
		"CRM Student Identity", {"national_id_digest": digest}, "name"
	)
	if identity:
		return identity

	identity_key = f"ID-{digest[:32]}"
	identity = frappe.db.get_value("CRM Student Identity", {"identity_key": identity_key}, "name")
	if identity:
		return identity

	doc = frappe.get_doc(
		{
			"doctype": "CRM Student Identity",
			"identity_key": identity_key,
			"identity_status": "active",
			"strong_identifier_digest": digest,
			"strong_identifier_digest_version": KEY_VERSION,
			"national_id_digest": digest,
			"national_id_digest_version": KEY_VERSION,
			"source_system": "phase3-migration",
			"evidence_reference": f"phase3-migration:{digest[:24]}",
			"identifiers": [
				{
					"identifier_type": "national_id",
					"is_strong": 1,
					"keyed_digest": digest,
					"strong_keyed_digest": digest,
					"digest_version": KEY_VERSION,
					"encrypted_normalized_value": _encrypt_identifier(
						normalize_identifier(student.get("id_number"))
					),
					"lifecycle": "active",
					"evidence_reference": f"phase3-migration:{digest[:24]}",
				}
			],
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _append_weak_observations(student: dict, identity: str) -> None:
	"""Keep phone/email evidence as a multimap without using it for identity."""
	doc = frappe.get_doc("CRM Student Identity", identity)
	known = {
		(row.identifier_type, row.weak_keyed_digest)
		for row in doc.identifiers
		if row.identifier_type in {"phone", "email"} and row.weak_keyed_digest
	}
	changed = False
	for identifier_type in ("phone", "email"):
		normalized = normalize_identifier(student.get(identifier_type))
		if not normalized:
			continue
		digest = keyed_digest(
			f"crm.identity.weak.v{KEY_VERSION}", identifier_type, normalized
		)
		if (identifier_type, digest) in known:
			continue
		doc.append(
			"identifiers",
			{
				"identifier_type": identifier_type,
				"is_strong": 0,
				"keyed_digest": digest,
				"weak_keyed_digest": digest,
				"digest_version": KEY_VERSION,
				"encrypted_normalized_value": _encrypt_identifier(normalized),
				"lifecycle": "active",
				"evidence_reference": f"phase3-migration:{digest[:24]}",
			},
		)
		changed = True
	if changed:
		doc.save(ignore_permissions=True)


def _source_reference_history(student_name: str) -> str:
	return json.dumps(
		[
			{"student": student_name, "kind": "legacy_source", "schema_version": SCHEMA_VERSION}
		],
		ensure_ascii=False,
		separators=(",", ":"),
	)


def _ensure_case_key(student: dict, identity: str, cycle: str) -> str:
	case_key = f"CK-{identity}-{cycle}"[:140]
	existing = frappe.db.get_value("CRM Student Case Key", {"case_key": case_key}, "name")
	if existing:
		return existing
	doc = frappe.get_doc(
		{
			"doctype": "CRM Student Case Key",
			"case_key": case_key,
			"identity": identity,
			"admission_year": cycle,
			"canonical_student": student["name"],
			"source_student": student["name"],
			"source_reference_history": _source_reference_history(student["name"]),
			"integrity_state": "resolved",
			"schema_version": SCHEMA_VERSION,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _set_student(name: str, values: dict) -> None:
	frappe.db.set_value("CRM Student", name, values, update_modified=False)


def _add_unique_index(table: str, columns: tuple[str, ...], index_name: str) -> bool:
	"""Add an index only when the table is duplicate-free and rerun-safe."""
	if not frappe.db.table_exists(table):
		return False
	# ``table_exists`` accepts a DocType name, while raw MariaDB statements
	# address the physical ``tab...`` table.  Keep that translation explicit so
	# a partially completed migration can be retried safely.
	physical_table = table if table.startswith("tab") else f"tab{table}"
	existing = frappe.db.sql(
		f"SHOW INDEX FROM `{physical_table}` WHERE Key_name = %s", index_name, as_dict=True
	)
	if existing:
		return True
	column_sql = ", ".join(f"`{column}`" for column in columns)
	duplicates = frappe.db.sql(
		f"""
		SELECT {column_sql}, COUNT(*) AS `count`
		FROM `{physical_table}`
		GROUP BY {column_sql}
		HAVING `count` > 1
		LIMIT 1
		""",
		as_dict=True,
	)
	if duplicates:
		frappe.log_error(
			f"Phase 3 skipped {index_name}; duplicate canonical data remains",
			"prepare_student_intake_data",
		)
		return False
	frappe.db.sql_ddl(
		f"ALTER TABLE `{physical_table}` ADD UNIQUE INDEX `{index_name}` ({column_sql})"
	)
	return True


def execute():
	"""Backfill provable cases and quarantine every unresolved legacy row."""
	fields = [
		"name",
		"admission_year",
		"id_number",
		"phone",
		"email",
		"lifecycle_stage",
		"enrollment_status",
		"assigned_to",
		"owner_staff",
		"owning_team",
	]
	students = frappe.get_all("CRM Student", fields=fields, order_by="name asc")
	resolvable = {}
	groups = defaultdict(list)
	for student in students:
		category = classify_student(student)
		if category != "resolvable":
			continue
		cycle = normalize_admission_year(student["admission_year"])
		digest = keyed_digest(
			f"crm.identity.strong.v{KEY_VERSION}",
			normalize_identifier(student["id_number"]),
		)
		resolvable[student["name"]] = (cycle, digest)
		groups[(digest, cycle)].append(student["name"])

	result = {"resolved": [], "quarantined": [], "reviews": [], "duplicates": 0}
	for student in students:
		name = student["name"]
		category = classify_student(student)
		if category == "resolvable":
			cycle, digest = resolvable[name]
			if len(groups[(digest, cycle)]) > 1:
				category = "duplicate_identity_cycle"
			elif _ownership_issue(student):
				category = _ownership_issue(student)

		if category != "resolvable":
			review = _ensure_review(student, category)
			values = {
				"intake_integrity_state": "quarantined",
				"intake_quarantine_reason": category,
			}
			_set_student(name, values)
			result["quarantined"].append(name)
			if review:
				result["reviews"].append(review)
			if category == "duplicate_identity_cycle":
				result["duplicates"] += 1
			continue

		cycle, digest = resolvable[name]
		identity = _ensure_identity(student, digest)
		_append_weak_observations(student, identity)
		case_key = _ensure_case_key(student, identity, cycle)
		values = {
			"identity": identity,
			"case_key": case_key,
			"intake_integrity_state": "resolved",
			"intake_quarantine_reason": None,
		}
		# Keep one operational state.  A named owner wins over compatibility
		# projections; otherwise the existing named team remains the pool state.
		if student.get("owner_staff") or student.get("assigned_to"):
			values.update({"owner_staff": student.get("owner_staff") or student.get("assigned_to"), "owning_team": None})
		_set_student(name, values)
		result["resolved"].append(name)

	_add_unique_index(
		"CRM Student Case Key",
		("identity", "admission_year"),
		"crm_student_case_key_identity_cycle_uniq",
	)
	_add_unique_index(
		"CRM Student Identity Identifier",
		("identifier_type", "strong_keyed_digest"),
		"crm_student_identity_strong_digest_uniq",
	)
	_add_unique_index(
		"CRM Student Identity Identifier",
		("parent", "identifier_type", "weak_keyed_digest"),
		"crm_student_identity_weak_digest_uniq",
	)
	return result
