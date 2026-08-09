# Thiết kế trợ lý công ty Hermes trên Zalo

Ngày: 2026-08-09

Trạng thái: Thiết kế hội thoại đã được người dùng duyệt; bản đặc tả viết này đang chờ người dùng rà soát lần cuối.

## 1. Tóm tắt

Dự án tạo một fork nội bộ từ `cuongdev/hermes-zalo-plugin@1.0.9`, dùng `RFS-ADRENO/zca-js@2.1.2` để kết nối một tài khoản Zalo công ty với một Hermes Agent chạy liên tục trên VPS Linux.

Công ty có năm người và các thành viên đều được tin cậy. Mọi Zalo ID trong allowlist được dùng toàn bộ tool thông thường của Hermes và toàn bộ chức năng vận hành của `zca-js` mà không cần quản trị viên duyệt từng thao tác. Quản trị viên có thêm quyền quản lý bot, thành viên, memory, cấu hình, QR, dịch vụ và lịch sử hội thoại.

Bot lưu toàn bộ chat riêng của thành viên và toàn bộ tin nhắn trong các group công ty, kể cả tin nhắn không mention bot. Mention chỉ quyết định bot có gọi Hermes và trả lời hay không; mention không quyết định việc lưu dữ liệu.

Thiết kế ưu tiên sự đơn giản. Không có approval broker, mã duyệt, policy nhiều tầng hoặc audit ledger phức tạp.

## 2. Baseline

- Plugin Zalo: tag `v1.0.9`, commit `b30cf000e62a02f5da304d17556e28ddcb2d4ca2`.
- Thư viện Zalo: `zca-js@2.1.2`.
- Hermes Agent: `0.19.0`.
- Môi trường triển khai: Ubuntu 22.04 hoặc 24.04, Node.js 22, Python 3.11 và systemd.
- Mô hình: một công ty, một tài khoản Zalo, một Hermes Agent và một VPS.

## 3. Quyết định đã chốt

1. Chỉ người có Zalo ID trong `allowed_users` được chat riêng với bot hoặc kích hoạt Hermes trong group.
2. Mọi tin nhắn trong `allowed_groups` được lưu, không phụ thuộc sender có trong allowlist hay bot có được mention hay không.
3. Trong group, bot chỉ gọi Hermes khi một thành viên trong allowlist mention bot.
4. Chat riêng của mỗi thành viên có session và lịch sử riêng.
5. Mỗi group có một session chung.
6. Mọi thành viên trong allowlist dùng tool Hermes và chức năng Zalo ngay, không cần approval.
7. Một tool Zalo đa năng cung cấp `list`, `describe` và `call` cho toàn bộ bề mặt `zca-js`.
8. Admin có toàn bộ quyền của thành viên và thêm quyền quản trị bot.
9. Mọi thành viên được đọc memory chung; chỉ admin được thêm, sửa hoặc xóa memory chung.
10. Cookie, token, API key, mật khẩu và session context không được trả qua chat hoặc ghi vào log.
11. Media không quá 20 MiB được tải và lưu; media lớn hơn chỉ lưu metadata và URL.
12. Hội thoại được giữ lâu dài cho tới khi admin xuất hoặc xóa.
13. Khi gọi Hermes, group nhận 100 tin nhắn gần nhất; lịch sử cũ được truy vấn bằng tool tìm kiếm.

## 4. Mục tiêu

Phiên bản đầu phải:

- Cho năm thành viên trao đổi tự nhiên với Hermes như một thư ký công ty.
- Cho thành viên dùng đọc/ghi file, terminal, email, hệ thống nội bộ và các tool Hermes khác ngay lập tức.
- Cho thành viên dùng mọi chức năng Zalo như gửi tin, file, sticker, voice, reaction, undo, poll, friend, group, reminder và các method khác của `zca-js`.
- Tách đúng lịch sử chat riêng và group.
- Ghi lại hội thoại group ngay cả khi bot không được mention.
- Cung cấp ngữ cảnh hội thoại gần và khả năng tìm lịch sử cũ cho Hermes.
- Cho admin quản lý allowlist, admin list, memory, cấu hình, QR, dịch vụ, log và lịch sử.
- Hoạt động lại sau khi bridge, Hermes hoặc VPS restart mà không ghi trùng tin nhắn.

