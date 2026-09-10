"""Shared rules for the zone-aware Student assignment pipeline.

The module is deliberately read-mostly.  Ownership changes continue to go
through :mod:`student_ownership`; this module only resolves routing context,
filters candidates, and provides manager/reporting façades.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from typing import Any

import frappe
from frappe.utils import now_datetime

from crm.fcrm.student_reference import canonical_student
from crm.fcrm.utils.effective import is_effective

MANUAL_QUEUE = "MANUAL_MANAGER_QUEUE"
ENRICHMENT_QUEUE = "DATA_ENRICHMENT_QUEUE"
REDUCED_LOAD = 0.85
BLOCKED_LOAD = 1.0


def _capacity_required() -> bool:
	"""Return the workspace's strict-capacity mode without breaking old sites."""
	try:
		if frappe.db.exists("DocType", "CRM Assignment Control"):
			value = frappe.db.get_single_value("CRM Assignment Control", "capacity_required")
			if value is not None:
				return value not in (0, "0", False, "false", "False", None)
	except Exception:
		pass
	return False


def _rows(doctype: str, filters: dict, fields: str | list[str] = "*"):

	try:
		return frappe.get_all(doctype, filters=filters, fields=fields, limit_page_length=100)
		# A missing optional geography table must not make ordinary routing fail.
	except Exception:
		return []


def resolve_student_zone(student, at=None) -> dict[str, Any]:
	"""Resolve school first, then ward/province; report conflicts explicitly."""
	at = at or now_datetime()
	at_date = at.date() if hasattr(at, "date") else at
	school_zone = None
	if student.get("high_school"):
		assignments = _rows(
			"CRM High School Assignment",
			{"high_school": student.high_school, "status": "Active", "needs_review": 0},
			["staff", "team", "zone", "assigned_on"],
		)
		zones = sorted({r.get("zone") for r in assignments if r.get("zone")})
		if len(zones) == 1:
			school_zone = zones[0]
		elif len(zones) > 1:
			return {"zone": None, "school_owner": None, "reason": "AMBIGUOUS_SCHOOL_ZONE", "tier": 4}
	province_zone = None
	# Geography implementations differ slightly between deployments.  Prefer
	# Ward, then the province's canonical zone field when available.
	if student.get("ward"):
		try:
			ward = frappe.db.get_value("CRM Ward", student.ward, ["zone", "province"], as_dict=True) or {}
			province_zone = ward.get("zone")
		except Exception:
			province_zone = None
	if school_zone and province_zone and school_zone != province_zone:
		return {"zone": None, "school_owner": None, "reason": "CONFLICTING_GEOGRAPHY", "tier": 4}
	zone = school_zone or province_zone
	owner = None
	owner_team = None
	staff = []
	if student.get("high_school") and zone:
		owners = _rows(
			"CRM High School Assignment",
			{"high_school": student.high_school, "zone": zone, "status": "Active", "needs_review": 0},
			["staff", "team"],
		)
		zone_assignments = _rows(
			"CRM Team Zone Assignment",
			{"zone": zone, "status": "Active", "effective_from": ["<=", at_date]},
			["team", "effective_from", "effective_until"],
		)
		current_teams = sorted({r.get("team") for r in zone_assignments if is_effective(r, at) and r.get("team")})
		staff = sorted(
			{
				r.get("staff")
				for r in owners
				if r.get("staff") and len(current_teams) == 1 and r.get("team") == current_teams[0]
			}
		)
		if staff:
			owner = staff[0]
			owner_team = current_teams[0] if len(current_teams) == 1 else None
	return {
		"zone": zone,
		"school_owner": owner,
		"school_owners": staff,
		"school_owner_team": owner_team,
		"tier": 1 if owner else 2 if zone else 3 if student.get("province") else 4,
		"reason": "school_owner"
		if owner
		else "zone"
		if zone
		else "province"
		if student.get("province")
		else "enrichment",
	}


def zone_team_pool(zone: str, campus: str, at=None) -> dict[str, Any] | None:
	at = (at or now_datetime()).date()
	rows = _rows(
		"CRM Team Zone Assignment",
		{"zone": zone, "status": "Active", "effective_from": ["<=", at]},
		["name", "team", "revision", "effective_from", "effective_until"],
	)
	rows = [r for r in rows if is_effective(r, at)]
	if len(rows) != 1:
		return None
	team = rows[0].get("team")
	pools = _rows(
		"CRM Student Pool",
		{"team": team, "campus": campus, "is_active": 1},
		["name", "team", "campus", "pool_name"],
	)
	if len(pools) != 1:
		return None
	return {
		"zone": zone,
		"team": team,
		"pool": pools[0].name,
		"assignment": rows[0].name,
		"revision": rows[0].get("revision") or 0,
	}


