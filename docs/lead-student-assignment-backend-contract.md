---
type: spec
date: 2026-09-08
status: local-backend-and-dashboard-contract
owner: frappe-crm
audience: dashboard-crm FE
---

# Contract BE phân công Lead tự động

## 1. Mục tiêu

Tài liệu này là contract hiện tại giữa `frappe-crm` và `dashboard-crm` cho luồng chính:

```text
Nguồn khác đổ Lead vào CRM
  → người vận hành bấm “Phân công Lead”
  → BE quét Lead chưa có người phụ trách
  → xử lý dữ liệu
  → chọn Team/Sale theo cấu hình Frappe
  → cập nhật ownership
```

BE là nguồn sự thật cho dữ liệu, status, permission và thuật toán. FE chỉ hiển thị,
gọi API và hiển thị kết quả; không tự tính Team, Zone, Sale hoặc capacity. Batch vẫn
được BE tạo nội bộ để lưu lịch sử, không phải bước setup của người dùng.

## 2. Mô hình dữ liệu chuẩn

### 2.1. CRM Lead và CRM Student

| Đối tượng     | Ý nghĩa                                                                                            |
| ------------- | -------------------------------------------------------------------------------------------------- |
| `CRM Lead`    | Một lần tiếp nhận/form submission trước khi Sale hoàn tất xử lý. Đây là record được đưa vào batch. |
| `CRM Student` | Hồ sơ canonical sau khi có thao tác chuyển đổi Lead riêng. Một Student có thể có nhiều Lead.            |
| `CRM Contact` | Không phải target chính của batch hiện tại. Không tạo Contact riêng trong bước phân công.          |

Quan hệ nghiệp vụ:

```text
1 CRM Student ← nhiều CRM Lead
```

Không được chặn Lead mới chỉ vì trùng phone/email. Việc phân loại trùng được thực hiện
ở bước processing.

Trang danh sách học sinh chỉ đọc `CRM Student` thật đã được tạo hoặc enrich qua thao tác chuyển đổi riêng
(có `source_lead` và `converted_at`) và phải có `owner_staff`, `assigned_to` cùng
`owning_team` hợp lệ. Lead `ASSIGNED`
chưa handoff chỉ xuất hiện ở màn hình Lead/cần xử lý, không được chiếu như Student.

Lead Sale dùng cùng màn hình Student hiện có như Sale nhưng ở phạm vi tổng quát:
xem được Student đã chuyển đổi và đã có người phụ trách trong các Team thuộc Group
mình quản lý, đồng thời nhìn thấy Sale/CTV Sale đang phụ trách. Phạm vi này không
mở rộng sang Group khác và không tạo thêm endpoint riêng.

Đối với `CRM Lead`, tài khoản `Lead Sale` được phép cập nhật các trường nghiệp vụ
được mở qua `crm.api.lead.update_lead` trên toàn bộ bảng intake. `Sale` và `CTV Sale`
chỉ được cập nhật Lead đang giao cho chính mình; các field server-managed và các
thay đổi ownership/lifecycle/processing vẫn phải đi qua command tương ứng.

Read-model chi tiết Lead trả `province` và `ward` dưới dạng nhãn hiển thị. Form tạo/cập
nhật gửi mã Link tương ứng; danh sách xã/phường được BE lọc theo tỉnh đã chọn.

Lead nguồn được trả dưới dạng metadata `sourceLead`, `processingStatus` và `resolution`;
Student dùng `student_stage` làm trường stage duy nhất.

### 2.2. API tạo nhanh Student kèm Lead nguồn

Form tạo nhanh dùng endpoint:

```text
POST /api/method/crm.api.student_school.create_student_with_lead
```

Endpoint tạo một `CRM Lead` nguồn và một `CRM Student` thật trong cùng giao dịch,
hoàn tất handoff ở stage `New`, sau đó liên kết hai bản ghi qua `CRM Student.source_lead`,
`CRM Lead.student` và metadata conversion (`converted_student`, `converted_at`).
Đây không phải endpoint tạo Lead cũ `create_student`; route cũ vẫn được giữ để tương
thích ngược và vẫn tạo `CRM Lead`.

Payload tối thiểu:

```json
{
  "student_name": "Nguyễn Văn An",
  "phone": "0901234567",
  "id_number": "012345678901",
  "province": "PROVINCE-001",
  "ward": "WARD-001",
  "high_school": "HIGH-SCHOOL-001",
  "admission_year": "2026",
  "source": "SOURCE-001",
  "assigned_to": "CRM-STAFF-001"
}
```

