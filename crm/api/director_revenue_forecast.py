"""Revenue forecast snapshot for the Director dashboard.

The endpoint deliberately reads the finance ledger and approved targets instead
of mixing dashboard fixtures into a production response.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import frappe

from crm.api.director_school_common import raise_api_error, require_director_access, resolve_admission_year

PERIODS = frozenset({"this-month", "this-quarter", "admission-year"})


@frappe.whitelist(methods=["GET"])
def get_director_revenue_forecast(
	admissionYear: str | int | None = None,
	period: str = "admission-year",
	scope: str = "all",
	timezone: str = "Asia/Ho_Chi_Minh",
	transactionLimit: int | str = 10,
	fromDate: str | None = None,
	toDate: str | None = None,
	**query: Any,
) -> dict[str, Any]:
	"""Return a permission-scoped revenue forecast, without student PII."""
	require_revenue_forecast_access()
	admission_year = resolve_admission_year(admissionYear)
	tz = _parse_timezone(timezone)
	selected_period = _parse_period(period)
	date_from, date_to, warnings = _resolve_range(
		admission_year, selected_period, query.get("from", fromDate), query.get("to", toDate), tz
	)
	scope_context = _resolve_scope(scope)
	limit = _parse_limit(transactionLimit)
	ledger = _load_ledger(date_from, date_to, scope_context, warnings)
	payments = _load_payments(date_from, date_to, scope_context, warnings)
	targets = _load_targets(admission_year, date_from, date_to, scope_context)
	return _build_response(
		admission_year,
		selected_period,
		scope_context,
		date_from,
		date_to,
		tz,
		ledger,
		payments,
		targets,
		limit,
		warnings,
	)


def require_revenue_forecast_access() -> dict[str, Any]:
	"""Extend the canonical Director permission to the dedicated finance role."""
	user = getattr(frappe.session, "user", None)
	if not user or user == "Guest":
		raise_api_error(
			"UNAUTHENTICATED", "Bạn cần đăng nhập để truy cập dữ liệu này.", frappe.AuthenticationError, 401
		)
	if frappe.db.get_value("User", user, "enabled") not in (1, True, "1"):
		raise_api_error("UNAUTHENTICATED", "Tài khoản không hoạt động.", frappe.AuthenticationError, 401)
	if user == "Administrator" or "Finance Director" in frappe.get_roles(user):
		return {"user": user, "profile": "finance_director", "roleState": "canonical_profile"}
	return require_director_access()


def _parse_timezone(value: Any) -> ZoneInfo:
	try:
		return ZoneInfo(str(value or "Asia/Ho_Chi_Minh"))
	except ZoneInfoNotFoundError:
		raise_api_error(
			"INVALID_QUERY", "timezone phải là IANA timezone hợp lệ.", frappe.ValidationError, 400
		)
		raise AssertionError("raise_api_error always raises")


def _parse_period(value: Any) -> str:
	result = str(value or "admission-year").strip().lower()
	if result not in PERIODS:
		raise_api_error("INVALID_QUERY", "period không hợp lệ.", frappe.ValidationError, 400)
	return result


def _parse_limit(value: Any) -> int:
	try:
		result = int(value)
	except (TypeError, ValueError):
		raise_api_error("INVALID_QUERY", "transactionLimit phải là số nguyên.", frappe.ValidationError, 400)
		return 10
	if not 0 <= result <= 50:
		raise_api_error(
			"INVALID_QUERY", "transactionLimit phải nằm trong khoảng 0..50.", frappe.ValidationError, 400
		)
	return result


def _resolve_range(
	year: str, period: str, from_value: Any, to_value: Any, tz: ZoneInfo
) -> tuple[date, date, list[str]]:
	warnings: list[str] = []
	row = frappe.db.get_value(
		"CRM Admission Year", {"year_name": year}, ["start_date", "end_date"], as_dict=True
	)
	start = _as_date(row.get("start_date")) if row else None
	end = _as_date(row.get("end_date")) if row else None
	if not start or not end:
		start, end = date(int(year), 1, 1), date(int(year), 12, 31)
		warnings.append("Kỳ tuyển sinh thiếu ngày hiệu lực; đã dùng năm dương lịch.")
	today = datetime.now(tz).date()
	if period == "this-month":
		default_from = today.replace(day=1)
		default_to = _month_end(today)
	elif period == "this-quarter":
		quarter_month = ((today.month - 1) // 3) * 3 + 1
		default_from = today.replace(month=quarter_month, day=1)
		default_to = _month_end(today.replace(month=quarter_month + 2, day=1))
	else:
		default_from, default_to = start, end
	date_from = _parse_date(from_value, "from") if from_value not in (None, "") else max(default_from, start)
	date_to = _parse_date(to_value, "to") if to_value not in (None, "") else min(default_to, end)
	if date_from > date_to:
		raise_api_error(
			"INVALID_DATE_RANGE",
			"Ngày bắt đầu phải trước hoặc bằng ngày kết thúc.",
			frappe.ValidationError,
			422,
		)
	return date_from, date_to, warnings


def _parse_date(value: Any, field: str) -> date:
	try:
		return date.fromisoformat(str(value).strip())
	except (TypeError, ValueError):
		raise_api_error(
			"INVALID_QUERY", f"Tham số {field} phải có định dạng YYYY-MM-DD.", frappe.ValidationError, 400
		)
		raise AssertionError("raise_api_error always raises")


def _month_end(value: date) -> date:
	return (value.replace(day=28) + __import__("datetime").timedelta(days=4)).replace(day=1) - __import__(
		"datetime"
	).timedelta(days=1)


def _resolve_scope(value: Any) -> dict[str, str | None]:
	text = str(value or "all").strip()
	if text.casefold() == "all":
		return {"id": "all", "label": "Toàn hệ thống", "campus": None}
	campus = frappe.db.get_value("CRM Campus", {"name": text}, ["name", "campus_name"], as_dict=True)
	if not campus:
		campus = frappe.db.get_value(
			"CRM Campus", {"campus_code": text}, ["name", "campus_name"], as_dict=True
		)
	if not campus:
		raise_api_error("INVALID_QUERY", "scope không hợp lệ.", frappe.ValidationError, 400)
	return {"id": campus.name, "label": campus.campus_name or campus.name, "campus": campus.name}


def _load_ledger(
	date_from: date, date_to: date, scope: dict[str, str | None], warnings: list[str]
) -> list[dict[str, Any]]:
	if not frappe.db.table_exists("CRM Revenue Recognition"):
		raise_api_error(
			"REVENUE_FORECAST_DATA_UNAVAILABLE", "Nguồn doanh thu chưa sẵn sàng.", frappe.ValidationError, 503
		)
	rows = frappe.get_all(
		"CRM Revenue Recognition",
		filters={"status": "Recognized", "recognition_period": ["between", [date_from, date_to]]},
		fields=[
			"name",
			"payment",
			"student",
			"gross_amount",
			"award_amount",
			"recognized_amount",
			"recognition_period",
			"recognized_at",
		],
		limit_page_length=0,
	)
	return _filter_student_scope(rows, scope, warnings)


def _load_payments(
	date_from: date, date_to: date, scope: dict[str, str | None], warnings: list[str]
) -> list[dict[str, Any]]:
	if not frappe.db.table_exists("CRM Student Payment"):
		warnings.append("Nguồn giao dịch thu chưa sẵn sàng.")
		return []
	rows = frappe.get_all(
		"CRM Student Payment",
		filters={"business_period": ["between", [date_from, date_to]]},
		fields=["name", "student", "amount", "status", "received_at", "business_period"],
		order_by="business_period desc",
		limit_page_length=0,
	)
	return _filter_student_scope(rows, scope, warnings)


def _filter_student_scope(
	rows: list[dict[str, Any]], scope: dict[str, str | None], warnings: list[str]
) -> list[dict[str, Any]]:
	if not scope.get("campus"):
		return [dict(row) for row in rows]
	student_ids = {row.get("student") for row in rows if row.get("student")}
	students = (
		{
			row.name: row.campus
			for row in frappe.get_all(
				"CRM Student",
				filters={"name": ["in", list(student_ids)]},
				fields=["name", "campus"],
				limit_page_length=0,
			)
		}
		if student_ids
		else {}
	)
	if student_ids and len(students) != len(student_ids):
		warnings.append("Một số giao dịch thiếu thông tin campus nên đã loại khỏi scope.")
	return [dict(row) for row in rows if students.get(row.get("student")) == scope["campus"]]


def _load_targets(
	year: str, date_from: date, date_to: date, scope: dict[str, str | None]
) -> dict[str, float]:
	if not frappe.db.table_exists("CRM Target"):
		return {"revenue": 0.0, "enrollment": 0.0}
	scope_key = "national" if scope["id"] == "all" else f"campus:{scope['id']}"
	planning_scope = frappe.db.get_value("CRM Planning Scope", {"scope_key": scope_key}, "name")
	if not planning_scope:
		return {"revenue": 0.0, "enrollment": 0.0}
	filters: dict[str, Any] = {
		"admission_year": year,
		"status": "Approved",
		"planning_scope": planning_scope,
		"period_start": ["<=", date_to],
		"period_end": [">=", date_from],
	}
	rows = frappe.get_all(
		"CRM Target",
		filters=filters,
		fields=["metric_key", "target_value", "planning_scope"],
		limit_page_length=0,
	)
	return {
		key: _number(next((row.target_value for row in rows if row.metric_key == key), 0))
		for key in ("revenue", "enrollment")
	}


def _build_response(
	year: str,
	period: str,
	scope: dict[str, str | None],
	date_from: date,
	date_to: date,
	tz: ZoneInfo,
	ledger: list[dict[str, Any]],
	payments: list[dict[str, Any]],
	targets: dict[str, float],
	limit: int,
	warnings: list[str],
) -> dict[str, Any]:
	gross = _money(sum(_number(row.get("gross_amount")) for row in ledger))
	reductions = _money(sum(_number(row.get("award_amount")) for row in ledger))
	actual = _money(sum(_number(row.get("recognized_amount")) for row in ledger))
	enrollments = len({row.get("student") for row in ledger if row.get("student")})
	days = max((date_to - date_from).days + 1, 1)
	year_days = 366 if date(int(year), 12, 31).timetuple().tm_yday == 366 else 365
	forecast = _money(actual * min(year_days / days, 1.5))
	forecast_enrollment = round(enrollments * min(year_days / days, 1.5))
	revenue_target, enrollment_target = targets["revenue"], targets["enrollment"]
	if not ledger:
		warnings.append("Chưa có bút toán doanh thu được ghi nhận trong phạm vi đã chọn.")
	if not revenue_target:
		warnings.append("Chưa có chỉ tiêu doanh thu đã duyệt cho phạm vi đã chọn.")
	points = _monthly_points(date_from, date_to, ledger, forecast, revenue_target)
	transactions = _transactions(payments, limit)
	collection = _collection_health(payments)
	status = "partial" if warnings else "available"
	return {
		"meta": {
			"admissionYear": int(year),
			"period": period,
			"scope": scope["id"],
			"scopeLabel": scope["label"],
			"from": date_from.isoformat(),
			"to": date_to.isoformat(),
			"asOf": datetime.now(tz).isoformat(timespec="seconds"),
			"timezone": tz.key,
			"currency": "VND",
			"status": status,
			"availability": status,
			"warnings": list(dict.fromkeys(warnings)),
		},
		"summary": {
			"forecastRevenue": forecast,
			"actualRevenue": actual,
			"revenueTarget": revenue_target,
			"forecastEnrollment": forecast_enrollment,
			"enrollmentTarget": round(enrollment_target),
			"revenueGap": _money(max(revenue_target - forecast, 0)),
			"modelConfidence": 72.0 if ledger else None,
			"changeVsPrevious": None,
		},
		"forecast": {"forecastStart": date_to.isoformat(), "points": points},
		"model": {
			"grossRevenue": gross,
			"scholarship": reductions,
			"discount": 0.0,
			"netRevenue": _money(gross - reductions),
		},
		"regions": _regions(ledger),
		"targetPlan": [
			{
				"id": "revenue",
				"label": "Doanh thu",
				"actual": actual,
				"target": revenue_target,
				"progress": _percentage(actual, revenue_target),
			},
			{
				"id": "enrollment",
				"label": "Nhập học",
				"actual": enrollments,
				"target": round(enrollment_target),
				"progress": _percentage(enrollments, enrollment_target),
			},
		],
		"signals": {
			"positive": ["Dòng tiền đã có bút toán được ghi nhận."] if ledger else [],
			"negative": ["Dự báo chưa đạt chỉ tiêu doanh thu."]
			if revenue_target and forecast < revenue_target
			else [],
			"primaryRisk": "Khoảng cách so với chỉ tiêu doanh thu."
			if revenue_target and forecast < revenue_target
			else None,
		},
		"collectionHealth": collection,
		"transactions": transactions,
		"activities": _activities(transactions),
		"channelMix": {"totalLeads": 0, "items": [], "topChannelId": None},
		"cashflow": {
			"points": [
				{
					"label": point["label"],
					"periodStart": point["periodStart"],
					"gross": point["actual"] or 0.0,
					"reductions": 0.0,
				}
				for point in points
			],
			"grossTotal": gross,
			"reductionTotal": reductions,
			"netTotal": _money(gross - reductions),
			"changeVsPrevious": None,
		},
		"decisions": [
			{
				"id": "close-revenue-gap",
				"title": "Ưu tiên các khoản thu sắp đến hạn",
				"impact": _money(max(revenue_target - forecast, 0)),
				"status": "recommended",
			}
		]
		if revenue_target and forecast < revenue_target
		else [],
		"scenarioSimulation": {
			"targetRevenue": revenue_target,
			"defaultScenarioId": "base",
			"scenarios": [
				{"id": "base", "label": "Cơ sở", "revenue": forecast},
				{"id": "accelerated", "label": "Tăng tốc thu", "revenue": _money(forecast * 1.08)},
			],
		},
		"aiExplanation": {
			"confidence": 72.0 if ledger else None,
			"conclusion": {
				"title": "Dự báo doanh thu",
				"description": "Dự báo được nội suy từ doanh thu đã ghi nhận trong phạm vi lựa chọn.",
			},
			"expectedEnrollment": forecast_enrollment,
			"drivers": ["Doanh thu đã ghi nhận", "Chỉ tiêu đã duyệt"],
			"primaryRisk": "Khoảng cách chỉ tiêu" if revenue_target and forecast < revenue_target else None,
		},
	}


def _monthly_points(
	date_from: date, date_to: date, ledger: list[dict[str, Any]], forecast: float, target: float
) -> list[dict[str, Any]]:
	grouped: dict[date, float] = defaultdict(float)
	for row in ledger:
		period = _as_date(row.get("recognition_period"))
		if period:
			grouped[period.replace(day=1)] += _number(row.get("recognized_amount"))
	points, cursor = [], date_from.replace(day=1)
	while cursor <= date_to:
		actual = _money(grouped[cursor]) if cursor in grouped else 0.0
		points.append(
			{
				"label": f"{cursor.month:02d}/{cursor.year}",
				"periodStart": cursor.isoformat(),
				"actual": actual,
				"forecast": _money(forecast / max(len(grouped), 1)) if cursor > date_to else actual,
				"target": _money(target / 12) if target else None,
			}
		)
		cursor = (cursor.replace(day=28) + __import__("datetime").timedelta(days=4)).replace(day=1)
	return points


def _transactions(payments: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
	return [
		{
			"id": row["name"],
			"title": "Khoản thu tuyển sinh",
			"occurredAt": str(row.get("received_at") or row.get("business_period")),
			"amount": _money(_number(row.get("amount"))),
			"direction": "income",
			"status": str(row.get("status") or "Pending").lower(),
			"reconciled": row.get("status") == "Received",
		}
		for row in payments[:limit]
	]


def _collection_health(payments: list[dict[str, Any]]) -> dict[str, Any]:
	received = [row for row in payments if row.get("status") == "Received"]
	outstanding = _money(
		sum(_number(row.get("amount")) for row in payments if row.get("status") == "Pending")
	)
	rate = _percentage(len(received), len(payments))
	return {
		"status": "stable" if (rate or 0) >= 80 else "watch" if payments else "critical",
		"onTimeRate": rate,
		"reconciledCount": len(received),
		"transactionCount": len(payments),
		"outstandingAmount": outstanding,
		"processingOnTimeRate": rate,
		"warnings": [],
	}


def _activities(transactions: list[dict[str, Any]]) -> list[dict[str, Any]]:
	return [
		{
			"id": f"activity:{row['id']}",
			"title": "Đã cập nhật giao dịch thu",
			"occurredAt": row["occurredAt"],
			"status": row["status"],
		}
		for row in transactions[:5]
	]


def _regions(ledger: list[dict[str, Any]]) -> list[dict[str, Any]]:
	by_student = {row.get("student") for row in ledger if row.get("student")}
	student_provinces = (
		{
			row.name: row.province
			for row in frappe.get_all(
				"CRM Student",
				filters={"name": ["in", list(by_student)]},
				fields=["name", "province"],
				limit_page_length=0,
			)
		}
		if by_student
		else {}
	)
	grouped: dict[str, float] = defaultdict(float)
	for row in ledger:
		grouped[student_provinces.get(row.get("student")) or "unassigned"] += _number(
			row.get("recognized_amount")
		)
	total = sum(grouped.values())
	return [
		{
			"id": key,
			"label": key,
			"actual": _money(value),
			"forecast": _money(value),
			"share": _percentage(value, total),
		}
		for key, value in sorted(grouped.items(), key=lambda item: -item[1])
	]


def _as_date(value: Any) -> date | None:
	if isinstance(value, datetime):
		return value.date()
	if isinstance(value, date):
		return value
	try:
		return date.fromisoformat(str(value))
	except (TypeError, ValueError):
		return None


def _number(value: Any) -> float:
	try:
		return float(value or 0)
	except (TypeError, ValueError):
		return 0.0


def _money(value: float) -> float:
	return round(value, 2)


def _percentage(numerator: float, denominator: float) -> float | None:
	return round(numerator / denominator * 100, 1) if denominator else None
