"""Read-only reconciliation report for CRM Student records created by the old
continuous Contact<->Student sync bug (fixed in Phase 2 — see
plans/260822-admissions-crm-alignment/phase-02-fix-contact-student-lifecycle-bug.md).

Strictly report-only: this patch never writes, archives, or deletes any record. No
staging/production-copy environment exists to validate a write-mode reconciliation
against, so that is deliberately left to a future phase with real environment access,
a backup, and human sign-off — a clean local/dev dry-run here is not sufficient
evidence to act on production data.

Catalogs three anomaly classes and writes them to a single Error Log entry:
1. CRM Student rows with no CRM Contact pointing at them (orphaned by the old
   auto-create path, e.g. if the owning Contact was later deleted).
2. CRM Contact rows whose `student` link points at a CRM Student that no longer
   exists (dangling link).
3. CRM Student rows whose enrollment_status was never in
   crm.fcrm.doctype.crm_contact.crm_contact.MILESTONE_ENROLLMENT_STATUSES,
   suggesting they were created by the old unconditional (pre-milestone) auto-create
   path rather than a genuine milestone event.
"""

import frappe

from crm.fcrm.doctype.crm_contact.crm_contact import MILESTONE_ENROLLMENT_STATUSES


def execute():
	linked_students = set(
		frappe.get_all("CRM Contact", filters={"student": ["is", "set"]}, pluck="student")
	)
	all_students = frappe.get_all(
		"CRM Student", fields=["name", "enrollment_status"]
	)
	all_student_names = {row.name for row in all_students}

	orphaned_students = [row.name for row in all_students if row.name not in linked_students]

	dangling_contact_links = frappe.get_all(
		"CRM Contact",
		filters={"student": ["is", "set"]},
		fields=["name", "student"],
	)
	dangling_contact_links = [
		row.name for row in dangling_contact_links if row.student not in all_student_names
	]

	pre_milestone_students = [
		row.name for row in all_students if row.enrollment_status not in MILESTONE_ENROLLMENT_STATUSES
	]

	report = (
		f"Orphaned CRM Student (no linked CRM Contact): {len(orphaned_students)}\n"
		f"{orphaned_students}\n\n"
		f"CRM Contact with dangling student link: {len(dangling_contact_links)}\n"
		f"{dangling_contact_links}\n\n"
		f"CRM Student never reaching a milestone enrollment_status "
		f"(possible pre-Phase-2 unconditional auto-create): {len(pre_milestone_students)}\n"
		f"{pre_milestone_students}"
	)

	frappe.log_error(title="Phase 2 auto-created Student reconciliation report", message=report)
