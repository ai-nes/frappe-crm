# vTiger → Frappe CRM — Schema Mapping (Complete)

**Nguồn:** `docs/crm-v8-test-trc_structure.sql` (structure-only dump)  
**Ngày:** 2026-05-30 (rev.3 — full audit, all tables)  
**Mục tiêu:** Sau khi migrate xong, Frappe CRM hoạt động thay thế hoàn toàn — không còn thuật ngữ hệ thống cũ trên UI.

---

## 1. Quy trình nghiệp vụ tổng quan

```
Hệ thống cũ                    Frappe CRM (sau migrate)
─────────────────────────────────────────────────────────────────
Leads                   →  CRM Lead            + custom fields
Contacts                →  Contact             + custom fields
Accounts (Trường THPT)  →  CRM Organization    + custom fields
Potentials (Hồ sơ)      →  CRM Deal            + custom fields
Tỉnh/Thành phố          →  CRM Province        (DocType mới — Phase 2)
Phường/Xã               →  CRM Ward            (DocType mới — Phase 2)
Ngành học               →  CRM Major           (DocType mới — Phase 2)
Chi nhánh               →  CRM Branch          (DocType mới — Phase 2)
Students                →  Enrollment Student  (DocType mới — Phase 2 ✓ implemented)
Lead Sharing Rules      →  Assignment Rules    (Phase 3 — deferred)
```

---

## 2. Quy tắc FK (từ SQL schema)

Tất cả `cf_*` custom fields trong `_scf` tables đều là **integer foreign keys**:

| Cột | SQL type | Trỏ đến |
|-----|----------|---------|
| `vtiger_leadscf.cf_city` | `int(19)` | `vtiger_citys.citysid` |
| `vtiger_leadscf.cf_school` | `int(19)` | `vtiger_account.accountid` |
| `vtiger_leadscf.cf_major` | `int(19)` | `vtiger_majors.majorsid` |
| `vtiger_leadscf.cf_student_contact_id` | `int(19)` | `vtiger_contactdetails.contactid` |
| `vtiger_accountscf.cf_city` | `int(19)` | `vtiger_citys.citysid` |
| `vtiger_accountscf.cf_ward` | `int(19)` | `vtiger_wards.wardsid` |
| `vtiger_contactscf.cf_source_lead_id` | `int(19)` | `vtiger_leaddetails.leadid` |
| `vtiger_contactscf.cf_major` | `int(19)` | `vtiger_majors.majorsid` |
| `vtiger_contactdetails.accountid` | `int(19)` | `vtiger_account.accountid` |
| `vtiger_potential.related_to` | `int(19)` | `vtiger_account.accountid` |
| `vtiger_potential.contact_id` | `int(19)` | `vtiger_contactdetails.contactid` |
| `vtiger_potentialscf.cf_major` | `int(19)` | `vtiger_majors.majorsid` |

**Cột varchar (NOT FK):**
- `vtiger_leadscf.leads_campus`: varchar(200) — lưu tên hiển thị trực tiếp
- `vtiger_leadscf.cf_kenh_quang_cao`: varchar(200) — lưu value trực tiếp
- `vtiger_leadscf.cf_nvfpt`: text — lưu value trực tiếp
- `vtiger_leadscf.cf_segment`: text — lưu comma-separated values
- `vtiger_leadscf.cf_tag`: text — lưu comma-separated values
- `vtiger_wards.city_id`: varchar(100) — lưu string identifier (KHÔNG phải int citysid)
- `vtiger_leaddetails.leadstatus`: varchar(200) — lưu string trực tiếp
- `vtiger_leaddetails.leadsource`: varchar(200) — lưu string trực tiếp

---

## 3. CRM Province ← vtiger_citys

| vTiger cột | Frappe field | Notes |
|------------|-------------|-------|
| `citysid` | `import_source_id` (Int, hidden) | trace only |
| `city_name` | `province_name` | reqd, unique, title field |
| `city_type` | `city_type` | Select — options từ vtiger_city_type |
| `city_number` | `city_number` | mã tỉnh — dùng làm idempotency key |
| `order_appearance` | *(bỏ)* | không cần UI |
| `description` | *(bỏ)* | |

