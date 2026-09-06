# FAIP CRM — Agent Guidelines

## Phạm vi dự án

Đây là hệ thống CRM gồm hai repository độc lập:

- **Backend:** repository hiện tại `frappe-crm` — Frappe Framework/Python.
- **Frontend chính:** repository kế bên `../dashboard-crm` — Next.js/React/TypeScript.

Khi xử lý một tính năng full-stack, xem Frappe là nguồn sự thật cho dữ liệu, nghiệp vụ,
phân quyền và API; xem `dashboard-crm` là giao diện CRM chính.

Hai thư mục là hai Git repository riêng. Trước khi sửa code, kiểm tra `git status` ở cả
hai repository và không ghi đè hoặc đưa các thay đổi có sẵn của người dùng vào phạm vi
công việc.

## Nguyên tắc bắt buộc

- Luôn áp dụng **SOLID, DRY, KISS và YAGNI**.
- Ưu tiên thay đổi nhỏ, rõ ràng, có thể kiểm thử; không tạo abstraction hoặc dependency
  mới nếu chưa có nhu cầu thực tế.
- Không dùng sandbox window nếu không cần thiết; ưu tiên terminal, test tự động và kiểm
  tra trực tiếp trong codebase.
- Không hardcode secret, token, URL production hoặc dữ liệu cá nhân.
- Không dùng các lệnh reset/xóa dữ liệu như `task reset`, `task seed-fresh` hoặc thao tác
  tương đương nếu chưa được yêu cầu rõ ràng.

## Backend — `frappe-crm`

### Cấu trúc chính

- `crm/`: Frappe app, DocTypes, API, hooks, migration, fixture và translation.
- `crm/api/`: các endpoint/API tùy chỉnh.
- `crm/tests/`: server tests; `crm/demo/`: dữ liệu demo và contract tests.
- `frontend/`: Vue/Vite frontend được đóng gói cùng Frappe. Đây **không phải frontend
  CRM chính**; chỉ sửa khi task yêu cầu trực tiếp hoặc cần cho Frappe shell/tương thích.
- `docs/`: tài liệu backend và API; `scripts/`: tiện ích; `docker/`: môi trường chạy.

### Quy tắc backend

- Đặt business rule, validation, tính toán và permission ở backend; frontend chỉ chịu
  trách nhiệm hiển thị và tương tác.
- Tái sử dụng DocType, service và API hiện có trước khi tạo mới.
- Khi thay đổi dữ liệu, cập nhật DocType JSON/migration theo convention của Frappe; không
  sửa database thủ công để thay cho migration.
- API phải kiểm tra authentication/authorization, validate input và trả response ổn
  định, dễ dùng cho frontend.
- Khi thay đổi API contract, cập nhật tài liệu tương ứng trong `docs/` hoặc
  `../dashboard-crm/docs/api/`, đồng thời cân nhắc backward compatibility.
- Python dùng `snake_case`, double quotes, tối đa 110 ký tự mỗi dòng và format/lint bằng
  Ruff theo `pyproject.toml`.

## Frontend chính — `../dashboard-crm`

### Stack và cấu trúc

- Next.js 16 App Router, React 19, TypeScript, Tailwind CSS.
- `src/app/`: route, layout và page; route chính dùng các route group hiện có.
- `src/components/`: component dùng chung và design-system primitives.
- `src/services/api/`: API service theo từng feature, kèm type và test liên quan.
- `src/hooks/`, `src/types/`, `src/utils/`: hook, type và utility dùng chung.
- Chạy lệnh frontend từ repository `dashboard-crm`, không chạy nhầm trong
  `frappe-crm/frontend`.

### Quy tắc frontend

- Đọc `../dashboard-crm/AGENTS.md` và hướng dẫn trong thư mục feature trước khi sửa.
- Dùng App Router và cấu trúc route hiện có; không tự tạo layout hoặc thư mục song song.
- Tách component theo trách nhiệm đơn nhất; tránh page/component quá lớn và tránh prop
  drilling sâu.
