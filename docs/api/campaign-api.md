# Campaign API

## Tổng quan

CRUD API cho DocType `CRM Campaign`. API dùng permission của DocType theo user
hiện tại; không dùng `ignore_permissions`. Frappe bọc mọi response trong key
`message` khi gọi qua HTTP.

- Base URL: `http://localhost:8000`
- Endpoint prefix: `/api/method/`
- Authentication: Frappe session cookie hoặc `Authorization: token <api_key>:<api_secret>`
- Campaign code `stable_code` được backend sinh theo dạng `CAM-YYYY-NNNNN` và
  không thể thay đổi sau khi tạo.

## Campaign object

| Field | Kiểu | Mô tả |
| --- | --- | --- |
| `name` | string | ID nội bộ của campaign; mặc định được sinh từ `title`. |
| `stable_code` | string | Mã campaign do server quản lý, immutable. |
| `title` | string | Tiêu đề, bắt buộc và duy nhất. |
| `campus` | string | ID `CRM Campus`, bắt buộc. |
| `campaign_type` | string/null | ID `CRM Campaign Type`. |
| `event_type` | string/null | `On-Campus` hoặc `Off-Campus`. |
| `status` | string | `DRAFT`, `UPCOMING`, `ACTIVE` hoặc `CLOSED`. Mặc định `DRAFT`. |
| `start_date` | date/null | Ngày bắt đầu, định dạng `YYYY-MM-DD`. |
| `end_date` | date/null | Ngày kết thúc, định dạng `YYYY-MM-DD`. |
| `budget` | number/null | Ngân sách campaign. |
| `owner_staff` | string/null | ID `CRM Staff`; mặc định theo user tạo nếu có. |
| `owning_team` | string/null | ID `CRM Team`. |
| `platform` | string/null | ID `CRM Platform`. |
| `channel_boundary` | string/null | `Digital`, `Field`, `Partner` hoặc `Mixed`. |
| `channel_type` | string/null | ID `CRM Campaign Channel Type`. |
| `channel_url` | string/null | URL landing page/form/channel. |
| `utm_source` | string/null | UTM source. |
| `utm_medium` | string/null | UTM medium. |
| `utm_campaign` | string/null | UTM campaign. |
| `kpi_target_leads` | integer/null | Mục tiêu số lead. |
| `kpi_target_enrollments` | integer/null | Mục tiêu số enrollment. |
| `notes` | string/null | Ghi chú. |
| `owner` | string | User tạo bản ghi. |
| `creation` | datetime | Thời điểm tạo. |
| `modified` | datetime | Thời điểm cập nhật gần nhất. |

## List campaigns

```http
GET /api/method/crm.api.campaign.list_campaigns
```

Query parameters:

| Parameter | Kiểu | Mặc định | Mô tả |
| --- | --- | ---: | --- |
| `status` | string | — | Lọc theo trạng thái campaign. |
| `campus` | string | — | Lọc theo ID `CRM Campus`. |
| `campaign_type` | string | — | Lọc theo ID `CRM Campaign Type`. |
| `event_type` | string | — | Lọc theo `On-Campus` hoặc `Off-Campus`. |
| `owner_staff` | string | — | Lọc theo ID `CRM Staff`. |
| `owning_team` | string | — | Lọc theo ID `CRM Team`. |
| `platform` | string | — | Lọc theo ID `CRM Platform`. |
| `channel_boundary` | string | — | Lọc theo boundary của channel. |
| `channel_type` | string | — | Lọc theo ID `CRM Campaign Channel Type`. |
| `stable_code` | string | — | Lọc đúng theo campaign code. |
| `start_date_from` | date | — | `start_date >=` giá trị truyền vào. |
| `start_date_to` | date | — | `start_date <=` giá trị truyền vào. |
| `end_date_from` | date | — | `end_date >=` giá trị truyền vào. |
| `end_date_to` | date | — | `end_date <=` giá trị truyền vào. |
| `search` | string | — | Tìm một phần trong `title`, `stable_code` và các UTM field. |
| `start` | integer | `0` | Offset phân trang. |
| `page_length` | integer | `20` | Số bản ghi mỗi trang. |
| `lead_only` | boolean | `false` | Chỉ trả campaign đang gắn với Lead mà user hiện tại được phép đọc. |

Ví dụ lọc campaign đang hoạt động tại một campus trong tháng 9:

```http
GET /api/method/crm.api.campaign.list_campaigns?status=ACTIVE&campus=CAMPUS-001&start_date_from=2026-09-01&start_date_to=2026-09-30&start=0&page_length=20
```

Response:

```json
{
  "message": {
    "total": 1,
    "start": 0,
    "page_length": 20,
    "campaigns": [
      {
        "name": "Tuyển sinh mùa thu 2026",
        "stable_code": "CAM-2026-00001",
        "title": "Tuyển sinh mùa thu 2026",
        "campus": "CAMPUS-001",
        "campaign_type": "Digital",
        "event_type": "On-Campus",
        "status": "ACTIVE",
        "start_date": "2026-09-01",
        "end_date": "2026-09-30",
        "budget": 125000,
        "owner_staff": "STAFF-001",
        "owning_team": "TEAM-001",
        "platform": "FACEBOOK",
        "channel_boundary": "Digital",
        "channel_type": "FACEBOOK_LEAD_FORM",
        "channel_url": "https://example.com/lead-form",
        "utm_source": "facebook",
        "utm_medium": "paid_social",
        "utm_campaign": "autumn-admissions",
        "kpi_target_leads": 100,
        "kpi_target_enrollments": 20,
        "notes": "Campaign mùa thu",
        "owner": "Administrator",
        "creation": "2026-09-01 08:00:00",
        "modified": "2026-09-01 08:00:00"
      }
    ]
  }
}
```

