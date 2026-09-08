"""Session-scoped read-only projections for the Lead Sale lead views."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any
from zoneinfo import ZoneInfo

import frappe
from frappe import _
from frappe.utils import get_datetime

from crm.api.audit import get_audit_logs_for_document
from crm.fcrm.lead_processing import PROCESSING_STATUSES, RESOLUTIONS
from crm.fcrm.permissions import can_read_full_lead_board, get_student_list_read_condition

LOCAL_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
MAX_PAGE_SIZE = 100
PROCESSING_STATUS_LABELS = {
	"NEW": "Mới",
	"PROCESSING": "Đang xử lý",
	"PROCESSED": "Đã xử lý",
	"ASSIGNED": "Đã phân công",
	"CLOSED": "Đã đóng",
}
RESOLUTION_LABELS = {
	"PENDING": "Chưa có kết quả",
	"MATCHED": "Đã liên kết",
	"CREATED": "Đã tạo mới",
	"DUPLICATE": "Trùng lặp",
	"INVALID": "Không hợp lệ",
	"SPAM": "Spam",
	"FAILED": "Thất bại",
}

LEAD_FIELDS = [
	"name",
	"lead_code",
	"processing_status",
	"resolution",
	"student_name",
	"phone",
	"email",
	"other_email",
	"enrollment_status",
	"lifecycle_stage",
	"high_school",
	"province",
	"ward",
	"branch",
	"major",
	"aspiration",
	"source",
	"advertising_channel",
	"conversion_potential",
	"segments",
	"admission_year",
	"notes",
	"owner_staff",
	"assigned_to",
	"student",
	"creation",
	"modified",
]


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_director_leads(
	admissionYear: str | int | None = None,
	page: str | int = 1,
	pageSize: str | int = 20,
	q: str | None = "",
	status: str | None = None,
	resolution: str | None = None,
	order: str = "desc",
	campaign: str | None = None,
) -> dict[str, Any]:
	"""Return a permission-scoped, paginated Lead list for the dashboard."""
	_require_access()
	query = _parse_query(
		admission_year=admissionYear,
		page=page,
		page_size=pageSize,
		query=q,
		status=status,
		resolution=resolution,
		campaign=campaign,
		order=order,
	)
	query["status"] = _resolve_status(query["status"])
	query["resolution"] = _resolve_resolution(query["resolution"])
	filters, or_filters = _lead_filters(query)
	list_scope_lead_ids = _list_scope_lead_ids()
	total = _count_leads(filters, or_filters, allowed_lead_ids=list_scope_lead_ids)
	year_filter = _year_filter(query["admission_year"])
	total_all = _count_leads(year_filter, allowed_lead_ids=list_scope_lead_ids)
	# The header actions ("Xử lý Lead" / "Phân công Lead") reflect the whole
	# intake year, not the operator's current filter, so these two counts are
	# deliberately measured outside `filters`.
	pending_new = _count_leads(
		{**year_filter, "processing_status": "NEW"}, allowed_lead_ids=list_scope_lead_ids
	)
	ready_to_assign = _count_leads(
		{
			**year_filter,
			"processing_status": "PROCESSED",
			"resolution": ["in", ["MATCHED", "CREATED"]],
		},
		allowed_lead_ids=list_scope_lead_ids,
	)
	rows = _fetch_lead_rows(
		query, filters, or_filters, allowed_lead_ids=list_scope_lead_ids
	)
	lookups = _load_lookups(rows)

	meta = {
		"total": total,
		"totalAll": total_all,
		"pendingNew": pending_new,
		"readyToAssign": ready_to_assign,
		"page": query["page"],
		"pageSize": query["page_size"],
		"totalPages": _total_pages(total, query["page_size"]),
		"hasNextPage": query["page"] < _total_pages(total, query["page_size"]),
		"admissionYear": _year_number(query["admission_year"]),
		"query": query["query"],
		"status": query["status"],
		"statusOptions": _status_options(),
		"resolution": query["resolution"],
		"resolutionOptions": _resolution_options(),
		"asOf": _as_iso(frappe.utils.now_datetime()),
	}
	if query.get("campaign"):
		meta["stats"] = _campaign_stats(
			filters, or_filters, allowed_lead_ids=list_scope_lead_ids
		)

	return {
		"data": [_map_lead_row(row, lookups=lookups) for row in rows],
		"meta": meta,
	}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_director_lead(lead_id: str) -> dict[str, Any]:
	"""Return one permission-checked Lead detail projection."""
	_require_access()
	lead_id = str(lead_id or "").strip()
	if not lead_id:
		_raise_api_error("INVALID_LEAD_ID", "leadId không được để trống.", frappe.ValidationError, 400)

	try:
		doc = frappe.get_doc("CRM Lead", lead_id)
	except frappe.DoesNotExistError:
		_raise_api_error("LEAD_NOT_FOUND", "Không tìm thấy Lead.", frappe.DoesNotExistError, 404)

	if not doc.has_permission("read") and not can_read_full_lead_board():
		_raise_api_error("LEAD_NOT_FOUND", "Không tìm thấy Lead.", frappe.DoesNotExistError, 404)

	row = frappe._dict({field: doc.get(field) for field in LEAD_FIELDS})
	lookups = _load_lookups([row])
	event_entries, event_titles = _event_projection(lead_id, lookups)
	return {
		"lead": _map_detail_row(row, lookups=lookups, event_titles=event_titles),
		"log": _lead_log(doc, lookups=lookups, event_entries=event_entries),
		"meta": {"asOf": _as_iso(frappe.utils.now_datetime())},
	}


def _parse_query(
	*,
	admission_year: str | int | None = None,
	page: str | int = 1,
	page_size: str | int = 20,
	query: str | None = "",
	status: str | None = None,
	resolution: str | None = None,
	campaign: str | None = None,
	order: str = "desc",
) -> dict[str, Any]:
	"""Normalize and validate public list arguments without querying Lead rows."""
	admission_year_value = str(admission_year or "").strip() or None
	if admission_year_value and not re.fullmatch(r"\d{4}", admission_year_value):
		frappe.throw(_("admissionYear must be a four-digit year."), frappe.ValidationError)
	order_value = str(order or "").strip().lower()
	if order_value not in {"asc", "desc"}:
		frappe.throw(_("order must be asc or desc."), frappe.ValidationError)
	status_value = str(status or "").strip() or None
	if status_value and _fold(status_value) == "all":
		status_value = None
	resolution_value = str(resolution or "").strip() or None
	if resolution_value and _fold(resolution_value) == "all":
		resolution_value = None
	campaign_value = str(campaign or "").strip() or None
	if campaign_value and _fold(campaign_value) == "all":
		campaign_value = None
	return {
		"admission_year": admission_year_value,
		"page": _parse_int(page, "page", 1, minimum=1),
		"page_size": _parse_int(page_size, "pageSize", 20, minimum=1, maximum=MAX_PAGE_SIZE),
		"query": str(query or "").strip(),
		"status": status_value,
		"resolution": resolution_value,
		"campaign": campaign_value,
		"order": order_value,
	}


def _resolve_status(value: str | None) -> str | None:
	if not value:
		return None
	candidate = str(value).strip().upper()
	if candidate in PROCESSING_STATUSES:
		return candidate
	_raise_api_error(
		"INVALID_STATUS",
		"Trạng thái xử lý Lead không hợp lệ.",
		frappe.ValidationError,
		422,
	)


def _resolve_resolution(value: str | None) -> str | None:
	if not value:
		return None
	candidate = str(value).strip().upper()
	if candidate in RESOLUTIONS:
		return candidate
	_raise_api_error(
		"INVALID_RESOLUTION",
		"Kết quả Lead không hợp lệ.",
		frappe.ValidationError,
		422,
	)


def _resolve_campaign(value: str) -> str:
	"""Accept the campaign document name and its stable code as filter values."""
	if frappe.db.exists("CRM Campaign", value):
		return value
	return frappe.db.get_value("CRM Campaign", {"stable_code": value}, "name") or value


def _lead_filters(query: dict[str, Any]) -> tuple[dict[str, Any], list[list[str]]]:
	filters = _year_filter(query["admission_year"])
	if query.get("status"):
		filters["processing_status"] = query["status"]
	if query.get("resolution"):
		filters["resolution"] = query["resolution"]
	if query.get("campaign"):
		filters["campaign"] = _resolve_campaign(query["campaign"])

	or_filters: list[list[str]] = []
	if query["query"]:
		pattern = f"%{query['query']}%"
		for field in (
			"name",
			"lead_code",
			"student_name",
			"phone",
			"email",
			"high_school",
			"owner_staff",
			"source",
		):
			or_filters.append([field, "like", pattern])
	return filters, or_filters


def _year_filter(admission_year: str | None) -> dict[str, Any]:
	return {"admission_year": admission_year} if admission_year else {}


def _list_scope_lead_ids() -> list[str] | None:
	"""Return explicit Lead IDs for the session's Group/Team list scope."""
	if can_read_full_lead_board():
		return None
	condition = get_student_list_read_condition(doctype="CRM Lead")
	if condition is None:
		return None
	rows = frappe.db.sql(f"select name from `tabCRM Lead` where ({condition})", as_dict=True)
	return [row.get("name") for row in rows if row.get("name")]


