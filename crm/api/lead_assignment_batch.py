"""Explicit CRM Lead assignment batches.

Lead intake is deliberately separate from assignment.  A user imports or
selects Leads into a batch, previews the routing context, then starts one
bounded execution.  This module is the only batch-facing entrypoint; the
actual owner transition still goes through ``student_ownership`` and the
zone/capacity selector remains shared with the legacy Student service.
"""

from __future__ import annotations

import uuid
from typing import Any

import frappe
from frappe import _
from frappe.utils import getdate, now_datetime, today

from crm.api import lead_mapping
from crm.api.assignment_workspace import _actor_context
from crm.fcrm.lead_processing import mark_lead_assigned, preview_lead, process_lead
from crm.fcrm.lead_routing import route_lead_now
from crm.fcrm.student_assignment import (
	ENRICHMENT_QUEUE,
	MANUAL_QUEUE,
	resolve_student_zone,
	zone_team_pool,
)
from crm.fcrm.student_ownership import change_student_ownership

BATCH_DOCTYPE = "CRM Lead Assignment Batch"
MAX_BATCH_SIZE = 1000
RUNNABLE_STATUSES = {"draft", "ready", "completed_with_errors"}
TERMINAL_ITEM_STATUSES = {"assigned", "skipped"}
BATCH_IMPORT_REQUIRED_HEADERS = frozenset(
	{"student_name", "phone", "province", "high_school", "major", "id_number", "source"}
)


def _require_access():
	context = _actor_context()
	capabilities = set(context["capabilities"])
	if not context.get("is_system_manager") and "student.routing.operate" not in capabilities:
		frappe.throw(
			_("Bạn không có quyền thực hiện phân công theo đợt."),
			frappe.PermissionError,
		)
	return context


def _require_read_access():
	"""Allow routing readers to inspect batch history without granting mutations."""
	context = _actor_context()
	capabilities = set(context["capabilities"])
	if not context.get("is_system_manager") and not capabilities.intersection(
		{"student.routing.read", "student.routing.operate"}
	):
		frappe.throw(
			_("Bạn không có quyền xem lịch sử phân công theo đợt."),
			frappe.PermissionError,
		)
	return context


def _parse_list(value: Any, label: str) -> list[str]:
	if isinstance(value, str):
		try:
			value = frappe.parse_json(value)
		except (TypeError, ValueError):
			value = [part.strip() for part in value.split(",") if part.strip()]
	if not isinstance(value, (list, tuple, set)):
		frappe.throw(_("{0} phải là một danh sách.").format(label), frappe.ValidationError)
	values = []
	for item in value:
		item = str(item or "").strip()
		if item and item not in values:
			values.append(item)
	if not values:
		frappe.throw(_("{0} không được rỗng.").format(label), frappe.ValidationError)
	if len(values) > MAX_BATCH_SIZE:
		frappe.throw(
			_("Một đợt tối đa {0} Lead.").format(MAX_BATCH_SIZE),
			frappe.ValidationError,
		)
	return values


def _lead_permission(lead) -> None:
	if not frappe.has_permission("CRM Lead", ptype="read", doc=lead, user=frappe.session.user):
		frappe.throw(_("Lead nằm ngoài phạm vi của bạn."), frappe.PermissionError)


def _lead(name: str):
	if not frappe.db.exists("CRM Lead", name):
		frappe.throw(_("Không tìm thấy Lead: {0}.").format(name), frappe.ValidationError)
	doc = frappe.get_doc("CRM Lead", name)
	_lead_permission(doc)
	return doc


def _pool(pool_name: str | None, branch: str | None, actor_context: dict[str, Any] | None = None):
	if not pool_name:
		return None
	pool = frappe.db.get_value(
		"CRM Student Pool",
		pool_name,
		["name", "team", "campus", "is_active"],
		as_dict=True,
	)
	if not pool or not pool.is_active:
		frappe.throw(_("Hàng chờ đầu vào không tồn tại hoặc đã tắt."), frappe.ValidationError)
	if branch and pool.campus != branch:
		frappe.throw(_("Hàng chờ và cơ sở của Lead không khớp."), frappe.ValidationError)
	if actor_context and not actor_context.get("is_system_manager"):
		allowed_teams = set(actor_context.get("teams") or [])
		allowed_campuses = set(actor_context.get("campuses") or [])
		if pool.team not in allowed_teams or pool.campus not in allowed_campuses:
			frappe.throw(_("Hàng chờ nằm ngoài phạm vi Team/cơ sở của bạn."), frappe.PermissionError)
	return pool


