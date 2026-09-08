# Public Leads & Campaigns API

Tài liệu contract cho các API public dùng bởi hệ thống bên ngoài. Các endpoint
không yêu cầu đăng nhập (`allow_guest=true`) và đều được giới hạn 120 request/
phút theo client identity/IP. Khi gọi qua HTTP, Frappe bọc dữ liệu trong key
`message`.

- Base URL: `http://<crm-host>`
- Authentication: Không yêu cầu
- Không cần gửi header `Authorization`

## 1. Lấy danh sách Lead theo campaign

### Endpoint

```http
GET /api/method/crm.api.lead_mapping.get_public_leads
```

Ví dụ:

```http
GET /api/method/crm.api.lead_mapping.get_public_leads?campaign_code=CAM-2026-00001&startdate=2026-09-01&enddate=2026-09-30&start=0&page_length=20
```

### Query parameters

| Parameter | Kiểu | Bắt buộc | Mặc định | Mô tả |
| --- | --- | :---: | ---: | --- |
| `campaign_code` | string | Có | — | Mã `CRM Campaign.stable_code`, dạng `CAM-YYYY-NNNNN`. |
| `startdate` | date | Không | — | Ngày bắt đầu theo `CRM Lead.creation`, inclusive. |
| `enddate` | date | Không | — | Ngày kết thúc theo `CRM Lead.creation`, inclusive cả ngày. |
| `start_date` | date | Không | — | Alias của `startdate`. |
| `end_date` | date | Không | — | Alias của `enddate`. |
| `start` | integer | Không | `0` | Offset phân trang, tối thiểu `0`. |
| `page_length` | integer | Không | `20` | Số Lead mỗi trang, từ `1` đến `100`. |

Ngày phải có định dạng `YYYY-MM-DD`. Nếu gửi cả tên chính và alias, hai giá trị
phải giống nhau.

### Response

```json
{
  "message": {
    "total": 1,
    "start": 0,
    "page_length": 20,
    "leads": [
      {
        "name": "HS-2026-HCM-000001",
        "lead_code": "HS-2026-HCM-000001",
        "student_name": "Nguyễn Văn An",
        "phone": "0901234567",
        "email": "an@example.com",
        "major": "Software Engineering",
        "high_school": "THPT Nguyễn Du",
        "province": "Hồ Chí Minh",
        "ward": "Phường Bến Nghé",
        "lead_status": "New",
        "campaign": "Lead API 2026 - Website",
        "creation": "2026-09-15 12:30:00"
      }
    ]
  }
}
```

Public Lead response gồm `name`, `lead_code`, `student_name`, `phone`, `email`,
`major`, `high_school`, `province`, `ward`, `lead_status`, `campaign` và
`creation`. Các field `high_school`, `province` và `ward` trả về tên hiển thị
(`school_name`, `province_name`, `ward_name`), không trả raw Link/docname. Vì
`phone` và `email` là dữ liệu cá nhân, bên tích hợp phải bảo vệ campaign code và
endpoint; các field ownership như `owner_staff` và `assigned_to` vẫn không được
trả về.

### Phân trang và sắp xếp

API dùng offset pagination:

```text
start = 0,  page_length = 20 -> trang đầu
start = 20, page_length = 20 -> trang tiếp theo
```

Danh sách được sắp xếp theo `creation desc, name desc`.

### Lỗi

| Code | Nguyên nhân |
| --- | --- |
| `REQUIRED_FIELD` | Thiếu `campaign_code`. |
| `INVALID_CAMPAIGN_CODE` | Campaign code sai định dạng hoặc không tồn tại. |
| `INVALID_DATE` | Ngày sai định dạng, không hợp lệ hoặc `startdate > enddate`. |
| `INVALID_PAGINATION` | `start`/`page_length` sai kiểu hoặc ngoài giới hạn. |

## 2. Lấy danh sách Campaign public

### Endpoint

```http
GET /api/method/crm.api.campaign.get_public_campaigns
```

Ví dụ:

```http
GET /api/method/crm.api.campaign.get_public_campaigns?campaign_code=CAM-2026-00001&startdate=2026-09-01&enddate=2026-09-30&start=0&page_length=20
```

### Query parameters

| Parameter | Kiểu | Bắt buộc | Mặc định | Mô tả |
| --- | --- | :---: | ---: | --- |
| `campaign_code` | string | Không | — | Lọc chính xác theo `CRM Campaign.stable_code`. |
| `startdate` | date | Không | — | Chỉ lấy campaign có `start_date >= startdate`. |
| `enddate` | date | Không | — | Chỉ lấy campaign có `end_date <= enddate`. |
| `start_date` | date | Không | — | Alias của `startdate`. |
| `end_date` | date | Không | — | Alias của `enddate`. |
| `start` | integer | Không | `0` | Offset phân trang, tối thiểu `0`. |
| `page_length` | integer | Không | `20` | Số campaign mỗi trang, từ `1` đến `100`. |

Có thể bỏ `campaign_code` để lấy danh sách campaign theo điều kiện ngày. Ngày
phải có định dạng `YYYY-MM-DD`; nếu gửi cả tên chính và alias, hai giá trị phải
giống nhau.

### Response

```json
{
  "message": {
    "total": 1,
    "start": 0,
    "page_length": 20,
    "campaigns": [
      {
        "name": "Lead API 2026 - Website",
        "stable_code": "CAM-2026-00001",
        "title": "Lead API 2026 - Website",
        "campus": "Ho Chi Minh City",
        "campaign_type": "Digital",
        "event_type": "On-Campus",
        "status": "ACTIVE",
        "start_date": "2026-09-01",
        "end_date": "2026-09-30",
        "platform": "Facebook",
        "channel_boundary": "Digital",
        "channel_type": "FACEBOOK_LEAD_FORM",
        "channel_url": "https://example.com/lead-form",
        "utm_source": "facebook",
        "utm_medium": "paid_social",
        "utm_campaign": "lead-api-website-2026"
      }
    ]
  }
}
```

Campaign response chỉ trả metadata phục vụ tích hợp public. Các field nội bộ
như `budget`, `owner_staff`, `owning_team`, KPI và `notes` không được trả về.
Danh sách được sắp xếp theo `start_date asc, stable_code asc, name asc`. Không
có campaign khớp điều kiện thì trả `total: 0` và `campaigns: []`.

### Lỗi

| Nguyên nhân | Response |
| --- | --- |
| Ngày sai định dạng hoặc không hợp lệ | `ValidationError` |
| `startdate` lớn hơn `enddate` | `ValidationError` |
| `start`/`page_length` sai kiểu hoặc ngoài giới hạn | `ValidationError` |

Campaign code không tồn tại không tạo lỗi; API trả danh sách rỗng.

## 3. Ví dụ cURL

```bash
curl "http://<crm-host>/api/method/crm.api.lead_mapping.get_public_leads?campaign_code=CAM-2026-00001&start=0&page_length=20"
```

```bash
curl "http://<crm-host>/api/method/crm.api.campaign.get_public_campaigns?startdate=2026-09-01&enddate=2026-09-30&start=0&page_length=20"
```

## Tham chiếu source

- `crm/api/lead_mapping.py` — method `get_public_leads`
- `crm/api/campaign.py` — method `get_public_campaigns`
- `crm/api/test_lead_mapping.py` — Lead contract tests
- `crm/api/test_campaign.py` — Campaign contract tests
