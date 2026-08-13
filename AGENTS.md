# Quy tắc tiếp tục công việc qua compact hoặc phiên mới

Tệp này là điểm vào bắt buộc cho mọi agent làm việc trong repository. Sau khi
context bị compact, mở lại phiên hoặc nhận bàn giao, không được bắt đầu sửa mã
trước khi hoàn tất trình tự dưới đây.

## Nguồn chuẩn phải đọc trước

1. `docs/architecture/system-overview.md` — kiến trúc process, trust boundary và
   data flow đã khóa.
2. `docs/architecture/database-schema.md` — schema SQLite, các bảng và SHA-256
   của migration bất biến.
3. `docs/architecture/file-manifest.md` — danh sách file được phép duy nhất.
4. Spec và kế hoạch đang hoạt động trong `docs/superpowers/specs/` và
   `docs/superpowers/plans/`; đọc mục **Checkpoint phiên làm việc** trước.

Nếu nội dung tóm tắt của phiên chat mâu thuẫn với các tệp trên, repository là
nguồn đúng. Không tự tạo service/process mới, không đổi schema hoặc
`hermes-plugin/migrations/001_initial.sql`, và không tạo file ngoài manifest.

## Trình tự khôi phục sau compact

1. Chạy `git status --short` và giữ nguyên mọi thay đổi hiện có.
2. Đọc bốn nguồn chuẩn phía trên.
3. Chạy `python scripts/acceptance.py --static --json`.
4. Đối chiếu file định sửa với `docs/architecture/file-manifest.md`.
5. Tiếp tục đúng mục `Việc tiếp theo` trong checkpoint; không làm lại task đã
   được đánh dấu hoàn thành nếu working tree vẫn chứa kết quả.

## Nội dung phải ưu tiên giữ trong bản tóm tắt compact

Theo thứ tự ưu tiên:

1. Kiến trúc hệ thống và ranh giới process.
2. Schema/database, tên migration và checksum khóa.
3. Danh sách file trong manifest và quy tắc không tạo file ngoài danh sách.
4. Task đã hoàn thành, test đã chạy và việc tiếp theo.
5. Lỗi/blocker còn mở.

Có thể bỏ log dài, output test cũ và chi tiết thảo luận trước khi bỏ năm nhóm
thông tin trên.

## Trước khi kết thúc một lượt triển khai

- Cập nhật mục **Checkpoint phiên làm việc** trong kế hoạch đang hoạt động.
- Ghi lệnh test mới nhất cùng số pass/fail thực tế.
- Chạy lại static acceptance và `git diff --check`.
- Không ghi secret, cookie, token hoặc credential vào checkpoint.
