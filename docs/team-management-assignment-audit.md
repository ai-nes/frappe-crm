# Audit Group, Team và phân công Lead

**Ngày rà soát:** 2026-09-08  
**Mục tiêu:** người không chuyên kỹ thuật có thể setup một lần trên
`dashboard-crm`, sau đó tạo đợt Lead và bấm phân công.

## 1. Mô hình nghiệp vụ chuẩn

```text
Admin/System Manager
  └── Group (một tỉnh)
        ├── một Trưởng Group
        └── nhiều Team
              ├── một Trưởng nhóm tổ chức của từng Team
              └── nhiều thành viên: Lead Sale, Sale, CTV Sale
```

- Admin hoặc Lead Sale được chọn một Trưởng Group cho từng Group.
- Admin hoặc Lead Sale được quyết định Trưởng nhóm tổ chức riêng cho từng Team.
- Trưởng nhóm quản lý thành viên của Team mình.
- Mỗi tỉnh có một Group hoạt động.
- Một Group có thể có nhiều Team.
- Một Team có nhiều Sale/CTV; không bắt buộc chỉ một Lead Sale.
- `Lead Sale` là vai trò quản lý/nghiệp vụ, không phải người nhận Lead tự động.
- Sale và CTV Sale mới là nhóm ứng viên nhận Lead.
- Trường THPT thuộc tỉnh nào được lấy từ dữ liệu Frappe; không cần gắn từng
  trường vào Team trong luồng phân công mới.

## 2. Setup tối thiểu trên dashboard

Người vận hành chỉ cần làm bốn việc:

1. Tạo hoặc chọn Group và gắn một tỉnh.
2. Chọn Trưởng Group cho Group.
3. Tạo Team bên trong Group.
4. Chọn Trưởng nhóm cho từng Team và thêm các thành viên Sale/CTV.

Team được coi là sẵn sàng khi:

- Team đang hoạt động.
- Group đang hoạt động và có tỉnh.
- Có Trưởng nhóm tổ chức đang hoạt động.
- Có ít nhất một Sale hoặc CTV Sale đang hoạt động.

Zone, hàng chờ đầu vào, Policy và mapping từng trường không còn là điều kiện
setup Lead batch. Các DocType cũ vẫn giữ nguyên để không phá Student và dữ liệu
lịch sử.

## 3. Luồng phân công Lead

```text
Tạo batch trên dashboard
  → nhập Lead tay hoặc CSV
  → mỗi Lead có tỉnh
  → xem trước
  → hệ thống tìm Group/Team theo tỉnh
  → chọn Sale/CTV có tải phù hợp
  → ghi ownership và lý do
```

Backend không nhận Team do người vận hành chọn trong luồng thông thường. Team
được tìm tự động từ Group có cùng tỉnh với Lead. Nếu một tỉnh có nhiều Team,
engine xét tất cả Team đủ điều kiện rồi chọn ứng viên có tải thấp nhất.

Trường THPT, CCCD và ngành quan tâm vẫn bắt buộc để kiểm tra Lead và phục vụ
bước handoff sang Student; chúng không được dùng để bắt người dùng setup mapping
thủ công.

## 4. Quyền thao tác

| Vai trò | Quyền |
|---|---|
| Admin/System Manager | Xem và quản lý tất cả Group, Team, trưởng nhóm, thành viên |
| Lead Sale | Xem và chỉnh Trưởng Group/Trưởng nhóm, quản lý thành viên trong phạm vi |
| Trưởng nhóm | Xem cấu trúc được cấp quyền và quản lý thành viên/Team trong phạm vi |
| Sale/CTV | Xem Team và xử lý Lead được giao |

Việc chọn Trưởng nhóm là quyền tổ chức riêng. Không suy ra Trưởng nhóm từ
function `Lead Sale`, `Sale` hoặc `CTV Sale`.

## 5. API dashboard cần dùng

### Quản lý Group/Team

Các API đọc Group/Team yêu cầu một trong các capability `system.configure`,
`admissions.oversee`, `team.oversee` hoặc `student.execute`; vì vậy Sale và CTV
Sale có thể tải workspace để xem Team của mình. Tạm thời profile Sale và Lead
Sale cũng được gọi các API ghi để chạy UI trước; đây chưa phải boundary bảo mật
cuối cùng. Việc tạo Group mới vẫn dành cho hai profile được cấp phạm vi toàn
cục và đầy đủ quyền đọc/ghi của workspace:

- CEO: role canonical `Administrator` (profile `ceo`), không bị giới hạn theo Team/Cơ sở.
- Director: role canonical `Admissions Director` (profile `admissions_director`), không bị giới hạn theo Team/Cơ sở.

Các kiểm tra nghiệp vụ và validation dữ liệu vẫn được áp dụng ở backend.

