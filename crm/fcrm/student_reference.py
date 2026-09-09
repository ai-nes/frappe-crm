"""Canonical Lead/Student reference helpers for the admissions core."""

from __future__ import annotations

import re

import frappe

CANONICAL_FIELD = "crm_student"
HS_CODE_PREFIX = "HS"
_DISPLAY_CODE_RE = re.compile(
	r"^(?:CRM\s+)?HS-(?P<year>\d{4})-(?P<region>[A-Z0-9]+)-(?P<sequence>\d{1,6})$",
	re.IGNORECASE,
)
_LEGACY_CODE_RE = re.compile(
	r"^(?:ENR|LD)-(?P<year>\d{4})-(?P<sequence>\d{1,6})$",
	re.IGNORECASE,
)


def hs_code_for_reference(value: str | None, admission_year: str | int | None = None) -> str | None:
	"""Return the single public Student ID for a legacy or HS reference."""
	text = str(value or "").strip()
	if text.casefold().startswith("crm "):
		text = text[4:].strip()
	display = _DISPLAY_CODE_RE.fullmatch(text)
	if display:
		return (
			f"HS-{display.group('year')}-{display.group('region').upper()}-"
			f"{display.group('sequence')[-6:].zfill(6)}"
		)
	legacy = _LEGACY_CODE_RE.search(text)
	if legacy:
		year = str(admission_year or legacy.group("year"))
		return f"HS-{year}-HCM-{legacy.group('sequence')[-6:].zfill(6)}"
	return None


def next_hs_code(admission_year: str | int | None = None, region: str = "HCM") -> str:
	"""Allocate the next HS ID across Lead and Student tables.

	Lead and Student cases intentionally share one identifier namespace. The
	caller must still set the source link when creating the converted Student;
	this allocator is only for a new standalone record.
	"""
	year = str(admission_year or frappe.utils.now_datetime().year)
	region = re.sub(r"[^A-Z0-9]", "", str(region or "HCM").upper()) or "HCM"
	prefix = f"HS-{year}-{region}-"
	highest = 0
	for doctype in ("CRM Lead", "CRM Student"):
		if not frappe.db.table_exists(doctype):
			continue
		rows = frappe.db.sql(
			f"select name from `tab{doctype}` where name like %s",
			(f"{prefix}%",),
			as_dict=True,
		)
		for row in rows:
			match = re.search(r"-(\d+)$", str(row.get("name") or ""))
			if match:
				highest = max(highest, int(match.group(1)))
	return f"{prefix}{highest + 1:06d}"


def _display_code_for_lead(lead: str, admission_year: str | None = None) -> str | None:
	return hs_code_for_reference(lead, admission_year)


def student_for_lead(lead: str | None) -> str | None:
	if not lead or not frappe.db.exists("CRM Lead", lead):
		return None
	values = frappe.db.get_value("CRM Lead", lead, ["converted_student", "student"], as_dict=True) or {}
	return (
		values.get("converted_student")
		or values.get("student")
		or frappe.db.get_value("CRM Student", {"source_lead": lead}, "name")
		or frappe.db.get_value("CRM Student", {"student": lead}, "name")
	)


def lead_for_student(student: str | None) -> str | None:
	if not student or not frappe.db.exists("CRM Student", student):
		return None
	return frappe.db.get_value("CRM Student", student, "source_lead") or frappe.db.get_value(
		"CRM Student", student, "student"
	)


def lead_for_reference(value: str | None) -> str | None:
	"""Resolve a public student reference to the authoritative CRM Lead.

	The Lead name, canonical CRM Student name, and public display value now all
	use ``HS-YYYY-REGION-NNNNNN``. Accept historical ENR/LD/CRMC references at
	API boundaries while keeping new stored foreign keys on the HS identifier.
	"""
	text = str(value or "").strip()
	if not text:
		return None

	candidates = [text]
	if text.casefold().startswith("crm "):
		candidates.append(text[4:].strip())
	for candidate in candidates:
		if frappe.db.exists("CRM Lead", candidate):
			return candidate
		lead = frappe.db.get_value("CRM Lead", {"lead_code": candidate}, "name")
		if lead:
			return lead
		if frappe.db.exists("CRM Student", candidate):
			return lead_for_student(candidate)
	legacy_hs = hs_code_for_reference(text)
	if legacy_hs:
		for candidate in (legacy_hs,):
			if frappe.db.exists("CRM Lead", candidate):
				return candidate
			if frappe.db.exists("CRM Student", candidate):
				return lead_for_student(candidate)

	match = _DISPLAY_CODE_RE.fullmatch(text)
	if not match:
		return None

	normalized = hs_code_for_reference(text)
	if not normalized:
		return None
	# Keep this fast path for pre-cutover Lead names, then scan only the
	# admission cycle for older records.
	sequence = int(match.group("sequence"))
	lead = f"ENR-{match.group('year')}-{sequence:05d}"
	if match.group("region").upper() == "HCM" and frappe.db.exists("CRM Lead", lead):
		return lead
	for row in frappe.get_all(
		"CRM Lead",
		filters={"admission_year": match.group("year")},
		fields=["name", "lead_code", "admission_year"],
		limit_page_length=0,
	):
		for candidate in (row.get("name"), row.get("lead_code")):
			if candidate and _display_code_for_lead(candidate, row.get("admission_year")) == normalized:
				return row.get("name")
	return None


def sync_canonical_student(doc, method=None):
	"""Populate the canonical Student link while retaining legacy Lead aliases."""
	has_canonical_field = doc.meta.has_field(CANONICAL_FIELD)
	has_contact_field = doc.meta.has_field("crm_contact")
	has_student_contact_field = doc.meta.has_field("contact")
	if not has_canonical_field and not has_contact_field and not has_student_contact_field:
		return

	student = doc.get(CANONICAL_FIELD) or doc.get("crm_contact") or doc.get("contact")
	lead = doc.get("student")
	if not student and lead:
		student = student_for_lead(lead)
	if not student and doc.doctype == "CRM Intent" and doc.get("interaction"):
		student = frappe.db.get_value("CRM Interaction", doc.interaction, "crm_student")
		if not student:
			student = student_for_lead(frappe.db.get_value("CRM Interaction", doc.interaction, "student"))

	if student and not frappe.db.exists("CRM Student", student):
		frappe.throw(f"Canonical Student {student} does not exist.", frappe.ValidationError)
	if student:
		if has_canonical_field:
			doc.set(CANONICAL_FIELD, student)
		if has_contact_field and not doc.get("crm_contact"):
			doc.set("crm_contact", student)
		if has_student_contact_field and not doc.get("contact"):
			doc.set("contact", student)
		if doc.meta.has_field("student") and not doc.get("student"):
			legacy_lead = lead_for_student(student)
			if legacy_lead:
				doc.set("student", legacy_lead)


def canonical_student(value: str | None) -> str | None:
	"""Resolve a canonical Student ID from any supported student reference."""
	if not value:
		return None
	if frappe.db.exists("CRM Student", value):
		return value
	lead = lead_for_reference(value)
	return student_for_lead(lead)


def get_canonical_student_doc(reference: str | None, *, allow_legacy_lead: bool = True):
	"""Load Student first, with an explicit Lead fallback for old adapters."""
	student = canonical_student(reference)
	if student:
		return frappe.get_doc("CRM Student", student)
	if allow_legacy_lead and reference and frappe.db.exists("CRM Lead", reference):
		return frappe.get_doc("CRM Lead", reference)
	return None
