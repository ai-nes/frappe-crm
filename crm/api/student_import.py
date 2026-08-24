"""Compatibility adapter for the retired legacy Student import route.

The old endpoint performed a global phone/email upsert and was guest writable.
It now delegates to the canonical intake command. It remains available only to
authenticated callers during provider reconciliation; external providers must
use :mod:`crm.api.student_intake_webhook`.
"""

from __future__ import annotations

import json
from typing import Any

import frappe

from crm.fcrm.student_intake import normalize_email, normalize_phone, submit_intake

LEGACY_LEAD_STATUS_MAP = {
	"New": "Mới",
	"Prospect": "Có triển vọng",
	"Pending Confirmation": "Đã xác nhận",
	"Confirmed": "Đã xác nhận",
	"Enrolled": "Đã nhập học",
	"Converted": "Đã chuyển đổi",
	"Rejected": "Từ chối",
	"Refused": "Từ chối",
	"Deferred": "Từ chối",
	"Withdrawn": "Từ chối",
	"Promising": "Có triển vọng",
}


def _parse_payload(payload: dict[str, Any] | str | None):
	if payload is None:
		try:
			payload = frappe.request.get_json(silent=True)
		except Exception:
			payload = None
	if isinstance(payload, str):
		try:
			payload = json.loads(payload)
		except ValueError:
			frappe.throw("payload phải là JSON object hợp lệ.", title="Payload không hợp lệ")
	if not isinstance(payload, dict):
		frappe.throw("payload phải là JSON object.", title="Payload không hợp lệ")
	return payload


def _compatibility_payload(payload: dict[str, Any]) -> dict[str, Any]:
	first = str(payload.get("firstname") or "").strip()
	last = str(payload.get("lastname") or "").strip()
	values = {
		"student_name": " ".join(value for value in (first, last) if value),
		"phone": payload.get("mobile") or payload.get("phone"),
		"email": payload.get("email"),
		"id_number": payload.get("id_number") or payload.get("national_id") or payload.get("cccd"),
		"campus": payload.get("leads_campus") or payload.get("campus") or payload.get("branch"),
		"admission_year": payload.get("cf_registered_year") or payload.get("admission_year"),
		"source": payload.get("leadsource") or payload.get("source"),
		"advertising_channel": payload.get("cf_kenh_quang_cao") or payload.get("advertising_channel"),
		"enrollment_status": LEGACY_LEAD_STATUS_MAP.get(payload.get("leadstatus"), payload.get("leadstatus")),
	}
	for source, target in (
		("cf_city", "province"),
		("cf_school", "high_school"),
		("cf_major", "major"),
		("cf_nvfpt", "aspiration"),
		("alt_name", "alt_name"),
		("alt_phone", "alt_phone"),
	):
		if payload.get(source):
			values[target] = payload[source]
	return {key: value for key, value in values.items() if value not in (None, "")}


@frappe.whitelist(methods=["POST"])
def upsert_student(
	payload: dict[str, Any] | str | None = None,
	source_namespace: str | None = None,
	source_record_id: str | None = None,
	idempotency_key: str | None = None,
	correlation_id: str | None = None,
) -> dict[str, Any]:
	"""Compatibility name; behavior is now deterministic intake only."""
	if getattr(frappe, "session", None) and frappe.session.user in ("Guest", ""):
		frappe.throw("Authentication is required for the retired import adapter.", frappe.PermissionError)
	payload = _parse_payload(payload)
	if not source_namespace:
		source_namespace = payload.get("source_namespace") or "legacy-student-import"
	if not source_record_id:
		source_record_id = payload.get("source_record_id") or payload.get("id") or payload.get("external_id")
	if not idempotency_key:
		idempotency_key = payload.get("idempotency_key")
	if not source_record_id or not idempotency_key:
		frappe.throw("source_record_id và idempotency_key là bắt buộc.", title="Legacy import đã bị khóa")
	result = submit_intake(
		_compatibility_payload(payload),
		source_namespace=source_namespace,
		source_record_id=str(source_record_id),
		idempotency_key=str(idempotency_key),
		correlation_id=correlation_id or payload.get("correlation_id"),
	)
	return {"name": result.get("student"), "action": result.get("outcome"), **result}


_normalize_phone = normalize_phone
_normalize_email = normalize_email