`student_name`, `phone`, `province`, `source` và `assigned_to` là bắt buộc. `id_number`,
`ward`, `high_school` và `admission_year` được chuẩn hóa theo các Link master tương ứng;
các field hồ sơ cơ bản khác có thể gửi thêm theo allowlist của endpoint. `student_stage`
không nhận từ client và Student mới luôn bắt đầu ở `New`.

Response trả về cả `student` và `lead`, cùng `source_lead`/`student` để FE cập nhật
cache hoặc điều hướng sang bản ghi vừa tạo.

### 2.3. Hai nhóm status cần phân biệt

`CRM Lead.processing_status` và `resolution` là workflow server-managed của
intake/assignment. FE không tự ghi hai field này.

| Field               | Giá trị           | Ý nghĩa                                                          |
| ------------------- | ----------------- | ---------------------------------------------------------------- |
| `processing_status` | `NEW`             | Lead mới nhận, chưa chạy xử lý.                                  |
|                     | `PROCESSING`      | BE đang kiểm tra và phân loại.                                   |
|                     | `PROCESSED`       | Đã qua điều kiện dữ liệu, chưa chắc đã có Sale.                  |
|                     | `ASSIGNED`        | Ownership Team/Sale đã ghi thành công.                           |
|                     | `CLOSED`          | Lead invalid/duplicate hoặc đã handoff thành công.               |
| `resolution`        | `PENDING`         | Chưa có kết quả; giữ nguyên trong toàn bộ bước xử lý và phân công. |
|                     | `MATCHED`         | Khớp một Student đã có.                                          |
|                     | `CREATED`         | Kết quả của thao tác chuyển đổi riêng: tạo Student mới.          |
|                     | `DUPLICATE`       | Kết quả chuyển đổi khi không xác định được một Student duy nhất. |
|                     | `INVALID`         | Kết quả legacy của luồng cũ; gate thiếu dữ liệu mới dùng PENDING. |
|                     | `SPAM` / `FAILED` | Kết quả kết thúc do xử lý thủ công hoặc lỗi nghiệp vụ.           |

Các field server-managed liên quan:

```text
processing_status
resolution
resolution_reason
matched_student
converted_student
converted_at
owner_staff
owning_team
owning_pool
ownership_revision
```

## 3. Điều kiện dữ liệu

### 3.1. Điều kiện để Lead được xử lý

Bốn điều kiện bắt buộc để Lead được xử lý là:

```text
Số điện thoại → CRM Lead.phone
Tỉnh/thành    → CRM Lead.province
Trường THPT   → CRM Lead.high_school
Ngành quan tâm → CRM Lead.major
```

CCCD và email không phải gate của luồng xử lý/phân công hiện tại.

Nếu thiếu một trong bốn điều kiện, BE đóng Lead với `CLOSED / PENDING` và không phân công.

### 3.2. Field bắt buộc khi import vào batch

API import batch yêu cầu các cột sau:

| Field API      | Nhãn FE        | Bắt buộc                                                    |
| -------------- | -------------- | ----------------------------------------------------------- |
| `student_name` | Họ và tên      | Có                                                          |
| `phone`        | Số điện thoại  | Có                                                          |
| `id_number`    | CCCD           | Không                                                       |
| `province`     | Tỉnh/Thành phố | Có                                                          |
| `high_school`  | Trường THPT    | Có                                                          |
| `major`        | Ngành quan tâm | Có                                                          |
| `source`       | Nguồn Lead     | Có                                                          |
| `email`        | Email          | Không                                                       |
| `branch`       | Cơ sở          | Không nếu tài khoản chỉ có một cơ sở hoặc có cơ sở mặc định |

FE không hardcode danh sách tỉnh, trường, ngành và nguồn.

### 3.3. Catalog từ Frappe

Gọi:

```text
GET crm.api.lead_assignment_batch.get_lead_assignment_catalogs
```

Response gồm:

```json
{
  "provinces": [{"id": "...", "label": "...", "code": "..."}],
  "sources": [{"id": "...", "label": "...", "code": null}],
  "majors": [{"id": "...", "label": "...", "code": "..."}],
  "highSchools": [{"id": "...", "label": "...", "code": "..."}]
}
```