## 5. Ngoài phạm vi

Phiên bản đầu không:

- Hỗ trợ nhiều công ty hoặc nhiều tài khoản Zalo.
- Dùng Zalo Official Account API.
- Xây approval broker hoặc yêu cầu mã duyệt cho từng hành động.
- Xây quyền theo phòng ban hoặc theo từng method Zalo.
- Cung cấp hệ thống audit chống sửa đổi dành cho tuân thủ pháp lý.
- Cam kết tránh việc tài khoản bị Zalo giới hạn hoặc khóa.

## 6. Kiến trúc

Hệ thống có sáu thành phần nhỏ.

### 6.1 ZaloClient

`ZaloClient` sở hữu kết nối `zca-js`:

- Đăng nhập bằng cookie hoặc QR.
- Duy trì cookie, keepalive và reconnect.
- Nhận message, reaction, undo, friend event và group event.
- Chuẩn hóa event trước khi chuyển cho bridge.
- Gửi hoặc thực hiện method Zalo.

Không thu gọn `zca-js` thành transport tối thiểu. Bề mặt chức năng đầy đủ được giữ lại để phục vụ nhóm người dùng tin cậy.

### 6.2 Zalo bridge

Node bridge:

- Chỉ bind `127.0.0.1`.
- Yêu cầu token nội bộ cho mọi route.
- Giữ các route chức năng hiện có và `POST /api/:method`.
- Phát event cho Python adapter qua SSE.
- Không quyết định role thành viên hoặc admin.

Bridge vẫn kiểm tra method tồn tại trước khi gọi và chuẩn hóa `ThreadType.User/Group`.

### 6.3 Hermes Zalo adapter

Python adapter:

- Xác định chat riêng hoặc group.
- Lưu event hội thoại trước mention gate.
- Kiểm tra allowlist khi quyết định gọi Hermes.
- Tạo session source đúng cho DM hoặc group.
- Gửi câu trả lời và media về Zalo.
- Đăng ký tool `zalo`, `zalo_admin` và tool tìm kiếm lịch sử.

### 6.4 Conversation Store

SQLite là nguồn dữ liệu chính cho hội thoại, attachment và hoạt động tool. Media được lưu trên filesystem, còn SQLite chỉ lưu metadata và đường dẫn.

### 6.5 Hermes Agent

Hermes giữ vai trò thư ký:

- Hiểu yêu cầu bằng ngôn ngữ tự nhiên.
- Dùng tool Hermes hoặc tool Zalo đa năng.
- Đọc 100 tin nhắn gần nhất của session.
- Tìm lịch sử cũ khi cần.
- Dùng memory chung của công ty.

### 6.6 Admin Guard

Admin Guard là lớp quyền nhỏ, không phải approval system. Nó chỉ bảo vệ các thao tác quản trị bot:

- Sửa `allowed_users` hoặc `admin_users`.
- Thay đổi memory chung.
- Sửa cấu hình bot/Hermes hoặc secret.
- Login QR, start, stop hoặc restart dịch vụ.
- Xuất hoặc xóa lịch sử.

Nếu requester không phải admin, thao tác bị từ chối ngay. Nếu là admin, thao tác chạy ngay, không cần xác nhận lần hai.

## 7. Định danh và quyền

### 7.1 Thành viên

Thành viên là Zalo ID nằm trong `allowed_users`.

Thành viên được:

- Chat với Hermes trong DM.
- Mention bot trong group được phép.
- Dùng toàn bộ tool Hermes thông thường ngay lập tức.
- Dùng `zalo list`, `zalo describe` và `zalo call` cho mọi method vận hành của `zca-js`.
- Đọc memory chung và tìm lịch sử mà họ được phép xem.

