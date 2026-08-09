# Checklist nghiệm thu

- [ ] Năm Zalo ID allowlist chat DM và nhận phản hồi Hermes.
- [ ] DM ngoài allowlist không tạo agent turn.
- [ ] Message group allowlist được lưu dù không mention.
- [ ] Group chỉ phản hồi khi allowed user mention bot.
- [ ] Mention từ người ngoài vẫn lưu nhưng không gọi Hermes.
- [ ] Hai DM có session/history riêng; group có một session chung.
- [ ] Context gọi Hermes có tối đa 100 message gần nhất.
- [ ] `zalo list`, `describe`, `call` dùng được method trong catalog và positional fallback.
- [ ] `getCookie`/`getContext`/credential bị ẩn, từ chối và redact.
- [ ] Media <=20 MiB được lưu; media lớn/stream vượt cap là metadata-only.
- [ ] Duplicate event không tạo message, media hoặc agent turn thứ hai.
- [ ] Admin add/remove user/admin, memory, history, QR/service hoạt động.
- [ ] Non-admin không dùng `zalo_admin` và không ghi memory qua file/terminal/execute-code.
- [ ] SQLite/media/session còn nguyên sau restart; event đã lưu không replay Hermes.
- [ ] `npm test`, `pytest`, integration, security smoke và `git diff --check` đều pass.
