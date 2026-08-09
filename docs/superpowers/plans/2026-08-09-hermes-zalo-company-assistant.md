# Trợ lý công ty Hermes trên Zalo - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (khuyến nghị) hoặc `superpowers:executing-plans` để thực hiện kế hoạch theo từng nhiệm vụ. Mỗi bước dùng checkbox `- [ ]`.

**Goal:** Biến fork `cuongdev/hermes-zalo-plugin@1.0.9` thành cầu nối một tài khoản Zalo công ty với Hermes Agent `0.19.0`, lưu đầy đủ hội thoại/media và cho thành viên allowlist dùng Hermes cùng toàn bộ method vận hành của `zca-js@2.1.2` ngay lập tức; admin có quyền quản trị cao hơn.

**Architecture:** Giữ Node `ZaloClient` làm lớp sở hữu phiên `zca-js` và bridge loopback token-authenticated. Python adapter ghi event vào SQLite trước mention gate, tạo DM/session routing, đăng ký `zalo`, `zalo_history`, `zalo_admin`, và dùng `ContextVar` + `pre_tool_call` để bảo vệ memory. Không có approval broker hay transport tối thiểu.

**Tech Stack:** Node.js 22, Express 4, `zca-js@2.1.2`, `node:test`, Python 3.11, Hermes Agent 0.19.0, `aiohttp`, SQLite, `pytest`, systemd.

---

## Tài liệu đã khóa trước code

- `docs/architecture/system-overview.md`
- `docs/architecture/database-schema.md`
- `docs/architecture/file-manifest.md`

Không đổi ba tài liệu trên để mở lại approval-heavy design, thu gọn zca-js hoặc đổi schema. Nếu phát hiện yêu cầu cần đổi kiến trúc/schema, dừng tại checkpoint và xin duyệt lại.

## Nhiệm vụ 1: Test harness và migration schema

**Files:**

- Tạo: `hermes-plugin/migrations/001_initial.sql`
- Tạo: `tests/python/conftest.py`, `tests/python/test_history_store.py`
- Tạo: `pyproject.toml`, `requirements-test.txt`
- Sửa: `package.json`, `package-lock.json`, `.gitignore`, `.npmignore`

- [ ] Viết test RED kiểm tra sáu bảng, foreign keys, unique dedupe và migration checksum.
- [ ] Chạy `python -m pytest tests/python/test_history_store.py -q`; xác nhận fail vì migration/module chưa tồn tại.
- [ ] Viết `001_initial.sql` đúng bảng/constraint trong `database-schema.md`, gồm trigger chặn UPDATE/DELETE trên `tool_activity` nếu cần append-only metadata.
- [ ] Cài `HistoryStore.apply_migrations()` chạy script theo version, SHA-256 checksum và transaction.
- [ ] Thêm script Node `test` dùng `node --test \"test/**/*.test.js\"`; thêm script Python trong `pyproject.toml`.
- [ ] Chạy lại test migration và `git diff --check`; commit checkpoint C1.

## Nhiệm vụ 2: Bridge config, auth, SSE và catalog

**Files:**

- Tạo: `bridge/config.js`, `bridge/auth.js`, `bridge/redaction.js`, `bridge/event-buffer.js`, `bridge/method-catalog.js`, `bridge/app.js`
- Tạo: `test/config.test.js`, `test/auth.test.js`, `test/event-buffer.test.js`, `test/method-catalog.test.js`, `test/app.test.js`, `test/helpers/fake-zalo-client.js`
- Sửa: `server.js`, `zaloClient.js`, `permissions.js`, `paths.js`

