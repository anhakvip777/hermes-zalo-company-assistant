"""Hermes tools exposed by the company Zalo plugin."""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

try:
    from .admin import AdminDenied, AdminService
    from .company_config import CompanyConfig
    from .history_store import HistoryStore, redact_text, redact_value
    from .request_context import MissingRequesterContext, Requester, current_requester
except ImportError:  # Hermes may also load adapter.py as a top-level module.
    from admin import AdminDenied, AdminService
    from company_config import CompanyConfig
    from history_store import HistoryStore, redact_text, redact_value
    from request_context import MissingRequesterContext, Requester, current_requester

try:  # Hermes is optional while the plugin's unit tests run.
    from tools.registry import tool_error, tool_result
except Exception:  # pragma: no cover - exercised only outside Hermes
    def tool_error(message: Any, **extra: Any) -> str:
        return json.dumps({"error": str(message), **extra}, ensure_ascii=False)

    def tool_result(data: Any = None, **kwargs: Any) -> str:
        return json.dumps(data if data is not None else kwargs, ensure_ascii=False)


_MEMORY_MUTATIONS = {
    "add",
    "append",
    "delete",
    "edit",
    "remove",
    "replace",
    "set",
    "update",
    "write",
}
_HISTORY_MUTATIONS = {
    "delete_history",
    "export_history",
    "history_delete",
    "history_export",
}
_READ_PATH_TOOL_NAMES = {"read_file"}
_MUTATING_PATH_TOOL_NAMES = {"delete_file", "edit_file", "remove_file", "write_file"}
_PATH_TOOL_NAMES = _READ_PATH_TOOL_NAMES | _MUTATING_PATH_TOOL_NAMES
_CODE_TOOL_NAMES = {"execute_code", "python", "terminal"}
_TARGET_KEYS = {"dest", "destination", "file", "file_path", "filename", "path", "target"}
_CODE_KEYS = {"code", "command", "script", "source"}
_WORKDIR_KEYS = {"cwd", "workdir", "working_dir", "working_directory"}
_PATCH_TARGET_RE = re.compile(
    r"(?im)^\s*(?:\*{3}\s+(?:add|delete|update)\s+file:|---|\+\+\+)\s*(?P<path>\S.*)$"
)
_HISTORY_API_RE = re.compile(r"(?i)/admin/api/history/(?:delete|export)(?:\b|[/?#])")
_HISTORY_COMMAND_RE = re.compile(
    r"(?im)(?:^|[;&|]\s*|\n\s*)(?:sudo\s+)?(?:[^\s;&|]*[\\/])?"
    r"(?:delete[_-]?history|export[_-]?history|history[_-]?(?:delete|export))"
    r"(?=$|\s|[;&|])"
)
_HISTORY_ADMIN_COMMAND_RE = re.compile(
    r"(?i)\b(?:zalo[_-]admin)\b[^\r\n;&|]*\b(?:delete[_-]?history|"
    r"export[_-]?history|history[_-]?(?:delete|export))\b"
)
_SYSTEMCTL_RE = re.compile(
    r"(?i)\bsystemctl\b[^\r\n;&|]*\b(?:disable|enable|kill|mask|reload|restart|start|stop|"
    r"try-restart|unmask)\b[^\r\n;&|]*\b(?:hermes-gateway|"
    r"hermes-zalo-company-bridge)(?:\.service)?\b"
)
_SERVICE_RE = re.compile(
    r"(?i)\bservice\s+(?:hermes-gateway|hermes-zalo-company-bridge)(?:\.service)?\s+"
    r"(?:reload|restart|start|stop)\b"
)
_HERMES_GATEWAY_RE = re.compile(
    r"(?i)\bhermes(?:\.exe)?\s+gateway\s+(?:restart|start|stop)\b"
)
_POWERSHELL_ENV_ENUM_RE = re.compile(
    r"(?im)\b(?:get-childitem|gci|dir|ls)\b[^\r\n;&|]*\benv:"
    r"(?:[\\/]*\*)?(?=$|[\s;&|])"
)
_DOTNET_ENV_ENUM_RE = re.compile(
    r"(?i)\[\s*(?:system\s*\.\s*)?environment\s*\]\s*::\s*"
    r"getenvironmentvariables\s*\("
)
_POSIX_ENV_ENUM_RE = re.compile(
    r"(?im)(?:^|[;&|]{1,2}[ \t]*|\n[ \t]*)(?:sudo[ \t]+)?"
    r"(?:[^\s;&|]*[\\/])?(?:printenv|env)(?=[ \t]*(?:-|$|[;&|]))"
)
_PYTHON_ENV_ACCESS_RE = re.compile(r"(?i)\bos\s*\.\s*environ\b")
_RELATIVE_MEMORY_TEXT_RE = re.compile(
    r"(?i)(?<![a-z0-9_.\\/\-])(?:\.?[\\/])?"
    r"(?:memories[\\/]|memory\.md\b|user\.md\b)"
)
_SECRET_ENV_WORD_RE = re.compile(r"(?<![A-Z0-9_])[A-Z][A-Z0-9_]{2,}(?![A-Z0-9_])")
_GUARD_MESSAGE = "Thao tác này cần quản trị viên thực hiện."