Thành viên không được:

- Dùng `zalo_admin`.
- Sửa allowlist, admin list, cấu hình bot hoặc service.
- Thêm, sửa hoặc xóa memory chung.
- Đọc chat riêng của thành viên khác.
- Nhận secret qua chat.

### 7.2 Admin

Admin là Zalo ID nằm trong cả `admin_users` và `allowed_users`.

Admin được toàn bộ quyền của thành viên và thêm:

- Quản lý thành viên và admin.
- Quản lý memory chung.
- Xem trạng thái, log đã redact và dung lượng lịch sử/media.
- Export hoặc xóa lịch sử theo DM/group/khoảng thời gian.
- Login lại QR và quản lý service.
- Sửa cấu hình bot/Hermes.

Hệ thống không cho xóa admin cuối cùng để tránh mất quyền quản trị.

### 7.3 Ranh giới secret

Các method hoặc kết quả dùng để xuất credential như `getCookie`, `getContext`, token, API key và mật khẩu không được trả về chat cho bất kỳ role nào. QR login và secret chỉ được xử lý trong admin flow đã redact hoặc trực tiếp trên VPS.

Đây là ranh giới cố định duy nhất ngoài Admin Guard.

## 8. Tool Zalo đa năng

Tool duy nhất dành cho thành viên có dạng:

```text
zalo(action="list", query="group")
zalo(action="describe", method="createPoll")
zalo(action="call", method="createPoll", params={...})
zalo(action="call", method="customMethod", args=[...])
```

### 8.1 `list`

- Liệt kê method theo nhóm hoặc từ khóa.
- Trả tên, mô tả ngắn và mức hỗ trợ schema.
- Không liệt kê method xuất credential như một capability có thể gọi qua chat.

### 8.2 `describe`

- Trả parameter, kiểu dữ liệu, mặc định và ví dụ.
- Catalog được tạo và kiểm thử theo `zca-js@2.1.2`.
- Hermes có thể gọi `describe` trước khi gọi một method ít dùng.

### 8.3 `call`

- `params` là object theo tên parameter khi catalog có schema.
- `args` là positional array fallback để bảo đảm mọi method còn lại vẫn dùng được.
- Method phải tồn tại trên live API object.
- `user` và `group` được đổi thành enum `ThreadType` khi cần.
- Kết quả được redact trước khi trả cho Hermes và người dùng.
- Không có bước approval.

### 8.4 Tool admin

Tool `zalo_admin` có các action đầu tiên:

```text
status
add_user
remove_user
add_admin
remove_admin
memory_add
memory_update
memory_delete
history_export
history_delete
login_qr
restart
stop
start
show_logs
```

Mỗi action kiểm tra `requester_id` thuộc `admin_users` trước khi thực hiện.

## 9. Lưu hội thoại

### 9.1 Group

Với mọi group trong `allowed_groups`:

1. Nhận event từ Zalo.
2. Chống trùng bằng khóa event/message ổn định.
3. Lưu event vào Conversation Store.
4. Nếu là message có attachment, xử lý attachment theo giới hạn media.
5. Sau khi lưu thành công mới kiểm tra mention.
6. Không mention: kết thúc, bot im lặng.
7. Có mention từ sender trong `allowed_users`: gọi Hermes bằng session group.
8. Có mention từ sender ngoài allowlist: vẫn lưu nhưng không gọi Hermes.

Tin nhắn của mọi thành viên trong group được lưu, không chỉ năm người trong allowlist.

### 9.2 Chat riêng

- Chỉ DM của sender trong `allowed_users` được lưu vào lịch sử thành viên và gọi Hermes.
- Mỗi sender có một session DM riêng.
- Tin nhắn và câu trả lời của bot đều được lưu.
- Người ngoài allowlist nhận thông báo không có quyền với tần suất giới hạn, sau đó bot im lặng.

### 9.3 Event được lưu

