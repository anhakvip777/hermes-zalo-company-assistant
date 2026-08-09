CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE TABLE conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    thread_type TEXT NOT NULL CHECK (thread_type IN ('dm', 'group')),
    thread_id TEXT NOT NULL,
    title TEXT,
    created_at TEXT NOT NULL,
    last_message_at TEXT NOT NULL,
    UNIQUE (account_id, thread_type, thread_id)
);

CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL
        REFERENCES conversations(id) ON DELETE CASCADE,
    dedupe_key TEXT NOT NULL UNIQUE,
    provider_message_id TEXT,
    provider_cli_message_id TEXT,
    sender_id TEXT NOT NULL,
    sender_name TEXT,
    text TEXT NOT NULL DEFAULT '',
    is_bot INTEGER NOT NULL DEFAULT 0 CHECK (is_bot IN (0, 1)),
    mentioned_bot INTEGER NOT NULL DEFAULT 0 CHECK (mentioned_bot IN (0, 1)),
    reply_to_message_id INTEGER REFERENCES messages(id),
    quote_json TEXT,
    sent_at TEXT NOT NULL,
    stored_at TEXT NOT NULL,
    recalled_at TEXT,
    extra_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX messages_conversation_sent_at_idx
    ON messages(conversation_id, sent_at DESC);
CREATE INDEX messages_sender_sent_at_idx
    ON messages(sender_id, sent_at DESC);
CREATE INDEX messages_provider_message_id_idx
    ON messages(provider_message_id);

CREATE TABLE message_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER REFERENCES messages(id) ON DELETE SET NULL,
    event_key TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    actor_id TEXT,
    actor_name TEXT,
    occurred_at TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX message_events_message_idx ON message_events(message_id);

CREATE TABLE attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL
        REFERENCES messages(id) ON DELETE CASCADE,
    attachment_index INTEGER NOT NULL,
    kind TEXT NOT NULL,
    filename TEXT,
    mime_type TEXT,
    size_bytes INTEGER,
    remote_url TEXT,
    local_path TEXT,
    sha256 TEXT,
    download_status TEXT NOT NULL
        CHECK (download_status IN ('pending', 'downloaded', 'metadata_only', 'failed')),
    created_at TEXT NOT NULL,
    UNIQUE (message_id, attachment_index)
);

CREATE INDEX attachments_message_idx ON attachments(message_id);

CREATE TABLE tool_activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,
    requester_id TEXT NOT NULL,
    thread_type TEXT NOT NULL
        CHECK (thread_type IN ('dm', 'group', 'system')),
    thread_id TEXT,
    tool_name TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK (status IN ('success', 'failed', 'unknown', 'blocked')),
    error_text TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX tool_activity_requester_time_idx
    ON tool_activity(requester_id, occurred_at DESC);
