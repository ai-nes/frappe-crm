"""Shared domain rules for Student profiles and admission documents."""

from __future__ import annotations

from collections.abc import Iterable

import frappe
from frappe import _

from crm.fcrm.student_reference import canonical_student

TEMPLATE_PROFILE_TYPES = frozenset({"academic_admission", "enrollment"})
TEMPLATE_STATUSES = frozenset({"Draft", "Active", "Archived"})
PROFILE_STATUSES = frozenset({"Draft", "Active", "Completed", "Archived"})
REQUIREMENT_MODES = frozenset({"ALL", "ANY"})
ENROLLMENT_STATUSES = frozenset({"Not Started", "In Progress", "Eligible", "Enrolled", "Cancelled"})
DOCUMENT_STATUSES = frozenset({"Uploaded", "Verified", "Rejected", "Not Applicable"})
ACCEPTED_DOCUMENT_STATUSES = frozenset({"Uploaded", "Verified"})
DOCUMENT_CATEGORIES = frozenset(
	{"identity", "education", "photo", "payment", "scholarship", "language", "special_program"}
)
PAYMENT_ACCOUNT_PURPOSES = frozenset({"Tuition", "Refund", "Other"})
PAYMENT_ACCOUNT_VERIFICATION_STATUSES = frozenset({"Pending", "Verified", "Rejected"})

# A field may have one owner only. Keep this catalog small and explicit so a
# later UI/API layer cannot quietly introduce a second source of truth.
STUDENT_FIELD_OWNERS = {
	"full_name": "CRM Student",
	"date_of_birth": "CRM Student",
	"gender": "CRM Student",
	"birth_place": "CRM Student",
	"ethnicity": "CRM Student",
	"religion": "CRM Student",
	"nationality": "CRM Student",
	"contact_address": "CRM Student",
	"id_number": "CRM Student Identity",
	"phone": "CRM Student",
	"other_phone": "CRM Student",
	"email": "CRM Student",
	"province": "CRM Student",
	"ward": "CRM Student",
	"high_school": "CRM Student",
	"major": "CRM Student",
	"admission_year": "CRM Student",
	"branch": "CRM Student",
	"graduation_score": "CRM Student",
	"transcript_score": "CRM Student",
	"english_converted_score": "CRM Student",
	"total_score": "CRM Student",
	"parent_name": "CRM Student Guardian",
	"parent_phone": "CRM Student Guardian",
}

ADMISSION_FIELD_OWNERS = {
	"school_region": "CRM Student Admission Profile",
	"graduation_year": "CRM Student Admission Profile",
	"priority_group": "CRM Student Admission Profile",
	"graduation_classification": "CRM Student Admission Profile",
	"conduct_rank": "CRM Student Admission Profile",
	"exam_candidate_number": "CRM Student Admission Profile",
	"score_details": "CRM Student Admission Profile",
	"grade_12_gpa": "CRM Student Admission Profile",
	"encouragement_type": "CRM Student Admission Profile",
	"encouragement_score": "CRM Student Admission Profile",
	"priority_type": "CRM Student Admission Profile",
	"priority_score": "CRM Student Admission Profile",
	"registration_code": "CRM Admission Application",
	"registration_location": "CRM Admission Application",
	"direct_admission_type": "CRM Admission Application",
	"registration_step": "CRM Admission Application",
	"enrollment_status": "CRM Student Admission Profile",
	"profile_status": "CRM Student Admission Profile",
	"admission_category": "CRM Admission Application",
	"eligible_for_student_id": "CRM Student Admission Profile",
	"student_number": "CRM Student Admission Profile",
	"enrollment_registered_at": "CRM Student Admission Profile",
	"enrollment_reference": "CRM Student Admission Profile",
	"enrollment_note": "CRM Student Admission Profile",
	"supplemental_enrollment_reference": "CRM Student Admission Profile",
	"payment_type": "CRM Student Payment",
	"invoice_date": "CRM Student Payment",
	"recipient_account": "CRM Student Payment",
	"agreed_tuition_fee": "CRM Admission Application",
	"scholarship_type": "CRM Admission Application",
	"discount_type": "CRM Admission Application",
	"discount_percentage": "CRM Admission Application",
	"discount_amount": "CRM Admission Application",
	"is_region_1": "CRM Student Admission Profile",
	"hard_copy_code": "CRM Student Admission Profile",
	"is_first_generation": "CRM Student Admission Profile",
	"fe_affinity_discount": "CRM Student Admission Profile",
	"fe_affinity_discount_amount": "CRM Student Admission Profile",
	"english_admission_reference": "CRM Student Admission Profile",
	"portal_access_allowed": "CRM Student Admission Profile",
	"support_start_date": "CRM Student Admission Profile",
	"support_end_date": "CRM Student Admission Profile",
}

