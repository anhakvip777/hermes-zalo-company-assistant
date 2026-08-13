from __future__ import annotations

import asyncio
import hashlib
import os
import re
import stat
from pathlib import Path

import pytest

from history_store import HistoryStore
from media_policy import MAX_MEDIA_BYTES, MediaPolicy, sanitize_filename


def make_pending_attachment(
    tmp_path: Path,
    *,
    size_bytes: int | None,
) -> tuple[HistoryStore, int, int]:
    store = HistoryStore(tmp_path / "history.sqlite3", account_id="company-zalo")
    message = store.store_message(
        thread_type="group",
        thread_id="g-1",
        sender_id="u-1",
        text="có file đính kèm",
        provider_message_id=f"media-{size_bytes}",
        sent_at="2026-08-09T01:00:00Z",
        attachments=[
            {
                "kind": "file",
                "filename": "../../Hợp đồng 01?.pdf",
                "mime_type": "application/pdf",
                "size_bytes": size_bytes,
                "remote_url": "https://example.invalid/file",
                "download_status": "pending",
            }
        ],
    )
    return store, message.message_id, message.attachment_ids[0]


def attachment_row(store: HistoryStore, attachment_id: int) -> dict[str, object]:
    row = store.get_attachment(
        attachment_id,
        requester_id="admin",
        is_admin=True,
        allowed_groups=set(),
    )
    assert row is not None
    return row


def test_default_cap_and_filename_sanitizing() -> None:
    assert MAX_MEDIA_BYTES == 20 * 1024 * 1024

    filename = sanitize_filename("../../Hợp đồng 01?.pdf")

    assert re.fullmatch(r"[A-Za-z0-9._-]+", filename)
    assert filename.endswith(".pdf")
    assert "/" not in filename
    assert "\\" not in filename
    assert ".." not in filename


def test_known_oversize_is_metadata_only_without_reading_stream(tmp_path: Path) -> None:
    store, message_id, attachment_id = make_pending_attachment(tmp_path, size_bytes=11)
    policy = MediaPolicy(tmp_path / "history", max_bytes=10)

    def unread_stream():
        raise AssertionError("oversize attachment stream must not be read")
        yield b"unreachable"

    result = asyncio.run(
        policy.store_attachment(
            store=store,
            attachment_id=attachment_id,
            attachment={
                "filename": "large.bin",
                "size_bytes": 11,
            },
            thread_type="group",
            thread_id="g-1",
            sent_at="2026-08-09T01:00:00Z",
            chunks=unread_stream(),
        )
    )

    assert result.status == "metadata_only"
    assert result.local_path is None
    assert attachment_row(store, attachment_id)["download_status"] == "metadata_only"
    assert store.get_message(
        message_id,
        requester_id="admin",
        is_admin=True,
        allowed_groups=set(),
    ) is not None


def test_unknown_stream_stops_immediately_after_crossing_cap(tmp_path: Path) -> None:
    store, _, attachment_id = make_pending_attachment(tmp_path, size_bytes=None)
    policy = MediaPolicy(tmp_path / "history", max_bytes=5)
    consumed: list[bytes] = []

    def chunks():
        for chunk in (b"123", b"456", b"must-not-be-read"):
            consumed.append(chunk)
            yield chunk

    result = asyncio.run(
        policy.store_attachment(
            store=store,
            attachment_id=attachment_id,
            attachment={"filename": "unknown.bin", "size_bytes": None},
            thread_type="group",
            thread_id="g-1",
            sent_at="2026-08-09T01:00:00Z",
            chunks=chunks(),
        )
    )

    assert result.status == "metadata_only"
    assert consumed == [b"123", b"456"]
    assert list((tmp_path / "history" / "media").rglob("*.part")) == []
    assert attachment_row(store, attachment_id)["local_path"] is None


