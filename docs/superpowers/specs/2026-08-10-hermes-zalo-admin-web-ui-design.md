# Thiết kế Admin Web UI cho Hermes Zalo

- Ngày khóa thiết kế: 2026-08-10
- Trạng thái: đã duyệt spec và kế hoạch; implementation đã hoàn tất trong working tree, đang nghiệm thu runtime production
- Thiết kế nền: `2026-08-09-hermes-zalo-company-assistant-design.md`

## 1. Mục tiêu

Tạo một Web UI đơn giản cho quản trị viên của công ty năm người để:

- Xem thông tin cơ bản của tài khoản Zalo đang chạy bot.
- Xem bạn bè, nhóm và thành viên nhóm kèm Zalo ID.
- Quản lý `allowed_users`, `admin_users` và `allowed_groups`.
- Xem, tìm kiếm, xuất và xóa lịch sử hội thoại đã lưu.
- Xem hoạt động tool, trạng thái Zalo bridge, Hermes Gateway, provider và model.
- Đăng nhập lại bằng QR, reconnect Zalo và điều khiển service.

Web UI là bề mặt quản trị của hệ thống hiện có, không phải một sản phẩm hoặc
service độc lập.

## 2. Quyết định kiến trúc đã khóa

1. Admin Web UI chạy bên trong Hermes Zalo plugin, cùng process và vòng đời với
   Hermes Gateway.
2. Không tạo Admin Web Service riêng.
3. Node bridge tiếp tục là process riêng duy nhất sở hữu phiên `zca-js`.
4. Web UI chỉ bind vào `127.0.0.1`; Caddy hoặc Nginx hiện có reverse proxy HTTPS
   tới cổng loopback của plugin.
5. Không thay đổi schema SQLite và không tạo migration mới.
6. Giữ nguyên `HistoryStore`, `AdminService`, `CompanyConfigFile`, cấu hình YAML
   và bảng `tool_activity`; chỉ mở rộng API của các lớp hiện có khi cần.
7. Không thêm frontend framework, bundler hoặc quy trình build giao diện.
8. HTML, CSS và JavaScript tối giản nằm trong file Python hiện có
   `hermes-plugin/admin.py`.
9. Không thêm process, daemon hoặc dependency runtime mới. HTTP server dùng
   `aiohttp.web`, cùng thư viện mà adapter đã dùng cho HTTP/SSE.
10. Không thêm hoặc xóa file runtime ngoài `docs/architecture/file-manifest.md`.

## 3. Cấu trúc hệ thống

```text
Zalo
  ↕
Node bridge + zca-js                         process 1
  ↕ SSE inbound / REST outbound + Bearer token
Hermes Gateway
  └─ Hermes Zalo plugin                     process 2
      ├─ ZaloAdapter
      ├─ ZaloTooling
      ├─ AdminService
      ├─ AdminWebApp
      ├─ HistoryStore → SQLite + media
      └─ CompanyConfigFile → config.yaml

Admin Browser
  → HTTPS
  → Caddy/Nginx
  → 127.0.0.1:<admin-web-port>
  → AdminWebApp trong plugin
```

`AdminWebApp` chỉ làm bốn việc:

- Xác thực phiên Web UI.
- Cung cấp trang HTML và API cùng origin.
- Chuyển yêu cầu nghiệp vụ cho `AdminService`, `HistoryStore` và adapter.
- Chuẩn hóa response, lỗi, CSRF và audit.

`AdminWebApp` không trực tiếp sở hữu phiên Zalo, không đọc credential Zalo hoặc
provider và không tự sửa SQLite hoặc YAML. Nó chỉ nhận password hash và session
secret từ cấu hình Web UI để thực hiện xác thực.

## 4. Vòng đời

- Adapter tạo `AdminService` và `AdminWebApp` từ các đối tượng đang dùng chung.
- Khi plugin connect, Web UI bắt đầu listen trên loopback nếu cấu hình Web UI
  hợp lệ.
- Khi plugin disconnect hoặc Gateway dừng, Web UI đóng listener và session
  trong bộ nhớ.
- Lỗi khởi động Web UI chỉ vô hiệu hóa UI và ghi log đã redact; không làm dừng
  luồng chat Zalo.
- Nếu Hermes Gateway chết hoàn toàn thì UI cũng không truy cập được. Admin phải
  dùng CLI/SSH/systemd để khởi động lại; đây là giới hạn được chấp nhận khi
  không có service quản trị riêng.

## 5. Cấu hình Web UI

Thông tin nhạy cảm chỉ lấy từ environment riêng của service:

```text
ZALO_ADMIN_WEB_ENABLED=true
ZALO_ADMIN_WEB_HOST=127.0.0.1
ZALO_ADMIN_WEB_PORT=8790
ZALO_ADMIN_WEB_PASSWORD_HASH=<scrypt hash>
ZALO_ADMIN_WEB_SESSION_SECRET=<random secret>
ZALO_ADMIN_WEB_SESSION_TTL_SECONDS=86400
```

Quy tắc:

- Host khác loopback bị từ chối khi khởi động.
- Thiếu password hash hoặc session secret thì UI không khởi động.
- Password hash, session secret, bridge token, cookie Zalo và provider API key
  không được ghi vào YAML, SQLite, HTML, JavaScript, response hoặc log.
- Caddy/Nginx chịu trách nhiệm TLS và có thể bổ sung rate limit ngoài plugin.

## 6. Xác thực và phiên

Hệ thống dùng một mật khẩu quản trị chung, phù hợp với một admin chính và công
ty nhỏ. Không tạo bảng user hoặc tích hợp OAuth.

- Mật khẩu lưu dưới dạng scrypt hash trong environment.
- So sánh hash theo thời gian cố định.
- Sau khi đăng nhập, server tạo cookie phiên được ký bằng
  `ZALO_ADMIN_WEB_SESSION_SECRET`.
- Cookie có `HttpOnly`, `Secure`, `SameSite=Strict`, path giới hạn cho Web UI và
  thời hạn mặc định 24 giờ.
- Mọi request thay đổi trạng thái phải có CSRF token ràng buộc với session.
- Đăng xuất làm hết hạn cookie phía trình duyệt.
- Năm lần đăng nhập sai trong năm phút sẽ tạm khóa đăng nhập toàn UI trong năm
  phút. Bộ đếm nằm trong RAM và mất khi Gateway restart.
- Hoạt động đã xác thực dùng requester cố định `web-admin`; hệ thống không tuyên
  bố phân biệt được nhiều người cùng dùng mật khẩu chung.

## 7. Điều hướng và bố cục

UI dùng một trang responsive, sidebar trên desktop và menu gọn trên màn hình
nhỏ. Có bốn mục:

1. Tổng quan.
2. Danh bạ & Allowlist.
3. Hội thoại.
4. Hệ thống & Hoạt động.

Giao diện dùng tiếng Việt. Mỗi trang có trạng thái đang tải, rỗng, lỗi và nút
thử lại rõ ràng. Không dùng WebSocket; dữ liệu được tải khi mở trang, khi bấm
làm mới và khi một thao tác hoàn tất.

## 8. Màn hình Tổng quan

Hiển thị:

- Tên và Zalo ID của tài khoản bot.
- Trạng thái đăng nhập Zalo, bridge và Hermes Gateway.
- Provider và model đang dùng; không hiện endpoint có credential hoặc API key.
- Số bạn bè, số nhóm, số người và số nhóm trong allowlist.
- Số hội thoại/tin nhắn đã lưu và thời gian tin gần nhất.
- Các hoạt động gần đây từ `tool_activity`.

Thao tác nhanh:

- Làm mới.
- Mở QR.
- Chuyển tới trang allowlist.
- Chuyển tới trang hệ thống.

Dữ liệu lấy từ status provider của adapter, bridge `/health`, bridge `/policy`,
`HistoryStore.stats()` và cấu hình công ty đang chạy.

## 9. Màn hình Danh bạ & Allowlist

### 9.1 Cá nhân

Mỗi dòng hiển thị:

- Tên Zalo.
- Zalo ID.
- Trạng thái bạn bè nếu bridge cung cấp.
- Có thuộc `allowed_users` hay không.
- Có thuộc `admin_users` hay không.

Admin có thể chọn từ danh sách bạn bè hoặc nhập Zalo ID trực tiếp. Bật admin chỉ
hợp lệ khi ID đồng thời nằm trong `allowed_users`.

### 9.2 Nhóm

Mỗi dòng hiển thị:

- Tên nhóm.
- Group ID.
- Số thành viên.
- Có thuộc `allowed_groups` hay không.

Khi mở chi tiết nhóm, UI tải danh sách thành viên kèm tên, ID và trạng thái
allowlist. Admin có thể chọn từ danh sách nhóm hoặc nhập group ID trực tiếp.

### 9.3 Quy tắc kích hoạt bot

