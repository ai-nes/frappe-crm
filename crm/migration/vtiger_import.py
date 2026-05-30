# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# vTiger → Frappe CRM import pipeline.
#
# Usage (single-threaded — do not run concurrent sessions against the same site):
#   bench --site crm.localhost execute crm.migration.vtiger_import.run \
#     --kwargs '{"step": "all", "fixtures_path": "crm/migration/fixtures", "dry_run": false}'
#
# Steps: provinces | wards | majors | branches | schools | leads | contacts | all

import csv
import json
import os

import frappe

from crm.migration.vtiger_transform import (
	build_first_name,
	build_lead_name,
	clean_email,
	normalize_phone,
	resolve_ward_province,
	safe_int,
)

BATCH_SIZE = 100
MAPS_DIR = os.path.join(os.path.dirname(__file__), "id_maps")


# ---------------------------------------------------------------------------
# Map persistence
# ---------------------------------------------------------------------------


def save_map(name, data):
	os.makedirs(MAPS_DIR, exist_ok=True)
	path = os.path.join(MAPS_DIR, f"{name}.json")
	with open(path, "w", encoding="utf-8") as f:
		json.dump({str(k): v for k, v in data.items()}, f, ensure_ascii=False, indent=2)


def load_map(name):
	path = os.path.join(MAPS_DIR, f"{name}.json")
	if not os.path.exists(path):
		raise FileNotFoundError(f"Required map missing: {path}. Run earlier steps first.")
	with open(path, encoding="utf-8") as f:
		return {safe_int(k): v for k, v in json.load(f).items()}


def _log(msg):
	frappe.log_error(msg, "vtiger_import") if frappe.flags.in_test else print(msg)


def _open_csv(fixtures_path, filename):
	path = os.path.join(fixtures_path, filename)
	if not os.path.exists(path):
		return []
	with open(path, newline="", encoding="utf-8-sig") as f:
		return list(csv.DictReader(f))


def _append_log(log_lines, entity, row_id, status, error=""):
	log_lines.append(json.dumps({"entity": entity, "id": row_id, "status": status, "error": error}))


def _flush_log(log_lines):
	if not log_lines:
		return
	os.makedirs(MAPS_DIR, exist_ok=True)
	path = os.path.join(MAPS_DIR, "import_log.jsonl")
	with open(path, "a", encoding="utf-8") as f:
		f.write("\n".join(log_lines) + "\n")
	log_lines.clear()


# ---------------------------------------------------------------------------
# Import steps
# ---------------------------------------------------------------------------


def import_provinces(fixtures_path, dry_run=False):
	rows = _open_csv(fixtures_path, "provinces.csv")
	province_map = {}
	ok = skip = fail = 0
	log_lines = []

	for row in rows:
		city_number = (row.get("city_number") or "").strip()
		province_name = (row.get("city_name") or row.get("province_name") or "").strip()
		citysid = safe_int(row.get("citysid"))
		if not province_name:
			continue
		existing = frappe.db.get_value("CRM Province", {"city_number": city_number}, "name") if city_number else None
		if existing:
			province_map[citysid] = existing
			skip += 1
			continue
		if dry_run:
			province_map[citysid] = province_name
			ok += 1
			continue
		try:
			doc = frappe.get_doc({
				"doctype": "CRM Province",
				"province_name": province_name,
				"city_type": (row.get("city_type") or "").strip() or None,
				"city_number": city_number or None,
				"import_source_id": citysid,
			})
			doc.insert(ignore_permissions=True)
			province_map[citysid] = doc.name
			ok += 1
			_append_log(log_lines, "province", citysid, "ok")
		except Exception as e:
			fail += 1
			_append_log(log_lines, "province", citysid, "fail", str(e))
			frappe.log_error(frappe.get_traceback(), "vtiger_import:province")

	save_map("province_map", province_map)
	_flush_log(log_lines)
	_log(f"Provinces: ok={ok} skip={skip} fail={fail}")
	return province_map


