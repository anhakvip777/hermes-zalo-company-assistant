# Thiết kế đồng bộ allowlist Admin Web vào `.env`

Ngày duyệt phương án: 2026-08-18  
Phạm vi: profile Hermes Zalo công ty hiện hữu  
Quyết định: phương án 1 — Admin Web đồng bộ `config.yaml`, `.env` và runtime

## Vấn đề

Admin Web đang ghi `allowed_users`, `admin_users` và `allowed_groups` vào
`gateway.platforms.zalo.extra` trong `config.yaml`, đồng thời áp dụng cấu hình
mới vào adapter đang chạy. Tuy nhiên profile `.env` vẫn giữ giá trị cũ. Khi
gateway khởi động lại, các biến `ZALO_ALLOWED_USERS`, `ZALO_ADMIN_USERS` và
`ZALO_ALLOWED_GROUPS` trong `.env` được ưu tiên hơn YAML, làm mất quyền vừa cấp
trên Web dù giao diện vẫn hiển thị cấu hình đã lưu.

## Mục tiêu

- Một lần bấm **Lưu và áp dụng** cập nhật đồng nhất YAML, `.env` và runtime.
- Quyền mới có hiệu lực ngay, không cần restart.
- Sau restart, runtime nạp đúng cùng allowlist đã hiển thị trên Web.
- Chỉ ba biến allowlist được sửa; token, API key, password hash, session secret,
  comment và các biến không liên quan phải được giữ nguyên.
- Nếu ghi file hoặc áp dụng runtime thất bại, hệ thống quay lại cấu hình cũ ở
  cả YAML, `.env` và runtime.

## Không thuộc phạm vi

- Không đổi API Admin Web, giao diện, schema SQLite hoặc migration.
- Không tự restart gateway khi lưu.
- Không chuyển secret từ `.env` sang YAML.
- Không thay đổi mô hình quyền trusted-team, mention gate hay admin boundary.

## Thiết kế

### Nguồn cấu hình

Admin Web tiếp tục đọc cấu hình hiển thị từ `config.yaml`. Ba biến dưới đây là
bản sao khởi động của cùng dữ liệu và phải được cập nhật trong cùng thao tác:

| YAML | `.env` |
|---|---|
| `allowed_users` | `ZALO_ALLOWED_USERS` |
| `admin_users` | `ZALO_ADMIN_USERS` |
| `allowed_groups` | `ZALO_ALLOWED_GROUPS` |

Giá trị `.env` dùng chuỗi ID phân cách bằng dấu phẩy, được chuẩn hóa, loại trùng
và sắp xếp giống YAML. Việc ưu tiên biến môi trường khi khởi động được giữ
nguyên; lỗi được loại bỏ vì hai nguồn luôn có cùng giá trị sau thao tác quản trị.

### Ghi `.env` có phạm vi

`AtomicConfigFile` nhận đường dẫn `.env` của cùng Hermes profile. Bộ ghi env:

1. Đọc toàn bộ nội dung hiện hữu dưới dạng text.
2. Chỉ thay thế hoặc bổ sung ba biến allowlist nêu trên.
3. Giữ nguyên mọi dòng khác, bao gồm comment và secret.
4. Ghi file tạm trong cùng thư mục, `flush` + `fsync`, đặt mode `0600`, rồi
   `os.replace` sang file thật.
5. Không log nội dung `.env` hoặc giá trị secret.

Nếu `.env` chưa tồn tại, hệ thống tạo file mới với mode `0600`. Không sử dụng
shell, `source` hoặc nối chuỗi command để sửa file.

### Giao dịch cấu hình

Luồng **Lưu và áp dụng** giữ lock cấu hình hiện có và thực hiện:

1. Kiểm tra fingerprint chống ghi đè cấu hình Web cũ.
2. Chuẩn hóa và validate candidate, gồm invariant admin là tập con của member.
3. Giữ snapshot YAML, `.env` và runtime trước thay đổi.
4. Ghi YAML và bản sao allowlist vào `.env`.
5. Áp dụng `CompanyConfig` mới trực tiếp vào adapter.
6. Trả fingerprint mới cho Web.

Nếu bước 4 hoặc 5 thất bại, YAML và `.env` được khôi phục từ snapshot; runtime
được trả về `CompanyConfig` trước thay đổi. Phản hồi Web giữ contract lỗi hiện
có và không trả nội dung secret.

Mọi đường thay đổi access dùng chung `AdminService.apply_access_config`, bao gồm
Admin Web và lệnh admin qua chat, nên không còn đường nào chỉ sửa một nguồn.

## Khởi tạo khi nâng cấp VPS

Trong lần triển khai đầu tiên, lấy snapshot allowlist hiện có trong YAML và gọi
chính luồng đồng bộ để cập nhật ba biến `.env`. Backup `config.yaml` và `.env`
được tạo trước khi chạy. Sau đó restart gateway một lần và xác minh thành viên
vừa cấp quyền vẫn nhắn được.

## Kiểm thử bắt buộc

1. Tái hiện regression: YAML có Tiny, `.env` chỉ có admin; cấu hình startup loại
   Tiny trước fix.
2. Sau apply, `.env` chứa Tiny và reload startup giữ Tiny trong `allowed_users`.
3. Cập nhật member/admin/group cùng lúc tạo ba biến đã chuẩn hóa.
4. API key, bridge token, password hash, session secret, comment và biến lạ giữ
   nguyên byte nội dung dòng của chúng.
5. `.env` mới hoặc được thay thế có mode `0600` trên POSIX.
6. Ghi `.env` thất bại không để YAML ở trạng thái mới.
7. Runtime apply thất bại rollback YAML, `.env` và runtime.
8. Fingerprint cũ vẫn trả `409` và không thay đổi bất kỳ nguồn nào.
9. Test Admin Web apply xác nhận response thành công chỉ sau khi cả ba nguồn đã
   đồng nhất.
10. Toàn bộ Node, Python, integration, static acceptance và `git diff --check`
    vẫn pass.

## Tiêu chí nghiệm thu VPS

- `config.yaml` và `.env` chứa cùng ba tập ID.
- Tiny và Tí Nị nhắn DM được ngay sau khi Web lưu.
- Restart gateway xong hai thành viên vẫn nhắn được.
- Bridge, gateway và Admin Web đều active; asset Web tiếp tục trả HTTP 200.
- Không có secret nào xuất hiện trong log, diff, checkpoint hoặc response API.
