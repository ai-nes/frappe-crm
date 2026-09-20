# Admin catalog API

## Score signals

`GET /api/method/crm.api.admin_catalog.list_score_signals`

Requires an authenticated user with read access to `CRM Score Signal`.

Query parameters:

- `search`: searches the signal key, label, category, and signal type.
- `active_only`: set to `true` to return only active signals.
- `start`: zero-based offset.
- `page_length`: page size.

Response:

```json
{
  "message": {
    "signals": [
      {
        "name": "GRADE_12_GPA",
        "signal_key": "GRADE_12_GPA",
        "label": "Điểm TB lớp 12",
        "category": "Fit",
        "signal_type": "property",
        "is_active": 1,
        "description": "Điểm trung bình lớp 12"
      }
    ],
    "total": 1,
    "start": 0,
    "page_length": 50
  }
}
```
