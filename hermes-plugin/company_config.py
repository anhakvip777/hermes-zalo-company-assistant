from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

import yaml


MAX_CONTEXT_MESSAGES = 100
MAX_MEDIA_BYTES = 20 * 1024 * 1024
DEFAULT_CONTEXT_MESSAGES = MAX_CONTEXT_MESSAGES
DEFAULT_MEDIA_MAX_BYTES = MAX_MEDIA_BYTES


class CompanyConfigError(ValueError):
    """Raised when company identity or routing configuration is unsafe."""


class CompanyConfigConflict(CompanyConfigError):
    """Raised when an access edit is based on a stale fingerprint."""


def _ids(value: Any) -> frozenset[str]:
    if value is None:
        return frozenset()
    if isinstance(value, str):
        values = value.split(",")
    elif isinstance(value, Mapping) or isinstance(value, (bytes, bytearray)):
        raise CompanyConfigError("ID lists must be strings or arrays")
    else:
        values = value
    try:
        return frozenset(
            str(item).strip() for item in values if str(item).strip()
        )
    except TypeError as exc:
        raise CompanyConfigError("ID lists must be strings or arrays") from exc


def _env_ids(env: Mapping[str, str], name: str, fallback: Any) -> frozenset[str]:
    if name not in env:
        return _ids(fallback)
    return _ids(env.get(name, ""))


def _integer(data: Mapping[str, Any], name: str, default: int) -> int:
    raw = data.get(name, default)
    if isinstance(raw, bool):
        raise CompanyConfigError(f"{name} must be an integer")
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise CompanyConfigError(f"{name} must be an integer") from exc
    if isinstance(raw, float) and raw != value:
        raise CompanyConfigError(f"{name} must be an integer")
    return value


def _validate_bridge_url(value: str) -> None:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise CompanyConfigError("bridge_url must use loopback 127.0.0.1") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.username is not None
        or parsed.password is not None
        or port is None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise CompanyConfigError("bridge_url must use loopback 127.0.0.1")