def frozen_mapping_is_current(mapping: dict[str, Any], campus: str) -> bool:
	current = zone_team_pool(mapping.get("zone"), campus)
	return bool(
		current
		and current.get("team") == mapping.get("team")
		and current.get("pool") == mapping.get("pool")
		and str(current.get("revision")) == str(mapping.get("revision"))
	)


def _capacity(staff: str, at=None) -> dict[str, Any]:
	at = at or now_datetime()
	rows = _rows(
		"CRM Staff Capacity Period",
		{"staff": staff, "period_start": ["<=", at.date()], "period_end": [">=", at.date()], "approved": 1},
		["max_active_students", "capacity_units"],
	)
	limit = int((rows[0].get("max_active_students") if rows else 0) or 0)
	active = (
		frappe.db.count(
			"CRM Student", {"owner_staff": staff, "student_stage": ["not in", ["Connected", "Disqualified"]]}
		)
		if limit
		else 0
	)
	today = frappe.db.count(
		"CRM Student Ownership Event",
		{
			"next_owner_staff": staff,
			"event_type": ["in", ["owner_assigned", "reassigned"]],
			"event_at": [">=", datetime.combine(at.date(), time.min)],
		},
	)
	return {
		"limit": limit,
		"configured": bool(limit),
		"active": active,
		"daily": today,
		"load": active / limit if limit else 0.0,
		"eligible": not limit or active < limit,
	}


def capacity_eligible(
	member: dict[str, Any], student=None, *, direct: bool = False
) -> tuple[bool, dict[str, Any]]:
	"""Return eligibility and an explainable snapshot; direct school owners obey the same 100% block."""
	snapshot = _capacity(member["staff"])
	if _capacity_required() and not snapshot["configured"]:
		return False, snapshot
	if snapshot["limit"] and snapshot["active"] >= snapshot["limit"]:
		return False, snapshot
	if snapshot["limit"] and snapshot["daily"] >= snapshot["limit"]:
		return False, snapshot
	# At 85%, retain only a strong school match.  General pool work is not a fit.
	if snapshot["load"] >= REDUCED_LOAD and not direct:
		if (
			not student
			or not student.get("high_school")
			or not frappe.db.exists(
				"CRM High School Assignment",
				{"high_school": student.high_school, "staff": member["staff"], "status": "Active"},
			)
		):
			return False, snapshot
	return True, snapshot


def scoring_weights(policy) -> dict[str, float]:
	default = {"load": 0.35, "territory": 0.30, "performance": 0.20, "rotation": 0.15}
	value = policy.get("scoring_weights") if policy else None
	if isinstance(value, str):
		try:
			value = json.loads(value)
		except ValueError:
			value = None
	if isinstance(value, dict):
		for key in default:
			try:
				default[key] = max(0.0, float(value.get(key, default[key])))
			except (TypeError, ValueError):
				pass
	return default


def score_member(member: dict[str, Any], student, policy=None) -> dict[str, Any]:
	capacity = _capacity(member["staff"])
	load = max(0.0, 1.0 - capacity["load"]) if capacity["limit"] else 1.0
	territory = (
		1.0
		if student.get("high_school")
		and frappe.db.exists(
			"CRM High School Assignment",
			{"high_school": student.high_school, "staff": member["staff"], "status": "Active"},
		)
		else 0.0
	)
	history = _rows(
		"CRM Student Ownership Event",
		{"next_owner_staff": member["staff"], "event_type": ["in", ["owner_assigned", "reassigned"]]},
		["event_at"],
	)
	team_history = _rows(
		"CRM Student Ownership Event",
		{"next_owning_team": member.get("team"), "event_type": ["in", ["owner_assigned", "reassigned"]]},
		["next_owner_staff"],
	)
	performance = 0.5 if len(history) < 5 else min(1.0, len(history) / max(1, len(team_history)))
	last = max((str(x.get("event_at") or "") for x in history), default="")
	rotation = 1.0 if not last else 0.5
	factors = {"load": load, "territory": territory, "performance": performance, "rotation": rotation}
	weights = scoring_weights(policy)
	return {
		"staff": member["staff"],
		"score": sum(factors[k] * weights[k] for k in factors),
		"factors": factors,
		"weights": weights,
		"capacity": capacity,
	}


