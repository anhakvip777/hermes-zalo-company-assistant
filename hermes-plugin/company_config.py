from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

import yaml


DEFAULT_CONTEXT_MESSAGES = 100
DEFAULT_MEDIA_MAX_BYTES = 20 * 1024 * 1024


class CompanyConfigError(ValueError):
    """Raised when company identity or routing configuration is unsafe."""


def _ids(value: Any) -> frozenset[str]:
    if value is None:
        return frozenset()
    if isinstance(value, str):
        values = value.split(",")
    else:
        values = value
    try:
        return frozenset(str(item).strip() for item in values if str(item).strip())
    except TypeError as exc:
        raise CompanyConfigError("ID lists must be strings or arrays") from exc


def _env_ids(env: Mapping[str, str], name: str, fallback: Any) -> frozenset[str]:
    if name not in env:
        return _ids(fallback)
    return _ids(env.get(name, ""))


@dataclass(frozen=True, slots=True)
class CompanyConfig:
    bridge_url: str
    allowed_users: frozenset[str]
    admin_users: frozenset[str]
    allowed_groups: frozenset[str]
    group_mode: str = "mention"
    history_context_messages: int = DEFAULT_CONTEXT_MESSAGES
    media_max_bytes: int = DEFAULT_MEDIA_MAX_BYTES
    history_retention: str = "forever"
    bridge_token: str = ""

    def __post_init__(self) -> None:
        if not self.allowed_users:
            raise CompanyConfigError("allowed_users must contain at least one Zalo ID")
        if not self.admin_users:
            raise CompanyConfigError("admin_users must contain at least one Zalo ID")
        if not self.admin_users.issubset(self.allowed_users):
            raise CompanyConfigError("admin_users must be a subset of allowed_users")
        if not self.allowed_groups:
            raise CompanyConfigError("allowed_groups must contain at least one company group")
        if self.group_mode != "mention":
            raise CompanyConfigError("group_mode must be mention")
        if not 1 <= self.history_context_messages <= 100:
            raise CompanyConfigError(
                "history_context_messages must be between 1 and 100"
            )
        if self.media_max_bytes <= 0:
            raise CompanyConfigError("media_max_bytes must be greater than zero")
        if self.history_retention != "forever":
            raise CompanyConfigError("history_retention must be forever")
        if not self.bridge_url.startswith("http://127.0.0.1:"):
            raise CompanyConfigError("bridge_url must use loopback 127.0.0.1")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CompanyConfig":
        return cls(
            bridge_url=str(data.get("bridge_url") or "http://127.0.0.1:8787").rstrip(
                "/"
            ),
            allowed_users=_ids(data.get("allowed_users")),
            admin_users=_ids(data.get("admin_users")),
            allowed_groups=_ids(data.get("allowed_groups")),
            group_mode=str(data.get("group_mode") or "mention").strip().lower(),
            history_context_messages=int(
                data.get("history_context_messages", DEFAULT_CONTEXT_MESSAGES)
            ),
            media_max_bytes=int(
                data.get("media_max_bytes", DEFAULT_MEDIA_MAX_BYTES)
            ),
            history_retention=str(
                data.get("history_retention") or "forever"
            ).strip(),
            bridge_token=str(data.get("bridge_token") or ""),
        )

    @classmethod
    def from_platform_extra(
        cls,
        extra: Mapping[str, Any],
        *,
        env: Mapping[str, str] | None = None,
    ) -> "CompanyConfig":
        source = os.environ if env is None else env
        data = dict(extra)
        data["bridge_url"] = source.get(
            "ZALO_PLUGIN_URL", data.get("bridge_url", "http://127.0.0.1:8787")
        )
        data["bridge_token"] = source.get(
            "ZALO_PLUGIN_TOKEN", data.get("bridge_token", "")
        )
        data["allowed_users"] = _env_ids(
            source, "ZALO_ALLOWED_USERS", data.get("allowed_users")
        )
        data["admin_users"] = _env_ids(
            source, "ZALO_ADMIN_USERS", data.get("admin_users")
        )
        data["allowed_groups"] = _env_ids(
            source, "ZALO_ALLOWED_GROUPS", data.get("allowed_groups")
        )
        if "ZALO_GROUP_MODE" in source:
            data["group_mode"] = source["ZALO_GROUP_MODE"]
        if "ZALO_HISTORY_CONTEXT_MESSAGES" in source:
            data["history_context_messages"] = source[
                "ZALO_HISTORY_CONTEXT_MESSAGES"
            ]
        if "ZALO_MEDIA_MAX_BYTES" in source:
            data["media_max_bytes"] = source["ZALO_MEDIA_MAX_BYTES"]
        return cls.from_mapping(data)

    def require_runtime_secrets(self) -> None:
        if len(self.bridge_token.encode("utf-8")) < 32:
            raise CompanyConfigError(
                "ZALO_PLUGIN_TOKEN must contain at least 32 UTF-8 bytes"
            )

    def to_mapping(self, *, include_secret: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "bridge_url": self.bridge_url,
            "allowed_users": sorted(self.allowed_users),
            "admin_users": sorted(self.admin_users),
            "allowed_groups": sorted(self.allowed_groups),
            "group_mode": self.group_mode,
            "history_context_messages": self.history_context_messages,
            "media_max_bytes": self.media_max_bytes,
            "history_retention": self.history_retention,
        }
        if include_secret and self.bridge_token:
            result["bridge_token"] = self.bridge_token
        return result