Khi truyền `province`, `highSchools` chỉ trả trường thuộc tỉnh đó:

```text
GET crm.api.lead_assignment_batch.get_lead_assignment_catalogs?province=<province>
```

Nguồn có trạng thái `Retired` không được trả về. Nếu tài khoản phụ trách nhiều cơ sở,
FE phải cho chọn `branch`; nếu không xác định được cơ sở, BE trả lỗi validation.

## 4. Luồng xử lý chuẩn

```text
NEW / PENDING
  │ bấm “Xử lý Lead” (process_new_leads)
  │
  ├─ thiếu số điện thoại / tỉnh / THPT / ngành
  │    └─ CLOSED / PENDING
  │
  └─ đủ 4 điều kiện
       └─ PROCESSED / PENDING
              ↓ bấm “Phân công Lead”
          Team/Sale ownership thành công
              ↓
          ASSIGNED / PENDING
```

Xử lý và phân công chỉ cập nhật trạng thái, Team và Sale/CTV phụ trách. Kết quả vẫn là
`PENDING` (“Chưa có kết quả”) và không tạo hoặc cập nhật `CRM Student`.
Việc chuyển đổi Lead thành Student là thao tác riêng, sau khi người dùng chủ động thực hiện.

Lead `CLOSED` do thiếu dữ liệu hoặc lỗi routing không được phân công. Nếu một Lead đã có
`converted_student` từ dữ liệu cũ, BE không tạo thêm Student.

### 4.1. Quy tắc phát hiện trùng và giữ Lead đại diện

CCCD không phải dữ liệu bắt buộc của Lead mới. BE chỉ dùng CCCD khi bản ghi có sẵn;
quy tắc chính vẫn hoạt động với bốn gate đầu vào. Các trường hợp được kiểm tra:

1. `phone + province + high_school + major` giống nhau: trùng hồ sơ nghiệp vụ.
2. `phone + email + province` giống nhau: fallback tương thích khi thông tin trường/ngành
   giữa hai lần gửi không đồng nhất.
3. `id_number` giống nhau: tín hiệu định danh mạnh khi Lead có CCCD.
4. Một Lead khớp nhiều Student: trùng đích không xác định, không được tự chọn Student.
5. Chỉ trùng số điện thoại: không tự đóng vì có thể là số dùng chung trong gia đình.

Với các trường hợp 1–3, BE gom các Lead hợp lệ thành một nhóm và chọn đúng một Lead
đại diện theo thứ tự: Lead đã `ASSIGNED`, Lead đã `PROCESSED`, sau đó Lead có thời điểm
tạo sớm nhất. Lead đại diện tiếp tục `PROCESSED / PENDING`; các bản sao còn lại là
`CLOSED / PENDING`, kèm `resolution_reason` trỏ tới Lead được giữ lại. Vì vậy nhóm N
Lead trùng luôn giữ lại 1 Lead và đóng N−1 bản sao.

Trường hợp 4 vẫn `CLOSED / PENDING` để người vận hành xác định đúng Student đích.
Trường hợp không trùng và không có Student phù hợp là `PROCESSED / PENDING`; kết quả
`MATCHED`/`CREATED` chỉ xuất hiện ở thao tác chuyển đổi Student riêng.

Student đã ở trạng thái đóng/lost không tự tạo bản ghi mới nếu Lead có thể chứng minh
đúng cùng một Student bằng CCCD hoặc bộ fallback `phone + email + province`; khi đó
resolution vẫn là `MATCHED` và Lead được enrich bản ghi canonical đó. Nếu không đủ
định danh để chứng minh, BE không được đoán và phải để kết quả cần rà soát thay vì
tự tạo bản ghi trùng.

Không được FE tự quyết định `MATCHED` hay `CREATED`.

## 5. Batch assignment contract

### 5.1. Batch status

| Status batch            | Ý nghĩa                                             |
| ----------------------- | --------------------------------------------------- |
| `draft`                 | Batch mới tạo, chưa xem trước/chạy.                 |
| `ready`                 | Đã xem trước; các item đã có context phân công.     |
| `running`               | Đang xử lý một lần. Không cho chạy đồng thời.       |
| `completed`             | Tất cả item đã xử lý thành công hoặc bỏ qua hợp lệ. |
| `completed_with_errors` | Có item deferred, manual review hoặc failed.        |
| `cancelled`             | Không chạy tiếp.                                    |

