"""Offline fixtures only: no real executable is ever started."""

import copy
import hashlib
import importlib.util
import json
import struct
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/prepare_maafgo_cli_smoke.py"
spec = importlib.util.spec_from_file_location("prepare_maafgo_cli_smoke", SCRIPT)
assert spec and spec.loader
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)

ORR_DIR = SCRIPT.parent / "maafgo-orr-agent"
PINNED_MAIN = (ORR_DIR / "agent-main.pinned.py").read_bytes()


def pe(machine=0x8664):
    data = bytearray(256)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 64)
    data[64:68] = b"PE\0\0"
    struct.pack_into("<H", data, 68, machine)
    struct.pack_into("<H", data, 88, 0x20B)
    return bytes(data)


@pytest.fixture
def materials():
    framework = {"bin/" + n: pe() for n in (*tool.REQUIRED_DLLS, "MaaPiCli.exe")}
    framework["share/MaaAgentBinary/android/x86_64/minitouch"] = b"ELF fixture"
    interface = {"agent": {"child_exec": "python", "child_args": ["../agent/main.py"]},
                 "controller": [{"name": "test", "type": "Adb"}],
                 "resource": [{"path": ["resource/base"]}], "import": ["tasks/daily.json"]}
    fgo = {"snapshot/assets/interface.json": json.dumps(interface).encode(),
           "snapshot/assets/tasks/daily.json": b'{"task": []}',
           "snapshot/assets/resource/base/pipeline.json": b"{}",
           "snapshot/agent/main.py": PINNED_MAIN,
           **{f"snapshot/{rel}": b"bbc module fixture" for rel in tool.BBC_MODULE_RELS},
           "snapshot/config/maa_pi_config.json": b"PRODUCTION_SECRET",
           "snapshot/unrelated.txt": b"PRIVATE"}
    python = {"python.exe": pe(), "python312.dll": pe(), "python312.zip": b"stdlib",
              "python312._pth": b"python312.zip\n.\n#import site\n"}
    wheel = {"maa/__init__.py": b"", "maa/bin/MaaFramework.dll": pe()}
    return framework, fgo, python, [wheel]


def test_deterministic_transform_and_source_unchanged(materials, tmp_path):
    before = copy.deepcopy(materials)
    files, transformation = tool.build_files(*materials)
    assert materials == before
    assert (files, transformation) == tool.build_files(*materials)
    document = json.loads(files["interface.json"])
    assert tool.transform_interface(document) == document
    original = json.loads(materials[1]["snapshot/assets/interface.json"])
    assert {k: v for k, v in document.items() if k != "agent"} == {
        k: v for k, v in original.items() if k != "agent"
    }
    assert not any(b"PRODUCTION_SECRET" in value or b"PRIVATE" in value for value in files.values())
    manifest = {"files": [{"path": n, "sha256": tool.digest(v)} for n, v in sorted(files.items())]}
    tool.write_distribution(tmp_path / "one", files, manifest)
    tool.write_distribution(tmp_path / "two", files, manifest)
    assert (tmp_path / "one/distribution-manifest.json").read_bytes() == (
        tmp_path / "two/distribution-manifest.json"
    ).read_bytes()
    assert str(tmp_path).encode() not in tool.json_bytes(manifest)


@pytest.mark.parametrize(("index", "name", "code"), [
    (0, "bin/MaaPiCli.exe", "MISSING_REQUIRED_FILE"),
    (0, "bin/MaaToolkit.dll", "MISSING_REQUIRED_FILE"),
    (0, "share/MaaAgentBinary/android/x86_64/minitouch", "MISSING_AGENT_BINARY"),
    (1, "snapshot/agent/main.py", "MISSING_REQUIRED_FILE"),
    (1, "snapshot/assets/tasks/daily.json", "MISSING_INTERFACE_IMPORT"),
    (1, "snapshot/assets/resource/base/pipeline.json", "MISSING_RESOURCE"),
    (2, "python.exe", "MISSING_REQUIRED_FILE"),
    (2, "python312.dll", "MISSING_REQUIRED_FILE"),
])
def test_missing_material(materials, index, name, code):
    del materials[index][name]
    with pytest.raises(tool.AssemblyError, match=code):
        tool.build_files(*materials)