- [ ] Viết test RED: config thiếu token/host ngoài loopback bị từ chối; mọi route thiếu Bearer trả 401; SSE replay theo `Last-Event-ID`; catalog có `sendMessage`, `createPoll` và ẩn `getCookie/getContext`.
- [ ] Chạy từng test bằng `node --test test/config.test.js` và xác nhận fail vì module/app factory chưa có.
- [ ] Cài `loadConfig(env)` với token tối thiểu 32 ký tự, host cố định `127.0.0.1`, port hợp lệ và path state.
- [ ] Cài `requireBridgeAuth` so sánh constant-time, nhận `Authorization: Bearer`; không đọc query token. Áp dụng trước route `/health`, `/events`, `/qr`, lifecycle và API.
- [ ] Cài `EventBuffer` ring 200 record, heartbeat, replay từ cursor và bỏ cursor quá cũ theo chuẩn SSE.
- [ ] Cài `MethodCatalog` đọc `node_modules/zca-js/dist/apis/*.d.ts` + signature runtime, gắn nhóm từ `permissions.js`, schema chung positional và schema tên cho method phổ biến. `list/describe` không trả raw source/credential.
- [ ] Cài `redactSecrets(value)` đệ quy theo key/value (`cookie`, `token`, `password`, `apiKey`, `secret`, `imei`, `authorization`) trước JSON response và log.
- [ ] Chuyển route hiện có vào `createBridgeApp({client, config})`; giữ route tiện dụng và `POST /api/:method`, thêm `GET /api/methods`/`:method`. `callRaw` chỉ gọi method tồn tại, chuyển `\"user\"`/`\"group\"` thành `ThreadType`, chặn method secret.
- [ ] Sửa `server.js` chỉ khởi động khi được chạy trực tiếp, đăng ký event qua `EventBuffer`, không log nội dung/credential thô.
- [ ] Chạy toàn bộ Node tests, `node --check` và `npm pack --dry-run`; commit C2.

## Nhiệm vụ 3: History Store và media policy

**Files:**

- Tạo: `hermes-plugin/media_policy.py`, `tests/python/test_media_policy.py`
- Sửa: `hermes-plugin/history_store.py` (tạo ở Nhiệm vụ 1 nếu chưa có), `paths.js`

- [ ] Viết RED cho insert trùng, group message không mention, context 100, search/recent/get_message/get_attachment và export/delete.
- [ ] Chạy pytest để quan sát đúng failure.
- [ ] Cài `upsert_conversation`, `insert_message`, `insert_event`, `insert_attachment`, `recent_messages`, `search_messages`, `export_history`, `delete_history`, `stats` với transaction và dedupe no-op.
- [ ] Cài `MediaPolicy` nhận normalized attachment; filename chỉ giữ chữ/số/`._-`, path theo `history/media/<type>/<id>/<date>`; size đã biết >20 MiB là metadata-only.
- [ ] Với size chưa biết, đọc stream từng chunk, dừng ngay khi tổng vượt cap; lỗi download cập nhật `failed` nhưng không rollback message.
- [ ] Hash SHA-256 và unique `(message_id, attachment_index)` để duplicate không tải lại.
- [ ] Chạy test media/history, kiểm tra file permissions và restart store trên cùng DB.

## Nhiệm vụ 4: Company config, requester context và adapter routing

**Files:**

- Tạo: `hermes-plugin/company_config.py`, `hermes-plugin/request_context.py`, `tests/python/test_company_config.py`, `tests/python/test_request_context.py`, `tests/python/test_adapter.py`
- Sửa: `hermes-plugin/adapter.py`, `hermes-plugin/plugin.yaml`, `hermes-plugin/__init__.py`

- [ ] Viết RED cho config fail-closed, admin subset, group mode mention, group lưu trước gate, DM tách session, group dùng session chung và người ngoài allowlist.
- [ ] Chạy pytest và ghi nhận failure trước implementation.
- [ ] Cài `CompanyConfig.from_platform_extra()` với `allowed_users`, `admin_users`, `allowed_groups`, `group_mode=mention`, cap/context/retention; env override không được tạo allow-all ngoài ý muốn.
- [ ] Cài `request_context` bằng `ContextVar[Requester]`, context manager `bind_requester()` và `current_requester()` fail-closed khi không có context.
- [ ] Trong `_on_inbound_message`, phân loại event; group thuộc allowlist luôn gọi `store_message`/media metadata trước mention check. DM ngoài allowlist không lưu và không gọi Hermes.
- [ ] Sau store thành công, group chỉ gọi Hermes khi sender allowlist + mention; DM allowlist gọi Hermes. Dedupe trả về trước khi tạo `MessageEvent`.
- [ ] Tạo session source DM/group đúng và định dạng context 100 message gần nhất trong `MessageEvent.text` hoặc hook pre-dispatch; không nhúng binary.
- [ ] Bind `Requester` bằng context manager bao quanh `handle_message(event)`; ghi inbound/outbound message và tool activity.
- [ ] Gửi media qua route buffer an toàn, timeout trả `unknown` và không retry; ghi outbound message sau provider response.
- [ ] Đặt `group_sessions_per_user: false` trong tài liệu/config migration; chạy adapter tests.

## Nhiệm vụ 5: Tool surface, admin guard và memory

**Files:**

- Tạo: `hermes-plugin/tooling.py`, `hermes-plugin/admin.py`, `tests/python/test_tooling.py`
- Sửa: `hermes-plugin/adapter.py`, `hermes-plugin/plugin.yaml`, `hermes-plugin/__init__.py`