### 5.2. Batch item status

| Status item     | Ý nghĩa                                                     |
| --------------- | ----------------------------------------------------------- |
| `pending`       | Chờ chạy.                                                   |
| `assigned`      | Đã chọn Sale và ghi ownership.                              |
| `deferred`      | Chưa phân công được, ví dụ chưa có policy/capacity phù hợp. |
| `manual_review` | Thiếu dữ liệu hoặc cần người quản trị xử lý.                |
| `failed`        | Lỗi xử lý item.                                             |
| `skipped`       | Lead đã converted hoặc đã có owner từ trước.                |

Batch không chạy bằng worker nền. Người dùng bấm một lần để chạy batch; chạy lại chỉ
dành cho item `deferred`, `manual_review` hoặc `failed`.

### 5.3. API chính

Tất cả API trả dữ liệu trong `response.message` theo chuẩn Frappe.

| Method                                                            | HTTP | Mục đích                                                                                                  |
| ----------------------------------------------------------------- | ---- | --------------------------------------------------------------------------------------------------------- |
| `crm.api.lead_assignment_batch.import_leads_to_assignment_batch`  | POST | Tạo Lead mới từ rows/CSV và đưa vào batch `draft`; chưa phân công.                                        |
| `crm.api.lead_assignment_batch.create_lead_assignment_batch`      | POST | Tạo batch từ các Lead đã có bằng `lead_ids`; chưa phân công.                                              |
| `crm.api.lead_assignment_batch.preview_lead_assignment_batch`     | POST | Kiểm tra điều kiện và routing context, chuyển batch sang `ready`.                                         |
| `crm.api.lead_assignment_batch.run_lead_assignment_batch`         | POST | Phân công Lead đã `PROCESSED`, chỉ ghi Team và Sale/CTV phụ trách.                                         |
| `crm.api.lead_assignment_batch.run_unassigned_lead_assignment`    | POST | Quét Lead đã `PROCESSED` mà chưa có owner rồi phân công. Không tạo Student và không lọc theo `source`.   |
| `crm.api.lead_processing.process_new_leads`                       | POST | Quét toàn bộ Lead `NEW` (tuỳ chọn `admission_year`, `limit`) và chạy điều kiện dữ liệu cho từng Lead.     |
| `crm.api.lead_assignment_batch.retry_lead_assignment_batch`       | POST | Chạy lại item lỗi/deferred/manual review.                                                                 |
| `crm.api.lead_assignment_batch.get_lead_assignment_batch`         | GET  | Lấy chi tiết một batch và item.                                                                           |
| `crm.api.lead_assignment_batch.get_lead_assignment_workflow`      | GET  | Lấy workflow và metrics từ trạng thái Lead hiện tại hoặc batch được chọn.                                  |
| `crm.api.lead_assignment_batch.list_lead_assignment_batches`      | GET  | Lấy lịch sử các batch.                                                                                    |
| `crm.api.lead_assignment_batch.list_lead_assignment_history_items` | GET  | Lấy danh sách hồ sơ theo trạng thái, gồm cả Lead `CLOSED` cần người vận hành kiểm tra; hỗ trợ lọc `lead_ids`. |
| `crm.api.lead_assignment_batch.get_lead_assignment_batch_options` | GET  | Lấy option pool nội bộ nếu cần kiểm tra quyền; không cần hiển thị cho người dùng thường.                  |

`get_lead_assignment_workflow` nhận tùy chọn `batch_name`. Nếu không truyền, API
tổng hợp trạng thái Lead hiện tại với item của các batch trong phạm vi quyền, khử
trùng theo Lead để không làm mất các hồ sơ đã rời scope sau khi được phân công. Nếu
truyền `batch_name`, API trả projection của đúng batch đó để xem lịch sử. Response có
`hasRun`, `hasData`, `summary` (tổng số `assigned`, `manualReview`, `pending` và các
trạng thái khác), `pendingCount`, `steps` và `connections`; các giá trị được tính ở
backend từ DB. Khi `pendingCount = 0`, nút phân công Lead trên giao diện phải bị vô
hiệu hóa.

`list_lead_assignment_history_items` tổng hợp item từ các batch và các Lead đang
`CLOSED` trong DB. Các Lead `CLOSED` được trả về với `status = manual_review`, không
có `batchId`, để người vận hành vẫn nhìn thấy đúng số hồ sơ cần xử lý dù chúng không
còn nằm trong một batch audit. Payload có thể truyền `lead_ids` (chuỗi phân tách bằng
dấu phẩy hoặc mảng) để chỉ trả về một tập Lead cụ thể và mở trực tiếp hàng đợi đó trên
giao diện.

