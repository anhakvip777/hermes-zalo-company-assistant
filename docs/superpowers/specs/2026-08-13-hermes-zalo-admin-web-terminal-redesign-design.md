# Thiết kế làm mới Hermes Zalo Admin Web theo phong cách terminal

Ngày chốt thiết kế: 2026-08-13
Phạm vi: chỉ thay lớp giao diện Admin Web
Baseline nghiệp vụ: official release `v1.1.4`

## 1. Mục tiêu

Làm lại toàn bộ giao diện Hermes Zalo Admin theo phong cách cửa sổ terminal:
nền xanh đen có lưới mờ, quầng sáng xanh–tím–cam, viền gradient mảnh, ba chấm
đỏ/vàng/xanh và các vùng nội dung tối có độ tương phản rõ.

Giao diện mới phải:

- Giữ nguyên toàn bộ chức năng của bốn màn hình hiện tại.
- Giữ nguyên API, payload, authentication, session, CSRF và quyền admin.
- Giữ nguyên database sáu bảng và migration `001_initial.sql`.
- Hoạt động tốt trên desktop, tablet và điện thoại.
- Có dark/light mode, mặc định theo hệ điều hành và ghi nhớ lựa chọn thủ công.
- Dễ bảo trì hơn chuỗi `ADMIN_HTML` đang nhúng trực tiếp trong `admin.py`.

## 2. Ngoài phạm vi

Thiết kế này không:

- Thêm hoặc đổi business API.
- Thêm bảng, cột, migration hoặc cache database mới.
- Thêm framework frontend, package manager frontend hoặc build pipeline.
- Thêm process/service mới.
- Đổi chính sách allowlist, history, retention hoặc phân quyền.
- Cho sửa provider endpoint, API key, cookie, token, session hoặc QR secret.
- Thay đổi luồng restart, reconnect, export hoặc delete ở backend.

## 3. Quyết định đã duyệt

1. Làm mới toàn bộ lớp giao diện nhưng giữ nguyên chức năng.
2. Dùng HTML, CSS và JavaScript thuần tách thành asset riêng.
3. Không dùng React, Vue, Vite, CDN hoặc font tải từ Internet.
4. Bố cục desktop dùng sidebar gọn bên trái và vùng nội dung rộng.
5. Sidebar mặc định hiện icon + tên, có nút thu gọn và ghi nhớ lựa chọn.
6. Mỗi trang dùng một terminal frame lớn; QR, log và thao tác nguy hiểm dùng
   terminal card riêng.
7. Monospace dùng cho tiêu đề kỹ thuật, ID, số liệu, trạng thái và log; nội dung
   dài dùng font hệ thống dễ đọc.
8. Bảng có mật độ gọn vừa phải; trên mobile chuyển thành card.
9. Theme lần đầu theo `prefers-color-scheme`; lựa chọn thủ công được ghi nhớ.
10. Mobile dùng thanh điều hướng dưới thay cho sidebar.

## 4. Kiến trúc và ranh giới

`AdminWebApp` trong `hermes-plugin/admin.py` tiếp tục sở hữu:

- Login, logout, session cookie và CSRF.
- Toàn bộ route `/admin/api/*` hiện tại.
- Error contract tiếng Việt và redaction.
- Bridge access, history access và lifecycle callback.

Lớp giao diện được tách thành:

| File | Trách nhiệm |
|---|---|
| `hermes-plugin/admin_web/index.html` | Khung đăng nhập, app shell, sidebar, topbar và vùng render |
| `hermes-plugin/admin_web/admin.css` | Design token, theme, terminal frame, bảng và responsive |
| `hermes-plugin/admin_web/app.js` | API client, state, điều hướng và render bốn màn hình |

Các file này là asset runtime, không phải source cần biên dịch. Installer và
release package phải copy nguyên trạng thư mục `admin_web/`.

Trình duyệt chỉ giao tiếp với Admin Web cùng origin:

```text
Browser
  -> GET /admin/                    index.html
  -> GET /admin/assets/admin.css    CSS cùng origin
  -> GET /admin/assets/app.js       JavaScript cùng origin
  -> /admin/api/*                   API hiện tại
  -> AdminWebApp / AdminService / HistoryStore / Bridge
```

Không có route business mới. Hai route asset chỉ đọc file đã biết trước; không
nhận path tùy ý từ request và không trở thành file server tổng quát.

## 5. Content Security Policy và asset

- `default-src 'self'`.
- Script chỉ từ asset cùng origin; không dùng inline event handler hoặc
  `unsafe-eval`.