def _safe_json(value: Any) -> str:
    return json.dumps(redact_value(value), ensure_ascii=False, default=str)


def _tool_leaf(tool_name: str) -> str:
    normalized = str(tool_name or "").strip().lower().replace("-", "_")
    return re.split(r"[.:/]", normalized)[-1]


def _mapping_action(args: Any) -> str:
    if isinstance(args, Mapping):
        for key in ("action", "operation", "mode"):
            value = args.get(key)
            if value is not None:
                return str(value).strip().lower().replace("-", "_")
    return ""


def _expand_env_references(value: str) -> str:
    text = str(value)

    def replace(match: re.Match[str]) -> str:
        name = next(group for group in match.groups() if group is not None)
        return os.getenv(name, match.group(0))

    text = re.sub(r"\$env:([A-Za-z_][A-Za-z0-9_]*)", replace, text, flags=re.I)
    text = re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", replace, text)
    text = re.sub(r"%([A-Za-z_][A-Za-z0-9_]*)%", replace, text)
    text = re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)", replace, text)
    return os.path.expandvars(text)


def _normalized_path_text(value: str) -> str:
    return str(value).replace("\\", "/").rstrip("/").casefold()


def _path_keys(value: str | Path) -> frozenset[str]:
    raw = _expand_env_references(str(value)).strip().strip("'\"")
    if not raw:
        return frozenset()
    expanded = os.path.expanduser(raw)
    keys = {_normalized_path_text(raw), _normalized_path_text(expanded)}
    try:
        keys.add(_normalized_path_text(Path(expanded).resolve(strict=False)))
    except (OSError, RuntimeError, ValueError):
        pass
    return frozenset(key for key in keys if key)


def _path_is_protected(
    candidate: str | Path,
    protected: list[tuple[frozenset[str], bool]],
) -> bool:
    for candidate_key in _path_keys(candidate):
        for protected_keys, is_root in protected:
            for protected_key in protected_keys:
                if candidate_key == protected_key:
                    return True
                if is_root and candidate_key.startswith(protected_key + "/"):
                    return True
    return False


def _path_is_exact(candidate: str | Path, expected: str | Path) -> bool:
    return not _path_keys(candidate).isdisjoint(_path_keys(expected))


def _is_relative_shared_memory_path(candidate: str | Path) -> bool:
    raw = _expand_env_references(str(candidate)).strip().strip("'\"")
    if not raw or Path(os.path.expanduser(raw)).is_absolute():
        return False
    normalized = raw.replace("\\", "/").casefold()
    while normalized.startswith(("./", "../")):
        normalized = normalized.split("/", 1)[1]
    return normalized in {"memory.md", "user.md"} or normalized.startswith(
        "memories/"
    )


def _text_mentions_protected_path(
    value: str,
    protected: list[tuple[frozenset[str], bool]],
) -> bool:
    text = _normalized_path_text(_expand_env_references(value))
    path_chars = frozenset(
        "abcdefghijklmnopqrstuvwxyz0123456789_.-"
    )
    for protected_keys, is_root in protected:
        for protected_key in protected_keys:
            start = 0
            while True:
                index = text.find(protected_key, start)
                if index < 0:
                    break
                end = index + len(protected_key)
                left_ok = index == 0 or text[index - 1] not in path_chars
                if end == len(text):
                    right_ok = True
                elif is_root and text[end] == "/":
                    right_ok = True
                else:
                    right_ok = text[end] not in path_chars and text[end] != "/"
                if left_ok and right_ok:
                    return True
                start = index + 1
    return False


