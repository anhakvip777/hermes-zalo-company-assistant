# Schema SQLite Conversation Store

Schema khóa cho `company-assistant-v1`. Migration đầu tiên là `hermes-plugin/migrations/001_initial.sql`; migration đã áp dụng không được sửa, mọi thay đổi sau đó phải dùng file `002_*.sql` trở lên.

## Nguyên tắc

- SQLite bật `foreign_keys=ON`, WAL và busy timeout.
- Mỗi thao tác inbound message + attachments metadata + `last_message_at` nằm trong một transaction.
- `dedupe_key` là duy nhất trong toàn bộ một tài khoản Zalo: `account_id|thread_type|thread_id|provider_message_id|provider_cli_message_id`; nếu provider không gửi ID thì dùng event ID ổn định do normalizer tạo.
- Insert trùng trả `inserted=false`, không ném lỗi nghiệp vụ.
- `audit`/`tool_activity` không chứa raw arguments hoặc result có thể có secret.
- Timestamps lưu ISO-8601 UTC.

## Bảng

### `schema_migrations`

`version INTEGER PRIMARY KEY`, `name TEXT NOT NULL`, `checksum TEXT NOT NULL`, `applied_at TEXT NOT NULL`.

### `conversations`

`id INTEGER PRIMARY KEY`, `account_id TEXT NOT NULL`, `thread_type TEXT CHECK(thread_type IN ('dm','group'))`, `thread_id TEXT NOT NULL`, `title TEXT`, `created_at TEXT NOT NULL`, `last_message_at TEXT NOT NULL`, `UNIQUE(account_id, thread_type, thread_id)`.

### `messages`

`id INTEGER PRIMARY KEY`, `conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE`, `dedupe_key TEXT NOT NULL UNIQUE`, `provider_message_id TEXT`, `provider_cli_message_id TEXT`, `sender_id TEXT NOT NULL`, `sender_name TEXT`, `text TEXT NOT NULL DEFAULT ''`, `is_bot INTEGER NOT NULL DEFAULT 0`, `mentioned_bot INTEGER NOT NULL DEFAULT 0`, `reply_to_message_id INTEGER REFERENCES messages(id)`, `quote_json TEXT`, `sent_at TEXT NOT NULL`, `stored_at TEXT NOT NULL`, `recalled_at TEXT`, `extra_json TEXT NOT NULL DEFAULT '{}'`.

Indexes: `(conversation_id, sent_at DESC)`, `(sender_id, sent_at DESC)`, `(provider_message_id)`.

### `message_events`

`id INTEGER PRIMARY KEY`, `message_id INTEGER REFERENCES messages(id) ON DELETE SET NULL`, `event_key TEXT NOT NULL UNIQUE`, `event_type TEXT NOT NULL`, `actor_id TEXT`, `actor_name TEXT`, `occurred_at TEXT NOT NULL`, `payload_json TEXT NOT NULL DEFAULT '{}'`.

### `attachments`

`id INTEGER PRIMARY KEY`, `message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE`, `attachment_index INTEGER NOT NULL`, `kind TEXT NOT NULL`, `filename TEXT`, `mime_type TEXT`, `size_bytes INTEGER`, `remote_url TEXT`, `local_path TEXT`, `sha256 TEXT`, `download_status TEXT CHECK(download_status IN ('pending','downloaded','metadata_only','failed')) NOT NULL`, `created_at TEXT NOT NULL`, `UNIQUE(message_id, attachment_index)`.

### `tool_activity`

`id INTEGER PRIMARY KEY`, `occurred_at TEXT NOT NULL`, `requester_id TEXT NOT NULL`, `thread_type TEXT CHECK(thread_type IN ('dm','group','system'))`, `thread_id TEXT`, `tool_name TEXT NOT NULL`, `status TEXT CHECK(status IN ('success','failed','unknown','blocked')) NOT NULL`, `error_text TEXT`, `metadata_json TEXT NOT NULL DEFAULT '{}'`.

## Migration runner

`state_store.py` đọc các migration theo số thứ tự, tính SHA-256 trên bytes UTF-8 và so với `schema_migrations`. Nếu checksum của version đã áp dụng đổi, startup fail. Mỗi migration chạy trong transaction; chỉ insert vào `schema_migrations` sau khi script thành công.

## Xóa/export

Admin export tạo JSONL/manifest media theo conversation hoặc khoảng thời gian trong thư mục tạm dưới `HERMES_HOME/zalo-company/exports`. Admin delete xóa message/attachment theo filter và binary media liên quan trong cùng một thao tác best-effort; kết quả trả số dòng đã xóa.
