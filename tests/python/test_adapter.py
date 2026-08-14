from __future__ import annotations

import asyncio
import ast
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from aiohttp import web
from aiohttp.test_utils import TestServer

from admin import AdminService
import adapter as adapter_module
from adapter import ZaloAdapter
from company_config import CompanyConfig, CompanyConfigFile
from history_store import HistoryStore
from media_policy import MediaPolicy
from request_context import (
    MissingRequesterContext,
    Requester,
    bind_requester,
    current_requester,
)


def _company_config(*, context_messages: int = 100) -> CompanyConfig:
    return CompanyConfig.from_mapping(
        {
            "bridge_url": "http://127.0.0.1:8787",
            "bridge_token": "x" * 32,
            "allowed_users": ["member-1", "member-2", "admin"],
            "admin_users": ["admin"],
            "allowed_groups": ["company-group"],
            "group_mode": "mention",
            "history_context_messages": context_messages,
        }
    )


def _adapter(
    tmp_path,
    *,
    context_messages: int = 100,
    monotonic_clock=None,
) -> ZaloAdapter:
    platform_config = SimpleNamespace(extra={"group_sessions_per_user": True})
    store = HistoryStore(tmp_path / "history.sqlite3", account_id="company")
    extra_kwargs = {}
    if monotonic_clock is not None:
        extra_kwargs["monotonic_clock"] = monotonic_clock
    adapter = ZaloAdapter(
        platform_config,
        company_config=_company_config(context_messages=context_messages),
        history_store=store,
        media_policy=MediaPolicy(tmp_path / "history"),
        **extra_kwargs,
    )
    adapter._own_id = "bot-id"
    adapter._own_name = "Trợ lý"
    adapter._message_handler = object()
    return adapter