- Mọi tin trong group thuộc `allowed_groups` đều được lưu dù không mention.
- Chỉ sender thuộc `allowed_users` và mention bot mới tạo Hermes turn.
- Thêm group không tự động thêm toàn bộ thành viên vào `allowed_users`.
- DM chỉ được lưu và xử lý khi sender thuộc `allowed_users`.

### 9.4 Bản nháp và Lưu và áp dụng

Thay đổi chỉ tồn tại trong bộ nhớ trình duyệt cho đến khi admin bấm
**Lưu và áp dụng**. UI gửi toàn bộ ba tập ID cùng fingerprint của cấu hình lúc
bắt đầu sửa.

Server thực hiện theo thứ tự:

1. Kiểm tra session và CSRF.
2. So fingerprint; nếu cấu hình đã đổi ở tab hoặc kênh khác thì trả `409` và
   yêu cầu tải lại.
3. Chuẩn hóa ID, loại trùng và validate bằng `CompanyConfig`.
4. Bảo đảm `allowed_users`, `admin_users`, `allowed_groups` không rỗng.
5. Bảo đảm admin là tập con của allowed user và không xóa admin cuối cùng.
6. Ghi YAML nguyên tử bằng `CompanyConfigFile`.
7. Cập nhật cấu hình trong adapter/tooling đang chạy, không restart bridge.
8. Ghi `admin_web.apply_access_config` vào `tool_activity`.

Nếu cập nhật runtime thất bại sau khi ghi file, server phục hồi bản YAML cũ,
phục hồi cấu hình runtime cũ và trả lỗi. Hệ thống không để cấu hình áp dụng một
nửa.

`AdminService` và `CompanyConfigFile` được mở rộng để hỗ trợ batch apply và
`add_group`/`remove_group`; UI không tự viết YAML.

## 10. Màn hình Hội thoại

Bố cục:

- Cột hội thoại gồm chat riêng và nhóm, tên/ID và thời gian tin gần nhất.
- Khung tin nhắn theo thời gian.
- Bộ lọc theo loại hội thoại, sender, khoảng ngày và từ khóa.
- Dấu hiệu message có mention bot, là tin bot hay tin người dùng.
- Attachment với tên, loại, kích thước và trạng thái tải.
- Hoạt động tool liên quan đến thread nếu có.

Admin Web UI có scope toàn công ty. Member không truy cập Web UI; scope lịch sử
của member qua Zalo vẫn giữ quy tắc DM riêng và group allowlist hiện tại.

Các thao tác:

- Liệt kê hội thoại có phân trang.
- Xem message có phân trang, tối đa 100 dòng mỗi request.
- Tìm kiếm từ khóa.
- Tải attachment đã lưu.
- Xuất một conversation hoặc khoảng thời gian thành JSONL.
- Xóa theo conversation hoặc khoảng thời gian sau hộp xác nhận.

Export dùng đường dẫn do server tạo dưới thư mục export hiện có; trình duyệt
không được truyền đường dẫn filesystem tùy ý. Attachment chỉ được phục vụ khi
`local_path` nằm dưới media root sau khi resolve path.

Xóa và export không tự retry khi timeout hoặc kết quả không rõ. Mỗi thao tác ghi
audit đã redact vào `tool_activity`.

Các hàm list conversation, page message và page tool activity được bổ sung vào
`HistoryStore`; chúng dùng schema hiện tại.

## 11. Màn hình Hệ thống & Hoạt động

Hiển thị:

- Tên/ID tài khoản Zalo và trạng thái đăng nhập.
- Bridge connected/disconnected, số SSE client và lỗi gần nhất.
- Hermes Gateway, provider và model đã redact.
- QR state.
- Log gần nhất đã redact.
- `tool_activity` lọc theo requester, tool, status, thread và thời gian.

Admin có thể:

- Làm mới trạng thái.
- Mở QR và yêu cầu đăng nhập lại.
- Reconnect Zalo.
- Restart Hermes Gateway hoặc bridge sau một hộp xác nhận.
- Sao chép thông báo lỗi đã redact.

Restart Gateway trả `202 Accepted` trước khi gọi lifecycle action. UI chuyển
sang trạng thái chờ và poll lại sau khi kết nối mất. Nếu Gateway không trở lại,
UI hướng dẫn dùng CLI/SSH; nó không cố tự chạy lặp thao tác restart.

Web UI không cho sửa provider endpoint, model credential hoặc secret. Provider
và model chỉ dùng để chẩn đoán trạng thái.

## 12. API nội bộ của Web UI

Tên route chính xác có thể giữ prefix cấu hình, nhưng contract logic gồm:

```text
GET  /admin/                         HTML/CSS/JS
POST /admin/api/login               tạo session
POST /admin/api/logout              hết hạn session
GET  /admin/api/overview            tổng quan
GET  /admin/api/access              cấu hình allowlist hiện tại + fingerprint
GET  /admin/api/friends             bạn bè từ bridge
GET  /admin/api/groups              nhóm từ bridge
GET  /admin/api/groups/:id/members  thành viên nhóm từ bridge
POST /admin/api/access/apply        Lưu và áp dụng
GET  /admin/api/conversations       danh sách hội thoại
GET  /admin/api/conversations/:id   message của hội thoại
GET  /admin/api/history/search      tìm kiếm
POST /admin/api/history/export      xuất và tải file
POST /admin/api/history/delete      xóa có xác nhận
GET  /admin/api/attachments/:id     tải attachment hợp lệ
GET  /admin/api/activity            tool_activity
GET  /admin/api/system              trạng thái hệ thống
POST /admin/api/system/qr           tạo/đọc QR flow
POST /admin/api/system/reconnect    reconnect Zalo
POST /admin/api/system/restart      restart target rõ ràng
GET  /admin/api/system/logs         log đã redact
```

Mọi route trừ trang và login yêu cầu session. Mọi route mutation sau đăng nhập,
gồm logout, yêu cầu CSRF; login là ngoại lệ vì chưa có session. Response lỗi có
`code`, thông báo tiếng Việt an toàn và `retryable`; không trả stack trace hoặc
raw provider error cho trình duyệt.

## 13. Nguồn dữ liệu và ranh giới

| Dữ liệu | Nguồn duy nhất | Ghi qua |
|---|---|---|
| Tài khoản, bạn bè, nhóm, thành viên, QR | Node bridge | Bridge API đã xác thực |
| Hội thoại, message, attachment | `HistoryStore` | `HistoryStore` |
| Allowlist và admin list | Hermes `config.yaml` | `CompanyConfigFile` |
| Audit | `tool_activity` | `HistoryStore.log_tool_activity` |
| Trạng thái/lifecycle/log | Adapter và `AdminService` | Lifecycle callback hiện có |

Trình duyệt chỉ giao tiếp với Admin Web UI. Bridge token chỉ tồn tại ở phía
server giữa plugin và bridge.

## 14. Audit

Các hành động sau phải ghi `tool_activity` với requester `web-admin`,
thread type `system` và thread ID `admin-web`:

- Đăng nhập và đăng xuất thành công.
- Lưu allowlist/admin/group.
- Export hoặc xóa lịch sử.
- Tải attachment.
- Tạo QR hoặc reconnect.
- Restart service.
- Đọc log.

Dashboard refresh và các request danh sách thông thường không ghi audit để
tránh tạo nhiều dòng vô ích. Metadata chỉ giữ tên action, target ID cần thiết và
số lượng; không giữ password, session, CSRF, token, raw args hoặc raw result.

## 15. Xử lý lỗi

- Bridge mất kết nối: UI vẫn mở, hiển thị trạng thái đỏ và vô hiệu hóa thao tác
  cần Zalo.
- Không lấy được bạn bè/nhóm: giữ dữ liệu lần tải thành công gần nhất trong tab
  và cho thử lại; không ghi cache mới xuống SQLite.
- YAML không hợp lệ hoặc invariant sai: trả lỗi theo field và không ghi file.
- Apply thất bại: phục hồi file/runtime cũ và ghi audit `failed`.
- Timeout có side effect: trả `unknown`, không tự retry.
- History/attachment không tồn tại: trả `404` an toàn.
- Session hết hạn: trả `401`, UI chuyển về màn hình đăng nhập và giữ bản nháp
  trong tab cho tới khi reload.
- CSRF sai: trả `403` và không chạy action.
- Mọi raw error chạy qua redaction trước log, audit và response.

## 16. Kiểm thử

Không tạo test file mới. Mở rộng các file test hiện có trong manifest.

### 16.1 Unit và contract

- Password hash, cookie ký, TTL, logout, rate limit và CSRF.
- Chỉ bind loopback, thiếu secret thì UI không khởi động.
- Route auth/read/mutation và error contract.
- Không có response chứa bridge token, cookie, API key hoặc password.
- `CompanyConfigFile` batch apply, fingerprint conflict và rollback.
- Group/user/admin invariant, gồm chặn xóa admin cuối.
- History pagination, search, attachment path containment và activity filter.
- Audit dùng `web-admin` và metadata đã redact.

### 16.2 Integration

