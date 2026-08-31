from __future__ import annotations

import hashlib
import json
from typing import Any

import frappe
from frappe.exceptions import QueryDeadlockError, QueryTimeoutError
from frappe.utils import nowdate
from pymysql import MySQLError

from crm.api.director_school_common import (
	as_iso,
	raise_api_error,
	require_director_access,
	resolve_admission_year,
	resolve_school_id,
)
from crm.fcrm.school_intelligence import calculate_school_potential

_SNAPSHOT_ORDER = "snapshot_date desc, recorded_at desc, revision desc, modified desc, name desc"
_SUPPORT_LIMIT = 50
_SOURCE_ERRORS = (frappe.PermissionError, frappe.DoesNotExistError, QueryDeadlockError, QueryTimeoutError, MySQLError)
_ACTIVITY_OUTCOMES = frozenset({"Positive", "Neutral", "Follow-up Needed", "No Response", "Not Applicable"})


class SchoolPrimarySourceUnavailable(RuntimeError):
	pass


def _one(doctype, *, filters, fields):
	rows = frappe.get_list(
		doctype,
		filters=filters,
		fields=fields,
		order_by="name asc",
		limit_page_length=1,
	)
	return dict(rows[0]) if rows else None


def _load_supporting_sources(school, admission_year):
	failed = set()
	capped = set()
	sources: dict[str, Any] = {
		"province": None,
		"ward": None,
		"snapshot": None,
		"intelligence": {},
		"students": [],
		"contacts": [],
		"stakeholders": [],
		"people": {},
		"roles": {},
		"activities": [],
		"activity_types": {},
	}

	def load(key, callback, default):
		try:
			sources[key] = callback()
		except _SOURCE_ERRORS:
			failed.add(key)
			sources[key] = default

	load(
		"province",
		lambda: _one(
			"CRM Province",
			filters={"name": school.get("province")},
			fields=["province_code", "province_name", "region"],
		),
		None,
	)
	load(
		"ward",
		lambda: _one(
			"CRM Ward",
			filters={"name": school.get("ward"), "province": school.get("province")},
			fields=["ward_code", "ward_name", "province"],
		),
		None,
	)

	def snapshot():
		rows = frappe.get_list(
			"CRM High School Annual Snapshot",
			filters={
				"high_school": school.get("name"),
				"admission_year": admission_year,
				"period_type": "Annual",
				"verification_status": "Verified",
			},
			fields=[
				"name", "snapshot_date", "recorded_at", "revision", "modified", "applicant_count",
				"enrolled_count", "contact_count", "student_count", "conversion_count", "average_score",
				"conversion_rate", "enrollment_rate", "forecast_count", "context_raw_counts", "verification_status",
			],
			order_by=_SNAPSHOT_ORDER,
			limit_page_length=1,
		)
		return dict(rows[0]) if rows else None

	load("snapshot", snapshot, None)
	load(
		"intelligence",
		lambda: {"potential": calculate_school_potential(school.get("name"), admission_year)},
		{},
	)
	load(
		"students",
		lambda: [
			dict(row)
			for row in frappe.get_list(
				"CRM Student",
				filters={"high_school": school.get("name"), "admission_year": admission_year},
				fields=["name", "current_grade", "study_stage", "lifecycle_stage"],
				order_by="name asc",
				limit_page_length=0,
			)
		],
		[],
	)
	load(
		"contacts",
		lambda: [
			dict(row)
			for row in frappe.get_list(
				"CRM Contact",
				filters={"high_school": school.get("name"), "admission_year": admission_year},
				fields=["name", "lifecycle_stage", "lead_status"],
				order_by="name asc",
				limit_page_length=0,
			)
		],
		[],
	)

	def stakeholders():
		rows = frappe.get_list(
			"CRM School Stakeholder",
			filters={"high_school": school.get("name")},
			fields=[
				"person", "stakeholder_role", "position_title", "relationship_status",
				"relationship_score", "is_primary", "last_touch_date", "next_touch_date",
				"effective_from", "effective_until",
			],
			order_by="is_primary desc, modified desc, name desc",
			limit_page_length=_SUPPORT_LIMIT + 1,
		)
		today = str(nowdate())
		active = [
			dict(row)
			for row in rows
			if (not row.get("effective_from") or str(row.get("effective_from")) <= today)
			and (not row.get("effective_until") or str(row.get("effective_until")) >= today)
		]
		if len(rows) > _SUPPORT_LIMIT or len(active) > _SUPPORT_LIMIT:
			capped.add("stakeholders")
		return active[:_SUPPORT_LIMIT]

	load("stakeholders", stakeholders, [])

	person_names = sorted({row.get("person") for row in sources["stakeholders"] if row.get("person")})
	if person_names:
		load(
			"people",
			lambda: {
				row.get("name"): row.get("full_name")
				for row in frappe.get_list(
					"CRM Person",
					filters={"name": ["in", person_names]},
					fields=["name", "full_name"],
					order_by="name asc",
					limit_page_length=_SUPPORT_LIMIT,
				)
			},
			{},
		)
	role_names = sorted({row.get("stakeholder_role") for row in sources["stakeholders"] if row.get("stakeholder_role")})
	if role_names:
		load(
			"roles",
			lambda: {
				row.get("name"): row.get("term_name")
				for row in frappe.get_list(
					"CRM Term",
					filters={"name": ["in", role_names], "category": "stakeholder_role"},
					fields=["name", "term_name"],
					order_by="name asc",
					limit_page_length=_SUPPORT_LIMIT,
				)
			},
			{},
		)

	def activities():
		rows = frappe.get_list(
			"CRM School Activity",
			filters={"high_school": school.get("name")},
			or_filters=[{"admission_year": admission_year}, {"admission_year": ["is", "not set"]}],
			fields=["activity_type", "activity_date", "scheduled_datetime", "status", "outcome", "attendance"],
			order_by="activity_date desc, scheduled_datetime desc, name desc",
			limit_page_length=_SUPPORT_LIMIT + 1,
		)
		if len(rows) > _SUPPORT_LIMIT:
			capped.add("activities")
		return [dict(row) for row in rows[:_SUPPORT_LIMIT]]

	load("activities", activities, [])
	activity_types = sorted({row.get("activity_type") for row in sources["activities"] if row.get("activity_type")})
	if activity_types:
		load(
			"activity_types",
			lambda: {
				row.get("name"): row.get("term_name")
				for row in frappe.get_list(
					"CRM Term",
					filters={"name": ["in", activity_types], "category": "activity_type"},
					fields=["name", "term_name"],
					order_by="name asc",
					limit_page_length=_SUPPORT_LIMIT,
				)
			},
			{},
		)
	return sources, failed, capped


