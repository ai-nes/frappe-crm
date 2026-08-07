"""Single convergence point for every `CRM Student.enrollment_status` write.

Every write path — the ordinary Document save (`on_update` hook in
crm_student.py, via `get_doc_before_save()`), and every `db_set`/
`db.set_value` bypass (convert-to-contact, the Contact-side edit sync,
demo seeding) — must converge on `record_transition()`. There is no second
logging path.

- `record_transition()` is a no-op when `old_status == new_status` (no
  empty/duplicate rows from saves that don't actually change status).
- Log failures are fail-open: caught and logged, never re-raised. A bug in
  transition logging must never block a student/contact save.
- Brand-new students get an initial transition row with `from_status=None`
  so the very first status isn't invisible in the log.
- Students that existed before this log was introduced are NOT backfilled.
  Their first logged transition will show `from_status` as whatever their
  status happened to be at that moment, not their original status at
  creation — there is no source to reconstruct that history from, so don't
  try.
"""

import frappe

DOCTYPE = "CRM Enrollment Transition"
FAILURE_LOG_TITLE = "CRM Enrollment Transition record_transition failed"
FAILURE_METRIC_CACHE_KEY = "crm_enrollment_transition_record_failures"


def record_transition(student, old_status, new_status, occurred_at=None, actor=None, source=None):
	"""Log one `enrollment_status` change for `student`.

	No-op if `old_status == new_status`. Runs inside its own DB savepoint
	so a failure here rolls back only the log write, never the caller's
	transaction (fail-open, confirmed design — student/contact save must
	never be blocked by a logging bug).
	"""
	if old_status == new_status:
		return

	occurred_at = occurred_at or frappe.utils.now_datetime()
	actor = actor or getattr(frappe.session, "user", None)

	def _write():
		_close_open_transition(student, occurred_at)
		_insert_transition_row(student, old_status, new_status, occurred_at, actor, source)

	_run_in_savepoint(_write)


def set_enrollment_status(doc, new_value, actor=None, source=None):
	"""The ONLY sanctioned way to change `enrollment_status` outside of an
	ordinary `doc.save()`.

	Writes the field via `db_set` (bypasses Document hooks by design — this
	is for programmatic changes like convert-to-contact or the Contact-side
	sync, which intentionally skip `validate`/`before_save`/`on_update`)
	and logs the transition through the same `record_transition()`
	primitive the `on_update` hook uses. Do not add a new direct
	`db_set`/`db.set_value("enrollment_status", ...)` call anywhere else —
	route it through this helper so it is captured in the log.

	`doc` may be a `CRM Student` name (str) or an already-loaded doc.
	Returns the (possibly newly-loaded) doc.
	"""
	if isinstance(doc, str):
		doc = frappe.get_doc("CRM Student", doc)

	old_value = doc.enrollment_status
	if old_value == new_value:
		return doc

	doc.db_set("enrollment_status", new_value)
	record_transition(doc.name, old_value, new_value, actor=actor, source=source or "set_enrollment_status")
	return doc


def _close_open_transition(student, occurred_at):
	"""Close the student's current open row (`to_date IS NULL`), if any."""
	open_row = frappe.db.get_value(
		DOCTYPE,
		{"student": student, "to_date": ["is", "not set"]},
		["name", "from_date"],
		as_dict=True,
	)
	if not open_row:
		return

	duration = None
	if open_row.from_date:
		duration = max(int((occurred_at - open_row.from_date).total_seconds()), 0)

	frappe.db.set_value(
		DOCTYPE,
		open_row.name,
		{"to_date": occurred_at, "duration": duration},
		update_modified=False,
	)


def _insert_transition_row(student, old_status, new_status, occurred_at, actor, source):
	frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"student": student,
			"from_status": old_status,
			"to_status": new_status,
			"from_date": occurred_at,
			"to_date": None,
			"duration": None,
			"log_owner": actor,
			"source": source,
		}
	).insert(ignore_permissions=True)


def _run_in_savepoint(fn):
	"""Run `fn()` isolated in its own DB savepoint (fail-open).

	Uses raw `SAVEPOINT` / `RELEASE SAVEPOINT` / `ROLLBACK TO SAVEPOINT`
	SQL rather than `frappe.db.savepoint()`, so a failure here rolls back
	only the log write and never poisons the caller's outer transaction.
	Standard SQL supported by both MariaDB and PostgreSQL (the backends
	Frappe supports), so it works regardless of Frappe version.
	"""
	savepoint_name = "crm_enrollment_transition_" + frappe.generate_hash(length=10)
	try:
		frappe.db.sql(f"SAVEPOINT {savepoint_name}")
	except Exception:
		# DB/driver doesn't support SAVEPOINT (or no active transaction).
		# Fall back to a bare try/except around the write itself — weaker
		# isolation (a failed insert can't be cleanly rolled back), but
		# still fail-open: never propagates into the caller.
		try:
			fn()
		except Exception:
			_record_failure()
		return

	try:
		fn()
		frappe.db.sql(f"RELEASE SAVEPOINT {savepoint_name}")
	except Exception:
		frappe.db.sql(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
		_record_failure()


def _record_failure():
	"""Fail-open failure signal: log via the existing `frappe.log_error`
	convention (queryable "Error Log" doctype — this fork has no separate
	metrics/counter subsystem) and bump a cache counter that the
	reconciliation job (see `reconcile_enrollment_transitions` in this
	module) reports alongside its mismatch findings.
	"""
	frappe.log_error(title=FAILURE_LOG_TITLE, message=frappe.get_traceback())
	try:
		frappe.cache().incrby(FAILURE_METRIC_CACHE_KEY, 1)
	except Exception:
		# Cache unavailable — the Error Log entry above is still the
		# durable record of the failure; don't let a cache hiccup mask it.
		pass


def reconcile_enrollment_transitions():
	"""Scheduled reconciliation: compare each student's current
	`enrollment_status` against the `to_status` of their most recent
	`CRM Enrollment Transition` row (the open one, `to_date IS NULL`).
	Flags mismatches — these indicate a status write that never got
	logged (e.g. a `record_transition()` failure, or a future write path
	that bypassed `set_enrollment_status`/the `on_update` hook).

	Runs daily via `scheduler_events` (see crm/hooks.py). Writes findings
	to the Error Log (same convention as `_record_failure`) rather than
	raising, so a reconciliation run itself never breaks the scheduler.
	"""
	mismatches = frappe.db.sql(
		"""
		SELECT
			student.name AS student,
			student.enrollment_status AS current_status,
			open_transition.name AS open_transition_name,
			open_transition.to_status AS logged_status
		FROM `tabCRM Student` AS student
		LEFT JOIN `tabCRM Enrollment Transition` AS open_transition
			ON open_transition.student = student.name AND open_transition.to_date IS NULL
		WHERE
			open_transition.name IS NULL
			OR open_transition.to_status != student.enrollment_status
		""",
		as_dict=True,
	)

	failure_count = 0
	try:
		failure_count = int(frappe.cache().get_value(FAILURE_METRIC_CACHE_KEY) or 0)
	except Exception:
		pass

	if not mismatches and not failure_count:
		return

	frappe.log_error(
		title="CRM Enrollment Transition reconciliation found drift",
		message=frappe.as_json(
			{
				"record_transition_failures_since_last_reset": failure_count,
				"mismatched_students": mismatches,
			}
		),
	)