## Get one campaign

```http
GET /api/method/crm.api.campaign.get_campaign?name=<campaign_name>
```

Ví dụ:

```http
GET /api/method/crm.api.campaign.get_campaign?name=Tuyển%20sinh%20m%C3%B9a%20thu%202026
```

Response `message` là một Campaign object.

## Dữ liệu cho trang chi tiết campaign

Trang chi tiết trên `dashboard-crm` dùng hai endpoint đọc sau:

```http
GET /api/method/crm.api.campaign.get_campaign?name=<campaign_name>
GET /api/method/crm.api.director_leads.get_director_leads?campaign=<campaign_name>&page=1&pageSize=100
```

Khi truyền `campaign`, response danh sách Lead bổ sung `meta.stats`:

```json
{
  "total": 12,
  "inProgress": 7,
  "closed": 3,
  "conversionRate": 25
}
```

Mỗi Lead row có thêm `processingStatus` và `createdAt` để hiển thị trạng thái xử lý
và ngày tạo trên trang chi tiết. Hai endpoint đều áp dụng permission của user hiện tại.

## Create campaign

```http
POST /api/method/crm.api.campaign.create_campaign
Content-Type: application/json
```

Các field được phép ghi:

| Field | Bắt buộc | Mô tả |
| --- | :---: | --- |
| `title` | Có | Tiêu đề duy nhất. |
| `campus` | Có | ID `CRM Campus`. |
| Các field còn lại trong Campaign object | Không | Chỉ gửi field cần dùng. |

Không gửi `name`, `stable_code`, `owner`, `creation` hoặc `modified`. `stable_code`
được sinh tự động; `owner_staff` được lấy từ user hiện tại nếu bỏ trống và user
có `CRM Staff` tương ứng.

Request mẫu:

```json
{
  "title": "Tuyển sinh mùa thu 2026",
  "campus": "CAMPUS-001",
  "status": "UPCOMING",
  "start_date": "2026-09-01",
  "end_date": "2026-09-30",
  "budget": 125000,
  "channel_boundary": "Digital",
  "utm_source": "facebook",
  "utm_medium": "paid_social",
  "utm_campaign": "autumn-admissions",
  "kpi_target_leads": 100,
  "kpi_target_enrollments": 20
}
```

Response là Campaign object vừa tạo.

## Update campaign

```http
PUT /api/method/crm.api.campaign.update_campaign?name=<campaign_name>
Content-Type: application/json
```

`POST` cũng được hỗ trợ cho client không dùng được `PUT`. Chỉ gửi các field cần
thay đổi:

```json
{
  "status": "ACTIVE",
  "budget": 150000,
  "notes": "Đã duyệt ngân sách mới"
}
```

`stable_code` immutable. Nếu request gửi code khác code hiện tại, API trả
`ValidationError`. `title` có thể thay đổi; vì `name` mặc định sinh từ title,
client nên dùng `name` trong response mới sau khi update.

## Delete campaign

```http
DELETE /api/method/crm.api.campaign.delete_campaign?name=<campaign_name>
```

`POST` cũng được hỗ trợ cho client không gửi được HTTP `DELETE`.

Response:

```json
{
  "message": {
    "deleted": "Tuyển sinh mùa thu 2026"
  }
}
```

## Permission và lỗi

API tuân theo permission của DocType `CRM Campaign`:

| Role | Read | Create | Write | Delete |
| --- | :---: | :---: | :---: | :---: |
| `Marketing` | ✓ | ✓ | ✓ | ✓ |
| `System Manager` | ✓ | ✓ | ✓ | ✓ |
| `Admissions Director`, `Lead Sale`, `Sale` | ✓ |  |  |  |

Các lỗi thường gặp:

| HTTP/Frappe | Nguyên nhân |
| --- | --- |
| `403` / `PermissionError` | User chưa đăng nhập hoặc không có quyền thao tác. |
| `404` / `DoesNotExistError` | Không tìm thấy campaign hoặc linked record. |
| `417` / `ValidationError` | Payload sai enum, thiếu `title`/`campus`, code bị sửa hoặc link không hợp lệ. |
| `409` / `DuplicateEntryError` | `title` hoặc mã campaign bị trùng. |

## Tham chiếu source

- `crm/api/campaign.py`
- `crm/api/campaign_channel_type.py`
- `crm/fcrm/doctype/crm_campaign/crm_campaign.json`
- `crm/fcrm/doctype/crm_campaign/crm_campaign.py`

## List campaign channel types

```http
GET /api/method/crm.api.campaign_channel_type.list_campaign_channel_types
```

Query parameters:

| Parameter | Kiểu | Mặc định | Mô tả |
| --- | --- | ---: | --- |
| `mode` | string | — | `ONLINE` hoặc `OFFLINE`; chỉ trả loại kênh hỗ trợ mode đó. |
| `search` | string | — | Tìm theo `code`, `display_name` hoặc `description`. |
| `enabled_only` | boolean | `true` | Chỉ trả loại kênh đang bật. |
| `start` | integer | `0` | Offset phân trang. |
| `page_length` | integer | `100` | Số bản ghi mỗi trang. |

Response nằm trong `message`:

```json
{
  "total": 24,
  "start": 0,
  "page_length": 100,
  "channel_types": [
    {
      "code": "EXPERIENCE_DAY",
      "display_name": "Experience Day",
      "is_online": 0,
      "is_offline": 1,
      "enabled": 1,
      "sort_order": 140,
      "modes": ["OFFLINE"]
    }
  ]
}
```

API dùng quyền đọc của DocType `CRM Campaign Channel Type`; không có fallback
hardcode ở frontend khi API lỗi.