def _target_values(args: Any) -> list[str]:
    if isinstance(args, (str, Path)):
        return [str(args)]
    if not isinstance(args, Mapping):
        return []
    targets: list[str] = []
    for key, value in args.items():
        if str(key).strip().lower() not in _TARGET_KEYS:
            continue
        if isinstance(value, (str, Path)):
            targets.append(str(value))
        elif isinstance(value, (list, tuple)):
            targets.extend(str(item) for item in value if isinstance(item, (str, Path)))
    return targets


def _patch_targets(args: Any) -> list[str]:
    targets = _target_values(args)
    patch_values: list[str] = []
    if isinstance(args, str):
        patch_values.append(args)
    elif isinstance(args, Mapping):
        for key in ("diff", "patch"):
            if isinstance(args.get(key), str):
                patch_values.append(str(args[key]))
    for patch_text in patch_values:
        for match in _PATCH_TARGET_RE.finditer(patch_text):
            target = match.group("path").split("\t", 1)[0].strip().strip("'\"")
            if target in {"/dev/null", "NUL"}:
                continue
            if target.startswith(("a/", "b/")):
                target = target[2:]
            targets.append(target)
    return targets


def _command_text(args: Any) -> str:
    if isinstance(args, str):
        return args
    if not isinstance(args, Mapping):
        return ""
    return "\n".join(
        str(value)
        for key, value in args.items()
        if str(key).strip().lower() in _CODE_KEYS and isinstance(value, str)
    )


def _working_directory_values(args: Any) -> list[str]:
    if not isinstance(args, Mapping):
        return []
    return [
        str(value)
        for key, value in args.items()
        if str(key).strip().lower() in _WORKDIR_KEYS
        and isinstance(value, (str, Path))
    ]


def _mentions_secret_env_name(text: str) -> bool:
    suffixes = (
        "_API_KEY",
        "_APIKEY",
        "_COOKIE",
        "_IMEI",
        "_PASSWORD",
        "_PASSWD",
        "_SECRET",
        "_TOKEN",
    )
    exact = {"API_KEY", "APIKEY", "COOKIE", "IMEI", "PASSWORD", "PASSWD", "SECRET", "TOKEN"}
    return any(
        word in exact or word.endswith(suffixes)
        for word in _SECRET_ENV_WORD_RE.findall(text)
    )


def _requester_from_event(event: Any) -> Requester | None:
    source = getattr(event, "source", None)
    if source is None:
        return None
    chat_type = str(getattr(source, "chat_type", "dm") or "dm").lower()
    thread_type = "group" if chat_type == "group" else "dm"
    requester_id = str(
        getattr(source, "user_id", None)
        or getattr(source, "sender_id", None)
        or getattr(source, "chat_id", "")
    )
    thread_id = str(getattr(source, "chat_id", "") or requester_id)
    if not requester_id or not thread_id:
        return None
    # The adapter sets the authoritative admin flag before dispatch.  A hook
    # must never trust a model-supplied field in event.raw_message.
    is_admin = bool(getattr(event, "zalo_is_admin", False))
    return Requester(
        requester_id=requester_id,
        thread_type=thread_type,
        thread_id=thread_id,
        is_admin=is_admin,
        session_key=f"zalo:{thread_type}:{thread_id}",
    )


class AiohttpBridge:
    """Minimal authenticated REST client used by the tool handlers."""

    def __init__(self, base_url: str, token: str, *, timeout: float = 60.0):
        self.base_url = str(base_url).rstrip("/")
        self.token = str(token)
        self.timeout = float(timeout)

    async def request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        import aiohttp

        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.request(
                    method,
                    self.base_url + path,
                    json=payload,
                    params=params,
                    headers=headers,
                ) as response:
                    body = await response.json(content_type=None)
                    if response.status >= 400:
                        return {"error": redact_text(body.get("error", f"HTTP {response.status}")), "outcome": "failed"}
                    return redact_value(body)
        except (asyncio.TimeoutError, TimeoutError):
            return {"error": "bridge request timed out", "outcome": "unknown"}
        except Exception as exc:
            # A transport failure has no reliable provider outcome.  Do not
            # encourage callers to resend automatically.
            return {"error": redact_text(f"bridge request failed: {exc}"), "outcome": "unknown"}