Conversation Store ghi:

- Text message.
- Reply và quote metadata.
- Mention metadata.
- Attachment metadata.
- Reaction và undo liên quan tới message.
- Bot outbound message.
- Timestamp và sender identity.

Typing event không cần lưu lâu dài.

## 10. Media

Với mỗi ảnh, file, voice hoặc video:

- Kích thước không quá 20 MiB: tải và lưu cục bộ.
- Kích thước lớn hơn 20 MiB: chỉ lưu tên, loại, MIME, kích thước và URL.
- Không biết trước kích thước: stream và dừng khi vượt 20 MiB.
- Download lỗi: vẫn lưu message và metadata với trạng thái `failed`.
- Chống tải trùng bằng message ID và attachment index.
- Filename được làm sạch trước khi ghi.

Thư mục mặc định:

```text
<HERMES_HOME>/zalo-company/history/media/<thread-type>/<thread-id>/<YYYY-MM-DD>/
```

Admin có thể xem dung lượng, export hoặc xóa media cùng lịch sử liên quan.

## 11. Session và ngữ cảnh Hermes

### 11.1 Session key

- DM: một session cho mỗi Zalo ID thành viên.
- Group: một session chung cho mỗi group ID.
- DM và group không dùng chung conversation history.

### 11.2 Context gần

Khi gọi Hermes, adapter cung cấp tối đa 100 message gần nhất của session theo thứ tự thời gian. Context gồm text, sender, timestamp, reply, mention và attachment summary; không nhúng toàn bộ binary media.

### 11.3 Tìm lịch sử cũ

Tool `zalo_history` hỗ trợ:

```text
search
recent
get_message
get_attachment
```

Thành viên chỉ được tìm:

- DM của chính mình.
- Group nằm trong `allowed_groups`.

Admin được tìm hoặc export mọi conversation của công ty.

## 12. Memory chung

- Mọi thành viên được đọc memory chung.
- Chỉ admin được gọi action memory ghi, sửa hoặc xóa.
- Hội thoại không tự động được ghi vào memory.
- Admin có thể yêu cầu Hermes đọc lịch sử rồi chủ động lưu một kết luận vào memory.
- Memory write chạy ngay sau khi role check, không có approval code.

Admin Guard phải áp dụng cả khi người dùng cố sửa memory bằng `write_file`, `patch`, terminal hoặc execute-code, không chỉ qua tool `memory`.

## 13. Mô hình dữ liệu

SQLite có năm bảng chính.

### 13.1 `conversations`

- `id`
- `thread_type`: `dm` hoặc `group`
- `thread_id`
- `title`
- `created_at`
- `last_message_at`
- Unique theo `thread_type + thread_id`.

### 13.2 `messages`

- `id`
- `conversation_id`
- `provider_message_id`
- `provider_cli_message_id`
- `sender_id`
- `sender_name`
- `text`
- `is_bot`
- `mentioned_bot`
- `reply_to_message_id`
- `sent_at`
- `stored_at`
- `recalled_at`
- `extra_json` cho normalized metadata không nhạy cảm.

Message có unique dedupe key theo account, thread và provider IDs.

### 13.3 `message_events`

- Reaction, undo và các event liên quan message.
- Giữ event type, actor, timestamp và normalized payload.

### 13.4 `attachments`

- Liên kết tới message.
- Index trong message.
- Kind, filename, MIME, kích thước, URL.
- Local path, SHA-256 và trạng thái download.

### 13.5 `tool_activity`

Log nhẹ gồm:

- Thời gian.
- Requester Zalo ID.
- DM/group origin.
- Tool name hoặc Zalo method.
- Trạng thái thành công/thất bại/chưa xác định.
- Lỗi đã redact.

Không lưu argument hoặc result chứa secret.

## 14. Luồng dữ liệu

### 14.1 Group không mention

```text
zca-js event
→ normalize
→ dedupe
→ lưu conversation/message/media
→ mention=false
→ kết thúc, không gọi Hermes
```

