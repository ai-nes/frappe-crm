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

LOCAL_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
MAX_PAGE_SIZE = 100

LEAD_FIELDS = [
	"name",
	"lead_code",
	"processing_status",
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
		campaign=campaign,
		order=order,
	)
	query["status"] = _resolve_status(query["status"])
	filters, or_filters = _lead_filters(query)
	total = _count_leads(filters, or_filters)
	total_all = _count_leads(_year_filter(query["admission_year"]))
	rows = _fetch_lead_rows(query, filters, or_filters)
	lookups = _load_lookups(rows)

	meta = {
		"total": total,
		"totalAll": total_all,
		"page": query["page"],
		"pageSize": query["page_size"],
		"totalPages": _total_pages(total, query["page_size"]),
		"hasNextPage": query["page"] < _total_pages(total, query["page_size"]),
		"admissionYear": _year_number(query["admission_year"]),
		"query": query["query"],
		"status": query["status"],
		"statusOptions": _status_options(),
		"asOf": _as_iso(frappe.utils.now_datetime()),
	}
	if query.get("campaign"):
		meta["stats"] = _campaign_stats(filters, or_filters)

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

	if not doc.has_permission("read"):
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
	campaign_value = str(campaign or "").strip() or None
	if campaign_value and _fold(campaign_value) == "all":
		campaign_value = None
	return {
		"admission_year": admission_year_value,
		"page": _parse_int(page, "page", 1, minimum=1),
		"page_size": _parse_int(page_size, "pageSize", 20, minimum=1, maximum=MAX_PAGE_SIZE),
		"query": str(query or "").strip(),
		"status": status_value,
		"campaign": campaign_value,
		"order": order_value,
	}


def _resolve_status(value: str | None) -> str | None:
	if not value:
		return None
	if not _table_exists("CRM Enrollment Status"):
		return value
	if frappe.db.exists("CRM Enrollment Status", value):
		return value
	rows = frappe.get_all(
		"CRM Enrollment Status",
		filters={"display_name": value},
		fields=["name"],
		limit_page_length=1,
	)
	if rows:
		return rows[0].get("name")
	_raise_api_error("INVALID_STATUS", "Tình trạng Lead không hợp lệ.", frappe.ValidationError, 422)


def _resolve_campaign(value: str) -> str:
	"""Accept the campaign document name and its stable code as filter values."""
	if frappe.db.exists("CRM Campaign", value):
		return value
	return frappe.db.get_value("CRM Campaign", {"stable_code": value}, "name") or value


def _lead_filters(query: dict[str, Any]) -> tuple[dict[str, Any], list[list[str]]]:
	filters = _year_filter(query["admission_year"])
	if query.get("status"):
		filters["enrollment_status"] = query["status"]
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


def _count_leads(filters: dict[str, Any], or_filters: list[list[str]] | None = None) -> int:
	rows = frappe.get_list(
		"CRM Lead",
		filters=filters,
		or_filters=or_filters or [],
		fields=["count(name) as total"],
		limit_page_length=1,
	)
	return int(rows[0].get("total") or 0) if rows else 0


def _campaign_stats(filters: dict[str, Any], or_filters: list[list[str]]) -> dict[str, int]:
	"""Return the processing funnel for a campaign-filtered lead query."""
	total = _count_leads(filters, or_filters)
	in_progress_filters = {**filters, "processing_status": ["in", ["PROCESSED", "ASSIGNED"]]}
	closed_filters = {**filters, "processing_status": "CLOSED"}
	in_progress = _count_leads(in_progress_filters, or_filters)
	closed = _count_leads(closed_filters, or_filters)
	return {
		"total": total,
		"inProgress": in_progress,
		"closed": closed,
		"conversionRate": round(closed / total * 100) if total else 0,
	}


def _fetch_lead_rows(query: dict[str, Any], filters: dict[str, Any], or_filters: list[list[str]]) -> list:
	return frappe.get_list(
		"CRM Lead",
		filters=filters,
		or_filters=or_filters,
		fields=LEAD_FIELDS,
		order_by=f"modified {query['order']}, name {query['order']}",
		limit_start=(query["page"] - 1) * query["page_size"],
		limit_page_length=query["page_size"],
	)


