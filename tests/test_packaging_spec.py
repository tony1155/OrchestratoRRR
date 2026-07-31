"""Static contract checks for the controlled PyInstaller spec."""

from __future__ import annotations

import ast
from pathlib import Path

_SPEC = Path(__file__).resolve().parent.parent / "packaging" / "OrchestratoRRR.spec"


def _calls(source: str, name: str) -> list[ast.Call]:
    tree = ast.parse(source)
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name
    ]


def _keyword(call: ast.Call, name: str) -> ast.expr:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    raise AssertionError(f"missing keyword: {name}")


def _literal(node: ast.expr) -> object:
    assert isinstance(node, ast.Constant)
    return node.value


def _attribute(node: ast.expr, base: str, attribute: str) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == base
        and node.attr == attribute
    )


def test_spec_is_a_minimal_onedir_console_definition() -> None:
    source = _SPEC.read_text(encoding="utf-8")

    analysis = _calls(source, "Analysis")
    pyz = _calls(source, "PYZ")
    exe = _calls(source, "EXE")
    collect = _calls(source, "COLLECT")
    assert len(analysis) == len(pyz) == len(exe) == len(collect) == 1

    analysis_call = analysis[0]
    pathex = _keyword(analysis_call, "pathex")
    assert isinstance(pathex, ast.List)
    assert len(pathex.elts) == 1
    assert isinstance(pathex.elts[0], ast.Call)
    assert isinstance(pathex.elts[0].func, ast.Name) and pathex.elts[0].func.id == "str"
    assert isinstance(pathex.elts[0].args[0], ast.Name) and pathex.elts[0].args[0].id == "source_root"

    datas = _keyword(analysis_call, "datas")
    assert isinstance(datas, ast.List) and len(datas.elts) == 1
    mapping = datas.elts[0]
    assert isinstance(mapping, ast.Tuple) and len(mapping.elts) == 2
    assert isinstance(mapping.elts[0], ast.Call)
    assert isinstance(mapping.elts[0].func, ast.Name) and mapping.elts[0].func.id == "str"
    assert isinstance(mapping.elts[0].args[0], ast.Name) and mapping.elts[0].args[0].id == "schema"
    assert isinstance(mapping.elts[1], ast.Constant)
    assert mapping.elts[1].value == "autogame_orchestrator/_resources"

    exe_call = exe[0]
    assert len(exe_call.args) == 3
    assert isinstance(exe_call.args[0], ast.Name) and exe_call.args[0].id == "pyz"
    assert _attribute(exe_call.args[1], "a", "scripts")
    assert isinstance(exe_call.args[2], ast.List) and not exe_call.args[2].elts
    assert _literal(_keyword(exe_call, "exclude_binaries")) is True
    assert _literal(_keyword(exe_call, "console")) is True
    assert _literal(_keyword(exe_call, "upx")) is False
    assert _literal(_keyword(exe_call, "strip")) is False
    assert _literal(_keyword(exe_call, "debug")) is False
    assert _literal(_keyword(exe_call, "name")) == "OrchestratoRRR"

    collect_call = collect[0]
    assert len(collect_call.args) == 3
    assert isinstance(collect_call.args[0], ast.Name) and collect_call.args[0].id == "exe"
    assert _attribute(collect_call.args[1], "a", "binaries")
    assert _attribute(collect_call.args[2], "a", "datas")
    assert _literal(_keyword(collect_call, "strip")) is False
    assert _literal(_keyword(collect_call, "upx")) is False
    assert _literal(_keyword(collect_call, "name")) == "OrchestratoRRR"


def test_spec_does_not_use_broad_collection_or_unapproved_inputs() -> None:
    source = _SPEC.read_text(encoding="utf-8")

    assert "a." + "splash" not in source
    assert "S" + "plash(" not in source
    assert "pyi_" + "splash" not in source
    assert "--" + "splash" not in source
    assert "collect_all(" not in source
    assert "collect_submodules(" not in source
    assert "collect_data_files(" not in source
    assert 'datas=[(".", ".")]' not in source
    assert "sys._MEIPASS" not in source
    assert "real-config" not in source
    assert "run-results" not in source
    assert 'excludes=["tests", "docs", "config"]' in source

    assert not _calls(source, "Splash")
    assert not _calls(source, "BUNDLE")
    assert not _calls(source, "MERGE")
