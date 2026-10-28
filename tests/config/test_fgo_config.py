"""game selector 与 FGO/MaaFgo 配置边界的契约测试。"""

import textwrap
from dataclasses import replace
from pathlib import Path

import pytest

from autogame_orchestrator.config_loader import load_config
from autogame_orchestrator.config_model import AppConfig, FgoConfig, GameSelection
from tests.fakes.maafgo_support import make_project


def write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "orchestrator.local.toml"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


# 顶层键必须出现在首个 table header 之前；game 行永远放在文件最前。
MINIMAL_STARRAIL = """\
    [orchestrator]
    log_dir = "logs"
    report_dir = "run-results"

    [mumu]
    executable = "C:/x/MuMuNxDevice.exe"
    adb_executable = "C:/x/adb.exe"
    adb_serial = "127.0.0.1:16384"

    [starrail]
    executable = "C:/x/python.exe"
    working_directory = "C:/x/StarRailCopilot"
    arguments = ["gui.py"]
    log_path_template = "log/{date}.txt"
    success_keywords = ["No task pending"]
    failure_keywords = ["ScriptError:"]
    [starrail.environment]
    PYTHONIOENCODING = "utf-8"

    [maa]
    executable = "C:/x/MAA.exe"
    working_directory = "C:/x/MAA"
    [maa.environment]
    PYTHONIOENCODING = "utf-8"
    """


def starrail_with_game(game_line: str = "") -> str:
    header = f"    {game_line}\n\n" if game_line else ""
    return header + MINIMAL_STARRAIL


def test_missing_game_key_defaults_to_starrail(tmp_path):
    path = write_config(tmp_path, starrail_with_game())
    config, errors = load_config(path)
    assert errors == []
    assert config is not None and config.game is GameSelection.STARRAIL


def test_explicit_starrail_ignores_maafgo_section(tmp_path):
    path = write_config(
        tmp_path,
        starrail_with_game('game = "starrail"')
        + '\n    [maafgo]\n    enabled = true\n    executable = "missing"\n    working_directory = "missing"\n    ',
    )
    config, errors = load_config(path)
    assert errors == []
    assert config is not None and config.game is GameSelection.STARRAIL
    # StarRail 链路不受 [maafgo] 段影响。
    assert config.validate() == []


@pytest.mark.parametrize("value", ['"mash"', '"FGO"', '"star-rail"', "1", "true", "false"])
def test_malformed_game_is_rejected(tmp_path, value):
    path = write_config(tmp_path, starrail_with_game(f"game = {value}"))
    config, errors = load_config(path)
    assert config is None and "CONFIG_SCHEMA_ERROR" in [error.value for error in errors]


def maafgo_lines(tmp_path: Path) -> str:
    project = make_project(tmp_path / "maafgo project")
    executable = str(project.executable).replace("\\", "/")
    working_directory = str(project.working_directory).replace("\\", "/")
    return f'\n    executable = "{executable}"\n    working_directory = "{working_directory}"\n    '


def fgo_config_body(tmp_path: Path) -> str:
    return (
        starrail_with_game('game = "fgo"')
        + "\n    [fgo]\n"
        + '    package_name = "com.bilibili.fatego"\n'
        + "\n    [maafgo]\n"
        + "    enabled = true\n"
        + maafgo_lines(tmp_path)
    )


def test_game_fgo_does_not_require_starrail_or_maa(tmp_path):
    path = write_config(
        tmp_path,
        textwrap.dedent(
            """\
            game = "fgo"

            [orchestrator]
            log_dir = "logs"
            report_dir = "run-results"

            [mumu]
            lifecycle_mode = "external"
            adb_executable = "C:/x/adb.exe"
            adb_serial = "127.0.0.1:16384"

            [fgo]
            package_name = "com.linekong.fgo.bilibili"

            [maafgo]
            enabled = true
            """
        )
        + maafgo_lines(tmp_path),
    )
    config, errors = load_config(path)
    assert errors == []
    assert config is not None
    assert config.game is GameSelection.FGO
    # starrail/maa 段整段缺省合法：FGO 链路不消费它们。
    assert config.starrail.executable == ""
    assert config.maa.executable == ""
    assert config.validate() == []


def test_game_fgo_requires_enabled_maafgo(tmp_path):
    path = write_config(
        tmp_path,
        textwrap.dedent(
            """\
            game = "fgo"

            [orchestrator]
            log_dir = "logs"
            report_dir = "run-results"

            [mumu]
            adb_executable = "C:/x/adb.exe"
            adb_serial = "127.0.0.1:16384"

            [fgo]
            package_name = "com.bilibili.fatego"
            """
        ),
    )
    config, errors = load_config(path)
    assert config is None
    assert "CONFIG_SCHEMA_ERROR" in [error.value for error in errors]


def test_game_fgo_full_config_loads(tmp_path):
    path = write_config(tmp_path, fgo_config_body(tmp_path))
    config, errors = load_config(path)
    assert errors == []
    assert config is not None
    assert config.game is GameSelection.FGO
    assert config.fgo.provider == "maafgo"
    assert config.fgo.stop_game_on_exit is True
    assert config.maafgo.enabled is True
    assert config.validate() == []


@pytest.mark.parametrize(
    "package",
    [
        "",
        "com.bilibili.fatego; rm -rf /",
        "com.bilibili.fatego extra",
        "bilibili.fatego",
        "com.bilibili..fatego",
        "1com.bilibili.fatego",
        "com.bilibili.fatego$",
        "com." + "a" * 60 + ".fatego",
        123,
        None,
    ],
)
def test_invalid_android_package_is_rejected(tmp_path, package):
    config = AppConfig(game=GameSelection.FGO, fgo=FgoConfig(package_name=package), maafgo=replace(_any_maafgo()))
    errors = config.validate()
    assert "CONFIG_SCHEMA_ERROR" in [error.value for error in errors]


def _any_maafgo():
    from autogame_orchestrator.maafgo_config import MaaFgoConfig

    return MaaFgoConfig(enabled=True, executable="C:/x/MaaPiCli.exe", working_directory="C:/x")


def test_valid_android_packages():
    for package in ("com.bilibili.fatego", "com.linekong.fgo.bilibili", "A.b", "a1.b2_c3.d4"):
        assert FgoConfig(package_name=package).validate() == []


@pytest.mark.parametrize("provider", ["", "mash", "MaaFgo", None])
def test_fgo_provider_must_be_maafgo(provider):
    assert FgoConfig(provider=provider).validate() != []


def test_fgo_adb_serial_stays_in_mumu_section(tmp_path):
    """[fgo]/[maafgo] 不提供第二份 ADB 设备真值。"""
    path = write_config(
        tmp_path,
        fgo_config_body(tmp_path)
        + '    \n    [fgo.extra]\n    adb_serial = "127.0.0.1:9999"\n    ',
    )
    config, errors = load_config(path)
    assert config is None and errors


def test_maafgo_section_unknown_fields_rejected(tmp_path):
    body = fgo_config_body(tmp_path) + '    adb_serial = "127.0.0.1:16384"\n    '
    path = write_config(tmp_path, body)
    config, errors = load_config(path)
    assert config is None and errors


def test_starrail_defaults_unchanged_without_game_key():
    config = AppConfig()
    assert config.game is GameSelection.STARRAIL
    assert config.validate() != []  # 默认 StarRail 段仍要求完整配置
    assert config.maafgo.enabled is False
