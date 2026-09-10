"""Authoritative Lead processing workflow.

The workflow deliberately keeps intake processing separate from the existing
admissions lifecycle and conversion commands:

    NEW -> PROCESSING -> PROCESSED -> ASSIGNED -> CLOSED

Phone, province, high school, and major are the only required processing gates.
Lead duplicate matching uses only Lead-owned identifiers and routing data;
CCCD belongs to the later Student profile and is never read here.
Processing and assignment only update the Lead status and ownership; neither
step creates a CRM Student. The explicit handoff command remains the separate
Lead-to-Student conversion boundary.

A CLOSED Lead is not a dead end: reopen_lead sends a corrected record back to
NEW and replays intake, so assignment never sees an unvalidated Lead.
"""

from __future__ import annotations

import re
from typing import Any

import frappe

from crm.fcrm.student_conversion import StudentConversionError, convert_student
from crm.fcrm.student_intake import normalize_email, normalize_phone
from crm.fcrm.student_ownership import StudentOwnershipError, change_student_ownership
from crm.fcrm.student_stage import StudentStageError, set_student_stage

PROCESSING_STATUSES = ("NEW", "PROCESSING", "PROCESSED", "ASSIGNED", "CLOSED")
RESOLUTIONS = ("PENDING", "MATCHED", "CREATED", "DUPLICATE", "INVALID", "SPAM", "FAILED")
ADVANCING_RESOLUTIONS = frozenset({"MATCHED", "CREATED"})
TERMINAL_RESOLUTIONS = frozenset({"DUPLICATE", "INVALID", "SPAM", "FAILED"})
STATUS_DEFAULT_RESOLUTIONS = {
	"NEW": "PENDING",
	"PROCESSING": "PENDING",
	"PROCESSED": "PENDING",
	"ASSIGNED": "PENDING",
	"CLOSED": "PENDING",
}
SERVICE_FLAG = "lead_processing_service"
MAX_PROCESS_SCAN = 1000


class LeadProcessingError(frappe.ValidationError):
	"""Stable machine-readable processing failure."""

	def __init__(self, code: str, message: str):
		self.code = code
		self.error_code = code
		super().__init__(message)


def _fail(code: str, message: str):
	raise LeadProcessingError(code, message)


def _required(value: Any, label: str, *, max_length: int = 255) -> str:
	if value is None or not str(value).strip():
		_fail("INVALID_INPUT", f"{label} is required.")
	value = str(value).strip()
	if len(value) > max_length:
		_fail("INVALID_INPUT", f"{label} is too long.")
	return value


def _reason(value: Any) -> str | None:
	if value in (None, ""):
		return None
	return _required(value, "reason", max_length=500)


def _operator_lead_reason(value: Any) -> str | None:
	"""Keep Lead reasons readable without exposing pre-conversion identifiers."""
	reason = _reason(value)
	if not reason:
		return None
	return re.sub(
		r"\bLead\s+(?:HS|LEAD)[-_][A-Z0-9_-]+",
		"một Lead khác",
		reason,
		flags=re.IGNORECASE,
	)


def _normalise_province(value: Any) -> str:
	return " ".join(str(value or "").strip().split()).casefold()


def _normalise_identifiers(lead) -> dict[str, str]:
	student_name = " ".join(str(lead.get("student_name") or "").strip().split()).casefold()
	high_school = " ".join(str(lead.get("high_school") or "").strip().split()).casefold()
	major = " ".join(str(lead.get("major") or "").strip().split()).casefold()
	phone = normalize_phone(lead.get("phone"))
	email = normalize_email(lead.get("email"))
	province = _normalise_province(lead.get("province"))
	blockers = []
	if not student_name:
		blockers.append("missing_name")
	if not phone and "missing_phone" not in blockers:
		blockers = [*blockers, "missing_phone"]
	if not province and "missing_province" not in blockers:
		blockers = [*blockers, "missing_province"]
	if blockers:
		_fail(
			"IDENTIFIER_GATE_FAILED",
			"Họ và tên, số điện thoại và tỉnh/thành phố là bắt buộc trước khi xử lý.",
		)
	return {
		"student_name": student_name,
		"high_school": high_school,
		"major": major,
		"phone": phone or "",
		"email": email or "",
		"province": province,
	}