**Picklist `vtiger_city_type`** → Set làm Select options trong field `city_type` của CRM Province DocType JSON.

---

## 4. CRM Ward ← vtiger_wards

| vTiger cột | Frappe field | Notes |
|------------|-------------|-------|
| `wardsid` | `import_source_id` (Int, hidden) | trace only |
| `ward_name` | `ward_name` | reqd, title field |
| `city_id` | `province` | Link CRM Province — city_id là varchar, resolve bằng tên/số |
| `ward_type` | `ward_type` | Select — options từ vtiger_ward_type |

**Picklist `vtiger_ward_type`** → Set làm Select options trong field `ward_type`.

**Lưu ý:** `city_id` là varchar, KHÔNG phải int → resolve bằng `province_name` hoặc `city_number`, không dùng int map.

---

## 5. CRM Major ← vtiger_majors

| vTiger cột | Frappe field | Notes |
|------------|-------------|-------|
| `majorsid` | `import_source_id` (Int, hidden) | trace only |
| `major_name` | `major_name` | reqd, title field |
| `major_code` | `major_code` | |
| `major_group` | `major_group` | Select — options từ vtiger_major_group |
| `is_active` | `is_active` | Check |
| `description` | *(bỏ)* | |

**Picklist `vtiger_major_group`** → Set làm Select options trong field `major_group`.

---

## 6. CRM Branch ← vtiger_leads_campus

| vTiger cột | Frappe field | Notes |
|------------|-------------|-------|
| `leads_campusid` | `import_source_id` (Int, hidden) | trace only |
| `leads_campus` | `branch_name` | reqd, title field |
| — | `branch_code` | manual: ha_noi / ho_chi_minh / da_nang / quy_nhon / can_tho |

**Seed 5 bản ghi:** Hà Nội, Hồ Chí Minh, Đà Nẵng, Quy Nhơn, Cần Thơ.

---

## 7. CRM Lead ← vtiger_leaddetails + vtiger_leadscf + vtiger_leadaddress + vtiger_leadsubdetails + vtiger_crmentity

### 7.1 Standard fields

| vTiger cột | Bảng | Frappe field | Transform |
|------------|------|-------------|-----------|
| `leadid` | `leaddetails` | `import_source_id` (Int, hidden) | lưu để build lead_map cho contact import |
| `firstname` | `leaddetails` | `first_name` | NULL → tách lastname hoặc 'N/A' |
| `lastname` | `leaddetails` | `last_name`, `lead_name` | |
| `email` | `leaddetails` | `email` | lower case |
| `secondaryemail` | `leaddetails` | `other_email` (custom) | |
| `leadsource` | `leaddetails` | `source` | lookup CRM Lead Source by string |
| `leadstatus` | `leaddetails` | `status` | lookup CRM Lead Status by string; fallback 'New' |
| `converted` | `leaddetails` | `converted` | 1→1 |
| `rating` | `leaddetails` | `conversion_potential` (custom Select) | string trực tiếp |
| `company` | `leaddetails` | `organization` (Data field) | text copy — trường học hiển thị tạm |
| `mobile` | `leadaddress` | `mobile_no` | normalize +84 |
| `phone` | `leadaddress` | `phone` | |
| `website` | `leadsubdetails` | `website` | cần JOIN leadsubdetails |
| `smownerid` | `crmentity` | `lead_owner` | resolve via users_map.csv |
| `description` | `crmentity` | FCRM Note | insert separately after lead |
| `createdtime` | `crmentity` | `creation` | set trực tiếp nếu Frappe cho phép |

### 7.2 Custom fields từ vtiger_leadscf