def _reset_item(item, *, status: str = "pending", reason: str | None = None):
	for fieldname in (
		"error_code",
		"routing_tier",
		"queue",
		"zone",
		"team",
		"owner_staff",
		"active_load",
		"capacity_limit",
		"remaining_capacity",
		"policy_version",
		"routing_request",
		"completed_at",
	):
		item.set(fieldname, None)
	item.status = status
	item.reason = reason


def _queue_for_zone(lead, routing_context: dict[str, Any]) -> str | None:
	tier = routing_context.get("tier")
	if tier == 3:
		province = str(lead.get("province") or "").strip()
		return f"PROVINCE:{province}" if province else MANUAL_QUEUE
	if tier == 4:
		return ENRICHMENT_QUEUE
	return None


def _resolve_batch_pool(batch, lead, actor_context: dict[str, Any]):
	"""Resolve the internal intake Pool without exposing it to operators."""
	pool_name = lead.get("owning_pool") or batch.get("pool")
	if pool_name:
		pool = _pool(pool_name, lead.get("branch"), actor_context)
		if pool:
			return pool

	context = resolve_student_zone(lead)
	branch = lead.get("branch")
	filters = {"is_active": 1, "campus": branch}
	if not actor_context.get("is_system_manager"):
		filters["team"] = ["in", actor_context.get("teams") or ["__no_team__"]]
	candidates = frappe.get_all(
		"CRM Student Pool",
		filters=filters,
		fields=["name", "team", "campus", "is_active"],
		limit_page_length=3,
	)
	if len(candidates) == 1:
		return _pool(candidates[0].name, branch, actor_context)
	if len(candidates) > 1:
		raise frappe.ValidationError("MULTIPLE_INPUT_QUEUES")

	# System Managers may not have an actor Team. In that case, use the
	# configured Zone pool when it is unambiguous, then fall back to one campus
	# pool. For a scoped operator, the actor Team pool above is always preferred.
	if branch and context.get("zone"):
		mapping = zone_team_pool(context["zone"], branch)
		if mapping and mapping.get("pool"):
			return _pool(mapping["pool"], branch, actor_context)

	if actor_context.get("is_system_manager"):
		campus_pools = frappe.get_all(
			"CRM Student Pool",
			filters={"is_active": 1, "campus": branch},
			fields=["name", "team", "campus", "is_active"],
			limit_page_length=3,
		)
		if len(campus_pools) == 1:
			return _pool(campus_pools[0].name, branch, actor_context)
		if len(campus_pools) > 1:
			raise frappe.ValidationError("MULTIPLE_INPUT_QUEUES")
	raise frappe.ValidationError("MISSING_INPUT_QUEUE")


