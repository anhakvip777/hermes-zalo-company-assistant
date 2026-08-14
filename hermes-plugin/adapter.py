"""
Zalo Platform Adapter for Hermes Agent.

Bridges to a companion Node.js process (hermes-zalo-plugin) that runs
zca-js (the unofficial Zalo personal API). Communication:

    inbound  : SSE stream  GET  {bridge}/events   (Zalo -> Hermes)
    outbound : REST        POST {bridge}/send, /send-attachment, ...

Configuration in config.yaml::

    gateway:
      platforms:
        zalo:
          enabled: true
          extra:
            bridge_url: "http://127.0.0.1:8787"
            allowed_users: ["member-1", "member-2"]
            admin_users: ["member-1"]
            allowed_groups: ["company-group"]
            group_mode: "mention"        # store all group messages; reply on allowed mention
            history_context_messages: 100
            media_max_bytes: 20971520

Or via environment variables (override config.yaml):
    ZALO_PLUGIN_URL, ZALO_PLUGIN_TOKEN, ZALO_ALLOWED_USERS,
    ZALO_ADMIN_USERS, ZALO_ALLOWED_GROUPS, ZALO_GROUP_MODE,
    ZALO_HOME_CHANNEL
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import time
import unicodedata
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


from gateway.platforms.base import (
    BasePlatformAdapter,
    SendResult,
    MessageEvent,
    MessageType,
    cache_image_from_bytes,
    cache_audio_from_bytes,
    cache_document_from_bytes,
)
from gateway.config import Platform
from gateway.session import build_session_key

try:
    from .admin import (
        AdminService,
        AdminWebApp,
        AdminWebSettings,
        AdminWebSettingsError,
    )
    from .company_config import CompanyConfig, CompanyConfigError, CompanyConfigFile
    from .history_store import HistoryStore, StoredMessage, redact_text
    from .follow_up import FollowUpService
    from .media_policy import MediaPolicy
    from .request_context import Requester, bind_requester
    from .tooling import ZaloTooling, register_tooling
except ImportError:  # Hermes also loads platform adapters as top-level modules.
    from admin import (
        AdminService,
        AdminWebApp,
        AdminWebSettings,
        AdminWebSettingsError,
    )
    from company_config import CompanyConfig, CompanyConfigError, CompanyConfigFile
    from history_store import HistoryStore, StoredMessage, redact_text
    from follow_up import FollowUpService
    from media_policy import MediaPolicy
    from request_context import Requester, bind_requester
    from tooling import ZaloTooling, register_tooling


_ACTIVE_ADAPTER: Optional["ZaloAdapter"] = None
_UNAUTHORIZED_DM_NOTICE = (
    "Bạn chưa được cấp quyền sử dụng Trợ lý công ty. "
    "Vui lòng liên hệ quản trị viên."
)


class _AdapterBridge:
    def __init__(self, adapter: "ZaloAdapter") -> None:
        self.adapter = adapter

    async def request(self, method, path, payload=None, params=None):
        if str(method).upper() == "GET":
            return await self.adapter._get(path, params=dict(params or {}))
        return await self.adapter._post(path, dict(payload or {}))

    async def request_bytes(self, path, params=None):
        return await self.adapter._get_bytes(path, params=dict(params or {}))


class _LazyTooling:
    @staticmethod
    def _current() -> ZaloTooling:
        if _ACTIVE_ADAPTER is None or not hasattr(_ACTIVE_ADAPTER, "tooling"):
            raise RuntimeError("Zalo adapter is not active")
        return _ACTIVE_ADAPTER.tooling

    async def zalo(self, args, **kwargs):
        try:
            return await self._current().zalo(args, **kwargs)
        except RuntimeError as exc:
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

    async def zalo_history(self, args, **kwargs):
        try:
            return await self._current().zalo_history(args, **kwargs)
        except RuntimeError as exc:
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

    async def zalo_admin(self, args, **kwargs):
        try:
            return await self._current().zalo_admin(args, **kwargs)
        except RuntimeError as exc:
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

    def on_pre_gateway_dispatch(self, **kwargs):
        if _ACTIVE_ADAPTER is None:
            return None
        return self._current().on_pre_gateway_dispatch(**kwargs)

    def on_pre_tool_call(self, **kwargs):
        if _ACTIVE_ADAPTER is None:
            return None
        return self._current().on_pre_tool_call(**kwargs)

    def on_post_tool_call(self, **kwargs):
        if _ACTIVE_ADAPTER is None:
            return None
        return self._current().on_post_tool_call(**kwargs)


_LAZY_TOOLING = _LazyTooling()


def _truthy(v) -> bool:
    return str(v if v is not None else "").strip().lower() in {"1", "true", "yes", "on"}


def _status_label(value: Any, default: str = "unknown") -> str:
    raw = redact_text(str(value or "").strip())
    if not raw or len(raw) > 128 or "://" in raw:
        return default
    return raw


def _configured_model_labels(hermes_home: Path) -> tuple[Optional[str], Optional[str]]:
    """Read non-secret provider/model labels from Hermes' model config."""
    try:
        import yaml

        payload = yaml.safe_load(
            (hermes_home / "config.yaml").read_text(encoding="utf-8")
        )
    except (OSError, TypeError, ValueError):
        return None, None
    if not isinstance(payload, dict) or not isinstance(payload.get("model"), dict):
        return None, None
    model = payload["model"]
    provider = _status_label(model.get("provider"), default="") or None
    model_name = _status_label(
        model.get("default") or model.get("model"), default=""
    ) or None
    return provider, model_name


def _parse_home_channel(raw: str) -> tuple[str, str]:
    """Parse ZALO_HOME_CHANNEL into (chat_id, thread_type).

    Accepts ``<threadId>`` (defaults to user) or ``<type>:<threadId>``
    where type is ``user`` or ``group``.
    """
    raw = str(raw or "").strip()
    if not raw:
        return "", "user"
    if ":" in raw:
        prefix, _, rest = raw.partition(":")
        prefix = prefix.strip().lower()
        if prefix in {"user", "group"}:
            return rest.strip(), prefix
    return raw, "user"


def _zalo_platform() -> Platform:
    """Return Hermes' dynamic Zalo platform member.

    Hermes normally registers the platform before constructing the adapter.
    This fallback mirrors Hermes 0.19's dynamic enum creation so direct imports
    used by tests and health probes remain usable too.
    """
    try:
        return Platform("zalo")
    except ValueError:
        pseudo = object.__new__(Platform)
        pseudo._value_ = "zalo"
        pseudo._name_ = "ZALO"
        Platform._value2member_map_["zalo"] = pseudo
        Platform._member_map_["ZALO"] = pseudo
        return pseudo


def _provider_timestamp(value: Any) -> str:
    """Normalize zca-js milliseconds/seconds/ISO timestamps to UTC ISO-8601."""
    if value in (None, ""):
        return datetime.now(timezone.utc).isoformat()
    raw = str(value).strip()
    try:
        numeric = float(raw)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(timezone.utc).isoformat()
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    if numeric > 100_000_000_000:
        numeric /= 1000
    return datetime.fromtimestamp(numeric, tz=timezone.utc).isoformat()


