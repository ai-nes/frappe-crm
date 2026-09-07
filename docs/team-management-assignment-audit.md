# Audit Group, Team và phân công Lead

**Ngày rà soát:** 2026-09-08  
**Mục tiêu:** người không chuyên kỹ thuật có thể setup một lần trên
`dashboard-crm`, sau đó tạo đợt Lead và bấm phân công.

## 1. Mô hình nghiệp vụ chuẩn

```text
Trưởng Group (một người quản lý tất cả Group đang hoạt động)
  └── Group (một tỉnh)
        └── nhiều Team
              ├── một Trưởng nhóm tổ chức
              └── nhiều thành viên: Lead Sale, Sale, CTV Sale
```

- Admin quyết định ai là Trưởng Group.
- Trưởng Group được áp dụng đồng nhất cho tất cả Group đang hoạt động.
- Admin quyết định Trưởng nhóm tổ chức riêng cho từng Team.
- Trưởng nhóm quản lý các Team và phạm vi tỉnh đã được giao.
- Mỗi tỉnh có một Group hoạt động.
- Một Group có thể có nhiều Team.
- Một Team có nhiều Sale/CTV; không bắt buộc chỉ một Lead Sale.
- `Lead Sale` là vai trò quản lý/nghiệp vụ, không phải người nhận Lead tự động.
- Sale và CTV Sale mới là nhóm ứng viên nhận Lead.
- Trường THPT thuộc tỉnh nào được lấy từ dữ liệu Frappe; không cần gắn từng
  trường vào Team trong luồng phân công mới.

## 2. Setup tối thiểu trên dashboard

Người vận hành chỉ cần làm bốn việc:

1. Chọn Trưởng Group cho toàn bộ các Group đang hoạt động.
2. Tạo hoặc chọn Group và gắn một tỉnh.
3. Tạo Team bên trong Group.
4. Thêm Trưởng nhóm tổ chức và các thành viên Sale/CTV cho Team.

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
| Trưởng nhóm | Xem cấu trúc được cấp quyền và quản lý thành viên/Team trong phạm vi |
| Sale/CTV | Xem Team và xử lý Lead được giao |

Việc chọn Trưởng nhóm là quyền tổ chức riêng. Không suy ra Trưởng nhóm từ
function `Lead Sale`, `Sale` hoặc `CTV Sale`.

## 5. API dashboard cần dùng

### Quản lý Group/Team

| API | Mục đích |
|---|---|
| `crm.api.team_management.get_team_management_workspace` | Đọc Group, Team, nhân sự và tỉnh |
| `crm.api.team_management.get_team_group_detail` | Đọc một Group và các Team |
| `crm.api.team_management.get_team_detail` | Đọc một Team và thành viên |
| `crm.api.team_management.save_team_group` | Tạo/cập nhật Group và tỉnh |
| `crm.api.team_management.save_global_group_lead` | Đặt một Trưởng Group cho tất cả Group đang hoạt động |
| `crm.api.team_management.save_team` | Tạo/cập nhật Team trong Group |
| `crm.api.team_management.add_team_member` | Thêm/cập nhật thành viên và function |
| `crm.api.team_management.move_team_member` | Chuyển thành viên giữa Team |
| `crm.api.team_management.remove_team_member` | Gỡ thành viên |
| `crm.api.team_management.change_team_lead` | Đổi Trưởng nhóm tổ chức |

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
- [ ] Trưởng nhóm được quản lý độc lập với function của thành viên.
- [ ] Team thiếu Sale/CTV hiển thị chưa sẵn sàng.
- [ ] Batch không cần chọn hàng chờ hoặc Team.
- [ ] Lead có tỉnh sẽ tự tìm Team thuộc Group của tỉnh đó.
- [ ] Preview hiển thị từng Lead sẽ vào Team/Sale/CTV nào.
- [ ] Run lưu người được chọn, Team, tỉnh, lý do và tải hiện tại.
- [ ] Lead thiếu CCCD/THPT/ngành chuyển sang cần xử lý, không gán sai người.
- [ ] Batch có thể tạo nhiều đợt và có trạng thái Hoàn tất hoặc Còn lỗi.
- [ ] Dữ liệu Frappe cũ về Zone/Pool/Policy không bị xóa.
