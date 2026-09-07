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

| Đối tượng | Ý nghĩa |
| --- | --- |
| `CRM Lead` | Một lần tiếp nhận/form submission trước khi Sale hoàn tất xử lý. Đây là record được đưa vào batch. |
| `CRM Student` | Hồ sơ canonical sau khi Lead được handoff thành công. Một Student có thể có nhiều Lead. |
| `CRM Contact` | Không phải target chính của batch hiện tại. Không tạo Contact riêng trong bước phân công. |

Quan hệ nghiệp vụ:

```text
1 CRM Student ← nhiều CRM Lead
```

Không được chặn Lead mới chỉ vì trùng phone/email. Việc phân loại trùng được thực hiện
ở bước processing.

### 2.2. Hai nhóm status cần phân biệt

`CRM Lead.lead_status` là lifecycle CRM hiện có, còn `processing_status` là workflow
server-managed của intake/assignment. FE không tự ghi hai field này.

| Field | Giá trị | Ý nghĩa |
| --- | --- | --- |
| `processing_status` | `NEW` | Lead mới nhận, chưa chạy xử lý. |
|  | `PROCESSING` | BE đang kiểm tra và phân loại. |
|  | `PROCESSED` | Đã qua điều kiện dữ liệu, chưa chắc đã có Sale. |
|  | `ASSIGNED` | Ownership Team/Sale đã ghi thành công. |
|  | `CLOSED` | Lead invalid/duplicate hoặc đã handoff thành công. |
| `resolution` | `PENDING` | Chưa phân loại. |
|  | `MATCHED` | Khớp một Student đã có. |
|  | `CREATED` | Chưa có Student phù hợp; sẽ tạo Student ở bước handoff. |
|  | `DUPLICATE` | Trùng Lead/Student không thể tự quyết định duy nhất. |
|  | `INVALID` | Thiếu dữ liệu bắt buộc. |
|  | `SPAM` / `FAILED` | Kết quả kết thúc do xử lý thủ công hoặc lỗi nghiệp vụ. |

Các field server-managed liên quan:

```text
processing_status
resolution
resolution_reason
matched_student
converted_student
converted_at
conversion_status
owner_staff
owning_team
owning_pool
ownership_revision
```

## 3. Điều kiện dữ liệu

### 3.1. Điều kiện để Lead được xử lý

Ba field bắt buộc là:

```text
CCCD          → CRM Lead.id_number
Trường THPT   → CRM Lead.high_school
Ngành quan tâm → CRM Lead.major
```

Phone, email và tỉnh/thành là dữ liệu liên hệ/routing. Chúng không thay thế ba điều
kiện trên.

Nếu thiếu hoặc CCCD không hợp lệ, BE trả kết quả `CLOSED / INVALID` và không phân công.

### 3.2. Field bắt buộc khi import vào batch

API import batch yêu cầu các cột sau:

| Field API | Nhãn FE | Bắt buộc |
| --- | --- | --- |
| `student_name` | Họ và tên | Có |
| `phone` | Số điện thoại | Có |
| `id_number` | CCCD | Có |
| `province` | Tỉnh/Thành phố | Có |
| `high_school` | Trường THPT | Có |
| `major` | Ngành quan tâm | Có |
| `source` | Nguồn Lead | Có |
| `email` | Email | Không |
| `branch` | Cơ sở | Không nếu tài khoản chỉ có một cơ sở hoặc có cơ sở mặc định |

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
  │
  ├─ thiếu CCCD / THPT / ngành
  │    └─ CLOSED / INVALID
  │
  └─ đủ dữ liệu
       ├─ Student đã có → MATCHED
       └─ chưa có → CREATED
              ↓
          PROCESSED
              ↓ bấm phân công batch
          Team/Sale ownership thành công
              ↓
          ASSIGNED
              ↓ Sale handoff
          Student New + Lead CLOSED