def _processing_validation(lead) -> dict[str, bool]:
	return {
		"student_name": bool(str(lead.get("student_name") or "").strip()),
		"phone": bool(normalize_phone(lead.get("phone"))),
		"province": bool(_normalise_province(lead.get("province"))),
	}


def _processing_validation_issues(lead) -> list[str]:
	"""Return operator-facing reasons for every failed processing gate."""

	def value(fieldname: str) -> Any:
		camel_name = "".join(
			part.capitalize() if index else part for index, part in enumerate(fieldname.split("_"))
		)
		return lead.get(fieldname) or lead.get(camel_name)

	issues = []
	if not str(value("student_name") or "").strip():
		issues.append("Thiếu họ và tên")
	phone = str(value("phone") or "").strip()
	if not phone:
		issues.append("Thiếu số điện thoại")
	elif not normalize_phone(phone):
		issues.append("Số điện thoại không hợp lệ")
	if not str(value("province") or "").strip():
		issues.append("Thiếu tỉnh/thành phố")
	return issues


def _processing_validation_reason(lead) -> str | None:
	issues = _processing_validation_issues(lead)
	return f"Đã đóng hồ sơ vì: {', '.join(issues)}." if issues else None


def _normalise_row(row: Any) -> dict[str, str]:
	return {
		"student_name": " ".join(
			str(row.get("student_name") or row.get("full_name") or "").strip().split()
		).casefold(),
		"high_school": " ".join(str(row.get("high_school") or "").strip().split()).casefold(),
		"major": " ".join(str(row.get("major") or "").strip().split()).casefold(),
		"phone": normalize_phone(row.get("phone")) or "",
		"email": normalize_email(row.get("email")) or "",
		"province": _normalise_province(row.get("province")),
	}


def _candidate_rows(doctype: str, identifiers: dict[str, str], *, exclude: str | None = None) -> list[Any]:
	filters = []
	for fieldname in ("phone", "email"):
		if identifiers[fieldname]:
			filters.append({fieldname: identifiers[fieldname]})
	if not filters:
		return []
	fields = ["name", "high_school", "major", "phone", "email", "province", "creation"]
	if doctype == "CRM Lead":
		fields.extend(
			[
				"student_name",
				"lead_code",
				"processing_status",
				"resolution",
				"owner_staff",
				"assigned_to",
				"student",
				"converted_student",
			]
		)
	else:
		fields.append("full_name")
	rows = frappe.get_all(
		doctype,
		or_filters=filters,
		fields=fields,
		limit_page_length=0,
		ignore_permissions=True,
	)
	return [row for row in rows if not exclude or row.get("name") != exclude]


_DUPLICATE_MATCH_LABELS = {
	"PHONE_PROVINCE": "số điện thoại và tỉnh/thành phố",
}


def _duplicate_match_type(identifiers: dict[str, str], candidate: Any) -> str | None:
	row = _normalise_row(candidate)
	if (
		identifiers["phone"]
		and identifiers["province"]
		and row["phone"] == identifiers["phone"]
		and row["province"] == identifiers["province"]
	):
		return "PHONE_PROVINCE"
	return None


def _valid_lead_candidate(row: Any) -> bool:
	identifiers = _normalise_row(row)
	return all(
		(
			identifiers["phone"],
			identifiers["province"],
		)
	)


def _eligible_lead_duplicate(row: Any) -> bool:
	status = str(row.get("processing_status") or "NEW").strip().upper()
	if status == "CLOSED" and not row.get("student") and not row.get("converted_student"):
		return False
	return _valid_lead_candidate(row)


def _canonical_lead_rank(row: Any) -> tuple[int, str, str, str]:
	status = str(row.get("processing_status") or "NEW").strip().upper()
	if status == "ASSIGNED" or row.get("owner_staff") or row.get("assigned_to"):
		status_rank = 0
	elif status == "PROCESSED":
		status_rank = 1
	elif status == "PROCESSING":
		status_rank = 2
	else:
		status_rank = 3
	return (
		status_rank,
		str(row.get("creation") or ""),
		str(row.get("lead_code") or ""),
		str(row.get("name") or ""),
	)