class _MonotonicClock:
    def __init__(self, now: float = 10_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _AsyncSseContent:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = iter(lines)

    def __aiter__(self):
        return self

    async def __anext__(self) -> bytes:
        try:
            return next(self._lines)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


def test_sse_cursor_starts_unset(tmp_path) -> None:
    adapter = _adapter(tmp_path)

    assert adapter._last_event_id is None


@pytest.mark.asyncio
async def test_sse_consumer_preserves_opaque_cursor_after_successful_handler(
    tmp_path,
) -> None:
    adapter = _adapter(tmp_path)
    handled: list[str] = []

    async def handle(_event_type: str, payload: str) -> None:
        handled.append(payload)
        if len(handled) == 2:
            raise RuntimeError("handler failed")

    adapter._handle_sse_event = handle
    response = SimpleNamespace(
        content=_AsyncSseContent(
            [
                b"id: generation-a:41\n",
                b"data: {\"index\": 1}\n",
                b"\n",
                b"id: generation-a:42\n",
                b"data: {\"index\": 2}\n",
                b"\n",
            ]
        )
    )

    with pytest.raises(RuntimeError, match="handler failed"):
        await adapter._consume_sse(response)

    assert adapter._last_event_id == "generation-a:41"


def test_apply_company_config_refreshes_default_tooling_reference(tmp_path) -> None:
    adapter = _adapter(tmp_path)
    updated = replace(adapter.company_config, allowed_groups=("new-group",))

    adapter._apply_company_config(updated)

    assert adapter.tooling.config is updated
    assert set(adapter.tooling.config.allowed_groups) == {"new-group"}


def test_history_retention_purges_expired_messages_at_startup(tmp_path) -> None:
    adapter = _adapter(tmp_path)
    adapter.company_config = replace(adapter.company_config, history_retention="90")
    adapter.history_store.store_message(
        thread_type="dm", thread_id="member-1", sender_id="member-1", text="expired",
        provider_message_id="expired", sent_at="2026-01-01T00:00:00+00:00",
    )
    adapter.history_store.store_message(
        thread_type="dm", thread_id="member-1", sender_id="member-1", text="current",
        provider_message_id="current", sent_at="2026-08-01T00:00:00+00:00",
    )

    result = adapter._apply_history_retention(
        now=adapter_module.datetime(2026, 8, 13, tzinfo=adapter_module.timezone.utc)
    )

    assert result["messages"] == 1
    assert [row["text"] for row in adapter.history_store.recent_messages("dm", "member-1")] == ["current"]


def test_history_retention_forever_is_a_noop(tmp_path) -> None:
    adapter = _adapter(tmp_path)
    adapter.company_config = replace(adapter.company_config, history_retention="forever")

    assert adapter._apply_history_retention() == {"messages": 0, "attachments": 0, "media_deleted": 0}


def test_admin_memory_path_matches_hermes_019_layout(tmp_path, monkeypatch) -> None:
    hermes_home = tmp_path / "hermes-home"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    adapter = _adapter(tmp_path)
    assert adapter.tooling.admin.memory_path == hermes_home / "memories" / "MEMORY.md"


def test_admin_status_exposes_redacted_provider_and_model_names(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_PROVIDER", "company-provider")
    monkeypatch.setenv("HERMES_MODEL", "company-model")

    adapter = _adapter(tmp_path)

    status = adapter._admin_status()

    assert status["provider"] == "company-provider"
    assert status["model"] == "company-model"
    assert status["sse_clients"] == 0
    assert status["gateway"] == {"status": "Đang chạy"}


def test_admin_status_reads_model_labels_from_gateway_config(tmp_path, monkeypatch) -> None:
    hermes_home = tmp_path / "hermes-home"
    hermes_home.mkdir()
    (hermes_home / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "model": {
                    "provider": "custom",
                    "default": "gpt-5.6-terra",
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.delenv("HERMES_PROVIDER", raising=False)
    monkeypatch.delenv("HERMES_PROVIDER_NAME", raising=False)
    monkeypatch.delenv("HERMES_MODEL", raising=False)
    monkeypatch.delenv("HERMES_MODEL_NAME", raising=False)

    adapter = _adapter(tmp_path)

    status = adapter._admin_status()

    assert status["provider"] == "custom"
    assert status["model"] == "gpt-5.6-terra"


@pytest.mark.asyncio
async def test_connect_accepts_gateway_reconnect_flag(tmp_path) -> None:
    platform_config = SimpleNamespace(extra={})
    store = HistoryStore(tmp_path / "history.sqlite3", account_id="company")
    adapter = ZaloAdapter(
        platform_config,
        company_config=replace(_company_config(), bridge_token=""),
        history_store=store,
        media_policy=MediaPolicy(tmp_path / "history"),
    )

    assert await adapter.connect(is_reconnect=True) is False


@pytest.mark.asyncio
async def test_admin_web_lifecycle_is_fail_soft_and_idempotent(tmp_path) -> None:
    calls: list[str] = []

    class FakeAdminWeb:
        is_running = False

        async def start(self):
            calls.append("start")
            self.is_running = True
            return True

        async def stop(self):
            calls.append("stop")
            self.is_running = False

    adapter = _adapter(tmp_path)
    fake = FakeAdminWeb()
    adapter.admin_web = fake

    await adapter._start_admin_web()
    await adapter._start_admin_web()

    assert calls == ["start"]
    await adapter.disconnect()
    assert calls == ["start", "stop"]


@pytest.mark.asyncio
async def test_session_dead_keeps_running_admin_web_for_qr_recovery(
    tmp_path,
) -> None:
    adapter = _adapter(tmp_path)
    notified: list[str] = []

    async def notify() -> None:
        notified.append("fatal")

    adapter._notify_fatal_error = notify
    adapter.admin_web = SimpleNamespace(is_running=True)

    await adapter._on_session_dead({"reason": "expired"})

    assert notified == []
    assert adapter.has_fatal_error is True


class _RunningAdminWeb:
    is_running = False

    async def start(self):
        self.is_running = True
        return True

    async def stop(self):
        self.is_running = False


async def _logged_out_health(_request):
    return web.json_response(
        {"ok": True, "loggedIn": False, "ownId": "bot-id", "qr": "pending"}
    )


@pytest.mark.asyncio
async def test_admin_web_keeps_adapter_loaded_when_bridge_needs_qr(
    tmp_path,
) -> None:
    app = web.Application()
    app.router.add_get("/health", _logged_out_health)
    server = TestServer(app)
    await server.start_server()
    adapter = _adapter(tmp_path)
    adapter._apply_company_config(
        replace(adapter.company_config, bridge_url=str(server.make_url("")).rstrip("/"))
    )
    adapter.admin_web = _RunningAdminWeb()
    try:
        assert await adapter.connect() is True
        assert adapter.has_fatal_error is True
        assert adapter.admin_web.is_running is True
    finally:
        await adapter.disconnect()
        await server.close()


@pytest.mark.asyncio
async def test_connect_still_fails_logged_out_without_admin_web(
    tmp_path,
) -> None:
    app = web.Application()
    app.router.add_get("/health", _logged_out_health)
    server = TestServer(app)
    await server.start_server()
    adapter = _adapter(tmp_path)
    adapter._apply_company_config(
        replace(adapter.company_config, bridge_url=str(server.make_url("")).rstrip("/"))
    )
    try:
        assert await adapter.connect() is False
    finally:
        await adapter.disconnect()
        await server.close()


@pytest.mark.asyncio
async def test_admin_web_keeps_adapter_loaded_when_bridge_is_down(
    tmp_path,
) -> None:
    server = TestServer(web.Application())
    await server.start_server()
    bridge_url = str(server.make_url("")).rstrip("/")
    await server.close()
    adapter = _adapter(tmp_path)
    adapter._apply_company_config(
        replace(adapter.company_config, bridge_url=bridge_url)
    )
    adapter.admin_web = _RunningAdminWeb()
    try:
        assert await adapter.connect() is True
        assert adapter.has_fatal_error is True
        assert adapter.admin_web.is_running is True
    finally:
        await adapter.disconnect()


@pytest.mark.asyncio
async def test_admin_access_apply_refreshes_tooling_config_for_history_authorization(
    tmp_path,
) -> None:
    initial = _company_config()
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {"gateway": {"platforms": {"zalo": {"extra": initial.to_mapping()}}}},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    store = HistoryStore(tmp_path / "history.sqlite3", account_id="company")
    admin = AdminService(store=store, config_file=CompanyConfigFile(config_path))
    adapter = ZaloAdapter(
        SimpleNamespace(extra={"group_sessions_per_user": True}),
        company_config=initial,
        history_store=store,
        media_policy=MediaPolicy(tmp_path / "history"),
        admin_service=admin,
    )
    store.store_message(
        thread_type="group",
        thread_id="company-group",
        sender_id="member-1",
        text="old group",
        provider_message_id="old-group-message",
    )

    admin_requester = Requester(
        requester_id="admin",
        thread_type="dm",
        thread_id="admin",
        is_admin=True,
        session_key="zalo:dm:admin",
    )
    snapshot = admin.get_access_config(requester=admin_requester)
    await admin.apply_access_config(
        allowed_users=[*sorted(initial.allowed_users), "member-3"],
        admin_users=sorted(initial.admin_users),
        allowed_groups=["new-group"],
        expected_fingerprint=snapshot["fingerprint"],
        requester=admin_requester,
    )
    store.store_message(
        thread_type="group",
        thread_id="new-group",
        sender_id="member-1",
        text="new group",
        provider_message_id="new-group-message",
    )

    member_requester = Requester(
        requester_id="member-1",
        thread_type="dm",
        thread_id="member-1",
        is_admin=False,
        session_key="zalo:dm:member-1",
    )
    with bind_requester(member_requester):
        old_result = json.loads(
            await adapter.tooling.zalo_history(
                {
                    "action": "recent",
                    "thread_type": "group",
                    "thread_id": "company-group",
                }
            )
        )
        new_result = json.loads(
            await adapter.tooling.zalo_history(
                {
                    "action": "recent",
                    "thread_type": "group",
                    "thread_id": "new-group",
                }
            )
        )

    assert "error" in old_result
    assert [item["provider_message_id"] for item in new_result["items"]] == [
        "new-group-message"
    ]


def _message(
    *,
    message_id: str,
    sender_id: str = "member-1",
    thread_id: str = "company-group",
    thread_type: str = "group",
    text: str = "nội dung",
    mentions: list[str] | None = None,
    attachment: dict | None = None,
) -> dict:
    message = {
        "messageId": message_id,
        "cliMsgId": f"cli-{message_id}",
        "threadId": thread_id,
        "threadType": thread_type,
        "senderId": sender_id,
        "senderName": sender_id,
        "text": text,
        "mentions": mentions or [],
        "ts": "2026-08-09T01:02:03Z",
    }
    if attachment is not None:
        message["msgType"] = "chat.recommended"
        message["attachment"] = attachment
    return message


def _capture_dispatch(adapter: ZaloAdapter):
    calls = []

    async def capture(event):
        calls.append((event, current_requester()))

    adapter.handle_message = capture
    return calls


@pytest.mark.asyncio
async def test_inbound_dm_matches_follow_up_after_store_before_hermes_dispatch(
    tmp_path,
) -> None:
    adapter = _adapter(tmp_path)
    order: list[str] = []

    class SpyFollowUp:
        def record_inbound_response(self, **_kwargs):
            order.append("follow-up")
            return []

    adapter.follow_ups = SpyFollowUp()

    async def capture(_event):
        order.append("hermes")

    adapter.handle_message = capture
    await adapter._on_inbound_message(
        _message(
            message_id="dm-follow-up",
            sender_id="member-1",
            thread_id="member-1",
            thread_type="user",
            text="Có",
        )
    )

    assert order == ["follow-up", "hermes"]
    assert adapter.history_store.recent_messages("dm", "member-1")[0]["text"] == "Có"


@pytest.mark.asyncio
async def test_follow_up_ticker_is_singleton_and_disconnect_cancels_it(tmp_path) -> None:
    adapter = _adapter(tmp_path)
    tick_started = asyncio.Event()
    release = asyncio.Event()

    async def tick():
        tick_started.set()
        await release.wait()
        return {"reminders": 0, "reports": 0}

    adapter.follow_ups.tick = tick
    adapter._bridge_available = True
    adapter._zalo_logged_in = True
    adapter._ensure_follow_up_task()
    first = adapter._follow_up_task
    adapter._ensure_follow_up_task()
    assert adapter._follow_up_task is first
    await asyncio.wait_for(tick_started.wait(), timeout=1)
    await adapter.disconnect()
    assert first is not None and first.done()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("kết bạn người này", "single"),
        ("Kết bạn với người này!", "single"),
        ("gửi lời mời kết bạn", "single"),
        ("add người này", "single"),
        ("ket ban nguoi nay", "single"),
        ("kết bạn những người này", "multiple"),
        ("kết bạn tất cả", "multiple"),
        ("hãy tóm tắt cuộc họp", None),
    ],
)
def test_friend_request_command_is_explicit(text: str, expected: str | None) -> None:
    assert adapter_module._friend_request_command(text) == expected


@pytest.mark.asyncio
async def test_contact_message_persists_contact_metadata_without_dispatch(
    tmp_path,
) -> None:
    adapter = _adapter(tmp_path)
    dispatches = _capture_dispatch(adapter)

    await adapter._on_inbound_message(
        _message(
            message_id="card-lan",
            sender_id="member-1",
            thread_type="group",
            attachment={
                "type": "chat.recommended",
                "contact": {"name": "Lan", "phone": "0901", "gUid": "uid-lan"},
            },
        )
    )

    row = adapter.history_store.recent_messages("group", "company-group")[0]
    assert row["extra"]["contact"] == {
        "name": "Lan",
        "phone": "0901",
        "gUid": "uid-lan",
    }
    assert dispatches == []


def _contact_message(
    *,
    message_id: str,
    name: str,
    g_uid: str,
    sender_id: str = "member-1",
    thread_id: str = "company-group",
    thread_type: str = "group",
    mentions: list[str] | None = None,
) -> dict:
    return _message(
        message_id=message_id,
        sender_id=sender_id,
        thread_id=thread_id,
        thread_type=thread_type,
        text=f"[contact: {name}]",
        mentions=mentions,
        attachment={
            "type": "chat.recommended",
            "contact": {"name": name, "gUid": g_uid},
        },
    )


@pytest.mark.asyncio
async def test_contact_friend_request_workflow_dm_admin_uses_nearest_card(
    tmp_path,
) -> None:
    adapter = _adapter(tmp_path)
    dispatches = _capture_dispatch(adapter)
    posts = []

    async def fake_post(path, body):
        posts.append((path, body))
        if path == "/friend/request":
            return {"success": True, "result": ""}
        return {
            "success": True,
            "result": {"message": {"msgId": "friend-report-1"}},
        }

    adapter._post = fake_post
    before_allowed = tuple(adapter.company_config.allowed_users)
    await adapter._on_inbound_message(
        _contact_message(
            message_id="dm-card",
            name="Lan",
            g_uid="uid-lan",
            sender_id="admin",
            thread_id="admin",
            thread_type="user",
        )
    )
    dispatches.clear()
    await adapter._on_inbound_message(
        _message(
            message_id="dm-command",
            sender_id="admin",
            thread_id="admin",
            thread_type="user",
            text="kết bạn người này",
        )
    )

    assert posts[0] == (
        "/friend/request",
        {"userId": "uid-lan", "msg": "Xin chào, tôi là trợ lý công ty."},
    )
    assert posts[1][0] == "/send"
    assert dispatches == []
    assert tuple(adapter.company_config.allowed_users) == before_allowed
    rows = adapter.history_store.recent_messages("dm", "admin")
    assert [
        (row["provider_message_id"], row["text"], row["is_bot"])
        for row in rows
        if row["is_bot"]
    ] == [("friend-report-1", "Kết quả kết bạn:\n- Lan: thành công", 1)]


@pytest.mark.asyncio
async def test_contact_friend_request_workflow_group_requires_admin_mention(
    tmp_path,
) -> None:
    adapter = _adapter(tmp_path)
    dispatches = _capture_dispatch(adapter)
    posts = []

    async def fake_post(path, body):
        posts.append((path, body))
        return {"success": True, "result": ""} if path == "/friend/request" else {"success": True}

    adapter._post = fake_post
    await adapter._on_inbound_message(
        _contact_message(message_id="group-card", name="Minh", g_uid="uid-minh")
    )
    await adapter._on_inbound_message(
        _message(
            message_id="group-no-mention",
            sender_id="admin",
            text="kết bạn người này",
            mentions=[],
        )
    )
    assert not any(path == "/friend/request" for path, _ in posts)
    assert len(dispatches) == 0

    await adapter._on_inbound_message(
        _message(
            message_id="group-admin-command",
            sender_id="admin",
            text="kết bạn người này",
            mentions=["bot-id"],
        )
    )
    assert sum(path == "/friend/request" for path, _ in posts) == 1
    assert len(dispatches) == 0


@pytest.mark.asyncio
async def test_contact_friend_request_workflow_member_is_told_to_contact_admin(
    tmp_path,
) -> None:
    adapter = _adapter(tmp_path)
    dispatches = _capture_dispatch(adapter)
    posts = []

    async def fake_post(path, body):
        posts.append((path, body))
        return {"success": True}

    adapter._post = fake_post
    await adapter._on_inbound_message(
        _contact_message(message_id="member-card", name="Hùng", g_uid="uid-hung")
    )
    await adapter._on_inbound_message(
        _message(
            message_id="member-command",
            sender_id="member-1",
            text="kết bạn người này",
            mentions=["bot-id"],
        )
    )

    assert not any(path == "/friend/request" for path, _ in posts)
    assert any(path == "/send" for path, _ in posts)
    assert "quản trị viên" in posts[-1][1]["text"]
    assert dispatches == []


@pytest.mark.asyncio
async def test_contact_friend_request_workflow_group_outsider_is_ignored(
    tmp_path,
) -> None:
    adapter = _adapter(tmp_path)
    posts = []

    async def fake_post(path, body):
        posts.append((path, body))
        return {"success": True}

    adapter._post = fake_post
    await adapter._on_inbound_message(
        _contact_message(message_id="outsider-card", name="Lan", g_uid="uid-lan")
    )
    await adapter._on_inbound_message(
        _message(
            message_id="outsider-command",
            sender_id="outsider",
            text="kết bạn người này",
            mentions=["bot-id"],
        )
    )

    assert posts == []


@pytest.mark.asyncio
async def test_contact_friend_request_workflow_batch_is_contiguous_and_sequential(
    tmp_path,
) -> None:
    adapter = _adapter(tmp_path)
    posts = []

    async def fake_post(path, body):
        posts.append((path, body))
        return {"success": True, "result": ""} if path == "/friend/request" else {"success": True}

    adapter._post = fake_post
    await adapter._on_inbound_message(
        _contact_message(message_id="old-card", name="Cũ", g_uid="uid-cu")
    )
    await adapter._on_inbound_message(
        _message(message_id="separator", sender_id="member-1", text="tin xen giữa")
    )
    await adapter._on_inbound_message(
        _contact_message(message_id="minh-card", name="Minh", g_uid="uid-minh")
    )
    await adapter._on_inbound_message(
        _contact_message(message_id="hung-card", name="Hùng", g_uid="uid-hung")
    )
    await adapter._on_inbound_message(
        _message(
            message_id="batch-command",
            sender_id="admin",
            text="kết bạn những người này",
            mentions=["bot-id"],
        )
    )

    requests = [body["userId"] for path, body in posts if path == "/friend/request"]
    assert requests == ["uid-minh", "uid-hung"]


@pytest.mark.asyncio
async def test_contact_friend_request_workflow_unknown_outcome_is_not_retried(
    tmp_path,
) -> None:
    adapter = _adapter(tmp_path)
    posts = []
    responses = iter(
        [
            {"error": "Zalo provider call timed out", "outcome": "unknown"},
            {"success": True},
        ]
    )

    async def fake_post(path, body):
        posts.append((path, body))
        return next(responses)

    adapter._post = fake_post
    await adapter._on_inbound_message(
        _contact_message(message_id="unknown-card", name="Lan", g_uid="uid-lan")
    )
    await adapter._on_inbound_message(
        _message(
            message_id="unknown-command",
            sender_id="admin",
            text="kết bạn người này",
            mentions=["bot-id"],
        )
    )

    assert [path for path, _ in posts].count("/friend/request") == 1


@pytest.mark.asyncio
async def test_allowed_group_is_stored_before_mention_gate(tmp_path) -> None:
    adapter = _adapter(tmp_path)
    calls = _capture_dispatch(adapter)

    await adapter._on_inbound_message(_message(message_id="group-unmentioned"))

    rows = adapter.history_store.recent_messages("group", "company-group")
    assert [row["provider_message_id"] for row in rows] == ["group-unmentioned"]
    assert calls == []


@pytest.mark.asyncio
async def test_group_text_prefix_without_real_mention_does_not_dispatch(tmp_path) -> None:
    adapter = _adapter(tmp_path)
    calls = _capture_dispatch(adapter)

    await adapter._on_inbound_message(
        _message(
            message_id="group-text-prefix",
            text="Hermes, hãy tóm tắt nội dung này",
            mentions=[],
        )
    )

    rows = adapter.history_store.recent_messages("group", "company-group")
    assert [row["provider_message_id"] for row in rows] == ["group-text-prefix"]
    assert calls == []


@pytest.mark.asyncio
async def test_group_reply_to_bot_without_real_mention_does_not_dispatch(tmp_path) -> None:
    adapter = _adapter(tmp_path)
    calls = _capture_dispatch(adapter)
    message = _message(
        message_id="group-reply-without-mention",
        text="hãy tóm tắt nội dung này",
        mentions=[],
    )
    message["quotedOwnerId"] = "bot-id"

    await adapter._on_inbound_message(message)

    rows = adapter.history_store.recent_messages("group", "company-group")
    assert [row["provider_message_id"] for row in rows] == [
        "group-reply-without-mention"
    ]
    assert calls == []


@pytest.mark.asyncio
async def test_reply_quote_object_is_normalized_to_text_for_hermes(tmp_path) -> None:
    adapter = _adapter(tmp_path)
    calls = _capture_dispatch(adapter)
    message = _message(
        message_id="reply-with-rich-quote",
        thread_type="user",
        thread_id="member-1",
        mentions=["bot-id"],
    )
    message["quote"] = {
        "msgId": "quoted-message",
        "content": {"msg": "tin nhắn được trích dẫn", "style": {"bold": True}},
    }

    await adapter._on_inbound_message(message)

    assert len(calls) == 1
    event = calls[0][0]
    assert event.reply_to_text == "tin nhắn được trích dẫn"
    assert isinstance(event.reply_to_text, str)


@pytest.mark.asyncio
async def test_group_sender_outside_allowlist_is_stored_but_not_dispatched(tmp_path) -> None:
    adapter = _adapter(tmp_path)
    calls = _capture_dispatch(adapter)

    await adapter._on_inbound_message(
        _message(
            message_id="outsider-group",
            sender_id="outsider",
            mentions=["bot-id"],
        )
    )

    rows = adapter.history_store.recent_messages("group", "company-group")
    assert [row["sender_id"] for row in rows] == ["outsider"]
    assert rows[0]["mentioned_bot"] == 1
    assert calls == []


@pytest.mark.asyncio
async def test_dm_only_stores_and_dispatches_allowed_members(tmp_path) -> None:
    adapter = _adapter(tmp_path)
    calls = _capture_dispatch(adapter)

    await adapter._on_inbound_message(
        _message(
            message_id="outsider-dm",
            sender_id="outsider",
            thread_id="outsider",
            thread_type="user",
        )
    )
    await adapter._on_inbound_message(
        _message(
            message_id="member-dm",
            sender_id="member-1",
            thread_id="member-1",
            thread_type="user",
        )
    )

    assert adapter.history_store.recent_messages("dm", "outsider") == []
    rows = adapter.history_store.recent_messages("dm", "member-1")
    assert [row["provider_message_id"] for row in rows] == ["member-dm"]
    assert len(calls) == 1
    event, requester = calls[0]
    assert event.source.chat_type == "dm"
    assert event.source.chat_id == "member-1"
    assert requester.requester_id == "member-1"
    assert requester.thread_type == "dm"
    assert requester.thread_id == "member-1"
    with pytest.raises(MissingRequesterContext):
        current_requester()


@pytest.mark.asyncio
async def test_outsider_dm_sends_one_notice_without_processing_or_storing(tmp_path) -> None:
    clock = _MonotonicClock()
    adapter = _adapter(tmp_path, monotonic_clock=clock)
    dispatches = _capture_dispatch(adapter)
    posts = []

    async def fake_post(path, body):
        posts.append((path, body))
        return {"success": True, "messageId": "provider-notice-id"}

    def fail_if_attachments_are_normalized(_message):
        raise AssertionError("outsider DM reached attachment processing")

    adapter._post = fake_post
    adapter._normalized_attachments = fail_if_attachments_are_normalized

    for index in range(3):
        message = _message(
            message_id=f"outsider-{index}",
            sender_id="outsider",
            thread_id="outsider",
            thread_type="user",
        )
        message["attachments"] = [{"url": "https://example.invalid/private"}]
        await adapter._on_inbound_message(message)

    assert posts == [
        (
            "/send",
            {
                "threadId": "outsider",
                "threadType": "user",
                "text": (
                    "Bạn chưa được cấp quyền sử dụng Trợ lý công ty. "
                    "Vui lòng liên hệ quản trị viên."
                ),
            },
        )
    ]
    assert adapter.history_store.recent_messages("dm", "outsider") == []
    assert "outsider" not in adapter._thread_types
    assert dispatches == []


@pytest.mark.asyncio
async def test_outsider_dm_notice_repeats_after_cooldown(tmp_path) -> None:
    clock = _MonotonicClock()
    adapter = _adapter(tmp_path, monotonic_clock=clock)
    posts = []

    async def fake_post(path, body):
        posts.append((path, body))
        return {"success": True}

    adapter._post = fake_post
    first = _message(
        message_id="outsider-first",
        sender_id="outsider",
        thread_id="outsider",
        thread_type="user",
    )
    await adapter._on_inbound_message(first)
    clock.advance(3599)
    await adapter._on_inbound_message({**first, "messageId": "outsider-early"})
    clock.advance(1)
    await adapter._on_inbound_message({**first, "messageId": "outsider-after"})

    assert [path for path, _body in posts] == ["/send", "/send"]


@pytest.mark.asyncio
async def test_outsider_dm_notice_uses_independent_sender_buckets(tmp_path) -> None:
    adapter = _adapter(tmp_path, monotonic_clock=_MonotonicClock())
    posts = []

    async def fake_post(path, body):
        posts.append((path, body))
        return {"success": True}

    adapter._post = fake_post
    for sender_id in ("outsider-a", "outsider-b", "outsider-a"):
        await adapter._on_inbound_message(
            _message(
                message_id=f"message-{sender_id}-{len(posts)}",
                sender_id=sender_id,
                thread_id=sender_id,
                thread_type="user",
            )
        )

    assert [body["threadId"] for _path, body in posts] == [
        "outsider-a",
        "outsider-b",
    ]


@pytest.mark.asyncio
async def test_allowed_dm_keeps_normal_history_and_dispatch_flow(tmp_path) -> None:
    adapter = _adapter(tmp_path, monotonic_clock=_MonotonicClock())
    dispatches = _capture_dispatch(adapter)

    async def unexpected_post(_path, _body):
        raise AssertionError("allowed DM used the outsider notice path")

    adapter._post = unexpected_post
    await adapter._on_inbound_message(
        _message(
            message_id="allowed-dm",
            sender_id="member-1",
            thread_id="member-1",
            thread_type="user",
        )
    )

    rows = adapter.history_store.recent_messages("dm", "member-1")
    assert [row["provider_message_id"] for row in rows] == ["allowed-dm"]
    assert adapter._thread_types["member-1"] == "user"
    assert len(dispatches) == 1


@pytest.mark.asyncio
async def test_outsider_dm_notice_map_is_bounded_and_prunes_expired_entries(
    tmp_path,
) -> None:
    clock = _MonotonicClock()
    adapter = _adapter(tmp_path, monotonic_clock=clock)
    posts = []

    async def fake_post(path, body):
        posts.append((path, body))
        return {"success": True}

    adapter._post = fake_post
    for index in range(1024):
        sender_id = f"outsider-{index}"
        await adapter._on_inbound_message(
            _message(
                message_id=f"message-{index}",
                sender_id=sender_id,
                thread_id=sender_id,
                thread_type="user",
            )
        )

    await adapter._on_inbound_message(
        _message(
            message_id="at-capacity",
            sender_id="new-outsider",
            thread_id="new-outsider",
            thread_type="user",
        )
    )
    assert len(adapter._unauthorized_dm_notice_times) == 1024
    assert "outsider-0" in adapter._unauthorized_dm_notice_times
    assert "new-outsider" not in adapter._unauthorized_dm_notice_times
    assert len(posts) == 1024

    clock.advance(3599)
    await adapter._on_inbound_message(
        _message(
            message_id="old-sender-before-expiry",
            sender_id="outsider-0",
            thread_id="outsider-0",
            thread_type="user",
        )
    )
    assert len(posts) == 1024

    clock.advance(1)
    await adapter._on_inbound_message(
        _message(
            message_id="after-prune",
            sender_id="new-outsider",
            thread_id="new-outsider",
            thread_type="user",
        )
    )
    assert adapter._unauthorized_dm_notice_times == {
        "new-outsider": clock.now,
    }
    assert len(posts) == 1025


@pytest.mark.asyncio
async def test_outsider_dm_notice_transport_failure_is_fail_soft(tmp_path) -> None:
    adapter = _adapter(tmp_path, monotonic_clock=_MonotonicClock())
    dispatches = _capture_dispatch(adapter)

    async def broken_post(_path, _body):
        raise RuntimeError("injected notice failure")

    def fail_if_attachments_are_normalized(_message):
        raise AssertionError("outsider DM reached attachment processing")

    adapter._post = broken_post
    adapter._normalized_attachments = fail_if_attachments_are_normalized
    message = _message(
        message_id="outsider-post-failure",
        sender_id="outsider",
        thread_id="outsider",
        thread_type="user",
    )
    message["attachments"] = [{"url": "https://example.invalid/private"}]

    await adapter._on_inbound_message(message)

    assert adapter.history_store.recent_messages("dm", "outsider") == []
    assert "outsider" not in adapter._thread_types
    assert dispatches == []


@pytest.mark.asyncio
async def test_outsider_dm_notice_preserves_cancellation(tmp_path) -> None:
    adapter = _adapter(tmp_path, monotonic_clock=_MonotonicClock())

    async def cancelled_post(_path, _body):
        raise asyncio.CancelledError

    adapter._post = cancelled_post

    with pytest.raises(asyncio.CancelledError):
        await adapter._on_inbound_message(
            _message(
                message_id="outsider-cancelled",
                sender_id="outsider",
                thread_id="outsider",
                thread_type="user",
            )
        )


@pytest.mark.asyncio
async def test_group_dispatch_uses_one_shared_session_and_store_is_visible(tmp_path) -> None:
    adapter = _adapter(tmp_path)
    observations = []

    async def capture(event):
        requester = current_requester()
        stored_ids = [
            row["provider_message_id"]
            for row in adapter.history_store.recent_messages(
                "group", "company-group"
            )
        ]
        observations.append((event, requester, stored_ids))

    adapter.handle_message = capture
    for message_id, sender_id in (("first", "member-1"), ("second", "member-2")):
        await adapter._on_inbound_message(
            _message(
                message_id=message_id,
                sender_id=sender_id,
                mentions=["bot-id"],
            )
        )

    assert observations[0][2] == ["first"]
    assert observations[1][2] == ["first", "second"]
    assert observations[0][1].session_key == observations[1][1].session_key
    assert observations[0][0].source.chat_type == "group"
    assert adapter.config.extra["group_sessions_per_user"] is False


@pytest.mark.asyncio
async def test_duplicate_inbound_message_is_not_dispatched_twice(tmp_path) -> None:
    adapter = _adapter(tmp_path)
    calls = _capture_dispatch(adapter)
    message = _message(message_id="duplicate", mentions=["bot-id"])

    await adapter._on_inbound_message(message)
    await adapter._on_inbound_message(message)

    assert len(adapter.history_store.recent_messages("group", "company-group")) == 1
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_context_contains_at_most_one_hundred_messages_in_order(tmp_path) -> None:
    adapter = _adapter(tmp_path, context_messages=100)
    calls = _capture_dispatch(adapter)
    for index in range(105):
        adapter.history_store.store_message(
            thread_type="group",
            thread_id="company-group",
            sender_id="member-1",
            sender_name="Thành viên",
            text=f"history-{index:03d}",
            provider_message_id=f"history-{index:03d}",
            sent_at=f"2026-08-08T00:{index // 60:02d}:{index % 60:02d}Z",
            mentioned_bot=index % 2 == 0,
            extra={
                "attachments": [
                    {"kind": "file", "filename": f"file-{index}.txt"}
                ]
            },
        )

    await adapter._on_inbound_message(
        _message(message_id="trigger", text="hãy tóm tắt", mentions=["bot-id"])
    )

    event = calls[0][0]
    context_lines = event.channel_context.splitlines()
    assert len(context_lines) <= 99  # Current trigger is the 100th message.
    assert "history-000" not in event.channel_context
    assert "history-104" in event.channel_context
    assert event.channel_context.index("history-006") < event.channel_context.index(
        "history-104"
    )
    assert "file-104.txt" in event.channel_context
    assert '"mentioned_bot":true' in event.channel_context


@pytest.mark.asyncio
async def test_outbound_is_stored_only_with_explicit_provider_message_id(tmp_path) -> None:
    adapter = _adapter(tmp_path)
    responses = iter(
        [
            {
                "success": True,
                "result": {"message": {"msgId": "provider-outbound"}},
            },
            {"success": True, "result": {"accepted": True}},
        ]
    )

    async def fake_post(_path, _body):
        return next(responses)

    adapter._post = fake_post
    first = await adapter.send("member-1", "câu trả lời thứ nhất")
    second = await adapter.send("member-1", "câu trả lời chưa có ID")

    rows = adapter.history_store.recent_messages("dm", "member-1")
    assert first.success is True
    assert first.message_id == "provider-outbound"
    assert second.success is True
    assert second.message_id is None
    assert [(row["provider_message_id"], row["text"], row["is_bot"]) for row in rows] == [
        ("provider-outbound", "câu trả lời thứ nhất", 1)
    ]


@pytest.mark.asyncio
async def test_unknown_send_outcome_is_not_retried_or_stored(tmp_path) -> None:
    adapter = _adapter(tmp_path)
    calls = []

    async def fake_post(path, body):
        calls.append((path, body))
        return {
            "error": "Zalo provider call timed out; outcome unknown",
            "outcome": "unknown",
        }

    adapter._post = fake_post
    result = await adapter.send("member-1", "không gửi lại")

    assert len(calls) == 1
    assert result.success is False
    assert result.retryable is False
    assert result.raw_response["outcome"] == "unknown"
    assert adapter.history_store.recent_messages("dm", "member-1") == []


@pytest.mark.asyncio
async def test_reaction_and_undo_events_are_deduped_and_persisted(tmp_path) -> None:
    adapter = _adapter(tmp_path)
    adapter.history_store.store_message(
        thread_type="group",
        thread_id="company-group",
        sender_id="member-1",
        text="message",
        provider_message_id="provider-message",
    )
    reaction = {
        "eventId": "reaction-1",
        "threadId": "company-group",
        "threadType": "group",
        "senderId": "member-2",
        "msgId": "provider-message",
        "icon": "HEART",
    }
    undo = {
        "eventId": "undo-1",
        "threadId": "company-group",
        "threadType": "group",
        "senderId": "member-1",
        "msgId": "provider-message",
    }
    await adapter._handle_sse_event("reaction", json.dumps(reaction))
    await adapter._handle_sse_event("reaction", json.dumps(reaction))
    await adapter._handle_sse_event("undo", json.dumps(undo))

    assert adapter.history_store.stats()["message_events"] == 2
    row = adapter.history_store.connection.execute(
        "SELECT recalled_at FROM messages WHERE provider_message_id='provider-message'"
    ).fetchone()
    assert row["recalled_at"] is not None


@pytest.mark.asyncio
async def test_non_message_sse_logs_do_not_repeat_content_or_credentials(
    tmp_path,
    caplog,
) -> None:
    adapter = _adapter(tmp_path)
    caplog.set_level("INFO", logger="adapter")

    await adapter._handle_sse_event(
        "friend_event",
        json.dumps(
            {
                "eventId": "friend-1",
                "threadId": "member-1",
                "content": "noi-dung-hoi-thoai-rieng",
                "authorization": "Basic dXNlcjpwYXNz",
            }
        ),
    )

    assert "friend_event" in caplog.text
    assert "friend-1" in caplog.text
    assert "noi-dung-hoi-thoai-rieng" not in caplog.text
    assert "dXNlcjpwYXNz" not in caplog.text

    caplog.clear()
    await adapter._handle_sse_event(
        "session_dead",
        json.dumps(
            {
                "code": "expired",
                "message": "Authorization: Basic c2Vzc2lvbi1zZWNyZXQ=",
            }
        ),
    )
    assert "c2Vzc2lvbi1zZWNyZXQ=" not in caplog.text


def test_adapter_never_logs_raw_exception_objects() -> None:
    source = Path(adapter_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    violations: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "logger"
        ):
            continue
        if func.attr == "exception":
            violations.append(node.lineno)
            continue
        if func.attr not in {"error", "warning"}:
            continue
        if any(
            isinstance(argument, ast.Name)
            and argument.id in {"e", "exc", "error"}
            for argument in node.args[1:]
        ):
            violations.append(node.lineno)
    assert violations == []


@pytest.mark.asyncio
async def test_media_download_errors_are_redacted_before_logging(
    tmp_path,
    caplog,
) -> None:
    adapter = _adapter(tmp_path)

    class BrokenRequest:
        async def __aenter__(self):
            raise RuntimeError("Authorization: Bearer secret-value")

        async def __aexit__(self, *_args):
            return False

    class BrokenSession:
        closed = False

        def get(self, *_args, **_kwargs):
            return BrokenRequest()

    adapter._session = BrokenSession()
    caplog.set_level("WARNING", logger="adapter")

    path, _message_type = await adapter._download_media(
        {"url": "https://example.invalid/file", "kind": "image"}
    )

    assert path is None
    assert "secret-value" not in caplog.text
    assert "[REDACTED]" in caplog.text


@pytest.mark.asyncio
async def test_outbound_attachment_is_stored_only_after_provider_id(tmp_path) -> None:
    adapter = _adapter(tmp_path)
    file_path = tmp_path / "report.txt"
    file_path.write_text("report", encoding="utf-8")
    responses = iter(
        [
            {"success": True, "result": {"message": {"msgId": "file-provider-id"}}},
            {"success": True, "result": {"accepted": True}},
        ]
    )

    async def fake_post(_path, _body):
        return next(responses)

    adapter._post = fake_post
    first = await adapter.send_document("member-1", str(file_path), caption="báo cáo")
    second = await adapter.send_document("member-1", str(file_path), caption="không có id")

    rows = adapter.history_store.recent_messages("dm", "member-1")
    assert first.message_id == "file-provider-id"
    assert second.message_id is None
    assert len(rows) == 1
    attachment = adapter.history_store.connection.execute(
        "SELECT local_path, download_status FROM attachments"
    ).fetchone()
    assert attachment["local_path"] == str(file_path)
    assert attachment["download_status"] == "downloaded"


@pytest.mark.asyncio
async def test_transport_error_is_ambiguous_and_never_marked_safe_to_retry(tmp_path) -> None:
    adapter = _adapter(tmp_path)

    class BrokenSession:
        closed = False

        def post(self, *_args, **_kwargs):
            raise OSError("connection reset after write")

    adapter._session = BrokenSession()
    result = await adapter._post("/send", {"threadId": "member-1", "text": "hello"})
    assert result["outcome"] == "unknown"


def test_plugin_registers_platform_three_tools_and_admin_hooks() -> None:
    class Context:
        def __init__(self):
            self.platform = None
            self.tools = []
            self.hooks = []

        def register_platform(self, **kwargs):
            self.platform = kwargs

        def register_tool(self, **kwargs):
            self.tools.append(kwargs)

        def register_hook(self, name, callback):
            self.hooks.append((name, callback))

    ctx = Context()
    adapter_module.register(ctx)
    assert ctx.platform is not None
    assert set(ctx.platform["required_env"]) == {"ZALO_PLUGIN_URL", "ZALO_PLUGIN_TOKEN"}
    assert {tool["name"] for tool in ctx.tools} == {"zalo", "zalo_history", "zalo_admin"}
    assert {name for name, _ in ctx.hooks} == {"pre_gateway_dispatch", "pre_tool_call", "post_tool_call"}


def test_validate_config_requires_runtime_token_and_company_allowlists(monkeypatch) -> None:
    monkeypatch.setenv("ZALO_PLUGIN_URL", "http://127.0.0.1:8787")
    monkeypatch.setenv("ZALO_PLUGIN_TOKEN", "t" * 32)
    assert adapter_module.check_requirements() is True
    assert adapter_module.validate_config(SimpleNamespace(extra={})) is False

    monkeypatch.setenv("ZALO_ALLOWED_USERS", "u-1,admin")
    monkeypatch.setenv("ZALO_ADMIN_USERS", "admin")
    monkeypatch.setenv("ZALO_ALLOWED_GROUPS", "g-1")
    assert adapter_module.validate_config(SimpleNamespace(extra={})) is True


def test_interactive_setup_writes_fail_closed_company_config_without_policy_picker(
    monkeypatch,
) -> None:
    import hermes_cli.setup as setup_module

    saved: dict[str, str] = {}
    prompts: list[str] = []
    existing = {"ZALO_PLUGIN_TOKEN": "t" * 32}

    def prompt(message, default=None, password=False):
        prompts.append(str(message))
        lowered = str(message).lower()
        if "bridge url" in lowered:
            return "http://127.0.0.1:8787"
        if "admin" in lowered or "quản trị" in lowered:
            return "admin"
        if ("allowed" in lowered and "user" in lowered) or "thành viên" in lowered:
            return "u-1,u-2,admin"
        if "group" in lowered or "thread" in lowered or "nhóm" in lowered:
            return "g-1"
        return default or ""

    monkeypatch.setattr(setup_module, "prompt", prompt)
    monkeypatch.setattr(setup_module, "prompt_yes_no", lambda *args, **kwargs: False)
    monkeypatch.setattr(setup_module, "save_env_value", saved.__setitem__)
    monkeypatch.setattr(setup_module, "get_env_value", lambda key: existing.get(key, ""))
    monkeypatch.setattr(setup_module, "print_header", lambda *args, **kwargs: None)
    monkeypatch.setattr(setup_module, "print_info", lambda *args, **kwargs: None)
    monkeypatch.setattr(setup_module, "print_warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        adapter_module,
        "_probe_health",
        lambda *_: {"loggedIn": True, "sessionDead": False},
    )
    monkeypatch.setattr(adapter_module, "_fetch_contacts", lambda *_: None)

    adapter_module.interactive_setup()

    assert saved["ZALO_ALLOWED_USERS"] == "u-1,u-2,admin"
    assert saved["ZALO_ADMIN_USERS"] == "admin"
    assert saved["ZALO_ALLOWED_GROUPS"] == "g-1"
    assert saved["ZALO_GROUP_MODE"] == "mention"
    assert "ZALO_ALLOWED_THREADS" not in saved
    assert "ZALO_ALLOWED_ACTION_GROUPS" not in saved
    assert "ZALO_ALLOWED_ACTIONS" not in saved
    assert not any("destructive" in message.lower() for message in prompts)