class CompanyConfigFile:
    """Atomic editor for gateway.platforms.zalo.extra in Hermes config.yaml."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _document(self) -> dict[str, Any]:
        try:
            loaded = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise CompanyConfigError(f"config file not found: {self.path}") from exc
        except (OSError, yaml.YAMLError) as exc:
            raise CompanyConfigError(f"cannot read config file: {exc}") from exc
        if loaded is None:
            loaded = {}
        if not isinstance(loaded, dict):
            raise CompanyConfigError("config root must be a mapping")
        return loaded

    @staticmethod
    def _extra(document: dict[str, Any]) -> dict[str, Any]:
        gateway = document.setdefault("gateway", {})
        if not isinstance(gateway, dict):
            raise CompanyConfigError("gateway config must be a mapping")
        platforms = gateway.setdefault("platforms", {})
        if not isinstance(platforms, dict):
            raise CompanyConfigError("gateway.platforms must be a mapping")
        zalo = platforms.setdefault("zalo", {})
        if not isinstance(zalo, dict):
            raise CompanyConfigError("gateway.platforms.zalo must be a mapping")
        extra = zalo.setdefault("extra", {})
        if not isinstance(extra, dict):
            raise CompanyConfigError(
                "gateway.platforms.zalo.extra must be a mapping"
            )
        return extra

    def load(self) -> CompanyConfig:
        document = self._document()
        return CompanyConfig.from_mapping(self._extra(document))

    def _write(self, document: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        rendered = yaml.safe_dump(
            document,
            sort_keys=False,
            allow_unicode=True,
        )
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=self.path.parent,
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(rendered)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.path)
        finally:
            try:
                Path(tmp_name).unlink(missing_ok=True)
            except OSError:
                pass

    def mutate(self, action: str, zalo_id: str) -> CompanyConfig:
        value = str(zalo_id or "").strip()
        if not value:
            raise CompanyConfigError("Zalo ID is required")
        document = self._document()
        extra = self._extra(document)
        current = CompanyConfig.from_mapping(extra)
        users = set(current.allowed_users)
        admins = set(current.admin_users)

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
        else:
            raise CompanyConfigError(f"unknown config mutation: {action}")

        updated = replace(
            current,
            allowed_users=frozenset(users),
            admin_users=frozenset(admins),
        )
        extra.clear()
        extra.update(updated.to_mapping())
        self._write(document)
        return updated