def _lead_reader(allowed_lead_ids: list[str] | None = None):
	"""Return the row reader matching the caller's Lead list/detail scope.

	``frappe.get_list`` applies the canonical row scope, which hides a Lead as
	soon as it is routed to another Team. A list scope resolved by
	``_list_scope_lead_ids`` is applied explicitly and can therefore use
	``frappe.get_all`` without widening visibility. The legacy no-argument path
	remains available for detail compatibility; both endpoints have already
	asserted the DocType read grant in ``_require_access``.
	"""
	if allowed_lead_ids is not None:
		return frappe.get_all
	return frappe.get_all if can_read_full_lead_board() else frappe.get_list


def _with_allowed_lead_ids(
	filters: dict[str, Any], allowed_lead_ids: list[str] | None
) -> dict[str, Any]:
	if allowed_lead_ids is None:
		return filters
	return {**filters, "name": ["in", allowed_lead_ids]}


def _count_leads(
	filters: dict[str, Any],
	or_filters: list[list[str]] | None = None,
	*,
	allowed_lead_ids: list[str] | None = None,
) -> int:
	if allowed_lead_ids is not None and not allowed_lead_ids:
		return 0
	rows = _lead_reader(allowed_lead_ids)(
		"CRM Lead",
		filters=_with_allowed_lead_ids(filters, allowed_lead_ids),
		or_filters=or_filters or [],
		fields=["count(name) as total"],
		limit_page_length=1,
	)
	return int(rows[0].get("total") or 0) if rows else 0


