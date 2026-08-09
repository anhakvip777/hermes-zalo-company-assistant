# Cấu hình vận hành

## Hermes `config.yaml`

```yaml
gateway:
  group_sessions_per_user: false
  platforms:
    zalo:
      enabled: true
      extra:
        bridge_url: http://127.0.0.1:8787
        allowed_users: ["zalo-id-1", "zalo-id-2"]
        admin_users: ["zalo-id-1"]
        allowed_groups: ["group-id-1"]
        group_mode: mention
        history_context_messages: 100
        media_max_bytes: 20971520
        history_retention: forever
``

Bridge token, cookie/session và API key nằm trong env/secret file, không đặt trong YAML chat context:

```text
ZALO_PLUGIN_TOKEN=<random-at-least-32-bytes>
ZALO_DATA_DIR=/var/lib/hermes-zalo
ZALO_PLUGIN_HOST=127.0.0.1
ZALO_PLUGIN_PORT=8787
ZALO_DB_PATH=/var/lib/hermes-zalo/history/conversations.sqlite3
``

Để mọi thành viên dùng tool Hermes không cần approval prompt, đặt `approvals.mode: off` trong cấu hình Hermes. Admin Guard của plugin vẫn chặn non-admin ghi `MEMORY.md`/`USER.md` qua mọi tool.

## Startup checks

Startup fail nếu token thiếu/ngắn, không có admin, admin nằm ngoài allowlist, database không migrate được hoặc bridge bind ngoài loopback. Sau khi đổi allowlist bằng `zalo_admin`, adapter cập nhật bản sao trong memory ngay; restart service vẫn đọc lại YAML.

## QR và service

Chạy `hermes-zalo-plugin login` trên terminal có quyền truy cập QR. Chat chỉ nhận trạng thái đã redact; không gửi cookie/context/QR secret qua Zalo. systemd chạy Node trước Hermes gateway, cả hai dùng cùng Unix user và thư mục state `0700`.
