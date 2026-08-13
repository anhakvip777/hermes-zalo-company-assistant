# File manifest triển khai

Đây là sổ đăng ký bắt buộc. Trước khi tạo, sửa hoặc xóa file, thêm/đổi dòng ở đây trong cùng thay đổi. Không tạo file ngoài danh sách nếu chưa có quyết định kiến trúc mới.

## File tạo mới

| File | Trách nhiệm |
|---|---|
| `AGENTS.md` | Điểm vào khôi phục context sau compact/phiên mới; bắt buộc đọc kiến trúc, schema, manifest và checkpoint |
| `docs/architecture/system-overview.md` | Kiến trúc, trust boundary, data flow |
| `docs/architecture/database-schema.md` | Schema, invariant, migration |
| `docs/architecture/file-manifest.md` | Sổ file và checkpoint |
| `docs/operations/configuration.md` | Cấu hình, secret, allowlist, QR |
| `docs/operations/acceptance-checklist.md` | Checklist nghiệm thu |
| `docs/superpowers/specs/2026-08-10-hermes-zalo-admin-web-ui-design.md` | Thiết kế Admin Web UI nhúng trong Hermes Zalo plugin |
| `docs/superpowers/plans/2026-08-10-hermes-zalo-admin-web-ui.md` | Kế hoạch triển khai Admin Web UI theo TDD |
| `docs/superpowers/specs/2026-08-09-hermes-zalo-company-assistant-design.md` | Spec trợ lý công ty Hermes trên Zalo |
| `docs/superpowers/plans/2026-08-09-hermes-zalo-company-assistant.md` | Kế hoạch triển khai trợ lý công ty Hermes trên Zalo |
| `bridge/config.js` | Đọc/validate bridge config |
| `bridge/auth.js` | Bearer-token middleware |
| `bridge/redaction.js` | Redact secret đệ quy |
| `bridge/event-buffer.js` | SSE ring buffer và replay cursor |
| `bridge/method-catalog.js` | Catalog list/describe và named-to-positional mapping |
| `bridge/app.js` | Express app factory và route contract |
| `hermes-plugin/company_config.py` | Load/validate/atomic update config công ty |
| `hermes-plugin/request_context.py` | ContextVar requester cho một agent turn |
| `hermes-plugin/history_store.py` | SQLite migration, message/event/tool CRUD |
| `hermes-plugin/media_policy.py` | Download cap, sanitize filename, media paths |
| `hermes-plugin/tooling.py` | Tool handlers `zalo`, `zalo_history`, `zalo_admin` |
| `hermes-plugin/admin.py` | Admin actions và service control |
| `hermes-plugin/migrations/001_initial.sql` | Schema migration đầu tiên |
| `test/helpers/fake-zalo-client.js` | Fake client cho Node contract tests |
| `test/config.test.js` | Config/token/loopback tests |
| `test/auth.test.js` | Auth trên mọi route |
| `test/event-buffer.test.js` | SSE replay/cap tests |
| `test/method-catalog.test.js` | Catalog zca-js 2.1.2 |
| `test/app.test.js` | Route allow/deny và redaction |
| `tests/python/conftest.py` | Hermes stubs, temp home, fixtures |
| `tests/python/test_company_config.py` | Config và invariant admin |
| `tests/python/test_history_store.py` | Migration, dedupe, transaction, search |
| `tests/python/test_media_policy.py` | Media cap/download/failure |
| `tests/python/test_request_context.py` | ContextVar isolation |
| `tests/python/test_tooling.py` | Tool schema, role và redaction |
| `tests/python/test_adapter.py` | DM/group/mention/session/outbound |
| `tests/integration/fake_bridge.py` | Fake HTTP/SSE bridge |
| `tests/integration/test_company_assistant_flow.py` | End-to-end company flows |
| `tests/integration/test_restart.py` | Restart/dedupe persistence |
| `pyproject.toml` | Pytest configuration |
| `requirements-test.txt` | Test dependencies |
| `requirements-runtime.txt` | Python runtime dependencies được pin riêng khỏi test |
| `npm-shrinkwrap.json` | Lock dependency tái lập được bên trong runtime npm package |
| `systemd/hermes-zalo-company-bridge.service` | Node service |
| `systemd/hermes-gateway.service` | Hermes service |
| `systemd/hermes-zalo-company.env.example` | Secret/environment template |
| `scripts/migrate-v1.0.9-config.mjs` | Import config cũ idempotent |
| `scripts/acceptance.py` | Acceptance runner |
| `scripts/run-node-tests.mjs` | Chạy Node tests và fail nếu test count bằng 0 |
| `scripts/build-release.mjs` | Tạo runtime package, source/audit bundle và manifest checksum/traceability |

## File sửa

| File | Phạm vi sửa |
|---|---|
| `package.json` | Private fork, scripts test, pin Node/dependency |
| `package-lock.json` | Lock dependency |
| `server.js` | Dùng app factory, bắt buộc token/loopback, lifecycle |
| `zaloClient.js` | Event normalization, live zca surface, secret-safe logging |
| `paths.js` | Database/history/media paths và permissions |
| `login.mjs` | QR flow không lộ secret |
| `install.mjs` | Cài plugin/config/systemd |
| `install.sh` | Cài Linux |
| `uninstall.mjs` | Gỡ service có phạm vi |
| `bin/cli.mjs` | status/doctor/migrate/enable |
| `hermes-plugin/adapter.py` | Store-first routing, context, tools, media, delivery |
| `hermes-plugin/plugin.yaml` | Tool/hook manifest và config mới |
| `hermes-plugin/__init__.py` | Export plugin |
| `permissions.js` | Catalog nhóm và secret denylist, không gate manage/destructive |
| `README.md` | Tài liệu tiếng Anh vận hành |
| `README.vi.md` | Tài liệu tiếng Việt vận hành |
| `.github/workflows/ci.yml` | Node/Python/integration/security checks |
| `.github/workflows/publish.yml` | Npm publish thủ công; không tự chạy theo tag của fork nội bộ |
| `.gitignore` | DB, media, credential, QR, cache |
| `.npmignore` | Loại state/secret/test khỏi package |

## File không xóa

Không xóa file baseline nào trong phiên bản này. `permissions.js` được giữ làm metadata catalog; policy action cũ được bỏ qua để mọi thành viên dùng toàn bộ method vận hành.

## Checkpoint

- `C0`: ba tài liệu kiến trúc và migration schema được tạo trước code nghiệp vụ.
- `C1`: test harness chạy được và migration pass.
- `C2`: bridge contract pass, không route thiếu auth.
- `C3`: history/media pass store-first/dedupe.
- `C4`: adapter/tools/admin pass role/session.
- `C5`: packaging/systemd/acceptance pass.

Mỗi checkpoint phải kiểm tra `git status`, đối chiếu mọi path thay đổi với bảng này và chạy `git diff --check`.
