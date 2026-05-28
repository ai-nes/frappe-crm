# Hướng dẫn chạy local dev

Repo này có 2 phần chạy cùng nhau:

- **Backend**: Frappe + MariaDB + Redis, chạy trong Docker.
- **Frontend**: Vue/Vite, chạy trực tiếp trên máy của bạn.

Code trong repo được mount vào Docker tại `/workspace`, nên khi sửa code backend trong thư mục `crm/`, container backend có thể thấy code mới.

## 1. Chạy lần đầu

Chạy:

```bash
task setup
```

Lệnh này sẽ:

- bật Docker backend
- tạo Frappe bench nếu chưa có
- tạo site `crm.localhost`
- install app CRM
- install frontend dependencies

Lần đầu có thể chạy khá lâu vì phải tạo bench, site và migrate database.

Sau khi setup xong, chạy frontend:

```bash
task fe
```

Mở app:

```text
http://crm.localhost:8080/crm
```

Tài khoản mặc định:

```text
Administrator / admin
```

## 2. Chạy hằng ngày

Mỗi ngày khi bắt đầu code, chạy backend trước:

```bash
task up
```

Sau đó chạy frontend:

```bash
task fe
```

Thông thường bạn sẽ để 2 terminal:

```text
Terminal 1: task up
Terminal 2: task fe
```

Nếu backend đã chạy sẵn rồi thì chỉ cần:

```bash
task fe
```

## 3. Các URL cần nhớ

| Mục đích | URL |
|---|---|
| Frontend dev | `http://crm.localhost:8080/crm` |
| Backend Frappe | `http://crm.localhost:8000` |
| Backend CRM page | `http://crm.localhost:8000/crm` |
| API Frappe | `http://crm.localhost:8000/api/method/...` |
| API docs local | `http://crm.localhost:8000/swagger` |

Nên dùng chung host `crm.localhost` cho cả frontend và backend.

Không nên login bằng:

```text
http://localhost:8000
```

rồi sau đó mở:

```text
http://crm.localhost:8080
```

Vì browser cookie phụ thuộc vào host. `localhost` và `crm.localhost` là 2 host khác nhau.

## 4. FE code như thế nào?

Frontend nằm ở:

```text
frontend/src/
```

Chạy frontend bằng:

```bash
task fe
```

Lệnh này thực chất chạy Vite.

Khi sửa Vue, JS hoặc CSS:

- Vite tự reload
- không cần restart Docker
- không cần rebuild backend

FE gọi API bằng path dạng:

```text
/api/method/...
```

Ví dụ:

```text
/api/method/crm.api.contact.get_contacts
```

Khi chạy ở port `8080`, Vite sẽ proxy API sang backend Frappe ở port `8000`.

## 5. BE code như thế nào?

Backend nằm ở:

```text
crm/
```

Một số file hay sửa:

```text
crm/api/contact.py
crm/api/deal.py
crm/api/lead.py
crm/fcrm/doctype/
crm/hooks.py
```

API trong Frappe thường được tạo bằng `@frappe.whitelist()`.

Ví dụ:

```python
import frappe

@frappe.whitelist()
def ping():
    return "pong"
```

API sẽ có URL:

```text
http://crm.localhost:8000/api/method/crm.api.contact.ping
```

Nếu gọi từ frontend thì dùng:

```text
/api/method/crm.api.contact.ping
```

## 6. Có cần restart Docker mỗi lần sửa code không?

Không.

Sửa frontend:

```text
Không restart Docker.
Vite tự reload.
```

Sửa backend Python:

```text
Thường chỉ cần gọi lại API hoặc refresh browser.
```

Nếu sửa Python mà backend chưa nhận code mới, chạy:

```bash
task restart
```

Nếu sửa DocType, database schema, patch, fixture hoặc hook, chạy:

```bash
task migrate
```

## 7. Khi nào dùng từng lệnh?

| Lệnh | Dùng khi nào |
|---|---|
| `task setup` | Lần đầu setup project |
| `task up` | Bật backend Docker |
| `task fe` | Chạy frontend Vite |
| `task logs` | Xem log backend |
| `task restart` | Restart backend Frappe |
| `task migrate` | Chạy migrate sau khi đổi DocType/schema/hook |
| `task shell` | Vào shell trong container backend |
| `task down` | Tắt backend Docker |
| `task build` | Build lại image khi đổi `docker/frappe.Dockerfile` |
| `task recreate` | Recreate container khi đổi `docker/docker-compose.dev.yml` |
| `task reset` | Xóa sạch database/bench local và tạo lại |

## 8. Xem log backend

Chạy:

```bash
task logs
```

Dùng lệnh này khi:

- API lỗi
- backend không start được
- cần xem traceback Python
- cần biết migrate có lỗi không

## 9. Vào container backend

Chạy:

```bash
task shell
```

Sau đó bạn có thể chạy lệnh Frappe bên trong container.

Ví dụ:

```bash
cd /home/frappe/frappe-bench
bench --site crm.localhost console
```

## 10. Xem API docs

Mở:

```text
http://crm.localhost:8000/swagger
```

Hoặc xem OpenAPI JSON:

```text
http://crm.localhost:8000/api/method/crm.api.swagger.get_openapi_spec
```

API docs này được sinh từ các function có:

```python
@frappe.whitelist()
```

Lưu ý: đây là API docs phục vụ local dev. Nó giúp xem endpoint và params, nhưng response schema có thể chưa đầy đủ như Swagger của FastAPI.

## 11. Lỗi thường gặp

### CSRFTokenError khi gọi API từ port 8080

Dev site cần có config:

```json
"ignore_csrf": 1
```

`docker/init.sh` đã tự set config này khi tạo site mới.

Nếu site cũ bị thiếu config, chạy:

```bash
docker compose -f docker/docker-compose.dev.yml exec frappe bash -lc 'cd /home/frappe/frappe-bench && bench --site crm.localhost set-config ignore_csrf 1'
task restart
```

### Bị chuyển sang trang `not-permitted`

Login tại:

```text
http://crm.localhost:8000/login
```

Sau đó mở lại:

```text
http://crm.localhost:8080/crm
```

Nếu vẫn lỗi, xóa browser site data của `crm.localhost`, rồi login lại.

### Lỗi thiếu package Rollup trên macOS

Nếu chạy `task fe` hoặc `yarn dev` bị lỗi thiếu:

```text
@rollup/rollup-darwin-arm64
```

thì chạy:

```bash
cd frontend
yarn install --check-files
```

## 12. Tóm tắt cực ngắn

Lần đầu:

```bash
task setup
task fe
```

Mỗi ngày:

```bash
task up
task fe
```

Sửa FE:

```text
Vite tự reload.
```

Sửa BE:

```text
Refresh/gọi lại API.
Nếu chưa ăn code mới thì task restart.
```

Sửa database schema hoặc DocType:

```bash
task migrate
```