def _campaign_stats(
	filters: dict[str, Any],
	or_filters: list[list[str]],
	*,
	allowed_lead_ids: list[str] | None = None,
) -> dict[str, int]:
	"""Return the processing funnel for a campaign-filtered lead query."""
	total = _count_leads(filters, or_filters, allowed_lead_ids=allowed_lead_ids)
	in_progress_filters = {
		**filters,
		"processing_status": ["in", ["PROCESSED", "ASSIGNED"]],
	}
	closed_filters = {**filters, "processing_status": "CLOSED"}
	in_progress = _count_leads(
		in_progress_filters, or_filters, allowed_lead_ids=allowed_lead_ids
	)
	closed = _count_leads(closed_filters, or_filters, allowed_lead_ids=allowed_lead_ids)
	return {
		"total": total,
		"inProgress": in_progress,
		"closed": closed,
		"conversionRate": round(closed / total * 100) if total else 0,
	}


def _fetch_lead_rows(
	query: dict[str, Any],
	filters: dict[str, Any],
	or_filters: list[list[str]],
	*,
	allowed_lead_ids: list[str] | None = None,
) -> list:
	if allowed_lead_ids is not None and not allowed_lead_ids:
		return []
	return _lead_reader(allowed_lead_ids)(
		"CRM Lead",
		filters=_with_allowed_lead_ids(filters, allowed_lead_ids),
		or_filters=or_filters,
		fields=LEAD_FIELDS,
		order_by=f"modified {query['order']}, name {query['order']}",
		limit_start=(query["page"] - 1) * query["page_size"],
		limit_page_length=query["page_size"],
	)


