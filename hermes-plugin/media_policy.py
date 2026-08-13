from __future__ import annotations

import asyncio
import hashlib
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterable, Iterable, Mapping


MAX_MEDIA_BYTES = 20 * 1024 * 1024
_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_filename(value: object, *, fallback: str = "attachment") -> str:
    """Return a path-free filename containing only the approved characters."""

    basename = str(value or "").replace("\\", "/").rsplit("/", 1)[-1]
    sanitized = _UNSAFE_FILENAME.sub("_", basename)
    while ".." in sanitized:
        sanitized = sanitized.replace("..", "_")
    sanitized = sanitized.strip("._")
    if not sanitized:
        sanitized = _UNSAFE_FILENAME.sub("_", str(fallback or "attachment"))
        sanitized = sanitized.strip("._") or "attachment"
    return sanitized[:180]


def _sanitize_component(value: object, *, fallback: str) -> str:
    sanitized = _UNSAFE_FILENAME.sub("_", str(value or ""))
    while ".." in sanitized:
        sanitized = sanitized.replace("..", "_")
    return sanitized.strip("._") or fallback


def _utc_date(value: str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).date().isoformat()
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).date().isoformat()


def _private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass


def _discard_partial(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


async def _chunks(
    source: AsyncIterable[bytes] | Iterable[bytes],
) -> AsyncIterable[bytes]:
    if hasattr(source, "__aiter__"):
        async for chunk in source:  # type: ignore[union-attr]
            yield chunk
        return
    for chunk in source:  # type: ignore[union-attr]
        yield chunk


@dataclass(frozen=True, slots=True)
class MediaResult:
    attachment_id: int
    status: str
    local_path: str | None = None
    sha256: str | None = None
    size_bytes: int | None = None


class MediaPolicy:
    """Persist normalized Zalo attachments within a strict streaming cap."""

    def __init__(
        self,
        history_root: str | Path,
        *,
        max_bytes: int = MAX_MEDIA_BYTES,
    ) -> None:
        if int(max_bytes) < 1:
            raise ValueError("max_bytes must be positive")
        self.history_root = Path(history_root)
        self.media_root = self.history_root / "media"
        self.max_bytes = int(max_bytes)
        self._download_lock = asyncio.Lock()
        _private_directory(self.media_root)

    def target_path(
        self,
        *,
        attachment_id: int,
        filename: object,
        thread_type: str,
        thread_id: str,
        sent_at: str | None,
    ) -> Path:
        normalized_type = str(thread_type).lower()
        if normalized_type not in {"dm", "group"}:
            raise ValueError("thread_type must be dm or group")
        safe_thread = _sanitize_component(thread_id, fallback="unknown")
        directory = (
            self.media_root
            / normalized_type
            / safe_thread
            / _utc_date(sent_at)
        )
        _private_directory(directory)
        safe_name = sanitize_filename(filename)
        return directory / f"{int(attachment_id)}-{safe_name}"

    @staticmethod
    def _result_from_record(attachment_id: int, record: Mapping[str, Any]) -> MediaResult:
        size = record.get("size_bytes")
        return MediaResult(
            attachment_id=int(attachment_id),
            status=str(record.get("download_status") or "failed"),
            local_path=str(record["local_path"]) if record.get("local_path") else None,
            sha256=str(record["sha256"]) if record.get("sha256") else None,
            size_bytes=int(size) if size is not None else None,
        )

    async def store_attachment(
        self,
        *,
        store: Any,
        attachment_id: int,
        attachment: Mapping[str, Any],
        thread_type: str,
        thread_id: str,
        sent_at: str | None,
        chunks: AsyncIterable[bytes] | Iterable[bytes],
    ) -> MediaResult:
        async with self._download_lock:
            return await self._store_attachment_locked(
                store=store,
                attachment_id=attachment_id,
                attachment=attachment,
                thread_type=thread_type,
                thread_id=thread_id,
                sent_at=sent_at,
                chunks=chunks,
            )

    async def _store_attachment_locked(
        self,
        *,
        store: Any,
        attachment_id: int,
        attachment: Mapping[str, Any],
        thread_type: str,
        thread_id: str,
        sent_at: str | None,
        chunks: AsyncIterable[bytes] | Iterable[bytes],
    ) -> MediaResult:
        record = store.get_attachment(
            int(attachment_id),
            requester_id="",
            is_admin=True,
            allowed_groups=(),
        )
        if record is None:
            raise ValueError(f"attachment not found: {attachment_id}")
        if record["download_status"] != "pending":
            return self._result_from_record(attachment_id, record)
        known_size = attachment.get("size_bytes")
        if known_size is None:
            known_size = record.get("size_bytes")
        if known_size is not None:
            known_size = int(known_size)
            if known_size > self.max_bytes:
                store.update_attachment(
                    attachment_id,
                    download_status="metadata_only",
                    size_bytes=known_size,
                )
                return MediaResult(
                    attachment_id=int(attachment_id),
                    status="metadata_only",
                    size_bytes=known_size,
                )

        target = self.target_path(
            attachment_id=attachment_id,
            filename=attachment.get("filename") or record.get("filename"),
            thread_type=thread_type,
            thread_id=thread_id,
            sent_at=sent_at,
        )
        temporary = target.with_name(f".{target.name}.part")
        digest = hashlib.sha256()
        total = 0
        over_limit = False

        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                0o600,
            )
            with os.fdopen(descriptor, "wb") as handle:
                async for chunk in _chunks(chunks):
                    if not isinstance(chunk, (bytes, bytearray, memoryview)):
                        raise TypeError("media stream chunks must be bytes")
                    data = bytes(chunk)
                    total += len(data)
                    if total > self.max_bytes:
                        over_limit = True
                        break
                    handle.write(data)
                    digest.update(data)

            if over_limit:
                _discard_partial(temporary)
                store.update_attachment(
                    attachment_id,
                    download_status="metadata_only",
                )
                return MediaResult(
                    attachment_id=int(attachment_id),
                    status="metadata_only",
                )

            os.replace(temporary, target)
            try:
                target.chmod(0o600)
            except OSError:
                pass
            sha256 = digest.hexdigest()
            store.update_attachment(
                attachment_id,
                download_status="downloaded",
                local_path=str(target),
                sha256=sha256,
                size_bytes=total,
            )
            return MediaResult(
                attachment_id=int(attachment_id),
                status="downloaded",
                local_path=str(target),
                sha256=sha256,
                size_bytes=total,
            )
        except BaseException as exc:
            _discard_partial(temporary)
            store.update_attachment(
                attachment_id,
                download_status="failed",
            )
            if not isinstance(exc, Exception):
                raise
            return MediaResult(
                attachment_id=int(attachment_id),
                status="failed",
            )
