"""
Parse a vTiger SQL dump and export CSV fixtures for vtiger_import.py.

Usage:
    python crm/migration/sql_to_fixtures.py \
        --sql docs/crm-v8-test-trc.sql \
        --out crm/migration/fixtures

Output files (one per import step):
    provinces.csv  wards.csv  majors.csv  branches.csv
    schools.csv    leads.csv  contacts.csv
"""

import argparse
import csv
import json
import os
import re
import sys
from collections import defaultdict


# ---------------------------------------------------------------------------
# SQL parser — extract INSERT rows into in-memory tables
# ---------------------------------------------------------------------------

_INSERT_RE = re.compile(r"INSERT INTO `(\w+)` \(([^)]+)\) VALUES\s*(.*);?\s*$", re.DOTALL)
_ROW_SPLIT_RE = re.compile(r"\),\s*\(")


def _unquote(val: str) -> str:
    """Strip surrounding quotes and unescape MySQL string escapes."""
    val = val.strip()
    if val.upper() == "NULL":
        return ""
    if val.startswith("'") and val.endswith("'"):
        val = val[1:-1]
        val = val.replace("\\'", "'").replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")
    return val


def _parse_values(values_str: str) -> list[list[str]]:
    """Split a VALUES clause into a list of row-value lists."""
    values_str = values_str.strip().rstrip(";").strip()
    # Remove outer parens of first and last row
    if values_str.startswith("("):
        values_str = values_str[1:]
    if values_str.endswith(")"):
        values_str = values_str[:-1]

    raw_rows = _ROW_SPLIT_RE.split(values_str)
    result = []
    for raw in raw_rows:
        # Simple tokenizer: handles 'string with, comma', numbers, NULL
        tokens: list[str] = []
        buf = ""
        in_str = False
        escape = False
        for ch in raw:
            if escape:
                buf += ch
                escape = False
            elif ch == "\\":
                buf += ch
                escape = True
            elif ch == "'" and not in_str:
                in_str = True
                buf += ch
            elif ch == "'" and in_str:
                in_str = False
                buf += ch
            elif ch == "," and not in_str:
                tokens.append(_unquote(buf))
                buf = ""
            else:
                buf += ch
        tokens.append(_unquote(buf))
        result.append(tokens)
    return result


def load_tables(sql_path: str, want: set[str]) -> dict[str, list[dict]]:
    """
    Stream-parse the SQL file and collect rows for all tables in `want`.
    Returns {table_name: [{"col": value, ...}, ...]}.
    """
    tables: dict[str, list[dict]] = defaultdict(list)
    buf: list[str] = []
    capturing = False

    with open(sql_path, encoding="utf-8", errors="replace") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n")

            # Detect INSERT start
            if line.startswith("INSERT INTO `"):
                m_table = re.match(r"INSERT INTO `(\w+)`", line)
                if m_table and m_table.group(1) in want:
                    buf = [line]
                    capturing = True
                    continue

            if capturing:
                buf.append(line)
                if line.rstrip().endswith(";"):
                    full = " ".join(buf)
                    m = _INSERT_RE.match(full)
                    if m:
                        tbl = m.group(1)
                        cols = [c.strip().strip("`") for c in m.group(2).split(",")]
                        for row_vals in _parse_values(m.group(3)):
                            if len(row_vals) == len(cols):
                                tables[tbl].append(dict(zip(cols, row_vals)))
                    buf = []
                    capturing = False

    return dict(tables)


# ---------------------------------------------------------------------------
# Join helpers
# ---------------------------------------------------------------------------

def index_by(rows: list[dict], key: str) -> dict[str, dict]:
    return {r[key]: r for r in rows if r.get(key)}


def index_multi(rows: list[dict], key: str) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get(key):
            result[r[key]].append(r)
    return dict(result)


# ---------------------------------------------------------------------------
# CSV writers
# ---------------------------------------------------------------------------

def write_csv(path: str, fieldnames: list[str], rows: list[dict]) -> int:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


# ---------------------------------------------------------------------------
# Per-entity extractors
# ---------------------------------------------------------------------------

def extract_provinces(tables: dict, out_dir: str) -> int:
    rows = tables.get("vtiger_citys", [])
    out = [
        {
            "citysid": r["citysid"],
            "city_name": r.get("city_name", ""),
            "city_type": r.get("city_type", ""),
            "city_number": r.get("city_number", ""),
        }
        for r in rows
    ]
    return write_csv(os.path.join(out_dir, "provinces.csv"),
                     ["citysid", "city_name", "city_type", "city_number"], out)


def extract_wards(tables: dict, out_dir: str) -> int:
    rows = tables.get("vtiger_wards", [])
    out = [
        {
            "wardsid": r["wardsid"],
            "ward_name": r.get("ward_name", ""),
            "city_id": r.get("city_id", ""),
            "ward_type": r.get("ward_type", ""),
        }
        for r in rows
    ]
    return write_csv(os.path.join(out_dir, "wards.csv"),
                     ["wardsid", "ward_name", "city_id", "ward_type"], out)