def _load_lookups(rows: list) -> dict[str, Any]:
	return {
		"schools": _lookup_map("CRM High School", {row.get("high_school") for row in rows}, "school_name"),
		"provinces": _lookup_map("CRM Province", {row.get("province") for row in rows}, "province_name"),
		"wards": _lookup_map("CRM Ward", {row.get("ward") for row in rows}, "ward_name"),
		"majors": _lookup_map("CRM Major", {row.get("major") for row in rows}, "major_name"),
		"owners": _lookup_map("CRM Staff", {row.get("owner_staff") for row in rows}, "full_name"),
		"sources": _lookup_map("CRM Lead Source", {row.get("source") for row in rows}, "source_name"),
		"branches": _lookup_map("CRM Campus", {row.get("branch") for row in rows}, "campus_name"),
		"aspirations": _lookup_map("CRM Aspiration", {row.get("aspiration") for row in rows}, "display_name"),
		"events": {},
		"statuses": _status_lookup(),
		"contact_counts": _contact_counts(rows),
	}


def _lookup_map(doctype: str, names: set[str | None], label_field: str) -> dict[str, str]:
	keys = [name for name in names if name]
	if not keys or not _table_exists(doctype):
		return {}
	rows = frappe.get_all(
		doctype, filters={"name": ["in", keys]}, fields=["name", label_field], limit_page_length=0
	)
	return {row.get("name"): row.get(label_field) or row.get("name") for row in rows}


def _contact_counts(rows: list) -> dict[str, dict[str, int]]:
	"""Aggregate call attempts for one Lead page without per-row queries."""
	lead_ids = {str(row.get("name")) for row in rows if row.get("name")}
	counts = {lead_id: {"no_answer": 0, "success": 0} for lead_id in lead_ids}
	if not lead_ids:
		return counts

	call_log_ids_by_lead: dict[str, set[str]] = {}
	if _table_exists("Call Log"):
		try:
			call_logs = frappe.get_list(
				"Call Log",
				filters={
					"reference_doctype": "CRM Lead",
					"reference_docname": ["in", sorted(lead_ids)],
				},
				fields=["name", "reference_docname", "status", "duration"],
				limit_page_length=0,
			)
		except frappe.PermissionError:
			call_logs = []
		for call in call_logs:
			lead_id = str(call.get("reference_docname") or "")
			call_id = str(call.get("name") or "")
			if lead_id not in counts:
				continue
			if call_id:
				call_log_ids_by_lead.setdefault(lead_id, set()).add(call_id)
			_bucket_contact_attempt(counts[lead_id], _call_log_succeeded(call))

	interaction_leads: dict[str, set[str]] = {}
	for row in rows:
		lead_id = str(row.get("name") or "")
		if lead_id not in lead_ids:
			continue
		student_id = str(row.get("student") or "")
		for target_id in {lead_id, student_id} - {""}:
			interaction_leads.setdefault(target_id, set()).add(lead_id)

	if _table_exists("CRM Interaction"):
		try:
			interactions = frappe.get_list(
				"CRM Interaction",
				filters={"student": ["in", sorted(interaction_leads)]},
				fields=[
					"name",
					"student",
					"interaction_type",
					"channel",
					"outcome",
					"reference_doctype",
					"reference_docname",
				],
				limit_page_length=0,
			)
		except frappe.PermissionError:
			interactions = []
		for interaction in interactions:
			lead_ids_for_interaction = interaction_leads.get(str(interaction.get("student") or ""), set())
			if not lead_ids_for_interaction or not _is_call_interaction(interaction):
				continue
			for lead_id in lead_ids_for_interaction:
				if interaction.get("reference_doctype") == "Call Log" and str(
					interaction.get("reference_docname") or ""
				) in call_log_ids_by_lead.get(lead_id, set()):
					continue
				_bucket_contact_attempt(counts[lead_id], _interaction_succeeded(interaction))

	return counts


def _bucket_contact_attempt(count: dict[str, int], succeeded: bool) -> None:
	count["success" if succeeded else "no_answer"] += 1


def _call_log_succeeded(row: dict[str, Any]) -> bool:
	status = _fold(row.get("status"))
	if status in {"completed", "connected"}:
		return True
	if status in {"no answer", "busy", "canceled", "missed", "failed"}:
		return False
	try:
		return int(row.get("duration") or 0) > 0
	except (TypeError, ValueError):
		return False


def _is_call_interaction(row: dict[str, Any]) -> bool:
	channel = _fold(row.get("channel"))
	interaction_type = _fold(row.get("interaction_type"))
	return any(marker in channel for marker in ("call", "phone", "goi")) or interaction_type in {
		"phone_call",
		"connected",
		"outreach",
	}