| vTiger cột | SQL type | Frappe field | Transform |
|------------|----------|-------------|-----------|
| `cf_city` | int FK | `province` (Link CRM Province) | `province_map[cf_city]` |
| `cf_school` | int FK | `high_school` (Link CRM Organization) | `school_map[cf_school]` |
| `cf_major` | int FK | `major` (Link CRM Major) | `major_map[cf_major]` |
| `leads_campus` | varchar | `branch` (Link CRM Branch) | lookup by `branch_name` |
| `cf_kenh_quang_cao` | varchar | `ad_channel` (Select) | string trực tiếp |
| `cf_segment` | text | `segments` (Small Text) | comma-sep text; store as-is |
| `cf_nvfpt` | text | `fpt_aspiration` (Select) | string trực tiếp |
| `cf_tag` | text | `tags` (Small Text) | comma-sep; hoặc Frappe Tags |
| `cf_student_contact_id` | int FK | `linked_contact` (Link Contact) | resolve sau khi contacts imported |

### 7.3 Fields hidden from layout (keep in DB)

`organization` (Data), `territory`, `industry`, `annual_revenue`, `no_of_employees`, `products`

---

## 8. CRM Organization ← vtiger_account + vtiger_accountscf

| vTiger cột | Bảng | Frappe field | Transform |
|------------|------|-------------|-----------|
| `accountid` | `account` | `import_source_id` (Int, hidden) | build school_map |
| `accountname` | `account` | `organization_name` | |
| `email1` | `account` | *(bỏ — Organization không có email field mặc định)* | |
| `phone` | `account` | *(bỏ)* | |
| `website` | `account` | `website` | |
| `cf_city` | `accountscf` | `province` (custom Link CRM Province) | `province_map[cf_city]` |
| `cf_ward` | `accountscf` | `ward` (custom Link CRM Ward) | `ward_map[cf_ward]` |

---

## 9. Contact ← vtiger_contactdetails + vtiger_contactscf + vtiger_contactsubdetails

| vTiger cột | Bảng | Frappe field | Transform |
|------------|------|-------------|-----------|
| `contactid` | `contactdetails` | `import_source_id` (Int, hidden) | trace only |
| `firstname` | `contactdetails` | `first_name` | NULL → tách lastname hoặc 'N/A' |
| `lastname` | `contactdetails` | `last_name` | |
| `email` | `contactdetails` | `email_id` | |
| `otheremail` | `contactdetails` | *(bỏ hoặc lưu secondary email)* | |
| `mobile` | `contactdetails` | `mobile_no` | normalize +84 |
| `phone` | `contactdetails` | `phone` | |
| `accountid` | `contactdetails` | `company_name` (hoặc custom Link CRM Organization) | `school_map[accountid]` |
| `leadsource` | `contactsubdetails` | `source` (custom Data) | string trực tiếp |
| `cf_source_lead_id` | `contactscf` | `source_lead` (custom Link CRM Lead) | `lead_map[cf_source_lead_id]` — cần lead import xong trước |
| `cf_major` | `contactscf` | `major` (custom Link CRM Major) | `major_map[cf_major]` |

---

## 10. CRM Deal ← vtiger_potential + vtiger_potentialscf

| vTiger cột | Bảng | Frappe field | Transform |
|------------|------|-------------|-----------|
| `potentialid` | `potential` | `import_source_id` (Int, hidden) | trace only |
| `potentialname` | `potential` | `lead_name` (deal title) | |
| `sales_stage` | `potential` | `status` | lookup CRM Deal Status by string |
| `amount` | `potential` | `deal_value` | |
| `closingdate` | `potential` | `closed_date` | |
| `probability` | `potential` | `probability` | |
| `leadsource` | `potential` | `source` | |
| `nextstep` | `potential` | `next_step` | |
| `related_to` | `potential` | `organization` | `school_map[related_to]` |
| `contact_id` | `potential` | contacts child table | `contact_frappe_name` |
| `description` | `potential` | FCRM Note | insert separately |
| `cf_major` | `potentialscf` | `major` (custom Link CRM Major) | `major_map[cf_major]` |

**Lưu ý:** Deals chỉ import nếu user xác nhận dùng Potentials trong vTiger tuyển sinh.

---

## 11. Picklists cần export để seed Select options