def extract_majors(tables: dict, out_dir: str) -> int:
    rows = tables.get("vtiger_majors", [])
    out = [
        {
            "majorsid": r["majorsid"],
            "major_name": r.get("major_name", ""),
            "major_code": r.get("major_code", ""),
            "major_group": r.get("major_group", ""),
            "is_active": r.get("is_active", "1"),
        }
        for r in rows
    ]
    return write_csv(os.path.join(out_dir, "majors.csv"),
                     ["majorsid", "major_name", "major_code", "major_group", "is_active"], out)


def extract_branches(tables: dict, out_dir: str) -> int:
    rows = tables.get("vtiger_leads_campus", [])
    out = [
        {
            "leads_campusid": r["leads_campusid"],
            "leads_campus": r.get("leads_campus", ""),
            "branch_code": "",
        }
        for r in rows
        if r.get("presence", "1") != "0"
    ]
    return write_csv(os.path.join(out_dir, "branches.csv"),
                     ["leads_campusid", "leads_campus", "branch_code"], out)


def extract_schools(tables: dict, out_dir: str) -> int:
    accounts = tables.get("vtiger_account", [])
    scf_idx = index_by(tables.get("vtiger_accountscf", []), "accountid")
    out = []
    for r in accounts:
        aid = r["accountid"]
        scf = scf_idx.get(aid, {})
        out.append({
            "accountid": aid,
            "accountname": r.get("accountname", ""),
            "website": r.get("website", ""),
            "cf_city": scf.get("cf_city", ""),
            "cf_ward": scf.get("cf_ward", ""),
        })
    return write_csv(os.path.join(out_dir, "schools.csv"),
                     ["accountid", "accountname", "website", "cf_city", "cf_ward"], out)


def extract_leads(tables: dict, out_dir: str) -> int:
    leads = tables.get("vtiger_leaddetails", [])
    entity_idx = index_by(tables.get("vtiger_crmentity", []), "crmid")
    lcf_idx = index_by(tables.get("vtiger_leadscf", []), "leadid")
    out = []
    for r in leads:
        lid = r["leadid"]
        entity = entity_idx.get(lid, {})
        lcf = lcf_idx.get(lid, {})
        # Skip deleted leads
        if entity.get("deleted", "0") == "1":
            continue
        out.append({
            "leadid": lid,
            "firstname": r.get("firstname", ""),
            "lastname": r.get("lastname", ""),
            "email": r.get("email", ""),
            "secondaryemail": r.get("secondaryemail", ""),
            "mobile": r.get("mobile", ""),
            "phone": r.get("phone", ""),
            "website": r.get("website", ""),
            "company": r.get("company", ""),
            "leadsource": r.get("leadsource", ""),
            "leadstatus": r.get("leadstatus", ""),
            "converted": r.get("converted", "0"),
            "rating": r.get("rating", ""),
            "description": entity.get("description", ""),
            "smownerid": entity.get("smownerid", ""),
            # Custom fields
            "cf_city": lcf.get("cf_city", ""),
            "cf_school": lcf.get("cf_school", ""),
            "cf_major": lcf.get("cf_major", ""),
            "leads_campus": lcf.get("leads_campus", ""),
            "cf_kenh_quang_cao": lcf.get("cf_kenh_quang_cao", ""),
            "cf_tag": lcf.get("cf_tag", ""),
            "cf_segment": lcf.get("cf_segment", ""),
            "cf_nvfpt": lcf.get("cf_nvfpt", ""),
        })
    fieldnames = [
        "leadid", "firstname", "lastname", "email", "secondaryemail",
        "mobile", "phone", "website", "company", "leadsource", "leadstatus",
        "converted", "rating", "description", "smownerid",
        "cf_city", "cf_school", "cf_major", "leads_campus",
        "cf_kenh_quang_cao", "cf_tag", "cf_segment", "cf_nvfpt",
    ]
    return write_csv(os.path.join(out_dir, "leads.csv"), fieldnames, out)


def _parse_id_list(raw: str) -> list[int]:
    """Parse vTiger JSON array or comma-separated string of IDs."""
    if not raw:
        return []
    raw = raw.strip()
    if raw.startswith("["):
        try:
            return [int(x) for x in json.loads(raw) if str(x).strip()]
        except (json.JSONDecodeError, ValueError):
            return []
    try:
        return [int(x.strip()) for x in raw.split(",") if x.strip()]
    except ValueError:
        return []