- Style chỉ từ asset cùng origin; không tải CDN.
- Ảnh cho phép `'self'` và `blob:` vì QR hiện được tải thành Blob URL.
- Không dùng external font; ưu tiên `Cascadia Code`, `SFMono-Regular`, Consolas
  và fallback monospace cho nội dung kỹ thuật.
- Icon dùng SVG nội bộ hoặc SVG tạo bằng DOM từ tập biểu tượng cố định; không
  nhúng HTML do API trả về.
- `textContent` tiếp tục là đường duy nhất đưa tên, ID, message và log vào DOM.

## 6. Design token và ngôn ngữ hình ảnh

CSS định nghĩa token riêng cho hai theme thay vì gắn màu trực tiếp vào từng
component:

- Background trang và lưới.
- Surface, panel và surface nổi.
- Border thường, border terminal gradient và focus ring.
- Text chính, text phụ và text mờ.
- Accent xanh dương/cyan.
- Success xanh lá, warning vàng và danger đỏ.
- Shadow và glow có cường độ thấp.

Dark theme bám sát ảnh tham chiếu. Light theme giữ cùng cấu trúc nhưng dùng nền
xám xanh rất nhạt, panel trắng xanh, chữ xanh đen và gradient dịu hơn; không chỉ
đảo màu máy móc.

Hiệu ứng chỉ gồm hover, focus, sidebar transition và skeleton pulse nhẹ. Khi
`prefers-reduced-motion: reduce`, transition và animation bị tắt.

## 7. App shell và điều hướng

### Desktop

- Sidebar cố định bên trái, mặc định rộng khoảng 220–240 px.
- Logo `HZ`, tên `HERMES ZALO` và nhãn `Company Assistant` ở đầu sidebar.
- Bốn mục: Tổng quan, Danh bạ & Allowlist, Hội thoại, Hệ thống & Hoạt động.
- Mục hiện tại có nền xanh trong suốt, border xanh và vạch cyan bên trái.
- Nút thu gọn chuyển sidebar về khoảng 72–84 px, chỉ còn icon.
- Topbar hiển thị đường dẫn kỹ thuật của trang, nút theme và hành động chính.
- Vùng nội dung có chiều rộng tối đa hợp lý nhưng dùng được toàn bộ không gian
  khi xem bảng hoặc hội thoại.

### Tablet

Sidebar mặc định chỉ hiện icon để ưu tiên bảng. Tooltip hoặc accessible label
vẫn cung cấp tên đầy đủ. Không bắt buộc ghi nhớ trạng thái tablet vào lựa chọn
desktop.

### Mobile

- Sidebar biến thành thanh điều hướng cố định dưới màn hình.
- Chỉ hiển thị icon và nhãn ngắn.
- Nội dung có padding dưới để không bị thanh điều hướng che.
- Topbar thu gọn; chỉ giữ theme và hành động chính phù hợp với trang.

### Persistence

`localStorage` chỉ lưu hai khóa giao diện có version:

- Theme `system`, `dark` hoặc `light`.
- Sidebar `expanded` hoặc `collapsed`.

Password, CSRF, session, API response, tên/ID và dữ liệu công ty không được lưu
trong `localStorage`.

## 8. Terminal frame và component chung

Mỗi trang dùng một `TerminalFrame` lớn gồm:

- Border gradient cyan–blue–amber–đỏ dịu.
- Header ba chấm đỏ/vàng/xanh chỉ mang tính trang trí.
- Tên frame bằng monospace, viết hoa và giãn ký tự.
- Body chứa card, bảng hoặc split view.

Các component chung:

- `StatusCard`: nhãn, giá trị lớn và chú thích.
- `Panel`: nội dung thông thường trong terminal frame.
- `MiniTerminal`: QR, log, activity hoặc danger zone.
- `DataTable`: header monospace, dòng gọn vừa và card fallback trên mobile.
- `Badge`: success, warning, danger, stale, bot và mention.
- `EmptyState`, `ErrorPanel`, `Skeleton` và `Toast`.
- `ConfirmModal`: xác nhận xóa/restart bằng nội dung cụ thể.
- `DraftBar`: cảnh báo allowlist chưa lưu và nút Lưu và áp dụng.

Component chỉ thay đổi cách render; không làm biến đổi dữ liệu API.

## 9. Màn hình đăng nhập

