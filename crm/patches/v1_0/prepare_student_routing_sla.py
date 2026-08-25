"""Prepare Phase 4 routing/SLA constraints without fabricating SLA history."""

from __future__ import annotations

try:
	import frappe
except ImportError:  # pragma: no cover - pure classifier tests run outside bench
	frappe = None


def classify_student_topology(student: dict, pools: list[dict] | None = None) -> str:
	"""Classify current responsibility without changing Student state.

	``owning_team`` is only a compatibility projection.  A pool topology is
	valid only when the service can resolve exactly one active Student Pool for
	the Student's Campus and that Team (or an explicit ``owning_pool`` link).
	"""
	status = str(student.get("enrollment_status") or "").casefold()
	stage = str(student.get("lifecycle_stage") or "").casefold()
	if status in {"lost", "converted"} or stage in {"lost", "converted"}:
		return "terminal"
	owner = bool(student.get("owner_staff") or student.get("assigned_to"))
	pool_signal = student.get("owning_pool") or student.get("owning_team")
	if owner and pool_signal:
		return "dual_owner_pool"
	if owner:
		return "owner"
	if not pool_signal:
		return "unowned_active"
	if pools is None:
		return "pool_projection_unresolved"

	campus = student.get("branch")
	candidates = []
	for pool in pools:
		if not pool.get("is_active") or pool.get("campus") != campus:
			continue
		if student.get("owning_pool"):
			if pool.get("name") == student.get("owning_pool"):
				candidates.append(pool)
		elif pool.get("team") == student.get("owning_team"):
			candidates.append(pool)
	if len(candidates) == 1:
		if student.get("owning_pool") and student.get("owning_team") != candidates[0].get("team"):
			return "invalid_pool_topology"
		return "pool"
	if len(candidates) > 1:
		return "ambiguous_pool"
	return "missing_pool"


def _add_unique_index(doctype: str, columns: tuple[str, ...], index_name: str) -> bool:
	if not frappe.db.table_exists(doctype):
		return False
	physical = f"tab{doctype}"
	if frappe.db.sql(
		f"SHOW INDEX FROM `{physical}` WHERE Key_name = %s", index_name
	):
		return True
	column_sql = ", ".join(f"`{column}`" for column in columns)
	duplicates = frappe.db.sql(
		f"""select {column_sql}, count(*) as row_count from `{physical}`
		group by {column_sql} having row_count > 1 limit 1""",
		as_dict=True,
	)
	if duplicates:
		frappe.log_error(
			f"Phase 4 skipped {index_name}; duplicate rows require quarantine",
			"prepare_student_routing_sla",
		)
		return False
	frappe.db.sql_ddl(
		f"ALTER TABLE `{physical}` ADD UNIQUE INDEX `{index_name}` ({column_sql})"
	)
	return True


def _add_index(doctype: str, columns: tuple[str, ...], index_name: str) -> bool:
	"""Add a non-unique operational scan index idempotently."""
	if not frappe.db.table_exists(doctype):
		return False
	physical = f"tab{doctype}"
	if frappe.db.sql(f"SHOW INDEX FROM `{physical}` WHERE Key_name = %s", index_name):
		return True
	column_sql = ", ".join(f"`{column}`" for column in columns)
	frappe.db.sql_ddl(f"ALTER TABLE `{physical}` ADD INDEX `{index_name}` ({column_sql})")
	return True


def execute():
	students = frappe.get_all(
		"CRM Student",
		fields=[
			"name", "enrollment_status", "lifecycle_stage", "owner_staff", "assigned_to",
			"owning_team", "owning_pool", "branch",
		],
		order_by="name asc",
	)
	pools = frappe.get_all(
		"CRM Student Pool",
		fields=["name", "team", "campus", "is_active"],
	)
	classification = {student.name: classify_student_topology(student, pools) for student in students}
	invalid = {
		name: state
		for name, state in classification.items()
		if state in {
			"dual_owner_pool", "unowned_active", "pool_projection_unresolved",
			"missing_pool", "ambiguous_pool", "invalid_pool_topology",
		}
	}
	for student in students:
		if classification[student.name] != "pool" or student.get("owning_pool"):
			continue
		pool = next(
			(
				row for row in pools
				if row.get("is_active") and row.get("campus") == student.get("branch")
				and row.get("team") == student.get("owning_team")
			),
			None,
		)
		if pool:
			frappe.db.set_value("CRM Student", student.name, "owning_pool", pool.name, update_modified=False)
	for doctype, columns, index_name in (
		(
			"CRM Student SLA Attempt",
			("student", "opening_ownership_revision", "reset_sequence"),
			"crm_student_sla_attempt_student_revision_reset_uniq",
		),
	):
		_add_unique_index(doctype, columns, index_name)
	for doctype, columns, index_name in (
		("CRM Student SLA Attempt", ("status", "warning_at"), "crm_student_sla_attempt_status_warning_idx"),
		("CRM Student SLA Attempt", ("status", "next_transition_at"), "crm_student_sla_attempt_status_next_transition_idx"),
		("CRM Student SLA Attempt", ("status", "breach_at"), "crm_student_sla_attempt_status_breach_idx"),
		("CRM Student SLA Attempt", ("student_pool", "status"), "crm_student_sla_attempt_pool_status_idx"),
		("CRM Student SLA Event", ("student", "event_type", "event_at"), "crm_student_sla_event_student_type_at_idx"),
		("CRM Student Routing Policy", ("campus", "student_pool", "status", "effective_from"), "crm_student_routing_policy_scope_status_idx"),
		("CRM Student SLA Policy", ("campus", "student_pool", "status", "effective_from"), "crm_student_sla_policy_scope_status_idx"),
	):
		_add_index(doctype, columns, index_name)
	return {
		"students_checked": len(students),
		"invalid_topology": invalid,
		"sla_backfilled": 0,
		"note": "Historical Contact timestamps and Student modified/creation times were not used.",
	}
