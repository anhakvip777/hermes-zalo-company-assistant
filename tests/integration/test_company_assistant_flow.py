from __future__ import annotations

import asyncio
import json
import os
import runpy
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from aiohttp.test_utils import TestClient, TestServer


ROOT = Path(__file__).resolve().parents[2]
PLUGIN_DIR = ROOT / "hermes-plugin"
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))
if str(Path(__file__).parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent))

from admin import (
    AdminService,
    AdminWebApp,
    AdminWebSettings,
    hash_admin_password,
)
import adapter as adapter_module
from adapter import ZaloAdapter
from company_config import CompanyConfig, CompanyConfigFile
from fake_bridge import FakeCompanyBridge
from history_store import HistoryStore
from media_policy import MediaPolicy
from request_context import Requester, bind_requester, current_requester
from tooling import ZaloTooling


def test_acceptance_manifest_rejects_changed_paths_outside_registry(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "docs" / "architecture" / "file-manifest.md"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        "| File | Trách nhiệm |\n"
        "|---|---|\n"
        "| `listed.py` | Đã đăng ký |\n",
        encoding="utf-8",
    )
    (tmp_path / "listed.py").write_text("listed", encoding="utf-8")
    (tmp_path / "unlisted.py").write_text("unlisted", encoding="utf-8")
    namespace = runpy.run_path(str(ROOT / "scripts" / "acceptance.py"))
    manifest_check = namespace["manifest_check"]
    manifest_check.__globals__["ROOT"] = tmp_path
    manifest_check.__globals__["changed_paths"] = lambda: {
        "listed.py",
        "unlisted.py",
    }

    result = manifest_check()

    assert result["ok"] is False
    assert result["missing"] == []
    assert result["unexpected"] == ["unlisted.py"]


def company_config() -> CompanyConfig:
    return CompanyConfig.from_mapping(
        {
            "bridge_url": "http://127.0.0.1:8787",
            "bridge_token": "x" * 32,
            "allowed_users": ["u-1", "admin"],
            "admin_users": ["admin"],
            "allowed_groups": ["g-1"],
            "group_mode": "mention",
        }
    )


def member() -> Requester:
    return Requester(
        requester_id="u-1",
        thread_type="dm",
        thread_id="u-1",
        is_admin=False,
        session_key="zalo:dm:u-1",
    )


async def integration_web_client(
    tmp_path: Path,
    *,
    admin: AdminService,
    store: HistoryStore,
    bridge: FakeCompanyBridge,
) -> tuple[TestClient, str, str]:
    settings = AdminWebSettings(
        enabled=True,
        host="127.0.0.1",
        port=8790,
        password_hash=hash_admin_password(
            "mat-khau",
            salt=b"0123456789abcdef",
        ),
        session_secret=b"k" * 32,  # type: ignore[arg-type]
        session_ttl_seconds=3600,
    )
    web_app = AdminWebApp(
        settings=settings,
        admin=admin,
        store=store,
        bridge=bridge,
        export_root=tmp_path / "exports",
    )
    application = web_app.create_application()

    async def cleanup(_application) -> None:
        try:
            await web_app.stop()
        finally:
            store.close()

    application.on_cleanup.append(cleanup)
    client = TestClient(TestServer(application))
    await client.start_server()
    login = await client.post(
        "/admin/api/login",
        json={"password": "mat-khau"},
    )
    assert login.status == 200
    body = await login.json()
    return client, login.headers["Set-Cookie"].split(";", 1)[0], body["csrf"]


