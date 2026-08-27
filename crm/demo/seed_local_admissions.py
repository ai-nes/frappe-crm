"""Run the local admissions fixture without persisting rollout flags."""

import secrets
from contextlib import contextmanager

import frappe

from crm.demo import seed_admissions_cohort, seed_demo, seed_staff
from crm.fcrm.student_intake import _secret_versions
from crm.fcrm.student_ownership import _configured_secret

LOCAL_FLAGS = {
	"crm_student_routing_enabled": 1,
	"crm_student_sla_enabled": 1,
	"crm_student_context_read_enabled": 1,
	"crm_student_engagement_write_enabled": 1,
	"crm_student_lifecycle_write_enabled": 1,
	"crm_student_conversion_read_enabled": 1,
	"crm_student_conversion_write_enabled": 1,
	"crm_phase9_governance_write_enabled": 1,
	"crm_phase9_audit_read_enabled": 1,
}


@contextmanager
def _temporary_local_flags():
	previous = {key: frappe.conf.get(key) for key in LOCAL_FLAGS}
	prev_flags = {
		"crm_governance_additive": frappe.flags.get("crm_governance_additive"),
		"crm_governance_change": frappe.flags.get("crm_governance_change"),
	}
	try:
		for key, value in LOCAL_FLAGS.items():
			frappe.conf[key] = value
		frappe.flags.crm_governance_additive = True
		frappe.flags.crm_governance_change = True
		yield
	finally:
		for key, value in prev_flags.items():
			if value is None:
				frappe.flags.pop(key, None)
			else:
				frappe.flags[key] = value
		for key, value in previous.items():
			if value is None:
				frappe.conf.pop(key, None)
			else:
				frappe.conf[key] = value


def _assert_integrity_keys():
	if not _secret_versions() or not _configured_secret("v1"):
		frappe.throw(
			"Configure the existing Student intake and receipt HMAC keys before running task seed.",
			frappe.ValidationError,
		)


def ensure_local_integrity_keys():
	"""Persist random HMAC keys for the disposable local site when absent.

	Existing keys are intentionally preserved so rerunning the seed cannot
	invalidate receipt/idempotency signatures or interfere with local rotation.
	"""
	if frappe.local.site != "crm.localhost":
		frappe.throw("The local admissions seed only runs on crm.localhost.", frappe.PermissionError)

	from frappe.installer import update_site_config

	configured = []
	if not _secret_versions():
		update_site_config("student_intake_hmac_secret", secrets.token_urlsafe(32), validate=False)
		configured.append("student_intake_hmac_secret")
	if not _configured_secret("v1"):
		update_site_config("crm_receipt_hmac_secret", secrets.token_urlsafe(32), validate=False)
		configured.append("crm_receipt_hmac_secret")
	return {"configured": configured}


def execute():
	"""Seed the fixed crm.localhost cohort through the current service boundaries."""
	if frappe.local.site != "crm.localhost":
		frappe.throw("The local admissions seed only runs on crm.localhost.", frappe.PermissionError)
	_assert_integrity_keys()
	frappe.set_user("Administrator")
	with _temporary_local_flags():
		seed_demo.execute()
		seed_staff.execute()
		return seed_admissions_cohort.execute()
