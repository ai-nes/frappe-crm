"""Repair admission references affected by the CRM Term name canonicalization."""

from crm.patches.v1_0.normalize_enrollment_term_names import repair_enrollment_status_references


def execute():
	repair_enrollment_status_references()
