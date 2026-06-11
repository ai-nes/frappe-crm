"""
Extend permissions to cover CRM Education Program (master DocType added with
the student extended attributes feature) and reload CRM Student to pick up the
new child table fields.

Child tables (CRM Student Academic Result, CRM Student Language Certificate)
carry no permissions — access is governed by the parent CRM Student DocType.

For NEW deployments: setup_crm_permissions also covers CRM Education Program
via EDUCATION_PROGRAM_PERMS in its DOCTYPE_PERMS registry. This patch handles
EXISTING deployments where setup_crm_permissions has already run.
"""

import json
import os

import frappe
from crm.patches.v1_0.setup_crm_permissions import EDUCATION_PROGRAM_PERMS


def _update_json_strict(doctype, perms, module):
	"""Like setup_crm_permissions._update_json but raises on missing file."""
	doctype_dir = frappe.scrub(doctype)
	json_path = os.path.join(
		frappe.get_module_path(module, "doctype", doctype_dir),
		f"{doctype_dir}.json",
	)
	if not os.path.exists(json_path):
		frappe.log_error(
			f"{json_path} not found — permissions not written",
			"setup_crm_student_extended_permissions",
		)
		raise frappe.ValidationError(
			f"setup_crm_student_extended_permissions: {json_path} not on disk. "
			"Ensure Phase 1 files are deployed before running bench migrate."
		)

	with open(json_path, encoding="utf-8") as f:
		doc_json = json.load(f)

	doc_json["permissions"] = [dict(sorted(p.items())) for p in perms]

	with open(json_path, "w", encoding="utf-8") as f:
		json.dump(doc_json, f, indent=1, ensure_ascii=False)
		f.write("\n")


def execute():
	_update_json_strict("CRM Education Program", EDUCATION_PROGRAM_PERMS, "FCRM")
	frappe.reload_doc("FCRM", "doctype", "crm_education_program", force=True)

	frappe.db.commit()
	frappe.clear_cache()
