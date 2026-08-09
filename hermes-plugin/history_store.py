from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


_MIGRATION_RE = re.compile(r"^(?P<version>\d{3})_(?P<name>.+)\.sql$")
_SECRET_KEY_RE = re.compile(
    r"(?:password|passwd|token|cookie|api[_-]?key|secret|imei|authorization)",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+")
_ASSIGNMENT_SECRET_RE = re.compile(
    r"(?i)\b(password|passwd|token|cookie|api[_-]?key|secret|imei)"
    r"(\s*[:=]\s*)[^\s,;]+"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def redact_text(value: str | None) -> str | None:
    if value is None:
        return None
    redacted = _BEARER_RE.sub(r"\1[REDACTED]", str(value))
    return _ASSIGNMENT_SECRET_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]",
        redacted,
    )


def redact_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): (
                "[REDACTED]"
                if _SECRET_KEY_RE.search(str(key))
                else redact_value(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [redact_value(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


class MigrationError(RuntimeError):
    pass


class MigrationChecksumError(MigrationError):
    pass


@dataclass(frozen=True, slots=True)
class StoredMessage:
    inserted: bool
    message_id: int
    conversation_id: int
    attachment_ids: tuple[int, ...] = ()


class HistoryStore:
    """Thread-safe SQLite source of truth for Zalo conversation history."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        account_id: str = "default",
        migrations_dir: str | Path | None = None,
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.account_id = str(account_id or "default")
        self.migrations_dir = (
            Path(migrations_dir)
            if migrations_dir is not None
            else Path(__file__).resolve().parent / "migrations"
        )
        self._lock = threading.RLock()
        self.connection = sqlite3.connect(
            self.db_path,
            timeout=30,
            check_same_thread=False,
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA busy_timeout=30000")
        try:
            self.apply_migrations()
        except Exception:
            self.connection.close()
            raise

    def __enter__(self) -> "HistoryStore":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            self.connection.close()

    def _migration_files(self) -> list[tuple[int, str, Path, str]]:
        migrations: list[tuple[int, str, Path, str]] = []
        if not self.migrations_dir.is_dir():
            raise MigrationError(
                f"migration directory not found: {self.migrations_dir}"
            )
        for path in sorted(self.migrations_dir.glob("*.sql")):
            match = _MIGRATION_RE.match(path.name)
            if not match:
                raise MigrationError(f"invalid migration filename: {path.name}")
            version = int(match.group("version"))
            raw = path.read_bytes()
            migrations.append(
                (
                    version,
                    match.group("name"),
                    path,
                    hashlib.sha256(raw).hexdigest(),
                )
            )
        if not migrations:
            raise MigrationError("no SQLite migrations found")
        versions = [item[0] for item in migrations]
        if versions != list(range(1, len(versions) + 1)):
            raise MigrationError(f"migration versions must be contiguous: {versions}")
        return migrations

    def _applied_migrations(self) -> dict[int, tuple[str, str]]:
        exists = self.connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
        if not exists:
            return {}
        return {
            int(row["version"]): (str(row["name"]), str(row["checksum"]))
            for row in self.connection.execute(
                "SELECT version, name, checksum FROM schema_migrations"
            )
        }

    def apply_migrations(self) -> None:
        with self._lock:
            files = self._migration_files()
            applied = self._applied_migrations()
            for version, name, path, checksum in files:
                if version in applied:
                    old_name, old_checksum = applied[version]
                    if old_name != name or old_checksum != checksum:
                        raise MigrationChecksumError(
                            f"migration {version:03d}_{name} checksum changed"
                        )
                    continue
                sql = path.read_text(encoding="utf-8")
                safe_name = name.replace("'", "''")
                script = (
                    "BEGIN IMMEDIATE;\n"
                    f"{sql.rstrip()}\n"
                    "INSERT INTO schema_migrations(version, name, checksum, applied_at) "
                    f"VALUES({version}, '{safe_name}', '{checksum}', '{utc_now()}');\n"
                    "COMMIT;\n"
                )
                try:
                    self.connection.executescript(script)
                except sqlite3.DatabaseError as exc:
                    try:
                        self.connection.execute("ROLLBACK")
                    except sqlite3.DatabaseError:
                        pass
                    raise MigrationError(
                        f"failed applying migration {path.name}: {exc}"
                    ) from exc

    @staticmethod
    def _thread_type(value: str) -> str:
        normalized = str(value).lower()
        if normalized not in {"dm", "group"}:
            raise ValueError("thread_type must be dm or group")
        return normalized

    def _dedupe_key(
        self,
        *,
        thread_type: str,
        thread_id: str,
        provider_message_id: str,
        provider_cli_message_id: str,
        event_id: str,
        sender_id: str,
        sent_at: str,
        text: str,
    ) -> str:
        provider_key = "|".join(
            part
            for part in (
                str(provider_message_id or ""),
                str(provider_cli_message_id or ""),
                str(event_id or ""),
            )
            if part
        )
        if not provider_key:
            provider_key = hashlib.sha256(
                f"{sender_id}|{sent_at}|{text}".encode("utf-8")
            ).hexdigest()
        material = (
            f"{self.account_id}|{thread_type}|{thread_id}|{provider_key}"
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def _conversation_id(
        self,
        *,
        thread_type: str,
        thread_id: str,
        title: str | None,
        timestamp: str,
    ) -> int:
        self.connection.execute(
            "INSERT INTO conversations("
            "account_id, thread_type, thread_id, title, created_at, last_message_at"
            ") VALUES(?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(account_id, thread_type, thread_id) DO UPDATE SET "
            "title=COALESCE(excluded.title, conversations.title)",
            (
                self.account_id,
                thread_type,
                thread_id,
                title,
                timestamp,
                timestamp,
            ),
        )
        row = self.connection.execute(
            "SELECT id FROM conversations "
            "WHERE account_id=? AND thread_type=? AND thread_id=?",
            (self.account_id, thread_type, thread_id),
        ).fetchone()
        assert row is not None
        return int(row["id"])

    def store_message(
        self,
        *,
        thread_type: str,
        thread_id: str,
        sender_id: str,
        text: str = "",
        provider_message_id: str = "",
        provider_cli_message_id: str = "",
        event_id: str = "",
        sender_name: str = "",
        title: str | None = None,
        is_bot: bool = False,
        mentioned_bot: bool = False,
        reply_to_provider_message_id: str = "",
        quote: Mapping[str, Any] | None = None,
        sent_at: str | None = None,
        attachments: Sequence[Mapping[str, Any]] | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> StoredMessage:
        normalized_type = self._thread_type(thread_type)
        normalized_thread_id = str(thread_id or "")
        normalized_sender = str(sender_id or "")
        if not normalized_thread_id or not normalized_sender:
            raise ValueError("thread_id and sender_id are required")
        timestamp = str(sent_at or utc_now())
        stored_at = utc_now()
        dedupe_key = self._dedupe_key(
            thread_type=normalized_type,
            thread_id=normalized_thread_id,
            provider_message_id=str(provider_message_id or ""),
            provider_cli_message_id=str(provider_cli_message_id or ""),
            event_id=str(event_id or ""),
            sender_id=normalized_sender,
            sent_at=timestamp,
            text=str(text or ""),
        )
        attachment_ids: list[int] = []
        with self._lock, self.connection:
            conversation_id = self._conversation_id(
                thread_type=normalized_type,
                thread_id=normalized_thread_id,
                title=title,
                timestamp=timestamp,
            )
            existing = self.connection.execute(
                "SELECT id, conversation_id FROM messages WHERE dedupe_key=?",
                (dedupe_key,),
            ).fetchone()
            if existing is not None:
                return StoredMessage(
                    inserted=False,
                    message_id=int(existing["id"]),
                    conversation_id=int(existing["conversation_id"]),
                )

            reply_to_message_id = None
            if reply_to_provider_message_id:
                reply = self.connection.execute(
                    "SELECT id FROM messages "
                    "WHERE conversation_id=? AND provider_message_id=? "
                    "ORDER BY id DESC LIMIT 1",
                    (conversation_id, str(reply_to_provider_message_id)),
                ).fetchone()
                if reply is not None:
                    reply_to_message_id = int(reply["id"])

            cursor = self.connection.execute(
                "INSERT INTO messages("
                "conversation_id, dedupe_key, provider_message_id, "
                "provider_cli_message_id, sender_id, sender_name, text, is_bot, "
                "mentioned_bot, reply_to_message_id, quote_json, sent_at, "
                "stored_at, extra_json"
                ") VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    conversation_id,
                    dedupe_key,
                    str(provider_message_id or "") or None,
                    str(provider_cli_message_id or "") or None,
                    normalized_sender,
                    str(sender_name or "") or None,
                    str(text or ""),
                    int(bool(is_bot)),
                    int(bool(mentioned_bot)),
                    reply_to_message_id,
                    _json(quote) if quote else None,
                    timestamp,
                    stored_at,
                    _json(extra or {}),
                ),
            )
            message_id = int(cursor.lastrowid)
            self.connection.execute(
                "UPDATE conversations SET last_message_at=? WHERE id=?",
                (timestamp, conversation_id),
            )
            for index, attachment in enumerate(attachments or []):
                status = str(
                    attachment.get("download_status") or "pending"
                ).lower()
                if status not in {
                    "pending",
                    "downloaded",
                    "metadata_only",
                    "failed",
                }:
                    raise ValueError(f"invalid attachment download_status: {status}")
                attach_cursor = self.connection.execute(
                    "INSERT INTO attachments("
                    "message_id, attachment_index, kind, filename, mime_type, "
                    "size_bytes, remote_url, local_path, sha256, download_status, "
                    "created_at"
                    ") VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        message_id,
                        int(attachment.get("attachment_index", index)),
                        str(attachment.get("kind") or "other"),
                        str(attachment.get("filename") or "") or None,
                        str(attachment.get("mime_type") or "") or None,
                        (
                            int(attachment["size_bytes"])
                            if attachment.get("size_bytes") is not None
                            else None
                        ),
                        str(attachment.get("remote_url") or "") or None,
                        str(attachment.get("local_path") or "") or None,
                        str(attachment.get("sha256") or "") or None,
                        status,
                        stored_at,
                    ),
                )
                attachment_ids.append(int(attach_cursor.lastrowid))
        return StoredMessage(
            inserted=True,
            message_id=message_id,
            conversation_id=conversation_id,
            attachment_ids=tuple(attachment_ids),
        )

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        for key in ("quote_json", "extra_json", "payload_json", "metadata_json"):
            if key in result and result[key]:
                try:
                    result[key.removesuffix("_json")] = json.loads(result.pop(key))
                except (TypeError, json.JSONDecodeError):
                    pass
        return result

    def recent_messages(
        self,
        thread_type: str,
        thread_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        capped = max(1, min(int(limit), 100))
        rows = self.connection.execute(
            "SELECT m.*, c.thread_type, c.thread_id, c.title "
            "FROM messages m JOIN conversations c ON c.id=m.conversation_id "
            "WHERE c.account_id=? AND c.thread_type=? AND c.thread_id=? "
            "ORDER BY m.sent_at DESC, m.id DESC LIMIT ?",
            (
                self.account_id,
                self._thread_type(thread_type),
                str(thread_id),
                capped,
            ),
        ).fetchall()
        return [self._row(row) for row in reversed(rows)]

    @staticmethod
    def _scope_sql(
        *,
        requester_id: str,
        is_admin: bool,
        allowed_groups: Iterable[str],
    ) -> tuple[str, list[Any]]:
        if is_admin:
            return "1=1", []
        groups = sorted({str(group) for group in allowed_groups if str(group)})
        clauses = ["(c.thread_type='dm' AND c.thread_id=?)"]
        params: list[Any] = [str(requester_id)]
        if groups:
            placeholders = ",".join("?" for _ in groups)
            clauses.append(
                f"(c.thread_type='group' AND c.thread_id IN ({placeholders}))"
            )
            params.extend(groups)
        return "(" + " OR ".join(clauses) + ")", params

    def search_messages(
        self,
        query: str,
        *,
        requester_id: str,
        is_admin: bool,
        allowed_groups: Iterable[str],
        thread_type: str | None = None,
        thread_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        scope, params = self._scope_sql(
            requester_id=requester_id,
            is_admin=is_admin,
            allowed_groups=allowed_groups,
        )
        clauses = ["c.account_id=?", scope, "m.text LIKE ? ESCAPE '\\'"]
        values: list[Any] = [self.account_id, *params, f"%{str(query)}%"]
        if thread_type is not None:
            clauses.append("c.thread_type=?")
            values.append(self._thread_type(thread_type))
        if thread_id is not None:
            clauses.append("c.thread_id=?")
            values.append(str(thread_id))
        values.append(max(1, min(int(limit), 200)))
        rows = self.connection.execute(
            "SELECT m.*, c.thread_type, c.thread_id, c.title "
            "FROM messages m JOIN conversations c ON c.id=m.conversation_id "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY m.sent_at DESC, m.id DESC LIMIT ?",
            values,
        ).fetchall()
        return [self._row(row) for row in rows]

    def get_message(
        self,
        message_id: int,
        *,
        requester_id: str,
        is_admin: bool,
        allowed_groups: Iterable[str],
    ) -> dict[str, Any] | None:
        scope, params = self._scope_sql(
            requester_id=requester_id,
            is_admin=is_admin,
            allowed_groups=allowed_groups,
        )
        row = self.connection.execute(
            "SELECT m.*, c.thread_type, c.thread_id, c.title "
            "FROM messages m JOIN conversations c ON c.id=m.conversation_id "
            f"WHERE m.id=? AND c.account_id=? AND {scope}",
            [int(message_id), self.account_id, *params],
        ).fetchone()
        return self._row(row) if row is not None else None

    def get_attachment(
        self,
        attachment_id: int,
        *,
        requester_id: str,
        is_admin: bool,
        allowed_groups: Iterable[str],
    ) -> dict[str, Any] | None:
        scope, params = self._scope_sql(
            requester_id=requester_id,
            is_admin=is_admin,
            allowed_groups=allowed_groups,
        )
        row = self.connection.execute(
            "SELECT a.*, c.thread_type, c.thread_id "
            "FROM attachments a "
            "JOIN messages m ON m.id=a.message_id "
            "JOIN conversations c ON c.id=m.conversation_id "
            f"WHERE a.id=? AND c.account_id=? AND {scope}",
            [int(attachment_id), self.account_id, *params],
        ).fetchone()
        return self._row(row) if row is not None else None

    def update_attachment(
        self,
        attachment_id: int,
        *,
        download_status: str,
        local_path: str | None = None,
        sha256: str | None = None,
        size_bytes: int | None = None,
    ) -> None:
        status = str(download_status).lower()
        if status not in {"pending", "downloaded", "metadata_only", "failed"}:
            raise ValueError("invalid attachment download_status")
        with self._lock, self.connection:
            self.connection.execute(
                "UPDATE attachments SET download_status=?, local_path=?, "
                "sha256=?, size_bytes=COALESCE(?, size_bytes) WHERE id=?",
                (status, local_path, sha256, size_bytes, int(attachment_id)),
            )

    def record_event(
        self,
        *,
        event_key: str,
        event_type: str,
        provider_message_id: str = "",
        actor_id: str = "",
        actor_name: str = "",
        occurred_at: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> bool:
        timestamp = str(occurred_at or utc_now())
        with self._lock, self.connection:
            message = None
            if provider_message_id:
                message = self.connection.execute(
                    "SELECT id FROM messages WHERE provider_message_id=? "
                    "ORDER BY id DESC LIMIT 1",
                    (str(provider_message_id),),
                ).fetchone()
            cursor = self.connection.execute(
                "INSERT OR IGNORE INTO message_events("
                "message_id, event_key, event_type, actor_id, actor_name, "
                "occurred_at, payload_json"
                ") VALUES(?, ?, ?, ?, ?, ?, ?)",
                (
                    int(message["id"]) if message is not None else None,
                    str(event_key),
                    str(event_type),
                    str(actor_id or "") or None,
                    str(actor_name or "") or None,
                    timestamp,
                    _json(redact_value(payload or {})),
                ),
            )
            inserted = cursor.rowcount == 1
            if (
                inserted
                and event_type == "undo"
                and message is not None
            ):
                self.connection.execute(
                    "UPDATE messages SET recalled_at=? WHERE id=?",
                    (timestamp, int(message["id"])),
                )
            return inserted

    def log_tool_activity(
        self,
        *,
        requester_id: str,
        thread_type: str,
        thread_id: str | None,
        tool_name: str,
        status: str,
        error_text: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        occurred_at: str | None = None,
    ) -> int:
        normalized_status = str(status).lower()
        if normalized_status not in {"success", "failed", "unknown", "blocked"}:
            raise ValueError("invalid tool activity status")
        normalized_thread_type = str(thread_type).lower()
        if normalized_thread_type not in {"dm", "group", "system"}:
            raise ValueError("invalid tool activity thread_type")
        with self._lock, self.connection:
            cursor = self.connection.execute(
                "INSERT INTO tool_activity("
                "occurred_at, requester_id, thread_type, thread_id, tool_name, "
                "status, error_text, metadata_json"
                ") VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(occurred_at or utc_now()),
                    str(requester_id),
                    normalized_thread_type,
                    str(thread_id) if thread_id is not None else None,
                    str(tool_name),
                    normalized_status,
                    redact_text(error_text),
                    _json(redact_value(metadata or {})),
                ),
            )
            return int(cursor.lastrowid)

    def _history_filter(
        self,
        *,
        thread_type: str | None,
        thread_id: str | None,
        since: str | None,
        until: str | None,
    ) -> tuple[str, list[Any]]:
        clauses = ["c.account_id=?"]
        params: list[Any] = [self.account_id]
        if thread_type is not None:
            clauses.append("c.thread_type=?")
            params.append(self._thread_type(thread_type))
        if thread_id is not None:
            clauses.append("c.thread_id=?")
            params.append(str(thread_id))
        if since is not None:
            clauses.append("m.sent_at>=?")
            params.append(str(since))
        if until is not None:
            clauses.append("m.sent_at<=?")
            params.append(str(until))
        return " AND ".join(clauses), params

    def export_history(
        self,
        destination: str | Path,
        *,
        thread_type: str | None = None,
        thread_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> dict[str, Any]:
        where, params = self._history_filter(
            thread_type=thread_type,
            thread_id=thread_id,
            since=since,
            until=until,
        )
        rows = self.connection.execute(
            "SELECT m.*, c.thread_type, c.thread_id, c.title "
            "FROM messages m JOIN conversations c ON c.id=m.conversation_id "
            f"WHERE {where} ORDER BY m.sent_at, m.id",
            params,
        ).fetchall()
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                message = self._row(row)
                attachments = [
                    self._row(item)
                    for item in self.connection.execute(
                        "SELECT * FROM attachments WHERE message_id=? "
                        "ORDER BY attachment_index",
                        (int(row["id"]),),
                    )
                ]
                message["attachments"] = attachments
                handle.write(_json(message) + "\n")
        return {"path": str(path), "messages": len(rows)}

    def delete_history(
        self,
        *,
        thread_type: str | None = None,
        thread_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> dict[str, Any]:
        where, params = self._history_filter(
            thread_type=thread_type,
            thread_id=thread_id,
            since=since,
            until=until,
        )
        local_paths: list[Path] = []
        with self._lock, self.connection:
            rows = self.connection.execute(
                "SELECT m.id FROM messages m "
                "JOIN conversations c ON c.id=m.conversation_id "
                f"WHERE {where}",
                params,
            ).fetchall()
            message_ids = [int(row["id"]) for row in rows]
            if not message_ids:
                return {"messages": 0, "attachments": 0, "media_deleted": 0}
            placeholders = ",".join("?" for _ in message_ids)
            attachment_rows = self.connection.execute(
                f"SELECT local_path FROM attachments "
                f"WHERE message_id IN ({placeholders})",
                message_ids,
            ).fetchall()
            local_paths = [
                Path(row["local_path"])
                for row in attachment_rows
                if row["local_path"]
            ]
            attachment_count = len(attachment_rows)
            self.connection.execute(
                f"DELETE FROM messages WHERE id IN ({placeholders})",
                message_ids,
            )
            self.connection.execute(
                "DELETE FROM conversations WHERE account_id=? "
                "AND NOT EXISTS("
                "SELECT 1 FROM messages WHERE messages.conversation_id=conversations.id"
                ")",
                (self.account_id,),
            )
        media_deleted = 0
        for path in local_paths:
            try:
                path.unlink(missing_ok=True)
                media_deleted += 1
            except OSError:
                pass
        return {
            "messages": len(message_ids),
            "attachments": attachment_count,
            "media_deleted": media_deleted,
        }

    def stats(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for table in (
            "conversations",
            "messages",
            "message_events",
            "attachments",
            "tool_activity",
        ):
            result[table] = int(
                self.connection.execute(
                    f"SELECT count(*) FROM {table}"
                ).fetchone()[0]
            )
        result["media_bytes"] = int(
            self.connection.execute(
                "SELECT COALESCE(sum(size_bytes), 0) FROM attachments "
                "WHERE download_status='downloaded'"
            ).fetchone()[0]
        )
        return result