def _section_state(value, *, failed=False, capped=False):
	if failed or value in (None, {}):
		return "unavailable"
	return "partial" if capped else "available"


def _source_revision(school, sources, failed=None, capped=None):
	payload = {
		"school": school,
		"sources": sources,
		"failed": sorted(failed or set()),
		"capped": sorted(capped or set()),
	}
	return hashlib.sha256(json.dumps(payload, default=str, sort_keys=True).encode()).hexdigest()[:16]


def _school_detail_context(snapshot):
	raw = (snapshot or {}).get("context_raw_counts")
	if isinstance(raw, str):
		try:
			raw = json.loads(raw)
		except (TypeError, ValueError):
			return {}
	if not isinstance(raw, dict):
		return {}
	context = raw.get("director_school_detail")
	return context if isinstance(context, dict) else {}


def _relationship_level(status: Any) -> str | None:
	return {
		"New": "Đã tiếp xúc",
		"Active": "Hợp tác thường xuyên",
		"Dormant": "Đã tiếp xúc",
		"Do Not Contact": "Chưa tiếp xúc",
	}.get(status)


def _build_detail(school, sources, failed, capped, admission_year):
	province = sources.get("province") or {}
	ward = sources.get("ward") or {}
	snapshot = sources.get("snapshot") or {}
	detail_context = _school_detail_context(snapshot)
	locality_context = detail_context.get("locality") if isinstance(detail_context.get("locality"), dict) else {}
	students = sources.get("students") or []
	lead_contacts = sources.get("contacts") or []
	potential = (sources.get("intelligence") or {}).get("potential") or {}
	grade12_students = sum(
		1
		for row in students
		if str(row.get("current_grade") or "") == "12"
		or str(row.get("study_stage") or "").startswith("grade_12")
	)
	available_students = sum(
		1
		for row in students
		if (
			str(row.get("current_grade") or "") == "12"
			or str(row.get("study_stage") or "").startswith("grade_12")
		)
		and row.get("lifecycle_stage") not in {"Enrolled", "Lost"}
	)
	student_applications = sum(1 for row in students if row.get("lifecycle_stage") == "Applicant")
	student_enrollment = sum(1 for row in students if row.get("lifecycle_stage") == "Enrolled")
	grade12_from_snapshot = None
	try:
		enrollment_rate = float(snapshot.get("enrollment_rate"))
		enrolled_count = int(snapshot.get("enrolled_count") or 0)
		if enrollment_rate > 0:
			grade12_from_snapshot = round(enrolled_count / (enrollment_rate / 100))
	except (TypeError, ValueError, ZeroDivisionError):
		pass
	school_code = str(school.get("school_code") or "")
	canonical_school_code = school_code.zfill(3) if school_code.isdigit() else None
	external_id = school.get("canonical_id")
	if province.get("province_code") and ward.get("ward_code") and canonical_school_code:
		external_id = f"{province['province_code']}-{ward['ward_code']}-{canonical_school_code}"

	contacts = []
	for row in sources.get("stakeholders") or []:
		name = (sources.get("people") or {}).get(row.get("person"))
		contacts.append({
			"role": (sources.get("roles") or {}).get(row.get("stakeholder_role")),
			"hasContact": bool(name),
			"full_name": name,
			"position": row.get("position_title"),
			"relationshipStatus": row.get("relationship_status"),
			"lastTouch": as_iso(row.get("last_touch_date")),
			"nextTouch": as_iso(row.get("next_touch_date")),
		})

	activities = [
		{
			"type": (sources.get("activity_types") or {}).get(row.get("activity_type")),
			"date": as_iso(row.get("activity_date")),
			"scheduledAt": as_iso(row.get("scheduled_datetime")),
			"status": "scheduled" if row.get("status") == "Planned" else "completed" if row.get("status") == "Completed" else None,
			"outcome": row.get("outcome") if row.get("outcome") in _ACTIVITY_OUTCOMES else None,
			"attendance": row.get("attendance"),
		}
		for row in sources.get("activities") or []
		if row.get("status") in {"Planned", "Completed"}
	]
	primary_relationship = next((row for row in sources.get("stakeholders") or [] if row.get("is_primary")), None)
	if primary_relationship is None and sources.get("stakeholders"):
		primary_relationship = sources["stakeholders"][0]
	primary_relationship = primary_relationship or {}
	relationship_name = (sources.get("people") or {}).get(primary_relationship.get("person"))
	sections = {
		"identity": "available",
		"snapshot": _section_state(sources.get("snapshot"), failed="snapshot" in failed),
		"relationship": _section_state(
			sources.get("stakeholders"),
			failed="stakeholders" in failed,
			capped="stakeholders" in capped or bool({"people", "roles"} & failed),
		),
		"activities": _section_state(
			sources.get("activities"),
			failed="activities" in failed,
			capped="activities" in capped or "activity_types" in failed,
		),
		"locality": "available" if school.get("latitude") is not None and school.get("longitude") is not None else "partial",
		"demographics": _section_state(detail_context.get("demographics")),
		"subjectMix": _section_state(detail_context.get("subjectMix")),
		"outcomes": "available" if any(
			detail_context.get(key) for key in ("scoreBands", "postGraduationChoices", "competitionContext")
		) else "unavailable",
	}
	status = "partial" if failed or capped or any(
		sections[key] != "available" for key in ("snapshot", "relationship", "activities", "locality")
	) else "available"
	return {
		"status": status,
		"school": {
			"id": external_id,
			"provinceCode": province.get("province_code") or school.get("province_code"),
			"province": province.get("province_name") or school.get("province"),
			"districtCode": ward.get("ward_code") or school.get("ward_code"),
			"district": ward.get("ward_name"),
			"schoolCode": canonical_school_code,
			"name": school.get("school_name"),
			"address": school.get("address"),
			"area": school.get("school_area"),
			"isBoardingSchool": school.get("boarding_type") == "Boarding School",
		},
		"potentialScore": detail_context.get("potentialScore"),
		"potentialState": potential.get("value") if potential.get("state") == "current" else None,
		"grade12Students": grade12_from_snapshot if snapshot else (grade12_students if students else None),
		"availableStudents": snapshot.get("student_count") if snapshot and snapshot.get("student_count") is not None else (available_students if students else None),
		"prospects": snapshot.get("contact_count") if snapshot else len(lead_contacts),
		"applications": snapshot.get("applicant_count") if snapshot else student_applications,
		"enrollment": snapshot.get("enrolled_count") if snapshot else student_enrollment,
		"changes": {"prospects": None, "applications": None, "enrollment": None},
		"performance": detail_context.get("performance") or {"6m": [], "year": []},
		"geography": detail_context.get("geography"),
		"locality": {
			"source": {
				"name": school.get("school_name"),
				"address": school.get("address"),
				"coordinates": {"latitude": school.get("latitude"), "longitude": school.get("longitude")},
			},
			"province": province.get("province_name"),
			"ward": ward.get("ward_name"),
			"travelTime": locality_context.get("travelTime"),
			"distanceKm": locality_context.get("distanceKm"),
			"marketStats": locality_context.get("marketStats") or {},
		},
		"demographics": detail_context.get("demographics"),
		"subjectMix": detail_context.get("subjectMix"),
		"earlyForecast": detail_context.get("earlyForecast"),
		"activityStats": detail_context.get("activityStats") or [],
	"relationship": {
			"level": _relationship_level(primary_relationship.get("relationship_status")),
			"score": primary_relationship.get("relationship_score"),
			"contact": relationship_name,
			"contactRole": (sources.get("roles") or {}).get(primary_relationship.get("stakeholder_role")),
			"lastTouch": as_iso(primary_relationship.get("last_touch_date")),
			"nextTouch": as_iso(primary_relationship.get("next_touch_date")),
		},
		"classification": {
			"group": "Trọng điểm" if school.get("is_key_account") else None,
			"isKeyAccount": bool(school.get("is_key_account")),
			"label": None,
			"action": None,
		},
		"quadrantPeers": detail_context.get("quadrantPeers") or [],
		"scoreBands": detail_context.get("scoreBands") or [],
		"examScoreBands": detail_context.get("examScoreBands") or [],
		"potentialIndicators": detail_context.get("potentialIndicators") or [],
		"academicGap": detail_context.get("academicGap"),
		"postGraduationChoices": detail_context.get("postGraduationChoices") or [],
		"competitionContext": detail_context.get("competitionContext"),
		"contacts": contacts,
		"activities": activities,
		"dataFreshness": as_iso(snapshot.get("snapshot_date")),
		"dataSources": {
			"directory": "CRM High School",
			"snapshot": "CRM High School Annual Snapshot" if snapshot else None,
			"relationship": "CRM School Stakeholder" if contacts else None,
			"activities": "CRM School Activity" if activities else None,
			"examScore": "CRM High School Annual Snapshot" if detail_context.get("examScoreBands") else None,
			"reportCard": "CRM High School Annual Snapshot" if detail_context.get("academicGap") else None,
		},
		"dataAvailability": {
			"sections": sections,
			"fields": {
				"potentialScore": "available" if detail_context.get("potentialScore") is not None else "unavailable",
				"potentialIndicators": "available" if detail_context.get("potentialIndicators") else "unavailable",
				"grade12Students": "available" if grade12_from_snapshot is not None or students else "unavailable",
				"availableStudents": "available" if snapshot.get("student_count") is not None or students else "unavailable",
				"demographics": "available" if detail_context.get("demographics") else "unavailable",
				"subjectMix": "available" if detail_context.get("subjectMix") else "unavailable",
				"postGraduationChoices": "available" if detail_context.get("postGraduationChoices") else "unavailable",
				"examScoreBands": "available" if detail_context.get("examScoreBands") else "unavailable",
				"competitionContext": "available" if detail_context.get("competitionContext") else "unavailable",
				"locality.travelTime": "available" if locality_context.get("travelTime") else "unavailable",
			},
		},
		"meta": {
			"admissionYear": int(admission_year),
			"asOf": as_iso(snapshot.get("snapshot_date") or snapshot.get("recorded_at")),
			"scope": "director",
			"sourceDataRevision": _source_revision(school, sources, failed, capped),
		},
	}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_director_school_detail(school_id: str, admissionYear=None):
	# Public read-only school detail endpoint; the whitelist explicitly allows guest reads.
	# require_director_access()
	admission_year = resolve_admission_year(admissionYear)
	try:
		school = resolve_school_id(school_id)
	except (frappe.DoesNotExistError, frappe.ValidationError):
		raise
	except SchoolPrimarySourceUnavailable:
		raise_api_error("SCHOOL_DATA_UNAVAILABLE", "Không thể tải nguồn dữ liệu trường chính.", frappe.ValidationError, 503)
	except _SOURCE_ERRORS:
		raise_api_error("SCHOOL_DATA_UNAVAILABLE", "Không thể tải nguồn dữ liệu trường chính.", frappe.ValidationError, 503)
	sources, failed, capped = _load_supporting_sources(school, admission_year)
	return _build_detail(school, sources, failed, capped, admission_year)
