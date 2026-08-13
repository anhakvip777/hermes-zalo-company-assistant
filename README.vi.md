# Hermes Zalo Company Assistant

[English](./README.md) · **Tiếng Việt**

Plugin này nối một tài khoản Zalo công ty với Hermes Agent thông qua
`zca-js@2.1.2`. Dự án bắt đầu từ `cuongdev/hermes-zalo-plugin@1.0.9` và giữ
toàn bộ bề mặt vận hành của Zalo để nhóm nhỏ có thể dùng Hermes như một thư ký
công ty.

Mô hình triển khai mặc định:

- Một công ty, một tài khoản Zalo, một Hermes Agent và một VPS.
- Mọi thành viên trong `allowed_users` được dùng toàn bộ tool thông thường của
  Hermes và mọi method Zalo vận hành, không cần duyệt từng lệnh.
- Admin có thêm quyền quản lý thành viên, memory, lịch sử, QR và dịch vụ.
- Toàn bộ tin nhắn trong `allowed_groups` được lưu, dù có mention bot hay không.
- Trong group, chỉ mention từ một thành viên được phép mới kích hoạt Hermes.
- Chat riêng của mỗi thành viên dùng session và lịch sử riêng.

> `zca-js` là API Zalo cá nhân không chính thức. Tài khoản có thể bị challenge,
> giới hạn hoặc khóa. Nên dùng tài khoản Zalo riêng cho bot công ty.

## Yêu cầu

- Node.js 22 trở lên.
- Python 3.11 trở lên.
- Hermes Agent 0.19.0 tại commit
  `eb52760564dbba2e5971fa54bd67384e281cd3b8`, có các contract
  `PlatformEntry.env_enablement_fn` và `MessageEvent.channel_context`.
- `aiohttp`, `PyYAML` cho adapter Python.
- Ubuntu 22.04/24.04 và systemd được khuyến nghị cho VPS.

## Cài nhanh

```bash
npm install
python -m pip install -r requirements-runtime.txt
node install.mjs
```

Installer tạo `~/.hermes-zalo/company.env` với quyền riêng tư, tự sinh bridge
token tối thiểu 32 byte nếu chưa có, hướng dẫn login QR và cài bridge service.

Nếu cài thủ công:

```bash
export ZALO_PLUGIN_HOST=127.0.0.1
export ZALO_PLUGIN_PORT=8787
export ZALO_PLUGIN_TOKEN="$(openssl rand -hex 32)"
export ZALO_DATA_DIR="$HOME/.hermes-zalo"

node login.mjs
node server.js
```

Mọi route bridge đều cần một trong hai header nội bộ:

```text
Authorization: Bearer <ZALO_PLUGIN_TOKEN>
x-bridge-token: <ZALO_PLUGIN_TOKEN>
```

Không hỗ trợ token trong query string. Bridge chỉ bind `127.0.0.1`.

## Cấu hình Hermes

Trong `config.yaml`:

```yaml
approvals:
  mode: off

gateway:
  group_sessions_per_user: false
  platforms:
    zalo:
      enabled: true
      extra:
        bridge_url: http://127.0.0.1:8787
        allowed_users:
          - "zalo-id-nhan-vien-1"
          - "zalo-id-nhan-vien-2"
          - "zalo-id-admin"
        admin_users:
          - "zalo-id-admin"
        allowed_groups:
          - "zalo-group-id-cong-ty"
        group_mode: mention
        history_context_messages: 100
        media_max_bytes: 20971520
        history_retention: "90"
```

Giữ token trong env của cả bridge và Hermes gateway, không ghi token vào YAML:

```bash
export ZALO_PLUGIN_URL=http://127.0.0.1:8787
export ZALO_PLUGIN_TOKEN=<cùng-token-với-bridge>
```

Cấu hình fail-closed: `allowed_users`, `admin_users` và `allowed_groups` không
được rỗng; admin phải là tập con của thành viên; `group_mode` phải là `mention`.

`approvals.mode: off` chỉ phù hợp khi đây là profile Zalo cô lập, chạy bằng user
hệ điều hành riêng và không truy cập profile/dữ liệu cá nhân khác. Không dùng
cấu hình này cho Hermes profile dùng chung. `off` bỏ qua approval trong toàn bộ
profile đích; Admin Guard vẫn chặn non-admin sửa memory chung bằng `memory`,
`write_file`, `patch`, terminal hoặc execute-code.

