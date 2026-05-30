# Production architecture

Tài liệu này giải thích cách production của repo này chạy. Đây không phải mô hình FE repo riêng + BE repo riêng như nhiều dự án thông thường. Đây là Frappe app:

- Python/Frappe backend nằm trong app `crm/`.
- Vue frontend nằm trong `frontend/`.
- Khi build production image, frontend được build thành static assets rồi nằm trong Frappe app.
- Runtime chạy nhiều process Frappe khác nhau bằng nhiều container, nhưng phần lớn dùng chung một Docker image CRM.

## 1. Tổng quan luồng production

```text
Git push main
  |
  v
GitHub Actions
  |
  | build docker/prod.Dockerfile
  | push ngothanhdatak/crm-frappe:latest
  v
Docker Hub
  |
  v
Dokploy / server pull image mới
  |
  v
docker compose production stack
```

Production image chính là:

```text
ngothanhdatak/crm-frappe:latest
```

Image này được build từ:

```text
docker/prod.Dockerfile
```

Workflow build image:

```text
.github/workflows/dockerhub-image.yml
```

Compose production:

```text
docker/docker-compose.prod.yml
```

## 2. Vì sao có nhiều container?

Frappe production không nên chạy một process duy nhất. Cùng một app CRM cần nhiều process khác nhau:

- HTTP backend để xử lý web/API.
- WebSocket server để realtime/socket.io.
- Background workers để xử lý job queue.
- Scheduler để tạo job định kỳ.
- Nginx để reverse proxy và serve static assets.
- MariaDB để lưu database.
- Redis để cache, queue và socket.io state.

Vì vậy production stack nhìn nhiều container là đúng.

Compose hiện tại định nghĩa các container chính:

| Container | Image | Vai trò |
|---|---|---|
| `nginx` | `nginx:1.27-alpine` | Entry point HTTP, serve `/assets`, proxy request vào backend/websocket |
| `backend` | `${CRM_IMAGE}` | Gunicorn chạy Frappe app ở port `8000` |
| `websocket` | `${CRM_IMAGE}` | Node socket.io server ở port `9000` |
| `queue-short` | `${CRM_IMAGE}` | Worker xử lý queue `short` |
| `queue-default` | `${CRM_IMAGE}` | Worker xử lý queue `default` |
| `queue-long` | `${CRM_IMAGE}` | Worker xử lý queue `long` |
| `scheduler` | `${CRM_IMAGE}` | Frappe scheduler, tạo job định kỳ |
| `mariadb` | `mariadb:10.8` | Database |
| `redis-cache` | `redis:7-alpine` | Redis cache |
| `redis-queue` | `redis:7-alpine` | Redis queue và socket.io |

Ngoài ra có service `site`, nhưng nó thuộc profile `setup`. Nó không phải container chạy thường trực. Nó chỉ dùng khi cần tạo site/migrate/setup:

```bash
docker compose -f docker/docker-compose.prod.yml --profile setup run --rm site
```

Vì vậy bình thường bạn sẽ thấy khoảng 10 container chính. Nếu môi trường deploy nào đó tắt bớt một role, số container có thể khác một chút.

## 3. Image CRM chứa gì?

`docker/prod.Dockerfile` tạo một Frappe bench bên trong image:

```text
/home/frappe/frappe-bench
```

Trong image có:

```text
apps/frappe   # Frappe framework, lấy từ bench init version-15
apps/crm      # source code CRM từ repo này
env/          # Python virtualenv của bench
sites/        # sites template được tạo lúc build
```

Build image làm các bước chính:

1. Cài Python, Node.js, Yarn, frappe-bench.
2. Chạy `bench init --version version-15`.
3. Copy source repo vào `apps/crm`.
4. Cài Python package CRM bằng `pip install -e apps/crm`.
5. Cài dependencies frontend.
6. Build Vue frontend bằng `yarn build`.
7. Copy `sites` thành `/opt/frappe/sites-template`.
8. Copy script production vào `/opt/frappe/scripts/`.

