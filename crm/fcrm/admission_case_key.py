"""The transaction-safe command for resolving one Student Case Key."""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from typing import Any

import frappe
from frappe import _

from crm.fcrm.admissions_canonical_contracts import canonical_case_key
from crm.fcrm.admissions_migration import stable_fingerprint

COMMAND_KIND = "case_key"


@contextmanager
def _case_key_writer_context():
	previous = getattr(frappe.flags, "case_key_writer", False)
	frappe.flags.case_key_writer = True
	try:
		yield
	finally:
		frappe.flags.case_key_writer = previous


def _command_key(identity: str, admission_year: str) -> str:
	return hashlib.sha256(f"{COMMAND_KIND}|{identity}|{admission_year}".encode()).hexdigest()


def _receipt(command_key: str, fingerprint: str):
	return frappe.db.get_value(
		"CRM Student Command Receipt",
		{"command_key": command_key},
		["name", "request_fingerprint", "target_student", "target_case_key", "result_json", "outcome"],
		as_dict=True,
	)


def _write_receipt(
	*,
	command_key: str,
	fingerprint: str,
	identity: str,
	admission_year: str,
	student: str,
	case_key: str,
	correlation_token: str | None,
):
	values = {
		"doctype": "CRM Student Command Receipt",
		"receipt_key": f"CASEKEY:{command_key}",
		"command_kind": COMMAND_KIND,
		"command_key": command_key,
		"source_key": f"case-key:{identity}:{admission_year}",
		"nonce_key": f"case-key:{command_key}",
		"request_fingerprint": fingerprint,
		"outcome": "attached",
		"target_student": student,
		"target_case_key": case_key,
		"actor": frappe.session.user,
		"schema_version": "admissions-erd-v2",
		"policy_version": "admissions-case-key-v1",
		"correlation_token": correlation_token or command_key,
		"request_received_at": frappe.utils.now_datetime(),
		"completed_at": frappe.utils.now_datetime(),
		"result_json": json.dumps({"student": student, "case_key": case_key}, separators=(",", ":")),
	}
	try:
		return frappe.get_doc(values).insert(ignore_permissions=True)
	except frappe.DuplicateEntryError:
		existing = _receipt(command_key, fingerprint)
		if existing and existing.request_fingerprint != fingerprint:
			frappe.throw(
				_("This Case Key command was already used with different input."), frappe.ValidationError
			)
		return existing


def _result(case_key: str, student: str, receipt, replayed: bool) -> dict[str, Any]:
	return {
		"case_key": case_key,
		"student": student,
		"receipt": receipt.name,
		"replayed": replayed,
		"schema_version": "admissions-erd-v2",
	}


def ensure_case_key(
	*,
	identity: str,
	admission_year: str,
	canonical_student: str,
	source_reference: str | None = None,
	correlation_token: str | None = None,
) -> dict[str, Any]:
	"""Attach exactly one case key to a Student, replaying the same command safely."""

	identity = str(identity or "").strip()
	admission_year = str(admission_year or "").strip()
	canonical_student = str(canonical_student or "").strip()
	if not identity or not admission_year or not canonical_student:
		frappe.throw(
			_("Identity, admission year and canonical Student are required."), frappe.ValidationError
		)
	case_key = canonical_case_key(identity, admission_year)
	command_key = _command_key(identity, admission_year)
	fingerprint = stable_fingerprint(identity, admission_year, canonical_student, source_reference)
	if existing := _receipt(command_key, fingerprint):
		if existing.request_fingerprint != fingerprint:
			frappe.throw(
				_("This Case Key command was already used with different input."), frappe.ValidationError
			)
		return _result(existing.target_case_key, existing.target_student, existing, True)

	student = frappe.db.sql(
		"SELECT name, identity, admission_year, case_key FROM `tabCRM Lead` WHERE name = %s FOR UPDATE",
		(canonical_student,),
		as_dict=True,
	)
	if not student:
		frappe.throw(_("Canonical Student does not exist."), frappe.DoesNotExistError)
	student = student[0]
	if student.identity not in (None, "", identity) or student.admission_year not in (
		None,
		"",
		admission_year,
	):
		frappe.throw(
			_("Student identity and admission year do not match the Case Key command."),
			frappe.ValidationError,
		)
	if student.case_key not in (None, "", case_key):
		frappe.throw(_("Student already points to another Case Key."), frappe.DuplicateEntryError)

	row = frappe.db.sql(
		"SELECT name, canonical_student, identity, admission_year FROM `tabCRM Student Case Key` WHERE identity = %s AND admission_year = %s FOR UPDATE",
		(identity, admission_year),
		as_dict=True,
	)
	if row:
		row = row[0]
		if row.canonical_student != canonical_student:
			frappe.throw(
				_("The Case Key is already attached to another canonical Student."),
				frappe.DuplicateEntryError,
			)
		case_name = row.name
	else:
		try:
			with _case_key_writer_context():
				case = frappe.get_doc(
					{
						"doctype": "CRM Student Case Key",
						"case_key": case_key,
						"identity": identity,
						"admission_year": admission_year,
						"canonical_student": canonical_student,
						"source_student": canonical_student,
						"integrity_state": "resolved",
						"schema_version": "admissions-erd-v2",
					}
				).insert(ignore_permissions=True)
			case_name = case.name
		except frappe.DuplicateEntryError:
			row = frappe.db.get_value(
				"CRM Student Case Key",
				{"identity": identity, "admission_year": admission_year},
				["name", "canonical_student"],
				as_dict=True,
			)
			if not row or row.canonical_student != canonical_student:
				frappe.throw(
					_("A concurrent Case Key command resolved a conflicting Student."),
					frappe.DuplicateEntryError,
				)
			case_name = row.name

	frappe.db.set_value("CRM Lead", canonical_student, "case_key", case_name, update_modified=False)
	receipt = _write_receipt(
		command_key=command_key,
		fingerprint=fingerprint,
		identity=identity,
		admission_year=admission_year,
		student=canonical_student,
		case_key=case_name,
		correlation_token=correlation_token,
	)
	return _result(case_name, canonical_student, receipt, False)