REQUIRED_COMMON_STUDENT_FIELDS = (
	"full_name",
	"date_of_birth",
	"gender",
	"phone",
	"email",
	"province",
	"ward",
	"high_school",
	"admission_year",
)

CONDITION_FIELDS = {
	"profile": frozenset(
		{
			"profile_type",
			"admission_year",
			"school_region",
			"graduation_year",
			"priority_group",
			"is_high_school_graduate",
			"enrollment_status",
			"is_region_1",
			"is_first_generation",
			"fe_affinity_discount",
			"english_admission_reference",
		}
	),
	"student": frozenset(
		{
			"education_program",
			"admission_year",
			"current_grade",
			"study_stage",
			"high_school",
			"major",
			"branch",
		}
	),
	"application": frozenset(
		{
			"admission_method",
			"admission_category",
			"scholarship_type",
			"discount_type",
			"direct_admission_type",
			"registration_step",
			"status",
		}
	),
}


def _value(document, fieldname):
	if hasattr(document, "get"):
		return document.get(fieldname)
	return getattr(document, fieldname, None)


def _is_non_empty(value) -> bool:
	return value is not None and str(value).strip() != ""


def _is_checked(value) -> bool:
	return str(value or "").strip().casefold() in {"1", "true", "yes"}


def _validate_condition_key(condition_key: str | None) -> None:
	key = str(condition_key or "").strip()
	if not key or key == "always":
		return
	if not key.startswith("field:") or "=" not in key:
		frappe.throw(
			_("Condition Key must use field:<source>.<field>=<value> format."), frappe.ValidationError
		)
	path, expected = key[6:].split("=", 1)
	if not expected.strip() or "." not in path:
		frappe.throw(
			_("Condition Key must include a source, field and expected value."), frappe.ValidationError
		)
	source, fieldname = path.split(".", 1)
	if source not in CONDITION_FIELDS or fieldname not in CONDITION_FIELDS[source]:
		frappe.throw(_("Condition Key references an unsupported field."), frappe.ValidationError)


def _condition_context(profile) -> dict[str, dict]:
	profile_fields = set(CONDITION_FIELDS["profile"])
	profile_context = {fieldname: _value(profile, fieldname) for fieldname in profile_fields}
	student_name = _value(profile, "student")
	student_context = {}
	if student_name:
		student_context = (
			frappe.db.get_value("CRM Student", student_name, list(CONDITION_FIELDS["student"]), as_dict=True)
			or {}
		)
	application_context = {}
	application_name = _value(profile, "application")
	if application_name:
		application_context = (
			frappe.db.get_value(
				"CRM Admission Application",
				application_name,
				list(CONDITION_FIELDS["application"]),
				as_dict=True,
			)
			or {}
		)
	return {
		"profile": profile_context,
		"student": student_context,
		"application": application_context,
	}


def _condition_applies(row, profile) -> bool:
	condition_key = str(_value(row, "condition_key") or "").strip()
	if not condition_key or condition_key == "always":
		return True
	_validate_condition_key(condition_key)
	path, expected = condition_key[6:].split("=", 1)
	source, fieldname = path.split(".", 1)
	actual = _condition_context(profile).get(source, {}).get(fieldname)
	if str(expected).strip().casefold() in {"true", "false"}:
		return _is_checked(actual) == (str(expected).strip().casefold() == "true")
	return str(actual or "").strip().casefold() == str(expected).strip().casefold()


