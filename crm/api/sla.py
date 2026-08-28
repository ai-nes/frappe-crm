"""Phase 3 SLA response-window tracking for CRM Contact. Replaces the
previously dead sla_status placeholder with real logic: the countdown starts
when a lead is first assigned (CRM Contact.sla_started_at, set once in
crm_contact.py's validate()) and is measured against first_contact_time —
the moment a staff member logs the first real contact. Locked thresholds:
30 minutes to "Sắp quá hạn" (warning), 2 hours to "Quá SLA" (breach).
Recomputed on a schedule (see hooks.py scheduler_events) rather than only on
save, since a lead can breach purely by elapsed time with no new save event.
See plans/260822-admissions-crm-alignment/phase-03-lead-status-routing-sla.md.
"""

import frappe
from frappe.utils import now_datetime

SLA_WARNING_MINUTES = 30
SLA_BREACH_MINUTES = 120

ON_TIME = "Đúng SLA"
WARNING = "Sắp quá hạn"
BREACH = "Quá SLA"

# Only leads still in an "open" enrollment_status bucket need a live SLA
# clock — reuses CRM Enrollment Status.stage_category (Phase 1/2) rather
# than re-deriving the same open/enrolled/lost split a second way.
_OPEN_STATUS_SUBQUERY = (
	"enrollment_status in (select status_name from `tabCRM Enrollment Status` where stage_category = 'open')"
)


def recompute_sla_statuses():
	# Reference time for the elapsed-time check is first_contact_time once
	# set (the response either met or missed the window, permanently), else
	# now() (still counting down / already overdue with no response yet).
	now = now_datetime()
	frappe.db.sql(
		f"""
		update `tabCRM Contact`
		set sla_status = %(breach)s
		where sla_started_at is not null
		  and {_OPEN_STATUS_SUBQUERY}
		  and timestampdiff(minute, sla_started_at, coalesce(first_contact_time, %(now)s)) >= %(breach_min)s
		""",
		{"breach": BREACH, "breach_min": SLA_BREACH_MINUTES, "now": now},
	)
	frappe.db.sql(
		f"""
		update `tabCRM Contact`
		set sla_status = %(warning)s
		where sla_started_at is not null
		  and {_OPEN_STATUS_SUBQUERY}
		  and timestampdiff(minute, sla_started_at, coalesce(first_contact_time, %(now)s)) >= %(warning_min)s
		  and timestampdiff(minute, sla_started_at, coalesce(first_contact_time, %(now)s)) < %(breach_min)s
		""",
		{"warning": WARNING, "warning_min": SLA_WARNING_MINUTES, "breach_min": SLA_BREACH_MINUTES, "now": now},
	)
	frappe.db.sql(
		f"""
		update `tabCRM Contact`
		set sla_status = %(on_time)s
		where sla_started_at is not null
		  and {_OPEN_STATUS_SUBQUERY}
		  and timestampdiff(minute, sla_started_at, coalesce(first_contact_time, %(now)s)) < %(warning_min)s
		""",
		{"on_time": ON_TIME, "warning_min": SLA_WARNING_MINUTES, "now": now},
	)
	frappe.db.commit()


def materialize_sla_evidence():
	"""Publish optional SLA state/evidence to Student at most every five minutes.

	The thresholds remain in this Frappe-owned SLA module. crm-agents receives
	only state/freshness metadata and never derives an SLA clock.
	"""
	rows = frappe.db.sql(
		"""SELECT student, sla_status, modified FROM `tabCRM Contact`
			WHERE student IS NOT NULL ORDER BY modified DESC""",
		as_dict=True,
	)
	seen = set()
	observed_at = frappe.utils.now_datetime()
	for row in rows:
		if row.student in seen:
			continue
		seen.add(row.student)
		state = "known" if row.sla_status else "unknown"
		previous = frappe.db.get_value("CRM Student", row.student, "sla_evidence_state")
		frappe.db.set_value(
			"CRM Student",
			row.student,
			{"sla_evidence_state": state, "sla_evidence_observed_at": observed_at},
			update_modified=False,
		)
		if previous != state:
			from crm.services.student_context import mark_student_context_changed

			mark_student_context_changed(row.student, "sla_evidence_state_change")
	frappe.db.commit()