@dataclass(frozen=True, slots=True)
class CompanyConfig:
    bridge_url: str
    allowed_users: frozenset[str]
    admin_users: frozenset[str]
    allowed_groups: frozenset[str]
    group_mode: str = "mention"
    history_context_messages: int = DEFAULT_CONTEXT_MESSAGES
    media_max_bytes: int = DEFAULT_MEDIA_MAX_BYTES
    history_retention: str = "90"
    bridge_token: str = ""

    def __post_init__(self) -> None:
        if not self.allowed_users:
            raise CompanyConfigError("allowed_users must contain at least one Zalo ID")
        if not self.admin_users:
            raise CompanyConfigError("admin_users must contain at least one Zalo ID")
        if not self.admin_users.issubset(self.allowed_users):
            raise CompanyConfigError("admin_users must be a subset of allowed_users")
        if not self.allowed_groups:
            raise CompanyConfigError(
                "allowed_groups must contain at least one company group"
            )
        if self.group_mode != "mention":
            raise CompanyConfigError("group_mode must be mention")
        if not 1 <= self.history_context_messages <= MAX_CONTEXT_MESSAGES:
            raise CompanyConfigError(
                "history_context_messages must be between 1 and 100"
            )
        if not 1 <= self.media_max_bytes <= MAX_MEDIA_BYTES:
            raise CompanyConfigError(
                "media_max_bytes must be between 1 byte and 20 MiB"
            )
        if self.history_retention not in {"30", "90", "365", "forever"}:
            raise CompanyConfigError(
                "history_retention must be 30, 90, 365, or forever"
            )
        _validate_bridge_url(self.bridge_url)

    @property
    def history_retention_days(self) -> int | None:
        return None if self.history_retention == "forever" else int(self.history_retention)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CompanyConfig":
        if not isinstance(data, Mapping):
            raise CompanyConfigError("platform extra must be a mapping")
        return cls(
            bridge_url=str(data.get("bridge_url") or "http://127.0.0.1:8787").rstrip(
                "/"
            ),
            allowed_users=_ids(data.get("allowed_users")),
            admin_users=_ids(data.get("admin_users")),
            allowed_groups=_ids(data.get("allowed_groups")),
            group_mode=str(data.get("group_mode") or "mention").strip().lower(),
            history_context_messages=_integer(
                data, "history_context_messages", DEFAULT_CONTEXT_MESSAGES
            ),
            media_max_bytes=_integer(
                data, "media_max_bytes", DEFAULT_MEDIA_MAX_BYTES
            ),
            history_retention=str(
                data.get("history_retention") or "90"
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
        if not isinstance(extra, Mapping):
            raise CompanyConfigError("platform extra must be a mapping")
        if env is not None and not isinstance(env, Mapping):
            raise CompanyConfigError("environment must be a mapping")
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
        group_env_name = (
            "ZALO_ALLOWED_GROUPS"
            if "ZALO_ALLOWED_GROUPS" in source
            else "ZALO_ALLOWED_THREADS"
        )
        data["allowed_groups"] = _env_ids(
            source, group_env_name, data.get("allowed_groups")
        )
        if "ZALO_GROUP_MODE" in source:
            data["group_mode"] = source["ZALO_GROUP_MODE"]
        if "ZALO_HISTORY_CONTEXT_MESSAGES" in source:
            data["history_context_messages"] = source[
                "ZALO_HISTORY_CONTEXT_MESSAGES"
            ]
        if "ZALO_MEDIA_MAX_BYTES" in source:
            data["media_max_bytes"] = source["ZALO_MEDIA_MAX_BYTES"]
        if "ZALO_HISTORY_RETENTION" in source:
            data["history_retention"] = source["ZALO_HISTORY_RETENTION"]
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


@dataclass(frozen=True, slots=True)
class AccessConfigSnapshot:
    config: CompanyConfig
    fingerprint: str

    def to_mapping(self) -> dict[str, Any]:
        return {
            "allowed_users": sorted(self.config.allowed_users),
            "admin_users": sorted(self.config.admin_users),
            "allowed_groups": sorted(self.config.allowed_groups),
            "fingerprint": self.fingerprint,
        }


def _access_fingerprint(config: CompanyConfig) -> str:
    payload = {
        "allowed_users": sorted(config.allowed_users),
        "admin_users": sorted(config.admin_users),
        "allowed_groups": sorted(config.allowed_groups),
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class CompanyConfigFile:
    """Atomic editor for gateway.platforms.zalo.extra in Hermes config.yaml."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.RLock()

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

    def load(self, *, env: Mapping[str, str] | None = None) -> CompanyConfig:
        document = self._document()
        return CompanyConfig.from_platform_extra(self._extra(document), env=env)

    def read_access_config(self) -> AccessConfigSnapshot:
        with self._lock:
            config = self.load(env={})
            return AccessConfigSnapshot(config, _access_fingerprint(config))

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

    def update_atomic(
        self,
        changes: Mapping[str, Any],
    ) -> CompanyConfig:
        """Validate and atomically replace the YAML document.

        ``changes`` is merged into the Zalo ``extra`` mapping. The candidate
        is validated before the temporary file is replaced, so an invalid
        update leaves the original file untouched.
        """
        if not isinstance(changes, Mapping):
            raise CompanyConfigError("config changes must be a mapping")

        document = self._document()
        extra = self._extra(document)
        candidate = dict(extra)
        candidate.update(changes)
        # Runtime credentials belong in the private service environment, never
        # in gateway config.yaml (which may be inspected by the agent).
        candidate.pop("bridge_token", None)

        # Validate the persisted values without ambient process env overrides;
        # an env override must never mask an unsafe YAML update on disk.
        persisted = CompanyConfig.from_mapping(candidate)
        extra.clear()
        extra.update(candidate)
        self._write(document)
        return persisted

    def apply_access_config(
        self,
        *,
        allowed_users: Any,
        admin_users: Any,
        allowed_groups: Any,
        expected_fingerprint: str,
    ) -> AccessConfigSnapshot:
        with self._lock:
            current = self.read_access_config()
            if not hmac.compare_digest(
                current.fingerprint,
                str(expected_fingerprint or ""),
            ):
                raise CompanyConfigConflict(
                    "company access config changed; reload before applying"
                )
            updated = self.update_atomic(
                {
                    "allowed_users": sorted(_ids(allowed_users)),
                    "admin_users": sorted(_ids(admin_users)),
                    "allowed_groups": sorted(_ids(allowed_groups)),
                }
            )
            return AccessConfigSnapshot(updated, _access_fingerprint(updated))

    def rollback_access_config(
        self,
        snapshot: AccessConfigSnapshot,
        *,
        expected_fingerprint: str,
    ) -> AccessConfigSnapshot:
        if not isinstance(snapshot, AccessConfigSnapshot):
            raise TypeError("snapshot must be an AccessConfigSnapshot")
        with self._lock:
            current = self.read_access_config()
            if not hmac.compare_digest(
                current.fingerprint,
                str(expected_fingerprint or ""),
            ):
                raise CompanyConfigConflict(
                    "company access config changed after apply; rollback refused"
                )
            return self.apply_access_config(
                allowed_users=snapshot.config.allowed_users,
                admin_users=snapshot.config.admin_users,
                allowed_groups=snapshot.config.allowed_groups,
                expected_fingerprint=current.fingerprint,
            )

    def mutate(self, action: str, zalo_id: str) -> CompanyConfig:
        value = str(zalo_id or "").strip()
        if not value:
            raise CompanyConfigError("Zalo ID is required")
        with self._lock:
            current = self.read_access_config()
            users = set(current.config.allowed_users)
            admins = set(current.config.admin_users)
            groups = set(current.config.allowed_groups)

            if action == "add_user":
                users.add(value)
            elif action == "remove_user":
                if value in admins:
                    raise CompanyConfigError(
                        "remove admin role before removing user"
                    )
                users.discard(value)
            elif action == "add_admin":
                if value not in users:
                    raise CompanyConfigError(
                        "admin must already be an allowed user"
                    )
                admins.add(value)
            elif action == "remove_admin":
                if value in admins and len(admins) == 1:
                    raise CompanyConfigError("cannot remove the last admin")
                admins.discard(value)
            elif action == "add_group":
                groups.add(value)
            elif action == "remove_group":
                if value in groups and len(groups) == 1:
                    raise CompanyConfigError(
                        "cannot remove the last allowed group"
                    )
                groups.discard(value)
            else:
                raise CompanyConfigError(f"unknown config mutation: {action}")

            updated = self.apply_access_config(
                allowed_users=users,
                admin_users=admins,
                allowed_groups=groups,
                expected_fingerprint=current.fingerprint,
            )
            return updated.config


def atomic_update_yaml(
    path: str | Path,
    changes: Mapping[str, Any],
) -> CompanyConfig:
    """Atomically update ``gateway.platforms.zalo.extra`` in a YAML file."""
    return CompanyConfigFile(path).update_atomic(changes)