def _classify_resolution_details(lead, identifiers: dict[str, str]) -> dict[str, Any]:
	"""Classify Student matches and Lead duplicates without closing every copy."""
	student_matches = _candidate_rows("CRM Student", identifiers)
	student_matches = [
		row for row in student_matches if _duplicate_match_type(identifiers, row)
	]
	if len(student_matches) > 1:
		return {
			"resolution": "DUPLICATE",
			"target_student": None,
			"duplicate_type": "MULTIPLE_STUDENTS",
			"reason": (
				"Đã đóng hồ sơ vì có nhiều hồ sơ Student trùng thông tin; "
				"cần người vận hành xác định đúng hồ sơ đích."
			),
		}

	lead_matches = []
	for row in _candidate_rows("CRM Lead", identifiers, exclude=lead.name):
		if not _eligible_lead_duplicate(row):
			continue
		match_type = _duplicate_match_type(identifiers, row)
		if match_type:
			lead_matches.append((row, match_type))

	current = {
		"name": lead.name,
		"student_name": lead.get("student_name"),
		"lead_code": lead.get("lead_code"),
		"creation": lead.get("creation"),
		"processing_status": _get_status(lead),
		"owner_staff": lead.get("owner_staff"),
		"assigned_to": lead.get("assigned_to"),
	}
	if lead_matches:
		canonical, match_type = min(
			[(row, matched_type) for row, matched_type in lead_matches] + [(current, None)],
			key=lambda entry: _canonical_lead_rank(entry[0]),
		)
		if canonical.get("name") != lead.name:
			label = _DUPLICATE_MATCH_LABELS.get(match_type or "PHONE_NAME_PROVINCE", "thông tin Lead")
			return {
				"resolution": "DUPLICATE",
				"target_student": None,
				"duplicate_of": canonical.get("name"),
				"duplicate_type": match_type,
				"reason": (
					f"Đã đóng Lead này vì trùng {label} với một Lead khác. "
					"Hệ thống giữ lại Lead đại diện để tiếp tục xử lý."
				),
			}
		label = _DUPLICATE_MATCH_LABELS.get(lead_matches[0][1], "thông tin định danh")
		return {
			"resolution": "MATCHED" if len(student_matches) == 1 else "CREATED",
			"target_student": student_matches[0].get("name") if student_matches else None,
			"duplicate_type": lead_matches[0][1],
			"reason": (
				f"Đã giữ lại Lead này làm hồ sơ đại diện; phát hiện Lead trùng theo {label}. "
				"Hồ sơ được tiếp tục xử lý và phân công."
			),
		}

	if len(student_matches) == 1:
		return {
			"resolution": "MATCHED",
			"target_student": student_matches[0].get("name"),
			"reason": "Đã giữ lại Lead để phân công; có một hồ sơ Student phù hợp để xử lý khi chuyển đổi.",
		}
	return {"resolution": "CREATED", "target_student": None}


def _classify_resolution(lead, identifiers: dict[str, str]) -> tuple[str, str | None]:
	classification = _classify_resolution_details(lead, identifiers)
	return classification["resolution"], classification.get("target_student")


def preview_lead(lead: str) -> dict[str, Any]:
	"""Return the processing decision without mutating the Lead."""
	lead_doc = _load_lead(lead)
	if _get_status(lead_doc) != "NEW":
		return {
			"status": _get_status(lead_doc),
			"resolution": _get_resolution(lead_doc),
			"lead": lead_doc.name,
			"target_student": lead_doc.get("matched_student") or lead_doc.get("converted_student"),
		}
	try:
		identifiers = _normalise_identifiers(lead_doc)
	except LeadProcessingError as exc:
		return {
			"status": "CLOSED",
			"resolution": "PENDING",
			"lead": lead_doc.name,
			"reason": str(exc),
			"error_code": exc.code,
			"processing_outcome": "INVALID",
		}
	classification = _classify_resolution_details(lead_doc, identifiers)
	return {
		"status": "PROCESSED"
		if classification["resolution"] in ADVANCING_RESOLUTIONS
		else "CLOSED",
		"resolution": "PENDING",
		"lead": lead_doc.name,
		"target_student": classification.get("target_student"),
		"processing_outcome": classification["resolution"],
		"duplicateOf": classification.get("duplicate_of"),
		"duplicateType": classification.get("duplicate_type"),
		"reason": classification.get("reason"),
		"validation": _processing_validation(lead_doc),
	}


