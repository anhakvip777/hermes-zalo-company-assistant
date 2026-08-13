from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from history_store import HistoryStore, MigrationChecksumError, redact_text


EXPECTED_TABLES = {
    "schema_migrations",
    "conversations",
    "messages",
    "message_events",
    "attachments",
    "tool_activity",
}


def make_store(tmp_path: Path) -> HistoryStore:
    return HistoryStore(tmp_path / "history.sqlite3", account_id="company-zalo")


def test_contact_cards_before_single_returns_nearest_contact_in_same_conversation(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    first = store.store_message(
        thread_type="group",
        thread_id="g-1",
        sender_id="u-1",
        text="[contact: Lan]",
        provider_message_id="card-1",
        extra={"contact": {"name": "Lan", "phone": "0901", "gUid": "uid-lan"}},
    )
    store.store_message(
        thread_type="group",
        thread_id="g-1",
        sender_id="u-2",
        text="tin xen giữa",
        provider_message_id="normal-1",
    )
    command = store.store_message(
        thread_type="group",
        thread_id="g-1",
        sender_id="admin",
        text="kết bạn người này",
        provider_message_id="command-1",
    )

    cards = store.contact_cards_before(
        message_id=command.message_id,
        thread_type="group",
        thread_id="g-1",
        multiple=False,
    )

    assert cards == [
        {
            "message_id": first.message_id,
            "sender_id": "u-1",
            "name": "Lan",
            "phone": "0901",
            "gUid": "uid-lan",
        }
    ]


def test_contact_cards_before_multiple_returns_only_contiguous_cards_in_order(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    store.store_message(
        thread_type="group",
        thread_id="g-1",
        sender_id="u-1",
        text="[contact: Cu]",
        provider_message_id="card-old",
        extra={"contact": {"name": "Cu", "gUid": "uid-cu"}},
    )
    store.store_message(
        thread_type="group",
        thread_id="g-1",
        sender_id="u-2",
        text="tin ngắt cụm",
        provider_message_id="normal-1",
    )
    for provider_id, name, uid in (
        ("card-minh", "Minh", "uid-minh"),
        ("card-hung", "Hùng", "uid-hung"),
    ):
        store.store_message(
            thread_type="group",
            thread_id="g-1",
            sender_id="u-2",
            text=f"[contact: {name}]",
            provider_message_id=provider_id,
            extra={"contact": {"name": name, "gUid": uid}},
        )
    command = store.store_message(
        thread_type="group",
        thread_id="g-1",
        sender_id="admin",
        text="kết bạn những người này",
        provider_message_id="command-1",
    )

    cards = store.contact_cards_before(
        message_id=command.message_id,
        thread_type="group",
        thread_id="g-1",
        multiple=True,
    )

    assert [item["gUid"] for item in cards] == ["uid-minh", "uid-hung"]


def test_contact_cards_before_multiple_stops_at_previous_message(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    store.store_message(
        thread_type="group",
        thread_id="g-1",
        sender_id="u-1",
        text="[contact: Lan]",
        provider_message_id="card-1",
        extra={"contact": {"name": "Lan", "gUid": "uid-lan"}},
    )
    store.store_message(
        thread_type="group",
        thread_id="g-1",
        sender_id="u-2",
        text="tin ngắt cụm",
        provider_message_id="normal-1",
    )
    command_after_text = store.store_message(
        thread_type="group",
        thread_id="g-1",
        sender_id="admin",
        text="kết bạn những người này",
        provider_message_id="command-1",
    )

    assert store.contact_cards_before(
        message_id=command_after_text.message_id,
        thread_type="group",
        thread_id="g-1",
        multiple=True,
    ) == []


def test_admin_history_pages_filter_order_and_decode_metadata(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    for index in range(3):
        store.store_message(
            thread_type="group",
            thread_id="g-1",
            sender_id=f"u-{index}",
            text=f"báo giá {index}",
            provider_message_id=f"m-{index}",
            sent_at=f"2026-08-10T0{index}:00:00Z",
            attachments=[
                {
                    "kind": "file",
                    "filename": f"f-{index}.txt",
                    "download_status": "pending",
                }
            ],
        )
    store.store_message(
        thread_type="dm",
        thread_id="u-1",
        sender_id="u-1",
        text="riêng",
        provider_message_id="dm-1",
        sent_at="2026-08-10T04:00:00Z",
    )
    for index in range(3):
        store.log_tool_activity(
            requester_id="web-admin" if index < 2 else "u-1",
            thread_type="system" if index < 2 else "dm",
            thread_id="admin-web" if index < 2 else "u-1",
            tool_name=f"admin_web.action_{index}",
            status="success",
            metadata={"index": index},
            occurred_at=f"2026-08-10T05:00:0{index}Z",
        )

    conversations = store.list_conversations(limit=1, offset=0)
    assert len(conversations["items"]) == 1
    assert conversations["next_offset"] == 1
    group = next(
        item
        for item in store.list_conversations(limit=10)["items"]
        if item["thread_id"] == "g-1"
    )
    messages = store.page_messages(
        group["id"],
        query="báo giá",
        limit=2,
        offset=0,
    )
    assert [item["text"] for item in messages["items"]] == [
        "báo giá 1",
        "báo giá 2",
    ]
    assert messages["items"][0]["attachments"][0]["filename"] == "f-1.txt"
    assert messages["next_offset"] == 2
    activity = store.page_tool_activity(requester_id="web-admin", limit=10)
    assert [item["metadata"]["index"] for item in activity["items"]] == [1, 0]
    with pytest.raises(ValueError, match="offset"):
        store.page_messages(group["id"], offset=-1)


def test_conversation_query_matches_metadata_or_message_without_narrowing_count(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    for index, text in enumerate(("không khớp", "kim chỉ nam", "cũng không")):
        store.store_message(
            thread_type="group",
            thread_id="g-message",
            title="Nhóm vận hành",
            sender_id="u-1",
            text=text,
            provider_message_id=f"message-{index}",
        )
    store.store_message(
        thread_type="group",
        thread_id="g-title",
        title="Kim cương",
        sender_id="u-1",
        text="nội dung khác",
        provider_message_id="title-match",
    )
    store.store_message(
        thread_type="dm",
        thread_id="kim-thread",
        sender_id="kim-thread",
        text="nội dung khác",
        provider_message_id="thread-match",
    )
    store.store_message(
        thread_type="group",
        thread_id="g-ignored",
        title="Không liên quan",
        sender_id="u-1",
        text="nội dung khác",
        provider_message_id="ignored",
    )

    items = store.list_conversations(query="kim", limit=10)["items"]

    assert {item["thread_id"] for item in items} == {
        "g-message",
        "g-title",
        "kim-thread",
    }
    message_match = next(
        item for item in items if item["thread_id"] == "g-message"
    )
    assert message_match["message_count"] == 3


def test_initial_migration_builds_locked_schema(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    tables = {
        row[0]
        for row in store.connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    assert tables == EXPECTED_TABLES
    assert store.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_applied_migration_checksum_drift_fails(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    source = Path("hermes-plugin/migrations/001_initial.sql")
    migration = migrations / source.name
    migration.write_bytes(source.read_bytes())

    db_path = tmp_path / "history.sqlite3"
    HistoryStore(db_path, migrations_dir=migrations).close()
    migration.write_text(migration.read_text(encoding="utf-8") + "\n-- drift\n", encoding="utf-8")

    with pytest.raises(MigrationChecksumError):
        HistoryStore(db_path, migrations_dir=migrations)


def test_store_message_is_idempotent_and_does_not_duplicate_attachment(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    payload = dict(
        thread_type="group",
        thread_id="g-1",
        sender_id="u-1",
        sender_name="An",
        text="họp lúc 9 giờ",
        provider_message_id="m-1",
        provider_cli_message_id="c-1",
        sent_at="2026-08-09T01:00:00Z",
        attachments=[
            {
                "kind": "file",
                "filename": "ke-hoach.pdf",
                "mime_type": "application/pdf",
                "size_bytes": 123,
                "remote_url": "https://example.invalid/file",
                "download_status": "pending",
            }
        ],
    )

    first = store.store_message(**payload)
    second = store.store_message(**payload)

    assert first.inserted is True
    assert second.inserted is False
    assert second.message_id == first.message_id
    assert store.connection.execute("SELECT count(*) FROM messages").fetchone()[0] == 1
    assert store.connection.execute("SELECT count(*) FROM attachments").fetchone()[0] == 1


def test_provider_ids_take_precedence_over_event_id_for_dedupe(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    payload = dict(
        thread_type="group",
        thread_id="g-1",
        sender_id="u-1",
        text="cùng một tin nhắn provider",
        provider_message_id="m-provider-1",
    )

    first = store.store_message(**payload, event_id="delivery-event-1")
    duplicate = store.store_message(**payload, event_id="delivery-event-2")

    assert first.inserted is True
    assert duplicate.inserted is False
    assert duplicate.message_id == first.message_id
    assert store.connection.execute("SELECT count(*) FROM messages").fetchone()[0] == 1


def test_provider_message_and_cli_id_keep_distinct_dedupe_positions(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    provider_message = store.store_message(
        thread_type="group",
        thread_id="g-1",
        sender_id="u-1",
        provider_message_id="same-id",
    )
    provider_cli_message = store.store_message(
        thread_type="group",
        thread_id="g-1",
        sender_id="u-1",
        provider_cli_message_id="same-id",
    )

    assert provider_message.inserted is True
    assert provider_cli_message.inserted is True
    assert provider_message.message_id != provider_cli_message.message_id


def test_recent_messages_returns_latest_in_chronological_order_and_caps_at_100(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    for index in range(105):
        store.store_message(
            thread_type="group",
            thread_id="g-1",
            sender_id=f"u-{index % 3}",
            text=f"message-{index:03d}",
            provider_message_id=f"m-{index}",
            sent_at=f"2026-08-09T01:{index // 60:02d}:{index % 60:02d}Z",
        )

    recent = store.recent_messages("group", "g-1", limit=100)

    assert len(recent) == 100
    assert recent[0]["text"] == "message-005"
    assert recent[-1]["text"] == "message-104"


def test_search_enforces_member_dm_scope_and_allows_company_groups(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.store_message(
        thread_type="dm",
        thread_id="u-1",
        sender_id="u-1",
        text="mật khẩu wifi phòng họp",
        provider_message_id="dm-1",
    )
    store.store_message(
        thread_type="dm",
        thread_id="u-2",
        sender_id="u-2",
        text="mật khẩu wifi kho",
        provider_message_id="dm-2",
    )
    store.store_message(
        thread_type="group",
        thread_id="g-1",
        sender_id="u-2",
        text="wifi dùng cho khách",
        provider_message_id="g-1",
    )

    member = store.search_messages(
        "wifi",
        requester_id="u-1",
        is_admin=False,
        allowed_groups={"g-1"},
    )
    admin = store.search_messages(
        "wifi",
        requester_id="admin",
        is_admin=True,
        allowed_groups=set(),
    )

    assert {(row["thread_type"], row["thread_id"]) for row in member} == {
        ("dm", "u-1"),
        ("group", "g-1"),
    }
    assert len(admin) == 3


def test_export_and_delete_history_use_the_same_scope(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    stored = store.store_message(
        thread_type="group",
        thread_id="g-1",
        sender_id="u-1",
        text="biên bản cuộc họp",
        provider_message_id="m-1",
    )
    export_path = tmp_path / "export.jsonl"

    result = store.export_history(export_path, thread_type="group", thread_id="g-1")
    lines = export_path.read_text(encoding="utf-8").splitlines()
    deleted = store.delete_history(thread_type="group", thread_id="g-1")

    assert result["messages"] == 1
    assert json.loads(lines[0])["id"] == stored.message_id
    assert deleted["messages"] == 1
    assert store.recent_messages("group", "g-1") == []


def test_tool_activity_redacts_secret_values(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.log_tool_activity(
        requester_id="u-1",
        thread_type="dm",
        thread_id="u-1",
        tool_name="zalo.call",
        status="failed",
        error_text="Authorization: Bearer abc123 password=hunter2",
        metadata={"method": "sendMessage", "token": "abc123"},
    )

    row = store.connection.execute(
        "SELECT error_text, metadata_json FROM tool_activity"
    ).fetchone()
    assert "abc123" not in row[0]
    assert "hunter2" not in row[0]
    assert "abc123" not in row[1]
    assert "[REDACTED]" in row[0]


def test_tool_activity_redacts_json_string_and_bearer_credentials(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.log_tool_activity(
        requester_id="u-1",
        thread_type="dm",
        thread_id="u-1",
        tool_name="zalo.call",
        status="failed",
        error_text='{"token":"abc123","password":"hunter2"} Authorization: Bearer bearer-secret',
    )
    row = store.connection.execute("SELECT error_text FROM tool_activity").fetchone()
    assert "abc123" not in row[0]
    assert "hunter2" not in row[0]
    assert "bearer-secret" not in row[0]
    assert "[REDACTED]" in row[0]


def test_redact_text_covers_unlabeled_bearer_credentials() -> None:
    assert redact_text("request failed with Bearer unlabeled-secret") == (
        "request failed with Bearer [REDACTED]"
    )


def test_public_insert_apis_are_idempotent(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    first_conversation = store.upsert_conversation(
        thread_type="group",
        thread_id="g-1",
        title="Nhóm công ty",
        timestamp="2026-08-09T01:00:00Z",
    )
    second_conversation = store.upsert_conversation(
        thread_type="group",
        thread_id="g-1",
        title="Nhóm công ty",
        timestamp="2026-08-09T01:01:00Z",
    )
    message = store.insert_message(
        thread_type="group",
        thread_id="g-1",
        sender_id="u-1",
        text="tin nhắn không mention",
        provider_message_id="m-public-1",
        mentioned_bot=False,
    )
    duplicate_message = store.insert_message(
        thread_type="group",
        thread_id="g-1",
        sender_id="u-1",
        text="tin nhắn không mention",
        provider_message_id="m-public-1",
        mentioned_bot=False,
    )
    attachment = store.insert_attachment(
        message_id=message.message_id,
        attachment_index=0,
        kind="file",
        filename="bao-cao.pdf",
        download_status="pending",
    )
    duplicate_attachment = store.insert_attachment(
        message_id=message.message_id,
        attachment_index=0,
        kind="file",
        filename="bao-cao.pdf",
        download_status="pending",
    )

    assert first_conversation == second_conversation == message.conversation_id
    assert message.inserted is True
    assert duplicate_message.inserted is False
    assert attachment.inserted is True
    assert duplicate_attachment.inserted is False
    assert duplicate_attachment.attachment_id == attachment.attachment_id
    assert store.insert_event(
        event_key="reaction-1",
        event_type="reaction",
        provider_message_id="m-public-1",
    ) is True
    assert store.insert_event(
        event_key="reaction-1",
        event_type="reaction",
        provider_message_id="m-public-1",
    ) is False

    stored = store.get_message(
        message.message_id,
        requester_id="admin",
        is_admin=True,
        allowed_groups=set(),
    )
    assert stored is not None
    assert stored["mentioned_bot"] == 0


def test_get_message_and_attachment_enforce_member_scope(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    own = store.store_message(
        thread_type="dm",
        thread_id="u-1",
        sender_id="u-1",
        text="hóa đơn của tôi",
        provider_message_id="dm-own",
        attachments=[{"kind": "file", "download_status": "pending"}],
    )
    other = store.store_message(
        thread_type="dm",
        thread_id="u-2",
        sender_id="u-2",
        text="hóa đơn người khác",
        provider_message_id="dm-other",
        attachments=[{"kind": "file", "download_status": "pending"}],
    )

    assert store.get_message(
        own.message_id,
        requester_id="u-1",
        is_admin=False,
        allowed_groups=set(),
    ) is not None
    assert store.get_message(
        other.message_id,
        requester_id="u-1",
        is_admin=False,
        allowed_groups=set(),
    ) is None
    assert store.get_attachment(
        own.attachment_ids[0],
        requester_id="u-1",
        is_admin=False,
        allowed_groups=set(),
    ) is not None
    assert store.get_attachment(
        other.attachment_ids[0],
        requester_id="u-1",
        is_admin=False,
        allowed_groups=set(),
    ) is None


def test_store_reopens_same_database_and_reports_stats(tmp_path: Path) -> None:
    db_path = tmp_path / "history.sqlite3"
    store = HistoryStore(db_path, account_id="company-zalo")
    store.store_message(
        thread_type="group",
        thread_id="g-1",
        sender_id="u-1",
        text="giữ lại sau restart",
        provider_message_id="restart-1",
        attachments=[{"kind": "image", "size_bytes": 4, "download_status": "downloaded"}],
    )
    store.close()

    reopened = HistoryStore(db_path, account_id="company-zalo")

    assert reopened.recent_messages("group", "g-1")[0]["text"] == "giữ lại sau restart"
    assert reopened.stats() == {
        "conversations": 1,
        "messages": 1,
        "message_events": 0,
        "attachments": 1,
        "tool_activity": 0,
        "media_bytes": 4,
    }


def test_redact_text_covers_every_authorization_scheme() -> None:
    assert redact_text("Authorization: Basic dXNlcjpwYXNz") == (
        "Authorization: Basic [REDACTED]"
    )
    digest = redact_text(
        'Authorization: Digest username="Aladdin", response="digest-secret"'
    )
    assert digest == "Authorization: Digest [REDACTED]"


def test_delete_history_never_unlinks_paths_outside_media_root(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    outside = tmp_path / "outside-media.txt"
    outside.write_text("must survive", encoding="utf-8")
    store.store_message(
        thread_type="group",
        thread_id="g-1",
        sender_id="u-1",
        provider_message_id="outside-path",
        attachments=[
            {
                "kind": "file",
                "local_path": str(outside),
                "download_status": "downloaded",
            }
        ],
    )

    deleted = store.delete_history(thread_type="group", thread_id="g-1")

    assert deleted["messages"] == 1
    assert deleted["media_deleted"] == 0
    assert outside.read_text(encoding="utf-8") == "must survive"


def test_delete_history_keeps_database_rows_when_media_unlink_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = make_store(tmp_path)
    media = tmp_path / "media" / "group" / "g-1" / "2026-08-09" / "1-file.bin"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"content")
    stored = store.store_message(
        thread_type="group",
        thread_id="g-1",
        sender_id="u-1",
        provider_message_id="locked-media",
        attachments=[
            {
                "kind": "file",
                "local_path": str(media),
                "download_status": "downloaded",
            }
        ],
    )
    original_unlink = Path.unlink

    def locked_unlink(path: Path, *args: object, **kwargs: object) -> None:
        if path.resolve() == media.resolve():
            raise PermissionError("media file is locked")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", locked_unlink)

    with pytest.raises(RuntimeError, match="media"):
        store.delete_history(thread_type="group", thread_id="g-1")

    assert store.get_message(
        stored.message_id,
        requester_id="admin",
        is_admin=True,
        allowed_groups=set(),
    ) is not None
    assert media.exists()


def test_purge_before_deletes_only_expired_messages(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.store_message(
        thread_type="dm", thread_id="u-1", sender_id="u-1", text="old",
        provider_message_id="old", sent_at="2026-01-01T00:00:00+00:00",
    )
    store.store_message(
        thread_type="dm", thread_id="u-1", sender_id="u-1", text="new",
        provider_message_id="new", sent_at="2026-08-01T00:00:00+00:00",
    )

    result = store.purge_before("2026-05-01T00:00:00+00:00")

    assert result["messages"] == 1
    assert [row["text"] for row in store.recent_messages("dm", "u-1")] == ["new"]

def test_message_event_is_scoped_to_the_store_account(tmp_path: Path) -> None:
    db_path = tmp_path / "history.sqlite3"
    account_a = HistoryStore(db_path, account_id="account-a")
    message_a = account_a.store_message(
        thread_type="dm",
        thread_id="user-a",
        sender_id="user-a",
        provider_message_id="same-provider-id",
    )
    account_b = HistoryStore(db_path, account_id="account-b")
    message_b = account_b.store_message(
        thread_type="dm",
        thread_id="user-b",
        sender_id="user-b",
        provider_message_id="same-provider-id",
    )

    assert account_a.record_event(
        event_key="account-a-undo",
        event_type="undo",
        provider_message_id="same-provider-id",
    ) is True

    event = account_a.connection.execute(
        "SELECT message_id FROM message_events WHERE event_key='account-a-undo'"
    ).fetchone()
    recalled_a = account_a.connection.execute(
        "SELECT recalled_at FROM messages WHERE id=?",
        (message_a.message_id,),
    ).fetchone()
    recalled_b = account_a.connection.execute(
        "SELECT recalled_at FROM messages WHERE id=?",
        (message_b.message_id,),
    ).fetchone()
    assert event["message_id"] == message_a.message_id
    assert recalled_a["recalled_at"] is not None
    assert recalled_b["recalled_at"] is None


def test_message_event_is_scoped_to_the_exact_conversation(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    first = store.store_message(
        thread_type="group",
        thread_id="group-a",
        sender_id="member-1",
        provider_message_id="same-provider-id",
    )
    second = store.store_message(
        thread_type="group",
        thread_id="group-b",
        sender_id="member-1",
        provider_message_id="same-provider-id",
    )

    assert store.record_event(
        event_key="group-a-undo",
        event_type="undo",
        provider_message_id="same-provider-id",
        thread_type="group",
        thread_id="group-a",
    ) is True

    event = store.connection.execute(
        "SELECT message_id FROM message_events WHERE event_key='group-a-undo'"
    ).fetchone()
    recalled_first = store.connection.execute(
        "SELECT recalled_at FROM messages WHERE id=?",
        (first.message_id,),
    ).fetchone()
    recalled_second = store.connection.execute(
        "SELECT recalled_at FROM messages WHERE id=?",
        (second.message_id,),
    ).fetchone()
    assert event["message_id"] == first.message_id
    assert recalled_first["recalled_at"] is not None
    assert recalled_second["recalled_at"] is None