- Hiển thị một terminal card giữa màn hình.
- Có logo, tên sản phẩm, input mật khẩu và nút Đăng nhập.
- Không hiển thị thông tin bot hoặc trạng thái runtime trước khi xác thực.
- Lỗi login xuất hiện trong error panel có `aria-live`.
- Giữ nguyên throttle, cookie và contract login hiện tại.
- Theme toggle hoạt động ở màn hình login vì theme không phải dữ liệu nhạy cảm.

## 10. Màn hình Tổng quan

Terminal frame `TỔNG QUAN · LIVE STATUS` chứa:

- Bốn status card ưu tiên: Zalo, Hermes Gateway, Hội thoại và Allowlist.
- Panel tài khoản bot: tên, Zalo ID, provider, model, bridge và tin gần nhất.
- Panel hoạt động gần đây từ `tool_activity`.
- Panel thao tác nhanh tới Allowlist, QR, Hội thoại và Hệ thống.
- Nút Làm mới ở topbar.

Không hiển thị endpoint, credential hoặc dữ liệu raw từ provider.

## 11. Màn hình Danh bạ & Allowlist

### Cá nhân

- Toolbar tìm theo tên hoặc Zalo ID và lọc trạng thái.
- Bảng gồm tài khoản, Zalo ID, trạng thái bạn bè, allowed user và admin.
- Avatar dùng chữ cái sinh từ tên; không yêu cầu API ảnh mới.
- Toggle admin tự đảm bảo allowed user theo quy tắc hiện tại.
- Có nút nhập Zalo ID trực tiếp.

### Nhóm

- Panel nhóm công ty hiển thị tên, Group ID, số thành viên và allow toggle.
- Chi tiết thành viên tải theo yêu cầu, không tải tất cả group khi mở trang.
- Thành viên hiển thị tên, Zalo ID và trạng thái allowlist.
- Có nút nhập Group ID trực tiếp.

### Draft

- Mọi thay đổi chỉ cập nhật `state.draft` trong tab hiện tại.
- Khi draft khác fingerprint/config ban đầu, `DraftBar` cố định ở cuối vùng nội
  dung hiện cảnh báo và nút **Lưu và áp dụng**.
- Chuyển màn hình hoặc đóng tab khi có draft chưa lưu sẽ hỏi xác nhận.
- Lỗi `409` giữ draft để admin đối chiếu nhưng yêu cầu tải lại cấu hình trước khi
  gửi lại.

## 12. Màn hình Hội thoại

Desktop dùng split view:

- Cột trái: danh sách conversation có phân trang, loại, tên/ID và thời gian gần
  nhất.
- Cột phải: header conversation, message timeline, attachment và tool activity.
- Toolbar trên cùng: loại thread, sender, khoảng ngày và từ khóa.

Tin nhắn người dùng và bot dùng hai sắc độ panel khác nhau nhưng vẫn giữ hướng
đọc tự nhiên; không mô phỏng ứng dụng chat đến mức làm mất metadata quản trị.
Badge hiển thị bot, mention, recalled và attachment status.

Mobile xếp danh sách conversation và nội dung theo chiều dọc. Khi mở một
conversation, có nút quay lại danh sách rõ ràng.

Export và delete giữ nguyên backend. Delete luôn mở `ConfirmModal` ghi rõ thread
và việc không thể hoàn tác. Không tự retry khi kết quả không rõ.

## 13. Màn hình Hệ thống & Hoạt động

Trang này dùng nhiều `MiniTerminal` có chủ đích:

- Runtime Status: Zalo, Bridge, Gateway, SSE client, provider và model.
- QR Login: QR, Tạo QR mới và Reconnect Zalo.
- Live Log: log đã redact bằng monospace, có nút sao chép lỗi đã redact.
- Activity: bộ lọc và bảng `tool_activity` có phân trang.
- Danger Zone: Restart Bridge và Restart Gateway.

Restart mở modal ghi target và hậu quả. Sau response `202`, UI chuyển sang trạng
thái chờ rồi dùng polling hiện tại. UI không tự gửi lại lệnh restart.

## 14. Trạng thái tải, rỗng, stale và lỗi

- Loading dùng skeleton có kích thước gần nội dung thật để tránh layout shift.
- Empty state nằm trong terminal frame, giải thích vì sao rỗng và cung cấp hành
  động hợp lệ như Làm mới hoặc đổi bộ lọc.
- Dữ liệu danh bạ từ snapshot cũ có badge **Dữ liệu cũ** cùng thông báo bridge
  đang không sẵn sàng.