def _load_lead(lead: str, *, internal_service: bool = False):
	lead_name = _required(lead, "lead")
	try:
		doc = frappe.get_doc("CRM Lead", lead_name)
	except Exception as exc:
		if exc.__class__.__name__ in {"DoesNotExistError", "ValidationError"}:
			_fail("NOT_FOUND", "Lead does not exist.")
		raise
	# A trusted in-process caller authorized its operator before the command and
	# may legitimately own a Lead that has just left that operator's row scope.
	if not internal_service and not doc.has_permission("write"):
		_fail("FORBIDDEN", "You cannot process this Lead.")
	return doc


def _lock_lead(name: str) -> None:
	frappe.db.sql("select name from `tabCRM Lead` where name=%s for update", (name,))


def _get_status(lead) -> str:
	return str(lead.get("processing_status") or "NEW").strip().upper()


def _get_resolution(lead) -> str:
	return str(lead.get("resolution") or "PENDING").strip().upper()


def _resolution_for_status(status: str, current_resolution: str) -> str:
	if status in {"NEW", "PROCESSING", "PROCESSED", "ASSIGNED"}:
		return "PENDING"
	if status == "CLOSED" and current_resolution in RESOLUTIONS[1:]:
		return current_resolution
	return STATUS_DEFAULT_RESOLUTIONS[status]


def _set_processing_values(name: str, values: dict[str, Any]) -> None:
	previous = getattr(frappe.flags, SERVICE_FLAG, False)
	setattr(frappe.flags, SERVICE_FLAG, True)
	try:
		frappe.db.set_value("CRM Lead", name, values, update_modified=True)
	finally:
		setattr(frappe.flags, SERVICE_FLAG, previous)


def update_processing_status(lead: str, status: str, reason: str | None = None) -> dict[str, Any]:
	"""Apply a manual processing-status correction without bypassing validation."""
	lead_doc = _load_lead(lead)
	_lock_lead(lead_doc.name)
	lead_doc = _load_lead(lead_doc.name)
	requested_status = _required(status, "status").upper()
	if requested_status not in PROCESSING_STATUSES:
		_fail("INVALID_STATUS", "Status must be one of the supported processing statuses.")

	resolution = _resolution_for_status(requested_status, _get_resolution(lead_doc))
	values = {
		"processing_status": requested_status,
		"resolution": resolution,
		"resolution_reason": _reason(reason) or f"Manual status update: {requested_status}.",
	}
	if requested_status in {"NEW", "PROCESSING"}:
		values["matched_student"] = None
	_set_processing_values(lead_doc.name, values)
	return {
		"status": requested_status,
		"resolution": resolution,
		"lead": lead_doc.name,
		"target_student": lead_doc.get("matched_student") if resolution == "MATCHED" else None,
		"validation": {},
	}