def _event_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _quote_text(value: Any) -> Optional[str]:
    """Extract a string quote for Hermes' ``MessageEvent.reply_to_text``.

    zca-js can return rich quote content as an object (for example
    ``{"msg": "...", "style": {...}}``), while Hermes slices this field as
    text. Normalize it at the adapter boundary so a reply can never crash the
    gateway with ``TypeError: unhashable type: 'slice'``.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("msg", "text", "content", "description"):
            if key in value:
                extracted = _quote_text(value.get(key))
                if extracted:
                    return extracted
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return str(value)
    if isinstance(value, (list, tuple)):
        parts = [_quote_text(item) for item in value]
        joined = " ".join(part for part in parts if part)
        return joined or None
    return str(value)


_FRIEND_SINGLE_COMMANDS = frozenset(
    {
        "ket ban nguoi nay",
        "ket ban voi nguoi nay",
        "gui loi moi ket ban",
        "add nguoi nay",
    }
)
_FRIEND_MULTIPLE_COMMANDS = frozenset(
    {
        "ket ban nhung nguoi nay",
        "ket ban tat ca",
        "gui loi moi ket ban cho nhung nguoi nay",
    }
)


def _normalized_command_text(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(character for character in text if unicodedata.category(character) != "Mn")
    text = re.sub(r"[^a-zA-Z0-9]+", " ", text).strip().lower()
    words = text.split()
    while words and words[0] in {"hay", "vui", "long", "giup"}:
        words.pop(0)
        if words and words[0] == "long":
            words.pop(0)
    return " ".join(words)


def _friend_request_command(text: str) -> str | None:
    normalized = _normalized_command_text(text)
    if normalized in _FRIEND_SINGLE_COMMANDS:
        return "single"
    if normalized in _FRIEND_MULTIPLE_COMMANDS:
        return "multiple"
    return None


def _contact_payload(message: Mapping[str, Any]) -> dict[str, str] | None:
    """Extract a normalized contact card without guessing an ID from text."""
    msg_type = str(message.get("msgType") or "")
    candidates: list[Mapping[str, Any]] = []
    for key in ("attachment", "media"):
        value = message.get(key)
        if isinstance(value, Mapping):
            candidates.append(value)
    listed = message.get("attachments")
    if isinstance(listed, list):
        candidates.extend(item for item in listed if isinstance(item, Mapping))

    for candidate in candidates:
        contact = candidate.get("contact")
        if not isinstance(contact, Mapping):
            if msg_type == "chat.recommended" and any(
                key in candidate for key in ("gUid", "uid", "userId")
            ):
                contact = candidate
            else:
                continue
        return {
            "name": str(contact.get("name") or contact.get("title") or candidate.get("title") or ""),
            "phone": str(contact.get("phone") or contact.get("phoneNumber") or ""),
            "gUid": str(
                contact.get("gUid")
                or contact.get("uid")
                or contact.get("userId")
                or ""
            ),
        }
    return None


def _friend_request_bucket(response: Mapping[str, Any]) -> str:
    if str(response.get("outcome") or "").casefold() == "unknown":
        return "unknown"
    if not response.get("error"):
        return "success"
    error = str(response.get("error") or "").casefold()
    if re.search(r"(?:^|\D)(?:222|225)(?:\D|$)", error):
        return "existing"
    return "failed"


def _explicit_provider_message_id(response: Any) -> Optional[str]:
    """Extract a provider-confirmed message id without inventing a fallback."""
    if not isinstance(response, dict):
        return None
    candidates = [response]
    result = response.get("result")
    if isinstance(result, dict):
        candidates.append(result)
        message = result.get("message")
        if isinstance(message, dict):
            candidates.append(message)
    for candidate in reversed(candidates):
        for key in ("msgId", "messageId"):
            value = candidate.get(key)
            if value not in (None, ""):
                return str(value)
    return None


class ZaloAdapter(BasePlatformAdapter):
    """Zalo adapter that talks to a zca-js bridge over HTTP/SSE."""

    def __init__(self, config, **kwargs):
        global _ACTIVE_ADAPTER
        platform = _zalo_platform()
        super().__init__(config=config, platform=platform)

        extra = getattr(config, "extra", {}) or {}
        if not isinstance(extra, dict):
            extra = dict(extra)
            config.extra = extra
        # Hermes 0.19 reads this key when constructing the session key. Company
        # groups deliberately share one agent session across all members.
        extra["group_sessions_per_user"] = False

        supplied_company_config = kwargs.pop("company_config", None)
        self.company_config = supplied_company_config or CompanyConfig.from_platform_extra(
            extra
        )
        if not isinstance(self.company_config, CompanyConfig):
            raise TypeError("company_config must be a CompanyConfig")
        hermes_home = Path(os.getenv("HERMES_HOME") or (Path.home() / ".hermes"))
        configured_provider, configured_model = _configured_model_labels(hermes_home)
        self._provider_name = _status_label(
            kwargs.pop("provider_name", None)
            or extra.get("provider")
            or getattr(config, "provider", None)
            or os.getenv("HERMES_PROVIDER")
            or os.getenv("HERMES_PROVIDER_NAME")
            or configured_provider
        )
        self._model_name = _status_label(
            kwargs.pop("model_name", None)
            or extra.get("model")
            or getattr(config, "model", None)
            or os.getenv("HERMES_MODEL")
            or os.getenv("HERMES_MODEL_NAME")
            or configured_model
        )

        self.bridge_url = self.company_config.bridge_url
        self.bridge_token = self.company_config.bridge_token
        self.allowed_users = sorted(self.company_config.allowed_users)
        self._allowed_users = set(self.company_config.allowed_users)
        self.allowed_threads = sorted(self.company_config.allowed_groups)
        self._allowed_threads = set(self.company_config.allowed_groups)
        self.group_mode = self.company_config.group_mode
        self._own_id: Optional[str] = None
        self._own_name: Optional[str] = None
        self._bridge_available = False
        self._zalo_logged_in = False
        self._last_bridge_error: Optional[str] = None
        self._monotonic_clock = kwargs.pop("monotonic_clock", time.monotonic)
        if not callable(self._monotonic_clock):
            raise TypeError("monotonic_clock must be callable")

        history_store = kwargs.pop("history_store", None)
        if history_store is None:
            db_path = Path(
                os.getenv("ZALO_DB_PATH")
                or extra.get("history_db_path")
                or hermes_home
                / "zalo-company"
                / "history"
                / "conversations.sqlite3"
            )
            history_store = HistoryStore(
                db_path,
                account_id=os.getenv("ZALO_ACCOUNT_ID") or "company-zalo",
            )
        if not isinstance(history_store, HistoryStore):
            raise TypeError("history_store must be a HistoryStore")
        self.history_store = history_store

        self.follow_ups = FollowUpService(
            store=self.history_store,
            allowed_users=lambda: set(self._allowed_users),
            send_dm=self._send_follow_up_dm,
        )

        media_policy = kwargs.pop("media_policy", None)
        if media_policy is None:
            media_policy = MediaPolicy(
                self.history_store.db_path.parent,
                max_bytes=self.company_config.media_max_bytes,
            )
        if not isinstance(media_policy, MediaPolicy):
            raise TypeError("media_policy must be a MediaPolicy")
        self.media_policy = media_policy

        export_root = hermes_home / "zalo-company" / "exports"
        bridge = _AdapterBridge(self)
        self.admin_service = kwargs.pop("admin_service", None) or AdminService(
            config_file=CompanyConfigFile(hermes_home / "config.yaml"),
            store=self.history_store,
            memory_path=hermes_home / "memories" / "MEMORY.md",
            status_provider=self._admin_status,
            lifecycle={
                "login_qr": self._admin_login_qr,
                "reconnect": self._admin_reconnect,
                "start": lambda args=None: self._admin_service_action("start", args),
                "stop": lambda args=None: self._admin_service_action("stop", args),
                "restart": lambda args=None: self._admin_service_action("restart", args),
            },
            log_path=Path(
                os.getenv("HERMES_GATEWAY_LOG")
                or hermes_home / "logs" / "gateway.log"
            ),
            log_provider=self._admin_show_logs,
            runtime_config_provider=lambda: self.company_config,
            runtime_config_applier=self._apply_company_config,
            export_root=export_root,
            follow_up_service=self.follow_ups,
        )
        if self.admin_service.runtime_config_provider is None:
            self.admin_service.runtime_config_provider = lambda: self.company_config
        if self.admin_service.runtime_config_applier is None:
            self.admin_service.runtime_config_applier = self._apply_company_config
        if self.admin_service.export_root is None:
            self.admin_service.export_root = export_root
        if getattr(self.admin_service, "follow_up_service", None) is None:
            self.admin_service.follow_up_service = self.follow_ups
        self.tooling = ZaloTooling(
            bridge=bridge,
            store=self.history_store,
            config=self.company_config,
            admin=self.admin_service,
            on_config_change=self._apply_company_config,
        )
        try:
            admin_web_settings = AdminWebSettings.from_env()
        except AdminWebSettingsError as exc:
            logger.error(
                "Zalo admin Web UI disabled: %s",
                redact_text(str(exc)) or "invalid settings",
            )
            admin_web_settings = AdminWebSettings(enabled=False)
        self.admin_web = kwargs.pop("admin_web_app", None) or AdminWebApp(
            settings=admin_web_settings,
            admin=self.admin_service,
            store=self.history_store,
            bridge=bridge,
            export_root=export_root,
        )
        _ACTIVE_ADAPTER = self

        # Log inbound uid/threadId to help operators discover ids for allowlists.
        self.log_ids = _truthy(os.getenv("ZALO_LOG_IDS")) if os.getenv("ZALO_LOG_IDS") else bool(extra.get("log_ids", False))

        max_msg = extra.get("max_message_length")
        self.max_message_length = int(max_msg or 4000)

        # Remember the thread type per chat_id from inbound messages so replies
        # route correctly (user vs group). Zalo thread IDs don't encode type.
        self._thread_types: Dict[str, str] = {}
        self._unauthorized_dm_notice_times: Dict[str, float] = {}
        self._unauthorized_dm_notice_cooldown = 3600.0
        self._unauthorized_dm_notice_limit = 1024
        self._policy: Optional[Dict[str, Any]] = None

        self._session = None  # aiohttp.ClientSession
        self._sse_task: Optional[asyncio.Task] = None
        self._follow_up_task: Optional[asyncio.Task] = None
        self._stop = False
        self._last_event_id: Optional[str] = None

    def _apply_company_config(self, config: CompanyConfig) -> None:
        self.company_config = config
        self.bridge_url = config.bridge_url
        self.bridge_token = config.bridge_token
        self.allowed_users = sorted(config.allowed_users)
        self._allowed_users = set(config.allowed_users)
        self.allowed_threads = sorted(config.allowed_groups)
        self._allowed_threads = set(config.allowed_groups)
        self.group_mode = config.group_mode
        tooling = getattr(self, "tooling", None)
        if tooling is not None:
            tooling.config = config

    def _admin_status(self) -> Dict[str, Any]:
        return {
            "success": True,
            "bridge_url": self.bridge_url,
            "connected": bool(self._bridge_available and self._zalo_logged_in),
            "adapter_active": bool(self.is_connected),
            "bot": {
                "id": self._own_id,
                "name": self._own_name,
            },
            "bridge_error": self._last_bridge_error,
            "gateway": {"status": "Đang chạy"},
            "sse_clients": int(
                self._sse_task is not None and not self._sse_task.done()
            ),
            "history": self.history_store.stats(),
            "provider": self._provider_name,
            "model": self._model_name,
        }

    async def _admin_login_qr(self, _args=None) -> Dict[str, Any]:
        return await self._post("/relogin", {"forceQR": True})

    async def _admin_reconnect(self, _args=None) -> Dict[str, Any]:
        return await self._post("/relogin", {"forceQR": False})

    async def _admin_service_action(
        self,
        action: str,
        args: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        units = {
            "bridge": os.getenv(
                "ZALO_BRIDGE_SYSTEMD_UNIT",
                "hermes-zalo-company-bridge.service",
            ),
            "gateway": os.getenv(
                "HERMES_GATEWAY_SYSTEMD_UNIT",
                "hermes-gateway.service",
            ),
        }
        target = str((args or {}).get("target") or "bridge")
        if target not in units:
            return {
                "success": False,
                "error": "invalid service target",
                "target": target,
            }
        unit = units[target]
        try:
            process = await asyncio.create_subprocess_exec(
                "systemctl",
                action,
                unit,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            return_code = await asyncio.wait_for(process.wait(), timeout=30)
        except Exception as exc:
            return {
                "success": False,
                "action": action,
                "unit": unit,
                "target": target,
                "error": redact_text(str(exc)) or "service action failed",
            }
        return {
            "success": return_code == 0,
            "action": action,
            "unit": unit,
            "target": target,
            "return_code": return_code,
        }

    async def _admin_show_logs(self, lines: int = 100) -> Dict[str, Any]:
        unit = os.getenv(
            "ZALO_BRIDGE_SYSTEMD_UNIT",
            "hermes-zalo-company-bridge.service",
        )
        try:
            process = await asyncio.create_subprocess_exec(
                "journalctl",
                "--unit",
                unit,
                "--no-pager",
                "--lines",
                str(max(1, min(int(lines), 500))),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=30)
            return {
                "success": process.returncode == 0,
                "unit": unit,
                "lines": stdout.decode("utf-8", errors="replace").splitlines(),
            }
        except Exception as exc:
            return {"success": False, "unit": unit, "error": str(exc)}

    @property
    def name(self) -> str:
        return "Zalo"

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.bridge_token:
            h["Authorization"] = f"Bearer {self.bridge_token}"
            # Kept during the 1.0.9 bridge migration.
            h["x-bridge-token"] = self.bridge_token
        return h

    async def _start_admin_web(self) -> bool:
        web_app = getattr(self, "admin_web", None)
        if web_app is None or bool(getattr(web_app, "is_running", False)):
            return bool(web_app and getattr(web_app, "is_running", False))
        try:
            await web_app.start()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(
                "Zalo admin Web UI failed to start: %s",
                redact_text(str(exc)) or "unknown error",
            )
            return False
        return bool(getattr(web_app, "is_running", False))

    async def _stop_admin_web(self) -> None:
        web_app = getattr(self, "admin_web", None)
        if web_app is None:
            return
        try:
            await web_app.stop()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "Zalo admin Web UI cleanup failed: %s",
                redact_text(str(exc)) or "unknown error",
            )

    def _ensure_sse_task(self) -> None:
        if self._sse_task is None or self._sse_task.done():
            self._sse_task = asyncio.create_task(self._sse_loop())

    def _ensure_follow_up_task(self) -> None:
        if self._follow_up_task is None or self._follow_up_task.done():
            self._follow_up_task = asyncio.create_task(self._follow_up_loop())

    async def _follow_up_loop(self) -> None:
        while not self._stop:
            if self._bridge_available and self._zalo_logged_in:
                try:
                    await self.follow_ups.tick()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.error(
                        "Zalo: follow-up ticker failed: %s",
                        redact_text(str(exc)) or "unknown error",
                    )
            await asyncio.sleep(5)

    # ── Connection lifecycle ──────────────────────────────────────────────

    def _apply_history_retention(
        self,
        *,
        now: datetime | None = None,
    ) -> dict[str, int]:
        days = self.company_config.history_retention_days
        if days is None:
            return {"messages": 0, "attachments": 0, "media_deleted": 0}
        cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=days)
        return self.history_store.purge_before(cutoff.isoformat())

    async def connect(self, *, is_reconnect: bool = False) -> bool:
        admin_web_running = await self._start_admin_web()
        try:
            self.company_config.require_runtime_secrets()
        except CompanyConfigError as exc:
            self._set_fatal_error("config_missing", str(exc), retryable=False)
            return False
        if not self.bridge_url:
            self._set_fatal_error("config_missing", "ZALO_PLUGIN_URL must be set", retryable=False)
            return False
        try:
            import aiohttp  # noqa
        except ImportError:
            self._set_fatal_error(
                "dependency_missing",
                "aiohttp is required for the Zalo adapter (pip install aiohttp)",
                retryable=False,
            )
            return False

        import aiohttp

        self._stop = False
        if self._session is not None and not self._session.closed:
            await self._close_session()
        purged = self._apply_history_retention()
        if purged.get("messages"):
            logger.info(
                "Zalo: retention purged %s messages and %s media files",
                purged.get("messages", 0),
                purged.get("media_deleted", 0),
            )
        self._session = aiohttp.ClientSession()

        # Probe bridge health and login state.
        try:
            async with self._session.get(
                f"{self.bridge_url}/health",
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json()
        except Exception as e:
            message = redact_text(str(e)) or "bridge unavailable"
            self._bridge_available = False
            self._zalo_logged_in = False
            self._last_bridge_error = message
            logger.error("Zalo: cannot reach bridge at %s — %s", self.bridge_url, message)
            self._set_fatal_error(
                "bridge_unreachable",
                f"Bridge unreachable: {message}",
                retryable=True,
            )
            if admin_web_running:
                self._ensure_sse_task()
                return True
            await self._close_session()
            return False

        self._bridge_available = True
        self._zalo_logged_in = bool(data.get("loggedIn"))
        self._last_bridge_error = None
        self._own_id = str(data.get("ownId") or "") or None
        if not data.get("loggedIn"):
            qr = data.get("qr")
            msg = (
                "Zalo plugin is running but not logged in. "
                f"Scan the QR (bridge state: {qr}). See {self.bridge_url}/qr.png"
            )
            logger.error("Zalo: %s", msg)
            self._set_fatal_error("not_logged_in", msg, retryable=True)
            if admin_web_running:
                self._ensure_sse_task()
                return True
            await self._close_session()
            return False

        # Fetch + log the active action policy (transparency; helps the agent
        # understand what it can/can't do without hitting 403 blindly).
        try:
            async with self._session.get(
                f"{self.bridge_url}/policy",
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as presp:
                policy = await presp.json()
            self._policy = policy
            logger.info(
                "Zalo: action policy groups=%s destructive=%s allowed=%s/%s",
                policy.get("groups"),
                policy.get("allowDestructive"),
                policy.get("allowedActionCount"),
                policy.get("totalActions"),
            )
        except Exception as e:
            self._policy = None
            logger.warning(
                "Zalo: could not fetch action policy: %s",
                redact_text(str(e)) or "unknown error",
            )

        # Start the SSE inbound loop.
        self._ensure_sse_task()
        self._ensure_follow_up_task()
        self._mark_connected()
        logger.info("Zalo: connected to bridge %s (ownId=%s)", self.bridge_url, self._own_id)
        return True

    async def disconnect(self) -> None:
        self._stop = True
        self._mark_disconnected()
        if self._sse_task and not self._sse_task.done():
            self._sse_task.cancel()
            try:
                await self._sse_task
            except asyncio.CancelledError:
                pass
        self._sse_task = None
        if self._follow_up_task and not self._follow_up_task.done():
            self._follow_up_task.cancel()
            try:
                await self._follow_up_task
            except asyncio.CancelledError:
                pass
        self._follow_up_task = None
        await self._stop_admin_web()
        await self._close_session()

    async def _close_session(self) -> None:
        if self._session and not self._session.closed:
            try:
                await self._session.close()
            except Exception:
                pass
        self._session = None

    # ── Inbound: SSE loop ─────────────────────────────────────────────────

    async def _sse_loop(self) -> None:
        """Consume the bridge SSE stream with reconnect + backoff."""
        import aiohttp

        backoff = 1.0
        while not self._stop:
            try:
                headers = self._headers()
                if self._last_event_id is not None:
                    headers["Last-Event-ID"] = self._last_event_id

                timeout = aiohttp.ClientTimeout(total=None, sock_read=None)
                async with self._session.get(
                    f"{self.bridge_url}/events", headers=headers, timeout=timeout
                ) as resp:
                    if resp.status != 200:
                        raise RuntimeError(f"SSE status {resp.status}")
                    backoff = 1.0  # reset after a successful connect
                    await self._consume_sse(resp)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if self._stop:
                    break
                logger.warning(
                    "Zalo: SSE disconnected (%s); reconnecting in %.1fs",
                    redact_text(str(e)) or "unknown error",
                    backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    async def _consume_sse(self, resp) -> None:
        event_type = "message"
        data_lines: List[str] = []
        event_id: Optional[str] = None

        async for raw_line in resp.content:
            if self._stop:
                return
            line = raw_line.decode("utf-8", errors="replace").rstrip("\n").rstrip("\r")

            if line == "":
                # Dispatch the accumulated event.
                if data_lines:
                    payload = "\n".join(data_lines)
                    await self._handle_sse_event(event_type, payload)
                    if event_id is not None:
                        self._last_event_id = event_id
                event_type = "message"
                data_lines = []
                event_id = None
                continue

            if line.startswith(":"):
                continue  # heartbeat / comment
            if line.startswith("event:"):
                event_type = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:"):].lstrip())
            elif line.startswith("id:"):
                event_id = line[len("id:"):].strip()
            elif line.startswith("retry:"):
                pass

    async def _handle_sse_event(self, event_type: str, payload: str) -> None:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return

        if event_type == "status":
            logger.info(
                "Zalo: bridge status state=%s loggedIn=%s sessionDead=%s",
                data.get("status") or data.get("state") or "unknown",
                bool(data.get("loggedIn")),
                bool(data.get("sessionDead")),
            )
            self._bridge_available = True
            logged_in = bool(data.get("loggedIn")) or str(
                data.get("status") or data.get("state") or ""
            ).lower() in {"connected", "authenticated", "logged_in"}
            self._zalo_logged_in = logged_in
            if logged_in:
                self._last_bridge_error = None
                own_id = str(data.get("ownId") or "")
                if own_id:
                    self._own_id = own_id
                self._ensure_follow_up_task()
                self._mark_connected()
            return
        if event_type == "session_dead":
            await self._on_session_dead(data)
            return
        if event_type == "message":
            await self._on_inbound_message(data)
            return
        # Reaction / undo / friend / group events: surface as a synthetic
        # context line for the agent (no media). These don't trigger a turn by
        # default unless a handler wants them; we log + optionally dispatch.
        if event_type in ("reaction", "undo", "friend_event", "group_event"):
            if event_type in {"reaction", "undo"}:
                self._store_message_event(event_type, data)
            logger.info(
                "Zalo: %s event id=%s thread=%s actor=%s",
                event_type,
                data.get("eventId") or data.get("event_id") or "unknown",
                data.get("threadId") or "unknown",
                data.get("senderId") or data.get("actorId") or "unknown",
            )
            return

    def _store_message_event(self, event_type: str, data: Dict[str, Any]) -> None:
        thread_type = "group" if data.get("threadType") == "group" else "dm"
        thread_id = str(data.get("threadId") or "")
        actor_id = str(data.get("senderId") or data.get("actorId") or "")
        if thread_type == "group":
            if thread_id not in self.company_config.allowed_groups:
                return
        elif actor_id not in self.company_config.allowed_users and thread_id not in self.company_config.allowed_users:
            return
        canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)
        event_key = str(data.get("eventId") or data.get("event_id") or "")
        if not event_key:
            event_key = hashlib.sha256(
                f"{event_type}|{thread_type}|{thread_id}|{canonical}".encode("utf-8")
            ).hexdigest()
        try:
            self.history_store.record_event(
                event_key=event_key,
                event_type=event_type,
                provider_message_id=str(data.get("msgId") or data.get("messageId") or ""),
                thread_type=thread_type,
                thread_id=thread_id,
                actor_id=actor_id,
                actor_name=str(data.get("senderName") or data.get("actorName") or ""),
                occurred_at=_provider_timestamp(
                    data.get("occurredAt") or data.get("timestamp") or data.get("ts")
                ),
                payload=data,
            )
        except Exception as exc:
            logger.error(
                "Zalo: failed to store %s event: %s",
                event_type,
                redact_text(str(exc)) or "unknown error",
            )

    async def _on_session_dead(self, data: Dict[str, Any]) -> None:
        """Zalo session ended (logout / kicked / cookie expired)."""
        msg = (
            redact_text(str((data or {}).get("message") or "Zalo session ended."))
            or "Zalo session ended."
        )
        code = (data or {}).get("code")
        logger.error("Zalo: SESSION DEAD (code=%s): %s", code, msg)
        # Mark fatal so `hermes gateway status` shows Zalo as down and the
        # gateway can surface/heal it.
        self._set_fatal_error(
            "session_dead",
            f"{msg} Re-scan the QR (POST {self.bridge_url}/relogin then open "
            f"{self.bridge_url}/qr.png) to recover.",
            retryable=True,
        )
        self._zalo_logged_in = False
        self._last_bridge_error = msg
        admin_web_running = bool(
            getattr(getattr(self, "admin_web", None), "is_running", False)
        )
        if not admin_web_running:
            try:
                await self._notify_fatal_error()
            except Exception:
                pass
        # Best-effort: notify the operator in their home channel if known.
        home = os.getenv("ZALO_HOME_CHANNEL")
        if home and self._message_handler:
            chat_id, ttype = _parse_home_channel(home)
            if chat_id:
                try:
                    src = self.build_source(
                        chat_id=chat_id,
                        chat_name=chat_id,
                        chat_type="group" if ttype == "group" else "dm",
                        user_id=self._own_id or "system",
                        user_name="Zalo",
                    )
                    ev = MessageEvent(
                        text=(
                            "⚠️ Zalo session đã hết hạn / bị đăng xuất. "
                            f"({msg}) Cần quét lại QR để khôi phục: "
                            f"POST {self.bridge_url}/relogin rồi mở {self.bridge_url}/qr.png"
                        ),
                        message_type=MessageType.TEXT,
                        source=src,
                        internal=True,
                        timestamp=datetime.now(),
                    )
                    await self.handle_message(ev)
                except Exception:
                    pass

    async def _notify_unauthorized_dm(self, sender_id: str) -> None:
        now = float(self._monotonic_clock())
        cooldown = self._unauthorized_dm_notice_cooldown
        expired = [
            user_id
            for user_id, sent_at in self._unauthorized_dm_notice_times.items()
            if now - sent_at >= cooldown
        ]
        for user_id in expired:
            self._unauthorized_dm_notice_times.pop(user_id, None)

        if sender_id in self._unauthorized_dm_notice_times:
            return
        if len(self._unauthorized_dm_notice_times) >= self._unauthorized_dm_notice_limit:
            return

        # Record before yielding so concurrent messages from one sender cannot
        # race into duplicate notices.
        self._unauthorized_dm_notice_times[sender_id] = now
        try:
            await self._post(
                "/send",
                {
                    "threadId": sender_id,
                    "threadType": "user",
                    "text": _UNAUTHORIZED_DM_NOTICE,
                },
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Zalo: failed to send unauthorized DM notice")

    async def _handle_contact_friend_request(
        self,
        *,
        stored: StoredMessage,
        requester_id: str,
        thread_type: str,
        thread_id: str,
        command_text: str,
    ) -> bool:
        command = _friend_request_command(command_text)
        if command is None:
            return False

        if thread_type == "group" and requester_id not in self.company_config.allowed_users:
            return False

        if requester_id not in self.company_config.admin_users:
            await self.send(
                str(thread_id),
                "Thao tác kết bạn bằng danh thiếp cần quản trị viên thực hiện.",
                metadata={"thread_type": thread_type},
            )
            return True

        cards = self.history_store.contact_cards_before(
            message_id=stored.message_id,
            thread_type=thread_type,
            thread_id=thread_id,
            multiple=command == "multiple",
        )
        if not cards:
            await self.send(
                str(thread_id),
                "Không tìm thấy danh thiếp phù hợp. Vui lòng gửi lại danh thiếp rồi ra lệnh kết bạn.",
                metadata={"thread_type": thread_type},
            )
            return True

        results: list[tuple[dict[str, Any], str]] = []
        for card in cards:
            g_uid = str(card.get("gUid") or "").strip()
            if not g_uid:
                results.append((card, "missing"))
                continue
            response = await self.friend_request(
                g_uid,
                msg="Xin chào, tôi là trợ lý công ty.",
            )
            results.append((card, _friend_request_bucket(response)))

        labels = {
            "success": "thành công",
            "existing": "đã là bạn hoặc đã có lời mời",
            "unknown": "không rõ kết quả",
            "missing": "thiếu Zalo ID",
            "failed": "thất bại",
        }
        lines = ["Kết quả kết bạn:"]
        for card, status in results:
            name = str(card.get("name") or card.get("gUid") or "(không tên)")
            lines.append(f"- {name}: {labels[status]}")
        await self.send(
            str(thread_id),
            "\n".join(lines),
            metadata={"thread_type": thread_type},
        )
        return True

    async def _on_inbound_message(self, m: Dict[str, Any]) -> None:
        if m.get("isSelf"):
            return

        thread_id = str(m.get("threadId") or "")
        provider_thread_type = m.get("threadType") or "user"
        sender_id = str(m.get("senderId") or "")
        sender_name = str(m.get("senderName") or "")
        original_text = str(m.get("text") or "")
        chat_type = "group" if provider_thread_type == "group" else "dm"

        if not thread_id or not sender_id:
            logger.warning("Zalo: inbound message is missing threadId or senderId")
            return
        if chat_type == "dm" and sender_id not in self.company_config.allowed_users:
            logger.debug("Zalo: notifying non-allowed DM sender %s", sender_id)
            await self._notify_unauthorized_dm(sender_id)
            return

        conversation_id = thread_id if chat_type == "group" else sender_id
        self._thread_types[conversation_id] = (
            "group" if chat_type == "group" else "user"
        )

        if self.log_ids:
            logger.info(
                "Zalo inbound: uid=%s name=%r threadId=%s type=%s",
                sender_id,
                sender_name,
                conversation_id,
                chat_type,
            )

        if chat_type == "group":
            if conversation_id not in self.company_config.allowed_groups:
                logger.debug(
                    "Zalo: ignoring message in non-allowed group %s",
                    conversation_id,
                )
                return
            addressed_text = self._is_addressed(m, original_text)
        else:
            addressed_text = original_text

        attachments = self._normalized_attachments(m)
        sent_at = _provider_timestamp(
            m.get("sentAt") or m.get("timestamp") or m.get("ts")
        )
        provider_message_id = str(m.get("messageId") or "")
        provider_cli_message_id = str(m.get("cliMsgId") or "")
        quote = m.get("quote") if isinstance(m.get("quote"), dict) else None
        reply_to_provider_message_id = str(
            m.get("replyToMessageId") or (quote or {}).get("msgId") or ""
        )

        contact = _contact_payload(m)
        extra = {
            "msg_type": str(m.get("msgType") or ""),
            "attachments": [
                {
                    key: attachment.get(key)
                    for key in (
                        "kind",
                        "filename",
                        "mime_type",
                        "size_bytes",
                        "download_status",
                    )
                }
                for attachment in attachments
            ],
        }
        if contact is not None:
            extra["contact"] = contact

        try:
            stored = self.history_store.store_message(
                thread_type=chat_type,
                thread_id=conversation_id,
                sender_id=sender_id,
                sender_name=sender_name,
                title=(
                    str(m.get("threadName") or conversation_id)
                    if chat_type == "group"
                    else str(sender_name or sender_id)
                ),
                text=original_text,
                provider_message_id=provider_message_id,
                provider_cli_message_id=provider_cli_message_id,
                event_id=str(m.get("eventId") or m.get("event_id") or ""),
                mentioned_bot=addressed_text is not None,
                reply_to_provider_message_id=reply_to_provider_message_id,
                quote=quote,
                sent_at=sent_at,
                attachments=attachments,
                extra=extra,
            )
        except Exception as exc:
            logger.error(
                "Zalo: failed to store inbound message: %s",
                redact_text(str(exc)) or "unknown error",
            )
            return

        if not stored.inserted:
            return

        if chat_type == "dm":
            try:
                self.follow_ups.record_inbound_response(
                    stored_message_id=stored.message_id,
                    sender_id=sender_id,
                    thread_type="dm",
                    thread_id=conversation_id,
                    sent_at=sent_at,
                    text=original_text,
                )
            except Exception as exc:
                logger.error(
                    "Zalo: failed to match follow-up response: %s",
                    redact_text(str(exc)) or "unknown error",
                )

        media_urls, media_types, message_type = await self._persist_attachments(
            stored=stored,
            attachments=attachments,
            thread_type=chat_type,
            thread_id=conversation_id,
            sent_at=sent_at,
        )

        command_text = addressed_text if chat_type == "group" else original_text
        if command_text is not None and await self._handle_contact_friend_request(
            stored=stored,
            requester_id=sender_id,
            thread_type=chat_type,
            thread_id=conversation_id,
            command_text=command_text,
        ):
            return

        if chat_type == "group":
            # Store every allowed-group event before sender and mention gates.
            if sender_id not in self.company_config.allowed_users:
                return
            if addressed_text is None:
                return
        if not self._message_handler:
            return

        source = self.build_source(
            chat_id=conversation_id,
            chat_name=(
                sender_name
                if chat_type == "dm"
                else str(m.get("threadName") or conversation_id)
            ),
            chat_type=chat_type,
            user_id=sender_id,
            user_name=sender_name,
            message_id=provider_message_id or provider_cli_message_id or None,
        )
        session_key = build_session_key(source, group_sessions_per_user=False)
        requester = Requester(
            requester_id=sender_id,
            thread_type=chat_type,
            thread_id=conversation_id,
            is_admin=sender_id in self.company_config.admin_users,
            session_key=session_key,
        )

        event = MessageEvent(
            text=addressed_text if chat_type == "group" else original_text,
            message_type=message_type,
            source=source,
            message_id=provider_message_id or provider_cli_message_id,
            raw_message=m,
            media_urls=media_urls,
            media_types=media_types,
            reply_to_message_id=reply_to_provider_message_id or None,
            reply_to_text=_quote_text((quote or {}).get("content")),
            channel_context=self._history_context(
                thread_type=chat_type,
                thread_id=conversation_id,
                current_message_id=stored.message_id,
            ),
            metadata={
                "requester_id": sender_id,
                "requester_is_admin": requester.is_admin,
                "session_key": session_key,
                "thread_type": chat_type,
                "stored_message_id": stored.message_id,
            },
            timestamp=_event_datetime(sent_at),
        )
        with bind_requester(requester):
            await self.handle_message(event)

    @staticmethod
    def _normalized_attachments(m: Dict[str, Any]) -> List[Dict[str, Any]]:
        raw_attachments: List[Dict[str, Any]] = []
        listed = m.get("attachments")
        if isinstance(listed, list):
            raw_attachments.extend(item for item in listed if isinstance(item, dict))
        media = m.get("media")
        if isinstance(media, dict):
            raw_attachments.append(media)
        elif not raw_attachments and isinstance(m.get("attachment"), dict):
            raw_attachments.append(m["attachment"])

        normalized: List[Dict[str, Any]] = []
        for index, attachment in enumerate(raw_attachments):
            remote_url = str(
                attachment.get("remote_url")
                or attachment.get("url")
                or attachment.get("href")
                or ""
            )
            raw_size = attachment.get("size_bytes")
            if raw_size is None:
                raw_size = attachment.get("size")
            try:
                size_bytes = int(raw_size) if int(raw_size or 0) > 0 else None
            except (TypeError, ValueError):
                size_bytes = None
            normalized.append(
                {
                    "attachment_index": int(
                        attachment.get("attachment_index", index)
                    ),
                    "kind": str(
                        attachment.get("kind")
                        or attachment.get("type")
                        or "other"
                    ),
                    "filename": str(
                        attachment.get("filename")
                        or attachment.get("fileName")
                        or attachment.get("title")
                        or f"attachment-{index}"
                    ),
                    "mime_type": str(
                        attachment.get("mime_type")
                        or attachment.get("mime")
                        or "application/octet-stream"
                    ),
                    "size_bytes": size_bytes,
                    "remote_url": remote_url or None,
                    "download_status": "pending" if remote_url else "metadata_only",
                }
            )
        return normalized

    async def _media_chunks(self, url: str):
        import aiohttp

        if not self._session or self._session.closed:
            raise RuntimeError("Zalo media session is not connected")
        async with self._session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=120),
        ) as response:
            if response.status != 200:
                raise RuntimeError(f"media download failed with HTTP {response.status}")
            async for chunk in response.content.iter_chunked(64 * 1024):
                yield chunk

    async def _persist_attachments(
        self,
        *,
        stored: StoredMessage,
        attachments: List[Dict[str, Any]],
        thread_type: str,
        thread_id: str,
        sent_at: str,
    ) -> tuple[List[str], List[str], MessageType]:
        media_urls: List[str] = []
        media_types: List[str] = []
        message_type = MessageType.TEXT
        type_map = {
            "image": MessageType.PHOTO,
            "voice": MessageType.VOICE,
            "video": MessageType.VIDEO,
            "file": MessageType.DOCUMENT,
        }
        for attachment_id, attachment in zip(stored.attachment_ids, attachments):
            if attachment["download_status"] != "pending":
                continue
            result = await self.media_policy.store_attachment(
                store=self.history_store,
                attachment_id=attachment_id,
                attachment=attachment,
                thread_type=thread_type,
                thread_id=thread_id,
                sent_at=sent_at,
                chunks=self._media_chunks(str(attachment["remote_url"])),
            )
            if result.status == "downloaded" and result.local_path:
                media_urls.append(result.local_path)
                media_types.append(str(attachment.get("mime_type") or ""))
                if message_type == MessageType.TEXT:
                    message_type = type_map.get(
                        str(attachment.get("kind") or "").lower(),
                        MessageType.DOCUMENT,
                    )
        return media_urls, media_types, message_type

    def _history_context(
        self,
        *,
        thread_type: str,
        thread_id: str,
        current_message_id: int,
    ) -> Optional[str]:
        cap = self.company_config.history_context_messages
        if cap <= 1:
            return None
        rows = self.history_store.recent_messages(
            thread_type,
            thread_id,
            limit=cap,
        )
        rows = [row for row in rows if int(row["id"]) != current_message_id]
        rows = rows[-(cap - 1) :]
        lines = []
        for row in rows:
            extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
            lines.append(
                json.dumps(
                    {
                        "sent_at": row.get("sent_at"),
                        "sender_id": row.get("sender_id"),
                        "sender_name": row.get("sender_name"),
                        "text": row.get("text"),
                        "reply_to_message_id": row.get("reply_to_message_id"),
                        "mentioned_bot": bool(row.get("mentioned_bot")),
                        "attachments": extra.get("attachments", []),
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
        return "\n".join(lines) or None

    async def _on_inbound_message_legacy(self, m: Dict[str, Any]) -> None:
        """Compatibility alias retained for callers of the old private hook."""
        await self._on_inbound_message(m)
        # ── Access control (Telegram-style) ──────────────────────────────────

    async def _download_media(self, media: Dict[str, Any]) -> tuple[Optional[str], "MessageType"]:
        """Download a media URL to the Hermes cache. Returns (path, MessageType)."""
        import aiohttp

        url = media.get("url")
        kind = media.get("kind") or "other"
        ext = (media.get("ext") or "bin").lstrip(".")
        file_name = media.get("fileName") or f"zalo.{ext}"
        if not url or not self._session or self._session.closed:
            return None, MessageType.TEXT
        try:
            async with self._session.get(
                url, timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                if resp.status != 200:
                    logger.warning("Zalo: media download failed (%s) for %s", resp.status, kind)
                    return None, MessageType.TEXT
                data = await resp.read()
        except Exception as e:
            message = redact_text(str(e)) or "media download failed"
            logger.warning("Zalo: media download error for %s: %s", kind, message)
            return None, MessageType.TEXT

        try:
            if kind == "image":
                return cache_image_from_bytes(data, ext="." + ext), MessageType.PHOTO
            if kind == "voice":
                return cache_audio_from_bytes(data, ext="." + ext), MessageType.VOICE
            if kind == "video":
                return cache_document_from_bytes(data, file_name), MessageType.VIDEO
            # file and anything else → document
            return cache_document_from_bytes(data, file_name), MessageType.DOCUMENT
        except Exception as e:
            logger.warning(
                "Zalo: failed to cache media (%s): %s",
                kind,
                redact_text(str(e)) or "unknown error",
            )
            return None, MessageType.TEXT

    def _is_addressed(self, m: Dict[str, Any], text: str) -> Optional[str]:
        """Return the (possibly stripped) text if the bot is addressed, else None.

        The bridge forwards real group @mentions as ``mentions[]`` UIDs. The
        bot is addressed only when its own UID is present; then a leading bot
        name is stripped from the text when possible.

        A plain text prefix such as ``Hermes`` or ``bot`` is deliberately not
        enough, and replying to an old bot message is not a substitute for the
        required @mention.
        """
        # 1) Real mention by uid.
        mentions = m.get("mentions") or []
        if self._own_id and str(self._own_id) in {str(x) for x in mentions}:
            return self._strip_leading_name(text) or text or " "

        return None

    def _strip_leading_name(self, text: str) -> Optional[str]:
        """If text starts with the bot name / a trigger, strip it and return the
        remainder; else None."""
        t = (text or "").strip()
        if not t:
            return None
        candidates = []
        if self._own_name:
            candidates.append(self._own_name)
        candidates += ["hermes", "@hermes", "bot"]
        low = t.lower()
        for c in candidates:
            cl = c.lower()
            if low.startswith(cl):
                return t[len(c):].lstrip(" :,@").strip() or t
            if low.startswith("@" + cl):
                return t[len(c) + 1:].lstrip(" :,@").strip() or t
        return None

    # ── Outbound ──────────────────────────────────────────────────────────

    def _thread_type_for(self, source_or_meta) -> str:
        """Resolve thread type ('user'|'group') from a SessionSource."""
        chat_type = getattr(source_or_meta, "chat_type", None)
        if chat_type == "group":
            return "group"
        return "user"

    async def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        import aiohttp

        if not self._session or self._session.closed:
            return {"error": "no session"}
        try:
            async with self._session.post(
                f"{self.bridge_url}{path}",
                data=json.dumps(body),
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                return await resp.json()
        except (asyncio.TimeoutError, TimeoutError) as e:
            return {
                "error": str(e) or "Zalo provider call timed out; outcome unknown",
                "outcome": "unknown",
            }
        except Exception as e:
            # Connection resets and other transport failures can happen after
            # the provider accepted a mutation. Never signal that an automatic
            # retry is safe.
            return {"error": str(e), "outcome": "unknown"}

    def _thread_type_from_chat_id(self, chat_id: str, metadata: Optional[Dict[str, Any]]) -> str:
        if metadata and metadata.get("thread_type") in {"user", "dm", "group"}:
            return "group" if metadata["thread_type"] == "group" else "user"
        # Use the type remembered from inbound messages for this chat.
        remembered = self._thread_types.get(str(chat_id))
        if remembered in {"user", "group"}:
            return remembered
        return "user"

    def _store_outbound(
        self,
        *,
        chat_id: str,
        thread_type: str,
        text: str,
        provider_message_id: str,
        reply_to: Optional[str] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        if not provider_message_id:
            return
        try:
            self.history_store.store_message(
                thread_type="group" if thread_type == "group" else "dm",
                thread_id=str(chat_id),
                sender_id=str(self._own_id or "zalo-bot"),
                sender_name=str(self._own_name or "Hermes"),
                text=str(text),
                provider_message_id=provider_message_id,
                is_bot=True,
                reply_to_provider_message_id=str(reply_to or ""),
                attachments=attachments,
            )
        except Exception as exc:
            # Delivery already happened; a history failure must be visible but
            # cannot safely turn a confirmed provider send into a retry.
            logger.error(
                "Zalo: failed to store confirmed outbound message: %s",
                redact_text(str(exc)) or "unknown error",
            )

    async def send(
        self,
        chat_id: str,
        content: str,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        thread_type = self._thread_type_from_chat_id(chat_id, metadata)
        # Split long messages.
        chunks = self.truncate_message(content, max_length=self.max_message_length)
        last = None
        last_message_id = None
        for chunk in chunks:
            if not chunk.strip():
                continue
            res = await self._post(
                "/send",
                {"threadId": chat_id, "threadType": thread_type, "text": chunk},
            )
            if res.get("error"):
                return SendResult(
                    success=False,
                    error=res["error"],
                    raw_response=res,
                    retryable=False,
                )
            last = res
            provider_message_id = _explicit_provider_message_id(res)
            if provider_message_id:
                last_message_id = provider_message_id
                self._store_outbound(
                    chat_id=str(chat_id),
                    thread_type=thread_type,
                    text=chunk,
                    provider_message_id=provider_message_id,
                    reply_to=reply_to,
                )
            await asyncio.sleep(0.2)
        return SendResult(
            success=True,
            message_id=last_message_id,
            raw_response=last,
        )

    async def _send_follow_up_dm(self, target_id: str, text: str) -> SendResult:
        return await self.send(
            str(target_id),
            str(text),
            metadata={"thread_type": "user"},
        )

    async def send_typing(self, chat_id: str, metadata=None) -> None:
        thread_type = self._thread_type_from_chat_id(chat_id, metadata)
        await self._post("/typing", {"threadId": chat_id, "threadType": thread_type})

    async def send_image(self, chat_id, image_url, caption=None, reply_to=None, metadata=None):
        return await self.send_image_file(chat_id, image_url, caption, reply_to, metadata)

    async def send_image_file(self, chat_id, image_path, caption=None, reply_to=None, metadata=None, **kwargs):
        return await self._send_local_attachment(
            chat_id,
            image_path,
            kind="image",
            caption=caption,
            reply_to=reply_to,
            metadata=metadata,
        )

    async def send_document(self, chat_id, file_path, caption=None, file_name=None, reply_to=None, metadata=None, **kwargs):
        return await self._send_local_attachment(
            chat_id,
            file_path,
            kind="file",
            caption=caption,
            reply_to=reply_to,
            metadata=metadata,
            file_name=file_name,
        )

    async def _send_local_attachment(
        self,
        chat_id,
        file_path,
        *,
        kind: str,
        caption=None,
        reply_to=None,
        metadata=None,
        file_name=None,
    ):
        thread_type = self._thread_type_from_chat_id(chat_id, metadata)
        res = await self._post(
            "/send-attachment",
            {"threadId": chat_id, "threadType": thread_type, "path": file_path, "caption": caption or ""},
        )
        if res.get("error"):
            return SendResult(success=False, error=res["error"], raw_response=res, retryable=False)
        provider_message_id = _explicit_provider_message_id(res)
        if provider_message_id:
            path = Path(str(file_path))
            try:
                size_bytes = path.stat().st_size
            except OSError:
                size_bytes = None
            self._store_outbound(
                chat_id=str(chat_id),
                thread_type=thread_type,
                text=str(caption or ""),
                provider_message_id=provider_message_id,
                reply_to=reply_to,
                attachments=[
                    {
                        "kind": kind,
                        "filename": str(file_name or path.name),
                        "size_bytes": size_bytes,
                        "local_path": str(path),
                        "download_status": "downloaded",
                    }
                ],
            )
        return SendResult(success=True, message_id=provider_message_id, raw_response=res)

    async def send_video(self, chat_id, video_path, caption=None, reply_to=None, metadata=None, **kwargs):
        return await self._send_local_attachment(
            chat_id,
            video_path,
            kind="video",
            caption=caption,
            reply_to=reply_to,
            metadata=metadata,
        )

    async def send_voice(self, chat_id, audio_path, caption=None, reply_to=None, metadata=None, **kwargs):
        thread_type = self._thread_type_from_chat_id(chat_id, metadata)
        if str(audio_path).startswith(("http://", "https://")):
            # A public m4a URL → real voice bubble via zca-js sendVoice.
            res = await self._post(
                "/send-voice",
                {"threadId": chat_id, "threadType": thread_type, "voiceUrl": audio_path},
            )
            if not res.get("error"):
                provider_message_id = _explicit_provider_message_id(res)
                if provider_message_id:
                    self._store_outbound(
                        chat_id=str(chat_id),
                        thread_type=thread_type,
                        text=str(caption or ""),
                        provider_message_id=provider_message_id,
                        reply_to=reply_to,
                        attachments=[
                            {
                                "kind": "voice",
                                "remote_url": str(audio_path),
                                "download_status": "metadata_only",
                            }
                        ],
                    )
                return SendResult(success=True, message_id=provider_message_id, raw_response=res)
        # Local audio file (or voiceUrl failed) → send as a playable file
        # attachment. zca-js sendVoice can't reliably HEAD the upload URL, so
        # we don't force a voice bubble for local files.
        res2 = await self._post(
            "/send-attachment",
            {"threadId": chat_id, "threadType": thread_type, "path": audio_path},
        )
        if res2.get("error"):
            return SendResult(success=False, error=res2["error"], raw_response=res2, retryable=False)
        provider_message_id = _explicit_provider_message_id(res2)
        if provider_message_id:
            path = Path(str(audio_path))
            try:
                size_bytes = path.stat().st_size
            except OSError:
                size_bytes = None
            self._store_outbound(
                chat_id=str(chat_id),
                thread_type=thread_type,
                text=str(caption or ""),
                provider_message_id=provider_message_id,
                reply_to=reply_to,
                attachments=[
                    {
                        "kind": "voice",
                        "filename": path.name,
                        "size_bytes": size_bytes,
                        "local_path": str(path),
                        "download_status": "downloaded",
                    }
                ],
            )
        return SendResult(success=True, message_id=provider_message_id, raw_response=res2)

    async def get_chat_info(self, chat_id: str) -> Dict[str, Any]:
        return {"name": str(chat_id), "type": "dm", "chat_id": str(chat_id)}

    # ── Extended Zalo actions (for agent tools / direct use) ────────────────

    async def react(self, chat_id, msg_id, icon="HEART", cli_msg_id=None, thread_type=None):
        """React to a message. icon = HEART/LIKE/HAHA/WOW/CRY/ANGRY/… or raw."""
        tt = thread_type or self._thread_types.get(str(chat_id), "user")
        return await self._post("/react", {
            "threadId": chat_id, "threadType": tt,
            "msgId": str(msg_id), "cliMsgId": str(cli_msg_id or msg_id), "icon": icon,
        })

    async def undo(self, chat_id, msg_id, cli_msg_id=None, thread_type=None):
        """Recall/undo one of our own messages."""
        tt = thread_type or self._thread_types.get(str(chat_id), "user")
        return await self._post("/undo", {
            "threadId": chat_id, "threadType": tt,
            "msgId": str(msg_id), "cliMsgId": str(cli_msg_id or msg_id),
        })

    async def reply(self, chat_id, text, quote, thread_type=None):
        """Send a text reply quoting a prior message (quote = SendMessageQuote)."""
        tt = thread_type or self._thread_types.get(str(chat_id), "user")
        return await self._post("/send", {
            "threadId": chat_id, "threadType": tt, "text": text, "quote": quote,
        })

    async def mention(self, chat_id, text, mentions, thread_type="group"):
        """Send a group message with @mentions = [{pos, uid, len}, …]."""
        return await self._post("/send", {
            "threadId": chat_id, "threadType": thread_type, "text": text, "mentions": mentions,
        })

    async def send_card(self, chat_id, user_id, phone_number=None, thread_type=None):
        tt = thread_type or self._thread_types.get(str(chat_id), "user")
        body = {"threadId": chat_id, "threadType": tt, "userId": str(user_id)}
        if phone_number:
            body["phoneNumber"] = str(phone_number)
        return await self._post("/send-card", body)

    # Friends
    async def friend_request(self, user_id, msg=None):
        return await self._post("/friend/request", {"userId": str(user_id), "msg": msg or "Xin chào"})

    async def friend_accept(self, user_id):
        return await self._post("/friend/accept", {"userId": str(user_id)})

    async def friend_reject(self, user_id):
        return await self._post("/friend/reject", {"userId": str(user_id)})

    async def list_friends(self):
        return await self._get("/friends")

    async def find_user(self, phone):
        return await self._get("/find-user", params={"phone": str(phone)})

    # Groups
    async def list_groups(self):
        return await self._get("/groups")

    async def group_create(self, name, members):
        return await self._post("/group/create", {"name": name, "members": [str(x) for x in members]})

    async def group_add(self, group_id, members):
        return await self._post("/group/add", {"groupId": str(group_id), "members": [str(x) for x in members]})

    async def group_remove(self, group_id, members):
        return await self._post("/group/remove", {"groupId": str(group_id), "members": [str(x) for x in members]})

    async def group_rename(self, group_id, name):
        return await self._post("/group/rename", {"groupId": str(group_id), "name": str(name)})

    async def group_deputy(self, group_id, members):
        return await self._post("/group/deputy", {"groupId": str(group_id), "members": [str(x) for x in members]})

    async def group_leave(self, group_id, silent=False):
        return await self._post("/group/leave", {"groupId": str(group_id), "silent": bool(silent)})

    # Poll
    async def poll_create(self, group_id, question, options, **extra):
        body = {"groupId": str(group_id), "question": str(question), "options": [str(o) for o in options]}
        body.update(extra)
        return await self._post("/poll/create", body)

    async def _get_bytes(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> tuple[bytes, str]:
        import aiohttp

        if not self._session or self._session.closed:
            raise RuntimeError("bridge session is not connected")
        try:
            async with self._session.get(
                f"{self.bridge_url}{path}",
                params=params or {},
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status != 200:
                    raise RuntimeError(
                        f"bridge bytes request failed with HTTP {response.status}"
                    )
                content_type = str(response.headers.get("Content-Type") or "")
                if not content_type.lower().startswith("image/png"):
                    raise RuntimeError("bridge returned a non-PNG QR response")
                length = int(response.headers.get("Content-Length") or 0)
                if length > 2 * 1024 * 1024:
                    raise RuntimeError("QR response exceeds the 2 MiB cap")
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.content.iter_chunked(64 * 1024):
                    total += len(chunk)
                    if total > 2 * 1024 * 1024:
                        raise RuntimeError("QR response exceeds the 2 MiB cap")
                    chunks.append(chunk)
                return b"".join(chunks), content_type
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise RuntimeError(
                redact_text(str(exc)) or "bridge bytes request failed"
            ) from exc

    async def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        import aiohttp
        if not self._session or self._session.closed:
            return {"error": "no session"}
        try:
            async with self._session.get(
                f"{self.bridge_url}{path}",
                params=params or {},
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                return await resp.json()
        except Exception as e:
            return {"error": str(e)}

    async def call(self, method: str, *args) -> Dict[str, Any]:
        """Call ANY zca-js API method through the bridge passthrough.

        Covers the full zca-js surface beyond the first-class helpers above —
        forwardMessage, deleteMessage, sendVideo, sendLink, getGroupMembersInfo,
        getGroupChatHistory, createReminder, setMute, setPinnedConversations,
        block/unblock, votePoll, profile/settings, business catalog, etc.

        Pass args positionally exactly as zca-js documents them. Where a method
        takes a ThreadType, pass the string "user" or "group" (auto-converted).

        Example:
            await adapter.call("deleteMessage", {"data": {...}, "threadId": tid, "type": "user"})
            await adapter.call("getGroupMembersInfo", ["<uid1>", "<uid2>"])
            await adapter.call("setMute", {}, chat_id, "user")
        """
        return await self._post(f"/api/{method}", {"args": list(args)})


# ---------------------------------------------------------------------------
# Plugin registration
# ---------------------------------------------------------------------------

def check_requirements() -> bool:
    """Zalo needs a bridge URL and aiohttp."""
    try:
        import aiohttp  # noqa
    except ImportError:
        return False
    token = os.getenv("ZALO_PLUGIN_TOKEN", "")
    return bool(os.getenv("ZALO_PLUGIN_URL")) and len(token.encode("utf-8")) >= 32


def validate_config(config) -> bool:
    extra = getattr(config, "extra", {}) or {}
    try:
        company = CompanyConfig.from_platform_extra(extra)
        company.require_runtime_secrets()
    except (CompanyConfigError, TypeError, ValueError):
        return False
    return True


def _env_enablement() -> Optional[dict]:
    """Seed PlatformConfig.extra from env so env-only setups show in status."""
    bridge_url = os.getenv("ZALO_PLUGIN_URL")
    if not bridge_url:
        return None
    extra = {
        "bridge_url": bridge_url.rstrip("/"),
        "bridge_token": os.getenv("ZALO_PLUGIN_TOKEN", ""),
    }
    result: Dict[str, Any] = {"extra": extra}
    home = os.getenv("ZALO_HOME_CHANNEL")
    if home:
        chat_id, thread_type = _parse_home_channel(home)
        if chat_id:
            result["home_channel"] = {"chat_id": chat_id, "chat_type": "group" if thread_type == "group" else "dm"}
    return result


def _probe_health(bridge_url: str, token: str) -> Optional[Dict[str, Any]]:
    """GET /health → {loggedIn, sessionDead, ...} or None if unreachable.

    Distinguishes the two failure modes the user must act on differently:
      - None            → bridge process is DOWN (service stopped / never started)
      - {loggedIn:False}→ bridge is UP but the Zalo session is logged out/expired
    """
    try:
        import urllib.request
        import json as _json
        req = urllib.request.Request(f"{bridge_url}/health")
        if token:
            req.add_header("x-bridge-token", token)
        with urllib.request.urlopen(req, timeout=5) as r:
            return _json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def _bridge_cli_hint() -> str:
    """Best-effort name of the bridge CLI for copy-paste hints."""
    import shutil
    if shutil.which("hermes-zalo-plugin"):
        return "hermes-zalo-plugin"
    return "npx hermes-zalo-plugin"  # works without a global install


def _run_bridge_login() -> bool:
    """Run the bridge's QR login interactively (blocks until scanned/failed).

    Returns True on success. Uses the installed CLI if present, else npx.
    """
    import subprocess
    import shutil
    cli = "hermes-zalo-plugin" if shutil.which("hermes-zalo-plugin") else None
    cmd = [cli, "login"] if cli else ["npx", "hermes-zalo-plugin", "login"]
    try:
        # Inherit stdio so the ASCII QR renders and the user can scan it.
        return subprocess.run(cmd).returncode == 0
    except Exception as e:
        logger.warning(
            "Zalo: could not launch bridge login: %s",
            redact_text(str(e)) or "unknown error",
        )
        return False


def _fetch_contacts(bridge_url: str, token: str) -> Optional[Dict[str, Any]]:
    """GET /contacts from the bridge → {groups:[{id,name}], friends:[{id,name}]}.
    Returns None if the bridge is unreachable or not logged in."""
    try:
        import urllib.request
        import json as _json
        req = urllib.request.Request(f"{bridge_url}/contacts")
        if token:
            req.add_header("x-bridge-token", token)
        with urllib.request.urlopen(req, timeout=15) as r:
            data = _json.loads(r.read().decode("utf-8"))
        if not data.get("success"):
            return None
        return {"groups": data.get("groups") or [], "friends": data.get("friends") or []}
    except Exception:
        return None


def _norm_text(s: str) -> str:
    """Lowercase + strip Vietnamese diacritics for forgiving name search."""
    import unicodedata
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d").replace("Đ", "D").lower().strip()


def _pick_ids(items: List[Dict[str, Any]], label: str, prompt_fn, print_fn) -> str:
    """Interactive picker over a possibly long {id,name} list.

    Commands at the prompt:
      <text>   search names (diacritic-insensitive); shows numbered matches
      <n,n,..> pick by number from the LAST shown list (accumulates)
      all      list everything (careful with long lists)
      done     show current picks
      <blank>  finish and return selected ids
    Raw ids can be pasted directly too.
    """
    print_fn(label)
    print_fn(f"   {len(items)} item(s). Type a name to search, numbers to pick, 'all' to list, blank to finish.")
    selected: Dict[str, str] = {}  # id -> name
    shown = items[: min(20, len(items))]  # default: first 20

    def _render(lst):
        if not lst:
            print_fn("   (no matches)")
            return
        for i, it in enumerate(lst, 1):
            mark = "✓" if str(it.get("id", "")) in selected else " "
            print_fn(f"   [{mark}] {i}. {it.get('name','?')}  ({it.get('id','')})")

    _render(shown)
    while True:
        raw = prompt_fn("search / numbers / 'all' / blank=done", default="")
        if raw is None:
            break
        raw = raw.strip()
        if not raw:
            break
        if raw.lower() == "all":
            shown = items
            _render(shown)
            continue
        if raw.lower() == "done":
            if selected:
                print_fn("   Selected: " + ", ".join(selected.values()))
            else:
                print_fn("   (nothing selected yet)")
            continue
        # If it looks like raw id(s) pasted directly (long digit strings) → add.
        toks = [t for t in raw.replace(" ", "").split(",") if t]
        if toks and all(t.isdigit() and len(t) >= 8 for t in toks):
            for t in toks:
                selected[t] = t
            print_fn("   Selected: " + ", ".join(selected.values()))
            continue
        # Pure short number / number-list → pick from current `shown`.
        if toks and all(t.isdigit() for t in toks):
            for t in toks:
                idx = int(t) - 1
                if 0 <= idx < len(shown):
                    it = shown[idx]
                    selected[str(it.get("id", ""))] = it.get("name", it.get("id", ""))
            print_fn("   Selected: " + (", ".join(selected.values()) or "(none)"))
            continue
        # Otherwise treat as a search query over names.
        q = _norm_text(raw)
        shown = [it for it in items if q in _norm_text(it.get("name", ""))]
        print_fn(f"   {len(shown)} match(es) for '{raw}':")
        _render(shown)
    return ",".join([i for i in selected.keys() if i])


def interactive_setup() -> None:
    """Configure the fail-closed five-person company assistant."""
    from hermes_cli.setup import (
        get_env_value,
        print_header,
        print_info,
        print_warning,
        prompt,
        save_env_value,
    )

    print_header("Zalo Company Assistant")
    print_info(
        "Khai báo bắt buộc allowlist thành viên, quản trị viên và nhóm công ty. "
        "Bot luôn lưu group; chỉ mention hợp lệ mới gọi Hermes."
    )

    bridge_url = str(
        prompt(
            "Bridge URL (http://127.0.0.1:8787)",
            default=get_env_value("ZALO_PLUGIN_URL") or "http://127.0.0.1:8787",
        )
        or ""
    ).strip().rstrip("/")
    token = str(get_env_value("ZALO_PLUGIN_TOKEN") or "").strip()
    if len(token.encode("utf-8")) < 32:
        token = str(prompt("Bridge token (ít nhất 32 byte)", password=True) or "").strip()

    users = str(
        prompt(
            "Zalo ID thành viên được phép (bắt buộc, phân cách bằng dấu phẩy)",
            default=get_env_value("ZALO_ALLOWED_USERS") or "",
        )
        or ""
    ).strip()
    admins = str(
        prompt(
            "Zalo ID quản trị viên (bắt buộc, phải nằm trong thành viên)",
            default=get_env_value("ZALO_ADMIN_USERS") or "",
        )
        or ""
    ).strip()
    groups = str(
        prompt(
            "Zalo ID nhóm công ty (bắt buộc, phân cách bằng dấu phẩy)",
            default=get_env_value("ZALO_ALLOWED_GROUPS") or "",
        )
        or ""
    ).strip()

    candidate_env = dict(os.environ)
    candidate_env.update(
        {
            "ZALO_PLUGIN_URL": bridge_url,
            "ZALO_PLUGIN_TOKEN": token,
            "ZALO_ALLOWED_USERS": users,
            "ZALO_ADMIN_USERS": admins,
            "ZALO_ALLOWED_GROUPS": groups,
            "ZALO_GROUP_MODE": "mention",
        }
    )
    try:
        validated = CompanyConfig.from_platform_extra({}, env=candidate_env)
        validated.require_runtime_secrets()
    except CompanyConfigError as exc:
        print_warning(f"Cấu hình chưa hợp lệ, chưa ghi thay đổi: {exc}")
        return

    for key, value in (
        ("ZALO_PLUGIN_URL", validated.bridge_url),
        ("ZALO_PLUGIN_TOKEN", token),
        ("ZALO_ALLOWED_USERS", users),
        ("ZALO_ADMIN_USERS", admins),
        ("ZALO_ALLOWED_GROUPS", groups),
        ("ZALO_GROUP_MODE", "mention"),
    ):
        save_env_value(key, value)

    home = str(
        prompt(
            "Home thread cho cron (tùy chọn: user:<id> hoặc group:<id>)",
            default=get_env_value("ZALO_HOME_CHANNEL") or "",
        )
        or ""
    ).strip()
    if home:
        save_env_value("ZALO_HOME_CHANNEL", home)

    health = _probe_health(validated.bridge_url, token)
    print_info(
        "✓ Đã lưu cấu hình company assistant: "
        f"{len(validated.allowed_users)} thành viên, "
        f"{len(validated.admin_users)} admin, "
        f"{len(validated.allowed_groups)} group."
    )
    if health and health.get("loggedIn") and not health.get("sessionDead"):
        print_info("✓ Bridge đang chạy và đã đăng nhập; chạy `hermes gateway` để bắt đầu.")
    else:
        print_info("Bridge chưa sẵn sàng; chạy `hermes-zalo-plugin login` rồi `hermes gateway`.")


def is_connected() -> bool:
    """Lightweight check used by `hermes gateway status` (env-only)."""
    return bool(os.getenv("ZALO_PLUGIN_URL"))


def register(ctx):
    """Plugin entry point: called by the Hermes plugin system."""
    ctx.register_platform(
        name="zalo",
        label="Zalo",
        adapter_factory=lambda cfg: ZaloAdapter(cfg),
        check_fn=check_requirements,
        validate_config=validate_config,
        required_env=["ZALO_PLUGIN_URL", "ZALO_PLUGIN_TOKEN"],
        install_hint="Run the hermes-zalo-plugin Node service and `pip install aiohttp`",
        setup_fn=interactive_setup,
        env_enablement_fn=_env_enablement,
        cron_deliver_env_var="ZALO_HOME_CHANNEL",
        allowed_users_env="ZALO_ALLOWED_USERS",
        max_message_length=4000,
        emoji="",
        pii_safe=False,
        allow_update_command=True,
        platform_hint=(
            "You are chatting via Zalo (a Vietnamese messaging app). Zalo does "
            "not render markdown — use plain text only. The user likely writes "
            "in Vietnamese; reply in Vietnamese unless they switch. Keep replies "
            "concise and conversational. You can send images, files, stickers, "
            "and voice. Messages over ~4000 chars are auto-split."
        ),
    )
    register_tooling(ctx, _LAZY_TOOLING)