- Lỗi API giữ app shell và navigation, chỉ thay vùng nội dung bằng `ErrorPanel`.
- `ErrorPanel` dùng message tiếng Việt đã redact và nút Thử lại nếu phù hợp.
- `401` xóa state nhạy cảm trong bộ nhớ và quay về màn hình đăng nhập.
- `409` hiển thị xung đột cấu hình với hành động tải lại rõ ràng.
- Side-effect timeout/unknown không hiển thị như thành công và không tự retry.

## 15. Accessibility

- Mọi button và navigation item có accessible name.
- Icon trang trí dùng `aria-hidden`.
- Focus ring cyan đủ tương phản trong cả hai theme.
- Theme toggle phản ánh trạng thái qua label, không chỉ qua icon.
- Modal giữ focus, hỗ trợ Escape và trả focus về nút gọi sau khi đóng.
- Loading, lỗi login và kết quả mutation dùng vùng `aria-live` phù hợp.
- Bảng có header semantic trên desktop; card mobile vẫn giữ label cho từng giá
  trị.
- Màu không phải tín hiệu duy nhất; trạng thái luôn có text hoặc icon kèm label.

## 16. JavaScript state và render boundary

`app.js` giữ một state object trong memory gồm:

- CSRF token hiện tại.
- View hiện tại và render version để bỏ response cũ.
- Draft allowlist và fingerprint.
- History/activity filters và pagination.
- Blob URL QR đang hoạt động.
- Theme/sidebar preference đã đọc từ `localStorage`.

API client giữ `credentials: same-origin`, tự thêm CSRF cho mutation và chuẩn
hóa error contract như hiện tại. Mỗi renderer chỉ phụ trách một màn hình; helper
chung tạo element bằng DOM API và `textContent`.

Không dùng `innerHTML` với dữ liệu động, template engine hoặc dynamic script.

## 17. Packaging và vận hành

- `package.json.files` và `npm-shrinkwrap.json` phải đóng gói `admin_web/`.
- Installer phải copy đủ asset vào plugin target.
- Startup fail rõ nếu `index.html`, `admin.css` hoặc `app.js` bị thiếu; không
  phục vụ một trang trắng một phần.
- Source/audit bundle tiếp tục chứa test và asset source.
- Không chứa state, password, cookie, QR, database, media hoặc log trong asset.

## 18. Chiến lược kiểm thử

### Python contract

- Trang `/admin/` trả HTML tham chiếu đúng asset cùng origin.
- CSS/JS route chỉ phục vụ đúng file cho phép, đúng content type và không path
  traversal.
- Asset route tuân theo security header và không yêu cầu business API mới.
- CSP không cho external script/style và vẫn cho QR Blob URL.
- Toàn bộ test login, session, CSRF, allowlist, history, QR, restart, log và
  redaction hiện tại tiếp tục pass.

### JavaScript/UI contract

- Theme khởi tạo theo hệ điều hành, override thủ công và persistence.
- Sidebar mặc định mở, thu gọn/mở lại và persistence.
- Điều hướng render đúng bốn màn hình và bỏ response cũ.
- Loading, empty, stale, error, `401`, `409` và unknown side effect.
- Draft warning, before-unload và Lưu và áp dụng.
- Modal delete/restart không gọi API trước khi xác nhận.
- Mọi dữ liệu động được đưa vào DOM bằng `textContent`.

### Browser acceptance

- Desktop 1280×720 và màn hình rộng.
- Tablet khoảng 768 px với sidebar icon-only.
- Mobile 390×844 với bottom navigation và bảng dạng card.
- Dark/light mode, keyboard focus và reduced motion.
- QR, log dài, tên/ID dài, conversation dài và empty/error state không gây
  tràn ngang toàn trang.

### Regression toàn dự án

- Node suite, Python suite và integration suite đều pass.
- `python scripts/acceptance.py --static --json` trả `ok: true`.
- `git diff --check` exit `0`.
- Migration checksum giữ nguyên
  `1bc42abea11f4480d7a513cb4ddd2ee9d6986d1449d5a939aed14e59c161e42a`.

## 19. Tiêu chí nghiệm thu

Thiết kế được xem là triển khai đạt khi:

1. Bốn màn hình và login dùng style terminal đã duyệt.
2. Theme system/dark/light và sidebar persistence hoạt động.
3. Desktop, tablet và mobile không tràn ngang trang.
4. Mọi chức năng cũ vẫn dùng đúng endpoint và payload cũ.
5. Không có thay đổi database, migration hoặc quyền.
6. Asset tách riêng được package/cài đặt đầy đủ và CSP chặn external content.
7. Loading, empty, stale, error và dangerous action rõ ràng.
8. Kiểm thử contract, browser acceptance và regression toàn dự án đều pass.