def process_lead(lead: str, resolution: str | None = None, reason: str | None = None) -> dict[str, Any]:
	"""Validate a NEW Lead without producing a conversion result."""
	lead_doc = _load_lead(lead)
	_lock_lead(lead_doc.name)
	lead_doc = _load_lead(lead_doc.name)
	if _get_status(lead_doc) != "NEW":
		_fail("INVALID_STATUS", "Only NEW Leads can enter processing.")

	try:
		identifiers = _normalise_identifiers(lead_doc)
	except LeadProcessingError:
		validation = _processing_validation(lead_doc)
		processing_reason = _processing_validation_reason(lead_doc)
		_set_processing_values(
			lead_doc.name,
			{
				"processing_status": "CLOSED",
				"resolution": "INVALID",
				"resolution_reason": processing_reason or "Đã đóng hồ sơ vì dữ liệu xử lý không hợp lệ.",
			},
		)
		return {
			"status": "CLOSED",
			"resolution": "INVALID",
			"lead": lead_doc.name,
			"processing_outcome": "INVALID",
			"validation": validation,
			"validation_issues": _processing_validation_issues(lead_doc),
		}

	requested_resolution = str(resolution or "").strip().upper() or None
	if requested_resolution and requested_resolution != "PENDING":
		_fail("INVALID_RESOLUTION", "Kết quả xử lý Lead luôn là Chưa có kết quả.")
	classification = _classify_resolution_details(lead_doc, identifiers)
	classified_resolution = classification["resolution"]
	target_student = classification.get("target_student")
	status = "PROCESSED" if classified_resolution in ADVANCING_RESOLUTIONS else "CLOSED"
	processing_reason = _reason(reason)
	if not processing_reason:
		processing_reason = (
			"Đã kiểm tra đủ họ tên, số điện thoại và tỉnh/thành phố; chờ phân công."
			if status == "PROCESSED"
			else classification.get("reason") or "Đã đóng hồ sơ vì thông tin bị trùng với hồ sơ khác."
		)
	_set_processing_values(
		lead_doc.name,
		{
			"processing_status": status,
			"resolution": classified_resolution if status == "CLOSED" else "PENDING",
			"resolution_reason": processing_reason,
			"phone": identifiers["phone"],
			"email": identifiers["email"],
			"matched_student": target_student,
		},
	)
	return {
		"status": status,
		"resolution": classified_resolution if status == "CLOSED" else "PENDING",
		"lead": lead_doc.name,
		"target_student": target_student,
		"processing_outcome": classified_resolution,
		"duplicate_of": classification.get("duplicate_of"),
		"duplicate_type": classification.get("duplicate_type"),
		"reason": processing_reason,
		"validation": _processing_validation(lead_doc),
	}


def reopen_lead(lead: str, reason: str | None = None) -> dict[str, Any]:
	"""Reopen a CLOSED Lead so a corrected record can be routed again.

	Assignment closes any Lead whose routing data cannot be resolved, and the
	operator then fixes that data. The Lead goes back through intake instead of
	jumping straight to PROCESSED: a record still missing phone, province, high
	school, or major closes again here rather than reaching assignment
	unvalidated.
	"""
	lead_doc = _load_lead(lead)
	if _get_status(lead_doc) != "CLOSED":
		_fail("INVALID_STATUS", "Only CLOSED Leads can be reopened.")
	reason = _reason(reason) or "Mở lại hồ sơ để phân công lại."
	update_processing_status(lead_doc.name, "NEW", reason)
	return process_lead(lead_doc.name, reason=reason)


def _scan_limit(limit: Any) -> int:
	if limit in (None, ""):
		return MAX_PROCESS_SCAN
	try:
		value = int(limit)
	except (TypeError, ValueError):
		_fail("INVALID_INPUT", "limit must be a number.")
	return max(1, min(value, MAX_PROCESS_SCAN))


def _pending_lead_filters(admission_year: Any) -> dict[str, Any]:
	year = str(admission_year or "").strip()
	if year and not (len(year) == 4 and year.isdigit()):
		_fail("INVALID_INPUT", "admission_year must be a four-digit year.")
	filters: dict[str, Any] = {"processing_status": "NEW"}
	if year:
		filters["admission_year"] = year
	return filters


