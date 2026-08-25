"""Whitelisted, scoped adapters for Student routing requests."""

from __future__ import annotations

import frappe
from frappe import _

from crm.fcrm.role_policy import capabilities_for_roles
from crm.fcrm.student_routing import (
	StudentRoutingError,
	get_student_routing_status as _get_status,
	retry_student_routing as _retry,
)


def _require(capability: str):
	actor = frappe.session.user
	roles = frappe.get_roles(actor)
	if capability not in capabilities_for_roles(roles, administrator=actor == "Administrator"):
		frappe.throw(_("You are not permitted to perform this Student routing action."), frappe.PermissionError)


def _read(callable_, **kwargs):
	try:
		return callable_(**kwargs)
	except StudentRoutingError as exc:
		exception_type = frappe.PermissionError if exc.code == "OUT_OF_SCOPE" else frappe.ValidationError
		frappe.throw(_("{0}: {1}").format(exc.code, str(exc)), exception_type)


@frappe.whitelist()
def get_student_routing_status(request: str) -> dict:
	_require("student.routing.read")
	return _read(_get_status, request_name=request)


@frappe.whitelist(methods=["POST"])
def retry_student_routing(request: str) -> dict:
	_require("student.routing.retry")
	return _read(_retry, request_name=request)