def _interaction_succeeded(row: dict[str, Any]) -> bool:
	outcome = _fold(row.get("outcome"))
	return outcome not in {"no response", "uncontactable", "no answer", "missed", "failed", "busy"}


def _status_rows() -> list:
	if not _table_exists("CRM Enrollment Status"):
		return []
	return frappe.get_all(
		"CRM Enrollment Status",
		fields=["name", "display_name", "enabled", "sort_order"],
		order_by="sort_order asc, name asc",
		limit_page_length=0,
	)


def _status_lookup() -> dict[str, str]:
	return {
		row.get("name"): row.get("display_name") or row.get("name")
		for row in _status_rows()
		if row.get("name")
	}


def _status_options() -> list[dict[str, str]]:
	return [
		{"value": status, "label": PROCESSING_STATUS_LABELS.get(status, status)}
		for status in PROCESSING_STATUSES
	]


def _resolution_options() -> list[dict[str, str]]:
	return [
		{"value": resolution, "label": RESOLUTION_LABELS.get(resolution, resolution)}
		for resolution in RESOLUTIONS
	]


def _map_lead_row(row, *, lookups: dict[str, Any] | None = None) -> dict[str, Any]:
	lookups = lookups or {}
	owner_key = row.get("owner_staff") or row.get("assigned_to")
	item = {
		"id": row.get("name"),
		"leadCode": row.get("lead_code"),
		"studentId": row.get("name"),
		"initials": _initials(row.get("student_name")),
		"name": row.get("student_name") or row.get("name"),
		"phone": row.get("phone") or "",
		"school": lookups.get("schools", {}).get(row.get("high_school")) or row.get("high_school") or "",
		"status": _processing_status_label(row.get("processing_status")),
		"statusCode": row.get("processing_status"),
		"result": _result_code(row.get("resolution")),
		"source": lookups.get("sources", {}).get(row.get("source")) or row.get("source") or "",
		"owner": lookups.get("owners", {}).get(owner_key) or owner_key or "Chưa phân công",
	}
	contact_count = lookups.get("contact_counts", {}).get(str(row.get("name")), {})
	item["contactNoAnswer"] = max(0, int(contact_count.get("no_answer", 0) or 0))
	item["contactSuccess"] = max(0, int(contact_count.get("success", 0) or 0))
	if row.get("processing_status"):
		item["processingStatus"] = row.get("processing_status")
	if row.get("creation"):
		item["createdAt"] = _as_iso(row.get("creation")) or ""
	return item


def _map_detail_row(
	row,
	*,
	lookups: dict[str, Any],
	event_titles: list[str],
) -> dict[str, Any]:
	item = _map_lead_row(row, lookups=lookups)
	return {
		**item,
		"lifecycleStatus": _status_label(row.get("enrollment_status"), lookups),
		"lifecycleStatusCode": row.get("enrollment_status"),
		"email": row.get("email") or "",
		"secondaryEmail": row.get("other_email") or "",
		"province": lookups.get("provinces", {}).get(row.get("province")) or row.get("province") or "",
		"ward": lookups.get("wards", {}).get(row.get("ward")) or row.get("ward") or "",
		"interestedMajor": lookups.get("majors", {}).get(row.get("major")) or row.get("major") or "",
		"adChannel": row.get("advertising_channel") or "",
		"segments": _segments(row.get("segments")),
		"enrollmentYear": _year_number(row.get("admission_year")),
		"conversionPotential": _conversion_label(row.get("conversion_potential")),
		"branch": lookups.get("branches", {}).get(row.get("branch")) or row.get("branch") or "",
		"tags": [],
		"fptAspiration": lookups.get("aspirations", {}).get(row.get("aspiration"))
		or row.get("aspiration")
		or "",
		"eventsParticipated": event_titles,
		"description": row.get("notes") or "",
		"modifiedAt": _as_iso(row.get("modified")),
	}


