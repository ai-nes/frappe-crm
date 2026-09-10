"""Deterministic admissions-funnel fixtures for the Director dashboard.

The regular showcase seed already owns the CRM Student cohort.  This module
adds only the canonical admission offerings/applications needed by the funnel
snapshot and refreshes dates on showcase-owned students so cohort and aging
charts have useful historical data.  Every write is keyed to ``NAMESPACE`` and
is safe to replay.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import frappe

NAMESPACE = "crm-demo-showcase:director-admission-funnel"
OFFERING_POLICY_VERSION = "director-funnel-demo-v1"
SNAPSHOT_STUDENT_COUNT = 50
MAX_MQL_APPLICATIONS = 60
FUNNEL_STAGES = frozenset({"MQL", "Applicant", "Enrolled"})


def application_status_for_stage(stage: str | None, index: int) -> str | None:
	"""Return a repeatable application status for one Student lifecycle stage."""
	if stage == "Enrolled":
		return "Enrolled"
	if stage == "Applicant":
		return "Accepted" if index % 4 == 0 else "Under Review"
	if stage == "MQL":
		return "Submitted"
	return None


def snapshot_datetime(as_of: datetime, index: int) -> datetime:
	"""Place ten showcase records into five cohorts old enough for six-week follow-up."""
	week_start = (as_of - timedelta(days=as_of.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
	cohort_index = min(max(index // 10, 0), 5)
	return week_start - timedelta(weeks=11 - cohort_index) + timedelta(hours=10)


def application_source_reference(student: str) -> str:
	"""Return the stable internal lineage key for one demo application."""
	return f"{NAMESPACE}:application:{student}"


def seed(context: dict[str, Any]) -> dict[str, Any]:
	"""Seed funnel applications for the existing showcase Student cohort."""
	if not _table_exists("CRM Admission Application") or not _table_exists("CRM Admission Offering"):
		return {"status": "skipped", "reason": "admission_doctypes_unavailable"}

	as_of = frappe.utils.now_datetime()
	students = _load_showcase_students(context)
	if not students:
		return {"status": "skipped", "reason": "showcase_students_unavailable"}

	date_by_student = _refresh_snapshot_dates(students, as_of)
	_ensure_admission_methods(students)
	targets = _application_targets(students)
	offerings: dict[tuple[str, str, str], str] = {}
	metrics = {
		"status": "available",
		"students_considered": len(students),
		"applications_created": 0,
		"applications_updated": 0,
		"applications_skipped": 0,
		"offerings_created": 0,
		"offerings_reused": 0,
		"errors": [],
	}

	for index, row in enumerate(targets):
		student = row.get("name")
		stage = row.get("lifecycle_stage")
		status = application_status_for_stage(stage, index)
		if not student or not status or not row.get("case_key"):
			metrics["applications_skipped"] += 1
			continue

		try:
			offering_key = _offering_identity(row, context)
			if not offering_key:
				metrics["applications_skipped"] += 1
				continue
			if offering_key not in offerings:
				offering, created = _ensure_offering(row, context)
				offerings[offering_key] = offering
				metrics["offerings_created" if created else "offerings_reused"] += 1

			created_at = date_by_student.get(student) or _coerce_datetime(row.get("creation"))
			created_at = created_at or as_of
			result = _ensure_application(
				row,
				offering=offerings[offering_key],
				status=status,
				index=index,
				created_at=created_at,
			)
			metrics["applications_created" if result == "created" else "applications_updated"] += 1
		except Exception as exc:
			metrics["errors"].append({"student": student, "error": str(exc)})

	frappe.db.commit()
	return metrics


def _load_showcase_students(context: dict[str, Any]) -> list[dict[str, Any]]:
	filters: dict[str, Any] = {
		"admission_year": context["admission_year"],
		"import_source_id": ["like", "crm-demo-showcase:%"],
	}
	if context.get("campus"):
		filters["branch"] = context["campus"]
	return [
		dict(row)
		for row in frappe.get_all(
			"CRM Lead",
			filters=filters,
			fields=[
				"name",
				"case_key",
				"admission_year",
				"lifecycle_stage",
				"engagement_revision",
				"branch",
				"major",
				"admission_method",
				"creation",
				"import_source_id",
			],
			order_by="name asc",
			limit_page_length=0,
			ignore_permissions=True,
		)
		or []
	]


def _application_targets(students: list[dict[str, Any]]) -> list[dict[str, Any]]:
	eligible = [row for row in students if row.get("lifecycle_stage") in FUNNEL_STAGES]
	mql = [row for row in eligible if row.get("lifecycle_stage") == "MQL"][:MAX_MQL_APPLICATIONS]
	progressed = [row for row in eligible if row.get("lifecycle_stage") != "MQL"]
	return mql + progressed


def _ensure_admission_methods(students: list[dict[str, Any]]) -> None:
	"""Ensure every Student admission-method code exists in the CRM Admission Method lookup."""
	for code in sorted({str(row.get("admission_method") or "").strip() for row in students}):
		if not code or frappe.db.exists("CRM Admission Method", code):
			continue
		frappe.get_doc(
			{
				"doctype": "CRM Admission Method",
				"code": code,
				"display_name": code.replace("_", " ").title(),
			}
		).insert(ignore_permissions=True)


def _refresh_snapshot_dates(students: list[dict[str, Any]], as_of: datetime) -> dict[str, datetime]:
	"""Give a bounded, deterministic subset five historical weekly cohorts."""
	date_by_student: dict[str, datetime] = {}
	for index, row in enumerate(students[:SNAPSHOT_STUDENT_COUNT]):
		student = row.get("name")
		if not student:
			continue
		created_at = snapshot_datetime(as_of, index)
		modified_at = created_at + timedelta(days=1, hours=index % 8)
		frappe.db.set_value(
			"CRM Lead",
			student,
			{"creation": created_at, "modified": modified_at},
			update_modified=False,
		)
		date_by_student[student] = created_at
	return date_by_student


def _offering_identity(row: dict[str, Any], context: dict[str, Any]) -> tuple[str, str, str] | None:
	campus = row.get("branch") or context.get("campus")
	major = row.get("major") or context.get("major")
	method = row.get("admission_method")
	if not campus or not major or not method:
		return None
	return str(campus), str(major), str(method)


def _ensure_offering(row: dict[str, Any], context: dict[str, Any]) -> tuple[str, bool]:
	identity = _offering_identity(row, context)
	if not identity:
		raise frappe.ValidationError("Funnel seed requires campus, major and admission method.")
	campus, major, method = identity
	year = str(context["admission_year"])
	owned_key = "|".join((NAMESPACE, year, campus, major, method))
	owned = frappe.db.get_value("CRM Admission Offering", {"offering_key": owned_key}, "name")
	if owned:
		doc = frappe.get_doc("CRM Admission Offering", owned)
		if doc.status != "Active":
			return _approve_offering(doc, method), False
		return doc.name, False

	active = frappe.db.get_value(
		"CRM Admission Offering",
		{
			"admission_year": year,
			"campus": campus,
			"major": major,
			"admission_method": method,
			"status": "Active",
		},
		"name",
	)
	if active:
		return active, False

	doc = frappe.get_doc(
		{
			"doctype": "CRM Admission Offering",
			"offering_key": owned_key,
			"admission_year": year,
			"campus": campus,
			"major": major,
			"admission_method": method,
			"quota": 5000,
			"effective_from": f"{year}-01-01",
			"effective_until": f"{year}-12-31",
			"status": "Draft",
			"policy_version": OFFERING_POLICY_VERSION,
			"source_reference": f"{NAMESPACE}:offering:{method}",
		}
	).insert(ignore_permissions=True)
	return _approve_offering(doc, method), True


def _approve_offering(doc: Any, method: str) -> str:
	from crm.fcrm.admission_offering import approve_offering

	approve_offering(
		offering=doc.name,
		idempotency_key=f"{NAMESPACE}:offering-approval:{method}",
	)
	return doc.name


def _ensure_application(
	row: dict[str, Any],
	*,
	offering: str,
	status: str,
	index: int,
	created_at: datetime,
) -> str:
	from crm.fcrm.admission_application import create_application

	student = row["name"]
	source_reference = application_source_reference(student)
	submitted_at = created_at + timedelta(days=2, hours=index % 5)
	enrolled_at = created_at + timedelta(days=7) if status == "Enrolled" else None
	values = {
		"offering": offering,
		"status": status,
		"preference_order": 1,
		"preference": "Primary",
		"document_total": 6,
		"document_completed": 6 if status in {"Accepted", "Enrolled"} else 4,
		"deadline": (created_at + timedelta(days=45)).date(),
		"submitted_at": submitted_at,
		"enrolled_at": enrolled_at,
		"source_reference": source_reference,
	}
	existing = frappe.db.get_value(
		"CRM Admission Application", {"source_reference": source_reference}, "name"
	)
	if existing:
		doc = frappe.get_doc("CRM Admission Application", existing)
		for field, value in values.items():
			if field != "offering" and value is not None:
				doc.set(field, value)
		doc.save(ignore_permissions=True)
		application = doc.name
		result = "updated"
	else:
		result = create_application(
			student=student,
			values=values,
			expected_revision=int(row.get("engagement_revision") or 0),
			idempotency_key=f"{NAMESPACE}:application:{student}",
		)
		application = result.get("application")
		if not application:
			raise frappe.ValidationError(f"Application was not created for Student {student}.")
		result = "created"

	# Application modified/creation timestamps are system fields and are adjusted
	# only for this demo namespace so the funnel's aging snapshot is historical.
	stage_at = enrolled_at or submitted_at
	frappe.db.set_value(
		"CRM Admission Application",
		application,
		{"creation": created_at, "modified": stage_at},
		update_modified=False,
	)
	return result


def _coerce_datetime(value: Any) -> datetime | None:
	if not value:
		return None
	try:
		parsed = frappe.utils.get_datetime(value)
		return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
	except (AttributeError, TypeError, ValueError, OverflowError):
		return None


def _table_exists(doctype: str) -> bool:
	try:
		return bool(frappe.db.table_exists(doctype))
	except (AttributeError, frappe.DoesNotExistError):
		return False