def test_wrong_architecture(materials):
    materials[0]["bin/MaaPiCli.exe"] = pe(0x14C)
    with pytest.raises(tool.AssemblyError, match="WRONG_PE_ARCHITECTURE"):
        tool.build_files(*materials)


def test_binding_mismatch(materials):
    materials[3][0]["maa/bin/MaaFramework.dll"] += b"different build"
    with pytest.raises(tool.AssemblyError, match="PYTHON_NATIVE_VERSION_PAIR_UNRESOLVED"):
        tool.build_files(*materials)


def test_missing_binding(materials):
    with pytest.raises(tool.AssemblyError, match="MISSING_PYTHON_BINDING_NATIVE"):
        tool.build_files(*materials[:3], [])


def test_no_overwrite_or_cleanup(tmp_path):
    target = tmp_path / "output"
    target.mkdir()
    sentinel = target / "user-file"
    sentinel.write_text("keep")
    outside = tmp_path / "outside"
    outside.write_text("keep")
    with pytest.raises(tool.AssemblyError, match="DESTINATION_NOT_EMPTY"):
        tool.write_distribution(target, {"new": b"no"}, {})
    assert sentinel.read_text() == outside.read_text() == "keep"
    assert not (target / "new").exists()


@pytest.mark.parametrize("name", ["../outside", "/absolute", "C:/private", "a\\b", "x:stream",
                                  "NUL.txt", "dir/file.", "a//b"])
def test_archive_escape_rejected(tmp_path, name):
    source = tmp_path / "input.zip"
    with zipfile.ZipFile(source, "w") as z:
        z.writestr(name, b"payload")
    if "\\" in name:
        # ZipInfo normalizes separators on Windows; emulate an external archive.
        source.write_bytes(source.read_bytes().replace(name.replace("\\", "/").encode(), name.encode()))
    with pytest.raises(tool.AssemblyError, match="UNSAFE_RELATIVE_PATH"):
        tool.archive(source, tool.digest(source.read_bytes()))
    assert not (tmp_path / "outside").exists()


def test_archive_hash_and_missing_input(tmp_path):
    source = tmp_path / "input.zip"
    with pytest.raises(tool.AssemblyError, match="MISSING_INPUT_ARCHIVE"):
        tool.archive(source, "0" * 64)
    with zipfile.ZipFile(source, "w") as z:
        z.writestr("valid", b"payload")
    with pytest.raises(tool.AssemblyError, match="SHA256_MISMATCH"):
        tool.archive(source, "0" * 64)
    assert tool.archive(source, hashlib.sha256(source.read_bytes()).hexdigest()) == {"valid": b"payload"}


def test_case_collision(tmp_path):
    source = tmp_path / "input.zip"
    with zipfile.ZipFile(source, "w") as z:
        z.writestr("File", b"a")
        z.writestr("file", b"b")
    with pytest.raises(tool.AssemblyError, match="ARCHIVE_COLLISION"):
        tool.archive(source, tool.digest(source.read_bytes()))


def test_unexpected_agent_rejected():
    with pytest.raises(tool.AssemblyError, match="UNEXPECTED_AGENT_CONTRACT"):
        tool.transform_interface({"agent": {"child_exec": "unexpected.exe"}})


def test_executable_pth_rejected(materials):
    materials[3][0]["startup.pth"] = b"import external_effect"
    with pytest.raises(tool.AssemblyError, match="UNSUPPORTED_WHEEL_LAYOUT"):
        tool.build_files(*materials)