class ZaloTooling:
    def __init__(
        self,
        *,
        bridge: Any,
        store: HistoryStore,
        config: Any,
        admin: AdminService | None = None,
        memory_path: str | Path | None = None,
        on_config_change: Callable[[CompanyConfig], Any] | None = None,
    ) -> None:
        self.bridge = bridge
        self.store = store
        self.config = config
        self.admin = admin or AdminService(store=store, memory_path=memory_path)
        self.on_config_change = on_config_change
        if self.admin.runtime_config_provider is None:
            self.admin.runtime_config_provider = lambda: self.config
        if self.admin.runtime_config_applier is None:
            self.admin.runtime_config_applier = self._apply_runtime_config

    async def _apply_runtime_config(self, config: CompanyConfig) -> None:
        self.config = config
        if self.on_config_change is not None:
            callback_result = self.on_config_change(config)
            if isinstance(callback_result, Awaitable):
                await callback_result

    def _requester(self) -> Requester:
        # Deliberately ignore requester_id in tool arguments: the bound
        # ContextVar is populated by the adapter and cannot be spoofed by the
        # model.
        return current_requester()

    @staticmethod
    def _activity_thread_type(requester: Requester) -> str:
        return "dm" if requester.thread_type == "user" else requester.thread_type

    async def _bridge_request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> Any:
        result = self.bridge.request(method, path, payload=payload, params=params)
        if isinstance(result, Awaitable):
            result = await result
        return redact_value(result)

    async def zalo(self, args: dict[str, Any], **_: Any) -> str:
        requester = self._requester()
        action = str(args.get("action") or "list").strip().lower()
        method_name = str(args.get("method") or "")
        status = "success"
        error_text = None
        try:
            if action == "list":
                query = str(args.get("query") or "")
                result = await self._bridge_request(
                    "GET",
                    "/api/methods",
                    None,
                    {"query": query} if query else None,
                )
            elif action == "describe":
                if not method_name:
                    raise ValueError("method is required for describe")
                result = await self._bridge_request("GET", f"/api/methods/{method_name}", None)
            elif action == "call":
                if not method_name:
                    raise ValueError("method is required for call")
                payload: dict[str, Any] = {}
                if isinstance(args.get("params"), Mapping):
                    payload["params"] = dict(args["params"])
                if isinstance(args.get("args"), list):
                    payload["args"] = list(args["args"])
                if not payload:
                    payload["args"] = []
                result = await self._bridge_request("POST", f"/api/{method_name}", payload)
            else:
                raise ValueError("action must be list, describe, or call")
            if isinstance(result, Mapping) and result.get("outcome") == "unknown":
                status = "unknown"
            elif isinstance(result, Mapping) and result.get("error"):
                status = "failed"
            return _safe_json(result)
        except Exception as exc:
            status = "unknown" if isinstance(exc, (TimeoutError,)) else "failed"
            error_text = str(exc)
            return tool_error(redact_text(error_text), outcome=status)
        finally:
            self.store.log_tool_activity(
                requester_id=requester.requester_id,
                thread_type=self._activity_thread_type(requester),
                thread_id=requester.thread_id,
                tool_name=f"zalo.{action}" + (f".{method_name}" if method_name else ""),
                status=status,
                error_text=error_text,
                metadata={"action": action, "method": method_name},
            )

    async def zalo_history(self, args: dict[str, Any], **_: Any) -> str:
        requester = self._requester()
        action = str(args.get("action") or "recent").strip().lower()
        status = "success"
        error_text = None
        try:
            if action == "recent":
                thread_type = str(
                    args.get("thread_type") or requester.thread_type
                ).strip().lower()
                if thread_type == "user":
                    thread_type = "dm"
                thread_id = str(args.get("thread_id") or requester.thread_id)
                if not requester.is_admin and thread_type == "dm" and thread_id != requester.requester_id:
                    raise PermissionError("members may only read their own DM history")
                if not requester.is_admin and thread_type == "group" and thread_id not in set(self.config.allowed_groups):
                    raise PermissionError("group is not in the company allowlist")
                result = {"items": self.store.recent_messages(thread_type, thread_id, limit=int(args.get("limit") or 100))}
            elif action == "search":
                result = {"items": self.store.search_messages(
                    str(args.get("query") or ""),
                    requester_id=requester.requester_id,
                    is_admin=requester.is_admin,
                    allowed_groups=self.config.allowed_groups,
                    thread_type=args.get("thread_type"),
                    thread_id=args.get("thread_id"),
                    limit=int(args.get("limit") or 50),
                )}
            elif action == "get_message":
                result = {"message": self.store.get_message(
                    int(args.get("message_id")),
                    requester_id=requester.requester_id,
                    is_admin=requester.is_admin,
                    allowed_groups=self.config.allowed_groups,
                )}
            elif action == "get_attachment":
                result = {"attachment": self.store.get_attachment(
                    int(args.get("attachment_id")),
                    requester_id=requester.requester_id,
                    is_admin=requester.is_admin,
                    allowed_groups=self.config.allowed_groups,
                )}
            else:
                raise ValueError("action must be recent, search, get_message, or get_attachment")
            return _safe_json(result)
        except Exception as exc:
            status = "failed"
            error_text = str(exc)
            return tool_error(redact_text(error_text))
        finally:
            self.store.log_tool_activity(
                requester_id=requester.requester_id,
                thread_type=self._activity_thread_type(requester),
                thread_id=requester.thread_id,
                tool_name=f"zalo_history.{action}",
                status=status,
                error_text=error_text,
                metadata={"action": action},
            )

    async def zalo_admin(self, args: dict[str, Any], **_: Any) -> str:
        requester = self._requester()
        action = str(args.get("action") or "status").strip().lower()
        status = "success"
        error_text = None
        try:
            admin_args = {key: value for key, value in args.items() if key != "action"}
            result = await self.admin.action(action, requester=requester, **admin_args)
            if (
                action
                in {
                    "add_user",
                    "remove_user",
                    "add_admin",
                    "remove_admin",
                    "add_group",
                    "remove_group",
                    "apply_access_config",
                }
                and isinstance(result, Mapping)
                and isinstance(result.get("config"), Mapping)
            ):
                refreshed = CompanyConfig.from_mapping(result["config"])
                self.config = replace(
                    refreshed,
                    bridge_token=getattr(self.config, "bridge_token", ""),
                )
            return _safe_json(result)
        except Exception as exc:
            status = "blocked" if isinstance(exc, (PermissionError, AdminDenied)) else "failed"
            error_text = str(exc)
            return tool_error(redact_text(error_text))
        finally:
            self.store.log_tool_activity(
                requester_id=requester.requester_id,
                thread_type=self._activity_thread_type(requester),
                thread_id=requester.thread_id,
                tool_name=f"zalo_admin.{action}",
                status=status,
                error_text=error_text,
                metadata={"action": action},
            )

    def _protected_runtime_paths(self) -> list[tuple[frozenset[str], bool]]:
        resources: list[tuple[str | Path, bool]] = []
        config_file = getattr(self.admin, "config_file", None)
        config_path = getattr(config_file, "path", None)
        if config_path:
            resources.append((config_path, False))
        if getattr(self.admin, "memory_path", None):
            resources.append((Path(self.admin.memory_path).parent, True))

        db_path = getattr(self.store, "db_path", None)
        if db_path:
            resources.extend(
                (
                    (db_path, False),
                    (f"{db_path}-wal", False),
                    (f"{db_path}-shm", False),
                )
            )
        if getattr(self.store, "media_root", None):
            resources.append((self.store.media_root, True))
        if getattr(self.admin, "export_root", None):
            resources.append((self.admin.export_root, True))

        hermes_home = Path(os.getenv("HERMES_HOME") or (Path.home() / ".hermes"))
        resources.extend(
            (
                (hermes_home / ".env", False),
                (Path.home() / ".hermes-zalo" / "company.env", False),
                ("~/.hermes-zalo/company.env", False),
                (Path("/etc/hermes-zalo-company.env"), False),
            )
        )
        zalo_data_dir = os.getenv("ZALO_DATA_DIR")
        if zalo_data_dir:
            resources.append((zalo_data_dir, True))
        return [(_path_keys(path), is_root) for path, is_root in resources]

    def _protected_working_directories(self) -> list[tuple[frozenset[str], bool]]:
        hermes_home = Path(os.getenv("HERMES_HOME") or (Path.home() / ".hermes"))
        resources: list[tuple[str | Path, bool]] = [
            (hermes_home, False),
            (Path.home() / ".hermes-zalo", True),
            (Path("/etc"), False),
        ]

        config_file = getattr(self.admin, "config_file", None)
        config_path = getattr(config_file, "path", None)
        if config_path:
            resources.append((Path(config_path).parent, False))
        if getattr(self.admin, "memory_path", None):
            resources.append((Path(self.admin.memory_path).parent, True))

        db_path = getattr(self.store, "db_path", None)
        if db_path:
            resources.append((Path(db_path).parent, False))
        if getattr(self.store, "media_root", None):
            resources.append((self.store.media_root, True))
        if getattr(self.admin, "export_root", None):
            resources.append((self.admin.export_root, True))
        zalo_data_dir = os.getenv("ZALO_DATA_DIR")
        if zalo_data_dir:
            resources.append((zalo_data_dir, True))
        return [(_path_keys(path), is_root) for path, is_root in resources]

    @staticmethod
    def _block_decision() -> dict[str, str]:
        return {"action": "block", "message": _GUARD_MESSAGE}

    def guard_tool_call(self, tool_name: str, args: Any) -> dict[str, str] | None:
        requester = self._requester()
        if requester.is_admin:
            return None

        normalized_tool = str(tool_name or "").strip().lower().replace("-", "_")
        leaf_tool = _tool_leaf(normalized_tool)
        action = _mapping_action(args)

        if leaf_tool == "memory" and action in _MEMORY_MUTATIONS:
            return self._block_decision()
        if leaf_tool in _HISTORY_MUTATIONS or action in _HISTORY_MUTATIONS:
            return self._block_decision()

        protected = self._protected_runtime_paths()
        if leaf_tool in _PATH_TOOL_NAMES:
            memory_path = getattr(self.admin, "memory_path", None)
            for path in _target_values(args):
                if (
                    leaf_tool in _MUTATING_PATH_TOOL_NAMES
                    and _is_relative_shared_memory_path(path)
                ):
                    return self._block_decision()
                if (
                    leaf_tool in _READ_PATH_TOOL_NAMES
                    and memory_path
                    and _path_is_exact(path, memory_path)
                ):
                    continue
                if _path_is_protected(path, protected):
                    return self._block_decision()
            return None
        if leaf_tool in {"apply_patch", "patch"}:
            if any(
                _is_relative_shared_memory_path(path)
                or _path_is_protected(path, protected)
                for path in _patch_targets(args)
            ):
                return self._block_decision()
            return None
        if leaf_tool not in _CODE_TOOL_NAMES:
            return None

        command = _command_text(args)
        protected_workdirs = self._protected_working_directories()
        if (
            any(
                _path_is_protected(path, protected_workdirs)
                for path in _working_directory_values(args)
            )
            or _text_mentions_protected_path(command, protected)
            or _SYSTEMCTL_RE.search(command)
            or _SERVICE_RE.search(command)
            or _HERMES_GATEWAY_RE.search(command)
            or _HISTORY_API_RE.search(command)
            or _HISTORY_COMMAND_RE.search(command)
            or _HISTORY_ADMIN_COMMAND_RE.search(command)
            or _POWERSHELL_ENV_ENUM_RE.search(command)
            or _DOTNET_ENV_ENUM_RE.search(command)
            or _POSIX_ENV_ENUM_RE.search(command)
            or (
                leaf_tool in {"execute_code", "python"}
                and _PYTHON_ENV_ACCESS_RE.search(command)
            )
            or _RELATIVE_MEMORY_TEXT_RE.search(command)
            or _mentions_secret_env_name(command)
        ):
            return self._block_decision()
        return None

    def on_pre_tool_call(self, *, tool_name: str = "", args: Any = None, **_: Any) -> dict[str, str] | None:
        try:
            decision = self.guard_tool_call(tool_name, args)
            if decision and decision.get("action") == "block":
                requester = self._requester()
                self.store.log_tool_activity(
                    requester_id=requester.requester_id,
                    thread_type=self._activity_thread_type(requester),
                    thread_id=requester.thread_id,
                    tool_name=str(tool_name),
                    status="blocked",
                    error_text=decision.get("message"),
                    metadata={},
                )
            return decision
        except MissingRequesterContext:
            # Hooks are process-global in Hermes. A CLI/cron/non-Zalo turn has
            # no Zalo requester and must remain unaffected.
            return None

    def on_post_tool_call(
        self,
        *,
        tool_name: str = "",
        status: str | None = None,
        result: Any = None,
        error_message: str | None = None,
        **_: Any,
    ) -> None:
        try:
            requester = self._requester()
        except MissingRequesterContext:
            return
        parsed_result = result
        if isinstance(result, str):
            try:
                parsed_result = json.loads(result)
            except (TypeError, ValueError):
                parsed_result = None
        reported_status = str(status or "").strip().lower()
        if isinstance(parsed_result, Mapping):
            outcome = str(
                parsed_result.get("outcome") or parsed_result.get("status") or ""
            ).strip().lower()
            if not reported_status and outcome in {
                "success",
                "failed",
                "unknown",
                "blocked",
            }:
                reported_status = outcome
            if error_message is None and parsed_result.get("error"):
                error_message = str(parsed_result["error"])
                if not reported_status:
                    reported_status = "failed"
        if reported_status in {"error", "failed"}:
            normalized = "failed"
        elif reported_status == "blocked":
            normalized = "blocked"
        elif reported_status == "unknown":
            normalized = "unknown"
        else:
            normalized = "success"
        self.store.log_tool_activity(
            requester_id=requester.requester_id,
            thread_type=self._activity_thread_type(requester),
            thread_id=requester.thread_id,
            tool_name=str(tool_name),
            status=normalized,
            error_text=redact_text(error_message),
            metadata={},
        )

    def on_pre_gateway_dispatch(self, *, event: Any = None, **_: Any) -> None:
        # ContextVar lifetime is bound around adapter.handle_message(); this
        # hook is intentionally observational and never trusts model args.
        return None