Đây là bot nội bộ cho trusted team, không phải bot public. Thành viên allowlist
có quyền vận hành rộng; prompt injection, tài khoản bị chiếm, AI hiểu sai và
action khó hoàn tác là rủi ro đã được chủ dự án chấp nhận. Chỉ dùng tài khoản
Zalo riêng cho bot, không dùng tài khoản cá nhân/chủ lực.

## Cách bot xử lý hội thoại

### Group công ty

1. Bridge nhận và chuẩn hóa event.
2. Adapter chống trùng và lưu message/attachment trước.
3. Không mention: bot im lặng nhưng message vẫn nằm trong lịch sử.
4. Mention từ user trong `allowed_users`: gọi Hermes bằng session chung của group.
5. Mention từ user ngoài allowlist: vẫn lưu nhưng không gọi Hermes.

### Chat riêng

- Chỉ DM từ `allowed_users` được lưu và gọi Hermes.
- Mỗi Zalo ID có session DM riêng.
- DM của thành viên này không được đưa cho thành viên khác.
- Tin outbound chỉ được lưu sau khi bridge trả provider message ID rõ ràng.
- Timeout hoặc kết quả gửi không rõ trả `unknown` và không tự gửi lại.

## Tool Hermes

### `zalo`

```text
zalo(action="list", query="poll")
zalo(action="describe", method="createPoll")
zalo(action="call", method="createPoll", params={...})
zalo(action="call", method="customMethod", args=[...])
```

Catalog được tạo từ declaration và API object của `zca-js@2.1.2`. `params` dùng
schema theo tên; `args` là positional fallback. Các method xuất credential như
`getCookie`, `getContext`, `getQR` bị ẩn và từ chối qua chat.

### `zalo_history`

Các action: `recent`, `search`, `get_message`, `get_attachment`.

- Thành viên đọc DM của chính mình và mọi group trong `allowed_groups`, kể cả
  khi hỏi từ DM hoặc group khác. Đây là policy trusted-team để bot làm thư ký
  chung; thành viên vẫn không thể đọc DM của người khác, export/xóa history hoặc
  đổi retention.
- Admin có thể đọc toàn bộ lịch sử công ty.

### `zalo_admin`

Các action ban đầu:

```text
status
add_user / remove_user
add_admin / remove_admin
add_group / remove_group
get_access_config / apply_access_config
memory_add / memory_update / memory_delete
history_export / history_delete
login_qr
start / stop / restart
show_logs
```

Mọi action kiểm tra requester từ `ContextVar`; tool không tin `requester_id` do
model tự truyền. Không thể xóa admin cuối cùng.
Các lệnh memory ghi đúng layout và định dạng native của Hermes 0.19 tại
`$HERMES_HOME/memories/MEMORY.md`.

## Admin Web UI

Web UI được nhúng trực tiếp trong Hermes Zalo plugin, không phải service riêng và
không tạo schema/migration mới. UI chỉ bind `127.0.0.1` và production phải mở qua
HTTPS reverse proxy.

Các biến service environment:

```text
ZALO_ADMIN_WEB_ENABLED=true
ZALO_ADMIN_WEB_HOST=127.0.0.1
ZALO_ADMIN_WEB_PORT=8790
ZALO_ADMIN_WEB_PASSWORD_HASH=<scrypt-hash>
ZALO_ADMIN_WEB_SESSION_SECRET=<random-at-least-32-utf8-bytes>
ZALO_ADMIN_WEB_SESSION_TTL_SECONDS=86400
```

Tạo password hash an toàn trên PowerShell:

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

Tạo session secret trên Windows, không cần OpenSSL:

```powershell
$bytes = New-Object byte[] 32
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
-join ($bytes | ForEach-Object { $_.ToString("x2") })
```

Ví dụ Caddy:

```caddyfile
zalo-admin.example.com {
    reverse_proxy 127.0.0.1:8790
}
```

Sau đó mở `https://zalo-admin.example.com/admin/`. Bốn mục chính là Tổng quan,
Danh bạ & Allowlist, Hội thoại, và Hệ thống & Hoạt động. Admin có thể xem họ
tên/Zalo ID bot, bạn bè, group, thành viên group; sửa ba allowlist bằng một lần
**Lưu và áp dụng**; xem/export/xóa history; mở QR, reconnect và xem activity/log.

UI sống cùng Hermes Gateway. Nếu bridge mất hoặc Zalo hết session, UI vẫn được
giữ để quét QR/reconnect. Nếu Gateway chết, dùng SSH/console:

```bash
sudo systemctl restart hermes-gateway
```

