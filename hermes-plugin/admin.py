"""Small, immediate admin surface for the company Zalo assistant.

This module intentionally contains role checks only.  It is not an approval
broker: an authenticated administrator's action is executed immediately.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import inspect
import logging
import math
import os
import secrets
import time
from collections import deque
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Mapping

try:
    from .company_config import (
        CompanyConfig,
        CompanyConfigConflict,
        CompanyConfigError,
        CompanyConfigFile,
    )
    from .history_store import HistoryStore, redact_text, redact_value
    from .request_context import Requester
except ImportError:  # Hermes may also load adapter.py as a top-level module.
    from company_config import (
        CompanyConfig,
        CompanyConfigConflict,
        CompanyConfigError,
        CompanyConfigFile,
    )
    from history_store import HistoryStore, redact_text, redact_value
    from request_context import Requester


_MEMORY_ENTRY_DELIMITER = "\n§\n"
_SCRYPT_N = 1 << 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32
logger = logging.getLogger(__name__)


class AdminWebSettingsError(ValueError):
    """Raised when the optional loopback admin Web UI is configured unsafely."""


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    encoded = str(value).encode("ascii")
    return base64.urlsafe_b64decode(encoded + b"=" * (-len(encoded) % 4))


def hash_admin_password(password: str, *, salt: bytes | None = None) -> str:
    """Return a self-contained scrypt password hash suitable for an env var."""

    value = str(password)
    if not value:
        raise ValueError("admin password must not be empty")
    selected_salt = os.urandom(16) if salt is None else bytes(salt)
    if len(selected_salt) < 16:
        raise ValueError("password salt must contain at least 16 bytes")
    digest = hashlib.scrypt(
        value.encode("utf-8"),
        salt=selected_salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
    )
    return "$".join(
        (
            "scrypt",
            str(_SCRYPT_N),
            str(_SCRYPT_R),
            str(_SCRYPT_P),
            _b64encode(selected_salt),
            _b64encode(digest),
        )
    )


def _parse_password_hash(encoded_hash: str) -> tuple[int, int, int, bytes, bytes]:
    try:
        algorithm, n, r, p, salt, digest = str(encoded_hash).split("$", 5)
        parsed = (int(n), int(r), int(p), _b64decode(salt), _b64decode(digest))
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ValueError("invalid scrypt password hash") from exc
    if (
        algorithm != "scrypt"
        or parsed[0] != _SCRYPT_N
        or parsed[1] != _SCRYPT_R
        or parsed[2] != _SCRYPT_P
        or len(parsed[3]) < 16
        or len(parsed[4]) != _SCRYPT_DKLEN
    ):
        raise ValueError("invalid scrypt password hash")
    return parsed


def verify_admin_password(password: str, encoded_hash: str) -> bool:
    try:
        n, r, p, salt, expected = _parse_password_hash(encoded_hash)
        actual = hashlib.scrypt(
            str(password).encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            dklen=len(expected),
        )
    except (TypeError, ValueError, UnicodeError):
        return False
    return hmac.compare_digest(actual, expected)


def _env_truthy(value: Any) -> bool:
    return str(value if value is not None else "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@dataclass(frozen=True, slots=True)
class AdminWebSettings:
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8790
    password_hash: str = ""
    session_secret: bytes = b""
    session_ttl_seconds: int = 86400

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
    ) -> "AdminWebSettings":
        source = os.environ if env is None else env
        if not isinstance(source, Mapping):
            raise AdminWebSettingsError("environment must be a mapping")
        enabled = _env_truthy(source.get("ZALO_ADMIN_WEB_ENABLED"))
        host = str(source.get("ZALO_ADMIN_WEB_HOST") or "127.0.0.1").strip()
        if host != "127.0.0.1":
            raise AdminWebSettingsError(
                "ZALO_ADMIN_WEB_HOST must be 127.0.0.1"
            )
        try:
            port = int(source.get("ZALO_ADMIN_WEB_PORT") or 8790)
            ttl = int(source.get("ZALO_ADMIN_WEB_SESSION_TTL_SECONDS") or 86400)
        except (TypeError, ValueError) as exc:
            raise AdminWebSettingsError(
                "admin Web port and session TTL must be integers"
            ) from exc
        if not 1 <= port <= 65535:
            raise AdminWebSettingsError("ZALO_ADMIN_WEB_PORT must be between 1 and 65535")
        if not 300 <= ttl <= 7 * 24 * 60 * 60:
            raise AdminWebSettingsError(
                "ZALO_ADMIN_WEB_SESSION_TTL_SECONDS must be between 300 and 604800"
            )
        password_hash = str(source.get("ZALO_ADMIN_WEB_PASSWORD_HASH") or "").strip()
        session_secret = str(
            source.get("ZALO_ADMIN_WEB_SESSION_SECRET") or ""
        ).encode("utf-8")
        if enabled:
            if not password_hash:
                raise AdminWebSettingsError(
                    "ZALO_ADMIN_WEB_PASSWORD_HASH is required when enabled"
                )
            try:
                _parse_password_hash(password_hash)
            except ValueError as exc:
                raise AdminWebSettingsError(
                    "ZALO_ADMIN_WEB_PASSWORD_HASH is invalid"
                ) from exc
            if len(session_secret) < 32:
                raise AdminWebSettingsError(
                    "ZALO_ADMIN_WEB_SESSION_SECRET must contain at least 32 UTF-8 bytes"
                )
        return cls(
            enabled=enabled,
            host=host,
            port=port,
            password_hash=password_hash,
            session_secret=session_secret,
            session_ttl_seconds=ttl,
        )


class AdminSessionSigner:
    """Sign opaque in-memory session identifiers with HMAC-SHA256."""

    def __init__(self, secret: bytes | str):
        self.secret = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
        if len(self.secret) < 32:
            raise ValueError("session signing secret must contain at least 32 bytes")

    def sign(self, session_id: str) -> str:
        value = str(session_id)
        signature = hmac.new(self.secret, value.encode("utf-8"), hashlib.sha256).digest()
        return f"{value}.{_b64encode(signature)}"

    def verify(self, signed_value: str) -> str:
        try:
            value, supplied = str(signed_value).rsplit(".", 1)
            expected = hmac.new(
                self.secret,
                value.encode("utf-8"),
                hashlib.sha256,
            ).digest()
            actual = _b64decode(supplied)
        except (ValueError, UnicodeError) as exc:
            raise ValueError("invalid session signature") from exc
        if not value or not hmac.compare_digest(actual, expected):
            raise ValueError("invalid session signature")
        return value


class LoginThrottle:
    """Small process-local lockout for the single shared admin password."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        maximum_failures: int = 5,
        window_seconds: int = 300,
        lock_seconds: int = 300,
    ) -> None:
        self.clock = clock
        self.maximum_failures = int(maximum_failures)
        self.window_seconds = int(window_seconds)
        self.lock_seconds = int(lock_seconds)
        self._failures: deque[float] = deque()
        self._locked_until = 0.0

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._failures and self._failures[0] <= cutoff:
            self._failures.popleft()

    def retry_after(self) -> int:
        now = float(self.clock())
        if self._locked_until <= now:
            self._locked_until = 0.0
            self._prune(now)
            return 0
        return max(1, int(math.ceil(self._locked_until - now)))

    def record_failure(self) -> int:
        retry = self.retry_after()
        if retry:
            return retry
        now = float(self.clock())
        self._prune(now)
        self._failures.append(now)
        if len(self._failures) >= self.maximum_failures:
            self._locked_until = now + self.lock_seconds
            self._failures.clear()
            return self.lock_seconds
        return 0

    def record_success(self) -> None:
        self._failures.clear()
        self._locked_until = 0.0

    def reset(self) -> None:
        self.record_success()