```

`CREATED` ở bước `PROCESSED` có nghĩa là “sẵn sàng tạo Student khi handoff”, chưa phải
Student đã được insert.

### 4.1. Quy tắc MATCHED/DUPLICATE

BE xử lý theo thứ tự:

1. Chuẩn hóa CCCD và tìm `CRM Student` theo CCCD.
2. Nếu không có CCCD match, fallback theo `phone + email + province`.
3. Một Student duy nhất → `MATCHED`, lưu `CRM Lead.matched_student`.
4. Nhiều Student phù hợp → `DUPLICATE / CLOSED`.
5. Không có Student nhưng có Lead trùng → `DUPLICATE / CLOSED`.
6. Không có match → `CREATED / PROCESSED`.

Không được FE tự quyết định `MATCHED` hay `CREATED`.

## 5. Batch assignment contract

### 5.1. Batch status

| Status batch | Ý nghĩa |
| --- | --- |
| `draft` | Batch mới tạo, chưa xem trước/chạy. |
| `ready` | Đã xem trước; các item đã có context phân công. |
| `running` | Đang xử lý một lần. Không cho chạy đồng thời. |
| `completed` | Tất cả item đã xử lý thành công hoặc bỏ qua hợp lệ. |
| `completed_with_errors` | Có item deferred, manual review hoặc failed. |
| `cancelled` | Không chạy tiếp. |

### 5.2. Batch item status

| Status item | Ý nghĩa |
| --- | --- |
| `pending` | Chờ chạy. |
| `assigned` | Đã chọn Sale và ghi ownership. |
| `deferred` | Chưa phân công được, ví dụ chưa có policy/capacity phù hợp. |
| `manual_review` | Thiếu dữ liệu hoặc cần người quản trị xử lý. |
| `failed` | Lỗi xử lý item. |
| `skipped` | Lead đã converted hoặc đã có owner từ trước. |

Batch không chạy bằng worker nền. Người dùng bấm một lần để chạy batch; chạy lại chỉ
dành cho item `deferred`, `manual_review` hoặc `failed`.

### 5.3. API chính

Tất cả API trả dữ liệu trong `response.message` theo chuẩn Frappe.

| Method | HTTP | Mục đích |
| --- | --- | --- |
| `crm.api.lead_assignment_batch.import_leads_to_assignment_batch` | POST | Tạo Lead mới từ rows/CSV và đưa vào batch `draft`; chưa phân công. |
| `crm.api.lead_assignment_batch.create_lead_assignment_batch` | POST | Tạo batch từ các Lead đã có bằng `lead_ids`; chưa phân công. |
| `crm.api.lead_assignment_batch.preview_lead_assignment_batch` | POST | Kiểm tra điều kiện và routing context, chuyển batch sang `ready`. |
| `crm.api.lead_assignment_batch.run_lead_assignment_batch` | POST | Xử lý Lead và phân công một lần. |
| `crm.api.lead_assignment_batch.run_unassigned_lead_assignment` | POST | Quét toàn bộ Lead chưa có `owner_staff`/`assigned_to`, tạo bản ghi chạy nội bộ và phân công một lần. Không lọc theo `source`. |
| `crm.api.lead_assignment_batch.retry_lead_assignment_batch` | POST | Chạy lại item lỗi/deferred/manual review. |
| `crm.api.lead_assignment_batch.get_lead_assignment_batch` | GET | Lấy chi tiết một batch và item. |
| `crm.api.lead_assignment_batch.list_lead_assignment_batches` | GET | Lấy lịch sử các batch. |
| `crm.api.lead_assignment_batch.get_lead_assignment_batch_options` | GET | Lấy option pool nội bộ nếu cần kiểm tra quyền; không cần hiển thị cho người dùng thường. |

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
  "batch": { "name": "...", "status": "completed", "summary": {} },
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

1. Lead `NEW` được BE đưa sang `PROCESSING`.
2. Lead không hợp lệ thành `CLOSED / INVALID`, item thành `manual_review`.
3. Lead hợp lệ thành `PROCESSED`.
4. BE tìm Team theo tỉnh của Lead rồi ghi Team/Sale ownership.
5. Ghi ownership thành công mới đổi Lead thành `ASSIGNED`, item thành `assigned`.
6. Không có Team hoặc Sale/CTV đủ điều kiện thì Lead giữ `PROCESSED`, item thành
   `manual_review` hoặc `deferred`.

FE không hiển thị nút “chạy ngầm”, không polling worker và không tự đổi status.

## 6. Thứ tự phân công Lead batch

Luồng Lead batch mới dùng một route đơn giản, không yêu cầu người vận hành setup
Pool/Policy/Zone:

1. Chuẩn hóa `CRM Lead.province`.
2. Tìm Group đang hoạt động có đúng tỉnh.
3. Lấy các Team Sales đang hoạt động thuộc Group.
4. Chỉ giữ Team có trưởng nhóm tổ chức và có Sale/CTV Sale đang hoạt động.
5. Chọn Sale/CTV có tải thấp nhất và còn giới hạn nhận nếu có.

Trường THPT vẫn là field nghiệp vụ bắt buộc của Lead và phục vụ bước chuyển sang
Student, nhưng không còn là khóa để người vận hành mapping Team trong batch.

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

`pool`, `zone` và policy cũ vẫn có thể xuất hiện trong contract để tương thích lịch
sử, nhưng không phải dữ liệu setup của Lead batch mới. Mã
`policyVersion = province-capacity-v1` chỉ dùng để truy vết kết quả.

## 7. Handoff sau khi Sale xử lý

Đây không phải bước của nút phân công batch. Khi Sale hoàn tất xử lý Lead, gọi:

```text
POST crm.api.lead_processing.handoff_lead
```

Điều kiện:

```text
processing_status = ASSIGNED
resolution = MATCHED hoặc CREATED
```

Kết quả thành công:

- `MATCHED`: dùng `matched_student` để enrich Student hiện có.
- `CREATED`: tạo Student mới từ snapshot Lead.
- CRM Student được đưa về stage `New`.
- Lead được `CLOSED`.
- `converted_student` và `conversion_status = Converted` được ghi bởi BE.

Handoff yêu cầu `idempotency_key` và `expected_lifecycle_revision` để chống xử lý lặp
hoặc ghi đè dữ liệu mới.

## 8. Contract UI cho FE

### FE phải làm

- Hiển thị một nút “Phân công Lead” để gọi `run_unassigned_lead_assignment`.
- Hiển thị trạng thái đang chạy, không có Lead cần xử lý và kết quả từng Lead.
- Cho xem lịch sử các lần chạy nội bộ; mỗi lần chạy có status và summary.
- Hiển thị kết quả từng item: đã phân công, chờ xử lý, cần bổ sung, lỗi.
- Sau khi run, dùng `batch.name` để gọi lại `get_lead_assignment_batch` nếu cần tải chi tiết.
- Cho retry riêng các item `deferred`, `manual_review`, `failed`.
- Giữ nguyên error code để support/debug, nhưng hiển thị thông báo tiếng Việt.

### FE không được làm

- Không tự ghi `processing_status`, `resolution`, `owner_staff`, `owning_team`.
- Không tự tính hoặc tự chọn Sale/Team/Zone.
- Không tạo CRM Student ở bước nhập Lead hoặc phân công.
- Không gọi worker; nút trên dashboard là điểm kích hoạt duy nhất.
- Không dùng `lead_status` để thay thế `processing_status`.
- Không hardcode dữ liệu tỉnh, trường, ngành, nguồn.

## 9. Error mapping tối thiểu

| Error code | Cách hiển thị đề xuất |
| --- | --- |
| `IDENTIFIER_GATE_FAILED` | Lead thiếu CCCD, trường THPT hoặc ngành quan tâm. |
| `INVALID_ID_NUMBER` | CCCD phải gồm 9 hoặc 12 chữ số. |
| `INVALID_LOOKUP` / `INVALID_PROVINCE` / `INVALID_HIGH_SCHOOL` | Chọn lại dữ liệu từ danh sách Frappe. |
| `MISSING_CAMPUS` | Bổ sung cơ sở cho Lead hoặc cấu hình cơ sở mặc định. |
| `TEAM_NOT_FOUND_FOR_PROVINCE` | Chưa có Team hoạt động phụ trách tỉnh. |
| `NO_ELIGIBLE_RECIPIENT` | Chưa có Sale/CTV hoạt động hoặc còn chỗ nhận. |
| `TEAM_NOT_READY` | Team thiếu Group/tỉnh/trưởng nhóm/nhân sự cần thiết. |
| `STALE_OWNERSHIP_REVISION` | Dữ liệu đã thay đổi; tải lại batch rồi retry. |
| `FORBIDDEN` / `OUT_OF_SCOPE` | Tài khoản không có quyền hoặc ngoài phạm vi Team/cơ sở. |

## 10. Trạng thái triển khai hiện tại

Đã kiểm tra local:

- Migration thành công, 190 CRM JSON hợp lệ.
- Processing contract: 9 tests pass.
- Lead mapping/catalog: 16 tests pass.
- Assignment batch: 10 tests pass.
- Routing: 10 tests pass.
- Student routing: 6 tests pass.
- Ruff, format và `git diff --check` pass.

- API `run_unassigned_lead_assignment` đã có; dashboard gọi API này từ nút
  “Phân công Lead”.
- Card tạo/import batch đã bỏ khỏi luồng chính; các API explicit batch vẫn giữ để đọc
  lịch sử và tương thích dữ liệu cũ.
- Seed local `crm.demo.seed_unassigned_leads.execute` tạo 10 Lead đủ dữ liệu routing,
  chưa có người phụ trách.

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
