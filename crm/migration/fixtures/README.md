# Migration Fixtures

CSV and JSON files for the vTiger → Frappe CRM data migration.

## Files required before running import

| File | SQL to export from vTiger | Required columns |
|------|--------------------------|-----------------|
| `picklists.json` | See phase-01 §1.2 | city_type, ward_type, major_group, ad_channel, fpt_aspiration, conversion_potential, segments |
| `provinces.csv` | `SELECT citysid, city_name, city_type, city_number FROM vtiger_citys` | citysid, city_name, city_number |
| `wards.csv` | `SELECT wardsid, ward_name, city_id, ward_type FROM vtiger_wards` | wardsid, ward_name, city_id (varchar) |
| `majors.csv` | `SELECT majorsid, major_name, major_code, major_group, is_active FROM vtiger_majors` | majorsid, major_name, major_code |
| `branches.csv` | `SELECT leads_campusid, leads_campus FROM vtiger_leads_campus WHERE presence=1` | leads_campusid, leads_campus |
| `schools.csv` | See phase-01 §1.3 | accountid, accountname, cf_city, cf_ward |
| `lead_sources.csv` | `SELECT leadsource FROM vtiger_leadsource WHERE presence=1 ORDER BY sortorderid` | leadsource |
| `lead_statuses.csv` | `SELECT leadstatus, color FROM vtiger_leadstatus WHERE presence=1 ORDER BY sortorderid` | leadstatus, color |
| `users_map.csv` | `SELECT id, user_name, email FROM vtiger_users WHERE status='Active'` | id, email |
| `leads.csv` | See phase-06 §6.4 | leadid, firstname, lastname, email, mobile, ... |
| `contacts.csv` | See phase-06 §6.6 | contactid, firstname, lastname, email, mobile, ... |
| `deals.csv` | See phase-06 §6.8 (optional) | potentialid, potentialname, ... |

## id_maps/ (auto-generated, git-ignored)

Built during import. Do not commit. Delete and re-run if data changes.

- `province_map.json` — `{citysid: "CRM Province name"}`
- `ward_map.json` — `{wardsid: "CRM Ward name"}`
- `major_map.json` — `{majorsid: "CRM Major name"}`
- `school_map.json` — `{accountid: "CRM Organization name"}`
- `lead_map.json` — `{leadid: "CRM Lead name"}`
- `users_map.json` — `{smownerid: "user@email.com"}`