- Dùng component trong `src/components/tailgrids/core/` trước khi tạo primitive mới.
- Dùng semantic tokens trong `src/app/globals.css`; không hardcode màu hex và không tạo
  CSS utility class mới nếu không thật sự cần.
- Giữ file ở kebab-case và component export ở PascalCase.
- API call phải đi qua `src/services/api/`; giữ type request/response rõ ràng, xử lý
  loading/error/empty state và không để mock data che khuất lỗi API thật.
- Không thêm state library hoặc package mới nếu chưa có lý do và chưa được chấp thuận.
- Giữ accessibility, keyboard navigation, focus state và responsive behavior khi sửa UI.

## Quy trình thay đổi full-stack

1. Xác định DocType, business rule, permission và API hiện có trong `frappe-crm`.
2. Xác định màn hình, service, type và design-system primitive tương ứng trong
   `../dashboard-crm`.
3. Nếu cần contract mới, thiết kế response/request trước; triển khai backend và test
   backend trước.
4. Cập nhật service/type/UI ở `dashboard-crm`; luôn có trạng thái loading, lỗi, rỗng và
   permission phù hợp.
5. Chạy test/lint/build liên quan ở cả repository bị ảnh hưởng.
6. Kiểm tra diff và `git status` riêng ở từng repository; commit tách biệt theo repository
   và dùng Conventional Commits.

Không mặc định sửa cả `frappe-crm/frontend` và `dashboard-crm` cho cùng một thay đổi.
Chỉ sửa UI Vue tích hợp nếu task nói rõ hoặc có bằng chứng kỹ thuật bắt buộc.

## Lệnh phát triển và kiểm thử

### Backend Frappe

```bash
task setup                 # lần đầu: khởi tạo stack và dependencies
task up                    # chạy Docker/Frappe
task down                  # dừng stack
task migrate               # migrate và validate DocType
task restart               # restart sau thay đổi backend
bench --site <site> run-tests --app crm
ruff check .
ruff format --check .
```

Backend local mặc định chạy tại `http://crm.localhost:8000/crm`.

### Frontend dashboard-crm

```bash
cd ../dashboard-crm
npm install                 # chỉ chạy khi dependencies thay đổi hoặc chưa cài
npm run dev                 # Next.js tại port 3000
npm run lint
npm test
npm run build
```

Không commit `node_modules`, `.env*`, credentials hoặc file sinh ra từ môi trường local.

## Kiểm thử

- Backend: thêm test tập trung cho business rule, API, validation và permission bị thay
  đổi.
- Frontend: thêm unit test cho service/utility/state; test flow UI quan trọng bằng
  Playwright khi có ảnh hưởng end-to-end.
- Tên Vitest backend/frontend theo convention hiện có; Playwright dùng `*.spec.ts`.
- Với thay đổi API, kiểm tra cả response thành công, lỗi validation, permission denied,
  dữ liệu rỗng và pagination/filter nếu có.
- Với thay đổi giao diện, kiểm tra desktop, mobile, dark mode và accessibility cơ bản.

## Git và bàn giao

- Giữ commit nhỏ, tập trung và dùng Conventional Commits, ví dụ
  `feat(api): add admission overview endpoint` hoặc `fix(dashboard): handle empty funnel`.
- PR phải mô tả behavior thay đổi, API/migration/config cần thiết, test đã chạy và
  screenshot/recording nếu có thay đổi UI.
- Trước khi bàn giao, nêu rõ file đã sửa, test đã chạy và các việc còn phụ thuộc vào
  repository còn lại.

<!-- hs-skills:begin -->
# HS Skills runtime instructions

Shared skills are installed in `.agents/skills/`. Follow the project AGENTS.md instructions
and use the installed skills when their descriptions match the task.
Runtime support files are in `.agents/`; do not assume Claude-specific tools, paths, or
environment variables are available.

<!-- hs-skills:end -->