### 5.4. Import batch

Payload tối thiểu:

```json
{
  "batch_name": "Đợt THPT Nguyễn Huệ tháng 9",
  "rows": [
    {
      "student_name": "Nguyễn Văn A",
      "phone": "0900000000",
      "id_number": "012345678901",
      "province": "Ho Chi Minh City",
      "high_school": "THPT Nguyễn Huệ",
      "major": "Công nghệ thông tin",
      "source": "Website",
      "email": "a@example.com"
    }
  ],
  "description": "Đợt Lead từ form THPT Nguyễn Huệ"
}
```

Hoặc truyền `csv_content`. Header CSV được chấp nhận bằng tiếng Việt hoặc field API;
CCCD có thể dùng `CCCD`, `Số căn cước` hoặc `id_number`.

Import chỉ tạo Lead `NEW / PENDING` và item `pending`. Không gọi routing trong bước
import.

### 5.4.1. Import nhanh trong dialog Tạo Lead nhanh

Dashboard `/lead-sale/leads` có luồng import file riêng, tạo trực tiếp `CRM Lead`
và không tạo Assignment Batch.

```text
POST crm.api.lead_mapping.inspect_lead_import  (multipart {file})
  → đọc header/sample, suy luận mapping, không insert
POST crm.api.lead_mapping.preview_lead_import  (multipart {file, column_mapping, campaign_code?})
  → map theo sourceIndex, validate/resolve lookup, không insert
POST crm.api.lead_mapping.import_leads         (multipart {file, column_mapping, campaign_code, import_mode=quick_create})
  → server đọc lại file gốc, tạo từng CRM Lead hợp lệ, savepoint theo dòng
```

Ba endpoint yêu cầu đăng nhập và quyền tạo `CRM Lead`; inspect không phải guest
endpoint vì response chứa dữ liệu thô từ file. `campaign_code` ở inspect/preview là
tùy chọn và được đọc từ multipart form field; ở import `quick_create`, đây là context
bắt buộc. Backend resolve code thành `CRM Campaign.name`, kiểm tra quyền đọc Campaign
và chỉ chấp nhận status chuẩn hóa `ACTIVE` hoặc `CLOSED`. Các lỗi context dùng mã
`CAMPAIGN_REQUIRED`, `INVALID_CAMPAIGN_CODE`, `CAMPAIGN_PERMISSION_DENIED` và
`CAMPAIGN_STATUS_NOT_ALLOWED`.

Preview không trả field server-managed `campaign` hoặc row-level `campaign_code` trong
`rows[].fields`. Campaign cấp request được áp dụng cho mọi Lead hợp lệ và không thể
bị ghi đè bởi dữ liệu trong file. FE lấy toàn bộ campaign người dùng có thể xem,
không dùng `lead_only`, sau đó chỉ hiển thị `ACTIVE` và `CLOSED`; campaign chưa có
Lead vẫn được chọn.

File `.csv` UTF-8 hoặc `.xlsx` worksheet đầu tiên được hỗ trợ, tối đa 5 MB, 1.000
dòng dữ liệu không rỗng và 100 cột. Inspect dùng dòng không rỗng đầu tiên làm header,
trả tối đa 10 dòng sample; số dòng là số dòng vật lý trong file. Giá trị sample được
serialize thành chuỗi JSON-safe hoặc `null` nếu ô rỗng. Contract v1 chưa tự nhận diện
title row và chưa cho chọn worksheet; title-row detection/multi-sheet selection được
để dành cho phiên bản sau.

Response gồm `fieldCatalog`, `headers`, `sampleRows` và `requiredFields`:

- `fieldCatalog`: nguồn sự thật từ backend, mỗi item có `{key, label, required,
  valueType}`. Frontend không tự sao chép allowlist này.
- `headers`: một item cho mỗi cột, có `{sourceIndex, label, inferredField, enabled}`;
  `sourceIndex` là khóa ổn định kể cả khi nhãn cột bị trùng.
- `sampleRows`: `{row, values}` với `row` là số dòng vật lý và `values` theo đúng thứ
  tự cột nguồn.
- `requiredFields`: nguồn sự thật cho các target bắt buộc của quick import.

