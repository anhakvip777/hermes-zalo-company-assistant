# Cấu hình vận hành

## Phiên bản Hermes bắt buộc

Official release `1.1.3` được kiểm thử với Hermes Agent `0.19.0` tại commit
`eb52760564dbba2e5971fa54bd67384e281cd3b8`. Không chỉ đối chiếu chuỗi version:
runtime phải có `PlatformEntry.env_enablement_fn` và
`MessageEvent.channel_context`. Trước triển khai, kiểm tra `hermes --version`
và commit checkout Hermes; CI dùng đúng commit này làm compatibility gate.

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
        history_retention: "90"
```

Bridge token, cookie/session và API key nằm trong env/secret file, không đặt trong YAML chat context:

```text
ZALO_PLUGIN_TOKEN=<random-at-least-32-bytes>
ZALO_DATA_DIR=/var/lib/hermes-zalo
ZALO_PLUGIN_HOST=127.0.0.1
ZALO_PLUGIN_PORT=8787
ZALO_DB_PATH=/var/lib/hermes-zalo/history/conversations.sqlite3
```

## Admin Web UI nhúng trong plugin

Admin UI chạy trong cùng process với Hermes Gateway, chỉ listen trên loopback.
Không có Admin service, database hoặc migration riêng.

```text
ZALO_ADMIN_WEB_ENABLED=true
ZALO_ADMIN_WEB_HOST=127.0.0.1
ZALO_ADMIN_WEB_PORT=8790
ZALO_ADMIN_WEB_PASSWORD_HASH=<scrypt-hash>
ZALO_ADMIN_WEB_SESSION_SECRET=<random-at-least-32-utf8-bytes>
ZALO_ADMIN_WEB_SESSION_TTL_SECONDS=86400
```

Tạo hash mà không ghi mật khẩu vào command history trên PowerShell. Lệnh dùng
đường dẫn tuyệt đối của bản plugin đã cài, nên chạy được dù prompt đang ở
`C:\Users\<tên>`:

```powershell
$secure = Read-Host "Mật khẩu Admin Web" -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
$plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
$env:ADMIN_WEB_PASSWORD = $plain
$pluginPath = Join-Path $env:LOCALAPPDATA "hermes\plugins\zalo"
python -c "import os,sys; sys.path.insert(0,sys.argv[1]); from admin import hash_admin_password; print(hash_admin_password(os.environ['ADMIN_WEB_PASSWORD']))" $pluginPath
Remove-Item Env:ADMIN_WEB_PASSWORD
[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
Remove-Variable plain -ErrorAction SilentlyContinue
```

Tạo session secret 32 byte bằng API có sẵn của Windows, không cần OpenSSL:

```powershell
$bytes = New-Object byte[] 32
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
-join ($bytes | ForEach-Object { $_.ToString("x2") })
```

Cookie có cờ `Secure`, vì vậy production phải đi qua HTTPS. Ví dụ Caddy:

```caddyfile
zalo-admin.example.com {
    reverse_proxy 127.0.0.1:8790
}
```

Trình duyệt chỉ gọi `/admin/`; bridge token và credential provider không đi tới
browser. UI cho phép xem bot/bạn bè/nhóm/thành viên, Lưu và áp dụng ba allowlist,
xem/xuất/xóa history, QR/reconnect, activity và log đã redact.
Web UI không cho sửa provider endpoint, model credential, API key hoặc provider
secret; tên provider và model chỉ được hiển thị để chẩn đoán.

Nếu allowlist cũ mới chỉ nằm trong `.env`, migrate một lần sang nguồn chuẩn
`config.yaml` trước khi mở tab **Danh bạ & Allowlist**:

```powershell
node E:\plugin\scripts\migrate-v1.0.9-config.mjs --config "$env:LOCALAPPDATA\hermes\config.yaml" --env-file "$env:LOCALAPPDATA\hermes\.env"
```

Không giữ một bản backup còn tên `plugin.yaml` bên dưới
`HERMES_HOME/plugins/<thư-mục-backup>`: Hermes sẽ discovery cả bản backup và có
thể ghi đè factory của plugin chính. Di chuyển backup ra ngoài `plugins`, hoặc
đổi riêng manifest thành `plugin.yaml.disabled`.

Chỉ đặt `approvals.mode: off` trong profile Zalo cô lập chạy bằng user OS riêng;
không áp dụng cho Hermes profile dùng chung. Installer không tự sửa approval.
Admin Guard vẫn chặn non-admin ghi `MEMORY.md`/`USER.md` qua mọi tool.

## Startup checks

Startup fail nếu token thiếu/ngắn, không có admin, admin nằm ngoài allowlist, database không migrate được hoặc bridge bind ngoài loopback. Sau khi đổi allowlist bằng `zalo_admin`, adapter cập nhật bản sao trong memory ngay; restart service vẫn đọc lại YAML.

## QR và service

Chạy `hermes-zalo-plugin login` trên terminal có quyền truy cập QR. Chat chỉ nhận trạng thái đã redact; không gửi cookie/context/QR secret qua Zalo. systemd chạy Node trước Hermes gateway, cả hai dùng cùng Unix user và thư mục state `0700`.

Khi Admin UI đã chạy, adapter được giữ trong Gateway nếu bridge tạm mất hoặc
Zalo cần quét lại QR, để admin vẫn mở được trang recovery. Nếu chính Gateway
chết thì UI cũng chết; cold-start bằng `systemctl restart hermes-gateway` qua
SSH/console.

Nút restart trả `202` trước khi chạy side effect và không tự gửi POST lần hai.
User chạy Gateway phải được systemd/polkit cho phép điều khiển đúng hai unit;
nếu chưa cấu hình quyền, dùng SSH thay vì mở rộng quyền tùy tiện cho service.