def _preview_item(batch, item, actor_context: dict[str, Any]) -> None:
	lead = _lead(item.lead)
	if lead.get("converted_student") or lead.get("conversion_status") == "Converted":
		_reset_item(item, status="skipped", reason="ALREADY_CONVERTED")
		item.ownership_revision = int(lead.get("ownership_revision") or 0)
		return
	if lead.get("owner_staff") or lead.get("assigned_to"):
		_reset_item(item, status="skipped", reason="ALREADY_ASSIGNED")
		item.ownership_revision = int(lead.get("ownership_revision") or 0)
		return
	processing = preview_lead(lead.name)
	item.reason = processing.get("reason") or processing.get("resolution") or "ready"
	item.error_code = processing.get("error_code")
	if processing.get("status") == "CLOSED":
		_reset_item(
			item, status="manual_review", reason=processing.get("reason") or processing.get("resolution")
		)
		item.error_code = processing.get("error_code") or processing.get("resolution")
		return
	if processing.get("status") not in {"NEW", "PROCESSING", "PROCESSED"}:
		_reset_item(item, status="manual_review", reason="INVALID_PROCESSING_STATUS")
		item.error_code = "INVALID_PROCESSING_STATUS"
		return
	if not lead.get("branch"):
		_reset_item(item, status="manual_review", reason="MISSING_CAMPUS")
		return
	context = resolve_student_zone(lead)
	pool = _resolve_batch_pool(batch, lead, actor_context)
	if not pool:
		_reset_item(item, status="manual_review", reason="MISSING_INPUT_QUEUE")
		return
	item.status = "pending"
	item.reason = context.get("reason") or "ready"
	item.routing_tier = context.get("tier")
	item.queue = _queue_for_zone(lead, context)
	item.zone = context.get("zone")
	item.team = context.get("school_owner_team") or context.get("mapping", {}).get("team")
	item.ownership_revision = int(lead.get("ownership_revision") or 0)
	item.error_code = None


def _preview_batch_items(batch, actor_context: dict[str, Any]) -> None:
	"""Evaluate every item before execution, keeping exceptions out of the run path."""
	for item in batch.items:
		try:
			_preview_item(batch, item, actor_context)
		except Exception as exc:
			code = (
				getattr(exc, "code", None) or getattr(exc, "error_code", None) or str(exc).strip()
				if str(exc).strip() in {"MISSING_INPUT_QUEUE", "MULTIPLE_INPUT_QUEUES"}
				else "PREVIEW_FAILED"
			)
			_reset_item(item, status="manual_review", reason=code)
			item.error_code = code
	batch.status = "ready"


def _count_items(batch) -> None:
	counts = {"assigned": 0, "deferred": 0, "manual_review": 0, "failed": 0}
	for item in batch.items:
		if item.status in counts:
			counts[item.status] += 1
	batch.total_count = len(batch.items)
	batch.assigned_count = counts["assigned"]
	batch.deferred_count = counts["deferred"]
	batch.manual_review_count = counts["manual_review"]
	batch.failed_count = counts["failed"]


def _serialize_item(item) -> dict[str, Any]:
	lead = (
		frappe.db.get_value(
			"CRM Lead",
			item.lead,
			[
				"student_name",
				"phone",
				"id_number",
				"email",
				"province",
				"high_school",
				"major",
				"source",
				"branch",
			],
			as_dict=True,
		)
		or {}
	)
	return {
		"id": item.name,
		"lead": item.lead,
		"leadId": item.lead,
		"studentName": lead.get("student_name") or item.lead,
		"phone": lead.get("phone"),
		"idNumber": lead.get("id_number"),
		"email": lead.get("email"),
		"province": lead.get("province"),
		"highSchool": lead.get("high_school"),
		"major": lead.get("major"),
		"source": lead.get("source"),
		"branch": lead.get("branch"),
		"status": item.status,
		"reason": item.reason,
		"errorCode": item.error_code,
		"routingTier": item.routing_tier,
		"queue": item.queue,
		"zone": item.zone,
		"team": item.team,
		"ownerStaff": item.owner_staff,
		"activeLoad": item.active_load,
		"capacityLimit": item.capacity_limit,
		"remainingCapacity": item.remaining_capacity,
		"policyVersion": item.policy_version,
		"ownershipRevision": item.ownership_revision,
		"routingRequest": item.routing_request,
		"executionId": item.execution_id,
		"completedAt": str(item.completed_at) if item.completed_at else None,
		"processingStatus": frappe.db.get_value("CRM Lead", item.lead, "processing_status"),
		"resolution": frappe.db.get_value("CRM Lead", item.lead, "resolution"),
		"matchedStudent": frappe.db.get_value("CRM Lead", item.lead, "matched_student"),
	}