def extract_contacts(tables: dict, out_dir: str) -> int:
    contacts = tables.get("vtiger_contactdetails", [])
    entity_idx = index_by(tables.get("vtiger_crmentity", []), "crmid")
    ccf_idx = index_by(tables.get("vtiger_contactscf", []), "contactid")
    csub_idx = index_by(tables.get("vtiger_contactsubdetails", []), "contactsubscriptionid")
    out = []
    for r in contacts:
        cid = r["contactid"]
        entity = entity_idx.get(cid, {})
        ccf = ccf_idx.get(cid, {})
        csub = csub_idx.get(cid, {})
        if entity.get("deleted", "0") == "1":
            continue
        out.append({
            "contactid": cid,
            "firstname": r.get("firstname", ""),
            "lastname": r.get("lastname", ""),
            "email": r.get("email", ""),
            "phone": r.get("phone", ""),
            "mobile": r.get("mobile", ""),
            "accountid": r.get("accountid", ""),
            "leadsource": csub.get("leadsource", ""),
            "cf_source_lead_id": ccf.get("cf_source_lead_id", ""),
            "cf_major": ccf.get("cf_major", ""),
        })
    fieldnames = [
        "contactid", "firstname", "lastname", "email", "phone", "mobile",
        "accountid", "leadsource", "cf_source_lead_id", "cf_major",
    ]
    return write_csv(os.path.join(out_dir, "contacts.csv"), fieldnames, out)


def extract_routing_config(tables: dict, out_dir: str) -> int:
    """Export vtiger_lead_sharing_config + vtiger_lead_sharing_school_config to CSV fixtures."""
    total = 0

    # Province-level routing rules (no school)
    rows = tables.get("vtiger_lead_sharing_config", [])
    out = []
    for r in rows:
        out.append({
            "campus": r.get("campus", ""),
            "city_ids": r.get("city_ids", ""),
            "staff_ids": r.get("staff_ids", ""),
            "is_active": r.get("is_active", "1"),
        })
    total += write_csv(
        os.path.join(out_dir, "routing_config.csv"),
        ["campus", "city_ids", "staff_ids", "is_active"],
        out,
    )

    # School-specific routing rules
    rows = tables.get("vtiger_lead_sharing_school_config", [])
    out = []
    for r in rows:
        out.append({
            "campus": r.get("campus", ""),
            "city_id": r.get("city_id", ""),
            "account_ids": r.get("account_ids", ""),
            "staff_ids": r.get("staff_ids", ""),
            "is_active": r.get("is_active", "1"),
        })
    total += write_csv(
        os.path.join(out_dir, "routing_school_config.csv"),
        ["campus", "city_id", "account_ids", "staff_ids", "is_active"],
        out,
    )
    return total


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

WANT_TABLES = {
    "vtiger_citys",
    "vtiger_wards",
    "vtiger_majors",
    "vtiger_leads_campus",
    "vtiger_account",
    "vtiger_accountscf",
    "vtiger_leaddetails",
    "vtiger_leadscf",
    "vtiger_crmentity",
    "vtiger_contactdetails",
    "vtiger_contactscf",
    "vtiger_contactsubdetails",
    "vtiger_lead_sharing_config",
    "vtiger_lead_sharing_school_config",
}

EXTRACTORS = [
    ("provinces", extract_provinces),
    ("wards", extract_wards),
    ("majors", extract_majors),
    ("branches", extract_branches),
    ("schools", extract_schools),
    ("leads", extract_leads),
    ("contacts", extract_contacts),
    ("routing_config", extract_routing_config),
]


def main():
    parser = argparse.ArgumentParser(description="vTiger SQL → CSV fixtures for vtiger_import.py")
    parser.add_argument("--sql", required=True, help="Path to the vTiger SQL dump")
    parser.add_argument("--out", default="crm/migration/fixtures", help="Output directory for CSV files")
    parser.add_argument("--only", help="Comma-separated subset: provinces,wards,majors,branches,schools,leads,contacts")
    args = parser.parse_args()

    only = set(args.only.split(",")) if args.only else None

    print(f"Parsing SQL: {args.sql}")
    print("(This may take a moment for large dumps...)")
    tables = load_tables(args.sql, WANT_TABLES)

    loaded = {t: len(rows) for t, rows in tables.items()}
    print("\nRows loaded:")
    for t, n in sorted(loaded.items()):
        print(f"  {t}: {n}")

    print(f"\nWriting CSV fixtures to: {args.out}")
    for name, fn in EXTRACTORS:
        if only and name not in only:
            continue
        count = fn(tables, args.out)
        print(f"  {name}.csv — {count} rows")

    print("\nDone. Run the import pipeline:")
    print(f"  bench --site crm.localhost execute crm.migration.vtiger_import.run \\")
    print(f"    --kwargs '{{\"step\": \"all\", \"fixtures_path\": \"{os.path.abspath(args.out)}\", \"dry_run\": false}}'")


if __name__ == "__main__":
    main()
