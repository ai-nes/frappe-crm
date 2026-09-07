"""Student 360 Sales dashboard: durable AI snapshot, live CRM journal/score."""
from __future__ import annotations

import hashlib
from datetime import timezone
from typing import Any

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

from crm.fcrm.intelligence_runs import (
	RUN_TYPES,
	STUDENT_360_POLICY_REVISION,
	STUDENT_360_SNAPSHOT_SCHEMA_VERSION,
	_public_stage,
	_source,
	request_run,
)
from crm.fcrm.scoring_projection import score_band, score_trend

CONTRACT_VERSION = "student360.dashboard.read:v1"
_RUN = RUN_TYPES["student"]


def _iso(value: Any) -> str | None:
	if not value:
		return None
	try:
		return get_datetime(value).replace(tzinfo=timezone.utc).isoformat()
	except Exception:
		return str(value)


def _student_scope(student: str | None) -> str:
	student = str(student or "").strip()
	if frappe.session.user == "Guest":
		frappe.throw(_("Vui lòng đăng nhập để xem toàn cảnh hồ sơ."), frappe.PermissionError)
	if not student or not frappe.has_permission("CRM Lead", "read", student, user=frappe.session.user):
		frappe.throw(_("Bạn không có quyền xem toàn cảnh hồ sơ này."), frappe.PermissionError)
	return student


def _stages(student: str, digest: str | None = None) -> list[dict]:
	runs = frappe.get_all(_RUN, filters={"student": student, "policy_revision": STUDENT_360_POLICY_REVISION, **({"source_digest": digest} if digest else {})}, pluck="name")
	if not runs:
		return []
	return frappe.get_all("CRM Analysis Run Stage", filters={"parent_run_type": _RUN, "parent_run": ["in", runs], "stage_kind": "student_360"}, fields=["name", "stage_kind", "status", "expected_source_digest", "report_json", "claims", "terminal_reason", "policy_revision", "model_revision", "analyzed_at", "modified"], order_by="modified desc, creation desc", limit_page_length=20)


def _snapshot(stage: dict | None) -> dict | None:
	if not stage or stage.get("status") != "completed":
		return None
	report = (_public_stage(stage, student=True).get("report") or {})
	if not report:
		return None
	return {
		"id": stage["name"],
		"analysis_input_digest": stage.get("expected_source_digest"),
		"generated_at": _iso(stage.get("analyzed_at")),
		**report,
	}


def _journal(student: str) -> dict:
	groups = {"inbound": [], "outbound": []}
	rows = frappe.get_all("CRM Interaction", filters={"student": student}, fields=["name", "interaction_datetime", "channel", "direction", "actor", "summary", "outcome"], order_by="interaction_datetime desc, creation desc", limit_page_length=20)
	for row in rows:
		direction = str(row.get("direction") or "").lower()
		if direction in groups:
			groups[direction].append({"id": row["name"], "occurred_at": _iso(row.get("interaction_datetime")), "channel": row.get("channel"), "actor": {"label": row.get("actor") or "Hệ thống", "kind": "staff" if row.get("actor") else "system"}, "summary": row.get("summary") or "", "outcome": row.get("outcome") or None, "evidence_refs": [f"interaction:{row['name']}"]})
	return {"as_of": _iso(now_datetime()), **groups, "next_cursor": None}


def _score(student: str) -> dict:
	rows = frappe.get_all("CRM Score History", filters={"student": student}, fields=["name", "scoring_time", "fit_score", "engagement_score", "intent_score", "final_score", "score_change"], order_by="scoring_time desc, creation desc", limit_page_length=6)
	latest = rows[0] if rows else None
	values = {"fit": latest.get("fit_score") if latest else None, "interaction": latest.get("engagement_score") if latest else None, "intent": latest.get("intent_score") if latest else None, "total": latest.get("final_score") if latest else None}
	score_change = latest.get("score_change") if latest else None
	contributors = []
	if latest:
		for detail in frappe.get_doc("CRM Score History", latest["name"]).get("details") or []:
			contributors.append({"category": detail.category, "signal": detail.signal, "score": detail.score})
	contributors = contributors[:4]
	return {"as_of": _iso(latest.get("scoring_time")) if latest else _iso(now_datetime()), "items": [{"key": key, "label": label, "value": values[key], "score_change": score_change, "contributors": contributors} for key, label in (("fit", "Fit"), ("interaction", "Interaction"), ("intent", "Intent"), ("total", "Total"))], "band": score_band(values["total"]), "trend": score_trend(score_change), "explanation": {"text": "Điểm do CRM tính; bản tóm tắt chỉ trình bày.", "evidence_refs": [f"score:{latest['name']}"] if latest else []}}


@frappe.whitelist()
def get_student_360(student: str, request: bool = False, refresh: bool = False) -> dict:
	"""Return live Sales blocks and optionally request the current snapshot."""
	student = _student_scope(student)
	_revision, digest = _source("student", student)
	current = _stages(student, digest)
	all_stages = _stages(student)
	latest_success = next((x for x in all_stages if x.get("status") == "completed"), None)
	active = next((x for x in current if x.get("status") in {"queued", "running"}), None)
	failed = next((x for x in current if x.get("status") in {"failed", "dead_lettered"}), None)
	request_error = False
	if request or refresh:
		try:
			retry_seed = str(now_datetime()) if refresh else ""
			request_key = hashlib.sha256(f"{frappe.session.user}:{student}:{digest}:{retry_seed}".encode()).hexdigest()[:32]
			request_run(domain="student", target=student, idempotency_key=f"student360:{request_key}")
		except Exception:
			# A dashboard refresh never removes the last successful analysis.
			# Details remain in server logs; the client receives a safe retry state.
			request_error = True
		current = _stages(student, digest)
		all_stages = _stages(student)
		latest_success = next((x for x in all_stages if x.get("status") == "completed"), None)
		active = next((x for x in current if x.get("status") in {"queued", "running"}), active)
		failed = next((x for x in current if x.get("status") in {"failed", "dead_lettered"}), failed)
	displayed = _snapshot(latest_success)
	snapshot_status = "NONE" if not displayed else "FRESH" if latest_success and latest_success.get("expected_source_digest") == digest else "STALE"
	analysis_status = "FAILED" if (failed or request_error) else "ANALYZING" if active else "IDLE"
	displayed = displayed or {}
	score = _score(student)
	items = {item["key"]: item for item in score["items"]}
	return {"student_id": student, "snapshot_schema_version": STUDENT_360_SNAPSHOT_SCHEMA_VERSION, "snapshot_status": snapshot_status, "analysis_status": analysis_status, "analyzed_at": displayed.get("generated_at"), "advisory_signals": displayed.get("advisory_signals", []), "interaction_journal": _journal(student), "score_overview": {"fit": items["fit"].get("value"), "interaction": items["interaction"].get("value"), "intent": items["intent"].get("value"), "total": items["total"].get("value"), "band": score.get("band"), "trend": score.get("trend", {"direction": "UNKNOWN", "delta": None}), "summary": score["explanation"]["text"], "contributors": items["total"].get("contributors", [])}, "risks": displayed.get("risks", []), "opportunity_signals": displayed.get("opportunity_signals", []), "recent_changes": displayed.get("recent_changes", [])}
