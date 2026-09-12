# Ma trận scope Group/Team cho LeadList và StudentList

**Ngày áp dụng:** 2026-09-08  
**Nguồn scope:** `CRM Staff` → `CRM Team Membership` → `CRM Team` → `CRM Team Group`

## 1. Ma trận mục tiêu

| Đối tượng đăng nhập | LeadList | StudentList | Quyền ghi |
|---|---|---|---|
| Lead Sale | Toàn bộ Lead | Toàn bộ Student | Theo quyền Lead Sale hiện hành |
| Director/CEO/Admin/System Manager | Toàn bộ Lead | Toàn bộ Student | Theo quyền hệ thống |
| Team Lead (Sale/CTV) | Lead thuộc Team mình dẫn và pool của Team | Student đã convert và assigned trong Team; Student chưa assign bị loại bởi invariant của API | Theo quyền ghi của bản thân/Team |
| Sale member | Lead được giao cho mình; được xem Lead trong Team/pool để phục vụ phân công | Student đã convert và assigned trong Team/pool scope | Chỉ bản ghi được phép ghi |
| CTV Sale member | Lead được giao cho mình; được xem Lead trong Team/pool | Student đã convert và assigned trong Team/pool scope | Theo quyền CTV hiện hành |

Nếu một nhân sự đồng thời có nhiều membership hoặc vai trò, scope là hợp của các
phạm vi hợp lệ. Scope được tính từ session, không tin vào `ownerId` do client gửi.

## 2. API đã áp dụng

### LeadList

`crm.api.director_leads.get_director_leads` dùng full-board reader cho Lead Sale
và lấy điều kiện từ `get_student_list_read_condition(doctype="CRM Lead")` cho
Sale/Team Lead/CTV, sau đó áp dụng danh sách ID được phép vào `total`, `totalAll`,
KPI trạng thái, campaign stats và dữ liệu phân trang.

Lead Sale được nhận diện là full-list profile và đọc trực tiếp toàn bộ Lead;
Sale/Team Lead mới đi qua explicit ID scope Group/Team/pool. `frappe.get_all`
chỉ được dùng cho full-list profile hoặc sau khi backend đã tạo explicit ID scope;
đường đọc detail tương thích cũ không thay đổi trong phạm vi này.

### StudentList

`crm.api.director_students.get_director_students` tiếp tục lấy scope từ Lead
projection trước khi truy vấn `CRM Student` đối với Sale/CTV. Lead Sale và
Director/CEO dùng unrestricted reader để xem toàn bộ Student. Bộ lọc Student vẫn
chỉ hiển thị bản ghi đã convert, đã có owner và đã được assign; đây là invariant
của màn hình Student, không phải lỗ hổng scope. Kết quả được nhóm theo
`student_stage` theo thứ tự `New` → `Attempting` → `Connected` → `Qualified` /
`Disqualified`. Trong mỗi chiều cũ nhất/mới nhất, kết quả được ưu tiên theo
`modified` trước, sau đó mới dùng thứ tự `student_stage` và tiêu chí phụ.

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

- Các API phân công, update, delete vẫn tự kiểm tra quyền ghi và revision.
- Không mở rộng quyền detail Student/Lead chỉ vì bản ghi xuất hiện trong list.
- Không sửa các thay đổi đang có sẵn trong repository `dashboard-crm`.
