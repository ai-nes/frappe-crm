# Ma trận scope Group/Team cho LeadList và StudentList

**Ngày áp dụng:** 2026-09-08  
**Nguồn scope:** `CRM Staff` → `CRM Team Membership` → `CRM Team` → `CRM Team Group`

## 1. Ma trận mục tiêu

| Đối tượng đăng nhập | LeadList | StudentList | Quyền ghi |
|---|---|---|---|
| Admin/System Manager/Admissions Director | Toàn bộ Lead | Toàn bộ Student | Theo quyền hệ thống |
| Group Lead | Các Lead thuộc mọi Team trong Group mình dẫn; pool Team; Lead chưa phân công theo tỉnh của Group | Student đã convert và assigned trong các Team thuộc Group; Student chưa assign bị loại bởi invariant của API | Chỉ theo rule ghi hiện hành; không mở rộng chỉ vì được xem list |
| Team Lead | Lead thuộc Team mình dẫn và pool của Team | Student đã convert và assigned trong Team; Student chưa assign bị loại bởi invariant của API | Theo quyền ghi của bản thân/Team |
| Sale member | Lead được giao cho mình; được xem Lead trong Team/pool để phục vụ phân công | Student đã convert và assigned trong Team/pool scope | Chỉ bản ghi được phép ghi |
| CTV Sale | Bản ghi được giao cho mình | Bản ghi được giao cho mình | Theo quyền CTV hiện hành |

Nếu một nhân sự đồng thời có nhiều membership hoặc vai trò, scope là hợp của các
phạm vi hợp lệ. Scope được tính từ session, không tin vào `ownerId` do client gửi.

## 2. API đã áp dụng

### LeadList

`crm.api.director_leads.get_director_leads` giờ lấy điều kiện từ
`get_student_list_read_condition(doctype="CRM Lead")`, sau đó áp dụng danh sách
ID được phép vào `total`, `totalAll`, KPI trạng thái, campaign stats và dữ liệu
phân trang.

Vì vậy Lead Sale không còn đọc toàn bộ bảng Lead khi gọi list. `frappe.get_all`
chỉ được dùng sau khi backend đã tạo explicit ID scope; đường đọc detail tương
thích cũ không thay đổi trong phạm vi này.

### StudentList

`crm.api.director_students.get_director_students` tiếp tục lấy scope từ Lead
projection trước khi truy vấn `CRM Student`. Do đó Group Lead nhận cùng phạm vi
Group/Team/pool với LeadList. Bộ lọc Student vẫn chỉ hiển thị bản ghi đã convert,
đã có owner và đã được assign; đây là invariant của màn hình Student, không phải
lỗ hổng scope.

## 3. Quy tắc dữ liệu

- Team phải hoạt động và thuộc Group hoạt động.
- Bản ghi đã phân công được nhận diện qua `owner_staff`, `assigned_to` và
  `owning_team`.
- Pool Team là bản ghi chưa có `owner_staff` và `assigned_to`, nhưng có
  `owning_team` đúng Team.
- Lead chưa có Team vẫn vào scope Group Lead nếu `province` thuộc Group đang dẫn.
- API không cho client tự chọn Group/Team để vượt quyền; mọi scope đều suy ra từ
  user hiện tại.

## 4. Không thay đổi

- Các API phân công, update, delete vẫn tự kiểm tra quyền ghi và revision.
- Không mở rộng quyền detail Student/Lead chỉ vì bản ghi xuất hiện trong list.
- Không sửa các thay đổi đang có sẵn trong repository `dashboard-crm`.