def test_legacy_config_migration_is_idempotent_and_never_persists_token(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "gateway:\n  platforms:\n    zalo:\n      enabled: true\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update(
        {
            "ZALO_PLUGIN_URL": "http://127.0.0.1:8787",
            "ZALO_PLUGIN_TOKEN": "do-not-write-this-secret",
            "ZALO_ALLOWED_USERS": "u-1,admin",
            "ZALO_ADMIN_USERS": "admin",
            "ZALO_ALLOWED_GROUPS": "g-1",
        }
    )
    command = [
        "node",
        str(ROOT / "scripts" / "migrate-v1.0.9-config.mjs"),
        "--config",
        str(config_path),
    ]
    first = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
    once = config_path.read_text(encoding="utf-8")
    second = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
    twice = config_path.read_text(encoding="utf-8")

    assert first.returncode == second.returncode == 0
    assert once == twice
    assert "do-not-write-this-secret" not in twice
    assert twice.count("extra:") == 1
    loaded = yaml.safe_load(twice)
    extra = loaded["gateway"]["platforms"]["zalo"]["extra"]
    assert extra["allowed_users"] == ["u-1", "admin"]
    assert extra["admin_users"] == ["admin"]
    assert extra["allowed_groups"] == ["g-1"]


def test_legacy_migration_targets_zalo_extra_when_another_platform_has_extra(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "gateway:\n"
        "  platforms:\n"
        "    telegram:\n"
        "      extra:\n"
        "        keep: true\n"
        "    zalo:\n"
        "      enabled: true\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update(
        {
            "ZALO_PLUGIN_URL": "http://127.0.0.1:8787",
            "ZALO_ALLOWED_USERS": "u-1,admin",
            "ZALO_ADMIN_USERS": "admin",
            "ZALO_ALLOWED_GROUPS": "g-1",
        }
    )
    command = [
        "node",
        str(ROOT / "scripts" / "migrate-v1.0.9-config.mjs"),
        "--config",
        str(config_path),
    ]
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)

    assert result.returncode == 0
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert loaded["gateway"]["platforms"]["telegram"]["extra"] == {"keep": True}
    zalo_extra = loaded["gateway"]["platforms"]["zalo"]["extra"]
    assert zalo_extra["allowed_users"] == ["u-1", "admin"]
    assert zalo_extra["admin_users"] == ["admin"]
    assert zalo_extra["allowed_groups"] == ["g-1"]


