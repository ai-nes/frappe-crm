"""Thin HTTP adapters for Student engagement commands."""

from __future__ import annotations

import frappe

from crm.fcrm.student_engagement import (
	StudentEngagementError,
)
from crm.fcrm.student_engagement import (
	get_outcome_vocabulary as _get_outcome_vocabulary,
)
from crm.fcrm.student_engagement import (
	get_student_context as _get_student_context,
)
from crm.fcrm.student_engagement import (
	record_outcome as _record_outcome,
)
from crm.fcrm.student_engagement import (
	supersede_outcome as _supersede_outcome,
)


def _read(callable_, **kwargs):
	try:
		return callable_(**kwargs)
	except StudentEngagementError as exc:
		exc_type = frappe.PermissionError if exc.code in {"UNAUTHORIZED", "FORBIDDEN", "OUT_OF_SCOPE", "DISABLED"} else frappe.ValidationError
		frappe.throw(str(exc), exc_type)


@frappe.whitelist(methods=["POST"])
def record_student_outcome(**kwargs):
	return _read(_record_outcome, **kwargs)


@frappe.whitelist(methods=["POST"])
def record_outcome(**kwargs):
	return record_student_outcome(**kwargs)


@frappe.whitelist(methods=["POST"])
def supersede_student_outcome(outcome: str, **kwargs):
	return _read(_supersede_outcome, outcome=outcome, **kwargs)


@frappe.whitelist(methods=["POST"])
def supersede_outcome(outcome: str, **kwargs):
	return supersede_student_outcome(outcome=outcome, **kwargs)


@frappe.whitelist()
def get_outcome_vocabulary():
	return _get_outcome_vocabulary()


@frappe.whitelist()
def get_student_context(
	student: str,
	history_limit: int = 20,
	history_page_size: int | None = None,
	history_cursor: str | None = None,
):
	return _get_student_context(
		student,
		history_limit=history_page_size if history_page_size is not None else history_limit,
		history_cursor=history_cursor,
	)
