"""
DocType-level permissions (DocPerm) for all CRM roles. Writes updated permissions to
the JSON files on disk, then calls reload_doc to sync each DocType into the DB — the
canonical Frappe approach. Idempotent — safe to rerun on every patch that changes a
permission set.

Row-level visibility for CRM Contact/CRM Student is NOT decided here — see
crm/fcrm/permissions.py and plans/260822-admissions-crm-alignment/business-rules-data-scope.md
for the locked scope matrix (Sale/Sale/Lead Sales/Sale/Marketing).

Marketing/Marketing scope to CRM Campaign/CRM Event only (not lead
ownership). Admissions Director/Admissions Director get system-wide Contact/Student
visibility via crm.fcrm.permissions.FULL_VISIBILITY_ROLES.
"""

import json
import os
import stat
import tempfile

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

# if_owner intentionally NOT used below — row visibility is enforced by the shared
# get_permission_query_conditions in crm/fcrm/permissions.py (keyed off Team Membership /
# assigned_to), not Frappe's native owner/creator field. See
# plans/260822-admissions-crm-alignment/business-rules-data-scope.md constraint 1.
STUDENT_PERMS = [
	_full("System Manager"),
	_full("Administrator"),
	_full("Lead Sales"),
	_p("Sale", read=1, write=1, create=1, email=1, prt=1, report=1, share=1),
	_p("Sale",       read=1, write=1, create=1, email=1, prt=1),
	_p("Sale",   read=1, write=1, create=1, prt=1),
	_p("Admissions Director", read=1, write=1, create=1, email=1, prt=1, report=1),
	_p("Admissions Director",   read=1, report=1, prt=1, export=1),
]

CONTACT_PERMS = [
	_full("System Manager"),
	_full("Administrator"),
	_full("Lead Sales"),
	_p("Sale",  read=1, write=1, create=1, email=1, prt=1, report=1, share=1),
	_p("Sale",        read=1, write=1, create=1, email=1, prt=1, report=1),
	_p("Sale",    read=1, write=1, create=1, prt=1),
	_p("Admissions Director", read=1, write=1, create=1, email=1, prt=1, report=1),
	_p("Admissions Director",   read=1, report=1, prt=1, export=1),
]

REF_PERMS = [
	_full("System Manager"),
	_full("Administrator"),
	_read("Lead Sales"),
	_read("Sale"),
	_p("Sale",        read=1),
	_p("Sale",    read=1),
	_p("Marketing", read=1),
	_p("Admissions Director", read=1),
	_p("Admissions Director",   read=1),
]

# Master-data-governance-owned lookup types (Phase 7): the owning role gets
# create+write so plain additive inserts (via before_insert/set_governance_defaults)
# work through the normal doctype permission table; the approver role gets
# read-only, since approve_change/reject_change apply the actual mutation via
# ignore_permissions=True and don't need doctype-level write access.
MARKETING_LOOKUP_PERMS = [
	_full("System Manager"),
	_full("Administrator"),
	_read("Lead Sales"),
	_read("Sale"),
	_p("Sale",        read=1),
	_p("Sale",    read=1),
	_p("Marketing", read=1),
	_p("Marketing", read=1, write=1, create=1, prt=1, report=1),
	_p("Marketing",     read=1, report=1, prt=1),
	_p("Admissions Director", read=1),
	_p("Admissions Director",   read=1),
]

LOST_REASON_PERMS = [
	_full("System Manager"),
	_full("Administrator"),
	_p("Lead Sales", read=1, report=1, prt=1),
	_read("Sale"),
	_p("Sale",        read=1),
	_p("Sale",    read=1),
	_p("Marketing", read=1),
	_p("Marketing", read=1, write=1, create=1, prt=1, report=1),
	_p("Marketing",   read=1, report=1, prt=1),
	_p("Admissions Director", read=1),
	_p("Admissions Director",   read=1),
]

CAMPUS_PERMS = [
	_full("System Manager"),
	_full("Administrator"),
	_read("Lead Sales"),
	_read("Sale"),
	_p("Sale",        read=1),
	_p("Sale",    read=1),
	_p("Marketing", read=1),
	_p("Admissions Director", read=1, write=1, create=1, prt=1, report=1),
	_p("Admissions Director",   read=1, report=1, prt=1, export=1),
]

EDUCATION_PROGRAM_PERMS = [
	_full("System Manager"),
	_full("Administrator"),
	_read("Lead Sales"),
	_read("Sale"),
	_p("Sale",               read=1),
	_p("Sale",           read=1),
	_p("Marketing",        read=1),
	_p("Admissions Director", read=1, write=1, create=1, prt=1, export=1),
	_p("Admissions Director", read=1),
	_p("Admissions Director",   read=1),
]

