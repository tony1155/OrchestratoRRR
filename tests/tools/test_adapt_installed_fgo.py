import ast
import json

import pytest

from scripts.adapt_installed_fgo import adapt_main, compatible_scan_select, resource_completion_overlay


def test_adapted_entry_preserves_native_imports_and_separates_gui_from_workflow():
    source = """import os
IS_ANDROID = False
if not IS_ANDROID:
    import bbc_action
    import bbc_start
    import bbc_stop
    import bbc_stop_listener
    import chaldea_import_action
    import battle_editor_action
import auto_battle_action
"""
    adapted = adapt_main(source)
    imported = []

    class FakeOs:
        environ = {}

    def fake_import(name, *args):
        imported.append(name)
        return FakeOs if name == "os" else object()

    for workflow in (False, True):
        imported.clear()
        FakeOs.environ = {"ORR_MAAFGO_RUN_ID": "test"} if workflow else {}
        exec(compile(ast.parse(adapted), "agent/main.py", "exec"), {"__builtins__": {"__import__": fake_import}})
        assert "auto_battle_action" in imported
        assert "chaldea_import_action" in imported
        assert ("bbc_stop_listener" in imported) is not workflow
        assert ("orr_reporter" in imported) is workflow
    assert adapt_main(adapted) == adapted


def test_unknown_entry_is_rejected():
    with pytest.raises(ValueError):
        adapt_main("import unexpected_upstream\n")


def test_existing_adapter_also_inserts_agent_module_search_path():
    source = """import sys
import os
AGENT_ROOT = os.path.dirname(os.path.abspath(__file__))
# ORR installed-runtime integration v1
"""
    result = adapt_main(source)
    assert "sys.path.insert(0, AGENT_ROOT)" in result
    assert adapt_main(result) == result


def test_scan_select_becomes_standard_select_with_concrete_overrides():
    source = {"type": "scan_select", "pipeline_override": {"node": {"attach": {"team": "{team}"}}}}
    result = compatible_scan_select("team", source, ["b.json", "a.json"])
    assert source["type"] == "scan_select"
    assert result["type"] == "select"
    assert result["cases"][0] == {"name": "a.json", "pipeline_override": {"node": {"attach": {"team": "a.json"}}}}
    assert result["default_case"] == "a.json"
    assert "pipeline_override" not in result


def test_scan_select_empty_directory_has_a_valid_disabled_value():
    result = compatible_scan_select("team", {"type": "scan_select"}, [])
    assert result["default_case"] == result["cases"][0]["name"]


def test_resource_overlay_only_completes_explicit_shortages(tmp_path):
    pipeline = tmp_path / "resource/base/pipeline"
    pipeline.mkdir(parents=True)
    original = {
        "风暴罐不足": {"recognition": {"type": "TemplateMatch"}, "next": ["回主界面"]},
        "风暴罐不足2": {"recognition": {"type": "OCR"}, "next": ["回主界面"]},
        "战斗中": {"next": ["继续", "[JumpBack]全局-战前吃体力"], "on_error": []},
        "错误出口": {"enabled": False, "on_error": []},
    }
    source = pipeline / "Dummy.json"
    source.write_text(json.dumps(original), "utf-8")
    before = source.read_bytes()
    overlay = resource_completion_overlay(tmp_path)
    assert source.read_bytes() == before
    assert "错误出口" not in overlay
    assert overlay["战斗中"]["on_error"] == []
    assert overlay["战斗中"]["next"][:2] == ["风暴罐不足", "风暴罐不足2"]
    assert overlay["风暴罐不足"]["next"] == ["ORR-资源耗尽完成"]
    assert overlay["风暴罐不足2"]["recognition"]["param"]["expected"] == [r"风暴罐\s*不足"]
    assert overlay["ORR-资源耗尽完成"]["action"]["type"] == "StopTask"
