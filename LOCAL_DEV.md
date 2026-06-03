# Hướng dẫn local dev

Repo này chạy local theo mô hình tách 2 phần:

- **Backend**: Frappe + CRM Python app + MariaDB + Redis, chạy trong Docker.
- **Frontend**: Vue 3 + Vite + frappe-ui, chạy trực tiếp trên máy ở port `5000`.

Code repo được mount vào container tại `/workspace`. App CRM trong bench local được soft-link về `/workspace`, nên khi sửa backend trong `crm/`, container có thể thấy source code mới.

## 0. Yêu cầu

Cần có:

- Docker Desktop, kèm Docker Compose v2
- `task` CLI
- Node.js 20.x hoặc mới hơn
- Yarn 1.x classic

Kiểm tra nhanh:

```bash
docker --version
docker compose version
task --version
node -v
yarn -v
```

### Windows

- Cài [Task](https://taskfile.dev/installation/) (Go) hoặc dùng `yarn dev` từ root thay `task fe`.
- Thêm vào `C:\Windows\System32\drivers\etc\hosts`:

  ```text
  127.0.0.1 crm.localhost
  ```

- Chạy frontend trong **Git Bash** hoặc **PowerShell** (không dùng CMD cũ nếu thiếu `&&`).
- Lần đầu: `cd frontend && yarn install --check-files` rồi `yarn dev`.
- Dòng `Local frappe-ui vite plugin not found, using npm package` là **cảnh báo bình thường**, không phải lỗi.
- Nếu port 5000 bận: `set FRAPPE_WEB_SERVER_PORT=8000` và `set VITE_PORT=5001` (PowerShell: `$env:VITE_PORT=5001`).

## 1. Chạy lần đầu

Ở thư mục root repo:

```bash
task setup
```

Lệnh này sẽ:

- bật MariaDB, Redis và Frappe backend bằng `docker/docker-compose.dev.yml`
- tạo Frappe bench nếu chưa có
- tạo site `crm.localhost`
- install app CRM vào site
- chạy migrate
- install frontend dependencies

Lần đầu có thể lâu vì phải tạo bench, tải Frappe và migrate database.

Sau khi backend lên xong, chạy frontend:

```bash
task fe
```

Mở app:

```text
http://crm.localhost:5000/crm
```

Tài khoản mặc định:

```text
Administrator / admin
```

## 2. Chạy hằng ngày

Mở 2 terminal:

```text
Terminal 1: task up
Terminal 2: task fe
```

Nếu backend đã chạy sẵn, thường chỉ cần:

```bash
task fe
```

Theo dõi backend log:

```bash
task logs
```

Dừng backend stack:

```bash
task down
```

## 3. URL cần nhớ

| Mục đích | URL |
|---|---|
| Frontend dev | `http://crm.localhost:5000/crm` |
| Backend Frappe | `http://crm.localhost:8000` |
| Backend CRM page | `http://crm.localhost:8000/crm` |
| API Frappe | `http://crm.localhost:8000/api/method/...` |
| API docs local | `http://crm.localhost:8000/swagger` |

Luôn dùng chung host `crm.localhost` cho cả frontend và backend.

Không login bằng `http://localhost:8000` rồi mở `http://crm.localhost:5000`, vì cookie trình duyệt phụ thuộc host. `localhost` và `crm.localhost` là 2 host khác nhau.

## 4. Backend code trước như thế nào?

Backend nằm chủ yếu trong:

```text
crm/
```

Các vị trí hay sửa:

```text
crm/api/
crm/fcrm/doctype/
crm/hooks.py
crm/install.py
crm/utils/
```

Khi BE cần mở API cho FE dùng, tạo hoặc sửa function có `@frappe.whitelist()`.

Ví dụ thêm API:

```python
# crm/api/example.py
import frappe


@frappe.whitelist()
def ping(name: str | None = None):
	return {"message": f"pong {name or ''}".strip()}
```

API sẽ có dotted path:

```text
crm.api.example.ping
```

Gọi trực tiếp bằng URL:

```text
http://crm.localhost:8000/api/method/crm.api.example.ping?name=Dat
```

Hoặc test bằng curl:

```bash
curl "http://crm.localhost:8000/api/method/crm.api.example.ping?name=Dat"
```

Nếu API cần login/session, hãy test trong browser sau khi login hoặc gọi từ FE dev server.

Khi sửa Python API/service thông thường:

```text
Refresh browser hoặc gọi lại API.
```

Nếu backend chưa nhận code mới:

```bash
task restart
```

Khi sửa DocType, database schema, patch, fixture hoặc `hooks.py`:

```bash
task migrate
task restart
```

Mở shell backend khi cần chạy bench command:

```bash
task shell
```

Ví dụ bên trong container:

```bash
cd /home/frappe/frappe-bench
bench --site crm.localhost console
```

## 5. Frontend nối với BE như thế nào?

Frontend nằm trong:

```text
frontend/src/
```

Chạy frontend:

```bash
task fe
```

Vite chạy ở:

```text
http://crm.localhost:5000
```

File `frontend/vite.config.js` dùng frappe-ui Vite plugin với dev proxy. Vì vậy FE gọi API bằng dotted path hoặc path tương đối, không hard-code host `localhost:8000`.

Ví dụ gọi API BE vừa tạo bằng `call` từ `frappe-ui`:

```js
import { call } from 'frappe-ui'

const result = await call('crm.api.example.ping', {
  name: 'Dat',
})
```

Ví dụ dùng `createResource`:

```js
import { createResource } from 'frappe-ui'

const ping = createResource({
  url: 'crm.api.example.ping',
  params: {
    name: 'Dat',
  },
  auto: true,
})
```

Nếu cần gọi path đầy đủ thì dùng path tương đối:

```text
/api/method/crm.api.example.ping
```

Không dùng:

```text
http://localhost:8000/api/method/...
```

vì như vậy dễ lệch cookie/session giữa FE và BE.

Khi sửa Vue, JS hoặc CSS:

```text
Vite tự hot reload.
Không cần restart Docker.
```

Nếu thêm package frontend:

```bash
cd frontend
yarn add ten-package
```

Người khác pull code mới có đổi `frontend/yarn.lock` thì chạy:

```bash
task install-fe
```

## 6. Quy trình phối hợp BE trước, FE sau

### Bước 1: BE định nghĩa contract

BE tạo API rõ input/output:

```python
@frappe.whitelist()
def get_summary(lead: str):
	doc = frappe.get_doc("CRM Lead", lead)
	return {
		"name": doc.name,
		"lead_name": doc.lead_name,
		"status": doc.status,
	}
```

Ghi lại cho FE:

```text
Method: crm.api.lead.get_summary
Input: { lead: string }
Output: { name, lead_name, status }
```

### Bước 2: BE test API trước

Test nhanh bằng browser/curl:

```text
http://crm.localhost:8000/api/method/crm.api.lead.get_summary?lead=LEAD-0001
```

Nếu là API POST hoặc cần session, test từ browser/FE sau khi login.

### Bước 3: FE gọi dotted path

FE dùng `call` hoặc `createResource`:

```js
const summary = await call('crm.api.lead.get_summary', {
  lead: leadName,
})
```

### Bước 4: FE xử lý loading/error

Với API hiển thị trên UI, luôn xử lý ít nhất:

```text
loading
empty state
error/toast
success data
```

### Bước 5: Khi BE đổi contract, FE đổi theo

Nếu BE đổi tên field, format output hoặc dotted path, FE phải cập nhật đúng chỗ đang gọi API đó. Tìm nhanh:

```bash
rg "crm.api.lead.get_summary" frontend/src
```

## 7. Khi có code mới thì chạy gì?

Sau khi pull code mới:

```bash
git pull
task up
```

Nếu có đổi dependencies frontend:

```bash
task install-fe
```

Nếu có đổi backend Python thường:

```bash
task restart
```

Nếu có đổi DocType/schema/patch/hooks:

```bash
task migrate
task restart
```

Nếu có đổi Docker dev compose:

```bash
task recreate
```

Nếu có đổi `docker/frappe.Dockerfile`:

```bash
task build
task up
```

Nếu muốn reset sạch local database và bench:

```bash
task reset
```

Lưu ý: `task reset` xóa local Docker volumes, mất database local.

## 8. Quy trình khi thay đổi database

Frappe không dùng migration kiểu độc lập như nhiều backend thuần SQL. Với repo này, DB schema chủ yếu đến từ DocType JSON trong app:

```text
crm/fcrm/doctype/**/**.json
crm/lead_syncing/doctype/**/**.json
```

Khi chạy:

```bash
task migrate
```

Frappe sẽ chạy `bench --site crm.localhost migrate`, bao gồm:

- chạy patches trong `crm/patches.txt`
- sync DocType JSON vào database
- tạo/sửa bảng và cột tương ứng
- cập nhật metadata/cache liên quan

### Sửa DocType hoặc thêm field

Quy trình local:

```bash
task up
# sửa DocType JSON hoặc tạo DocType/field bằng Frappe developer tools
task migrate
task restart
```

Nếu chỉ thêm field/table đơn giản, thường `task migrate` là đủ. `task restart` giúp backend reload Python/hooks/meta sạch hơn.

### Đổi dữ liệu, backfill, rename hoặc migrate logic

Nếu thay đổi cần sửa dữ liệu đang có, không sửa tay trực tiếp bằng SQL. Hãy viết patch.

Tạo file patch:

```text
crm/patches/v1_0/my_change.py
```

Ví dụ:

```python
import frappe


def execute():
	if not frappe.db.exists("DocType", "CRM Lead"):
		return

	frappe.db.sql("""
		update `tabCRM Lead`
		set custom_source = 'Unknown'
		where custom_source is null
	""")
```

Sau đó thêm dotted path vào `crm/patches.txt`.

Dùng `[pre_model_sync]` khi patch cần chạy trước khi Frappe sync DocType, ví dụ rename DocType/field cũ trước khi schema mới apply.

Dùng `[post_model_sync]` khi patch cần schema mới tồn tại trước, ví dụ backfill field mới, tạo default record, tạo Custom Field, Property Setter.

Sau khi thêm patch:

```bash
task migrate
task restart
```

Patch nên viết theo hướng an toàn:

- kiểm tra tồn tại bằng `frappe.db.exists`
- không assume dữ liệu luôn có
- có thể chạy lại mà không phá dữ liệu
- không hard-code dữ liệu production nếu không cần
- nếu rename/delete field quan trọng, nên có patch chuyển dữ liệu trước

### Khi nào không cần migrate?

Không cần `task migrate` nếu chỉ sửa:

- Vue/JS/CSS frontend
- Python API logic không đổi DocType/schema/hooks
- text hiển thị
- validation logic không tạo field/table mới

Nếu sửa `hooks.py`, DocType JSON, patches, fixtures hoặc install/setup logic thì chạy:

```bash
task migrate
task restart
```

## 9. Checklist theo loại thay đổi

| Loại thay đổi | Cần chạy |
|---|---|
| `frontend/src/**/*.vue/js/css` | Không cần restart, Vite tự reload |
| `frontend/package.json` hoặc `frontend/yarn.lock` | `task install-fe` |
| `crm/api/*.py` | Gọi lại API, nếu chưa ăn thì `task restart` |
| Python service/helper trong `crm/` | Gọi lại flow, nếu chưa ăn thì `task restart` |
| DocType/schema/patch/fixture | `task migrate`, rồi `task restart` nếu cần |
| `crm/hooks.py` | `task migrate` và thường nên `task restart` |
| `docker/docker-compose.dev.yml` | `task recreate` |
| `docker/frappe.Dockerfile` | `task build`, rồi `task up` |

Quy tắc dễ nhớ:

```text
FE đổi       -> Vite reload
BE API đổi   -> gọi lại API, chưa ăn thì restart
DB/schema đổi -> migrate
Docker đổi   -> recreate/build
```

## 10. Test nhanh trước khi commit

Frontend unit tests:

```bash
task test-fe
```

Kiểm tra compose dev còn hợp lệ:

```bash
docker compose -f docker/docker-compose.dev.yml config
```

Nếu chỉ sửa docs thì không cần chạy backend/frontend.