### 14.2 Group có mention hợp lệ

```text
zca-js event
→ normalize
→ dedupe
→ lưu conversation/message/media
→ sender thuộc allowlist và mention=true
→ tải 100 message gần nhất
→ Hermes xử lý
→ lưu và gửi câu trả lời
```

### 14.3 DM thành viên

```text
zca-js event
→ xác thực allowed user
→ dedupe và lưu
→ tải context DM của chính sender
→ Hermes xử lý
→ lưu và gửi câu trả lời
```

### 14.4 Gọi chức năng Zalo

```text
Hermes chọn method
→ zalo describe nếu cần
→ zalo call
→ bridge /api/:method
→ zca-js
→ redact result
→ lưu tool_activity
→ trả kết quả
```

### 14.5 Admin action

```text
zalo_admin
→ kiểm tra requester trong admin_users
→ thực hiện ngay
→ lưu tool_activity
→ trả kết quả đã redact
```

## 15. Cấu hình

Cấu hình hành vi nằm trong `config.yaml`:

```yaml
gateway:
  platforms:
    zalo:
      extra:
        bridge_url: http://127.0.0.1:8787
        allowed_users:
          - "zalo-id-1"
        admin_users:
          - "zalo-id-1"
        allowed_groups:
          - "group-id-1"
        group_mode: mention
        history_context_messages: 100
        media_max_bytes: 20971520
        history_retention: forever
```

Bridge token và credential nằm ngoài YAML trong secret file hoặc `.env` có quyền hạn chế.

Startup fail nếu:

- Không có admin.
- Admin không nằm trong allowed users.
- Bridge token thiếu.
- Database không thể mở hoặc migrate.

## 16. Xử lý lỗi

### 16.1 Tin nhắn trùng

Unique dedupe key làm lần ghi thứ hai trở thành no-op. Duplicate không gọi Hermes lần hai.

### 16.2 Lỗi lưu lịch sử

Nếu event hợp lệ nhưng Conversation Store không ghi được, adapter không gọi Hermes cho event đó. Bot giữ kết nối và báo admin để tránh có câu trả lời không được lưu.

### 16.3 Zalo mất kết nối

Bridge reconnect có backoff. Session chết hoặc cookie hết hạn được báo cho admin để login QR lại.

### 16.4 Lỗi tool Zalo

- Method không tồn tại: trả lỗi rõ ràng.
- Sai parameter: Hermes có thể gọi `describe` rồi thử lại nếu operation chắc chắn chưa chạy.
- Outcome gửi/mutation chưa rõ: báo `unknown`, không tự chạy lại.
- Rate limit: dừng, backoff và thông báo người dùng.

### 16.5 Media lỗi

Message vẫn được lưu; attachment được đánh dấu `failed` hoặc `metadata_only`.

## 17. Log và mức bảo vệ tối thiểu

Do mọi thành viên được tin cậy, hệ thống không có approval hoặc policy chi tiết. Tuy vậy vẫn giữ bốn bảo vệ vận hành:

1. Allowlist cho người kích hoạt Hermes.
2. Admin Guard cho cấu hình, memory, service và lịch sử quản trị.
3. Bridge loopback cùng token nội bộ.
4. Redaction credential khỏi chat và log.

Không log raw cookie, token, API key, password hoặc IMEI. Nội dung hội thoại nằm trong Conversation Store, không lặp lại vào system journal.

## 18. Triển khai

VPS chạy:

1. Node Zalo bridge.
2. Hermes gateway cùng plugin Zalo.
3. SQLite Conversation Store và thư mục media dưới `HERMES_HOME`.

Hai service chạy bằng Unix user riêng, tự restart khi lỗi và khởi động cùng VPS. QR login chỉ cần lại khi Zalo session hết hạn hoặc bị kick.

## 19. Kiểm thử

### 19.1 Hội thoại