def validate_profile_completeness(profile, *, strict: bool = True) -> list[str]:
	"""Return missing canonical Student fields and optionally fail closed."""
	student_name = _value(profile, "student")
	student = frappe.db.get_value(
		"CRM Student", student_name, list(REQUIRED_COMMON_STUDENT_FIELDS), as_dict=True
	)
	missing = []
	if not student:
		missing = list(REQUIRED_COMMON_STUDENT_FIELDS)
	else:
		missing = [
			fieldname
			for fieldname in REQUIRED_COMMON_STUDENT_FIELDS
			if not _is_non_empty(student.get(fieldname))
		]
	if strict and missing:
		frappe.throw(
			_("Student profile is missing required common fields: {0}.").format(", ".join(missing)),
			frappe.ValidationError,
		)
	return missing


def validate_profile_document_type_rows(profile) -> None:
	"""Validate the template junction's allowlist and deterministic ordering."""
	seen_types: set[str] = set()
	seen_orders: set[int] = set()
	groups: dict[str, dict] = {}
	for row in _value(profile, "document_types") or []:
		document_type = str(_value(row, "document_type") or "").strip()
		if not document_type:
			frappe.throw(_("Every profile template row requires a Document Type."), frappe.ValidationError)
		if document_type in seen_types:
			frappe.throw(
				_("Document Type {0} is duplicated in the template.").format(document_type),
				frappe.ValidationError,
			)
		seen_types.add(document_type)
		section_code = str(_value(row, "section_code") or "general").strip()
		if not section_code:
			frappe.throw(_("Every document requirement needs a section code."), frappe.ValidationError)
		requirement_mode = str(_value(row, "requirement_mode") or "ALL").strip().upper()
		if requirement_mode not in REQUIREMENT_MODES:
			frappe.throw(_("Requirement Mode must be ALL or ANY."), frappe.ValidationError)
		try:
			min_required = int(_value(row, "min_required") or 0)
			quantity = int(_value(row, "quantity") or 0)
			order_display = int(_value(row, "order_display") or 0)
		except (TypeError, ValueError):
			min_required = quantity = order_display = 0
		if min_required < 1:
			frappe.throw(_("min_required must be a positive integer."), frappe.ValidationError)
		if quantity < 1:
			frappe.throw(_("quantity must be a positive integer."), frappe.ValidationError)
		if requirement_mode == "ANY" and quantity != 1:
			frappe.throw(_("ANY requirements must use quantity 1."), frappe.ValidationError)
		_validate_condition_key(_value(row, "condition_key"))
		group_name = str(_value(row, "requirement_group") or f"document:{document_type}").strip()
		group = groups.setdefault(
			group_name,
			{
				"section_code": section_code,
				"mode": requirement_mode,
				"is_required": _is_checked(_value(row, "is_required")),
				"min_required": min_required,
				"rows": [],
			},
		)
		if (
			group["section_code"] != section_code
			or group["mode"] != requirement_mode
			or group["is_required"] != _is_checked(_value(row, "is_required"))
			or group["min_required"] != min_required
		):
			frappe.throw(
				_("Rows in one requirement group must share section, mode and required settings."),
				frappe.ValidationError,
			)
		group["rows"].append(row)
		try:
			order_display = int(_value(row, "order_display") or 0)
		except (TypeError, ValueError):
			order_display = 0
		if order_display < 1:
			frappe.throw(_("order_display must be a positive integer."), frappe.ValidationError)
		if order_display in seen_orders:
			frappe.throw(_("order_display values must be unique within a template."), frappe.ValidationError)
		seen_orders.add(order_display)
		status = frappe.db.get_value(
			"CRM Document Type", document_type, ["status", "is_active"], as_dict=True
		)
		if not status or status.status != "Active" or not status.is_active:
			frappe.throw(
				_("Document Type {0} must be active before assignment.").format(document_type),
				frappe.ValidationError,
			)
	for group_name, group in groups.items():
		if group["mode"] == "ANY" and group["min_required"] > len(group["rows"]):
			frappe.throw(
				_("Requirement group {0} has min_required greater than its alternatives.").format(group_name),
				frappe.ValidationError,
			)


