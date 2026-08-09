from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from history_store import HistoryStore, MigrationChecksumError


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

