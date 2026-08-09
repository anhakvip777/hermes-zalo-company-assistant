from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from company_config import CompanyConfig, CompanyConfigError, CompanyConfigFile


def valid_extra() -> dict:
    return {
        "bridge_url": "http://127.0.0.1:8787",
        "allowed_users": ["u-1", "u-2"],
        "admin_users": ["u-1"],
        "allowed_groups": ["g-1"],
        "group_mode": "mention",
        "history_context_messages": 100,
        "media_max_bytes": 20 * 1024 * 1024,
        "history_retention": "forever",
    }


def test_company_config_loads_the_locked_defaults() -> None:
    cfg = CompanyConfig.from_mapping(valid_extra())
    assert cfg.allowed_users == frozenset({"u-1", "u-2"})
    assert cfg.admin_users == frozenset({"u-1"})
    assert cfg.allowed_groups == frozenset({"g-1"})
    assert cfg.group_mode == "mention"
    assert cfg.history_context_messages == 100
    assert cfg.media_max_bytes == 20 * 1024 * 1024


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("allowed_users", [], "allowed_users"),
        ("admin_users", [], "admin_users"),
        ("admin_users", ["outside"], "subset"),
        ("allowed_groups", [], "allowed_groups"),
        ("group_mode", "all", "mention"),
        ("history_context_messages", 0, "history_context_messages"),
        ("media_max_bytes", 0, "media_max_bytes"),
    ],
)
def test_company_config_fails_closed(field: str, value, message: str) -> None:
    data = valid_extra()
    data[field] = value
    with pytest.raises(CompanyConfigError, match=message):
        CompanyConfig.from_mapping(data)


def test_environment_overrides_are_explicit_and_never_create_allow_all() -> None:
    cfg = CompanyConfig.from_platform_extra(
        valid_extra(),
        env={
            "ZALO_ALLOWED_USERS": "u-3,u-4",
            "ZALO_ADMIN_USERS": "u-3",
            "ZALO_ALLOWED_GROUPS": "g-2",
            "ZALO_PLUGIN_TOKEN": "x" * 32,
        },
    )
    assert cfg.allowed_users == frozenset({"u-3", "u-4"})
    assert cfg.admin_users == frozenset({"u-3"})
    assert cfg.allowed_groups == frozenset({"g-2"})

    with pytest.raises(CompanyConfigError, match="allowed_users"):
        CompanyConfig.from_platform_extra(
            valid_extra(),
            env={"ZALO_ALLOWED_USERS": "", "ZALO_ADMIN_USERS": ""},
        )


def test_atomic_config_update_keeps_admin_subset_and_last_admin(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "gateway": {
                    "platforms": {"zalo": {"extra": valid_extra()}}
                }
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    config_file = CompanyConfigFile(path)

    updated = config_file.mutate("add_user", "u-3")
    updated = config_file.mutate("add_admin", "u-3")
    updated = config_file.mutate("remove_admin", "u-1")

    assert updated.admin_users == frozenset({"u-3"})
    assert updated.allowed_users == frozenset({"u-1", "u-2", "u-3"})
    with pytest.raises(CompanyConfigError, match="last admin"):
        config_file.mutate("remove_admin", "u-3")