def allowed_document_types(profile) -> set[str]:
	return {
		str(_value(row, "document_type"))
		for row in _document_type_rows(profile)
		if _is_non_empty(_value(row, "document_type")) and _condition_applies(row, profile)
	}


def _document_type_rows(profile):
	rows = _value(profile, "document_types")
	if rows:
		return _sort_document_type_rows(rows)
	template_name = _value(profile, "profile_template")
	if not template_name:
		return []
	return _sort_document_type_rows(
		frappe.get_doc("CRM Admission Profile Template", template_name).get("document_types") or []
	)


def _sort_document_type_rows(rows):
	def sort_key(row):
		try:
			order_display = int(_value(row, "order_display") or 0)
		except (TypeError, ValueError):
			order_display = 0
		return order_display, str(_value(row, "document_type") or "")

	return sorted(rows, key=sort_key)


def calculate_document_completeness(profile) -> dict:
	"""Calculate ALL/ANY checklist completion without placeholder documents."""
	groups: dict[str, dict] = {}
	for row in _document_type_rows(profile):
		if not _condition_applies(row, profile) or not _is_non_empty(_value(row, "document_type")):
			continue
		group_name = str(
			_value(row, "requirement_group") or f"document:{_value(row, 'document_type')}"
		).strip()
		groups.setdefault(
			group_name,
			{
				"section_code": str(_value(row, "section_code") or "general").strip(),
				"mode": str(_value(row, "requirement_mode") or "ALL").strip().upper(),
				"is_required": _is_checked(_value(row, "is_required")),
				"min_required": int(_value(row, "min_required") or 1),
				"rows": [],
			},
		)["rows"].append(row)
	if not groups or not _value(profile, "name"):
		return {"total": 0, "completed": 0, "missing": [], "groups": []}
	document_types = {str(_value(row, "document_type")) for group in groups.values() for row in group["rows"]}
	document_rows = frappe.get_all(
		"CRM Student Document",
		filters={
			"student_admission_profile": _value(profile, "name"),
			"document_type": ["in", list(document_types)],
		},
		fields=["document_type", "version", "status", "name"],
		ignore_permissions=True,
	)
	latest_documents = {}
	for row in document_rows:
		document_type = row.get("document_type")
		previous = latest_documents.get(document_type)
		if not previous or (int(row.get("version") or 0), row.get("name")) > (
			int(previous.get("version") or 0),
			previous.get("name"),
		):
			latest_documents[document_type] = row
	latest_accepted = {
		document_type: row
		for document_type, row in latest_documents.items()
		if row.get("status") in ACCEPTED_DOCUMENT_STATUSES
	}
	total = 0
	completed = 0
	missing = []
	group_results = []
	for group_name, group in groups.items():
		if not group["is_required"]:
			group_total = group_completed = 0
			group_missing = []
		elif group["mode"] == "ANY":
			group_total = group["min_required"]
			group_completed = min(
				group_total,
				sum(1 for row in group["rows"] if _value(row, "document_type") in latest_accepted),
			)
			group_missing = [] if group_completed >= group_total else [group_name]
		else:
			required_rows = [row for row in group["rows"] if _is_checked(_value(row, "is_required"))]
			group_total = sum(int(_value(row, "quantity") or 1) for row in required_rows)
			group_completed = sum(
				1 for row in required_rows if _value(row, "document_type") in latest_accepted
			)
			group_missing = [
				str(_value(row, "document_type"))
				for row in required_rows
				if _value(row, "document_type") not in latest_accepted
			]
		total += group_total
		completed += group_completed
		missing.extend(group_missing)
		group_results.append(
			{
				"group": group_name,
				"section_code": group["section_code"],
				"mode": group["mode"],
				"total": group_total,
				"completed": group_completed,
				"missing": group_missing,
				"document_types": [str(_value(row, "document_type")) for row in group["rows"]],
				"instruction": str(_value(group["rows"][0], "instruction") or "").strip(),
			}
		)
	return {"total": total, "completed": completed, "missing": missing, "groups": group_results}


