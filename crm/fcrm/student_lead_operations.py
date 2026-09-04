"""Manager and CTV operations layered on the canonical ownership command."""

from __future__ import annotations

import uuid

import frappe

from crm.fcrm.student_assignment import capacity_eligible, fairness_report, resolve_student_zone
from crm.fcrm.student_ownership import change_student_ownership


def is_ctv_eligible(student) -> bool:
	"""CTV batches exclude high-value or complex leads."""
	try:
		if float(student.get("latest_score") or 0) >= 80:
			return False
	except (TypeError, ValueError):
		return False
	return student.get("fit_level") not in {"High", "Complex", "Strategic"}


def open_ctv_batch(staff: str, team: str, *, size: int, validity_hours: int = 24):
	"""Open one bounded CTV batch; the unique open-row check is concurrency-safe."""
	if frappe.db.exists("CRM Student Assignment Batch", {"staff": staff, "status": "open"}):
		raise frappe.ValidationError("CTV staff already has an open batch.")
	from frappe.utils import add_to_date, now_datetime

	batch = frappe.get_doc(
		{
			"doctype": "CRM Student Assignment Batch",
			"staff": staff,
			"team": team,
			"status": "open",
			"opened_at": now_datetime(),
			"expires_at": add_to_date(now_datetime(), hours=validity_hours),
			"batch_size": max(1, int(size)),
			"schema_version": "phase7-v1",
		}
	)
	batch.insert(ignore_permissions=True)
	return batch


def deliver_ctv_student(student, member: dict, *, policy=None):
	if not is_ctv_eligible(student):
		return None
	from frappe.utils import now_datetime

	rows = frappe.get_all(
		"CRM Student Assignment Batch",
		filters={"staff": member["staff"], "status": "open"},
		fields=["name", "batch_size"],
		limit_page_length=1,
	)
	batch = (
		frappe.get_doc("CRM Student Assignment Batch", rows[0].name)
		if rows
		else open_ctv_batch(member["staff"], member["team"], size=10)
	)
	items = batch.get("items") or []
	if len(items) >= int(batch.batch_size or 1):
		return None
	if not any(item.student == student.name for item in items):
		batch.append("items", {"student": student.name, "status": "delivered", "assigned_at": now_datetime()})
		batch.save(ignore_permissions=True)
	return batch


def recall_expired_ctv_batches(limit: int = 50):
	now = frappe.utils.now_datetime()
	try:
		rows = frappe.get_all(
			"CRM Student Assignment Batch",
			{"status": "open", "expires_at": ["<", now]},
			["name"],
			limit_page_length=limit,
		)
	except Exception:
		return {"recalled": 0, "batches": 0, "disabled": 1}
	recalled = 0
	for row in rows:
		batch = frappe.get_doc("CRM Student Assignment Batch", row.name)
		for item in batch.get("items") or []:
			if item.status != "delivered":
				continue
			student = frappe.get_doc("CRM Student", item.student)
			if student.get("owner_staff"):
				pool = frappe.db.get_value(
					"CRM Student Pool",
					{"team": batch.team, "campus": student.branch, "is_active": 1},
					"name",
				)
				if pool:
					change_student_ownership(
						student=student.name,
						target_kind="pool",
						target_id=pool,
						target_team_id=None,
						reason="CTV batch expired; lead recalled",
						idempotency_key=f"ctv-recall:{batch.name}:{item.name}",
						expected_revision=int(student.get("ownership_revision") or 0),
						correlation_id=f"ctv-recall:{batch.name}",
						_internal_service=True,
						_commit=False,
						_route_trigger="ctv_batch_recall",
					)
			item.status = "recalled"
			item.recalled_at = now
			recalled += 1
		frappe.db.set_value(
			"CRM Student Assignment Batch",
			row.name,
			{"status": "recalled", "recall_reason": "expired"},
			update_modified=False,
		)
		batch.save(ignore_permissions=True)
	frappe.db.commit()
	return {"recalled": recalled, "batches": len(rows)}


def complete_ctv_item(batch_name: str, student: str):
	batch = frappe.get_doc("CRM Student Assignment Batch", batch_name)
	for item in batch.get("items") or []:
		if item.student == student and item.status == "delivered":
			item.status = "worked"
			item.worked_at = frappe.utils.now_datetime()
			batch.completed_count = int(batch.completed_count or 0) + 1
			batch.save(ignore_permissions=True)
			return batch
	raise frappe.ValidationError("Student is not an open item in this CTV batch.")


def replenish_ctv_batch(batch_name: str, *, validity_hours: int = 24):
	batch = frappe.get_doc("CRM Student Assignment Batch", batch_name)
	if batch.status != "open":
		raise frappe.ValidationError("Only an open CTV batch can be replenished.")
	if int(batch.completed_count or 0) < max(1, int(batch.batch_size or 1) * 0.75):
		return batch
	batch.status = "completed"
	batch.save(ignore_permissions=True)
	return open_ctv_batch(
		batch.staff, batch.team, size=int(batch.batch_size or 1), validity_hours=validity_hours
	)


def manager_reassign_student(
	student: str,
	target_staff: str,
	target_team: str,
	reason: str,
	expected_revision: int,
	*,
	emergency_override: bool = False,
) -> dict:
	student_doc = frappe.get_doc("CRM Student", student)
	geo = resolve_student_zone(student_doc)
	if geo.get("zone") and not emergency_override:
		from crm.fcrm.student_assignment import zone_team_pool

		mapping = zone_team_pool(geo["zone"], student_doc.branch)
		if not mapping or mapping.get("team") != target_team:
			raise frappe.ValidationError("Target staff must belong to the student's zone-owning team.")
	member = {"staff": target_staff, "team": target_team}
	allowed, _capacity_snapshot = capacity_eligible(member, student_doc, direct=True)
	if not allowed and not emergency_override:
		raise frappe.ValidationError("Target staff is at capacity.")
	return change_student_ownership(
		student=student,
		target_kind="owner",
		target_id=target_staff,
		target_team_id=target_team,
		reason=f"Manager transfer: {reason}",
		idempotency_key=f"manager-transfer:{student}:{expected_revision}:{target_staff}",
		expected_revision=expected_revision,
		correlation_id=str(uuid.uuid4()),
		_internal_service=True,
		_internal_actor=frappe.session.user,
		_route_trigger="manager_transfer",
	)


def fairness_summary(**kwargs):
	return fairness_report(**kwargs)