def _serialize_batch(batch) -> dict[str, Any]:
	_count_items(batch)
	return {
		"name": batch.name,
		"batchName": batch.batch_name,
		"status": batch.status,
		"source": batch.source,
		"pool": batch.pool,
		"description": batch.description,
		"createdBy": batch.created_by,
		"executionId": batch.execution_id,
		"startedAt": str(batch.started_at) if batch.started_at else None,
		"completedAt": str(batch.completed_at) if batch.completed_at else None,
		"summary": {
			"total": batch.total_count,
			"valid": max(0, batch.total_count - batch.manual_review_count),
			"invalid": batch.manual_review_count,
			"pending": sum(item.status == "pending" for item in batch.items),
			"assigned": batch.assigned_count,
			"deferred": batch.deferred_count,
			"manualReview": batch.manual_review_count,
			"failed": batch.failed_count,
			"skipped": sum(item.status == "skipped" for item in batch.items),
		},
		"items": [_serialize_item(item) for item in batch.items],
	}


def _save_batch(batch):
	_count_items(batch)
	batch.save(ignore_permissions=True)


@frappe.whitelist(methods=["POST"])
def create_lead_assignment_batch(
	batch_name: str,
	lead_ids: list[str] | str,
	pool: str | None = None,
	source: str | None = None,
	description: str | None = None,
):
	"""Create a draft batch without changing any Lead ownership."""
	actor_context = _require_access()
	batch_name = str(batch_name or "").strip()
	if not batch_name:
		frappe.throw(_("Tên đợt là bắt buộc."), frappe.ValidationError)
	if frappe.db.exists(BATCH_DOCTYPE, {"batch_name": batch_name}):
		frappe.throw(_("Tên đợt đã tồn tại."), frappe.DuplicateEntryError)
	lead_names = _parse_list(lead_ids, "lead_ids")
	if pool:
		_pool(pool, None, actor_context)
	batch = frappe.get_doc(
		{
			"doctype": BATCH_DOCTYPE,
			"batch_name": batch_name,
			"status": "draft",
			"pool": pool,
			"source": (source or "").strip()[:140],
			"description": (description or "").strip(),
			"created_by": frappe.session.user,
		}
	)
	for lead_name in lead_names:
		lead = _lead(lead_name)
		batch.append(
			"items",
			{
				"lead": lead.name,
				"status": "pending",
				"ownership_revision": int(lead.get("ownership_revision") or 0),
			},
		)
	_save_batch(batch)
	frappe.db.commit()
	return _serialize_batch(batch)


def _parse_batch_import_rows(rows: list[dict[str, Any]] | str | None, csv_content: str | None):
	if csv_content is not None:
		return lead_mapping._parse_csv_rows(
			csv_content,
			required_headers=BATCH_IMPORT_REQUIRED_HEADERS,
		)
	if isinstance(rows, str):
		try:
			rows = frappe.parse_json(rows)
		except (TypeError, ValueError):
			frappe.throw(_("rows phải là JSON array hợp lệ."), frappe.ValidationError)
	if not isinstance(rows, list) or not rows:
		frappe.throw(_("Cần truyền rows hoặc csv_content."), frappe.ValidationError)
	if len(rows) > MAX_BATCH_SIZE:
		frappe.throw(_("Một đợt tối đa {0} Lead.").format(MAX_BATCH_SIZE), frappe.ValidationError)
	return [lead_mapping._parse_public_payload(row) for row in rows]


def _default_campus(row: dict[str, Any], actor_context: dict[str, Any]) -> str:
	requested_branch = str(row.get("branch") or "").strip()
	allowed_campuses = set(actor_context.get("campuses") or [])
	if requested_branch:
		resolved_branch = lead_mapping._normalize_public_lead_payload(
			{**row, "branch": requested_branch}, require_campaign=False
		).get("branch")
		if (
			resolved_branch
			and not actor_context.get("is_system_manager")
			and resolved_branch not in allowed_campuses
		):
			frappe.throw(_("Cơ sở của Lead nằm ngoài phạm vi của bạn."), frappe.PermissionError)
		return resolved_branch
	if actor_context.get("is_system_manager"):
		default_campus = frappe.db.get_value("CRM Campus", {"is_default": 1}, "name")
		if default_campus:
			return default_campus
		campuses = frappe.get_all(
			"CRM Campus",
			filters={"is_active": 1},
			pluck="name",
			limit_page_length=2,
		)
		if len(campuses) == 1:
			return campuses[0]
	if len(allowed_campuses) == 1:
		return next(iter(allowed_campuses))
	frappe.throw(
		_("Không xác định được cơ sở. Hãy thêm cột Cơ sở khi tài khoản phụ trách nhiều cơ sở."),
		frappe.ValidationError,
	)