def import_wards(fixtures_path, dry_run=False):
	province_map = load_map("province_map")
	rows = _open_csv(fixtures_path, "wards.csv")
	ward_map = {}
	ok = skip = fail = 0
	log_lines = []
	province_cache = {}

	for row in rows:
		ward_name = (row.get("ward_name") or "").strip()
		wardsid = safe_int(row.get("wardsid"))
		city_id_str = (row.get("city_id") or "").strip()
		if not ward_name:
			continue
		# Cache province lookups — same city_id_str repeats for every ward in the city
		if city_id_str not in province_cache:
			province_cache[city_id_str] = resolve_ward_province(city_id_str, frappe)
		province_name = province_cache[city_id_str]

		existing = frappe.db.get_value("CRM Ward", {"ward_name": ward_name, "province": province_name}, "name")
		if existing:
			ward_map[wardsid] = existing
			skip += 1
			continue
		if dry_run:
			ward_map[wardsid] = ward_name
			ok += 1
			continue
		try:
			doc = frappe.get_doc({
				"doctype": "CRM Ward",
				"ward_name": ward_name,
				"province": province_name,
				"ward_type": (row.get("ward_type") or "").strip() or None,
				"import_source_id": wardsid,
			})
			doc.insert(ignore_permissions=True)
			ward_map[wardsid] = doc.name
			ok += 1
			_append_log(log_lines, "ward", wardsid, "ok")
		except Exception as e:
			fail += 1
			_append_log(log_lines, "ward", wardsid, "fail", str(e))
			frappe.log_error(frappe.get_traceback(), "vtiger_import:ward")

	save_map("ward_map", ward_map)
	_flush_log(log_lines)
	_log(f"Wards: ok={ok} skip={skip} fail={fail}")
	return ward_map


def import_majors(fixtures_path, dry_run=False):
	rows = _open_csv(fixtures_path, "majors.csv")
	major_map = {}
	ok = skip = fail = 0
	log_lines = []

	for row in rows:
		major_name = (row.get("major_name") or "").strip()
		majorsid = safe_int(row.get("majorsid"))
		if not major_name:
			continue
		if frappe.db.exists("CRM Major", major_name):
			major_map[majorsid] = major_name
			skip += 1
			continue
		if dry_run:
			major_map[majorsid] = major_name
			ok += 1
			continue
		try:
			doc = frappe.get_doc({
				"doctype": "CRM Major",
				"major_name": major_name,
				"major_code": (row.get("major_code") or "").strip() or None,
				"major_group": (row.get("major_group") or "").strip() or None,
				"is_active": int(row.get("is_active") or 1),
				"import_source_id": majorsid,
			})
			doc.insert(ignore_permissions=True)
			major_map[majorsid] = doc.name
			ok += 1
			_append_log(log_lines, "major", majorsid, "ok")
		except Exception as e:
			fail += 1
			_append_log(log_lines, "major", majorsid, "fail", str(e))
			frappe.log_error(frappe.get_traceback(), "vtiger_import:major")

	save_map("major_map", major_map)
	_flush_log(log_lines)
	_log(f"Majors: ok={ok} skip={skip} fail={fail}")
	return major_map


def import_branches(fixtures_path, dry_run=False):
	rows = _open_csv(fixtures_path, "branches.csv")
	ok = skip = fail = 0
	branch_map = {}
	log_lines = []

	default_branches = [
		{"branch_name": "Hà Nội", "branch_code": "ha_noi"},
		{"branch_name": "Hồ Chí Minh", "branch_code": "ho_chi_minh"},
		{"branch_name": "Đà Nẵng", "branch_code": "da_nang"},
		{"branch_name": "Quy Nhơn", "branch_code": "quy_nhon"},
		{"branch_name": "Cần Thơ", "branch_code": "can_tho"},
	]

	for row in (rows if rows else default_branches):
		branch_name = (row.get("leads_campus") or row.get("branch_name") or "").strip()
		branch_code = (row.get("branch_code") or "").strip() or None
		campusid = safe_int(row.get("leads_campusid"))
		if not branch_name:
			continue
		existing = frappe.db.get_value("CRM Branch", branch_name, "name")
		if existing:
			branch_map[branch_name] = existing
			skip += 1
			continue
		if dry_run:
			branch_map[branch_name] = branch_name
			ok += 1
			continue
		try:
			doc = frappe.get_doc({
				"doctype": "CRM Branch",
				"branch_name": branch_name,
				"branch_code": branch_code,
				"import_source_id": campusid,
			})
			doc.insert(ignore_permissions=True)
			branch_map[branch_name] = doc.name
			ok += 1
			_append_log(log_lines, "branch", branch_name, "ok")
		except Exception as e:
			fail += 1
			_append_log(log_lines, "branch", branch_name, "fail", str(e))
			frappe.log_error(frappe.get_traceback(), "vtiger_import:branch")

	save_map("branch_map", branch_map)
	_flush_log(log_lines)
	_log(f"Branches: ok={ok} skip={skip} fail={fail}")
	return branch_map


