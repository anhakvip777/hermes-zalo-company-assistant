CREATE TABLE follow_ups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id TEXT NOT NULL,
    title TEXT NOT NULL,
    question_text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    due_at TEXT NOT NULL,
    state TEXT NOT NULL
        CHECK (state IN ('active', 'awaiting_admin', 'closed')),
    report_state TEXT NOT NULL
        CHECK (report_state IN ('pending', 'sending', 'sent', 'unknown')),
    report_claimed_at TEXT,
    report_sent_at TEXT,
    closed_at TEXT
);

CREATE TABLE follow_up_targets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    follow_up_id INTEGER NOT NULL
        REFERENCES follow_ups(id) ON DELETE CASCADE,
    target_id TEXT NOT NULL,
    target_name TEXT,
    state TEXT NOT NULL CHECK (state IN (
        'initial_sending', 'awaiting_response', 'initial_failed',
        'initial_unknown', 'reminder_sending', 'reminded',
        'reminder_failed', 'reminder_unknown', 'responded'
    )),
    initial_claimed_at TEXT,
    initial_provider_message_id TEXT,
    initial_sent_at TEXT,
    response_message_id INTEGER
        REFERENCES messages(id) ON DELETE SET NULL,
    response_at TEXT,
    response_kind TEXT CHECK (response_kind IN ('yes', 'no', 'other')),
    reminder_provider_message_id TEXT,
    reminder_claimed_at TEXT,
    reminder_sent_at TEXT,
    UNIQUE (follow_up_id, target_id)
);

CREATE INDEX follow_up_targets_pending_due_idx
    ON follow_up_targets(state, follow_up_id);
CREATE INDEX follow_up_targets_target_response_idx
    ON follow_up_targets(target_id, state, initial_sent_at);
CREATE INDEX follow_ups_state_due_idx ON follow_ups(state, due_at);