Mapped preview/quick commit nhận `column_mapping` là JSON array theo source index:

```json
[
  {"sourceIndex": 0, "targetField": "student_name", "enabled": true},
  {"sourceIndex": 1, "targetField": null, "enabled": false}
]
```

Các cột bắt buộc của quick import là `student_name`, `phone`, `province`,
`high_school` và `source`; `assigned_to` để trống sẽ giữ Lead chưa phân công. Backend
từ chối mapping không an toàn bằng các mã `INVALID_COLUMN_MAPPING`,
`MAPPING_TARGET_REQUIRED`, `UNKNOWN_FIELD`, `SERVER_MANAGED_FIELD`,
`DUPLICATE_SOURCE_INDEX`, `DUPLICATE_TARGET_FIELD`, `INVALID_SOURCE_INDEX` và
`MISSING_REQUIRED_MAPPING`. `processing_status`, `campaign`, identifiers và các field
server-managed không phải target; quick import giữ mặc định server `NEW/PENDING`.
Preview không tạo dữ liệu; commit luôn parse lại file gốc và giữ savepoint độc lập theo
từng dòng.

`import_mode` khác `quick_create` giữ nguyên contract legacy, bao gồm caller
`student-school-update`, và không bắt buộc `campaign_code`.

### 5.4.2. Thứ tự rollout

Triển khai backend contract và test trước để `inspect_lead_import`, mapped preview,
allowlist, giới hạn file và commit re-parse ổn định. Sau khi backend sẵn sàng, dashboard
mới bật wizard mapping/live preview và gửi multipart file gốc kèm `column_mapping`.
Các plan duplicate-review tiếp theo chỉ được tiêu thụ row shape đã preview, không thay
đổi boundary v1 hoặc khôi phục việc tin rows đã normalize từ browser.

### 5.5. Preview và run

#### Luồng chính trên dashboard

FE gọi một API duy nhất khi người dùng bấm nút:

```text
POST crm.api.lead_assignment_batch.run_unassigned_lead_assignment
```

BE sẽ bỏ qua Lead đã có người phụ trách hoặc đã Converted, không quan tâm Lead đến từ
form, import hay hệ thống nào. Kết quả trả về có cùng cấu trúc batch/item hiện tại;
`batch` là bản ghi audit nội bộ để FE hiển thị lịch sử. Nếu không có việc cần làm,
BE trả `status = "no_work"`, `batch = null` và `items = []`.

Response khi có Lead cần xử lý có thêm:

```json
{
  "status": "completed",
  "scanned": 10,
  "batch": {"name": "...", "status": "completed", "summary": {}},
  "items": []
}
```

`scanned` là số Lead được quét trong lần bấm. FE không cần cho người dùng nhập tên
batch, chọn hàng chờ, chọn Team hoặc import CSV.

Các API explicit batch dưới đây vẫn được giữ để tương thích lịch sử và công cụ nội bộ:

```text
import/create batch
  → preview batch
  → hiển thị số Lead hợp lệ / cần bổ sung
  → run batch
  → refresh batch detail
```

`run` cũng có thể nhận batch `draft`, nhưng UI nên preview trước để người dùng thấy
ảnh hưởng.

Khi chạy:

1. Lead còn ở `NEW` hoặc `PROCESSING` không được batch xử lý hộ: item thành
   `manual_review` với error code `NOT_PROCESSED`. Bước xử lý là hành động riêng
   (`process_new_leads`, nút “Xử lý Lead”).
2. Lead đã `CLOSED` cũng thành `manual_review`.
3. Chỉ Lead `PROCESSED / PENDING` chưa có owner mới được phân công.
4. BE tìm Team theo tỉnh của Lead rồi ghi Team/Sale ownership.
5. Ghi ownership thành công đổi Lead thành `ASSIGNED`.
6. Item thành `assigned` sau khi ownership được ghi thành công; kết quả Lead vẫn `PENDING`.
7. Không có Team hoặc Sale/CTV đủ điều kiện thì Lead giữ `PROCESSED`, item thành
   `manual_review` hoặc `deferred`.