| API | Mục đích |
|---|---|
| `crm.api.team_management.get_team_management_workspace` | Đọc Group, Team, nhân sự và tỉnh |
| `crm.api.team_management.get_team_group_detail` | Đọc một Group và các Team |
| `crm.api.team_management.get_team_detail` | Đọc một Team và thành viên |
| `crm.api.team_management.save_team_group` | Tạo/cập nhật Group và tỉnh |
| `crm.api.team_management.save_team` | Tạo/cập nhật Team trong Group |
| `crm.api.team_management.add_team_member` | Thêm/cập nhật thành viên và function |
| `crm.api.team_management.move_team_member` | Chuyển thành viên giữa Team |
| `crm.api.team_management.remove_team_member` | Gỡ thành viên |
| `crm.api.team_management.change_team_lead` | Đổi Trưởng nhóm tổ chức |
| `crm.api.team_management.update_team_member` | Cập nhật tên nhân sự |

### Thông tin vai trò của tài khoản đăng nhập

`crm.api.session.me` bổ sung `crm_team_memberships`. Mỗi phần tử cho biết:

- `role`/`function`: vai trò nghiệp vụ của người đó (`Sale`, `CTV Sale`, `Lead Sale`).
- `membership_role`: vai trò trong Team (`Trưởng nhóm` hoặc `Thành viên`).
- `team_id`, `team_name`, `group_id`, `group_name`, `province_id`: phạm vi tổ chức.
- `is_team_lead`: giá trị máy đọc được tương ứng với `membership_role`.

### Phân công theo đợt

| API | Mục đích |
|---|---|
| `import_leads_to_assignment_batch` | Tạo Lead và đợt nháp từ form/CSV |
| `preview_lead_assignment_batch` | Xem Team/Sale dự kiến theo tỉnh |
| `run_lead_assignment_batch` | Ghi phân công cho đợt |
| `retry_lead_assignment_batch` | Xử lý lại item lỗi/cần bổ sung |
| `get_lead_assignment_catalogs` | Lấy tỉnh, trường, ngành, nguồn từ Frappe |

## 6. Những nghiệp vụ đã bỏ khỏi luồng setup mới

- Không chọn Pool/hàng chờ đầu vào khi tạo batch.
- Không tạo hoặc gán Zone để một Lead được phân công.
- Không tạo Policy/chiến lược chia Lead riêng cho từng Team.
- Không mapping từng trường vào Team.
- Không yêu cầu worker chạy ngầm.
- Không để dashboard tự tính hoặc tự chọn Sale.

Các lớp trên không bị xóa khỏi backend. Chúng vẫn có thể được đọc bởi luồng
Student/legacy và giữ dữ liệu lịch sử. Lead batch mới dùng route
`province → Group → Team → Sale/CTV`.

## 7. Checklist nghiệm thu

- [ ] Admin tạo được Group có tỉnh từ danh mục Frappe.
- [ ] Tạo được nhiều Team trong cùng Group.
- [ ] Một Team có thể có nhiều Lead Sale, nhiều Sale và nhiều CTV.
- [ ] Mỗi card Group hiển thị và cho phép chỉnh một Trưởng Group.
- [ ] Trưởng nhóm được quản lý độc lập với function của thành viên.
- [ ] Team thiếu Sale/CTV hiển thị chưa sẵn sàng.
- [ ] Batch không cần chọn hàng chờ hoặc Team.
- [ ] Lead có tỉnh sẽ tự tìm Team thuộc Group của tỉnh đó.
- [ ] Preview hiển thị từng Lead sẽ vào Team/Sale/CTV nào.
- [ ] Run lưu người được chọn, Team, tỉnh, lý do và tải hiện tại.
- [ ] Lead thiếu CCCD/THPT/ngành chuyển sang cần xử lý, không gán sai người.
- [ ] Batch có thể tạo nhiều đợt và có trạng thái Hoàn tất hoặc Còn lỗi.
- [ ] Dữ liệu Frappe cũ về Zone/Pool/Policy không bị xóa.

## 8. Repair tài khoản vận hành trên production

Hai endpoint workspace và lịch sử phân công yêu cầu tài khoản nghiệp vụ có:

- Role chuẩn `Sale` hoặc `Lead Sale`.
- Một `CRM Staff` đang hoạt động liên kết đúng với User.
- `department` và `campus` hợp lệ; thêm `team` nếu tài khoản cần tham gia luồng
  phân công.

Nếu tài khoản đã đăng nhập được nhưng trả về `An active CRM Staff record is
required.`, System Manager chạy command repair có tham số rõ ràng:

```bash
bench --site <site> execute crm.demo.repair_operational_accounts.execute --kwargs '{"accounts":[{"email":"sale@example.com","role":"Sale","department":"<department>","campus":"<campus>","team":"<sales-team>"},{"email":"lead@example.com","role":"Lead Sale","department":"<department>","campus":"<campus>","team":"<sales-team>","is_team_lead":true}]}'
```

`department`, `campus` và `team` phải là bản ghi đã tồn tại; command kiểm tra
Team đang hoạt động, thuộc đúng campus và không tạo hai primary team. Có thể bỏ
`team` để chỉ sửa identity Staff, nhưng tài khoản sẽ cần được gắn Team thủ công
trước khi chạy routing. Command không đổi mật khẩu, không tự bật User bị disable,
không sửa tài khoản `Administrator`/`System Manager`, và rollback toàn bộ nếu một
tài khoản không hợp lệ.