class AdminDenied(PermissionError):
    """Raised when a non-admin reaches an administrative operation."""


class AdminGuard:
    @staticmethod
    def require(requester: Requester) -> None:
        if not requester.is_admin:
            raise AdminDenied("only a Zalo administrator may perform this action")


async def _maybe_call(callback: Callable[..., Any] | None, *args: Any, **kwargs: Any) -> Any:
    if callback is None:
        return {"success": False, "error": "operation is not configured"}
    result = callback(*args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


class AdminService:
    """Implement the explicit ``zalo_admin`` actions."""

    def __init__(
        self,
        *,
        config_file: CompanyConfigFile | None = None,
        store: HistoryStore | None = None,
        memory_path: str | Path | None = None,
        status_provider: Callable[[], Any] | None = None,
        lifecycle: Mapping[str, Callable[..., Any]] | None = None,
        log_path: str | Path | None = None,
        log_provider: Callable[[int], Any] | None = None,
        runtime_config_provider: Callable[[], Any] | None = None,
        runtime_config_applier: Callable[[CompanyConfig], Any] | None = None,
        export_root: str | Path | None = None,
        follow_up_service: Any | None = None,
    ) -> None:
        self.config_file = config_file
        self.store = store
        self.memory_path = Path(memory_path) if memory_path else None
        self.status_provider = status_provider
        self.lifecycle = dict(lifecycle or {})
        self.log_path = Path(log_path) if log_path else None
        self.log_provider = log_provider
        self.runtime_config_provider = runtime_config_provider
        self.runtime_config_applier = runtime_config_applier
        self.export_root = Path(export_root) if export_root else None
        self.follow_up_service = follow_up_service
        self._config_lock = asyncio.Lock()

    def require(self, requester: Requester) -> None:
        AdminGuard.require(requester)

    def _memory_text(self) -> str:
        if self.memory_path is None:
            raise CompanyConfigError("shared memory path is not configured")
        try:
            return self.memory_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    def _write_memory(self, text: str) -> None:
        if self.memory_path is None:
            raise CompanyConfigError("shared memory path is not configured")
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.memory_path.with_name("." + self.memory_path.name + ".tmp")
        temporary.write_text(text, encoding="utf-8", newline="\n")
        temporary.replace(self.memory_path)

    def _memory_entries(self) -> list[str]:
        return [
            entry.strip()
            for entry in self._memory_text().split(_MEMORY_ENTRY_DELIMITER)
            if entry.strip()
        ]

    def _write_memory_entries(self, entries: list[str]) -> None:
        self._write_memory(_MEMORY_ENTRY_DELIMITER.join(entries))

    def memory_add(self, text: str, *, requester: Requester) -> dict[str, Any]:
        self.require(requester)
        value = str(text or "").strip()
        if not value:
            raise ValueError("memory text is required")
        entries = self._memory_entries()
        if value in entries:
            return {"success": True, "action": "memory_add", "added": False}
        entries.append(value)
        self._write_memory_entries(entries)
        return {"success": True, "action": "memory_add", "added": True}

    def memory_update(
        self,
        old: str,
        new: str,
        *,
        requester: Requester,
    ) -> dict[str, Any]:
        self.require(requester)
        old_value, new_value = str(old or ""), str(new or "")
        if not old_value or not new_value:
            raise ValueError("old and new memory text are required")
        entries = self._memory_entries()
        match = next(
            (index for index, entry in enumerate(entries) if old_value in entry),
            None,
        )
        if match is None:
            raise ValueError("memory text was not found")
        entries[match] = entries[match].replace(old_value, new_value, 1).strip()
        self._write_memory_entries(entries)
        return {"success": True, "action": "memory_update"}

    def memory_delete(self, text: str, *, requester: Requester) -> dict[str, Any]:
        self.require(requester)
        value = str(text or "").strip()
        if not value:
            raise ValueError("memory text is required")
        entries = self._memory_entries()
        match = next(
            (index for index, entry in enumerate(entries) if value in entry),
            None,
        )
        if match is None:
            return {"success": True, "action": "memory_delete", "deleted": False}
        entries.pop(match)
        self._write_memory_entries(entries)
        return {"success": True, "action": "memory_delete", "deleted": True}

    def get_access_config(self, *, requester: Requester) -> dict[str, Any]:
        self.require(requester)
        if self.config_file is None:
            raise CompanyConfigError("company config file is not configured")
        return self.config_file.read_access_config().to_mapping()

    async def apply_access_config(
        self,
        *,
        allowed_users: Any,
        admin_users: Any,
        allowed_groups: Any,
        expected_fingerprint: str,
        requester: Requester,
    ) -> dict[str, Any]:
        self.require(requester)
        if self.config_file is None:
            raise CompanyConfigError("company config file is not configured")
        if self.runtime_config_provider is None:
            raise CompanyConfigError("company config runtime is not configured")
        async with self._config_lock:
            persisted_before = self.config_file.read_access_config()
            runtime_before = await _maybe_call(self.runtime_config_provider)
            if not isinstance(runtime_before, CompanyConfig):
                raise CompanyConfigError(
                    "runtime config provider did not return CompanyConfig"
                )
            persisted_after = self.config_file.apply_access_config(
                allowed_users=allowed_users,
                admin_users=admin_users,
                allowed_groups=allowed_groups,
                expected_fingerprint=expected_fingerprint,
            )
            runtime_after = replace(
                runtime_before,
                allowed_users=persisted_after.config.allowed_users,
                admin_users=persisted_after.config.admin_users,
                allowed_groups=persisted_after.config.allowed_groups,
            )
            try:
                if self.runtime_config_applier is not None:
                    await _maybe_call(self.runtime_config_applier, runtime_after)
            except Exception:
                try:
                    self.config_file.rollback_access_config(
                        persisted_before,
                        expected_fingerprint=persisted_after.fingerprint,
                    )
                finally:
                    if self.runtime_config_applier is not None:
                        try:
                            await _maybe_call(
                                self.runtime_config_applier,
                                runtime_before,
                            )
                        except Exception:
                            pass
                raise
            return {
                "success": True,
                "config": persisted_after.config.to_mapping(),
                "fingerprint": persisted_after.fingerprint,
            }

    async def config_mutate(
        self,
        action: str,
        zalo_id: str,
        *,
        requester: Requester,
    ) -> dict[str, Any]:
        self.require(requester)
        if self.config_file is None:
            raise CompanyConfigError("company config file is not configured")
        value = str(zalo_id or "").strip()
        if not value:
            raise CompanyConfigError("Zalo ID is required")
        snapshot = self.config_file.read_access_config()
        users = set(snapshot.config.allowed_users)
        admins = set(snapshot.config.admin_users)
        groups = set(snapshot.config.allowed_groups)
        if action == "add_user":
            users.add(value)
        elif action == "remove_user":
            if value in admins:
                raise CompanyConfigError("remove admin role before removing user")
            users.discard(value)
        elif action == "add_admin":
            if value not in users:
                raise CompanyConfigError("admin must already be an allowed user")
            admins.add(value)
        elif action == "remove_admin":
            if value in admins and len(admins) == 1:
                raise CompanyConfigError("cannot remove the last admin")
            admins.discard(value)
        elif action == "add_group":
            groups.add(value)
        elif action == "remove_group":
            if value in groups and len(groups) == 1:
                raise CompanyConfigError("cannot remove the last allowed group")
            groups.discard(value)
        else:
            raise CompanyConfigError(f"unknown config mutation: {action}")
        result = await self.apply_access_config(
            allowed_users=users,
            admin_users=admins,
            allowed_groups=groups,
            expected_fingerprint=snapshot.fingerprint,
            requester=requester,
        )
        return {**result, "action": action}

    def history_export(self, destination: str | Path, *, requester: Requester, **filters: Any) -> dict[str, Any]:
        self.require(requester)
        if self.store is None:
            raise CompanyConfigError("history store is not configured")
        destination_path = Path(destination)
        if self.export_root is not None:
            root = self.export_root.resolve(strict=False)
            if not destination_path.is_absolute():
                destination_path = root / destination_path
            destination_path = destination_path.resolve(strict=False)
            try:
                destination_path.relative_to(root)
            except ValueError as exc:
                raise CompanyConfigError(
                    "history export destination must stay inside export root"
                ) from exc
        return self.store.export_history(destination_path, **filters)

    def history_delete(self, *, requester: Requester, **filters: Any) -> dict[str, Any]:
        self.require(requester)
        if self.store is None:
            raise CompanyConfigError("history store is not configured")
        return self.store.delete_history(**filters)

    def web_history_export(
        self,
        *,
        requester: Requester,
        thread_type: str | None = None,
        thread_id: str | None = None,
        sender_id: str | None = None,
        query: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> dict[str, Any]:
        self.require(requester)
        if self.store is None or self.export_root is None:
            raise CompanyConfigError("history export is not configured")
        self.export_root.mkdir(parents=True, exist_ok=True)
        destination = self.export_root / (
            f"history-{int(time.time())}-{secrets.token_hex(4)}.jsonl"
        )
        result = self.store.export_history(
            destination,
            thread_type=thread_type,
            thread_id=thread_id,
            sender_id=sender_id,
            query=query,
            since=since,
            until=until,
        )
        return {**result, "path": str(destination)}

    async def action(self, action: str, *, requester: Requester, **args: Any) -> Any:
        self.require(requester)
        action = str(action or "").strip().lower()
        if action in {"get_access_config", "access"}:
            return self.get_access_config(requester=requester)
        if action == "apply_access_config":
            return await self.apply_access_config(
                allowed_users=args.get("allowed_users"),
                admin_users=args.get("admin_users"),
                allowed_groups=args.get("allowed_groups"),
                expected_fingerprint=str(
                    args.get("fingerprint")
                    or args.get("expected_fingerprint")
                    or ""
                ),
                requester=requester,
            )
        config_actions = {
            "add_user",
            "remove_user",
            "add_admin",
            "remove_admin",
            "add_group",
            "remove_group",
        }
        if action in config_actions:
            return await self.config_mutate(
                action,
                str(args.get("zalo_id") or args.get("user_id") or ""),
                requester=requester,
            )
        return await self._action_without_config(
            action,
            requester=requester,
            **args,
        )

    async def _action_without_config(
        self,
        action: str,
        *,
        requester: Requester,
        **args: Any,
    ) -> Any:
        if action == "status":
            result = await _maybe_call(self.status_provider)
            return result if result is not None else {"success": True}
        if action == "memory_add":
            return self.memory_add(str(args.get("text") or ""), requester=requester)
        if action == "memory_update":
            return self.memory_update(str(args.get("old") or ""), str(args.get("new") or ""), requester=requester)
        if action == "memory_delete":
            return self.memory_delete(str(args.get("text") or ""), requester=requester)
        if action == "history_export":
            return self.history_export(str(args.get("destination") or "history.jsonl"), requester=requester, **_history_filters(args))
        if action == "history_delete":
            return self.history_delete(requester=requester, **_history_filters(args))
        if action in {"login_qr", "reconnect", "start", "stop", "restart"}:
            return await _maybe_call(self.lifecycle.get(action), args)
        if action == "show_logs":
            lines = int(args.get("lines") or 100)
            if self.log_provider is not None:
                return await _maybe_call(self.log_provider, lines)
            return self.show_logs(lines, requester=requester)
        if action.startswith("follow_up_"):
            if self.follow_up_service is None:
                raise CompanyConfigError("follow-up service is not configured")
            if action == "follow_up_create":
                return await self.follow_up_service.create(
                    owner_id=requester.requester_id,
                    title=str(args.get("title") or ""),
                    question=str(args.get("question") or ""),
                    targets=args.get("targets") or [],
                    due_at=str(args.get("due_at") or ""),
                )
            if action == "follow_up_status":
                return await self.follow_up_service.status(
                    follow_up_id=(
                        int(args["follow_up_id"])
                        if args.get("follow_up_id") is not None
                        else None
                    )
                )
            if action == "follow_up_extend":
                return await self.follow_up_service.extend(
                    actor_id=requester.requester_id,
                    follow_up_id=int(args.get("follow_up_id")),
                    due_at=str(args.get("due_at") or ""),
                )
            if action == "follow_up_remind":
                return await self.follow_up_service.remind(
                    actor_id=requester.requester_id,
                    follow_up_id=int(args.get("follow_up_id")),
                    target_ids=args.get("target_ids"),
                )
            if action == "follow_up_close":
                return self.follow_up_service.close(
                    actor_id=requester.requester_id,
                    follow_up_id=int(args.get("follow_up_id")),
                )
        raise ValueError(f"unknown admin action: {action}")

    def show_logs(self, lines: int = 100, *, requester: Requester) -> dict[str, Any]:
        self.require(requester)
        if self.log_path is None:
            return {"success": True, "lines": []}
        try:
            content = self.log_path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            content = []
        return {"success": True, "lines": content[-max(1, min(int(lines), 500)) :]}


def _history_filters(args: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: args[key]
        for key in ("thread_type", "thread_id", "since", "until")
        if args.get(key) is not None
    }


WEB_ADMIN_REQUESTER = Requester(
    requester_id="web-admin",
    thread_type="system",
    thread_id="admin-web",
    is_admin=True,
    session_key="zalo:system:admin-web",
)


@dataclass(slots=True)
class _AdminSession:
    csrf: str
    expires_at: float


ADMIN_WEB_ROOT = Path(__file__).resolve().parent / "admin_web"


def _read_admin_asset(name: str) -> str:
    if name not in {"index.html", "admin.css", "app.js"}:
        raise RuntimeError(f"unknown Admin Web asset: {name}")
    path = ADMIN_WEB_ROOT / name
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"required Admin Web asset is missing: {name}") from exc


ADMIN_HTML = _read_admin_asset("index.html")
ADMIN_CSS = _read_admin_asset("admin.css")
ADMIN_APP_JS = _read_admin_asset("app.js")


class AdminWebApp:
    """Authenticated loopback-only Web UI embedded in the Hermes plugin."""

    COOKIE_NAME = "hermes_zalo_admin"
    RESTART_COOLDOWN_SECONDS = 0.5

    def __init__(
        self,
        *,
        settings: AdminWebSettings,
        admin: AdminService,
        store: HistoryStore,
        bridge: Any,
        export_root: str | Path,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.settings = settings
        self.admin = admin
        self.store = store
        self.bridge = bridge
        self.export_root = Path(export_root)
        self.clock = clock
        self.signer = (
            AdminSessionSigner(settings.session_secret) if settings.enabled else None
        )
        self.throttle = LoginThrottle(clock=clock)
        self._login_lock = asyncio.Lock()
        self._lifecycle_lock = asyncio.Lock()
        self.sessions: dict[str, _AdminSession] = {}
        self._runner: Any = None
        self._site: Any = None
        self._application: Any = None
        self._session_id_key: Any = None
        self._session_key: Any = None
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self._relogin_task: asyncio.Task[Any] | None = None
        self._restart_tasks: dict[str, asyncio.Task[Any]] = {}
        self._restart_accepted_at: dict[str, float] = {}
        self._contact_cache: dict[str, list[dict[str, Any]]] = {}

    @property
    def is_running(self) -> bool:
        return self._runner is not None

    @property
    def application(self):
        return self.create_application()

    def _audit(
        self,
        action: str,
        *,
        status: str = "success",
        error_text: str | None = None,
        target_id: str | int | None = None,
        count: int | None = None,
    ) -> int:
        metadata: dict[str, Any] = {}
        if target_id is not None:
            metadata["target_id"] = str(target_id)
        if count is not None:
            metadata["count"] = int(count)
        return self.store.log_tool_activity(
            requester_id="web-admin",
            thread_type="system",
            thread_id="admin-web",
            tool_name=f"admin_web.{action}",
            status=status,
            error_text=redact_text(error_text),
            metadata=metadata,
        )

    @staticmethod
    def _error(
        status: int,
        code: str,
        message: str,
        *,
        retryable: bool = False,
    ):
        from aiohttp import web

        return web.json_response(
            {
                "code": str(code),
                "message": redact_text(str(message)) or "Yêu cầu thất bại",
                "retryable": bool(retryable),
            },
            status=int(status),
            headers={"Cache-Control": "no-store"},
        )

    @staticmethod
    def _invalid_config_message(exc: Exception) -> str:
        message = str(exc).lower()
        if "admin_users" in message and "subset" in message:
            return "Mọi quản trị viên phải đồng thời là thành viên được phép"
        if "allowed_users" in message:
            return "Danh sách thành viên được phép không được để trống"
        if "admin_users" in message or "last admin" in message:
            return "Danh sách quản trị viên phải còn ít nhất một người"
        if "allowed_groups" in message:
            return "Danh sách nhóm được phép không được để trống"
        return "Cấu hình không hợp lệ"

    def _require_session(self, request: Any) -> tuple[str, _AdminSession]:
        if self.signer is None:
            raise ValueError("admin Web UI is disabled")
        try:
            session_id = self.signer.verify(
                request.cookies.get(self.COOKIE_NAME, "")
            )
        except ValueError as exc:
            raise ValueError("invalid admin session") from exc
        session = self.sessions.get(session_id)
        if session is None or session.expires_at <= float(self.clock()):
            self.sessions.pop(session_id, None)
            raise ValueError("admin session expired")
        return session_id, session

    def create_application(self):
        from aiohttp import web

        if self._application is not None:
            return self._application

        @web.middleware
        async def errors(request: Any, handler: Callable[..., Any]):
            try:
                return await handler(request)
            except asyncio.CancelledError:
                raise
            except web.HTTPException as exc:
                if exc.status == 404:
                    code = "not_found"
                    message = "Không tìm thấy tài nguyên"
                elif exc.status == 405:
                    code = "method_not_allowed"
                    message = "Phương thức không được hỗ trợ"
                else:
                    code = "http_error"
                    message = "Yêu cầu HTTP không hợp lệ"
                response = self._error(exc.status, code, message)
                allow = exc.headers.get("Allow")
                if allow:
                    response.headers["Allow"] = allow
                return response
            except Exception as exc:
                logger.error(
                    "Admin Web request failed: %s",
                    redact_text(str(exc)) or "unknown error",
                )
                return self._error(
                    500,
                    "internal_error",
                    "Không thể xử lý yêu cầu",
                )

        @web.middleware
        async def auth(request: Any, handler: Callable[..., Any]):
            public = {
                ("GET", "/admin/"),
                ("GET", "/admin/assets/admin.css"),
                ("GET", "/admin/assets/app.js"),
                ("POST", "/admin/api/login"),
            }
            if (
                request.method == "GET"
                and request.path.startswith("/admin/assets/")
                and (request.method, request.path) not in public
            ):
                return self._error(404, "not_found", "Không tìm thấy tài nguyên")
            if (request.method, request.path) not in public:
                try:
                    session_id, session = self._require_session(request)
                except ValueError:
                    return self._error(
                        401,
                        "unauthorized",
                        "Phiên đăng nhập không hợp lệ hoặc đã hết hạn",
                    )
                request[self._session_id_key] = session_id
                request[self._session_key] = session
                if request.method not in {"GET", "HEAD", "OPTIONS"}:
                    supplied = request.headers.get("X-CSRF-Token", "")
                    if not hmac.compare_digest(str(supplied), session.csrf):
                        return self._error(
                            403,
                            "csrf",
                            "CSRF token không hợp lệ",
                        )
            return await handler(request)

        self._session_id_key = web.RequestKey("admin_session_id", str)
        self._session_key = web.RequestKey("admin_session", _AdminSession)
        app = web.Application(
            middlewares=[errors, auth],
            client_max_size=256 * 1024,
        )
        app.router.add_get("/admin/", self._page)
        app.router.add_get("/admin/assets/admin.css", self._admin_css)
        app.router.add_get("/admin/assets/app.js", self._admin_js)
        app.router.add_post("/admin/api/login", self._login)
        app.router.add_get("/admin/api/session", self._session_route)
        app.router.add_post("/admin/api/logout", self._logout)
        app.router.add_get("/admin/api/overview", self._overview)
        app.router.add_get("/admin/api/access", self._access)
        app.router.add_get("/admin/api/friends", self._friends)
        app.router.add_get("/admin/api/groups", self._groups)
        app.router.add_get(
            "/admin/api/groups/{group_id}/members",
            self._group_members,
        )
        app.router.add_post("/admin/api/access/apply", self._apply_access)
        app.router.add_get("/admin/api/conversations", self._conversations)
        app.router.add_get(
            "/admin/api/conversations/{conversation_id}",
            self._conversation,
        )
        app.router.add_get("/admin/api/history/search", self._history_search)
        app.router.add_post("/admin/api/history/export", self._history_export)
        app.router.add_post("/admin/api/history/delete", self._history_delete)
        app.router.add_get(
            "/admin/api/attachments/{attachment_id}",
            self._attachment,
        )
        app.router.add_get("/admin/api/activity", self._activity)
        app.router.add_get("/admin/api/system", self._system)
        app.router.add_post("/admin/api/system/qr", self._qr)
        app.router.add_get("/admin/api/system/qr.png", self._qr_png)
        app.router.add_post("/admin/api/system/reconnect", self._reconnect)
        app.router.add_post("/admin/api/system/restart", self._restart)
        app.router.add_get("/admin/api/system/logs", self._logs)
        self._application = app
        return app

    async def _page(self, _request: Any):
        from aiohttp import web

        return web.Response(
            text=ADMIN_HTML,
            content_type="text/html",
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": (
                    "default-src 'self'; base-uri 'none'; object-src 'none'; "
                    "frame-ancestors 'none'; form-action 'self'; "
                    "style-src 'self'; script-src 'self'; img-src 'self' blob:"
                ),
                "X-Content-Type-Options": "nosniff",
            },
        )

    async def _admin_css(self, _request: Any):
        from aiohttp import web

        return web.Response(
            text=ADMIN_CSS,
            content_type="text/css",
            charset="utf-8",
            headers={
                "Cache-Control": "no-cache",
                "X-Content-Type-Options": "nosniff",
            },
        )

    async def _admin_js(self, _request: Any):
        from aiohttp import web

        return web.Response(
            text=ADMIN_APP_JS,
            content_type="application/javascript",
            charset="utf-8",
            headers={
                "Cache-Control": "no-cache",
                "X-Content-Type-Options": "nosniff",
            },
        )

    async def _login(self, request: Any):
        from aiohttp import web

        if not self.settings.enabled or self.signer is None:
            return self._error(404, "disabled", "Admin Web UI chưa được bật")
        retry = self.throttle.retry_after()
        if retry:
            response = self._error(
                429,
                "login_throttled",
                "Đăng nhập đang tạm khóa",
                retryable=True,
            )
            response.headers["Retry-After"] = str(retry)
            return response
        try:
            body = await request.json()
        except Exception:
            return self._error(400, "invalid_json", "Dữ liệu đăng nhập không hợp lệ")
        async with self._login_lock:
            retry = self.throttle.retry_after()
            if retry:
                response = self._error(
                    429,
                    "login_throttled",
                    "Đăng nhập đang tạm khóa",
                    retryable=True,
                )
                response.headers["Retry-After"] = str(retry)
                return response
            valid = isinstance(body, Mapping) and await asyncio.to_thread(
                verify_admin_password,
                str(body.get("password") or ""),
                self.settings.password_hash,
            )
            if not valid:
                retry = self.throttle.record_failure()
                response = self._error(
                    401 if not retry else 429,
                    "bad_credentials" if not retry else "login_throttled",
                    "Mật khẩu không đúng" if not retry else "Đăng nhập đang tạm khóa",
                    retryable=bool(retry),
                )
                if retry:
                    response.headers["Retry-After"] = str(retry)
                return response
            self.throttle.reset()
            session_id = secrets.token_urlsafe(32)
            session = _AdminSession(
                csrf=secrets.token_urlsafe(24),
                expires_at=float(self.clock()) + self.settings.session_ttl_seconds,
            )
            self.sessions[session_id] = session
            response = web.json_response(
                {"success": True, "csrf": session.csrf},
                headers={"Cache-Control": "no-store"},
            )
            response.set_cookie(
                self.COOKIE_NAME,
                self.signer.sign(session_id),
                httponly=True,
                secure=True,
                samesite="Strict",
                path="/admin",
                max_age=self.settings.session_ttl_seconds,
            )
            self._audit("login")
            return response

    async def _session_route(self, request: Any):
        from aiohttp import web

        return web.json_response(
            {"csrf": request[self._session_key].csrf},
            headers={"Cache-Control": "no-store"},
        )

    async def _logout(self, request: Any):
        from aiohttp import web

        self.sessions.pop(request[self._session_id_key], None)
        response = web.json_response(
            {"success": True},
            headers={"Cache-Control": "no-store"},
        )
        response.set_cookie(
            self.COOKIE_NAME,
            "",
            httponly=True,
            secure=True,
            samesite="Strict",
            path="/admin",
            max_age=0,
        )
        self._audit("logout")
        return response

    async def _bridge_json(
        self,
        method: str,
        path: str,
        *,
        payload: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> Any:
        if self.bridge is None:
            return {"error": "bridge is unavailable", "outcome": "failed"}
        try:
            result = self.bridge.request(
                method,
                path,
                payload=payload,
                params=params,
            )
            if inspect.isawaitable(result):
                result = await result
            return redact_value(result)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return {
                "error": redact_text(str(exc)) or "bridge request failed",
                "outcome": "unknown",
            }

    @staticmethod
    def _result_value(value: Any) -> Any:
        if isinstance(value, Mapping) and "result" in value:
            return value.get("result")
        return value

    @classmethod
    def _result_items(cls, value: Any) -> list[Any]:
        selected = cls._result_value(value)
        if isinstance(selected, list):
            return selected
        if isinstance(selected, Mapping):
            for key in (
                "items",
                "friends",
                "groups",
                "members",
                "currentMems",
                "memberIds",
            ):
                candidate = selected.get(key)
                if isinstance(candidate, list):
                    return candidate
                if isinstance(candidate, Mapping):
                    return list(candidate.values())
        return []

    @staticmethod
    def _bridge_failed(value: Any) -> bool:
        return isinstance(value, Mapping) and (
            bool(value.get("error"))
            or str(value.get("outcome") or "").lower() in {"failed", "unknown"}
        )

    def _contact_response(
        self,
        cache_key: str,
        items: list[dict[str, Any]],
        bridge_result: Any,
    ) -> dict[str, Any]:
        if not self._bridge_failed(bridge_result):
            snapshot = [dict(item) for item in items]
            self._contact_cache[cache_key] = snapshot
            return {"items": snapshot, "bridge": bridge_result}
        cached = self._contact_cache.get(cache_key)
        response: dict[str, Any] = {
            "items": [dict(item) for item in (cached or [])],
            "bridge": bridge_result,
            "stale": True,
        }
        if isinstance(bridge_result, Mapping) and bridge_result.get("error"):
            response["error"] = redact_text(str(bridge_result["error"]))
        return response

    @staticmethod
    def _person(item: Any) -> dict[str, Any] | None:
        if not isinstance(item, Mapping):
            value = str(item or "").strip()
            return {"id": value, "name": value} if value else None
        identifier = str(
            item.get("id")
            or item.get("userId")
            or item.get("uid")
            or ""
        ).strip()
        if not identifier:
            return None
        name = str(
            item.get("name")
            or item.get("displayName")
            or item.get("dName")
            or item.get("zaloName")
            or item.get("username")
            or identifier
        )
        result = dict(item)
        result["id"] = identifier
        result["name"] = name
        return result

    @staticmethod
    def _member_token(item: Any) -> str:
        if isinstance(item, Mapping):
            for key in ("id", "userId", "uid", "memberId"):
                value = item.get(key)
                if value is not None and str(value).strip():
                    return str(value).strip()
            return ""
        return "" if item is None else str(item).strip()

    @staticmethod
    def _member_name(item: Any) -> str:
        if not isinstance(item, Mapping):
            return ""
        for key in ("displayName", "zaloName", "name", "dName"):
            value = item.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""

    @staticmethod
    def _strip_member_version(identifier: str) -> str:
        base, separator, version = identifier.rpartition("_")
        if separator and base and version.isdigit():
            return base
        return identifier

    @classmethod
    def _keyed_member_values(cls, value: Any) -> list[Any]:
        if isinstance(value, list):
            return value
        if not isinstance(value, Mapping) or cls._bridge_failed(value):
            return []
        items: list[Any] = []
        for key, member in value.items():
            if isinstance(member, Mapping):
                candidate = dict(member)
                candidate.setdefault("id", key)
            else:
                candidate = {"id": key, "name": member}
            items.append(candidate)
        return items

    @classmethod
    def _normalize_group_members(
        cls,
        raw_items: list[Any],
        profiles: Any = None,
        *,
        strip_versions: bool = False,
    ) -> list[dict[str, str]]:
        profile_by_member: dict[str, Mapping[str, Any]] = {}
        if isinstance(profiles, Mapping) and not cls._bridge_failed(profiles):
            profile_entries = list(profiles.items())
        elif isinstance(profiles, list):
            profile_entries = [("", profile) for profile in profiles]
        else:
            profile_entries = []
        for key, profile in profile_entries:
            if not isinstance(profile, Mapping) or cls._bridge_failed(profile):
                continue
            for candidate in (
                key,
                profile.get("id"),
                profile.get("userId"),
                profile.get("uid"),
            ):
                token = "" if candidate is None else str(candidate).strip()
                if not token:
                    continue
                profile_by_member[token] = profile
                profile_by_member[cls._strip_member_version(token)] = profile

        items: list[dict[str, str]] = []
        seen: set[str] = set()
        for member in raw_items:
            if isinstance(member, Mapping) and cls._bridge_failed(member):
                continue
            token = cls._member_token(member)
            identifier = (
                cls._strip_member_version(token) if strip_versions else token
            )
            if not identifier or identifier in seen:
                continue
            seen.add(identifier)
            profile = profile_by_member.get(token) or profile_by_member.get(identifier)
            items.append(
                {
                    "id": identifier,
                    "name": (
                        cls._member_name(profile)
                        or cls._member_name(member)
                        or identifier
                    ),
                }
            )
        return items

    @staticmethod
    def _group(item: Any) -> dict[str, Any] | None:
        if not isinstance(item, Mapping):
            value = str(item or "").strip()
            return {"id": value, "name": f"(group {value})"} if value else None
        identifier = str(
            item.get("id")
            or item.get("groupId")
            or item.get("threadId")
            or ""
        ).strip()
        if not identifier:
            return None
        result = dict(item)
        result["id"] = identifier
        result["name"] = str(
            item.get("name")
            or item.get("groupName")
            or f"(group {identifier})"
        )
        if "memberCount" not in result and item.get("totalMember") is not None:
            result["memberCount"] = item.get("totalMember")
        return result

    @classmethod
    def _profile(cls, value: Any, own_id: str) -> dict[str, Any] | None:
        selected = cls._result_value(value)
        if not isinstance(selected, Mapping):
            return None
        profiles = selected.get("changed_profiles")
        if isinstance(profiles, Mapping):
            candidate = profiles.get(own_id)
            if candidate is None and profiles:
                candidate = next(iter(profiles.values()))
            return cls._person(candidate)
        return cls._person(selected)

    async def _overview(self, _request: Any):
        from aiohttp import web

        status = await self.admin.action(
            "status",
            requester=WEB_ADMIN_REQUESTER,
        )
        rendered_status = (
            dict(status) if isinstance(status, Mapping) else {"status": status}
        )
        health = await self._bridge_json("GET", "/health")
        policy = await self._bridge_json("GET", "/policy")
        contacts = await self._bridge_json("GET", "/contacts")
        contact_value = self._result_value(contacts)
        contact_friends = (
            contact_value.get("friends")
            if isinstance(contact_value, Mapping)
            and isinstance(contact_value.get("friends"), list)
            else None
        )
        contact_groups = (
            contact_value.get("groups")
            if isinstance(contact_value, Mapping)
            and isinstance(contact_value.get("groups"), list)
            else None
        )
        friends = (
            contact_friends
            if contact_friends is not None
            else self._result_items(await self._bridge_json("GET", "/friends"))
        )
        if contact_groups is not None:
            groups = contact_groups
        else:
            raw_groups = self._result_value(
                await self._bridge_json("GET", "/groups")
            )
            groups = (
                list(raw_groups.get("gridVerMap", {}).keys())
                if isinstance(raw_groups, Mapping)
                and isinstance(raw_groups.get("gridVerMap"), Mapping)
                else self._result_items(raw_groups)
            )
        bot = rendered_status.get("bot")
        if not isinstance(bot, Mapping) or not bot.get("name"):
            own_id = health.get("ownId") if isinstance(health, Mapping) else None
            if own_id:
                profile = await self._bridge_json(
                    "GET",
                    "/chat-info",
                    params={"threadId": str(own_id), "threadType": "user"},
                )
                resolved = self._profile(profile, str(own_id))
                if resolved is not None:
                    bot = resolved
        access: Mapping[str, Any] = {}
        try:
            access = self.admin.get_access_config(
                requester=WEB_ADMIN_REQUESTER
            )
        except CompanyConfigError:
            pass
        latest_page = self.store.list_conversations(limit=1, offset=0)
        latest_message_at = (
            latest_page["items"][0].get("last_message_at")
            if latest_page.get("items")
            else None
        )
        recent_activity = self.store.page_tool_activity(limit=10, offset=0)[
            "items"
        ]
        result = {
            **rendered_status,
            "bot": redact_value(bot or {}),
            "bridge": health,
            "policy": policy,
            "history": self.store.stats(),
            "latest_message_at": latest_message_at,
            "recent_activity": recent_activity,
            "counts": {
                "friends": len(friends),
                "groups": len(groups),
                "allowed_users": len(access.get("allowed_users", [])),
                "admin_users": len(access.get("admin_users", [])),
                "allowed_groups": len(access.get("allowed_groups", [])),
            },
        }
        return web.json_response(
            redact_value(result),
            headers={"Cache-Control": "no-store"},
        )

    async def _access(self, _request: Any):
        from aiohttp import web

        try:
            result = self.admin.get_access_config(
                requester=WEB_ADMIN_REQUESTER
            )
        except CompanyConfigError as exc:
            return self._error(503, "config_unavailable", str(exc), retryable=True)
        return web.json_response(
            redact_value(result),
            headers={"Cache-Control": "no-store"},
        )

    async def _friends(self, _request: Any):
        from aiohttp import web

        contacts = await self._bridge_json("GET", "/contacts")
        selected = self._result_value(contacts)
        raw_items = (
            selected.get("friends")
            if isinstance(selected, Mapping)
            and isinstance(selected.get("friends"), list)
            else None
        )
        result = contacts
        if raw_items is None:
            result = await self._bridge_json("GET", "/friends")
            raw_items = self._result_items(result)
        items = [self._person(item) for item in raw_items]
        normalized = [item for item in items if item is not None]
        return web.json_response(
            self._contact_response("friends", normalized, result),
            headers={"Cache-Control": "no-store"},
        )

    async def _groups(self, _request: Any):
        from aiohttp import web

        contacts = await self._bridge_json("GET", "/contacts")
        selected = self._result_value(contacts)
        raw_items = (
            selected.get("groups")
            if isinstance(selected, Mapping)
            and isinstance(selected.get("groups"), list)
            else None
        )
        result = contacts
        if raw_items is None:
            result = await self._bridge_json("GET", "/groups")
            direct = self._result_value(result)
            if isinstance(direct, Mapping) and isinstance(
                direct.get("gridVerMap"), Mapping
            ):
                raw_items = [
                    {"id": str(group_id), "name": f"(group {group_id})"}
                    for group_id in direct["gridVerMap"]
                ]
            else:
                raw_items = self._result_items(result)
        items = [self._group(item) for item in raw_items]
        normalized = [item for item in items if item is not None]
        return web.json_response(
            self._contact_response("groups", normalized, result),
            headers={"Cache-Control": "no-store"},
        )

    async def _group_members(self, request: Any):
        from aiohttp import web

        group_id = str(request.match_info.get("group_id") or "").strip()
        if not group_id:
            return self._error(400, "group_required", "Group ID là bắt buộc")
        result = await self._bridge_json(
            "GET",
            "/group-members",
            params={"groupId": group_id},
        )
        selected = self._result_value(result)
        failed = self._bridge_failed(result) or self._bridge_failed(selected)
        raw_items: list[Any] = []
        profiles: Any = None
        if not failed:
            if isinstance(selected, list):
                raw_items = selected
            elif isinstance(selected, Mapping):
                raw_items = self._keyed_member_values(selected.get("members"))
                profiles = selected.get("profiles")
                if not raw_items:
                    raw_items = self._keyed_member_values(profiles)
        items = self._normalize_group_members(raw_items, profiles)

        if not items:
            result = await self._bridge_json(
                "GET",
                "/chat-info",
                params={"threadId": group_id, "threadType": "group"},
            )
            selected = self._result_value(result)
            failed = self._bridge_failed(result) or self._bridge_failed(selected)
            raw_items = []
            profiles = None
            strip_versions = False
            if not failed:
                if isinstance(selected, list):
                    raw_items = selected
                elif isinstance(selected, Mapping):
                    grid = selected.get("gridInfoMap")
                    group = (
                        grid.get(group_id) if isinstance(grid, Mapping) else selected
                    )
                    if isinstance(group, Mapping) and not self._bridge_failed(group):
                        profiles = group.get("profiles")
                        for key in (
                            "currentMems",
                            "members",
                            "memberIds",
                            "memVerList",
                        ):
                            candidate = self._keyed_member_values(group.get(key))
                            if candidate:
                                raw_items = candidate
                                strip_versions = key == "memVerList"
                                break
                        if not raw_items:
                            raw_items = self._keyed_member_values(profiles)
            items = self._normalize_group_members(
                raw_items,
                profiles,
                strip_versions=strip_versions,
            )
        response = self._contact_response(f"members:{group_id}", items, result)
        response["group_id"] = group_id
        return web.json_response(
            response,
            headers={"Cache-Control": "no-store"},
        )

    async def _apply_access(self, request: Any):
        from aiohttp import web

        try:
            body = await request.json()
        except Exception:
            return self._error(400, "invalid_json", "Dữ liệu cấu hình không hợp lệ")
        if not isinstance(body, Mapping):
            return self._error(400, "invalid_body", "Dữ liệu cấu hình phải là object")
        try:
            result = await self.admin.apply_access_config(
                allowed_users=body.get("allowed_users"),
                admin_users=body.get("admin_users"),
                allowed_groups=body.get("allowed_groups"),
                expected_fingerprint=str(body.get("fingerprint") or ""),
                requester=WEB_ADMIN_REQUESTER,
            )
        except CompanyConfigConflict as exc:
            self._audit("apply_access_config", status="failed", error_text=str(exc))
            return self._error(
                409,
                "config_conflict",
                "Cấu hình đã thay đổi; hãy tải lại trước khi lưu",
                retryable=True,
            )
        except (CompanyConfigError, TypeError, ValueError) as exc:
            self._audit("apply_access_config", status="failed", error_text=str(exc))
            return self._error(
                400,
                "invalid_config",
                self._invalid_config_message(exc),
            )
        except Exception as exc:
            self._audit("apply_access_config", status="failed", error_text=str(exc))
            return self._error(
                500,
                "apply_failed",
                "Không thể áp dụng cấu hình; trạng thái cũ đã được giữ",
                retryable=False,
            )
        self._audit("apply_access_config")
        return web.json_response(
            redact_value(result),
            headers={"Cache-Control": "no-store"},
        )

    @staticmethod
    def _query_int(
        request: Any,
        name: str,
        default: int,
    ) -> int:
        try:
            return int(request.query.get(name, default))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be an integer") from exc

    @staticmethod
    def _web_history_filters(data: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: data[key]
            for key in (
                "thread_type",
                "thread_id",
                "sender_id",
                "query",
                "since",
                "until",
            )
            if data.get(key) is not None and str(data.get(key)).strip()
        }

    async def _conversations(self, request: Any):
        from aiohttp import web

        try:
            result = self.store.list_conversations(
                thread_type=request.query.get("thread_type"),
                query=request.query.get("query"),
                limit=self._query_int(request, "limit", 50),
                offset=self._query_int(request, "offset", 0),
            )
        except (TypeError, ValueError):
            return self._error(
                400,
                "invalid_page",
                "Tham số phân trang không hợp lệ",
            )
        return web.json_response(
            redact_value(result),
            headers={"Cache-Control": "no-store"},
        )

    async def _conversation(self, request: Any):
        from aiohttp import web

        try:
            conversation_id = int(request.match_info["conversation_id"])
            conversation = self.store.get_conversation(conversation_id)
            if conversation is None:
                return self._error(
                    404,
                    "conversation_not_found",
                    "Không tìm thấy hội thoại",
                )
            result = self.store.page_messages(
                conversation_id,
                sender_id=request.query.get("sender_id"),
                since=request.query.get("since"),
                until=request.query.get("until"),
                query=request.query.get("query"),
                limit=self._query_int(request, "limit", 100),
                offset=self._query_int(request, "offset", 0),
            )
        except (TypeError, ValueError):
            return self._error(
                400,
                "invalid_page",
                "Bộ lọc hoặc phân trang hội thoại không hợp lệ",
            )
        return web.json_response(
            {**redact_value(result), "conversation": redact_value(conversation)},
            headers={"Cache-Control": "no-store"},
        )

    async def _history_search(self, request: Any):
        from aiohttp import web

        try:
            result = self.store.search_messages(
                request.query.get("query", ""),
                requester_id="web-admin",
                is_admin=True,
                allowed_groups=set(),
                thread_type=request.query.get("thread_type"),
                thread_id=request.query.get("thread_id"),
                limit=self._query_int(request, "limit", 50),
            )
        except (TypeError, ValueError):
            return self._error(
                400,
                "invalid_search",
                "Bộ lọc tìm kiếm không hợp lệ",
            )
        return web.json_response(
            redact_value({"items": result}),
            headers={"Cache-Control": "no-store"},
        )

    async def _history_export(self, request: Any):
        from aiohttp import web

        try:
            body = await request.json()
            if not isinstance(body, Mapping):
                raise ValueError("export filters must be an object")
            result = self.admin.web_history_export(
                requester=WEB_ADMIN_REQUESTER,
                **self._web_history_filters(body),
            )
            path = Path(result["path"]).resolve(strict=True)
            root = self.export_root.resolve(strict=False)
            path.relative_to(root)
        except (CompanyConfigError, OSError, TypeError, ValueError) as exc:
            message = redact_text(str(exc)) or "Không thể xuất lịch sử"
            self._audit("history_export", status="failed", error_text=message)
            return self._error(400, "history_export_failed", message)
        self._audit(
            "history_export",
            count=int(result.get("messages", 0)),
        )
        response = web.FileResponse(path)
        response.headers["Content-Disposition"] = (
            f'attachment; filename="{path.name}"'
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    async def _history_delete(self, request: Any):
        from aiohttp import web

        try:
            body = await request.json()
        except Exception:
            return self._error(400, "invalid_json", "Dữ liệu xóa không hợp lệ")
        if not isinstance(body, Mapping) or body.get("confirm") is not True:
            return self._error(
                400,
                "confirmation_required",
                "Cần xác nhận thao tác xóa",
            )
        try:
            result = self.admin.history_delete(
                requester=WEB_ADMIN_REQUESTER,
                **self._web_history_filters(body),
            )
        except (CompanyConfigError, TypeError, ValueError) as exc:
            message = redact_text(str(exc)) or "Không thể xóa lịch sử"
            self._audit("history_delete", status="failed", error_text=message)
            return self._error(400, "history_delete_failed", message)
        except Exception as exc:
            message = redact_text(str(exc)) or "Không thể xóa lịch sử"
            self._audit("history_delete", status="unknown", error_text=message)
            return self._error(
                500,
                "history_delete_unknown",
                message,
                retryable=False,
            )
        self._audit("history_delete", count=int(result.get("messages", 0)))
        return web.json_response(
            redact_value(result),
            headers={"Cache-Control": "no-store"},
        )

    async def _attachment(self, request: Any):
        from aiohttp import web

        try:
            attachment_id = int(request.match_info["attachment_id"])
        except (TypeError, ValueError):
            return self._error(404, "attachment_not_found", "Không tìm thấy file")
        item = self.store.get_attachment(
            attachment_id,
            requester_id="web-admin",
            is_admin=True,
            allowed_groups=set(),
        )
        if not item or not item.get("local_path"):
            return self._error(404, "attachment_not_found", "Không tìm thấy file")
        try:
            target = Path(str(item["local_path"])).resolve(strict=True)
            root = self.store.media_root.resolve(strict=False)
            target.relative_to(root)
        except (OSError, ValueError):
            return self._error(404, "attachment_not_found", "Không tìm thấy file")
        if not target.is_file():
            return self._error(404, "attachment_not_found", "Không tìm thấy file")
        self._audit("attachment_download", target_id=item["id"])
        response = web.FileResponse(target)
        response.headers["Content-Type"] = "application/octet-stream"
        response.headers["Content-Disposition"] = "attachment"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    async def _activity(self, request: Any):
        from aiohttp import web

        try:
            result = self.store.page_tool_activity(
                requester_id=request.query.get("requester_id"),
                tool_name=request.query.get("tool_name"),
                status=request.query.get("status"),
                thread_type=request.query.get("thread_type"),
                thread_id=request.query.get("thread_id"),
                since=request.query.get("since"),
                until=request.query.get("until"),
                limit=self._query_int(request, "limit", 100),
                offset=self._query_int(request, "offset", 0),
            )
        except (TypeError, ValueError):
            return self._error(
                400,
                "invalid_page",
                "Bộ lọc hoặc phân trang hoạt động không hợp lệ",
            )
        return web.json_response(
            redact_value(result),
            headers={"Cache-Control": "no-store"},
        )

    async def _system(self, _request: Any):
        from aiohttp import web

        status = await self.admin.action(
            "status",
            requester=WEB_ADMIN_REQUESTER,
        )
        rendered = (
            dict(status) if isinstance(status, Mapping) else {"status": status}
        )
        health = await self._bridge_json("GET", "/health")
        bot = rendered.get("bot")
        if not isinstance(bot, Mapping) or not bot.get("name"):
            own_id = health.get("ownId") if isinstance(health, Mapping) else None
            if own_id:
                profile = await self._bridge_json(
                    "GET",
                    "/chat-info",
                    params={"threadId": str(own_id), "threadType": "user"},
                )
                resolved = self._profile(profile, str(own_id))
                if resolved is not None:
                    bot = resolved
        result = {
            **rendered,
            "bot": redact_value(bot or {}),
            "bridge": health,
            "policy": await self._bridge_json("GET", "/policy"),
            "qr": await self._bridge_json("GET", "/qr"),
            "provider": rendered.get("provider", "unknown"),
            "model": rendered.get("model", "unknown"),
        }
        return web.json_response(
            redact_value(result),
            headers={"Cache-Control": "no-store"},
        )

    def _track_task(self, task: asyncio.Task[Any]) -> asyncio.Task[Any]:
        self._background_tasks.add(task)

        def finished(completed: asyncio.Task[Any]) -> None:
            self._background_tasks.discard(completed)
            try:
                completed.result()
            except (asyncio.CancelledError, Exception):
                pass

        task.add_done_callback(finished)
        return task

    async def _run_admin_action(self, action: str, **args: Any) -> Any:
        try:
            return await self.admin.action(
                action,
                requester=WEB_ADMIN_REQUESTER,
                **args,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            return None

    async def _qr(self, _request: Any):
        from aiohttp import web

        if self._relogin_task is None or self._relogin_task.done():
            self._relogin_task = self._track_task(
                asyncio.create_task(
                    self._run_admin_action("login_qr", forceQR=True)
                )
            )
            self._audit("qr", status="unknown")
        return web.json_response(
            {"accepted": True, "pending": not self._relogin_task.done()},
            status=202,
            headers={"Cache-Control": "no-store"},
        )

    async def _qr_png(self, _request: Any):
        from aiohttp import web

        if self.bridge is None or not hasattr(self.bridge, "request_bytes"):
            return self._error(
                404,
                "qr_unavailable",
                "QR chưa sẵn sàng",
                retryable=True,
            )
        try:
            result = self.bridge.request_bytes("/qr.png")
            if inspect.isawaitable(result):
                result = await result
            payload, content_type = result
            if not isinstance(payload, (bytes, bytearray)):
                raise ValueError("QR payload is invalid")
            if not str(content_type).lower().startswith("image/png"):
                raise ValueError("QR response is not PNG")
            if len(payload) > 2 * 1024 * 1024:
                raise ValueError("QR response exceeds 2 MiB")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return self._error(
                404,
                "qr_unavailable",
                redact_text(str(exc)) or "QR chưa sẵn sàng",
                retryable=True,
            )
        return web.Response(
            body=bytes(payload),
            content_type="image/png",
            headers={"Cache-Control": "no-store"},
        )

    async def _reconnect(self, _request: Any):
        from aiohttp import web

        if self._relogin_task is None or self._relogin_task.done():
            self._relogin_task = self._track_task(
                asyncio.create_task(
                    self._run_admin_action("reconnect", forceQR=False)
                )
            )
            self._audit("reconnect", status="unknown")
        return web.json_response(
            {"accepted": True, "pending": not self._relogin_task.done()},
            status=202,
            headers={"Cache-Control": "no-store"},
        )

    async def _restart(self, request: Any):
        from aiohttp import web

        try:
            body = await request.json()
        except Exception:
            return self._error(400, "invalid_json", "Dữ liệu restart không hợp lệ")
        target = str(body.get("target") or "") if isinstance(body, Mapping) else ""
        if target not in {"gateway", "bridge"}:
            return self._error(
                400,
                "invalid_target",
                "Target phải là gateway hoặc bridge",
            )
        task = self._restart_tasks.get(target)
        now = asyncio.get_running_loop().time()
        cooldown_elapsed = (
            now - self._restart_accepted_at.get(target, float("-inf"))
            >= self.RESTART_COOLDOWN_SECONDS
        )
        if (task is None or task.done()) and cooldown_elapsed:
            async def restart_once() -> None:
                await asyncio.sleep(0.05)
                await self._run_admin_action("restart", target=target)

            task = self._track_task(asyncio.create_task(restart_once()))
            self._restart_tasks[target] = task
            self._restart_accepted_at[target] = now

            def clear_restart(completed: asyncio.Task[Any]) -> None:
                if self._restart_tasks.get(target) is completed:
                    self._restart_tasks.pop(target, None)

            task.add_done_callback(clear_restart)
            self._audit("restart", status="unknown", target_id=target)
        return web.json_response(
            {"accepted": True, "target": target},
            status=202,
            headers={"Cache-Control": "no-store"},
        )

    async def _logs(self, request: Any):
        from aiohttp import web

        try:
            lines = max(1, min(self._query_int(request, "lines", 100), 500))
            result = await self.admin.action(
                "show_logs",
                requester=WEB_ADMIN_REQUESTER,
                lines=lines,
            )
        except (TypeError, ValueError):
            return self._error(
                400,
                "invalid_lines",
                "Số dòng log không hợp lệ",
            )
        self._audit("show_logs", count=lines)
        return web.json_response(
            redact_value(result),
            headers={"Cache-Control": "no-store"},
        )

    async def start(self) -> bool:
        async with self._lifecycle_lock:
            if not self.settings.enabled or self._runner is not None:
                return False
            if self.settings.host != "127.0.0.1":
                raise AdminWebSettingsError(
                    "ZALO_ADMIN_WEB_HOST must be 127.0.0.1"
                )
            from aiohttp import web

            runner = web.AppRunner(self.create_application(), access_log=None)
            try:
                await runner.setup()
                site = web.TCPSite(
                    runner,
                    self.settings.host,
                    self.settings.port,
                )
                await site.start()
            except BaseException:
                await runner.cleanup()
                raise
            self._runner = runner
            self._site = site
            return True

    async def stop(self) -> None:
        async with self._lifecycle_lock:
            self.sessions.clear()
            tasks = list(self._background_tasks)
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            self._background_tasks.clear()
            self._relogin_task = None
            self._restart_tasks.clear()
            self._restart_accepted_at.clear()
            runner = self._runner
            self._runner = None
            self._site = None
            if runner is not None:
                await runner.cleanup()
