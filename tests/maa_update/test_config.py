from __future__ import annotations

import pytest

from autogame_orchestrator.config_loader import _parse_maa_update
from autogame_orchestrator.config_model import MAAUpdateConfig
from autogame_orchestrator.models import ErrorCode


def test_default_disabled() -> None:
    assert MAAUpdateConfig().enabled is False


def test_default_network_not_allowed() -> None:
    assert MAAUpdateConfig().allow_network is False


def test_default_administrator_not_required() -> None:
    assert MAAUpdateConfig().requires_administrator is False


def test_sync_default_administrator_not_required() -> None:
    from autogame_orchestrator.config_model import MAASyncConfig

    assert MAASyncConfig().requires_administrator is False


@pytest.mark.parametrize("value", ["true", 1, 0, [], {}])
def test_sync_administrator_requires_strict_bool(value: object) -> None:
    from autogame_orchestrator.config_model import MAASyncConfig

    assert ErrorCode.CONFIG_SCHEMA_ERROR in MAASyncConfig(requires_administrator=value).validate()  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["enabled", "allow_network", "requires_administrator"])
@pytest.mark.parametrize("value", ["true", 1, 0, [], {}])
def test_boolean_fields_are_strict(field: str, value: object) -> None:
    config = MAAUpdateConfig(**{field: value})  # type: ignore[arg-type]
    assert ErrorCode.CONFIG_SCHEMA_ERROR in config.validate()


@pytest.mark.parametrize("value", [True, False, 0, -1, "1800", 1.5, None])
def test_timeout_requires_positive_non_bool_integer(value: object) -> None:
    config = MAAUpdateConfig(timeout_seconds=value)  # type: ignore[arg-type]
    assert ErrorCode.CONFIG_SCHEMA_ERROR in config.validate()


@pytest.mark.parametrize("value", [(), [], "update", None])
def test_arguments_require_non_empty_sequence(value: object) -> None:
    config = MAAUpdateConfig(arguments=value)  # type: ignore[arg-type]
    assert ErrorCode.CONFIG_SCHEMA_ERROR in config.validate()


@pytest.mark.parametrize("verb", ["self", "hot-update", "install", "run", "task", "Update", "UPDATE", " update"])
def test_first_argument_must_be_exact_update(verb: str) -> None:
    assert ErrorCode.CONFIG_SCHEMA_ERROR in MAAUpdateConfig(arguments=(verb,)).validate()


@pytest.mark.parametrize("forbidden", ["self", "hot-update", "install", "run", "task"])
def test_forbidden_lifecycle_or_task_token_is_rejected_anywhere(forbidden: str) -> None:
    assert ErrorCode.CONFIG_SCHEMA_ERROR in MAAUpdateConfig(arguments=("update", forbidden)).validate()


def test_at_most_sixteen_arguments() -> None:
    assert ErrorCode.CONFIG_SCHEMA_ERROR in MAAUpdateConfig(arguments=("update",) + ("--flag",) * 16).validate()


@pytest.mark.parametrize("argument", ["", "\x00", "line\nfeed", "tab\tvalue", "\x01", "\x1f", "\x7f", 7])
def test_argument_content_is_bounded_and_printable(argument: object) -> None:
    config = MAAUpdateConfig(arguments=("update", argument))  # type: ignore[arg-type]
    assert ErrorCode.CONFIG_SCHEMA_ERROR in config.validate()


@pytest.mark.parametrize("length", [513, 1024])
def test_argument_length_limit(length: int) -> None:
    assert ErrorCode.CONFIG_SCHEMA_ERROR in MAAUpdateConfig(arguments=("update", "x" * length)).validate()


def test_enabled_requires_explicit_network_opt_in() -> None:
    assert ErrorCode.CONFIG_SCHEMA_ERROR in MAAUpdateConfig(enabled=True).validate()


def test_enabled_with_network_is_valid() -> None:
    assert MAAUpdateConfig(enabled=True, allow_network=True).validate() == []


def test_arguments_list_is_accepted() -> None:
    assert MAAUpdateConfig(arguments=["update", "--channel", "stable"]).validate() == []  # type: ignore[arg-type]


def test_loader_defaults_missing_section() -> None:
    assert _parse_maa_update(None) == (MAAUpdateConfig(), [])


def test_loader_parses_all_fields() -> None:
    raw = {
        "enabled": True,
        "allow_network": True,
        "requires_administrator": True,
        "arguments": ["update", "--channel", "stable"],
        "timeout_seconds": 123,
    }
    config, errors = _parse_maa_update(raw)
    assert errors == []
    assert config == MAAUpdateConfig(True, True, True, ("update", "--channel", "stable"), 123)


@pytest.mark.parametrize(
    "field,value",
    [
        ("enabled", "false"),
        ("allow_network", 1),
        ("requires_administrator", 0),
        ("arguments", "update"),
        ("arguments", ["update", 1]),
        ("timeout_seconds", True),
    ],
)
def test_loader_rejects_wrong_types(field: str, value: object) -> None:
    raw: dict[str, object] = {field: value}
    assert _parse_maa_update(raw) == (None, [ErrorCode.CONFIG_SCHEMA_ERROR])


@pytest.mark.parametrize(
    "field",
    ["executable", "working_directory", "self_update", "hot_update", "self_update_arguments", "hot_update_arguments"],
)
def test_loader_rejects_unapproved_fields(field: str) -> None:
    assert _parse_maa_update({field: "forbidden"}) == (None, [ErrorCode.CONFIG_SCHEMA_ERROR])


def test_default_timeout_leaves_margin_for_large_archive_extraction() -> None:
    """默认超时须留出足够余量，降低解压中途被强杀而留下坏资源的概率。

    maa-cli 的安装环节非事务性：`maa_core.rs` 的 pre_install_hook 先用
    `ensure_clean()` 将 lib/ 与 resource/ 整体删除（`maa-dirs` 的 remove_dir_all
    后重建空目录），再直接往正式目录逐文件解压，无暂存目录、无完成标记、
    无回滚。官方 Windows 整包约 254 MiB、共 9367 个归档条目（其中 8843 个在
    resource/ 下），1800 秒偏紧；取 3600 以降低被超时强杀的概率。

    中断后的恢复依赖两道兜底：官方包将 MaaCore.dll 排在所有资源条目之后
    （本机核对 v6.9.5–v6.14.2 共 11 个包均如此），中断时动态库通常尚未落盘，
    core_version() 读不出版本，下一次 maa update 会重装；其次是 MAA GUI 覆盖安装。
    """
    assert MAAUpdateConfig().timeout_seconds >= 3600
