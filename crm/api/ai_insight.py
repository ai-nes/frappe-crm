"""Audited AI insight write-back command.

The command accepts only AI-owned insight data.  Student identity, contact
resolution, revision checks, and the command receipt are all resolved by CRM;
callers cannot choose an arbitrary Contact or mutate human-review fields.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import now_datetime

from crm.fcrm.record_retention import technical_retention_until
from crm.fcrm.student_contact_conversion import contacts_for_student

RECEIPT_DOCTYPE = "CRM Student Command Receipt"
INSIGHT_DOCTYPE = "CRM AI Lead Insight"
ITEM_DOCTYPE = "CRM AI Lead Insight Item"
COMMAND_KIND = "ai_insight"
POLICY_VERSION = "ai-insight"
SCHEMA_VERSION = "ai-insight"

AI_FIELDS = frozenset(
	{
		"ai_score",
		"ai_score_reason",
		"ai_next_action",
		"ai_summary",
		"ai_detected_interests",
		"ai_risk_flags",
	}
)
METADATA_FIELDS = frozenset(
	{
		"ai_generated_at",
		"ai_source_context_revision",
		"ai_policy_version",
		"generation_idempotency_key",
		"command_receipt",
	}
)
ALLOWED_REQUEST_FIELDS = frozenset(
	{
		# WriteBackClient adds this generic alias to every mutation request.  It
		# is transport-only and must match the canonical generation key.
		"idempotency_key",
		"student",
		"expected_context_revision",
		"generation_idempotency_key",
		"producer_identity",
		"ai_policy_version",
		*AI_FIELDS,
	}
)

INTEREST_FIELDS = frozenset(
	{
		"item_kind",
		"dimension_code",
		"label",
		"interest_level",
		"score",
		"trend",
		"stance",
		"confidence",
		"evidence",
	}
)
RISK_FIELDS = frozenset({"item_kind", "label", "severity", "evidence"})
INTEREST_DIMENSIONS = frozenset(
	{
		"COST",
		"PROGRAM_COMPETITOR",
		"CAREER",
		"STUDENT_LIFE",
		"ACCOMMODATION",
		"ENROLLMENT_READINESS",
		"INTERESTED",
		"OTHER",
	}
)
INTEREST_TRENDS = frozenset({"NEW", "STABLE", "INCREASING", "DECREASING", "RESOLVED", "UNKNOWN"})
INTEREST_STANCES = frozenset({"POSITIVE", "NEUTRAL", "NEGATIVE", "UNRESOLVED"})
RISK_SEVERITIES = frozenset({"Low", "Medium", "High"})


class AIInsightError(frappe.ValidationError):
	"""Machine-readable validation failure for the AI insight command."""

	def __init__(self, code: str, message: str):
		self.code = code
		super().__init__(f"{code}: {message}")


class ReadBackVerificationError(AIInsightError):
	"""The database did not contain the values that were just written."""


def _fail(code: str, message: str):
	raise AIInsightError(code, message)


def _require_agent_identity():
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication is required."), frappe.PermissionError)
	if frappe.session.user == "Administrator":
		return
	configured = frappe.conf.get("crm_agents_service_user")
	if not configured or frappe.session.user != configured:
		frappe.throw(
			_("This command is restricted to the crm-agents service identity."), frappe.PermissionError
		)


def _required_text(value: Any, fieldname: str, *, max_length: int = 140) -> str:
	value = str(value or "").strip()
	if not value:
		_fail("INVALID_INPUT", _("{0} is required.").format(fieldname))
	if len(value) > max_length:
		_fail("INVALID_INPUT", _("{0} exceeds the maximum length.").format(fieldname))
	return value


def _optional_text(value: Any, fieldname: str, *, max_length: int | None = None) -> str | None:
	if value is None:
		return None
	if not isinstance(value, str):
		_fail("INVALID_INPUT", _("{0} must be text.").format(fieldname))
	value = value.strip()
	if max_length is not None and len(value) > max_length:
		_fail("INVALID_INPUT", _("{0} exceeds the maximum length.").format(fieldname))
	return value


def _optional_score(value: Any) -> float | None:
	if value is None:
		return None
	try:
		score = float(value)
	except (TypeError, ValueError):
		_fail("INVALID_INPUT", _("ai_score must be numeric."))
	if score < 0 or score > 100:
		_fail("INVALID_INPUT", _("ai_score must be between 0 and 100."))
	return score


def _as_list(value: Any, fieldname: str) -> list[Any]:
	if isinstance(value, str):
		try:
			value = frappe.parse_json(value)
		except Exception:
			_fail("INVALID_INPUT", _("{0} must be a JSON array.").format(fieldname))
	if value is None:
		return []
	if not isinstance(value, list):
		_fail("INVALID_INPUT", _("{0} must be an array.").format(fieldname))
	return value


def _validate_item_fields(item: dict[str, Any], allowed: frozenset[str], fieldname: str):
	unsupported = sorted(set(item) - allowed)
	if unsupported:
		_fail(
			"INVALID_FIELD",
			_("{0} contains unsupported fields: {1}.").format(fieldname, ", ".join(unsupported)),
		)


def _normalize_interest(value: Any, index: int) -> dict[str, Any]:
	fieldname = f"ai_detected_interests[{index}]"
	if isinstance(value, str):
		label = _required_text(value, fieldname, max_length=500)
		return {
			"dimension_code": label if label in INTEREST_DIMENSIONS else "OTHER",
			"label": label,
		}
	if not isinstance(value, dict):
		_fail("INVALID_INPUT", _("{0} must be text or an object.").format(fieldname))
	_validate_item_fields(value, INTEREST_FIELDS, fieldname)
	if value.get("item_kind") not in (None, "", "interest"):
		_fail("INVALID_INPUT", _("{0}.item_kind must be interest.").format(fieldname))
	item = {key: value[key] for key in INTEREST_FIELDS if key in value and value[key] is not None}
	item.pop("item_kind", None)
	if item.get("dimension_code") in (None, "") and item.get("label") in (None, ""):
		_fail("INVALID_INPUT", _("{0} needs a dimension_code or label.").format(fieldname))
	if item.get("dimension_code") in (None, ""):
		item["dimension_code"] = "OTHER"
	if item["dimension_code"] not in INTEREST_DIMENSIONS:
		_fail("INVALID_INPUT", _("{0}.dimension_code is unsupported.").format(fieldname))
	if item.get("label") is not None:
		item["label"] = _required_text(item["label"], f"{fieldname}.label", max_length=500)
	if item.get("trend") not in (None, "") and item["trend"] not in INTEREST_TRENDS:
		_fail("INVALID_INPUT", _("{0}.trend is unsupported.").format(fieldname))
	if item.get("stance") not in (None, "") and item["stance"] not in INTEREST_STANCES:
		_fail("INVALID_INPUT", _("{0}.stance is unsupported.").format(fieldname))
	return item


def _normalize_risk(value: Any, index: int) -> dict[str, Any]:
	fieldname = f"ai_risk_flags[{index}]"
	if isinstance(value, str):
		return {"label": _required_text(value, fieldname, max_length=500)}
	if not isinstance(value, dict):
		_fail("INVALID_INPUT", _("{0} must be text or an object.").format(fieldname))
	_validate_item_fields(value, RISK_FIELDS, fieldname)
	if value.get("item_kind") not in (None, "", "risk"):
		_fail("INVALID_INPUT", _("{0}.item_kind must be risk.").format(fieldname))
	item = {key: value[key] for key in RISK_FIELDS if key in value and value[key] is not None}
	item.pop("item_kind", None)
	if not item.get("label"):
		_fail("INVALID_INPUT", _("{0}.label is required.").format(fieldname))
	item["label"] = _required_text(item["label"], f"{fieldname}.label", max_length=500)
	if item.get("severity") not in (None, "") and item["severity"] not in RISK_SEVERITIES:
		_fail("INVALID_INPUT", _("{0}.severity is unsupported.").format(fieldname))
	return item


def _normalize_request(kwargs: dict[str, Any]) -> dict[str, Any]:
	unsupported = sorted(set(kwargs) - ALLOWED_REQUEST_FIELDS)
	if unsupported:
		_fail("INVALID_FIELD", _("Unsupported AI insight fields: {0}.").format(", ".join(unsupported)))
	student = _required_text(kwargs.get("student"), "student")
	key = _required_text(kwargs.get("generation_idempotency_key"), "generation_idempotency_key")
	if "idempotency_key" in kwargs and _required_text(kwargs["idempotency_key"], "idempotency_key") != key:
		_fail("INVALID_INPUT", "idempotency_key must match generation_idempotency_key.")
	producer = _required_text(kwargs.get("producer_identity"), "producer_identity")
	policy_version = _required_text(kwargs.get("ai_policy_version"), "ai_policy_version")
	try:
		expected_revision = int(kwargs.get("expected_context_revision"))
	except (TypeError, ValueError):
		_fail("INVALID_REVISION", "expected_context_revision must be a non-negative integer.")
	if expected_revision < 0:
		_fail("INVALID_REVISION", "expected_context_revision must be a non-negative integer.")

	request = {
		"student": student,
		"expected_context_revision": expected_revision,
		"generation_idempotency_key": key,
		"producer_identity": producer,
		"ai_policy_version": policy_version,
	}
	if "ai_score_reason" in kwargs:
		request["ai_score_reason"] = _optional_text(kwargs["ai_score_reason"], "ai_score_reason")
	if "ai_score" in kwargs:
		request["ai_score"] = _optional_score(kwargs["ai_score"])
	if "ai_next_action" in kwargs:
		request["ai_next_action"] = _optional_text(kwargs["ai_next_action"], "ai_next_action", max_length=140)
	if "ai_summary" in kwargs:
		request["ai_summary"] = _optional_text(kwargs["ai_summary"], "ai_summary")
	if "ai_detected_interests" in kwargs:
		request["ai_detected_interests"] = [
			_normalize_interest(item, index)
			for index, item in enumerate(_as_list(kwargs["ai_detected_interests"], "ai_detected_interests"))
		]
	if "ai_risk_flags" in kwargs:
		request["ai_risk_flags"] = [
			_normalize_risk(item, index)
			for index, item in enumerate(_as_list(kwargs["ai_risk_flags"], "ai_risk_flags"))
		]
	return request


def _canonical(value: Any) -> str:
	return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def _fingerprint(request: dict[str, Any]) -> str:
	return hashlib.sha256(_canonical(request).encode()).hexdigest()


def _command_key(generation_idempotency_key: str) -> str:
	return hashlib.sha256(f"{COMMAND_KIND}|{generation_idempotency_key}".encode()).hexdigest()


def _read_receipt(command_key: str, fingerprint: str) -> dict[str, Any] | None:
	name = frappe.db.get_value(RECEIPT_DOCTYPE, {"command_key": command_key}, "name")
	if not name:
		return None
	receipt = frappe.get_doc(RECEIPT_DOCTYPE, name)
	if receipt.get("request_fingerprint") != fingerprint:
		_fail("IDEMPOTENCY_KEY_REUSED", "The generation idempotency key was already used for another request.")
	try:
		result = json.loads(receipt.get("result_json") or "{}")
	except (TypeError, ValueError):
		result = {}
	if not isinstance(result, dict):
		result = {}
	student = receipt.get("target_student")
	if student and frappe.db.exists("CRM Student", student):
		result["current_revision"] = int(frappe.db.get_value("CRM Student", student, "student_context_revision") or 0)
	outcome = receipt.get("outcome")
	if outcome == "pending":
		# A previous worker may have crashed after creating the receipt but
		# before settling it.  Let the caller recover the same receipt instead
		# of replaying a permanently non-terminal result.
		return None
	result.update(
		{
			"applied": False,
			"duplicate": outcome == "applied",
			"replayed": True,
			"receipt": receipt.name,
		}
	)
	if outcome == "failed":
		result["failed"] = True
	return result


def _new_receipt(command_key: str, fingerprint: str, request: dict[str, Any]):
	return frappe.get_doc(
		{
			"doctype": RECEIPT_DOCTYPE,
			"receipt_key": command_key,
			"command_key": command_key,
			"command_kind": COMMAND_KIND,
			"request_fingerprint": fingerprint,
			"outcome": "pending",
			"target_student": request["student"],
			"actor": frappe.session.user,
			"scope_snapshot": {
				"actor": frappe.session.user,
				"student": request["student"],
				"producer_identity": request["producer_identity"],
			},
			"policy_version": request["ai_policy_version"],
			"schema_version": SCHEMA_VERSION,
			"correlation_token": request["generation_idempotency_key"],
			"request_received_at": now_datetime(),
		}
	).insert(ignore_permissions=True)


def _finish_receipt(receipt, result: dict[str, Any], *, outcome: str, error_code: str | None = None):
	values = {
		"outcome": outcome,
		"result_json": json.dumps(result, default=str),
		"completed_at": now_datetime(),
		"retention_until": technical_retention_until("receipt"),
	}
	if error_code:
		values["error_code"] = error_code
	for fieldname, value in values.items():
		receipt.db_set(fieldname, value, update_modified=False)


def _lock_student(student: str):
	row = frappe.db.sql(
		"SELECT name, student_context_revision FROM `tabCRM Student` WHERE name = %s FOR UPDATE",
		(student,),
		as_dict=True,
	)
	if not row:
		_fail("NOT_FOUND", "The Student does not exist.")
	return row[0]


def _lock_contact_for_student(student: str) -> str:
	contacts = list(dict.fromkeys(contact for contact in contacts_for_student(student) if contact))
	if not contacts:
		_fail("CONTACT_REQUIRED", "The Student has no linked CRM Student.")
	if len(contacts) > 1:
		_fail("AMBIGUOUS_CONTACT", "The Student has more than one linked CRM Student.")
	contact = contacts[0]
	row = frappe.db.sql(
		"SELECT name FROM `tabCRM Student` WHERE name = %s FOR UPDATE",
		(contact,),
		as_dict=True,
	)
	if not row:
		_fail("NOT_FOUND", "The linked CRM Contact does not exist.")
	return contact


def _current_insight(student: str):
	rows = frappe.db.sql(
		"""
		SELECT name
		FROM `tabCRM AI Lead Insight`
		WHERE student = %s AND insight_type = 'Conversation Summary'
		ORDER BY ai_generated_at DESC, generated_at DESC, creation DESC, name DESC
		LIMIT 1
		FOR UPDATE
		""",
		(student,),
		as_dict=True,
	)
	return frappe.get_doc(INSIGHT_DOCTYPE, rows[0].name) if rows else None


def _item_rows(interests: list[dict[str, Any]], risks: list[dict[str, Any]]) -> list[dict[str, Any]]:
	return [{"item_kind": "interest", **item} for item in interests] + [
		{"item_kind": "risk", **item} for item in risks
	]


def _replace_items(insight_name: str, interests: list[dict[str, Any]], risks: list[dict[str, Any]]):
	frappe.db.delete(ITEM_DOCTYPE, {"parent": insight_name, "parenttype": INSIGHT_DOCTYPE, "parentfield": "items"})
	for index, item in enumerate(_item_rows(interests, risks), start=1):
		frappe.get_doc(
			{
				"doctype": ITEM_DOCTYPE,
				"parent": insight_name,
				"parenttype": INSIGHT_DOCTYPE,
				"parentfield": "items",
				"idx": index,
				**item,
			}
		).insert(ignore_permissions=True)


def _json_list(value: Any, fieldname: str) -> list[Any]:
	if value in (None, ""):
		return []
	if isinstance(value, str):
		try:
			value = frappe.parse_json(value)
		except Exception:
			_raise_readback(fieldname)
	if not isinstance(value, list):
		_raise_readback(fieldname)
	return value


def _raise_readback(fieldname: str):
	raise ReadBackVerificationError("READ_BACK_VERIFICATION_FAILED", f"Read-back verification failed for {fieldname}.")


def _readback_items(insight) -> list[dict[str, Any]]:
	items = []
	for row in insight.get("items") or []:
		item_kind = row.get("item_kind")
		if item_kind == "interest":
			items.append(
				{
					"item_kind": item_kind,
					**{
						key: row.get(key)
						for key in INTEREST_FIELDS
						if key != "item_kind" and row.get(key) is not None
					},
				}
			)
		elif item_kind == "risk":
			items.append(
				{
					"item_kind": item_kind,
					**{
						key: row.get(key)
						for key in RISK_FIELDS
						if key != "item_kind" and row.get(key) is not None
					},
				}
			)
		else:
			_raise_readback("items.item_kind")
	return items


def _verify_readback(insight_name: str, expected: dict[str, Any], expected_items: list[dict[str, Any]]):
	readback = frappe.get_doc(INSIGHT_DOCTYPE, insight_name)
	for fieldname, expected_value in expected.items():
		actual_value = readback.get(fieldname)
		if fieldname in {"ai_detected_interests", "ai_risk_flags"}:
			actual_value = _json_list(actual_value, fieldname)
		if fieldname == "ai_source_context_revision":
			try:
				actual_value = int(actual_value or 0)
			except (TypeError, ValueError):
				_raise_readback(fieldname)
		if _canonical(actual_value) != _canonical(expected_value):
			_raise_readback(fieldname)
	actual_items = _readback_items(readback)
	if len(actual_items) != len(expected_items):
		_raise_readback("items")
	for expected_item, actual_item in zip(expected_items, actual_items, strict=True):
		if expected_item.get("item_kind") != actual_item.get("item_kind"):
			_raise_readback("items.item_kind")
		for fieldname, expected_value in expected_item.items():
			if fieldname != "item_kind" and _canonical(actual_item.get(fieldname)) != _canonical(expected_value):
				_raise_readback(f"items.{fieldname}")
	return readback


def _result(*, insight_name: str | None, receipt_name: str, applied: bool, duplicate: bool, stale: bool, current_revision: int, **extra):
	return {
		"applied": applied,
		"duplicate": duplicate,
		"stale": stale,
		"current_revision": current_revision,
		"insight": insight_name,
		"receipt": receipt_name,
		**extra,
	}


@frappe.whitelist(methods=["POST"])
def upsert_ai_insight(**kwargs) -> dict[str, Any]:
	"""Atomically upsert the current AI insight for a Student's Contact.

	The command is idempotent by ``generation_idempotency_key`` and accepts a
	write only when ``expected_context_revision`` still equals the locked
	Student projection.  A stale request is a settled non-write; it is not a
	retryable exception.
	"""
	_require_agent_identity()
	request = _normalize_request(kwargs)
	fingerprint = _fingerprint(request)
	command_key = _command_key(request["generation_idempotency_key"])
	if replay := _read_receipt(command_key, fingerprint):
		return replay
	try:
		receipt = _new_receipt(command_key, fingerprint, request)
	except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
		frappe.db.rollback()
		existing_name = frappe.db.get_value(RECEIPT_DOCTYPE, {"command_key": command_key}, "name")
		if existing_name:
			existing_receipt = frappe.get_doc(RECEIPT_DOCTYPE, existing_name)
			if existing_receipt.get("request_fingerprint") != fingerprint:
				_fail("IDEMPOTENCY_KEY_REUSED", "The generation idempotency key was already used for another request.")
			if existing_receipt.get("outcome") == "pending":
				receipt = existing_receipt
			else:
				if replay := _read_receipt(command_key, fingerprint):
					return replay
				raise
		else:
			raise

	savepoint = f"ai_insight_{frappe.generate_hash(length=8)}"
	frappe.db.savepoint(savepoint)
	try:
		student_row = _lock_student(request["student"])
		current_revision = int(student_row.get("student_context_revision") or 0)
		if current_revision != request["expected_context_revision"]:
			result = _result(
				insight_name=None,
				receipt_name=receipt.name,
				applied=False,
				duplicate=False,
				stale=True,
				current_revision=current_revision,
			)
			_finish_receipt(receipt, result, outcome="rejected", error_code="STALE_REVISION")
			return result

		contact = _lock_contact_for_student(request["student"])
		if frappe.db.exists(INSIGHT_DOCTYPE, {"generation_idempotency_key": request["generation_idempotency_key"]}):
			_fail("IDEMPOTENCY_KEY_REUSED", "The generation idempotency key already belongs to another insight.")

		insight = _current_insight(request["student"])
		ai_generated_at = now_datetime()
		if insight:
			previous_interests = _json_list(insight.get("ai_detected_interests"), "ai_detected_interests")
			previous_risks = _json_list(insight.get("ai_risk_flags"), "ai_risk_flags")
		else:
			previous_interests = []
			previous_risks = []

		interests = request.get("ai_detected_interests", previous_interests)
		risks = request.get("ai_risk_flags", previous_risks)
		updates = {
			"student": request["student"],
			"producer_identity": request["producer_identity"],
			"payload_digest": fingerprint,
			"ai_generated_at": ai_generated_at,
			"generated_at": ai_generated_at,
			"ai_source_context_revision": current_revision,
			"ai_policy_version": request["ai_policy_version"],
			"generation_idempotency_key": request["generation_idempotency_key"],
			"command_receipt": receipt.name,
			"ai_detected_interests": interests,
			"ai_risk_flags": risks,
		}
		for fieldname in AI_FIELDS - {"ai_detected_interests", "ai_risk_flags"}:
			if fieldname in request:
				updates[fieldname] = request[fieldname]
		is_new_insight = insight is None
		if insight:
			db_updates = dict(updates)
			db_updates["ai_detected_interests"] = frappe.as_json(interests)
			db_updates["ai_risk_flags"] = frappe.as_json(risks)
			frappe.db.set_value(INSIGHT_DOCTYPE, insight.name, db_updates, update_modified=True)
			insight_name = insight.name
		else:
			insert_updates = dict(updates)
			insert_updates["ai_detected_interests"] = frappe.as_json(interests)
			insert_updates["ai_risk_flags"] = frappe.as_json(risks)
			insight = frappe.get_doc(
				{
					"doctype": INSIGHT_DOCTYPE,
					"contact": contact,
					"student": request["student"],
					"insight_type": "Conversation Summary",
					**insert_updates,
				}
			).insert(ignore_permissions=True)
			insight_name = insight.name

		if "ai_detected_interests" in request or "ai_risk_flags" in request or is_new_insight:
			_replace_items(insight_name, interests, risks)

		expected_fields = dict(updates)
		expected_items = _item_rows(interests, risks)
		_verified = _verify_readback(insight_name, expected_fields, expected_items)
		result = _result(
			insight_name=insight_name,
			receipt_name=receipt.name,
			applied=True,
			duplicate=False,
			stale=False,
			current_revision=current_revision,
			producer_identity=request["producer_identity"],
		)
		_finish_receipt(receipt, result, outcome="applied")
		return result
	except ReadBackVerificationError as exc:
		frappe.db.rollback(save_point=savepoint)
		result = _result(
			insight_name=None,
			receipt_name=receipt.name,
			applied=False,
			duplicate=False,
			stale=False,
			current_revision=int(frappe.db.get_value("CRM Student", request["student"], "student_context_revision") or 0),
			error_code=exc.code,
			verification_failed=True,
		)
		_finish_receipt(receipt, result, outcome="failed", error_code=exc.code)
		return result
	except Exception as exc:
		frappe.db.rollback(save_point=savepoint)
		error_code = exc.code if isinstance(exc, AIInsightError) else "INTERNAL_ERROR"
		try:
			current_revision = int(
				frappe.db.get_value(
					"CRM Student", request["student"], "student_context_revision"
				)
				or 0
			)
		except Exception:
			current_revision = 0
		try:
			_finish_receipt(
				receipt,
				{
					"applied": False,
					"duplicate": False,
					"stale": False,
					"current_revision": current_revision,
					"receipt": receipt.name,
				},
				outcome="failed",
				error_code=error_code,
			)
		except Exception:
			frappe.log_error(
				message=frappe.get_traceback(),
				title="AI insight receipt settlement failed",
			)
		else:
			# The command owns the transaction after rolling back its savepoint.
			# Commit the terminal receipt before propagating the business error so
			# the next retry can observe a durable failure rather than a poison
			# pending row.
			frappe.db.commit()
		raise