OPS_PERMS = [
	_full("System Manager"),
	_full("Administrator"),
	_full("Lead Sales"),
	_p("Sale",  read=1, write=1, create=1, email=1, prt=1, report=1),
	_p("Sale",        read=1, write=1, create=1, prt=1, if_owner=1),
	_p("Sale",    read=1),
	_p("Marketing", read=1),
	_p("Admissions Director", read=1, write=1, create=1, email=1, prt=1, report=1),
	_p("Admissions Director",   read=1, report=1),
]

RECOMMENDATION_PERMS = [
	_full("System Manager"),
	_full("Administrator"),
	_p("Lead Sales", read=1, write=1, email=1, prt=1, report=1),
	_p("Sale", read=1, write=1, email=1, prt=1, report=1),
	_p("Sale", read=1, write=1, prt=1),
	_p("Sale", read=1, write=1, prt=1),
	_p("Marketing", read=1),
]

SALES_ACTION_PERMS = [
	_full("System Manager"),
	_full("Administrator"),
	_p("Lead Sales", read=1, write=1, create=1, email=1, prt=1, report=1),
	_p("Sale", read=1, write=1, create=1, email=1, prt=1, report=1),
	_p("Sale", read=1, write=1, create=1, prt=1, report=1),
	_p("Sale", read=1, write=1, create=1, prt=1),
	_p("Marketing", read=1),
]

# Marketing roles are scoped to Campaign/Event ownership, not lead ownership — see
# business-rules-data-scope.md. Not granted access to CRM Contact/CRM Student here.
CAMPAIGN_EVENT_PERMS = [
	_full("System Manager"),
	_full("Administrator"),
	_full("Lead Sales"),
	_p("Sale",  read=1, report=1, prt=1),
	_p("Sale",        read=1),
	_p("Sale",    read=1),
	_p("Marketing", read=1),
	_full("Marketing"),
	_p("Marketing", read=1, write=1, create=1, email=1, prt=1, report=1),
	_p("Admissions Director", read=1, report=1),
	_p("Admissions Director",   read=1, report=1, export=1),
]

TEAM_PERMS = [
	_full("System Manager"),
	_full("Administrator"),
	_read("Lead Sales"),
	_read("Sale"),
	_p("Sale",        read=1),
	_p("Sale",    read=1),
	_p("Marketing", read=1),
	_p("Marketing",     read=1),
	_p("Marketing",         read=1),
	_p("Admissions Director",  read=1),
	_p("Admissions Director",    read=1),
]

SYS_PERMS = [
	_full("System Manager"),
	_full("Administrator"),
]

# ── DocType → permission set mapping ────────────────────────────────────────