- Fake bridge cung cấp profile, friends, groups, member, health và QR.
- Đăng nhập → tải overview → sửa draft → Lưu và áp dụng → đọc lại config.
- Group allowlist lưu message không mention; allowed sender mention mới gọi
  Hermes.
- Export/delete history và kiểm tra audit.
- Bridge down không làm UI hoặc chat state hỏng.
- Restart response có thể mất kết nối nhưng không tự gửi lại action.

### 16.3 Nghiệm thu thực tế

1. Đăng nhập Web UI qua HTTPS.
2. Thấy đúng tên/ID bot, bạn bè, `Group AI` và thành viên kèm ID.
3. Thêm/xóa một user và group thử nghiệm rồi Lưu và áp dụng.
4. Xác nhận cấu hình runtime đổi mà bridge không restart.
5. Gửi tin không mention trong `Group AI`: lưu nhưng bot im lặng.
6. Allowed user mention: Hermes trả lời và history có cả hai tin.
7. Tìm kiếm, xuất và xóa một phạm vi thử nghiệm.
8. Mở QR/reconnect và kiểm tra system/activity.
9. Quét HTML, JSON, log và `tool_activity` để xác nhận không lộ secret.

## 17. File dự kiến sửa khi triển khai

Không tạo file runtime mới. Kế hoạch triển khai chỉ được sử dụng các file đã có
và đã đăng ký trong manifest:

- `hermes-plugin/admin.py`: `AdminWebApp`, HTML/CSS/JS, auth và route.
- `hermes-plugin/adapter.py`: vòng đời Web UI và data/status callbacks.
- `hermes-plugin/company_config.py`: batch apply, group mutation, fingerprint và
  rollback helper.
- `hermes-plugin/history_store.py`: conversation/activity pagination.
- `hermes-plugin/tooling.py`: đồng bộ action group/config và audit.
- `hermes-plugin/plugin.yaml`: khai báo tên biến Web UI; không lưu giá trị
  password hash hoặc session secret.
- `tests/python/test_tooling.py`, `test_adapter.py`, `test_company_config.py`,
  `test_history_store.py`: test Web UI và backend liên quan.
- `tests/integration/fake_bridge.py`,
  `tests/integration/test_company_assistant_flow.py`: integration.
- `docs/operations/configuration.md`, `README.vi.md`,
  `docs/operations/acceptance-checklist.md`: hướng dẫn và nghiệm thu.

Nếu triển khai cần thêm file khác, phải dừng và xin duyệt trước khi thay đổi
manifest.

## 18. Ngoài phạm vi

- Multi-tenant hoặc nhiều tài khoản Zalo.
- Hệ thống tài khoản Web UI cho từng nhân viên.
- OAuth, SSO, phân quyền chi tiết trong Web UI.
- Approval broker hoặc duyệt từng tool call.
- Frontend framework, SPA build pipeline hoặc mobile app.
- Sửa provider credential, API key hoặc secret trong trình duyệt.
- Sửa memory chung trong Web UI; admin tiếp tục dùng `zalo_admin` cho memory.
- Thay schema SQLite hoặc migration.
- Service/process quản trị riêng.
- Active-active hoặc tự khôi phục Gateway khi chính Gateway đã chết.

## 19. Rủi ro và giới hạn được chấp nhận

- UI cùng process với Gateway nên không dùng được khi Gateway chết.
- Mật khẩu chung chỉ cho biết thao tác đến từ `web-admin`, không phân biệt cá
  nhân nếu sau này có nhiều admin dùng chung.
- Dữ liệu bạn bè/nhóm có thể cũ trong thời gian bridge đang cache hoặc Zalo rate
  limit.
- Admin được đọc toàn bộ lịch sử công ty và có thể xóa dữ liệu.
- `zca-js` là API không chính thức nên Zalo có thể thay đổi hành vi hoặc giới hạn
  tài khoản.

## 20. Tiêu chí hoàn thành

Tính năng chỉ được coi là hoàn thành khi:

1. Tất cả màn hình và luồng đã duyệt hoạt động trên desktop và màn hình nhỏ.
2. Không có process, schema, migration hoặc file runtime mới.
3. Luồng chat hiện có vẫn vượt qua toàn bộ test.
4. Test auth, allowlist, history, audit, QR và system action vượt qua.
5. Nghiệm thu thật với `Group AI` vượt qua.
6. Không phát hiện secret trong response, HTML, log hoặc `tool_activity`.
7. `git diff --check`, Node test, Python test, integration và acceptance đều
   thành công.