| Bảng vTiger | Cột value | Dùng cho | Frappe target |
|-------------|-----------|----------|---------------|
| `vtiger_leadsource` | `leadsource` | CRM Lead Source | CRM Lead Source (DocType) |
| `vtiger_leadstatus` | `leadstatus` | CRM Lead Status | CRM Lead Status (DocType) |
| `vtiger_leads_campus` | `leads_campus` | Chi nhánh | CRM Branch (DocType) |
| `vtiger_major_group` | `major_group` | Nhóm ngành | Select options trong CRM Major.major_group |
| `vtiger_city_type` | `city_type` | Loại tỉnh | Select options trong CRM Province.city_type |
| `vtiger_ward_type` | `ward_type` | Loại phường | Select options trong CRM Ward.ward_type |
| `vtiger_cf_kenh_quang_cao` | `cf_kenh_quang_cao` | Kênh quảng cáo | Select options trong CRM Lead.ad_channel |
| `vtiger_cf_nvfpt` | `cf_nvfpt` | Nguyện vọng FPT | Select options trong CRM Lead.fpt_aspiration |
| `vtiger_rating` | `rating` | Khả năng chuyển đổi | Select options trong CRM Lead.conversion_potential |
| `vtiger_cf_segment` | `cf_segment` | Segments | Select options trong CRM Lead.segments (nếu MultiSelect) |

---

## 12. Bảng bỏ qua (không cần migrate)

| Bảng | Lý do |
|------|-------|
| `com_vtiger_workflow_*` | Workflows hệ thống cũ — thiết lập lại trong Frappe |
| `vtiger_campaign*` | Marketing campaigns — không dùng trong CRM mới |
| `vtiger_lead_sharing_*` | Phase 3 — deferred; thiết lập lại bằng Frappe Assignment Rules |
| `vtiger_leadstage` | Khác leadstatus — không dùng |
| `vtiger_accountbillads`, `vtiger_accountshipads` | Địa chỉ hóa đơn/giao hàng — không áp dụng tuyển sinh |
| `vtiger_tmp_*` | Bảng tạm, không có data lâu dài |
| `vtiger_freetags`, `vtiger_freetagged_objects` | Tags cũ — dùng Frappe Tags thay |
| `vtiger_contpotentialrel` | Được handle qua CRM Deal contacts child table |
| `vtiger_convertleadmapping` | Frappe có built-in lead conversion |

---

## 13. Import order (strict)

```
1.  city_type picklist    → CRM Province.city_type options (seed vào DocType JSON)
2.  ward_type picklist    → CRM Ward.ward_type options (seed vào DocType JSON)
3.  major_group picklist  → CRM Major.major_group options (seed vào DocType JSON)
4.  ad_channel picklist   → CRM Lead.ad_channel options (seed vào Custom Field)
5.  fpt_aspiration picklist → CRM Lead.fpt_aspiration options (Custom Field)
6.  conversion_potential picklist → CRM Lead.conversion_potential options (Custom Field)
7.  provinces.csv         → CRM Province            (build province_map)
8.  wards.csv             → CRM Ward                (needs province_map; build ward_map)
9.  majors.csv            → CRM Major               (build major_map)
10. schools.csv           → CRM Organization        (needs province_map + ward_map; build school_map)
11. lead_sources.csv      → CRM Lead Source
12. lead_statuses.csv     → CRM Lead Status
13. branches.csv          → CRM Branch              (5 records)
14. leads.csv             → CRM Lead                (needs all maps; build lead_map)
15. contacts.csv          → Contact                 (needs lead_map + major_map + school_map)
16. deals.csv             → CRM Deal                (optional — nếu user confirm)
```

---

## 14. UI Sidebar mapping (Phase 1)

| Sidebar Frappe | Label VI | Label EN source |
|----------------|---------|-----------------|
| Leads | Khách hàng tiềm năng | Leads |
| Deals | Hồ sơ quan tâm | Deals |
| Contacts | Liên hệ | Contacts |
| Organizations | **Trường THPT** | Organizations |
| *(future)* Students | Sinh viên | — |

**Không có từ nào liên quan đến hệ thống cũ trong UI.**
