"""One-time backfill: populate lifecycle_stage on existing CRM Contact and
CRM Student rows from their current enrollment_status, using the same
CRM Enrollment Status.lifecycle_stage lookup that CRMContact/CRMStudent
.validate() now applies on every save (see crm.fcrm.lifecycle.
get_lifecycle_stage). Runs after seed_lifecycle_stage_on_enrollment_status so
the lookup table is populated. Idempotent — only touches rows where
lifecycle_stage is unset.
"""

import frappe

DOCTYPES = ["CRM Contact", "CRM Student"]


def execute():
	frappe.reload_doc("fcrm", "doctype", "crm_contact", force=True)
	frappe.reload_doc("fcrm", "doctype", "crm_student", force=True)

	for doctype in DOCTYPES:
		frappe.db.sql(
			f"""
			update `tab{doctype}` c
			join `tabCRM Enrollment Status` s on s.name = c.enrollment_status
			set c.lifecycle_stage = s.lifecycle_stage
			where c.lifecycle_stage is null or c.lifecycle_stage = ''
			"""
		)

	frappe.db.commit()
