"""Whitelisted privacy-right request endpoints."""

from __future__ import annotations

import frappe

from crm.fcrm.student_privacy import (
	open_privacy_request as _open_privacy_request,
	resolve_privacy_request as _resolve_privacy_request,
)


@frappe.whitelist(methods=["POST"])
def open_request(student: str, request_type: str, details: str | None = None, contact: str | None = None) -> dict:
	return _open_privacy_request(student, request_type, details=details, contact=contact)


@frappe.whitelist(methods=["POST"])
def resolve_request(name: str, status: str, resolution: str, evidence_reference: str | None = None) -> dict:
	return _resolve_privacy_request(name, status, resolution, evidence_reference=evidence_reference)