def test_orr_transform_replaces_agent_and_drops_bbc(materials):
    files, transformation = tool.build_files(*materials)
    pinned, orr_main, reporter = tool.load_orr_agent_materials()
    assert files["agent/main.py"] == orr_main and files["agent/main.py"] != pinned
    assert files["agent/orr_reporter.py"] == reporter
    for rel in tool.BBC_MODULE_RELS:
        assert rel not in files
        assert f"snapshot/{rel}" in materials[1]  # source snapshot untouched
    orr = transformation["orr_transform"]
    assert orr["transform_id"] == tool.ORR_TRANSFORM_ID
    assert orr["transform_version"] == 1
    assert orr["agent_main_source_sha256"] == tool.PINNED_AGENT_MAIN_SHA
    assert orr["agent_main_result_sha256"] == tool.digest(orr_main)
    assert orr["orr_reporter_sha256"] == tool.digest(reporter)
    assert orr["bbc_listener_registered"] is False and orr["reporter_registered"] is True
    assert orr["bbc_modules_removed"] == list(tool.BBC_MODULE_RELS)
    # ORR main is exactly pinned-main minus the BBC imports plus the reporter import.
    dropped = [line for line in pinned.splitlines() if line.startswith(b"import bbc_")]
    assert len(dropped) == 4
    orr_reporter_line = next(
        line + b"\n" for line in orr_main.splitlines() if line.startswith(b"import orr_reporter")
    )
    rebuilt = pinned.replace(dropped[0] + b"\r\n", b"").replace(dropped[0] + b"\n", b"")
    for line in dropped[1:]:
        rebuilt = rebuilt.replace(line + b"\r\n", b"").replace(line + b"\n", b"")
    rebuilt = rebuilt.replace(
        b"import auto_battle_repeat_action\n",
        b"import auto_battle_repeat_action\n" + orr_reporter_line,
        1,
    )
    assert rebuilt == orr_main


def test_agent_main_source_mismatch_fails_closed(materials):
    materials[1]["snapshot/agent/main.py"] = PINNED_MAIN + b"# drift\n"
    with pytest.raises(tool.AssemblyError, match="AGENT_MAIN_SOURCE_MISMATCH"):
        tool.build_files(*materials)


def test_orr_agent_materials_are_compilable_python():
    """ADR-0003「native Agent import 面保持」的回归护栏：ORR 变换产物
    （agent-main.orr.py / orr_reporter.py）必须仍是可编译的 Python。
    内存编译，不写任何文件。"""
    _, orr_main, reporter = tool.load_orr_agent_materials()
    compile(orr_main, "agent/main.py", "exec")
    compile(reporter, "agent/orr_reporter.py", "exec")


def test_missing_bbc_module_layout_fails_closed(materials):
    del materials[1]["snapshot/agent/custom/bbc_stop_listener.py"]
    with pytest.raises(tool.AssemblyError, match="BBC_MODULE_LAYOUT_UNEXPECTED"):
        tool.build_files(*materials)


def test_pinned_reference_hash_guard(tmp_path):
    import shutil

    target = tmp_path / "orr-agent"
    shutil.copytree(ORR_DIR, target)
    (target / "agent-main.pinned.py").write_bytes(b"tampered")
    original_dir = tool.ORR_AGENT_DIR
    tool.ORR_AGENT_DIR = target
    try:
        with pytest.raises(tool.AssemblyError, match="PINNED_AGENT_MAIN_SHA_MISMATCH"):
            tool.load_orr_agent_materials()
    finally:
        tool.ORR_AGENT_DIR = original_dir


def test_repo_pinned_reference_matches_constant():
    assert tool.digest(PINNED_MAIN) == tool.PINNED_AGENT_MAIN_SHA
    # 与 maafgo_config 的生产分发校验共用同一 pinned commit 身份（该常量在
    # maafgo_config.py 中独立声明；此处防止两者漂移）。
    config_source = (
        Path(__file__).resolve().parents[2] / "src/autogame_orchestrator/maafgo_config.py"
    ).read_text(encoding="utf-8")
    assert tool.FGO_COMMIT in config_source
    assert tool.ORR_TRANSFORM_ID in config_source