def process_new_leads(admission_year: Any = None, limit: Any = None) -> dict[str, Any]:
	"""Process every NEW Lead the operator may write, in one scan.

	This is the bulk twin of :func:`process_lead` and keeps the same gates: the
	candidate scan is unfiltered by permission, but each Lead still passes the
	row-level write check inside ``_load_lead``. Every Lead runs inside its own
	savepoint so one failure cannot poison the rest of the scan.
	"""
	filters = _pending_lead_filters(admission_year)
	rows = frappe.get_all(
		"CRM Lead",
		filters=filters,
		fields=["name"],
		order_by="creation asc, name asc",
		limit_page_length=_scan_limit(limit),
	)

	summary = {"scanned": 0, "processed": 0, "closed": 0, "skipped": 0, "failed": 0}
	items: list[dict[str, Any]] = []
	for index, row in enumerate(rows):
		name = row.get("name")
		if not name:
			continue
		summary["scanned"] += 1
		savepoint = f"lead_processing_scan_{index}"
		frappe.db.savepoint(savepoint)
		try:
			result = process_lead(name)
		except Exception as exc:
			try:
				frappe.db.rollback(save_point=savepoint)
			except Exception:
				pass
			code = getattr(exc, "code", None) or "PROCESSING_FAILED"
			# FORBIDDEN and INVALID_STATUS are ordinary scan outcomes: the Lead
			# belongs to somebody else, or another operator just processed it.
			summary["skipped" if code in {"FORBIDDEN", "NOT_FOUND", "INVALID_STATUS"} else "failed"] += 1
			items.append(
				{
					"lead": name,
					"status": None,
					"resolution": None,
					"errorCode": code,
					"reason": str(exc),
				}
			)
			continue
		status = str(result.get("status") or "").upper()
		if status == "PROCESSED":
			summary["processed"] += 1
		elif status == "CLOSED":
			summary["closed"] += 1
		else:
			summary["skipped"] += 1
		items.append(
			{
				"lead": name,
				"status": status,
				"resolution": result.get("resolution"),
				"errorCode": None,
				"reason": result.get("reason"),
				"duplicateOf": result.get("duplicate_of"),
				"duplicateType": result.get("duplicate_type"),
			}
		)

	frappe.db.commit()
	return {
		"summary": summary,
		"items": items,
		"admissionYear": filters.get("admission_year"),
	}


def mark_lead_assigned(lead: str, reason: str | None = None) -> dict[str, Any]:
	"""Mark a successfully owned Lead as ASSIGNED without writing ownership twice."""
	lead_doc = _load_lead(lead)
	if _get_status(lead_doc) == "ASSIGNED":
		return {"status": "ASSIGNED", "lead": lead_doc.name, "resolution": "PENDING"}
	if _get_status(lead_doc) != "PROCESSED":
		_fail("INVALID_STATUS", "Only processed valid Leads can be assigned.")
	if not lead_doc.get("owner_staff") and not lead_doc.get("assigned_to"):
		_fail("OWNER_REQUIRED", "Lead ownership must be written before marking it assigned.")
	_set_processing_values(lead_doc.name, {"processing_status": "ASSIGNED", "resolution": "PENDING"})
	return {
		"status": "ASSIGNED",
		"lead": lead_doc.name,
		"resolution": "PENDING",
		"reason": reason,
	}


def assign_lead(
	lead: str,
	owner_staff: str,
	target_team_id: str,
	reason: str,
	idempotency_key: str,
	expected_revision: Any,
	correlation_id: str | None = None,
) -> dict[str, Any]:
	"""Assign a processed Lead to a Sale and then move it to ASSIGNED."""
	lead_doc = _load_lead(lead)
	if _get_status(lead_doc) != "PROCESSED":
		_fail("INVALID_STATUS", "Only processed valid Leads can be assigned.")
	owner_staff = _required(owner_staff, "owner_staff")
	target_team_id = _required(target_team_id, "target_team_id")
	idempotency_key = _required(idempotency_key, "idempotency_key")
	reason = _required(reason, "reason", max_length=2000)
	correlation_id = _required(correlation_id or frappe.generate_hash(length=20), "correlation_id")

	try:
		ownership = change_student_ownership(
			student=lead_doc.name,
			target_kind="owner",
			target_id=owner_staff,
			target_team_id=target_team_id,
			reason=reason,
			idempotency_key=idempotency_key,
			expected_revision=expected_revision,
			correlation_id=correlation_id,
			_internal_service=True,
			_internal_actor=getattr(frappe.session, "user", None),
			_commit=False,
			_route_trigger="assignment_batch",
			_enqueue_routing=False,
			_skip_sla=True,
		)
		_set_processing_values(
			lead_doc.name,
			{"processing_status": "ASSIGNED", "resolution": "PENDING"},
		)
		frappe.db.commit()
	except (StudentOwnershipError, LeadProcessingError):
		frappe.db.rollback()
		raise
	except Exception:
		frappe.db.rollback()
		raise

	return {
		"status": "ASSIGNED",
		"resolution": "PENDING",
		"lead": lead_doc.name,
		"ownership": ownership,
	}