def _create_batch_import_lead(row: dict[str, Any], actor_context: dict[str, Any]):
	for fieldname, label in (
		("student_name", "Họ và tên"),
		("phone", "Di động"),
		("id_number", "CCCD"),
		("province", "Tỉnh/Thành phố"),
		("high_school", "Trường THPT"),
		("major", "Ngành quan tâm"),
		("source", "Nguồn"),
	):
		if not str(row.get(fieldname) or "").strip():
			frappe.throw(_("{0} là bắt buộc.").format(label), frappe.ValidationError)
	# Batch import is an authenticated internal intake flow. Campaign attribution
	# is optional here; public lead intake keeps its stricter campaign contract.
	values = lead_mapping._normalize_public_lead_payload(
		{**row, "branch": _default_campus(row, actor_context)},
		require_campaign=False,
	)
	doc = frappe.get_doc({"doctype": "CRM Lead", **values})
	doc.check_permission("create")
	doc.insert()
	return doc


@frappe.whitelist(methods=["POST"])
def import_leads_to_assignment_batch(
	batch_name: str,
	pool: str | None = None,
	rows: list[dict[str, Any]] | str | None = None,
	csv_content: str | None = None,
	filename: str | None = None,
	description: str | None = None,
):
	"""Import Leads into a draft batch without selecting a Sale."""
	actor_context = _require_access()
	batch_name = str(batch_name or "").strip()
	if not batch_name:
		frappe.throw(_("Tên đợt là bắt buộc."), frappe.ValidationError)
	if frappe.db.exists(BATCH_DOCTYPE, {"batch_name": batch_name}):
		frappe.throw(_("Tên đợt đã tồn tại."), frappe.DuplicateEntryError)
	input_pool = _pool(str(pool or "").strip(), None, actor_context) if pool else None
	parsed_rows = _parse_batch_import_rows(rows, csv_content)
	batch = frappe.get_doc(
		{
			"doctype": BATCH_DOCTYPE,
			"batch_name": batch_name,
			"status": "draft",
			"pool": input_pool.name if input_pool else None,
			"source": (filename or "dashboard-crm").strip()[:140],
			"description": (description or "Nhập Lead vào đợt phân công.").strip(),
			"created_by": frappe.session.user,
		}
	)
	batch.insert(ignore_permissions=True)
	created = []
	errors = []
	for index, row in enumerate(parsed_rows, start=2):
		savepoint = f"lead_assignment_import_{index}"
		frappe.db.savepoint(savepoint)
		item = None
		try:
			lead = _create_batch_import_lead(row, actor_context)
			item = batch.append(
				"items",
				{
					"lead": lead.name,
					"status": "pending",
					"ownership_revision": int(lead.get("ownership_revision") or 0),
				},
			)
			item.reason = "Đã nhận trong đợt"
			created.append({"row": index, "lead": lead.name})
		except Exception as exc:
			frappe.db.rollback(save_point=savepoint)
			if item is not None:
				batch.items = [row_item for row_item in batch.items if row_item is not item]
			errors.append(
				{
					"row": index,
					"code": getattr(exc, "code", None) or "IMPORT_ROW_FAILED",
					"message": str(exc),
				}
			)
	_save_batch(batch)
	frappe.db.commit()
	result = _serialize_batch(batch)
	result["import"] = {
		"filename": (filename or "").strip(),
		"total": len(parsed_rows),
		"created": len(created),
		"failed": len(errors),
		"errors": errors,
	}
	return result