Điểm quan trọng: FE production không chạy bằng Vite dev server. FE đã được build thành static assets trong image.

## 4. Frontend production được serve như thế nào?

Frontend Vue nằm ở:

```text
frontend/
```

Khi build production:

```bash
cd apps/crm/frontend
yarn build
```

Build output được đưa vào Frappe app public assets:

```text
apps/crm/crm/public/frontend
```

Frappe page entry nằm ở:

```text
crm/www/crm.html
```

Khi user mở:

```text
https://crm.beyond8.io.vn/crm
```

Frappe trả về HTML page, HTML đó load các JS/CSS từ:

```text
/assets/crm/frontend/...
```

Nginx serve `/assets/...` trực tiếp từ volume:

```text
/home/frappe/frappe-bench/sites/assets
```

Vì Nginx là container riêng, nó không nhìn thấy `apps/crm/...` trong app container. Do đó runtime script sẽ copy public assets thật vào volume `sites/assets`. Đây là lý do có `prod-runtime.sh` và `prod-site.sh`.

## 5. Request đi qua các container như thế nào?

Luồng HTTP chính:

```text
Browser
  |
  v
Domain / Dokploy proxy
  |
  v
nginx:8080
  |
  | /assets/*      -> serve static file từ sites/assets
  | /socket.io     -> proxy tới websocket:9000
  | everything else -> proxy tới backend:8000
  v
backend / websocket
```

Chi tiết Nginx:

| Path | Nginx làm gì |
|---|---|
| `/assets/...` | Serve file tĩnh từ `sites/assets` |
| `/socket.io` | Proxy WebSocket tới service `websocket:9000` |
| `/api/method/...` | Proxy tới `backend:8000` |
| `/crm` | Proxy tới `backend:8000`, Frappe trả CRM HTML page |
| `/login` | Proxy tới `backend:8000`, Frappe trả login page |

## 6. Backend container làm gì?

Service `backend` chạy:

```text
gunicorn frappe.app:application
```

Nó listen trong container tại:

```text
0.0.0.0:8000
```

Nó xử lý:

- Frappe web pages như `/login`, `/crm`.
- Frappe APIs như `/api/method/...`.
- Server-side permission, database access, session, auth.
- Các request mà Nginx không serve trực tiếp.

Trước khi Gunicorn chạy, compose gọi:

```text
/opt/frappe/scripts/prod-runtime.sh
```

Script này sẽ:

1. Seed `sites` từ `/opt/frappe/sites-template` nếu volume còn thiếu file.
2. Set MariaDB host.
3. Set Redis cache/queue/socketio host.
4. Set socket.io port.
5. Nếu `SYNC_PUBLIC_ASSETS=1`, copy assets thật vào `sites/assets`.

Backend đang bật:

```text
SYNC_PUBLIC_ASSETS=1
```

Vì vậy mỗi lần backend start/recreate, nó sẽ tự đảm bảo assets trong volume đúng, không còn lỗi symlink gãy khiến Nginx 404.

## 7. WebSocket container làm gì?

Service `websocket` chạy:

```text
node apps/frappe/socketio.js
```

Nó listen trong container tại:

```text
9000
```

Nginx proxy `/socket.io` vào service này.

Nó dùng `redis-queue` làm Redis socket.io backend:

```text
REDIS_SOCKETIO=redis://redis-queue:6379
```

## 8. Worker containers làm gì?

Frappe dùng background jobs. Jobs được đưa vào Redis queue, sau đó worker xử lý.

Production tách 3 worker:

```text
queue-short    -> bench worker --queue short
queue-default  -> bench worker --queue default
queue-long     -> bench worker --queue long
```

Ý nghĩa:

- `short`: job nhanh.
- `default`: job bình thường.
- `long`: job lâu hơn.

Tách container giúp:

- job lâu không chặn job nhanh;
- restart từng worker độc lập;
- sau này có thể scale riêng queue nào bị tải cao.

## 9. Scheduler container làm gì?

Service `scheduler` chạy:

```text
bench schedule
```

Nó không xử lý request HTTP. Nó kiểm tra scheduled jobs và đưa job vào Redis queue.

Ví dụ:

- job định kỳ;
- cleanup;
- notification;
- background maintenance.

Worker containers mới là nơi xử lý job thực tế.

## 10. MariaDB và Redis dùng để làm gì?

MariaDB:

```text
mariadb-data:/var/lib/mysql
```

Lưu database Frappe site, DocType data, user, session-related data, CRM records.

Redis cache:

```text
redis-cache
```

Dùng cho Frappe cache.

Redis queue:

```text
redis-queue
```

Dùng cho:

- background job queue;
- socket.io Redis backend.

## 11. Volumes production

Compose định nghĩa 3 volumes:

| Volume | Mount vào đâu | Dùng để làm gì |
|---|---|---|
| `mariadb-data` | `/var/lib/mysql` | Persist database |
| `sites` | `/home/frappe/frappe-bench/sites` | Persist Frappe site config, public/private files, assets |
| `logs` | `/home/frappe/frappe-bench/logs` | Persist Frappe logs |

Quan trọng nhất:

- Không xóa `mariadb-data` nếu không muốn mất database.
- Không xóa `sites` nếu không muốn mất site config/files/assets.
- Image mới có thể recreate container, nhưng data sống trong volumes.

## 12. Setup site khác gì runtime?

Service `site` chỉ chạy khi gọi profile `setup`.

Nó chạy:

```text
bash /opt/frappe/scripts/prod-site.sh
```

Script này làm:

1. Seed `sites` từ template.
2. Set DB/Redis/socket.io config.
3. Nếu site chưa tồn tại, chạy `bench new-site`.
4. Install app CRM vào site.
5. `bench use`.
6. `bench migrate`.
7. `bench clear-cache`.
8. Sync public assets vào `sites/assets`.

Chạy setup lần đầu:

```bash
docker compose -f docker/docker-compose.prod.yml --profile setup run --rm site
```

Chạy lại khi cần migrate sau khi có code mới:

```bash
docker compose -f docker/docker-compose.prod.yml --profile setup run --rm site
```

Với Dokploy hiện tại, nếu Dokploy chỉ pull image và recreate container, có thể nó không tự chạy `site`. Runtime `backend` đã tự sync assets, nhưng migration/schema thay đổi vẫn nên chạy setup/migrate có chủ đích.

## 13. Deploy code mới diễn ra như thế nào?

Quy trình chuẩn:

1. Dev push code lên `main`.
2. GitHub Actions build image mới.
3. Image mới được push lên Docker Hub:

```text
ngothanhdatak/crm-frappe:latest
ngothanhdatak/crm-frappe:<github-sha>
```

4. Dokploy/server pull image mới.
5. Recreate các service dùng `${CRM_IMAGE}`:

```text
backend
websocket
queue-short
queue-default
queue-long
scheduler
```

6. Backend start và tự sync public assets vào volume `sites/assets`.
7. Nginx tiếp tục serve request.

Nếu thay đổi có database migration, cần chạy `site` setup/migrate một lần.

## 14. Quy trình production khi có thay đổi database

Với Frappe, thay đổi DB production phải đi qua:

```text
bench --site <site-name> migrate
```

Trong stack này, cách chuẩn là chạy service `site` profile setup:

```bash
docker compose -f docker/docker-compose.prod.yml --profile setup run --rm site
```

Service này chạy `prod-site.sh`, trong đó có:

```text
bench --site "${SITE_NAME}" migrate
bench --site "${SITE_NAME}" clear-cache
sync_public_assets
```

### Khi nào production cần migrate?

Cần migrate nếu code mới có một trong các thay đổi:

- thêm/sửa/xóa DocType field trong `crm/fcrm/doctype/**`
- thêm DocType mới
- sửa `crm/patches.txt`
- thêm patch trong `crm/patches/**`
- sửa fixture/default data cần sync
- sửa `hooks.py` có ảnh hưởng metadata, scheduler, doc events
- đổi Custom Field, Property Setter, default records bằng code

Không cần migrate nếu chỉ sửa:

- frontend Vue/JS/CSS
- Python API logic không đổi schema
- text hiển thị
- Docker/Nginx config không liên quan DB

### Quy trình deploy DB change an toàn

Quy trình khuyến nghị:

1. Backup trước khi migrate.
2. Deploy/pull image mới.
3. Chạy migrate bằng `site` setup.
4. Recreate/restart app containers nếu deploy tool chưa làm.
5. Kiểm tra `/crm`, `/login`, API chính và worker logs.

Nếu có compose file trên server:

```bash
docker compose -f docker/docker-compose.prod.yml --profile setup run --rm site
```

Nếu Dokploy chỉ pull/recreate container và bạn không dễ chạy compose profile, có thể chạy migrate trong backend container đang dùng image mới:

```bash
docker exec -it crm-crmdev-bgfanm-backend-1 bash -lc '
cd /home/frappe/frappe-bench &&
bench --site crm.beyond8.io.vn migrate &&
bench --site crm.beyond8.io.vn clear-cache
'
```

Thay `crm.beyond8.io.vn` bằng đúng `SITE_NAME` production nếu khác.

### Backup production trước migration

Chạy trong backend container:

```bash
docker exec -it crm-crmdev-bgfanm-backend-1 bash -lc '
cd /home/frappe/frappe-bench &&
bench --site crm.beyond8.io.vn backup --with-files
'
```

Backup sẽ nằm trong site backup folder bên trong volume `sites`. Với thay đổi lớn, nên copy backup ra ngoài server/volume trước khi tiếp tục.

### Viết patch production-safe

Patch production nằm trong:

```text
crm/patches/
crm/patches.txt
```

Nguyên tắc:

- patch phải idempotent, chạy lại không phá data
- kiểm tra field/table/record tồn tại trước khi sửa
- không xóa dữ liệu ngay nếu chưa có backup và chưa có bước chuyển đổi
- rename field/table nên có patch chuyển data trước
- backfill field mới nên để `[post_model_sync]`
- rename DocType/field cũ trước khi schema mới sync thì để `[pre_model_sync]`

Ví dụ patch an toàn:

```python
import frappe


def execute():
	if not frappe.db.exists("DocType", "CRM Lead"):
		return

	if not frappe.db.has_column("CRM Lead", "custom_source"):
		return

	frappe.db.sql("""
		update `tabCRM Lead`
		set custom_source = 'Unknown'
		where custom_source is null
	""")
```

Sau khi patch được deploy và migrate chạy thành công, Frappe sẽ ghi nhận patch đã chạy. Lần migrate sau patch đó không chạy lại theo cơ chế patch log của Frappe.

### Thứ tự nên làm khi thay đổi DB lớn

Với thay đổi lớn, nên chia làm nhiều deploy nhỏ:

1. Deploy thêm field/table mới, không xóa field cũ.
2. Chạy patch backfill/chuyển dữ liệu.
3. Cập nhật code đọc field mới.
4. Sau khi ổn định, deploy sau mới xóa field cũ nếu thật sự cần.

Cách này giảm rủi ro downtime và giúp rollback dễ hơn.

## 15. Env production

Template env nằm ở:

```text
docker/.env.example
```

Các biến chính:

```text
CRM_IMAGE=ngothanhdatak/crm-frappe:latest
SITE_NAME=crm.example.com
ADMIN_PASSWORD=change-me-admin
MYSQL_ROOT_PASSWORD=change-me-db-root
HTTP_PORT=8000
SOCKETIO_PORT=9000
GUNICORN_WORKERS=2
```

Ý nghĩa:

| Biến | Ý nghĩa |
|---|---|
| `CRM_IMAGE` | Image CRM production cần pull |
| `SITE_NAME` | Tên Frappe site |
| `ADMIN_PASSWORD` | Password admin khi tạo site lần đầu |
| `MYSQL_ROOT_PASSWORD` | Root password MariaDB |
| `HTTP_PORT` | Port publish ra host cho Nginx |
| `SOCKETIO_PORT` | Port socket.io nội bộ Frappe config |
| `GUNICORN_WORKERS` | Số Gunicorn workers |

Không commit secret thật vào repo.

## 16. Vì sao không phải FE/BE độc lập?

Dự án này khác kiểu:

```text
frontend repo -> build SPA -> deploy static hosting
backend repo  -> deploy API server
```

Ở đây:

```text
crm/ frontend/ docker/prod.Dockerfile
```

cùng đi vào một Frappe bench image.

Frappe backend serve page `/crm`, page này load Vue bundle từ `/assets/crm/frontend`. FE gọi API qua cùng domain:

```text
/api/method/...
```

Nginx là entry point duy nhất cho cả:

- static assets;
- Frappe pages;
- Frappe API;
- socket.io.

Vì vậy production deploy không tách riêng FE service. Vue app là static assets nằm trong Frappe app image.

## 17. Lệnh kiểm tra nhanh trên server

Xem containers:

```bash
docker ps
```

Xem logs backend:

```bash
docker logs -f crm-crmdev-bgfanm-backend-1
```

Xem logs Nginx:

```bash
docker logs -f crm-crmdev-bgfanm-nginx-1
```

Kiểm tra assets có được sync thành directory thật chưa:

```bash
docker exec -it crm-crmdev-bgfanm-nginx-1 sh -lc '
ls -ld /home/frappe/frappe-bench/sites/assets/crm
ls -ld /home/frappe/frappe-bench/sites/assets/frappe
'
```

Kết quả đúng là `drwx...`, không phải `lrwx...`.

Test asset CRM:

```bash
curl -I -H "Host: crm.beyond8.io.vn" \
http://127.0.0.1:8000/assets/crm/frontend/index.html
```

Test Frappe login CSS:

```bash
curl -I -H "Host: crm.beyond8.io.vn" \
http://127.0.0.1:8000/assets/frappe/dist/css/login.bundle.56NPG5HJ.css
```

Tên file hashed có thể thay đổi sau mỗi build. Nếu cần lấy danh sách asset thật mà trang đang gọi:

```bash
curl -s -H "Host: crm.beyond8.io.vn" http://127.0.0.1:8000/login \
| grep -Eo '(/assets/[^"]+\.(css|js)[^"]*)' \
| head -50
```

## 18. Khi lỗi thì nhìn ở đâu?

| Triệu chứng | Nơi kiểm tra |
|---|---|
| Nginx restart liên tục | `docker logs nginx`, kiểm tra Nginx config/mount |
| Trang HTML trần, không có CSS | `/assets/frappe/...` hoặc `/assets/crm/...` bị 404 |
| `/assets` 404 | Kiểm tra `sites/assets` trong Nginx container |
| API lỗi 500 | `docker logs backend` |
| Realtime không chạy | `docker logs websocket`, kiểm tra `/socket.io` |
| Job không chạy | `docker logs queue-short/default/long` |
| Scheduled job không tạo | `docker logs scheduler` |
| DB không lên | `docker logs mariadb`, volume `mariadb-data` |
| Redis lỗi | `docker logs redis-cache` hoặc `redis-queue` |

## 19. Những thứ không nên xóa bừa

Không xóa các volumes này nếu không hiểu rõ hậu quả:

```text
mariadb-data
sites
logs
```

Đặc biệt:

```text
mariadb-data
sites
```

là dữ liệu production quan trọng.

Container có thể recreate. Image có thể pull lại. Nhưng volume là nơi giữ data thật.