DOCTYPE_PERMS = {
	"CRM Student":  STUDENT_PERMS,
	"CRM Contact":  CONTACT_PERMS,
	"CRM Score Template": REF_PERMS,
	"CRM Score History":  OPS_PERMS,
	"CRM Recommendation": RECOMMENDATION_PERMS,
	"CRM Sales Action": SALES_ACTION_PERMS,
	# Reference data
	"CRM Campus":            CAMPUS_PERMS,
	"CRM Major":             REF_PERMS,
	"CRM Major Group":       REF_PERMS,
	"CRM High School":       REF_PERMS,
	"CRM Province":          REF_PERMS,
	"CRM Ward":              REF_PERMS,
	"CRM Region":            REF_PERMS,
	"CRM School Type":       REF_PERMS,
	"CRM Aspiration":        REF_PERMS,
	"CRM Enrollment Status": REF_PERMS,
	"CRM Lead Source":       MARKETING_LOOKUP_PERMS,
	"CRM Platform":          MARKETING_LOOKUP_PERMS,
	"CRM Intent Type":       MARKETING_LOOKUP_PERMS,
	"CRM Admission Year":    REF_PERMS,
	"CRM Education Program": EDUCATION_PROGRAM_PERMS,
	"CRM Campaign Type":     REF_PERMS,
	"CRM Department":        REF_PERMS,
	"CRM Lost Reason":       LOST_REASON_PERMS,
	"Holiday List":      REF_PERMS,
	"CRM Team":          TEAM_PERMS,
	# Operations
	"CRM Campaign": CAMPAIGN_EVENT_PERMS,
	"CRM Event":    CAMPAIGN_EVENT_PERMS,
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

def _merge_duplicate_permissions(perms):
	"""Keep the least-privilege common grant for each canonical role."""
	grouped = {}
	for permission in perms:
		grouped.setdefault(permission["role"], []).append(permission)
	merged = []
	for role, rows in grouped.items():
		common = {"role": role}
		for key in set().union(*(row.keys() for row in rows)) - {"role"}:
			if all(row.get(key) for row in rows):
				common[key] = 1
		merged.append(common)
	return merged


DOCTYPE_PERMS = {doctype: _merge_duplicate_permissions(perms) for doctype, perms in DOCTYPE_PERMS.items()}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _stage_json(doctype, perms, module):
	"""Render one permission JSON file into a same-directory staging file.

		All files are staged before any is published.  The original bytes and mode
		are retained so a later publish/reload failure can restore the whole batch.
	"""
	doctype_dir = frappe.scrub(doctype)
	json_path = os.path.join(
		frappe.get_module_path(module, "doctype", doctype_dir),
		f"{doctype_dir}.json",
	)
	if not os.path.exists(json_path):
		return None

	with open(json_path, "rb") as original_file:
		original = original_file.read()
	staged = False
	try:
		doc_json = json.loads(original.decode("utf-8"))

		doc_json["permissions"] = [dict(sorted(p.items())) for p in perms]

		fd, temp_path = tempfile.mkstemp(
			prefix=f".{doctype_dir}.", suffix=".json.tmp", dir=os.path.dirname(json_path)
		)
		try:
			with os.fdopen(fd, "w", encoding="utf-8") as f:
				json.dump(doc_json, f, indent=1, ensure_ascii=False)
				f.write("\n")
				f.flush()
				os.fsync(f.fileno())
			staged = True
			return {
				"doctype": doctype,
				"module": module,
				"json_path": json_path,
				"temp_path": temp_path,
				"original": original,
				"mode": stat.S_IMODE(os.stat(json_path).st_mode),
			}
		finally:
			if os.path.exists(temp_path) and not staged:
				os.unlink(temp_path)
	except Exception as e:
		# Permission JSON is part of the cutover transaction.  Continuing after a
		# failed write would reload stale permissions and commit a partial policy.
		raise RuntimeError(f"setup_crm_permissions: failed to update {doctype} JSON") from e


def _update_json(doctype, perms, module):
	"""Backward-compatible single-file helper used by older patches/tests."""
	staged = _stage_json(doctype, perms, module)
	if staged is None:
		return
	try:
		os.replace(staged["temp_path"], staged["json_path"])
		os.chmod(staged["json_path"], staged["mode"])
	finally:
		if os.path.exists(staged["temp_path"]):
			os.unlink(staged["temp_path"])


def _restore_staged_json(staged):
	for item in reversed(staged):
		fd, temp_path = tempfile.mkstemp(
			prefix=f".{frappe.scrub(item['doctype'])}.restore.",
			suffix=".json.tmp",
			dir=os.path.dirname(item["json_path"]),
		)
		try:
			with os.fdopen(fd, "wb") as f:
				f.write(item["original"])
				f.flush()
				os.fsync(f.fileno())
			os.replace(temp_path, item["json_path"])
			os.chmod(item["json_path"], item["mode"])
		finally:
			if os.path.exists(temp_path):
				os.unlink(temp_path)


# ── Main ─────────────────────────────────────────────────────────────────────

def execute(*, commit=True):
	# Batch-fetch existing doctypes and their modules in one query
	rows = frappe.get_all(
		"DocType",
		filters={"name": ["in", list(DOCTYPE_PERMS)]},
		fields=["name", "module"],
	)
	modules = {r.name: r.module for r in rows}

	staged = []
	try:
		# Stage every candidate before publishing any file.  This catches malformed
		# JSON, missing directories, and disk errors before the first mutation.
		for doctype, perms in DOCTYPE_PERMS.items():
			module = modules.get(doctype)
			if module:
				item = _stage_json(doctype, perms, module)
				if item:
					staged.append(item)
		for item in staged:
			os.replace(item["temp_path"], item["json_path"])
			os.chmod(item["json_path"], item["mode"])
		for item in staged:
			frappe.reload_doc(item["module"], "doctype", frappe.scrub(item["doctype"]), force=True)
		if commit:
			frappe.db.commit()
		frappe.clear_cache()
	except Exception:
		try:
			_restore_staged_json(staged)
			frappe.db.rollback()
		except Exception:
			frappe.log_error(frappe.get_traceback(), "setup_crm_permissions rollback failed")
		raise
	finally:
		for item in staged:
			if os.path.exists(item["temp_path"]):
				os.unlink(item["temp_path"])