- Group không mention vẫn lưu nhưng không gọi Hermes.
- Group có mention từ allowed user lưu trước rồi gọi Hermes.
- Mention từ user ngoài allowlist được lưu nhưng không gọi Hermes.
- DM thành viên được lưu và phản hồi.
- Hai DM không trộn lịch sử.
- Group không đọc được DM.
- Bot outbound cũng được lưu.

### 19.2 Media

- Media nhỏ hơn hoặc bằng 20 MiB được lưu.
- Media lớn hơn được ghi `metadata_only`.
- Stream vượt cap bị dừng.
- Download lỗi không làm mất message.
- Duplicate event không tải media lần hai.

### 19.3 Tool

- `zalo list` và `describe` trả catalog đúng bản `zca-js`.
- Thành viên gọi được các nhóm send, reaction, undo, poll, friend, group và read API.
- Positional fallback dùng được method không có named schema.
- Result có secret bị redact.
- Outcome không rõ không bị retry mù.

### 19.4 Admin

- Non-admin không dùng được `zalo_admin`.
- Admin thêm/xóa user và admin được.
- Không thể xóa admin cuối cùng.
- Chỉ admin sửa memory chung.
- Admin export/xóa lịch sử và quản lý service được.
- Thành viên không né Admin Guard bằng file, terminal hoặc execute-code.

### 19.5 Restart

- SQLite và media còn nguyên sau restart.
- Event đã lưu không gọi Hermes lần hai.
- Hai service tự lên sau reboot khi Zalo session còn hiệu lực.

## 20. Tiêu chí nghiệm thu

Release đạt khi chứng minh được:

1. Năm thành viên trong allowlist chat được với Hermes.
2. Người ngoài allowlist không kích hoạt Hermes.
3. Mọi message trong group công ty được lưu dù không mention.
4. Group chỉ nhận câu trả lời khi allowed user mention bot.
5. Chat riêng được tách đúng theo thành viên.
6. Hermes nhận đúng 100 message gần nhất và tìm được lịch sử cũ.
7. Media không quá 20 MiB được lưu; media lớn hơn chỉ có metadata.
8. Thành viên dùng được toàn bộ tool Hermes thông thường mà không cần approval.
9. Thành viên dùng được tool Zalo đa năng với toàn bộ method vận hành `zca-js`.
10. Admin dùng được các chức năng quản trị ngay lập tức.
11. Non-admin không sửa được allowlist, config, memory hoặc service.
12. Cookie, token và password không xuất hiện trong chat hoặc log.
13. Duplicate event không tạo message, media hoặc agent turn thứ hai.
14. Outcome Zalo chưa rõ không bị tự động chạy lại.
15. Lịch sử, media và Zalo session hợp lệ sống qua VPS restart.

## 21. Rủi ro còn lại

- `zca-js` là API không chính thức; tài khoản có thể bị challenge, giới hạn hoặc khóa.
- Thành viên có quyền rộng và thao tác chạy ngay. Một yêu cầu nhầm có thể gây gửi nhầm, đổi group hoặc thay đổi dữ liệu trước khi admin can thiệp.
- Một tài khoản Zalo chỉ có một listener web ổn định; hệ thống không active-active.
- Lịch sử và media tăng dần vì retention mặc định là lâu dài; admin cần theo dõi dung lượng và chủ động export/xóa.
- Prompt injection trong tin nhắn hoặc tài liệu có thể khiến Hermes dùng tool sai. Thiết kế chấp nhận rủi ro này vì nhóm nhỏ và các thành viên được tin cậy.

## 22. Thay thế thiết kế cũ

Spec này thay thế thiết kế approval-heavy trước đó. Kế hoạch triển khai cũ có approval broker, mã duyệt, role policy chi tiết, transport tối thiểu và audit SQLite phức tạp không còn là nguồn yêu cầu hợp lệ.

Sau khi người dùng duyệt bản spec viết này, cần viết lại toàn bộ kế hoạch triển khai bằng tiếng Việt theo thiết kế mới; không chỉnh vá kế hoạch cũ.
