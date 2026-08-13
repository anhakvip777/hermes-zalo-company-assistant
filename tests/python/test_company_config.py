from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from company_config import (
    CompanyConfig,
    CompanyConfigConflict,
    CompanyConfigError,
    CompanyConfigFile,
    atomic_update_yaml,
)


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


def _config_file(path: Path) -> CompanyConfigFile:
    path.write_text(
        yaml.safe_dump(
            {
                "gateway": {
                    "platforms": {"zalo": {"extra": valid_extra()}}
                },
                "unrelated": {"keep": True},
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return CompanyConfigFile(path)


def test_access_fingerprint_apply_conflict_and_unrelated_yaml(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.yaml"
    config_file = _config_file(path)
    before = config_file.read_access_config()

    applied = config_file.apply_access_config(
        allowed_users=["u-2", "u-1", "u-2"],
        admin_users=["u-1"],
        allowed_groups=["g-2", "g-1", "g-2"],
        expected_fingerprint=before.fingerprint,
    )

    assert applied.config.allowed_users == frozenset({"u-1", "u-2"})
    assert applied.config.allowed_groups == frozenset({"g-1", "g-2"})
    assert applied.fingerprint != before.fingerprint
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["unrelated"] == {
        "keep": True
    }
    bytes_after = path.read_bytes()
    with pytest.raises(CompanyConfigConflict, match="changed"):
        config_file.apply_access_config(
            allowed_users=["u-1", "u-2"],
            admin_users=["u-1"],
            allowed_groups=["g-1"],
            expected_fingerprint=before.fingerprint,
        )
    assert path.read_bytes() == bytes_after


def test_access_rollback_and_group_mutation_protect_last_group(
    tmp_path: Path,
) -> None:
    config_file = _config_file(tmp_path / "config.yaml")
    before = config_file.read_access_config()
    applied = config_file.apply_access_config(
        allowed_users=["u-1", "u-2"],
        admin_users=["u-1"],
        allowed_groups=["g-1", "g-2"],
        expected_fingerprint=before.fingerprint,
    )

    rolled_back = config_file.rollback_access_config(
        before,
        expected_fingerprint=applied.fingerprint,
    )

    assert rolled_back.config.allowed_groups == frozenset({"g-1"})
    assert "g-2" in config_file.mutate("add_group", "g-2").allowed_groups
    assert "g-2" not in config_file.mutate("remove_group", "g-2").allowed_groups
    with pytest.raises(CompanyConfigError, match="last allowed group"):
        config_file.mutate("remove_group", "g-1")


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


def test_media_cap_cannot_be_raised_above_the_locked_twenty_mib_limit() -> None:
    data = valid_extra()
    data["media_max_bytes"] = 20 * 1024 * 1024 + 1

    with pytest.raises(CompanyConfigError, match="20 MiB"):
        CompanyConfig.from_mapping(data)


def test_atomic_yaml_update_merges_and_rolls_back_invalid_changes(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "gateway": {
                    "platforms": {"zalo": {"extra": valid_extra()}},
                },
                "unrelated": {"keep": True},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    updated = atomic_update_yaml(path, {"allowed_users": ["u-1", "u-2", "u-3"]})
    assert "u-3" in updated.allowed_users
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert document["unrelated"] == {"keep": True}

    before_invalid = path.read_bytes()
    with pytest.raises(CompanyConfigError, match="subset"):
        atomic_update_yaml(path, {"admin_users": ["not-allowed"]})
    assert path.read_bytes() == before_invalid


def test_id_mapping_is_rejected_instead_of_being_treated_as_an_allowlist() -> None:
    data = valid_extra()
    data["allowed_users"] = {"u-1": True}

    with pytest.raises(CompanyConfigError, match="strings or arrays"):
        CompanyConfig.from_mapping(data)


def test_history_retention_environment_override_is_validated() -> None:
    with pytest.raises(CompanyConfigError, match="history_retention"):
        CompanyConfig.from_platform_extra(
            valid_extra(),
            env={
                "ZALO_HISTORY_RETENTION": "7",
            },
        )


@pytest.mark.parametrize(("value", "days"), [("30", 30), ("90", 90), ("365", 365), ("forever", None)])
def test_history_retention_accepts_bounded_days_or_forever(value: str, days: int | None) -> None:
    data = valid_extra()
    data["history_retention"] = value

    config = CompanyConfig.from_mapping(data)

    assert config.history_retention == value
    assert config.history_retention_days == days


def test_history_retention_defaults_to_ninety_days() -> None:
    data = valid_extra()
    data.pop("history_retention", None)

    assert CompanyConfig.from_mapping(data).history_retention == "90"


def test_non_numeric_caps_raise_company_config_error() -> None:
    data = valid_extra()
    data["history_context_messages"] = "many"

    with pytest.raises(CompanyConfigError, match="history_context_messages"):
        CompanyConfig.from_mapping(data)


def test_missing_platform_extra_fails_closed_with_config_error() -> None:
    with pytest.raises(CompanyConfigError, match="mapping"):
        CompanyConfig.from_platform_extra(None)  # type: ignore[arg-type]


def test_bridge_url_cannot_smuggle_a_remote_host_through_userinfo() -> None:
    data = valid_extra()
    data["bridge_url"] = "http://127.0.0.1:8787@evil.example"
    with pytest.raises(CompanyConfigError, match="loopback"):
        CompanyConfig.from_mapping(data)


def test_atomic_yaml_update_never_persists_bridge_token(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    extra = valid_extra()
    extra["bridge_token"] = "legacy-secret-token"
    path.write_text(
        yaml.safe_dump({"gateway": {"platforms": {"zalo": {"extra": extra}}}}),
        encoding="utf-8",
    )
    CompanyConfigFile(path).update_atomic({"allowed_users": ["u-1", "u-2"]})
    rendered = path.read_text(encoding="utf-8")
    assert "legacy-secret-token" not in rendered
    assert "bridge_token" not in rendered
