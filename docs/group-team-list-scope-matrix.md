# Ma trận scope Group/Team cho LeadList và StudentList

**Ngày áp dụng:** 2026-09-08  
**Nguồn scope:** `CRM Staff` → `CRM Team Membership` → `CRM Team` → `CRM Team Group`

## 1. Ma trận mục tiêu

| Đối tượng đăng nhập | LeadList | StudentList | Quyền ghi |
|---|---|---|---|
| Lead Sale | Toàn bộ Lead | Toàn bộ Student | Theo quyền Lead Sale hiện hành |
| Director/CEO/Admin/System Manager | Toàn bộ Lead | Toàn bộ Student | Theo quyền hệ thống |
| Team Lead (Sale) | Lead thuộc Team mình dẫn và pool của Team | Student đã convert và assigned trong Team; Student chưa assign bị loại bởi invariant của API | Theo quyền ghi của bản thân/Team |
| Sale member | Lead được giao cho mình | Student được giao cho mình | Chỉ bản ghi được phép ghi |
| Team Lead/Group Lead (Sale) | Lead thuộc Team/Group mình dẫn và pool tương ứng | Student thuộc Team/Group mình dẫn và đã assigned | Chỉ bản ghi được phép ghi |
| CTV Sale member | Chỉ Lead được phân công cho mình | Chỉ Student đã convert và được phân công cho mình | Theo quyền CTV hiện hành |

Nếu một nhân sự đồng thời có nhiều membership hoặc vai trò, scope là hợp của các
phạm vi hợp lệ. Scope được tính từ session, không tin vào `ownerId` do client gửi.

## 2. API đã áp dụng

### LeadList

`crm.api.director_leads.get_director_leads` dùng full-board reader cho Lead Sale
và lấy điều kiện từ `get_student_list_read_condition(doctype="CRM Lead")` cho
Sale/Team Lead/CTV, sau đó áp dụng danh sách ID được phép vào `total`, `totalAll`,
KPI trạng thái, campaign stats và dữ liệu phân trang.

Lead Sale được nhận diện là full-list profile và đọc trực tiếp toàn bộ Lead;
Sale/Team Lead mới đi qua explicit ID scope Group/Team/pool. Với Sale,
scope mở rộng chỉ đến từ `team_lead_staff` và `group_lead_staff`; Sale member
thường và CTV chỉ dùng điều kiện `owner_staff` của chính mình. `frappe.get_all`
chỉ được dùng cho full-list profile hoặc sau khi backend đã tạo explicit ID scope;
đường đọc detail và update dùng cùng scope với danh sách; quyền delete vẫn giữ
kiểm tra ownership riêng.

Các command tạo/cập nhật `CRM Admission Application` của Lead Sale dùng quyền
full-case tương ứng với Student mà Lead Sale được xem. Đây là quyền trên
application service, không mở rộng quyền sửa trực tiếp các trường Student.

### StudentList

`crm.api.director_students.get_director_students` tiếp tục lấy scope từ Lead
projection trước khi truy vấn `CRM Student` đối với Sale/CTV. Sale member/CTV
chỉ xem owner; Sale Team Lead/Group Lead xem scope Team/Group của mình. Lead
Sale và Director/CEO dùng unrestricted reader để xem toàn bộ Student. Bộ lọc Student vẫn
chỉ hiển thị bản ghi đã convert, đã có owner và đã được assign; đây là invariant
của màn hình Student, không phải lỗ hổng scope. Kết quả được nhóm theo
`student_stage` theo thứ tự `New` → `Attempting` → `Connected` → `Qualified` /
`Disqualified`. Trong mỗi chiều cũ nhất/mới nhất, kết quả được ưu tiên theo
`modified` trước, sau đó mới dùng thứ tự `student_stage` và tiêu chí phụ.
Các bản ghi liên kết của Student Detail gồm Application, Admission Profile và
Student Document cũng kế thừa full-case read của Lead Sale; vì vậy hồ sơ vừa tạo
không bị ẩn bởi query scope Team/Pool.

## 3. Quy tắc dữ liệu

- Team phải hoạt động và thuộc Group hoạt động.
- Bản ghi đã phân công được nhận diện qua `owner_staff`, `assigned_to` và
  `owning_team`.
- Pool Team là bản ghi chưa có `owner_staff` và `assigned_to`, nhưng có
  `owning_team` đúng Team.
- Lead chưa có Team vẫn vào scope Team Lead/Group Lead nếu `province` thuộc Group
  đang dẫn; các profile full-list không cần điều kiện này.
- API không cho client tự chọn Group/Team để vượt quyền; mọi scope đều suy ra từ
  user hiện tại.

## 4. Không thay đổi

- Các API phân công, update, delete vẫn tự kiểm tra quyền ghi, ownership và revision.
- Detail Student/Lead và update dùng cùng read scope; delete vẫn có ownership
  check riêng.
- Không sửa các thay đổi đang có sẵn trong repository `dashboard-crm`.