@frappe.whitelist(methods=["POST"])
def preview_lead_assignment_batch(batch_name: str):
	actor_context = _require_access()
	batch = frappe.get_doc(BATCH_DOCTYPE, batch_name)
	if batch.status in {"running", "completed", "cancelled"}:
		frappe.throw(_("Đợt này không còn cho phép kiểm tra trước."), frappe.ValidationError)
	_preview_batch_items(batch, actor_context)
	_save_batch(batch)
	frappe.db.commit()
	return _serialize_batch(batch)


def _assign_input_pool(batch, item, lead, actor_context: dict[str, Any]):
	if lead.get("owning_pool"):
		return int(lead.get("ownership_revision") or 0)
	pool = _resolve_batch_pool(batch, lead, actor_context)
	if lead.get("owning_team") and lead.get("owning_team") != pool.team:
		raise frappe.ValidationError("INPUT_QUEUE_TEAM_MISMATCH")
	result = change_student_ownership(
		student=lead.name,
		target_kind="pool",
		target_id=pool.name,
		target_team_id=pool.team,
		reason="Gán Lead vào hàng chờ của đợt trước khi phân công.",
		idempotency_key=f"lead-batch-pool:{batch.name}:{item.name}:{lead.get('ownership_revision') or 0}",
		expected_revision=int(lead.get("ownership_revision") or 0),
		correlation_id=batch.execution_id or str(uuid.uuid4()),
		_internal_service=True,
		_internal_actor=getattr(frappe.session, "user", None),
		_commit=False,
		_route_trigger="pool_entry",
		_enqueue_routing=False,
	)
	return int(result.get("revision") or 0)


def _apply_result(item, result: dict[str, Any], execution_id: str):
	ownership = result.get("ownership") or {}
	item.execution_id = execution_id
	item.routing_tier = result.get("tier") or item.routing_tier
	item.queue = result.get("queue") or item.queue
	item.owner_staff = result.get("owner_staff")
	item.team = result.get("owning_team") or item.team
	item.policy_version = (
		result.get("routing_policy_version")
		or result.get("policy_version")
		or ownership.get("routing_policy_version")
		or ownership.get("policy_version")
	)
	item.routing_request = result.get("request")
	if result.get("status") == "applied":
		item.status = "assigned"
		item.reason = f"{item.reason or 'ready'} → ASSIGNED"
		item.completed_at = now_datetime()
	elif result.get("status") in {"queued", "deferred"}:
		item.status = "deferred"
		item.reason = result.get("reason") or result.get("queue") or "DEFERRED"
		item.error_code = result.get("reason")
	else:
		item.status = "failed"
		item.reason = result.get("reason") or "ROUTING_FAILED"
		item.error_code = result.get("error_code") or result.get("reason") or "ROUTING_FAILED"


def _capacity_snapshot(staff: str | None) -> dict[str, int | None]:
	if not staff:
		return {"active": None, "limit": None, "remaining": None}
	period = frappe.db.get_value(
		"CRM Staff Capacity Period",
		{
			"staff": staff,
			"period_start": ["<=", getdate(today())],
			"period_end": [">=", getdate(today())],
			"approved": 1,
		},
		["max_active_students"],
		as_dict=True,
	)
	limit = int((period or {}).get("max_active_students") or 0)
	active = int(
		frappe.db.count(
			"CRM Lead",
			{"owner_staff": staff, "lifecycle_stage": ["not in", ["Lost", "Converted"]]},
		)
	)
	return {"active": active, "limit": limit or None, "remaining": max(0, limit - active) if limit else None}


