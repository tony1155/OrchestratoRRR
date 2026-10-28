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
           "snapshot/agent/main.py": b"# never execute\n",
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
