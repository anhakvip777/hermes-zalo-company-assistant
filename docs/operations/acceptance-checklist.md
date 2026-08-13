# Checklist nghiệm thu

Trạng thái bằng chứng ngày 2026-08-11: Node `34/34`, toàn bộ Python `166/166`,
integration `14/14`, acceptance `ok: true` và `git diff --check` exit `0`.
Production Admin Web đã đăng nhập thành công trên loopback; Tổng quan, Allowlist,
Hội thoại và Hệ thống/Hoạt động đã được đọc trực tiếp. Chỉ đánh dấu `[x]` cho
mục đã có bằng chứng tự động hoặc runtime; các thao tác mutation production vẫn
để trống cho tới khi người dùng cho phép chạy.

## Provenance, compatibility và policy

- [ ] Working tree sạch và HEAD có tag đúng `v<package.version>`.
- [x] Manifest builder pin Hermes Agent `0.19.0`, commit
  `eb52760564dbba2e5971fa54bd67384e281cd3b8` và hai contract
  `PlatformEntry.env_enablement_fn`, `MessageEvent.channel_context`.
- [x] CI checkout đúng Hermes commit và chạy plugin registration cùng toàn bộ
  Python/integration suite.
- [x] CI tag build ghi CI run ID/URL vào manifest và upload artifact/checksum.
- [x] Builder ngoài Git checkout dừng bằng thông báo thiếu Git provenance,
  không trả traceback Git thô.
- [x] Allowed member được đọc history của mọi `allowed_groups`, nhưng không đọc
  DM người khác, export/xóa history, đổi retention hoặc gọi quyền quản trị.

- [ ] Năm Zalo ID allowlist chat DM và nhận phản hồi Hermes.
- [ ] DM ngoài allowlist không tạo agent turn.
- [x] Message group allowlist được lưu dù không mention.
- [x] Group chỉ phản hồi khi allowed user mention bot.
- [ ] Mention từ người ngoài vẫn lưu nhưng không gọi Hermes.
- [ ] Hai DM có session/history riêng; group có một session chung.
- [ ] Context gọi Hermes có tối đa 100 message gần nhất.
- [ ] `zalo list`, `describe`, `call` dùng được method trong catalog và positional fallback.
- [ ] `getCookie`/`getContext`/credential bị ẩn, từ chối và redact.
- [ ] Media <=20 MiB được lưu; media lớn/stream vượt cap là metadata-only.
- [ ] Duplicate event không tạo message, media hoặc agent turn thứ hai.
- [ ] Admin add/remove user/admin, memory, history, QR/service hoạt động.
- [ ] Đăng nhập Admin Web qua HTTPS; cookie có `HttpOnly`, `Secure`, `SameSite=Strict`.
- [x] Tổng quan hiện đúng họ tên/Zalo ID bot, bạn bè và group kèm ID.
- [ ] `Group AI` hiện danh sách thành viên kèm ID.
- [ ] Lưu và áp dụng đồng thời user/admin/group; stale fingerprint trả `409`.
- [ ] History Web tìm kiếm, phân trang, tải attachment, export và xóa có xác nhận.
- [ ] QR trả `202` ngay khi login còn chờ; refresh ảnh không gửi lại `/relogin`.
- [ ] Reconnect/restart chỉ chạy một lần; bridge down không làm Admin UI biến mất.
- [x] Quét HTML/JavaScript, mọi JSON response, log gần nhất và `tool_activity`; không mục nào chứa token, cookie, password, bridge token hoặc API key.
- [ ] Non-admin không dùng `zalo_admin` và không ghi memory qua file/terminal/execute-code.
- [ ] SQLite/media/session còn nguyên sau restart; event đã lưu không replay Hermes.
- [x] `python scripts/acceptance.py --static --json` xác nhận continuity, manifest và checksum migration.
- [x] Mở phiên Codex mới và xác nhận agent đọc `AGENTS.md`, kiến trúc, database, manifest và checkpoint trước khi sửa.
- [x] `npm test`, `pytest`, integration, security smoke và `git diff --check` đều pass.
