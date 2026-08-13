from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PLUGIN_DIR = ROOT / "hermes-plugin"
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))

from history_store import HistoryStore
from media_policy import MediaPolicy


def test_sqlite_media_and_dedupe_survive_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "history" / "conversations.sqlite3"
    store = HistoryStore(db_path, account_id="company")
    message = store.store_message(
        thread_type="group",
        thread_id="g-1",
        sender_id="u-1",
        text="biên bản",
        provider_message_id="provider-1",
        sent_at="2026-08-09T01:00:00Z",
        attachments=[
            {
                "kind": "file",
                "filename": "bien-ban.txt",
                "size_bytes": 4,
                "download_status": "pending",
            }
        ],
    )
    policy = MediaPolicy(tmp_path / "history")
    downloaded = asyncio.run(
        policy.store_attachment(
            store=store,
            attachment_id=message.attachment_ids[0],
            attachment={"filename": "bien-ban.txt", "size_bytes": 4},
            thread_type="group",
            thread_id="g-1",
            sent_at="2026-08-09T01:00:00Z",
            chunks=[b"data"],
        )
    )
    store.close()

    reopened = HistoryStore(db_path, account_id="company")
    duplicate = reopened.store_message(
        thread_type="group",
        thread_id="g-1",
        sender_id="u-1",
        text="biên bản",
        provider_message_id="provider-1",
        sent_at="2026-08-09T01:00:00Z",
    )

    assert duplicate.inserted is False
    assert len(reopened.recent_messages("group", "g-1")) == 1
    attachment = reopened.get_attachment(
        message.attachment_ids[0],
        requester_id="admin",
        is_admin=True,
        allowed_groups=set(),
    )
    assert attachment is not None
    assert attachment["download_status"] == "downloaded"
    assert Path(downloaded.local_path or "").read_bytes() == b"data"