def _event_projection(
	lead_id: str, lookups: dict[str, dict[str, str]]
) -> tuple[list[dict[str, Any]], list[str]]:
	if not _table_exists("CRM Marketing Engagement"):
		return [], []
	try:
		rows = frappe.get_list(
			"CRM Marketing Engagement",
			filters={"student": lead_id, "engagement_kind": "event_participation"},
			fields=[
				"name",
				"crm_event",
				"status",
				"notes",
				"actor",
				"registered_at",
				"checked_in_at",
				"creation",
			],
			order_by="creation desc, name desc",
			limit_page_length=0,
		)
	except frappe.PermissionError:
		# Attribution evidence is deliberately not granted to sales profiles.
		# The Lead projection remains readable when that optional source is not.
		return [], []
	event_names = {row.get("crm_event") for row in rows if row.get("crm_event")}
	event_titles = _lookup_map("CRM Event", event_names, "title")
	entries: list[dict[str, Any]] = []
	titles: list[str] = []
	for row in rows:
		title = event_titles.get(row.get("crm_event")) or row.get("crm_event") or "Sự kiện tuyển sinh"
		if title not in titles:
			titles.append(title)
		status = row.get("status") or ""
		content = f"Lead tham gia sự kiện {title}."
		if status:
			content = f"{content} Trạng thái: {status}."
		if row.get("notes"):
			content = f"{content} {row.get('notes')}"
		entries.append(
			{
				"id": row.get("name"),
				"type": "activity",
				"title": "Tham gia sự kiện",
				"author": _user_label(row.get("actor")),
				"date": _as_iso(row.get("checked_in_at") or row.get("registered_at") or row.get("creation"))
				or "",
				"content": content,
			}
		)
	return entries, titles


def _lead_log(
	doc, *, lookups: dict[str, dict[str, str]], event_entries: list[dict[str, Any]]
) -> list[dict[str, Any]]:
	entries: list[dict[str, Any]] = []
	for log in get_audit_logs_for_document(
		doc.name,
		doctype="CRM Lead",
		include_creation=True,
		include_deletion=False,
	):
		entries.extend(_map_audit_log_entry(log))
	entries.extend(event_entries)

	if _table_exists("FCRM Note"):
		notes = frappe.get_list(
			"FCRM Note",
			filters={"reference_doctype": "CRM Lead", "reference_docname": doc.name},
			fields=["name", "content", "owner", "creation", "modified"],
			order_by="modified desc, name desc",
			limit_page_length=0,
		)
		for note in notes:
			if not note.get("content"):
				continue
			entries.append(
				{
					"id": note.get("name"),
					"type": "note",
					"title": "Ghi chú chăm sóc",
					"author": _user_label(note.get("owner")),
					"date": _as_iso(note.get("modified") or note.get("creation")) or "",
					"content": note.get("content"),
				}
			)
	return sorted(entries, key=lambda entry: entry.get("date") or "", reverse=True)


def _map_audit_log_entry(log: dict[str, Any]) -> list[dict[str, Any]]:
	category = log.get("category") or "data"
	title = {
		"record": "Lead được tạo",
		"status": "Cập nhật tình trạng Lead",
		"lifecycle": "Cập nhật vòng đời Lead",
		"assignment": "Thay đổi phân công Lead",
		"processing": "Cập nhật xử lý Lead",
		"conversion": "Cập nhật chuyển đổi Lead",
		"outcome": "Ghi nhận kết quả Lead",
	}.get(category, "Cập nhật dữ liệu Lead")
	if log.get("event_type") == "status_initialized":
		title = "Gán tình trạng ban đầu cho Lead"
	old_value = log.get("old_value")
	new_value = log.get("new_value")
	if category == "record":
		content = "Lead được tiếp nhận từ hệ thống CRM."
	elif log.get("field_label") or log.get("fieldname"):
		field = log.get("field_label") or log.get("fieldname")
		content = f'{field} được cập nhật từ "{_audit_value_text(old_value)}" sang "{_audit_value_text(new_value)}".'
	else:
		content = "Thông tin Lead được cập nhật."
	if log.get("reason"):
		content = f"{content} Lý do: {log['reason']}"

	return [
		{
			"id": log.get("event_id"),
			"type": "activity",
			"title": title,
			"author": log.get("owner_full_name") or _user_label(log.get("owner")),
			"date": _as_iso(log.get("occurred_at")) or "",
			"content": content,
			"event_type": log.get("event_type"),
			"category": category,
			"fieldname": log.get("fieldname"),
			"field_label": log.get("field_label"),
			"old_value": old_value,
			"new_value": new_value,
			"reason": log.get("reason"),
			"source": log.get("source"),
			"metadata": log.get("metadata"),
		}
	]