- [ ] Viết RED: member gọi `zalo(list|describe|call)` được; `zalo_history` chỉ thấy DM của mình/group allowlist; non-admin `zalo_admin` bị từ chối; admin mutation chạy ngay; non-admin memory qua `memory`, `write_file`, `patch`, `terminal`, `execute_code` bị block.
- [ ] Chạy pytest để xác nhận RED.
- [ ] Đăng ký tool qua `ctx.register_tool(name, toolset, schema, handler, is_async=True)`; handler không nhận `requester_id` tin từ model, chỉ dùng `current_requester()`.
- [ ] `zalo` gọi `/api/methods`, `/api/methods/:method`, `/api/:method`; `params` chuyển theo catalog, `args` là fallback; mọi response chạy redaction và `HistoryStore.log_tool_activity`.
- [ ] `zalo_history` triển khai `recent`, `search`, `get_message`, `get_attachment`; member scope là session DM cá nhân hoặc group allowlist, admin scope toàn công ty.
- [ ] `zalo_admin` triển khai `status`, allowlist/admin, memory add/update/delete, history export/delete, login_qr, start/stop/restart, show_logs; mọi action kiểm tra `is_admin`, cấm xóa admin cuối.
- [ ] Hook `pre_gateway_dispatch` lưu/bind context; hook `pre_tool_call` phân tích args/path/code để chặn non-admin đụng `MEMORY.md`, `USER.md` hoặc thư mục memory. Hook `post_tool_call` log trạng thái đã redact.
- [ ] Cấu hình `approvals.mode: off` chỉ là migration vận hành đã được người dùng chốt; plugin không tạo approval code/broker.
- [ ] Chạy test tooling/adapter và kiểm tra tool schemas với Hermes Agent 0.19.0.

## Nhiệm vụ 6: Đóng gói và vận hành

**Files:**

- Tạo: `systemd/hermes-zalo-company-bridge.service`, `systemd/hermes-gateway.service`, `systemd/hermes-zalo-company.env.example`, `scripts/migrate-v1.0.9-config.mjs`, `tests/integration/fake_bridge.py`, `tests/integration/test_company_assistant_flow.py`, `tests/integration/test_restart.py`
- Sửa: `package.json`, `package-lock.json`, `install.mjs`, `install.sh`, `uninstall.mjs`, `login.mjs`, `bin/cli.mjs`, `README.md`, `README.vi.md`, `.github/workflows/ci.yml`, `.gitignore`, `.npmignore`

- [ ] Viết integration RED cho DM/group/tool/restart trên fake bridge.
- [ ] Cài migration config 1.0.9 idempotent: map env cũ sang `gateway.platforms.zalo.extra`, không copy secret vào YAML.
- [ ] Cập nhật install/CLI/systemd dùng data dir `0700`, env file `0600`, Node 22/Python 3.11; service bridge chạy trước gateway.
- [ ] Cập nhật README tiếng Việt với allowlist, group lưu không mention, memory admin-only, QR và rủi ro unofficial API.
- [ ] Chạy integration và kiểm tra package bằng `npm pack --dry-run`.

## Nhiệm vụ 7: Nghiệm thu và review

- [ ] Chạy `npm test` và đọc đủ output; không dùng exit code cuối của chuỗi lệnh để che failure.
- [ ] Chạy `python -m pytest -q`, integration, restart, `npm audit --omit=dev --json`, `npm pack --dry-run`, `git diff --check`.
- [ ] Chạy `python scripts/acceptance.py --json` và đối chiếu `docs/operations/acceptance-checklist.md` từng dòng.
- [ ] Dùng GitNexus `status`, `context` cho `ZaloClient`, `ZaloAdapter`, `createBridgeApp` và `HistoryStore` để kiểm tra call path sau thay đổi.
- [ ] Kiểm tra `git status --short`; mọi file thay đổi phải có trong `docs/architecture/file-manifest.md`.
- [ ] Nếu một test fail, viết regression test trước khi sửa; chỉ báo hoàn tất sau khi có output mới với exit code 0 và checklist đủ.

## Điều kiện dừng

Dừng và xin duyệt lại nếu cần đổi `system-overview.md`, `database-schema.md`, `file-manifest.md`, thêm approval broker, thu gọn bề mặt `zca-js`, hoặc tạo file ngoài manifest. Các lỗi dependency/test có thể sửa trong phạm vi file đã khóa; không tự mở rộng kiến trúc.