def fairness_report(
	*,
	zone: str | None = None,
	since: date | None = None,
	until: date | None = None,
	staff_scope: set[str] | None = None,
) -> dict[str, Any]:
	since = since or date.today().replace(day=1)
	until = until or date.today()
	filters = {
		"event_type": ["in", ["owner_assigned", "reassigned"]],
		"event_at": ["between", [datetime.combine(since, time.min), datetime.combine(until, time.max)]],
	}
	rows = _rows(
		"CRM Student Ownership Event", filters, ["next_owner_staff", "event_at", "reason", "student"]
	)
	if staff_scope is not None:
		rows = [row for row in rows if row.get("next_owner_staff") in staff_scope]
	if zone:
		student_ids = []
		for student_name in {r.get("student") for r in rows if r.get("student")}:
			try:
				canonical_name = canonical_student(student_name) or student_name
				student = frappe.get_doc("CRM Student", canonical_name)
				if resolve_student_zone(student).get("zone") == zone:
					student_ids.append(canonical_name)
			except Exception:
				continue
		rows = [r for r in rows if r.get("student") in student_ids]
	counts: dict[str, int] = {}
	transferred: dict[str, int] = {}
	quality: dict[str, list[float]] = {}
	for row in rows:
		staff = row.get("next_owner_staff")
		if not staff:
			continue
		counts[staff] = counts.get(staff, 0) + 1
		if str(row.get("reason") or "").lower().startswith(("manager", "transfer")):
			transferred[staff] = transferred.get(staff, 0) + 1
		try:
			student_name = canonical_student(row.student) or row.student
			student = frappe.get_doc("CRM Student", student_name)
			score = float(student.get("latest_score") or 0)
			quality.setdefault(staff, []).append(score)
		except Exception:
			pass
	values = list(counts.values())
	average = sum(values) / len(values) if values else 0
	quality_average = {staff: sum(scores) / len(scores) for staff, scores in quality.items() if scores}
	quality_values = list(quality_average.values())
	return {
		"since": str(since),
		"until": str(until),
		"zone": zone,
		"counts": counts,
		"manager_transfers": transferred,
		"variance": (max(values) - min(values)) if values else 0,
		"average": average,
		"quality_average": quality_average,
		"quality_variance": (max(quality_values) - min(quality_values)) if quality_values else 0,
		"weekly_review": {
			"week_ending": str(until),
			"actions_required": bool(average and max(values) - min(values) > max(1, average * 0.25)),
		},
		"flagged": bool(average and max(values) - min(values) > max(1, average * 0.25)),
	}


def priority_minutes(policy, priority: str | None) -> int | None:
	"""Return a priority override; ``None`` preserves the existing SLA timer."""
	value = policy.get("priority_deadlines") if policy else None
	if value is None:
		value = getattr(frappe, "conf", {}).get("crm_student_sla_priority_deadlines")
	if isinstance(value, str):
		try:
			value = json.loads(value)
		except (TypeError, ValueError):
			value = None
	if isinstance(value, dict) and priority in value:
		try:
			return max(1, int(value[priority]))
		except (TypeError, ValueError):
			return None
	return None


def next_working_start(value: datetime, policy) -> datetime:
	"""Move off-hours intake to the next weekday working boundary."""
	start = policy.get("working_hours_start") if policy else None
	end = policy.get("working_hours_end") if policy else None
	conf = getattr(frappe, "conf", {})
	start = start or conf.get("crm_student_sla_working_hours_start")
	end = end or conf.get("crm_student_sla_working_hours_end")
	if not start or not end:
		return value
	try:
		start_time = datetime.strptime(str(start), "%H:%M:%S").time()
		end_time = datetime.strptime(str(end), "%H:%M:%S").time()
	except ValueError:
		return value
	if value.weekday() < 5 and start_time <= value.time() <= end_time:
		return value
	next_day = (
		value.date() + timedelta(days=1) if value.time() > end_time or value.weekday() >= 5 else value.date()
	)
	while next_day.weekday() >= 5:
		next_day += timedelta(days=1)
	return datetime.combine(next_day, start_time)


def recall_due(attempt, now=None) -> bool:
	"""Whether an open attempt is eligible for the conservative 2x overdue recall."""
	now = now or now_datetime()
	if attempt.status in {"responded", "closed", "closed_inactive", "superseded"} or not attempt.breach_at:
		return False
	return now >= attempt.breach_at + (attempt.breach_at - attempt.opened_at)