def _load_lookups(rows: list) -> dict[str, dict[str, str]]:
	return {
		"schools": _lookup_map("CRM High School", {row.get("high_school") for row in rows}, "school_name"),
		"provinces": _lookup_map("CRM Province", {row.get("province") for row in rows}, "province_name"),
		"majors": _lookup_map("CRM Major", {row.get("major") for row in rows}, "major_name"),
		"owners": _lookup_map("CRM Staff", {row.get("owner_staff") for row in rows}, "full_name"),
		"sources": _lookup_map("CRM Lead Source", {row.get("source") for row in rows}, "source_name"),
		"branches": _lookup_map("CRM Campus", {row.get("branch") for row in rows}, "campus_name"),
		"aspirations": _lookup_map("CRM Aspiration", {row.get("aspiration") for row in rows}, "display_name"),
		"events": {},
		"statuses": _status_lookup(),
	}


def _lookup_map(doctype: str, names: set[str | None], label_field: str) -> dict[str, str]:
	keys = [name for name in names if name]
	if not keys or not _table_exists(doctype):
		return {}
	rows = frappe.get_all(
		doctype, filters={"name": ["in", keys]}, fields=["name", label_field], limit_page_length=0
	)
	return {row.get("name"): row.get(label_field) or row.get("name") for row in rows}


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
		{"value": row.get("name"), "label": row.get("display_name") or row.get("name")}
		for row in _status_rows()
		if row.get("name") and row.get("enabled", 1)
	]


def _map_lead_row(row, *, lookups: dict[str, dict[str, str]] | None = None) -> dict[str, Any]:
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
		"status": _status_label(row.get("enrollment_status"), lookups),
		"statusCode": row.get("enrollment_status"),
		"source": lookups.get("sources", {}).get(row.get("source")) or row.get("source") or "",
		"owner": lookups.get("owners", {}).get(owner_key) or owner_key or "Chưa phân công",
	}
	if row.get("processing_status"):
		item["processingStatus"] = row.get("processing_status")
	if row.get("creation"):
		item["createdAt"] = _as_iso(row.get("creation")) or ""
	return item


def _map_detail_row(
	row,
	*,
	lookups: dict[str, dict[str, str]],
	event_titles: list[str],
) -> dict[str, Any]:
	item = _map_lead_row(row, lookups=lookups)
	return {
		**item,
		"email": row.get("email") or "",
		"secondaryEmail": row.get("other_email") or "",
		"province": lookups.get("provinces", {}).get(row.get("province")) or row.get("province") or "",
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
	entries = list(event_entries)
	status_entry_added = False
	for index, change in enumerate(doc.get("status_change_log") or []):
		from_status = _status_label(change.get("from"), lookups)
		to_status = _status_label(change.get("to"), lookups)
		if not from_status and not to_status:
			continue
		is_initial_status = not to_status
		content = (
			f'Lead được tạo với tình trạng "{from_status}".'
			if is_initial_status
			else f'Tình trạng Lead được cập nhật từ "{from_status or "-"}" sang "{to_status}".'
		)
		entries.append(
			{
				"id": change.get("name") or f"{doc.name}:status:{index}",
				"type": "activity",
				"title": "Lead được tạo" if is_initial_status else "Cập nhật tình trạng Lead",
				"author": _user_label(change.get("log_owner")),
				"date": _as_iso(change.get("to_date") or change.get("from_date")) or "",
				"content": content,
			}
		)
		status_entry_added = True

	created_at = _as_iso(doc.get("creation")) or ""
	if created_at and not status_entry_added:
		entries.append(
			{
				"id": f"{doc.name}:created",
				"type": "activity",
				"title": "Lead được tạo",
				"author": _user_label(doc.get("owner")),
				"date": created_at,
				"content": "Lead được tiếp nhận từ hệ thống CRM.",
			}
		)

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