Mỗi item thành công phải được ghi bền vững là `assigned` cùng Team, Sale, lý do,
`activeLoad`, giới hạn nhận và `executionId` trước khi trả response. Field Int
`capacity_limit` và `remaining_capacity` không được ghi `NULL`; dùng `0` trong audit
cho trường hợp không giới hạn, còn API có thể serialize thành `null` để FE hiển thị
“không giới hạn”. Summary batch
được tính lại từ các item đã lưu; không được trả `assigned_count = 0` hoặc item
`pending` khi Lead tương ứng đã ở `ASSIGNED`.

FE không hiển thị nút “chạy ngầm”, không polling worker và không tự đổi status.

## 6. Thứ tự phân công Lead batch

Luồng Lead batch mới dùng một route đơn giản, không yêu cầu người vận hành setup
Pool/Policy/Zone:

1. Chuẩn hóa `CRM Lead.province`.
2. Tìm Group đang hoạt động có đúng tỉnh.
3. Lấy các Team Sales đang hoạt động thuộc Group.
4. Chỉ giữ Team có trưởng nhóm tổ chức và có Sale/CTV Sale đang hoạt động.
5. Chọn Sale/CTV có tải thấp nhất và còn giới hạn nhận nếu có.

Trường THPT và ngành quan tâm là field nghiệp vụ bắt buộc để xử lý Lead. Chúng không
phải là khóa để người vận hành mapping Team trong batch.

Các kết quả routing được trả ở item:

```text
province
team
ownerStaff
activeLoad
capacityLimit
remainingCapacity
policyVersion
routingRequest
reason
```

FE chỉ hiển thị các giá trị BE trả về. Không tính lại phần trăm tải hoặc tự chọn người.

Tải hiện tại của một Sale/CTV là số Lead chưa `CLOSED`, chưa có
`resolution = CREATED` và chưa có `converted_student` mà người đó đang sở hữu
(`owner_staff` hoặc `assigned_to`).

`pool`, `zone` và policy cũ vẫn có thể xuất hiện trong contract để tương thích lịch
sử, nhưng không phải dữ liệu setup của Lead batch mới. Mã
`policyVersion = province-capacity-v1` chỉ dùng để truy vết kết quả.

## 7. Chuyển đổi Lead thành Student (luồng riêng)

Đây không phải bước backend tự gọi sau khi chọn owner. API được giữ cho thao tác chuyển
đổi riêng hoặc các luồng nội bộ cần handoff:

```text
POST crm.api.lead_processing.handoff_lead
```

Điều kiện tối thiểu:

```text
processing_status = ASSIGNED
resolution = MATCHED hoặc CREATED
```

Kết quả thành công:

- `MATCHED`: dùng `matched_student` để enrich Student hiện có.
- `CREATED`: tạo Student mới từ snapshot Lead.
- Handoff chỉ được phép khi Lead có `owner_staff` và `assigned_to` trùng nhau; Staff
  và User phụ trách phải đang hoạt động.
- Student sau khi tạo/enrich bắt buộc phải có `assigned_to`; nếu không, toàn bộ handoff
  rollback với lỗi `OWNER_REQUIRED`.
- Student sau khi tạo/enrich cũng phải có `owner_staff` trùng `assigned_to` và
  `owning_team` đang hoạt động.
- CRM Student được đưa về stage `New`.
- Lead được `CLOSED`.
- `converted_student` và `resolution = CREATED` được ghi bởi BE.

Handoff yêu cầu `idempotency_key` và `expected_lifecycle_revision` để chống xử lý lặp
hoặc ghi đè dữ liệu mới.

Các endpoint conversion cũ cũng phải đi qua cùng điều kiện: Lead mới phải ở
`ASSIGNED` với resolution `MATCHED` hoặc `CREATED` và có ownership hợp lệ. Nếu chưa
đạt status, BE trả `LEAD_NOT_ASSIGNED`; nếu thiếu người phụ trách, BE trả
`OWNER_REQUIRED` và không insert Student.

## 8. Contract UI cho FE

### FE phải làm

- Hiển thị nút “Xử lý Lead” để gọi `process_new_leads` khi còn Lead `NEW`
  (`meta.pendingNew` của `get_director_leads`), và chỉ đổi sang nút “Phân công Lead”
  gọi `run_unassigned_lead_assignment` khi không còn Lead `NEW`.