ZALO_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["list", "describe", "call"]},
        "query": {"type": "string"},
        "method": {"type": "string"},
        "params": {"type": "object"},
        "args": {"type": "array"},
    },
    "required": ["action"],
}
ZALO_HISTORY_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["recent", "search", "get_message", "get_attachment"]},
        "query": {"type": "string"},
        "thread_type": {"type": "string", "enum": ["dm", "group"]},
        "thread_id": {"type": "string"},
        "message_id": {"type": "integer"},
        "attachment_id": {"type": "integer"},
        "limit": {"type": "integer"},
    },
    "required": ["action"],
}
ZALO_ADMIN_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string"},
        "zalo_id": {"type": "string"},
        "user_id": {"type": "string"},
        "text": {"type": "string"},
        "old": {"type": "string"},
        "new": {"type": "string"},
        "destination": {"type": "string"},
        "thread_type": {"type": "string"},
        "thread_id": {"type": "string"},
        "since": {"type": "string"},
        "until": {"type": "string"},
        "lines": {"type": "integer"},
        "allowed_users": {"type": "array", "items": {"type": "string"}},
        "admin_users": {"type": "array", "items": {"type": "string"}},
        "allowed_groups": {"type": "array", "items": {"type": "string"}},
        "fingerprint": {"type": "string"},
    },
    "required": ["action"],
}


def register_tooling(ctx: Any, tooling: ZaloTooling) -> None:
    """Register tools and guards using Hermes Agent 0.19's plugin facade."""
    ctx.register_tool(name="zalo", toolset="zalo", schema=ZALO_SCHEMA, handler=tooling.zalo, is_async=True, description="Gọi catalog vận hành zca-js")
    ctx.register_tool(name="zalo_history", toolset="zalo", schema=ZALO_HISTORY_SCHEMA, handler=tooling.zalo_history, is_async=True, description="Tìm và đọc lịch sử Zalo theo scope requester")
    ctx.register_tool(name="zalo_admin", toolset="zalo", schema=ZALO_ADMIN_SCHEMA, handler=tooling.zalo_admin, is_async=True, description="Quản trị bot, memory và lịch sử; chỉ admin")
    ctx.register_hook("pre_gateway_dispatch", tooling.on_pre_gateway_dispatch)
    ctx.register_hook("pre_tool_call", tooling.on_pre_tool_call)
    ctx.register_hook("post_tool_call", tooling.on_post_tool_call)