@frappe.whitelist(methods=["POST"])
def run_lead_assignment_batch(batch_name: str):
	actor_context = _require_access()
	batch = frappe.get_doc(BATCH_DOCTYPE, batch_name)
	if batch.status not in RUNNABLE_STATUSES:
		frappe.throw(_("Đợt phải ở trạng thái Nháp, Sẵn sàng hoặc Có lỗi."), frappe.ValidationError)
	if batch.status == "draft":
		_preview_batch_items(batch, actor_context)
	batch.status = "running"
	batch.execution_id = f"lead-batch-{uuid.uuid4().hex}"
	batch.started_at = now_datetime()
	batch.completed_at = None
	_save_batch(batch)

	for index, item in enumerate(batch.items):
		if item.status in TERMINAL_ITEM_STATUSES:
			continue
		if item.status == "manual_review":
			continue
		savepoint = f"lead_assignment_{index}"
		frappe.db.savepoint(savepoint)
		try:
			lead = _lead(item.lead)
			if str(lead.get("processing_status") or "NEW").upper() == "NEW":
				processing = process_lead(lead.name)
				if processing.get("status") == "CLOSED":
					_reset_item(
						item,
						status="manual_review",
						reason=processing.get("resolution") or "INVALID",
					)
					item.error_code = processing.get("resolution") or "INVALID"
					item.execution_id = batch.execution_id
					item.completed_at = now_datetime()
					_save_batch(batch)
					continue
				lead = _lead(item.lead)
			if lead.get("owner_staff") or lead.get("assigned_to"):
				_reset_item(item, status="skipped", reason="ALREADY_ASSIGNED")
			else:
				revision = _assign_input_pool(batch, item, lead, actor_context)
				result = route_lead_now(
					lead.name,
					trigger="pool_entry",
					expected_revision=revision,
					correlation_id=f"{batch.execution_id}:{item.name}",
				)
				_apply_result(item, result, batch.execution_id)
				if result.get("status") == "applied":
					mark_lead_assigned(
						lead.name,
						reason=result.get("reason") or "Phân công tự động trong đợt.",
					)
				item.ownership_revision = int(result.get("revision") or revision)
				snapshot = _capacity_snapshot(item.owner_staff)
				item.active_load = snapshot["active"]
				item.capacity_limit = snapshot["limit"]
				item.remaining_capacity = snapshot["remaining"]
		except Exception as exc:
			frappe.db.rollback(save_point=savepoint)
			batch.reload()
			item = next(row for row in batch.items if row.name == item.name)
			item.status = "failed"
			item.reason = str(exc)
			item.error_code = (
				getattr(exc, "code", None) or getattr(exc, "error_code", None) or "ROUTING_FAILED"
			)
			item.execution_id = batch.execution_id
			item.completed_at = now_datetime()
		batch.status = "running"
		_save_batch(batch)

	batch.completed_at = now_datetime()
	_count_items(batch)
	batch.status = (
		"completed"
		if not any(item.status in {"deferred", "manual_review", "failed"} for item in batch.items)
		else "completed_with_errors"
	)
	_save_batch(batch)
	frappe.db.commit()
	return _serialize_batch(batch)


@frappe.whitelist(methods=["POST"])
def retry_lead_assignment_batch(batch_name: str, item_ids: list[str] | str | None = None):
	_require_access()
	batch = frappe.get_doc(BATCH_DOCTYPE, batch_name)
	selected = set(_parse_list(item_ids, "item_ids")) if item_ids else None
	for item in batch.items:
		if selected is not None and item.name not in selected:
			continue
		if item.status in {"deferred", "manual_review", "failed"}:
			_reset_item(item)
	batch.status = "ready"
	_save_batch(batch)
	frappe.db.commit()
	return run_lead_assignment_batch(batch.name)


@frappe.whitelist()
def get_lead_assignment_batch(batch_name: str):
	actor_context = _require_read_access()
	batch = frappe.get_doc(BATCH_DOCTYPE, batch_name)
	if batch.pool:
		_pool(batch.pool, None, actor_context)
	return _serialize_batch(batch)