Nút restart trong UI chỉ hoạt động khi user chạy Gateway đã được polkit/systemd
cho phép điều khiển đúng unit. Không cấp quyền systemctl rộng chỉ để bật nút này.

## Lưu lịch sử và media

SQLite lưu conversation, message, event, attachment và tool activity. Binary
media nằm trên filesystem.

Mặc định lịch sử được giữ `90` ngày. Có thể chọn `30`, `90`, `365` hoặc
`forever` bằng `history_retention`/`ZALO_HISTORY_RETENTION`. Adapter purge khi
khởi động; admin vẫn có thể export hoặc xóa theo group/user/khoảng thời gian.
Xóa group khỏi allowlist không tự xóa dữ liệu cũ.

SQLite, media, config và backup phải thuộc user `hermes-zalo`, thư mục `0700`,
file secret `0600`. Mã hóa backup trước khi chuyển khỏi VPS; không mount hoặc
symlink home/profile cá nhân vào `/var/lib/hermes-zalo`.

Khi thành viên rời team hoặc nghi tài khoản bị chiếm: xóa ID khỏi allowlist,
dừng hai service, thu hồi API key/email/bridge token, QR relogin, kiểm tra audit
log rồi export/purge dữ liệu bị ảnh hưởng.

```text
~/.hermes-zalo/history/conversations.sqlite3
~/.hermes-zalo/history/media/<dm|group>/<thread-id>/<YYYY-MM-DD>/
~/.hermes-zalo/exports/
```

- Media không quá 20 MiB được stream xuống đĩa, chmod riêng tư và hash SHA-256.
- Media lớn hơn chỉ lưu metadata/URL.
- Stream chưa biết kích thước dừng ngay khi vượt cap.
- Download lỗi không làm rollback message.
- Dedupe theo message và attachment index nên restart không tải/lưu lần hai.

## API bridge

Các route tiện dụng của bản 1.0.9 vẫn được giữ: `/send`, `/send-attachment`,
`/send-sticker`, `/send-voice`, `/typing`, `/react`, `/undo`, friend/group/poll,
`/health`, `/events`, `/qr`, `/relogin`, `/shutdown`.

Khám phá và gọi toàn bộ bề mặt Zalo:

```text
GET  /api/methods
GET  /api/methods/:method
POST /api/:method       body: {"params": {...}} hoặc {"args": [...]}
```

Kết quả và log được redact đệ quy cho cookie, token, password, API key, secret,
IMEI và Authorization.

## systemd trên VPS

Mẫu production nằm trong `systemd/`:

```bash
sudo cp systemd/hermes-zalo-company.env.example /etc/hermes-zalo-company.env
sudo chmod 600 /etc/hermes-zalo-company.env
sudo cp systemd/hermes-zalo-company-bridge.service /etc/systemd/system/
sudo cp systemd/hermes-gateway.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hermes-zalo-company-bridge hermes-gateway
```

Mẫu environment giữ cấu hình tối thiểu vì Admin Web là tùy chọn. Nếu bật Web UI,
thêm sáu biến `ZALO_ADMIN_WEB_*` ở phần **Admin Web UI** phía trên vào
`/etc/hermes-zalo-company.env` trước khi restart Gateway.

Tạo user riêng `hermes-zalo`, không cấp sudo và không cho đọc home/profile khác.
Mẫu service dùng `HERMES_HOME=/var/lib/hermes-zalo/profile`, `ProtectHome=true`
và `ProtectSystem=strict`. Sửa đường dẫn `/opt` và token theo VPS thực tế. Bridge được
khởi động trước gateway và cả hai tự restart khi lỗi.

Xem trước mà không thay đổi gì:

```bash
node install.mjs --dry-run --hermes-home /var/lib/hermes-zalo/profile
```

Cài cần `--yes`. Mục tiêu tồn tại chỉ được thay khi có `--force`; installer sẽ
backup config và plugin cũ vào `HERMES_HOME/backups` trước khi thay thế.

## Nâng cấp từ cấu hình 1.0.9

```bash
node scripts/migrate-v1.0.9-config.mjs \
  --config "$HERMES_HOME/config.yaml" \
  --env-file "$HERMES_HOME/.env"
```

Migration idempotent và không copy token/cookie vào YAML.

## Kiểm thử và nghiệm thu

```bash
npm test
python -m pip install -r requirements-test.txt
python -m pytest -q
npm audit --omit=dev
npm pack --dry-run
python scripts/acceptance.py --json
git diff --check
```

Checklist vận hành chi tiết: `docs/operations/acceptance-checklist.md`.

## Giấy phép

MIT.