def import_schools(fixtures_path, dry_run=False):
	province_map = load_map("province_map")
	ward_map = load_map("ward_map")
	rows = _open_csv(fixtures_path, "schools.csv")
	school_map = {}
	ok = skip = fail = 0
	log_lines = []

	for row in rows:
		org_name = (row.get("accountname") or "").strip()
		accountid = safe_int(row.get("accountid"))
		if not org_name:
			continue
		existing = frappe.db.get_value("CRM Organization", org_name, "name")
		if existing:
			school_map[accountid] = existing
			skip += 1
			continue
		cf_city = safe_int(row.get("cf_city"))
		cf_ward = safe_int(row.get("cf_ward"))
		if dry_run:
			school_map[accountid] = org_name
			ok += 1
			continue
		try:
			doc = frappe.get_doc({
				"doctype": "CRM Organization",
				"organization_name": org_name,
				"website": (row.get("website") or "").strip() or None,
				"province": province_map.get(cf_city),
				"ward": ward_map.get(cf_ward),
				"import_source_id": accountid,
			})
			doc.insert(ignore_permissions=True)
			school_map[accountid] = doc.name
			ok += 1
			_append_log(log_lines, "school", accountid, "ok")
		except Exception as e:
			fail += 1
			_append_log(log_lines, "school", accountid, "fail", str(e))
			frappe.log_error(frappe.get_traceback(), "vtiger_import:school")

	save_map("school_map", school_map)
	_flush_log(log_lines)
	_log(f"Schools: ok={ok} skip={skip} fail={fail}")
	return school_map


def import_leads(fixtures_path, dry_run=False):
	province_map = load_map("province_map")
	school_map = load_map("school_map")
	major_map = load_map("major_map")

	try:
		users_map = load_map("users_map")
	except FileNotFoundError:
		users_map = {}

	# Pre-fetch branch name→doc name map to avoid N+1 queries inside loop
	branch_name_map = {r.branch_name: r.name for r in frappe.get_all("CRM Branch", fields=["name", "branch_name"])}

	rows = _open_csv(fixtures_path, "leads.csv")
	lead_map = {}
	ok = skip = fail = 0
	log_lines = []

	for i, row in enumerate(rows):
		leadid = safe_int(row.get("leadid"))
		mobile = normalize_phone(row.get("mobile"))
		email = clean_email(row.get("email"))

		existing = None
		if mobile:
			existing = frappe.db.get_value("CRM Lead", {"mobile_no": mobile}, "name")
		if not existing and email:
			existing = frappe.db.get_value("CRM Lead", {"email": email}, "name")

		if existing:
			lead_map[leadid] = existing
			skip += 1
			continue

		firstname = build_first_name(row.get("firstname"), row.get("lastname"))
		lastname = (row.get("lastname") or "").strip() or "N/A"

		if dry_run:
			lead_map[leadid] = f"dry-run-{leadid}"
			ok += 1
			continue

		try:
			doc = frappe.get_doc({
				"doctype": "CRM Lead",
				"first_name": firstname,
				"last_name": lastname,
				"lead_name": build_lead_name(row.get("firstname"), row.get("lastname")),
				"email": email,
				"other_email": clean_email(row.get("secondaryemail")),
				"mobile_no": mobile,
				"phone": normalize_phone(row.get("phone")),
				"website": (row.get("website") or "").strip() or None,
				"source": (row.get("leadsource") or "").strip() or None,
				"status": (row.get("leadstatus") or "New").strip(),
				"converted": int(row.get("converted") or 0),
				"conversion_potential": (row.get("rating") or "").strip() or None,
				"organization": (row.get("company") or "").strip() or None,
				"province": province_map.get(safe_int(row.get("cf_city"))),
				"high_school": school_map.get(safe_int(row.get("cf_school"))),
				"major": major_map.get(safe_int(row.get("cf_major"))),
				"branch": branch_name_map.get((row.get("leads_campus") or "").strip()),
				"ad_channel": (row.get("cf_kenh_quang_cao") or "").strip() or None,
				"segments": (row.get("cf_segment") or "").strip() or None,
				"fpt_aspiration": (row.get("cf_nvfpt") or "").strip() or None,
				"lead_owner": users_map.get(safe_int(row.get("smownerid"))),
				"import_source_id": leadid,
			})
			doc.insert(ignore_permissions=True)
			lead_map[leadid] = doc.name

			if row.get("description"):
				frappe.get_doc({
					"doctype": "FCRM Note",
					"reference_doctype": "CRM Lead",
					"reference_docname": doc.name,
					"content": row["description"],
				}).insert(ignore_permissions=True)

			ok += 1
			_append_log(log_lines, "lead", leadid, "ok")
		except Exception as e:
			fail += 1
			_append_log(log_lines, "lead", leadid, "fail", str(e))
			frappe.log_error(frappe.get_traceback(), "vtiger_import:lead")

		if (i + 1) % BATCH_SIZE == 0:
			frappe.db.commit()
			_flush_log(log_lines)

	save_map("lead_map", lead_map)
	frappe.db.commit()
	_flush_log(log_lines)
	_log(f"Leads: ok={ok} skip={skip} fail={fail}")
	return lead_map


