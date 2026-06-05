# Enrollment Terminology — Source of Truth

**Date:** 2026-05-30
**Version:** 1.0 (aligned with vTiger SQL schema audit)
**Scope:** Phase 1 display labels only — no DocType/route/fieldname changes.

---

## A. Module Names (Navigation)

| Key | EN source (Frappe) | VI display | vTiger module |
|-----|--------------------|------------|---------------|
| nav.leads | Leads | Khách hàng tiềm năng | Leads |
| nav.deals | Deals | Hồ sơ quan tâm | Contact pipeline / Potentials |
| nav.contacts | Contacts | Liên hệ | Contacts |
| nav.organizations | Organizations | Trường THPT | Accounts (vtiger_account) |
| nav.territory | Territory | Chi nhánh | leads_campus |
| nav.dashboard | Dashboard | Bảng tin | |

## B. Actions

| Key | EN | VI |
|-----|----|----|
| action.create_lead | Create Lead | Tạo lead tuyển sinh |
| action.convert | Convert to Deal | Chuyển thành hồ sơ quan tâm |
| action.convert_short | Convert | Chuyển đổi |
| action.create_deal | Create Deal | Tạo hồ sơ quan tâm |

## C. Field Labels — CRM Lead

| fieldname | EN label | VI label | vTiger source |
|-----------|----------|----------|---------------|
| first_name | First Name | Họ | |
| last_name | Last Name | Tên | |
| lead_name | Full Name | Họ và tên | |
| mobile_no | Mobile No. | Di động | |
| email | Email | Email | |
| lead_owner | Lead Owner | Giao cho | smownerid |
| source | Source | Nguồn | leadsource |
| status | Status | Tình trạng | leadstatus |
| industry | Industry | Ngành quan tâm | cf_major (Phase 2) |
| organization | Organization | Trường THPT | cf_school → account |
| territory | Territory | Chi nhánh | leads_campus |
| converted | Converted | Đã chuyển hồ sơ | converted |
| lost_reason | Lost Reason | Lý do không theo | |
| lost_notes | Lost Notes | Ghi chú | |
| annual_revenue | Annual Revenue | (ẩn Phase 2) | |
| no_of_employees | No. of Employees | (ẩn Phase 2) | |

## D. Field Labels — CRM Deal

| fieldname | EN label | VI label |
|-----------|----------|----------|
| deal_owner | Deal Owner | Người phụ trách |
| status | Status | Trạng thái hồ sơ |
| lead | Lead | Khách hàng tiềm năng |
| lead_name | Lead Name | Họ và tên |
| organization | Organization | Trường THPT |
| territory | Territory | Chi nhánh |
| probability | Probability | Xác suất nhập học |
| expected_closure_date | Expected Closure Date | Ngày dự kiến nhập học |
| closed_date | Closed Date | Ngày hoàn tất |
| lost_reason | Lost Reason | Lý do không theo |
| lost_notes | Lost Notes | Ghi chú |

## E. Roles (Display Only — DB Unchanged)

| Role DB value | VI display |
|---------------|------------|
| Sales Manager | Quản lý tuyển sinh |
| Sales User | Nhân viên tuyển sinh |

## F. vTiger → Frappe Module Mapping

```
vTiger Leads     → CRM Lead       (UI: Khách hàng tiềm năng)
vTiger Contacts  → Contact        (UI: Liên hệ)
                 → CRM Deal       (UI: Hồ sơ quan tâm)
vTiger Accounts  → CRM Organization (UI: Trường THPT)
vTiger leads_campus → CRM Territory (UI: Chi nhánh)
vTiger Students  → Enrollment Student DocType (Phase 2 — implemented)
vTiger Potentials → CRM Deal
```

## G. Decisions Made

- [x] Leads = Khách hàng tiềm năng
- [x] Deals = Hồ sơ quan tâm
- [x] Organizations = Trường THPT (per SQL vtiger_account + cf_school mapping)
- [x] Territory = Chi nhánh (per leads_campus field)
- [x] Status names: DB giữ EN, dịch qua vi.po (Option B)
- [x] Students module: Enrollment Student DocType implemented (Phase 2)
- [x] Custom fields added to CRM Lead, CRM Organization, Contact (Phase 2)

## H. Implemented (Phase 2)

- Custom fields: province, ward, major, school, branch, ad_channel (vtiger_leadscf) — added via `add_enrollment_custom_fields` patch
- Enrollment Student DocType created — whitelisted `create_from_contact` API for CRM UI integration
- Side panel layout updated: hidden legacy sales fields, added enrollment section
- Lead Sources & Lead Statuses picklists — seeded via `seed_enrollment_picklists` patch

## I. Deferred (Phase 3)

- Students sidebar link + UI listing for Enrollment Student
- Lead Sharing Rules → Assignment Rules (Phase 3)