def test_success_streams_to_safe_path_and_records_sha256(tmp_path: Path) -> None:
    store, _, attachment_id = make_pending_attachment(tmp_path, size_bytes=6)
    policy = MediaPolicy(tmp_path / "history", max_bytes=10)

    result = asyncio.run(
        policy.store_attachment(
            store=store,
            attachment_id=attachment_id,
            attachment={
                "filename": "../../Hợp đồng 01?.pdf",
                "size_bytes": 6,
            },
            thread_type="group",
            thread_id="g-1",
            sent_at="2026-08-09T01:00:00Z",
            chunks=[b"abc", b"123"],
        )
    )

    assert result.status == "downloaded"
    assert result.sha256 == hashlib.sha256(b"abc123").hexdigest()
    assert result.size_bytes == 6
    assert result.local_path is not None
    local_path = Path(result.local_path)
    assert local_path.read_bytes() == b"abc123"
    assert local_path.parent == tmp_path / "history" / "media" / "group" / "g-1" / "2026-08-09"
    assert re.fullmatch(r"[A-Za-z0-9._-]+", local_path.name)
    if os.name != "nt":
        assert stat.S_IMODE(local_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(local_path.parent.stat().st_mode) == 0o700

    row = attachment_row(store, attachment_id)
    assert row["download_status"] == "downloaded"
    assert row["sha256"] == result.sha256
    assert row["local_path"] == str(local_path)


def test_completed_attachment_is_not_downloaded_again(tmp_path: Path) -> None:
    store, _, attachment_id = make_pending_attachment(tmp_path, size_bytes=3)
    policy = MediaPolicy(tmp_path / "history", max_bytes=10)
    first = asyncio.run(
        policy.store_attachment(
            store=store,
            attachment_id=attachment_id,
            attachment={"filename": "once.bin", "size_bytes": 3},
            thread_type="group",
            thread_id="g-1",
            sent_at="2026-08-09T01:00:00Z",
            chunks=[b"abc"],
        )
    )

    def unread_stream():
        raise AssertionError("completed attachment must not be downloaded again")
        yield b"unreachable"

    second = asyncio.run(
        policy.store_attachment(
            store=store,
            attachment_id=attachment_id,
            attachment={"filename": "once.bin", "size_bytes": 3},
            thread_type="group",
            thread_id="g-1",
            sent_at="2026-08-09T01:00:00Z",
            chunks=unread_stream(),
        )
    )

    assert first.status == second.status == "downloaded"
    assert first.local_path == second.local_path
    assert Path(first.local_path or "").read_bytes() == b"abc"


def test_download_failure_marks_attachment_without_rolling_back_message(
    tmp_path: Path,
) -> None:
    store, message_id, attachment_id = make_pending_attachment(tmp_path, size_bytes=None)
    policy = MediaPolicy(tmp_path / "history", max_bytes=10)

    def broken_stream():
        yield b"abc"
        raise OSError("network disconnected")

    result = asyncio.run(
        policy.store_attachment(
            store=store,
            attachment_id=attachment_id,
            attachment={"filename": "broken.bin", "size_bytes": None},
            thread_type="group",
            thread_id="g-1",
            sent_at="2026-08-09T01:00:00Z",
            chunks=broken_stream(),
        )
    )

    assert result.status == "failed"
    assert attachment_row(store, attachment_id)["download_status"] == "failed"
    assert store.get_message(
        message_id,
        requester_id="admin",
        is_admin=True,
        allowed_groups=set(),
    ) is not None
    assert list((tmp_path / "history" / "media").rglob("*.part")) == []


def test_cancelled_download_cleans_partial_file_and_keeps_cancellation(
    tmp_path: Path,
) -> None:
    store, message_id, attachment_id = make_pending_attachment(tmp_path, size_bytes=None)
    policy = MediaPolicy(tmp_path / "history", max_bytes=10)

    async def cancelled_stream():
        yield b"abc"
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            policy.store_attachment(
                store=store,
                attachment_id=attachment_id,
                attachment={"filename": "cancelled.bin", "size_bytes": None},
                thread_type="group",
                thread_id="g-1",
                sent_at="2026-08-09T01:00:00Z",
                chunks=cancelled_stream(),
            )
        )

    assert attachment_row(store, attachment_id)["download_status"] == "failed"
    assert store.get_message(
        message_id,
        requester_id="admin",
        is_admin=True,
        allowed_groups=set(),
    ) is not None
    assert list((tmp_path / "history" / "media").rglob("*.part")) == []


def test_concurrent_downloads_for_one_attachment_are_serialized(tmp_path: Path) -> None:
    store, _, attachment_id = make_pending_attachment(tmp_path, size_bytes=3)
    policy = MediaPolicy(tmp_path / "history", max_bytes=10)

    async def run_downloads():
        first_started = asyncio.Event()
        release_first = asyncio.Event()

        async def first_stream():
            first_started.set()
            await release_first.wait()
            yield b"abc"

        first_task = asyncio.create_task(
            policy.store_attachment(
                store=store,
                attachment_id=attachment_id,
                attachment={"filename": "race.bin", "size_bytes": 3},
                thread_type="group",
                thread_id="g-1",
                sent_at="2026-08-09T01:00:00Z",
                chunks=first_stream(),
            )
        )
        await first_started.wait()
        second_task = asyncio.create_task(
            policy.store_attachment(
                store=store,
                attachment_id=attachment_id,
                attachment={"filename": "race.bin", "size_bytes": 3},
                thread_type="group",
                thread_id="g-1",
                sent_at="2026-08-09T01:00:00Z",
                chunks=[b"xyz"],
            )
        )
        await asyncio.sleep(0)
        release_first.set()
        return await asyncio.gather(first_task, second_task)

    first, second = asyncio.run(run_downloads())

    assert first.status == second.status == "downloaded"
    assert first.local_path == second.local_path
    assert Path(first.local_path or "").read_bytes() == b"abc"
    assert list((tmp_path / "history" / "media").rglob("*.part")) == []


def test_cleanup_failure_does_not_mask_download_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _, attachment_id = make_pending_attachment(tmp_path, size_bytes=None)
    policy = MediaPolicy(tmp_path / "history", max_bytes=10)
    original_unlink = Path.unlink

    def cleanup_fails(path: Path, *args: object, **kwargs: object) -> None:
        if path.name.endswith(".part"):
            raise PermissionError("cleanup denied")
        original_unlink(path, *args, **kwargs)

    def broken_stream():
        yield b"abc"
        raise OSError("network disconnected")

    monkeypatch.setattr(Path, "unlink", cleanup_fails)

    result = asyncio.run(
        policy.store_attachment(
            store=store,
            attachment_id=attachment_id,
            attachment={"filename": "cleanup.bin", "size_bytes": None},
            thread_type="group",
            thread_id="g-1",
            sent_at="2026-08-09T01:00:00Z",
            chunks=broken_stream(),
        )
    )

    assert result.status == "failed"
    assert attachment_row(store, attachment_id)["download_status"] == "failed"