def import_contacts(fixtures_path, dry_run=False):
	lead_map = load_map("lead_map")
	major_map = load_map("major_map")
	school_map = load_map("school_map")

	rows = _open_csv(fixtures_path, "contacts.csv")
	contact_map = {}
	ok = skip = fail = 0
	log_lines = []

	for i, row in enumerate(rows):
		contactid = safe_int(row.get("contactid"))
		mobile = normalize_phone(row.get("mobile"))
		email = clean_email(row.get("email"))

		existing = None
		if mobile:
			existing = frappe.db.get_value("Contact", {"mobile_no": mobile}, "name")
		if not existing and email:
			existing = frappe.db.get_value("Contact", {"email_id": email}, "name")

		if existing:
			contact_map[contactid] = existing
			skip += 1
			continue

		if dry_run:
			contact_map[contactid] = f"dry-run-{contactid}"
			ok += 1
			continue

		try:
			doc = frappe.get_doc({
				"doctype": "Contact",
				"first_name": build_first_name(row.get("firstname"), row.get("lastname")),
				"last_name": (row.get("lastname") or "").strip() or None,
				"email_id": email,
				"mobile_no": mobile,
				"phone": normalize_phone(row.get("phone")),
				"source_lead": lead_map.get(safe_int(row.get("cf_source_lead_id"))),
				"major": major_map.get(safe_int(row.get("cf_major"))),
				"school": school_map.get(safe_int(row.get("accountid"))),
				"source": (row.get("leadsource") or "").strip() or None,
				"import_source_id": contactid,
			})
			doc.insert(ignore_permissions=True)
			contact_map[contactid] = doc.name
			ok += 1
			_append_log(log_lines, "contact", contactid, "ok")
		except Exception as e:
			fail += 1
			_append_log(log_lines, "contact", contactid, "fail", str(e))
			frappe.log_error(frappe.get_traceback(), "vtiger_import:contact")

		if (i + 1) % BATCH_SIZE == 0:
			frappe.db.commit()
			_flush_log(log_lines)

	save_map("contact_map", contact_map)
	frappe.db.commit()
	_flush_log(log_lines)
	_log(f"Contacts: ok={ok} skip={skip} fail={fail}")
	return contact_map


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

# Ordered list of (step_name, fn) — ALL_ORDER is derived to stay in sync
_PIPELINE = [
	("provinces", import_provinces),
	("wards", import_wards),
	("majors", import_majors),
	("branches", import_branches),
	("schools", import_schools),
	("leads", import_leads),
	("contacts", import_contacts),
]

STEPS = {name: fn for name, fn in _PIPELINE}
ALL_ORDER = [name for name, _ in _PIPELINE]


def run(step="all", fixtures_path=None, dry_run=False):
	if fixtures_path is None:
		fixtures_path = os.path.join(frappe.get_app_path("crm"), "migration", "fixtures")

	if step == "all":
		for name, fn in _PIPELINE:
			fn(fixtures_path, dry_run=dry_run)
	elif step in STEPS:
		STEPS[step](fixtures_path, dry_run=dry_run)
	else:
		raise ValueError(f"Unknown step '{step}'. Valid: {', '.join(STEPS)} | all")

	_log(f"Import complete — step={step} dry_run={dry_run}")