def handoff_lead(
	lead: str,
	expected_lifecycle_revision: Any = None,
	idempotency_key: str = "",
	correlation_id: str | None = None,
	target_student: str | None = None,
	_internal_service: bool = False,
) -> dict[str, Any]:
	"""Convert an assigned Lead, initialise Student stage, and close the Lead.

	``_internal_service`` mirrors ``assign_lead``: the assignment batch already
	authorized the operator, so the conversion must not fail merely because the
	committed ownership moved the Lead outside that operator's row scope.
	"""
	lead_doc = _load_lead(lead, internal_service=_internal_service)
	resolution = _get_resolution(lead_doc)
	if _get_status(lead_doc) != "ASSIGNED":
		_fail("INVALID_STATUS", "Only assigned Leads can be handed off.")
	if resolution == "PENDING":
		identifiers = _normalise_identifiers(lead_doc)
		resolution, classified_target = _classify_resolution(lead_doc, identifiers)
		if classified_target and not target_student:
			target_student = classified_target
	if resolution not in ADVANCING_RESOLUTIONS:
		_fail("INVALID_STATUS", "Lead này chưa đủ điều kiện để chuyển đổi Student.")
	# Processing deliberately leaves an advancing Lead at PENDING while it is
	# waiting for assignment.  Once the assigned Lead is handed off, persist the
	# classification before entering the conversion command.  The conversion
	# guard uses the persisted resolution to prevent a direct Lead -> Student
	# bypass, and the same transaction rolls this projection back on failure.
	if _get_resolution(lead_doc) == "PENDING":
		_set_processing_values(
			lead_doc.name,
			{
				"resolution": resolution,
				"matched_student": target_student if resolution == "MATCHED" else None,
				"resolution_reason": f"{resolution} handoff queued.",
			},
		)
		lead_doc = _load_lead(lead_doc.name, internal_service=_internal_service)
	idempotency_key = _required(idempotency_key, "idempotency_key")
	correlation_id = _required(correlation_id or frappe.generate_hash(length=20), "correlation_id")
	if expected_lifecycle_revision in (None, ""):
		expected_lifecycle_revision = lead_doc.get("lifecycle_revision") or 0
	if resolution == "CREATED" and target_student:
		_fail("TARGET_STUDENT_NOT_ALLOWED", "CREATED handoff must create a new Student.")

	if resolution == "MATCHED" and not target_student:
		target_student = lead_doc.get("matched_student")
	if resolution == "MATCHED" and not target_student:
		identifiers = _normalise_identifiers(lead_doc)
		_, target_student = _classify_resolution(lead_doc, identifiers)
		if not target_student:
			_fail("TARGET_STUDENT_REQUIRED", "MATCHED Lead must point to its target Student.")

	try:
		conversion = convert_student(
			student=lead_doc.name,
			expected_lifecycle_revision=expected_lifecycle_revision,
			idempotency_key=idempotency_key,
			correlation_id=correlation_id,
			target_student=target_student,
			_internal_service=_internal_service,
		)
		student_id = conversion.get("target_student") or conversion.get("student_id")
		if not student_id:
			_fail("CONVERSION_RESULT_INVALID", "Conversion did not return a Student.")
		set_student_stage(student_id, "New", _internal_service=True)
		_set_processing_values(
			lead_doc.name,
			{
				"processing_status": "CLOSED",
				"resolution": resolution,
				"resolution_reason": f"{resolution} handoff completed.",
			},
		)
		extra = {"status": "CLOSED", "resolution": resolution, "lead": lead_doc.name, "student": student_id}
		frappe.db.commit()
		return {**extra, "conversion": conversion, "student_stage": "New"}
	except StudentStageError as exc:
		frappe.db.rollback()
		_fail(exc.code, str(exc))
	except (StudentConversionError, LeadProcessingError):
		# Conversion errors are intentionally propagated. The Lead remains ASSIGNED
		# and the caller can remediate rollout/integrity prerequisites before retry.
		frappe.db.rollback()
		raise
	except Exception:
		frappe.db.rollback()
		raise