def refresh_document_completeness(profile_name: str) -> dict:
	profile = frappe.get_doc("CRM Student Admission Profile", profile_name)
	completeness = calculate_document_completeness(profile)
	profile.db_set("document_completeness", frappe.as_json(completeness), update_modified=False)
	return completeness


def validate_student_document_ownership(document) -> None:
	profile_name = _value(document, "student_admission_profile")
	student_name = _value(document, "student")
	if not profile_name or not student_name:
		frappe.throw(_("Student and Student Admission Profile are required."), frappe.ValidationError)
	profile = frappe.db.get_value(
		"CRM Student Admission Profile", profile_name, ["student", "profile_status"], as_dict=True
	)
	if not profile or profile.student != student_name:
		frappe.throw(
			_("Student Document does not belong to the selected Student profile."), frappe.ValidationError
		)
	if profile.profile_status == "Archived":
		frappe.throw(_("Archived Student profiles cannot receive new documents."), frappe.ValidationError)
	document_type = _value(document, "document_type")
	profile_doc = frappe.get_doc("CRM Student Admission Profile", profile_name)
	if document_type not in allowed_document_types(profile_doc):
		frappe.throw(
			_("Document Type is not allowed by the selected Student profile."), frappe.ValidationError
		)
	requires_file = _value(document, "status") != "Not Applicable"
	if requires_file and not _is_non_empty(_value(document, "file")):
		frappe.throw(_("A private file is required for a Student Document."), frappe.ValidationError)
	if _is_non_empty(_value(document, "file")) and not _value(document, "is_private"):
		frappe.throw(_("Student admission files must be private."), frappe.PermissionError)
	file_name = (
		frappe.db.get_value("File", {"file_url": _value(document, "file")}, "name")
		if _is_non_empty(_value(document, "file"))
		else None
	)
	if file_name:
		is_private = frappe.db.get_value("File", file_name, "is_private")
		if is_private in (0, "0", False):
			frappe.throw(_("Student admission files must be private."), frappe.PermissionError)


def can_verify_student_document(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return user == "Administrator" or bool(
		set(frappe.get_roles(user)) & {"System Manager", "Admissions Director"}
	)


def validate_unique_primary_account(account) -> None:
	if not _value(account, "is_primary"):
		return
	filters = {
		"student": _value(account, "student"),
		"account_purpose": _value(account, "account_purpose") or "Other",
		"is_primary": 1,
	}
	if _value(account, "name"):
		filters["name"] = ["!=", _value(account, "name")]
	if frappe.db.exists("CRM Student Payment Account", filters):
		frappe.throw(
			_("Only one primary payment account is allowed for the Student and account purpose."),
			frappe.DuplicateEntryError,
		)


def resolve_student_reference(reference: str | None) -> str | None:
	"""Resolve old Lead references for migration and compatibility adapters only."""
	return canonical_student(reference)


def unique_owner_catalog(
	catalogs: Iterable[dict[str, str]] = (STUDENT_FIELD_OWNERS, ADMISSION_FIELD_OWNERS),
) -> dict[str, str]:
	"""Merge ownership catalogs and reject duplicate field ownership declarations."""
	merged: dict[str, str] = {}
	for catalog in catalogs:
		for fieldname, owner in catalog.items():
			if fieldname in merged and merged[fieldname] != owner:
				raise ValueError(f"Field {fieldname} has multiple owners")
			merged[fieldname] = owner
	return merged