- Dùng đúng một tên “Phân công Lead” cho hành động phân công trên mọi màn hình.
- Hiển thị trạng thái đang chạy, không có Lead cần xử lý và kết quả từng Lead.
- Cho xem lịch sử các lần chạy nội bộ; mỗi lần chạy có status và summary.
- Hiển thị kết quả từng item: đã phân công, chờ xử lý, cần bổ sung, lỗi.
- Sau khi run, dùng `batch.name` để gọi lại `get_lead_assignment_batch` nếu cần tải chi tiết.
- Cho retry riêng các item `deferred`, `manual_review`, `failed`.
- Giữ nguyên error code để support/debug, nhưng hiển thị thông báo tiếng Việt.

### FE không được làm

- Không tự ghi `processing_status`, `resolution`, `owner_staff`, `owning_team`.
- Không tự tính hoặc tự chọn Sale/Team/Zone.
- Không tạo CRM Student ở bước nhập Lead, xử lý hoặc phân công. FE chỉ gọi API conversion
  khi người dùng chủ động chuyển đổi.
- Không gọi worker; nút trên dashboard là điểm kích hoạt duy nhất.
- Không tự ghi `processing_status` hoặc `resolution`.
- Không hardcode dữ liệu tỉnh, trường, ngành, nguồn.

## 9. Error mapping tối thiểu

| Error code                                                    | Cách hiển thị đề xuất                                   |
| ------------------------------------------------------------- | ------------------------------------------------------- |
| `IDENTIFIER_GATE_FAILED`                                      | Lead thiếu số điện thoại, tỉnh, trường THPT hoặc ngành quan tâm. |
| `INVALID_ID_NUMBER`                                           | CCCD phải gồm 9 hoặc 12 chữ số.                         |
| `INVALID_LOOKUP` / `INVALID_PROVINCE` / `INVALID_HIGH_SCHOOL` | Chọn lại dữ liệu từ danh sách Frappe.                   |
| `MISSING_CAMPUS`                                              | Bổ sung cơ sở cho Lead hoặc cấu hình cơ sở mặc định.    |
| `TEAM_NOT_FOUND_FOR_PROVINCE`                                 | Chưa có Team hoạt động phụ trách tỉnh.                  |
| `NO_ELIGIBLE_RECIPIENT`                                       | Chưa có Sale/CTV hoạt động hoặc còn chỗ nhận.           |
| `TEAM_NOT_READY`                                              | Team thiếu Group/tỉnh/trưởng nhóm/nhân sự cần thiết.    |
| `STALE_OWNERSHIP_REVISION`                                    | Dữ liệu đã thay đổi; tải lại batch rồi retry.           |
| `LEAD_NOT_ASSIGNED`                                           | Lead chưa được phân công nên chưa thể tạo Student.      |
| `OWNER_REQUIRED`                                              | Lead/Student chưa có người phụ trách hợp lệ.            |
| `FORBIDDEN` / `OUT_OF_SCOPE`                                  | Tài khoản không có quyền hoặc ngoài phạm vi Team/cơ sở. |

## 10. Trạng thái triển khai hiện tại

Đã kiểm tra local:

- Migration thành công, 190 CRM JSON hợp lệ.
- Processing contract: 9 tests pass.
- Lead mapping/catalog: 16 tests pass.
- Assignment batch: 11 tests pass.
- Routing: 10 tests pass.
- Student routing: 6 tests pass.
- `git diff --check` pass. Ruff chưa khả dụng trong môi trường chuẩn; focused backend
  suite còn các lỗi integration baseline do môi trường/fixture, không phải lỗi mapping
  contract mới.

- API `run_unassigned_lead_assignment` đã có; dashboard gọi API này từ nút
  “Phân công Lead”.
- Card tạo/import batch đã bỏ khỏi luồng chính; các API explicit batch vẫn giữ để đọc
  lịch sử và tương thích dữ liệu cũ.
- Seed local `task seed-assignment-conversion` tạo Lead để kiểm tra luồng; bấm “Xử lý Lead”
  rồi “Phân công Lead” chỉ ghi trạng thái và owner, không tạo Student.

## References

- `crm/api/lead_assignment_batch.py`
- `crm/api/lead_processing.py`
- `crm/api/lead_mapping.py`
- `crm/fcrm/lead_processing.py`
- `crm/fcrm/lead_routing.py`
- `crm/fcrm/student_routing.py`
- `crm/fcrm/doctype/crm_lead/crm_lead.json`
- `crm/fcrm/doctype/crm_lead_assignment_batch/crm_lead_assignment_batch.json`
- `crm/fcrm/doctype/crm_lead_assignment_batch_item/crm_lead_assignment_batch_item.json`
