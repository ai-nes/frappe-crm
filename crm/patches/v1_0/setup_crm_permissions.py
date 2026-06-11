"""
Replace Sales Manager / Sales User with 6 custom CRM roles across all DocTypes.
Writes updated permissions to the JSON files on disk, then calls reload_doc to
sync each DocType into the DB — the canonical Frappe approach.

Role matrix:
- Team Leader  : CRUD all records of campus
- Counseller   : CRU all records of campus (no delete)
- Sale         : Read all leads/contacts; write/create own students
- CTV-Sale     : Write/create own records only
- Promoter-PR  : Read-only on leads/contacts
- Administrator: Full access everywhere
"""

import json
import os

import frappe

# ── Permission builders ──────────────────────────────────────────────────────

def _p(role, *, read=0, write=0, create=0, delete=0,
        email=0, export=0, prt=0, report=0, share=0, if_owner=0):
	d = {"role": role}
	if read:     d["read"] = 1
	if write:    d["write"] = 1
	if create:   d["create"] = 1
	if delete:   d["delete"] = 1
	if email:    d["email"] = 1
	if export:   d["export"] = 1
	if prt:      d["print"] = 1
	if report:   d["report"] = 1
	if share:    d["share"] = 1
	if if_owner: d["if_owner"] = 1
	return d

def _full(role):
	return _p(role, read=1, write=1, create=1, delete=1,
	          email=1, export=1, prt=1, report=1, share=1)

def _read(role):
	return _p(role, read=1, report=1, prt=1, export=1)

# ── Permission sets per DocType category ────────────────────────────────────

STUDENT_PERMS = [
	_full("System Manager"),
	_full("Administrator"),
	_full("Team Leader"),
	_p("Counseller", read=1, write=1, create=1, email=1, prt=1, report=1, share=1),
	_p("Sale",       read=1, write=1, create=1, email=1, prt=1, if_owner=1),
	_p("CTV-Sale",   read=1, write=1, create=1, prt=1, if_owner=1),
]

# Sale gets two rows: read all leads + write own
CONTACT_PERMS = [
	_full("System Manager"),
	_full("Administrator"),
	_full("Team Leader"),
	_p("Counseller",  read=1, write=1, create=1, email=1, prt=1, report=1, share=1),
	_p("Sale",        read=1, report=1),
	_p("Sale",        write=1, create=1, email=1, prt=1, if_owner=1),
	_p("CTV-Sale",    read=1, write=1, create=1, prt=1, if_owner=1),
	_p("Promoter-PR", read=1, report=1, prt=1),
]

REF_PERMS = [
	_full("System Manager"),
	_full("Administrator"),
	_read("Team Leader"),
	_read("Counseller"),
	_p("Sale",        read=1),
	_p("CTV-Sale",    read=1),
	_p("Promoter-PR", read=1),
]

EDUCATION_PROGRAM_PERMS = [
	_full("System Manager"),
	_full("Administrator"),
	_read("Team Leader"),
	_read("Counseller"),
	_p("Sale",               read=1),
	_p("CTV-Sale",           read=1),
	_p("Promoter-PR",        read=1),
	_p("Enrollment Manager", read=1, write=1, create=1, prt=1, export=1),
]

OPS_PERMS = [
	_full("System Manager"),
	_full("Administrator"),
	_full("Team Leader"),
	_p("Counseller",  read=1, write=1, create=1, email=1, prt=1, report=1),
	_p("Sale",        read=1, write=1, create=1, prt=1, if_owner=1),
	_p("CTV-Sale",    read=1),
	_p("Promoter-PR", read=1),
]

SYS_PERMS = [
	_full("System Manager"),
	_full("Administrator"),
]

# ── DocType → permission set mapping ────────────────────────────────────────

DOCTYPE_PERMS = {
	"CRM Student":  STUDENT_PERMS,
	"CRM Contact":  CONTACT_PERMS,
	# Reference data
	"CRM Campus":            REF_PERMS,
	"CRM Major":             REF_PERMS,
	"CRM Major Group":       REF_PERMS,
	"CRM High School":       REF_PERMS,
	"CRM Province":          REF_PERMS,
	"CRM Ward":              REF_PERMS,
	"CRM Region":            REF_PERMS,
	"CRM School Type":       REF_PERMS,
	"CRM Aspiration":        REF_PERMS,
	"CRM Enrollment Status": REF_PERMS,
	"CRM Lead Source":       REF_PERMS,
	"CRM Admission Year":    REF_PERMS,
	"CRM Education Program": EDUCATION_PROGRAM_PERMS,
	"CRM Campaign Type":     REF_PERMS,
	"CRM Department":        REF_PERMS,
	"CRM Lost Reason":       REF_PERMS,
	"Holiday List":      REF_PERMS,
	# Operations
	"CRM Campaign": OPS_PERMS,
	"CRM Event":    OPS_PERMS,
	"CRM Staff":    OPS_PERMS,
	"CRM Person":   OPS_PERMS,
	"Task":     OPS_PERMS,
	"Call Log": OPS_PERMS,
	"FCRM Note":    OPS_PERMS,
	# System / config
	"Fields Layout":           SYS_PERMS,
	"Form Script":             SYS_PERMS,
	"View Settings":           SYS_PERMS,
	"Global Settings":         SYS_PERMS,
	"FCRM Settings":               SYS_PERMS,
	"Notification":            SYS_PERMS,
	"Dashboard":               SYS_PERMS,
	"Invitation":              SYS_PERMS,
	"Telephony Agent":         SYS_PERMS,
	"Service Level Agreement": SYS_PERMS,
	"CRM Influence":               SYS_PERMS,
	"CRM Academic Year Config":    SYS_PERMS,
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _update_json(doctype, perms, module):
	doctype_dir = frappe.scrub(doctype)
	json_path = os.path.join(
		frappe.get_module_path(module, "doctype", doctype_dir),
		f"{doctype_dir}.json",
	)
	if not os.path.exists(json_path):
		return

	try:
		with open(json_path, encoding="utf-8") as f:
			doc_json = json.load(f)

		doc_json["permissions"] = [dict(sorted(p.items())) for p in perms]

		with open(json_path, "w", encoding="utf-8") as f:
			json.dump(doc_json, f, indent=1, ensure_ascii=False)
			f.write("\n")
	except Exception as e:
		frappe.log_error(f"setup_crm_permissions: failed to update {doctype} JSON — {e}")


# ── Main ─────────────────────────────────────────────────────────────────────

def execute():
	# Batch-fetch existing doctypes and their modules in one query
	rows = frappe.get_all(
		"DocType",
		filters={"name": ["in", list(DOCTYPE_PERMS)]},
		fields=["name", "module"],
	)
	modules = {r.name: r.module for r in rows}

	for doctype, perms in DOCTYPE_PERMS.items():
		module = modules.get(doctype)
		if not module:
			continue
		_update_json(doctype, perms, module)
		frappe.reload_doc(module, "doctype", frappe.scrub(doctype), force=True)

	frappe.db.commit()
	frappe.clear_cache()