def test_legacy_migration_normalizes_group_mode_to_mention(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "gateway:\n"
        "  platforms:\n"
        "    zalo:\n"
        "      extra:\n"
        "        group_mode: all\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update(
        {
            "ZALO_PLUGIN_URL": "http://127.0.0.1:8787",
            "ZALO_ALLOWED_USERS": "u-1,admin",
            "ZALO_ADMIN_USERS": "admin",
            "ZALO_ALLOWED_GROUPS": "g-1",
            "ZALO_GROUP_MODE": "all",
        }
    )
    result = subprocess.run(
        [
            "node",
            str(ROOT / "scripts" / "migrate-v1.0.9-config.mjs"),
            "--config",
            str(config_path),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    extra = yaml.safe_load(config_path.read_text(encoding="utf-8"))["gateway"]["platforms"]["zalo"]["extra"]
    assert extra["group_mode"] == "mention"


def test_runtime_env_templates_include_gateway_plugin_url() -> None:
    env_template = (ROOT / "systemd" / "hermes-zalo-company.env.example").read_text(
        encoding="utf-8"
    )
    installer = (ROOT / "install.mjs").read_text(encoding="utf-8")
    assert "ZALO_PLUGIN_URL=http://127.0.0.1:8787" in env_template
    assert "ZALO_PLUGIN_URL" in installer


def test_systemd_templates_isolate_the_zalo_profile() -> None:
    gateway = (ROOT / "systemd" / "hermes-gateway.service").read_text(encoding="utf-8")
    bridge = (ROOT / "systemd" / "hermes-zalo-company-bridge.service").read_text(encoding="utf-8")
    env_template = (ROOT / "systemd" / "hermes-zalo-company.env.example").read_text(encoding="utf-8")

    for unit in (gateway, bridge):
        assert "User=hermes-zalo" in unit
        assert "Group=hermes-zalo" in unit
        assert "ProtectHome=true" in unit
        assert "ProtectSystem=strict" in unit
        assert "NoNewPrivileges=true" in unit
    assert "HERMES_HOME=/var/lib/hermes-zalo/profile" in gateway
    assert "HERMES_HOME=/var/lib/hermes-zalo/profile" in env_template
    assert "ZALO_HISTORY_RETENTION=90" in env_template


def test_plugin_loads_with_hermes_directory_package_semantics() -> None:
    script = r'''
from pathlib import Path
from hermes_cli.plugins import PluginManager

plugin_dir = Path("hermes-plugin").resolve()
manager = PluginManager()
manifest = manager._parse_manifest(
    plugin_dir / "plugin.yaml",
    plugin_dir,
    "project",
    "",
)
assert manifest is not None
manager._load_plugin(manifest)
loaded = manager._plugins[manifest.key or manifest.name]
assert loaded.enabled and loaded.error is None
assert set(loaded.tools_registered) == {"zalo", "zalo_history", "zalo_admin"}
assert set(loaded.hooks_registered) == {
    "pre_gateway_dispatch",
    "pre_tool_call",
    "post_tool_call",
}
assert "zalo" in manager._plugin_platform_names
'''
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_target_hermes_exposes_required_plugin_contracts() -> None:
    from dataclasses import fields

    from gateway.platform_registry import PlatformEntry
    from gateway.platforms.base import MessageEvent

    assert "env_enablement_fn" in {field.name for field in fields(PlatformEntry)}
    assert "channel_context" in {field.name for field in fields(MessageEvent)}


def test_plugin_manifest_keeps_admin_web_env_optional_for_hermes_019() -> None:
    manifest = yaml.safe_load(
        (PLUGIN_DIR / "plugin.yaml").read_text(encoding="utf-8")
    )
    required = {item["name"] for item in manifest["requires_env"]}
    optional = {item["name"] for item in manifest["optional_env"]}
    admin_names = {
        "ZALO_ADMIN_WEB_ENABLED",
        "ZALO_ADMIN_WEB_HOST",
        "ZALO_ADMIN_WEB_PORT",
        "ZALO_ADMIN_WEB_PASSWORD_HASH",
        "ZALO_ADMIN_WEB_SESSION_SECRET",
        "ZALO_ADMIN_WEB_SESSION_TTL_SECONDS",
    }
    assert admin_names <= optional
    assert admin_names.isdisjoint(required)


@pytest.mark.asyncio
async def test_real_adapter_stores_group_before_gate_and_dispatches_only_allowed_mention(
    tmp_path: Path,
) -> None:
    previous_active_adapter = adapter_module._ACTIVE_ADAPTER
    store = HistoryStore(tmp_path / "history.sqlite3", account_id="company")
    try:
        adapter = ZaloAdapter(
            SimpleNamespace(extra={}),
            company_config=company_config(),
            history_store=store,
            media_policy=MediaPolicy(tmp_path / "history"),
        )
        adapter._own_id = "bot-id"
        adapter._own_name = "Trợ lý công ty"
        adapter._message_handler = object()
        dispatches: list[tuple[object, Requester, list[str]]] = []

        async def capture(event) -> None:
            dispatches.append(
                (
                    event,
                    current_requester(),
                    [
                        row["provider_message_id"]
                        for row in store.recent_messages("group", "g-1")
                    ],
                )
            )

        def group_message(
            message_id: str,
            sender_id: str,
            *,
            text: str,
            mentions: list[str],
        ) -> dict[str, object]:
            return {
                "messageId": message_id,
                "cliMsgId": f"cli-{message_id}",
                "threadId": "g-1",
                "threadType": "group",
                "threadName": "Group AI",
                "senderId": sender_id,
                "senderName": sender_id,
                "text": text,
                "mentions": mentions,
                "ts": "2026-08-11T01:02:03Z",
            }

        adapter.handle_message = capture
        await adapter._on_inbound_message(
            group_message(
                "without-real-mention",
                "u-1",
                text="Trợ lý công ty, hãy ghi nhận nội dung này",
                mentions=[],
            )
        )
        assert [
            row["provider_message_id"]
            for row in store.recent_messages("group", "g-1")
        ] == ["without-real-mention"]
        assert dispatches == []

        await adapter._on_inbound_message(
            group_message(
                "outsider-real-mention",
                "outsider",
                text="@Trợ lý công ty hãy trả lời",
                mentions=["bot-id"],
            )
        )
        assert [
            (row["provider_message_id"], row["sender_id"], row["mentioned_bot"])
            for row in store.recent_messages("group", "g-1")
        ] == [
            ("without-real-mention", "u-1", 0),
            ("outsider-real-mention", "outsider", 1),
        ]
        assert dispatches == []

        await adapter._on_inbound_message(
            group_message(
                "allowed-real-mention",
                "u-1",
                text="@Trợ lý công ty hãy trả lời",
                mentions=["bot-id"],
            )
        )
        assert len(dispatches) == 1
        event, requester, stored_ids_at_dispatch = dispatches[0]
        assert stored_ids_at_dispatch == [
            "without-real-mention",
            "outsider-real-mention",
            "allowed-real-mention",
        ]
        assert event.metadata["stored_message_id"] == store.recent_messages(
            "group", "g-1"
        )[-1]["id"]
        assert requester.requester_id == "u-1"
        assert requester.thread_type == "group"
        assert requester.thread_id == "g-1"
        assert requester.is_admin is False
        assert requester.session_key.endswith("zalo:group:g-1")

        await adapter._on_inbound_message(
            group_message(
                "admin-real-mention",
                "admin",
                text="@Trợ lý công ty kiểm tra quyền quản trị",
                mentions=["bot-id"],
            )
        )
        assert len(dispatches) == 2
        assert dispatches[1][1].requester_id == "admin"
        assert dispatches[1][1].is_admin is True
    finally:
        adapter_module._ACTIVE_ADAPTER = previous_active_adapter
        store.close()


@pytest.mark.asyncio
async def test_follow_up_group_message_is_not_response_and_report_targets_owner(
    tmp_path: Path,
) -> None:
    previous_active_adapter = adapter_module._ACTIVE_ADAPTER
    store = HistoryStore(tmp_path / "history.sqlite3", account_id="company")
    try:
        adapter = ZaloAdapter(
            SimpleNamespace(extra={}),
            company_config=company_config(),
            history_store=store,
            media_policy=MediaPolicy(tmp_path / "history"),
        )
        adapter._own_id = "bot-id"
        adapter._own_name = "Trợ lý công ty"
        adapter._message_handler = object()
        sent: list[tuple[str, str]] = []

        async def fake_send(chat_id: str, content: str, *args, **kwargs):
            sent.append((str(chat_id), str(content)))
            return SimpleNamespace(
                success=True,
                message_id=f"out-{len(sent)}",
                raw_response={"success": True},
            )

        adapter.send = fake_send
        adapter.handle_message = lambda _event: asyncio.sleep(0)
        adapter.follow_ups.now = lambda: datetime(2026, 8, 14, 9, tzinfo=timezone.utc)
        with bind_requester(
            Requester(
                requester_id="admin",
                thread_type="dm",
                thread_id="admin",
                is_admin=True,
                session_key="zalo:dm:admin",
            )
        ):
            created = json.loads(
                await adapter.tooling.zalo_admin(
                    {
                        "action": "follow_up_create",
                        "title": "Họp",
                        "question": "Có họp không?",
                        "targets": [{"zalo_id": "u-1", "name": "Lan"}],
                        "due_at": "2026-08-15T10:00:00Z",
                    }
                )
            )
        adapter.follow_ups.now = lambda: datetime(2026, 8, 15, 10, tzinfo=timezone.utc)

        await adapter._on_inbound_message(
            {
                "messageId": "group-reply",
                "cliMsgId": "cli-group-reply",
                "threadId": "g-1",
                "threadType": "group",
                "threadName": "Group AI",
                "senderId": "u-1",
                "senderName": "Lan",
                "text": "Có",
                "mentions": [],
                "ts": "2026-08-15T11:00:00Z",
            }
        )
        await adapter.follow_ups.tick()

        assert [recipient for recipient, _ in sent] == ["u-1", "u-1", "admin"]
        target = store.follow_up_targets(created["follow_up_id"])[0]
        assert target["response_kind"] is None
        assert "Chưa phản hồi" in sent[-1][1]
    finally:
        adapter_module._ACTIVE_ADAPTER = previous_active_adapter
        store.close()


@pytest.mark.asyncio
async def test_admin_web_login_overview_apply_history_and_bridge_down(
    tmp_path: Path,
) -> None:
    bridge = FakeCompanyBridge()
    store = HistoryStore(tmp_path / "history.sqlite3")
    store.store_message(
        thread_type="group",
        thread_id="g-1",
        sender_id="u-1",
        text="mai họp 9 giờ",
        provider_message_id="seed-1",
    )
    store.store_message(
        thread_type="dm",
        thread_id="u-other",
        sender_id="u-other",
        text="không thuộc phạm vi export/xóa",
        provider_message_id="seed-other",
        sent_at="2026-08-09T00:00:00Z",
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "gateway": {
                    "platforms": {
                        "zalo": {"extra": company_config().to_mapping()}
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    runtime = [company_config()]
    admin = AdminService(
        config_file=CompanyConfigFile(config_path),
        store=store,
        status_provider=lambda: {
            "success": True,
            "connected": bridge.available and bridge.logged_in,
            "bot": bridge.profile,
            "provider": "unknown",
            "model": "unknown",
        },
        runtime_config_provider=lambda: runtime[-1],
        runtime_config_applier=runtime.append,
        export_root=tmp_path / "exports",
    )
    client, cookie, csrf = await integration_web_client(
        tmp_path,
        admin=admin,
        store=store,
        bridge=bridge,
    )
    try:
        overview = await client.get(
            "/admin/api/overview",
            headers={"Cookie": cookie},
        )
        assert (await overview.json())["bot"]["id"] == "bot-id"
        friends = await client.get(
            "/admin/api/friends",
            headers={"Cookie": cookie},
        )
        assert (await friends.json())["items"][0]["id"] == "u-1"
        access = await (
            await client.get(
                "/admin/api/access",
                headers={"Cookie": cookie},
            )
        ).json()
        applied = await client.post(
            "/admin/api/access/apply",
            headers={"Cookie": cookie, "X-CSRF-Token": csrf},
            json={**access, "allowed_groups": ["g-1", "g-2"]},
        )
        assert applied.status == 200
        applied_body = await applied.json()
        assert applied_body["config"]["allowed_groups"] == ["g-1", "g-2"]
        access_after = await (
            await client.get(
                "/admin/api/access",
                headers={"Cookie": cookie},
            )
        ).json()
        assert access_after["allowed_groups"] == ["g-1", "g-2"]
        runtime_after = runtime[-1]
        assert runtime_after.allowed_users == frozenset(
            access_after["allowed_users"]
        )
        assert runtime_after.admin_users == frozenset(
            access_after["admin_users"]
        )
        assert runtime_after.allowed_groups == frozenset({"g-1", "g-2"})
        persisted = CompanyConfigFile(config_path).read_access_config()
        assert persisted.config.allowed_users == runtime_after.allowed_users
        assert persisted.config.admin_users == runtime_after.admin_users
        assert persisted.config.allowed_groups == frozenset({"g-1", "g-2"})
        groups = await (
            await client.get(
                "/admin/api/groups",
                headers={"Cookie": cookie},
            )
        ).json()
        assert groups["items"] == [
            {"id": "g-1", "name": "Group AI", "memberCount": 2}
        ]
        members = await (
            await client.get(
                "/admin/api/groups/g-1/members",
                headers={"Cookie": cookie},
            )
        ).json()
        assert {(item["id"], item["name"]) for item in members["items"]} == {
            ("u-1", "Lan"),
            ("admin", "Việt Anh"),
        }
        conversations = await (
            await client.get(
                "/admin/api/conversations",
                headers={"Cookie": cookie},
            )
        ).json()
        assert conversations["items"][0]["thread_id"] == "g-1"

        exported = await client.post(
            "/admin/api/history/export",
            headers={"Cookie": cookie, "X-CSRF-Token": csrf},
            json={"thread_type": "group", "thread_id": "g-1"},
        )
        assert exported.status == 200
        exported_rows = [
            json.loads(line)
            for line in (await exported.text()).splitlines()
            if line
        ]
        assert [
            (row["thread_type"], row["thread_id"], row["text"])
            for row in exported_rows
        ] == [("group", "g-1", "mai họp 9 giờ")]
        export_paths = list((tmp_path / "exports").glob("history-*.jsonl"))
        assert len(export_paths) == 1
        assert export_paths[0].resolve().parent == (tmp_path / "exports").resolve()

        deleted = await client.post(
            "/admin/api/history/delete",
            headers={"Cookie": cookie, "X-CSRF-Token": csrf},
            json={
                "thread_type": "group",
                "thread_id": "g-1",
                "confirm": True,
            },
        )
        assert deleted.status == 200
        assert (await deleted.json())["messages"] == 1
        assert store.recent_messages("group", "g-1") == []
        assert [
            row["text"] for row in store.recent_messages("dm", "u-other")
        ] == ["không thuộc phạm vi export/xóa"]
        audit_rows = store.connection.execute(
            "SELECT requester_id, thread_type, thread_id, tool_name, status "
            "FROM tool_activity "
            "WHERE tool_name IN "
            "('admin_web.history_export', 'admin_web.history_delete') "
            "ORDER BY id"
        ).fetchall()
        assert [tuple(row) for row in audit_rows] == [
            (
                "web-admin",
                "system",
                "admin-web",
                "admin_web.history_export",
                "success",
            ),
            (
                "web-admin",
                "system",
                "admin-web",
                "admin_web.history_delete",
                "success",
            ),
        ]

        bridge.available = False
        system = await client.get(
            "/admin/api/system",
            headers={"Cookie": cookie},
        )
        assert system.status == 200
        system_body = await system.json()
        assert system_body["bridge"] == {
            "error": "bridge unavailable",
            "outcome": "failed",
        }
        assert company_config().bridge_token not in json.dumps(system_body)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_admin_web_qr_start_returns_accepted_while_login_is_pending(
    tmp_path: Path,
) -> None:
    bridge = FakeCompanyBridge()
    store = HistoryStore(tmp_path / "history.sqlite3")
    gate = asyncio.Event()
    calls: list[str] = []

    async def login_qr(_args=None):
        calls.append("login_qr")
        await gate.wait()
        return {"success": True}

    admin = AdminService(
        store=store,
        status_provider=lambda: {"success": True},
        lifecycle={"login_qr": login_qr},
    )
    client, cookie, csrf = await integration_web_client(
        tmp_path,
        admin=admin,
        store=store,
        bridge=bridge,
    )
    try:
        first = await client.post(
            "/admin/api/system/qr",
            headers={"Cookie": cookie, "X-CSRF-Token": csrf},
            json={},
        )
        second = await client.post(
            "/admin/api/system/qr",
            headers={"Cookie": cookie, "X-CSRF-Token": csrf},
            json={},
        )
        await asyncio.sleep(0)
        assert first.status == second.status == 202
        assert calls == ["login_qr"]
        image = await client.get(
            "/admin/api/system/qr.png",
            headers={"Cookie": cookie},
        )
        assert image.status == 200
    finally:
        gate.set()
        await asyncio.sleep(0)
        await client.close()


@pytest.mark.parametrize("outcome", ["unknown", "failed"])
@pytest.mark.asyncio
async def test_admin_web_restart_outcome_is_accepted_once_without_auto_retry(
    tmp_path: Path,
    outcome: str,
) -> None:
    bridge = FakeCompanyBridge()
    store = HistoryStore(tmp_path / "history.sqlite3")
    started = asyncio.Event()
    release = asyncio.Event()
    completed = asyncio.Event()
    calls: list[tuple[str, str]] = []

    async def restart(args=None):
        calls.append(("restart", str((args or {}).get("target") or "")))
        started.set()
        await release.wait()
        completed.set()
        return {
            "success": False,
            "outcome": outcome,
            "error": "restart result unavailable",
        }

    admin = AdminService(
        store=store,
        status_provider=lambda: {"success": True},
        lifecycle={"restart": restart},
    )
    client, cookie, csrf = await integration_web_client(
        tmp_path,
        admin=admin,
        store=store,
        bridge=bridge,
    )
    try:
        first = await asyncio.wait_for(
            client.post(
                "/admin/api/system/restart",
                headers={"Cookie": cookie, "X-CSRF-Token": csrf},
                json={"target": "bridge"},
            ),
            timeout=1,
        )
        second = await asyncio.wait_for(
            client.post(
                "/admin/api/system/restart",
                headers={"Cookie": cookie, "X-CSRF-Token": csrf},
                json={"target": "bridge"},
            ),
            timeout=1,
        )
        assert first.status == second.status == 202
        await asyncio.wait_for(started.wait(), timeout=1)
        assert calls == [("restart", "bridge")]

        release.set()
        await asyncio.wait_for(completed.wait(), timeout=1)
        await asyncio.sleep(AdminWebApp.RESTART_COOLDOWN_SECONDS + 0.1)
        assert calls == [("restart", "bridge")]
        audits = store.connection.execute(
            "SELECT status FROM tool_activity "
            "WHERE tool_name='admin_web.restart' ORDER BY id"
        ).fetchall()
        assert [row["status"] for row in audits] == ["unknown"]
    finally:
        release.set()
        await client.close()


@pytest.mark.asyncio
async def test_member_calls_zalo_surface_with_redaction_and_activity_log(tmp_path: Path) -> None:
    bridge = FakeCompanyBridge()
    store = HistoryStore(tmp_path / "history.sqlite3")
    tooling = ZaloTooling(bridge=bridge, store=store, config=company_config())

    with bind_requester(member()):
        result = json.loads(
            await tooling.zalo(
                {
                    "action": "call",
                    "method": "createPoll",
                    "params": {"groupId": "g-1", "question": "Ăn trưa?", "options": ["A", "B"]},
                }
            )
        )

    assert result["success"] is True
    assert "never-leak" not in json.dumps(result)
    assert bridge.calls[-1]["path"] == "/api/createPoll"
    assert store.stats()["tool_activity"] == 1


@pytest.mark.asyncio
async def test_unknown_provider_outcome_is_returned_once_without_retry(tmp_path: Path) -> None:
    bridge = FakeCompanyBridge()
    bridge.next_outcome = {"error": "deadline exceeded", "outcome": "unknown"}
    store = HistoryStore(tmp_path / "history.sqlite3")
    tooling = ZaloTooling(bridge=bridge, store=store, config=company_config())

    with bind_requester(member()):
        result = json.loads(await tooling.zalo({"action": "call", "method": "sendMessage", "args": ["hi"]}))

    assert result["outcome"] == "unknown"
    assert [call["path"] for call in bridge.calls].count("/api/sendMessage") == 1
    row = store.connection.execute("SELECT status FROM tool_activity").fetchone()
    assert row["status"] == "unknown"
