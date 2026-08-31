# Local dev

Backend chạy trong **Docker** (`:8000`). Frontend chạy trên máy bằng **Vite** (`:5000`).

```
http://crm.localhost:5000/crm     ← dev hàng ngày
Administrator / admin             ← login mặc định
```

---

## Yêu cầu

- Docker Desktop
- [Task](https://taskfile.dev/installation/)
- Node.js 20+
- Yarn 1.x

Thêm vào **hosts** (`/etc/hosts` hoặc `C:\Windows\System32\drivers\etc\hosts`):

```text
127.0.0.1 crm.localhost
```

Xem tất cả lệnh: `task` hoặc `task --list`

---

## Người mới — clone lần đầu

**Terminal 1** — backend (lần đầu ~10–20 phút):

```bash
git clone <url-repo>
cd crm-1.72.0
task setup
task logs          # đợi bench start xong
```

**Terminal 2** — frontend:

```bash
task fe
```

Mở `http://crm.localhost:5000/crm`

`task setup` = bật Docker + cài frontend deps. Container tự tạo bench, site `crm.localhost`, cài app CRM, migrate **và seed bộ dữ liệu demo** (lần đầu). School domain có 10 trường cho mỗi tỉnh trong danh sách demo (7 tỉnh / 70 trường nguồn chuẩn); Market Intelligence dùng annual school snapshots cho application/enrollment/conversion, còn `opportunity`, `potentialScore` và các chỉ số grade-12 vẫn `unavailable` cho tới khi có nguồn được xác minh. Đặt `CRM_SEED_DEMO=0` trong `docker/.env` nếu muốn site rỗng.

Seed lại thủ công: `task seed` (giữ site, chọn 10 trường cho mỗi tỉnh trong danh sách demo) hoặc `task seed-fresh` (reinstall + migrate + seed). Trường nguồn cũ đang được Student/Contact tham chiếu sẽ được giữ lại khi prune để tránh orphan.
Chỉ làm gọn school domain local: `task seed-school-domain-demo`. Lệnh này xóa các business rows do showcase tạo (giữ audit/receipt append-only), rồi prune và seed lại school domain.

---

## Hàng ngày

```bash
task up      # terminal 1 — backend
task fe      # terminal 2 — frontend
```

Backend đã chạy sẵn → chỉ cần `task fe`.

Dừng backend: `task down`  
Xem log: `task logs`

---

## Sau `git pull`

```bash
git pull
task pull
```

`task pull` = deps + migrate + clear cache + restart backend + **seed lại demo data** (idempotent, không reinstall).

Không muốn seed lại: `task pull-fast`. Biết chính xác đổi gì thì chạy riêng (xem bảng dưới).

---

## Sửa code thì chạy gì?

| Đổi gì                           | Lệnh                            |
| -------------------------------- | ------------------------------- |
| Vue / JS / CSS (`frontend/src/`) | Không cần — Vite tự reload      |
| `yarn.lock` / thêm package FE    | `task deps`                     |
| Python API, logic BE (`crm/`)    | F5 — chưa ăn thì `task restart` |
| DocType JSON, patch, `hooks.py`  | `task migrate` → `task restart` |
| Dockerfile / compose dev         | `task rebuild`                  |

Quy tắc nhanh:

```
FE  → save file
BE  → restart
DB  → migrate
```

---

## URL

|             |                                            |
| ----------- | ------------------------------------------ |
| CRM dev     | `http://crm.localhost:5000/crm`            |
| Frappe Desk | `http://crm.localhost:8000/app`            |
| API         | `http://crm.localhost:8000/api/method/...` |

Luôn dùng host **`crm.localhost`**. Không mix `localhost:8000` với `crm.localhost:5000` — cookie/session sẽ lệch.

---

## Thư mục code

```
frontend/src/     Vue UI
crm/api/          API Python (@frappe.whitelist)
crm/fcrm/doctype/ DocType JSON
```

FE gọi BE qua dotted path, không hard-code `localhost:8000`:

```js
import {call} from 'frappe-ui'
await call('crm.api.example.ping', {name: 'Dat'})
```

---

## Khi gặp lỗi

| Vấn đề                      | Thử                          |
| --------------------------- | ---------------------------- |
| Backend chưa lên            | `task logs` — đợi init xong  |
| BE không nhận code mới      | `task restart`               |
| Desk thiếu nav / schema lỗi | `task migrate`               |
| Docker đổi mà container cũ  | `task rebuild`               |
| Muốn reset sạch DB local    | `task reset` ⚠️ mất hết data |

Lệnh bench khác:

```bash
task bench -- --site crm.localhost console
task shell
```

### Windows

- Chạy terminal bằng Git Bash hoặc PowerShell
- Có thể dùng `yarn dev` thay `task fe`
- Cảnh báo `Local frappe-ui vite plugin not found` là bình thường
- Port 5000 bận: `$env:VITE_PORT=5001` rồi mở `:5001/crm`
