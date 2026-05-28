# Hướng dẫn Docker production

Production không chạy Vite và không dùng `task fe`.

Production chạy bằng Docker image được build từ source code hiện tại. Mỗi lần có code mới, build lại image, migrate site, rồi restart services.

## 1. Các service production

File chính:

```text
docker/docker-compose.prod.yml
```

Production stack gồm:

| Service | Vai trò |
|---|---|
| `mariadb` | Database |
| `redis-cache` | Redis cache |
| `redis-queue` | Redis queue + realtime |
| `site` | One-shot service để tạo site/migrate/build assets |
| `backend` | Gunicorn chạy Frappe web/API |
| `websocket` | Socket.IO realtime |
| `queue-short` | Worker queue short |
| `queue-default` | Worker queue default |
| `queue-long` | Worker queue long |
| `scheduler` | Scheduled jobs |

Image production được build từ:

```text
docker/prod.Dockerfile
```

Script tạo/migrate site:

```text
docker/prod-site.sh
```

## 2. Chuẩn bị server lần đầu

Trên server cần có:

- Docker
- Docker Compose plugin
- domain trỏ về server
- reverse proxy/SSL bên ngoài nếu muốn dùng HTTPS

Copy file env mẫu:

```bash
cp docker/.env.example docker/.env
```

Sửa `docker/.env`:

```env
CRM_IMAGE=crm-frappe:prod
SITE_NAME=crm.example.com
ADMIN_PASSWORD=change-me-admin
MYSQL_ROOT_PASSWORD=change-me-db-root
HTTP_PORT=8000
SOCKETIO_PORT=9000
GUNICORN_WORKERS=2
```

Đổi `SITE_NAME` thành domain thật, ví dụ:

```env
SITE_NAME=crm.your-domain.com
```

## 3. Deploy lần đầu

Build image:

```bash
task prod-build
```

Tạo site hoặc migrate site:

```bash
task prod-init
```

Start production services:

```bash
task prod-up
```

Mở:

```text
http://crm.your-domain.com:8000
```

Nếu có reverse proxy như Nginx/Caddy/Traefik, proxy domain HTTPS vào:

```text
backend:8000
websocket:9000
```

## 4. Mỗi lần có code mới

Trên server:

```bash
git pull
task prod-update
```

`task prod-update` sẽ làm 3 việc:

```text
1. build lại production image
2. chạy migrate/build assets bằng service site
3. restart production services
```

Đây là flow dùng cho cả FE, BE và DocType.

## 5. Nếu chỉ muốn chạy từng bước

Build image:

```bash
task prod-build
```

Migrate/build assets:

```bash
task prod-init
```

Restart services:

```bash
task prod-up
```

Xem logs:

```bash
task prod-logs
```

Stop production:

```bash
task prod-down
```

## 6. Tóm tắt cực ngắn

Lần đầu:

```bash
cp docker/.env.example docker/.env
# sửa docker/.env
task prod-build
task prod-init
task prod-up
```

Mỗi lần update code:

```bash
git pull
task prod-update
```

Không chạy:

```bash
task fe
```

trên production.