@frappe.whitelist()
def list_lead_assignment_batches(
	limit: int | str = 50,
	page: int | str = 1,
	page_size: int | str | None = None,
	status: str | None = None,
	q: str | None = None,
):
	actor_context = _require_read_access()
	try:
		requested_page_size = page_size if page_size not in (None, "") else limit
		page_size = max(1, min(int(requested_page_size), 100))
		page = max(1, int(page or 1))
	except (TypeError, ValueError):
		frappe.throw(_("Thông tin phân trang không hợp lệ."), frappe.ValidationError)
	filters = {}
	if status and status != "all":
		if status not in {"draft", "ready", "running", "completed", "completed_with_errors", "cancelled"}:
			frappe.throw(_("Trạng thái đợt không hợp lệ."), frappe.ValidationError)
		filters["status"] = status
	search = str(q or "").strip()
	if len(search) > 140:
		frappe.throw(_("Từ khóa tìm kiếm quá dài."), frappe.ValidationError)
	if search:
		filters["batch_name"] = ["like", f"%{search}%"]
	if not actor_context.get("is_system_manager"):
		allowed_pools = frappe.get_all(
			"CRM Student Pool",
			filters={
				"is_active": 1,
				"team": ["in", actor_context.get("teams") or ["__no_team__"]],
				"campus": ["in", actor_context.get("campuses") or ["__no_campus__"]],
			},
			pluck="name",
			limit_page_length=200,
		)
		or_filters = [
			{"pool": ["in", allowed_pools or ["__no_pool__"]]},
			{"pool": ["is", "not set"], "created_by": actor_context["actor"]},
		]
	else:
		or_filters = None
	fields = [
		"name",
		"batch_name",
		"status",
		"pool",
		"source",
		"total_count",
		"assigned_count",
		"deferred_count",
		"manual_review_count",
		"failed_count",
		"created_by",
		"creation",
	]
	query = {
		"doctype": BATCH_DOCTYPE,
		"filters": filters,
		"fields": fields,
		"order_by": "creation desc",
		"limit_page_length": page_size,
		"limit_start": (page - 1) * page_size,
	}
	if or_filters:
		query["or_filters"] = or_filters
	total = len(
		frappe.get_all(
			BATCH_DOCTYPE,
			filters=filters,
			or_filters=or_filters,
			fields=["name"],
			limit_page_length=0,
		)
	)
	total_pages = max(1, (total + page_size - 1) // page_size)
	return {
		"items": frappe.get_all(**query),
		"pagination": {
			"page": page,
			"page_size": page_size,
			"total": total,
			"total_pages": total_pages,
			"has_next_page": page < total_pages,
		},
	}


@frappe.whitelist()
def get_lead_assignment_batch_options():
	"""Return human-readable input queues available to the current operator."""
	actor_context = _require_read_access()
	filters = {"is_active": 1}
	if not actor_context.get("is_system_manager"):
		filters["team"] = ["in", actor_context.get("teams") or ["__no_team__"]]
		filters["campus"] = ["in", actor_context.get("campuses") or ["__no_campus__"]]
	return {
		"pools": frappe.get_list(
			"CRM Student Pool",
			filters=filters,
			fields=["name", "pool_name", "team", "campus"],
			order_by="pool_name asc",
			limit_page_length=200,
		)
	}


def _catalog_rows(doctype: str, fields: list[str], label_field: str, filters=None):
	rows = frappe.get_list(
		doctype,
		filters=filters or {},
		fields=fields,
		order_by=f"{label_field} asc, name asc",
		limit_page_length=5000,
	)
	return [
		{
			"id": row.get("name"),
			"label": row.get(label_field) or row.get("name"),
			"code": row.get("province_code") or row.get("school_code") or row.get("major_code"),
		}
		for row in rows
	]


@frappe.whitelist(methods=["GET"])
def get_lead_assignment_catalogs(province: str | None = None):
	"""Return Frappe-owned choices for the batch Lead form."""
	_require_read_access()
	province_name = str(province or "").strip()
	if province_name and not frappe.db.exists("CRM Province", province_name):
		province_name = lead_mapping._resolve_province(province_name)
	return {
		"provinces": _catalog_rows(
			"CRM Province",
			["name", "province_name", "province_code"],
			"province_name",
		),
		"sources": _catalog_rows(
			"CRM Lead Source",
			["name", "source_name"],
			"source_name",
			{"approval_state": ["!=", "Retired"]},
		),
		"majors": _catalog_rows(
			"CRM Major",
			["name", "major_name", "major_code"],
			"major_name",
		),
		"highSchools": (
			_catalog_rows(
				"CRM High School",
				["name", "school_name", "school_code", "province"],
				"school_name",
				{"province": province_name},
			)
			if province_name
			else []
		),
	}