def _audit_value_text(value: Any) -> str:
	if value in (None, ""):
		return "-"
	if isinstance(value, (dict, list)):
		return json.dumps(value, ensure_ascii=False, sort_keys=True)
	return str(value)


def _segments(value: Any) -> list[str]:
	if isinstance(value, str):
		try:
			value = json.loads(value)
		except (TypeError, ValueError):
			return []
	if not isinstance(value, list):
		return []
	return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _conversion_label(value: Any) -> str | None:
	labels = {"High": "Cao", "Medium": "Trung bình", "Low": "Thấp", "Unknown": "Chưa xác định"}
	value = str(value or "").strip()
	return labels.get(value) if value else None


def _status_label(value: Any, lookups: dict[str, dict[str, str]]) -> str:
	value = str(value or "").strip()
	return lookups.get("statuses", {}).get(value) or value


def _processing_status_label(value: Any) -> str:
	value = str(value or "").strip()
	return PROCESSING_STATUS_LABELS.get(value) or value


def _result_code(value: Any) -> str:
	result = str(value or "").strip().upper()
	return "" if result in {"", "PENDING"} else result


def _user_label(user: Any) -> str:
	user = str(user or "").strip()
	if not user:
		return "Hệ thống"
	return frappe.db.get_value("User", user, "full_name") or user


def _initials(value: Any) -> str:
	text = str(value or "").strip()
	if not text:
		return "L"
	normalized = unicodedata.normalize("NFD", text)
	normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
	normalized = normalized.replace("đ", "d").replace("Đ", "D")
	parts = normalized.split()
	return "".join(part[0].upper() for part in parts[-2:] if part) or "L"


def _fold(value: Any) -> str:
	return "".join(
		char for char in unicodedata.normalize("NFD", str(value or "")) if unicodedata.category(char) != "Mn"
	).lower()


def _parse_int(value: Any, field: str, default: int, *, minimum: int, maximum: int | None = None) -> int:
	if value is None or str(value).strip() == "":
		return default
	text = str(value).strip()
	if not re.fullmatch(r"[+-]?\d+", text):
		frappe.throw(_(f"{field} must be an integer."), frappe.ValidationError)
	parsed = int(text)
	if parsed < minimum or (maximum is not None and parsed > maximum):
		frappe.throw(_(f"{field} is out of range."), frappe.ValidationError)
	return parsed


def _year_number(value: Any) -> int | None:
	try:
		return int(value) if value not in (None, "") else None
	except (TypeError, ValueError):
		return None


def _total_pages(total: int, page_size: int) -> int:
	return max(1, (total + page_size - 1) // page_size)


def _as_iso(value: Any) -> str | None:
	if not value:
		return None
	try:
		parsed = get_datetime(value)
	except (TypeError, ValueError, OverflowError):
		return None
	if parsed.tzinfo is None:
		parsed = parsed.replace(tzinfo=LOCAL_TIMEZONE)
	return parsed.isoformat()


def _table_exists(doctype: str) -> bool:
	try:
		return bool(frappe.db.exists("DocType", doctype))
	except (AttributeError, frappe.DoesNotExistError):
		return False


def _require_access() -> None:
	user = getattr(frappe.session, "user", None)
	if not user or user in {"Guest", "None"}:
		_raise_api_error(
			"UNAUTHENTICATED",
			"Bạn cần đăng nhập để truy cập dữ liệu Lead.",
			frappe.AuthenticationError,
			401,
		)
	try:
		frappe.has_permission("CRM Lead", "read", user=user, throw=True)
	except frappe.PermissionError:
		_raise_api_error(
			"FORBIDDEN",
			"Bạn không có quyền đọc dữ liệu Lead.",
			frappe.PermissionError,
			403,
		)


def _raise_api_error(code: str, message: str, exception, status: int) -> None:
	try:
		if getattr(frappe, "local", None) and isinstance(getattr(frappe.local, "response", None), dict):
			frappe.local.response["error"] = {"code": code, "message": message}
			frappe.local.response["http_status_code"] = status
	except (AttributeError, TypeError):
		pass
	frappe.throw(_(message), exception)
