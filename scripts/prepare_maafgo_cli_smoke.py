"""Offline, dev-only MaaFgo assembly. Never executes or downloads its inputs.

Use the reviewed lock beside this script. Output must be outside the repository.
An interrupted write is deliberately retained for inspection; it cannot be reused.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import stat
import struct
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import TypeAlias, cast

FileMap: TypeAlias = dict[str, bytes]
JsonObject: TypeAlias = dict[str, object]
Manifest: TypeAlias = dict[str, object]

FRAMEWORK_VERSION = "v5.13.0"
FRAMEWORK_COMMIT = "2bcfa85c66a2eac6ca3e5937f175495275ee0643"
FRAMEWORK_SHA = "179b51b6211fc74317c8dc06f10fae4724aca370df7d1bf694cd00d06ff38efe"
FGO_COMMIT = "d7f3a474f50b9a0631ee9acd6df67998c1933f2b"
FGO_SHA = "d21e0ec90e4aecce87d950c0ac04b72f46cce1bfd55e4a0488d29a86163f247b"
PYTHON_SHA = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
BINDING_SHA = "105c22431183446d350864b946fb9448f47fd9d73a20e4b46e276ea2a22067e5"
REQUIRED_DLLS = (
    "MaaFramework.dll", "MaaAgentClient.dll", "MaaAgentServer.dll", "MaaToolkit.dll",
    "MaaUtils.dll", "MaaAdbControlUnit.dll", "onnxruntime_maa.dll", "opencv_world4_maa.dll",
    "fastdeploy_ppocr_maa.dll", "DirectML.dll",
)


class AssemblyError(ValueError):
    """Stable path-free diagnostic; never includes untrusted input text."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_name(name: str) -> str:
    parts = name.split("/")
    if not name or "\\" in name or any(
        not p or p in {".", ".."} or p.endswith((" ", "."))
        or any(c in p for c in ':<>"|?*') or any(ord(c) < 32 for c in p)
        or re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", p)
        for p in parts
    ):
        raise AssemblyError("UNSAFE_RELATIVE_PATH")
    return name


def reject_links(path: Path) -> None:
    for candidate in (path, *path.parents):
        if candidate.exists() or candidate.is_symlink():
            info = candidate.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise AssemblyError("REPARSE_POINT_REJECTED")


def archive(path: Path, expected_sha: str) -> dict[str, bytes]:
    reject_links(path)
    if not path.is_file():
        raise AssemblyError("MISSING_INPUT_ARCHIVE")
    if not re.fullmatch("[0-9a-f]{64}", expected_sha):
        raise AssemblyError("INVALID_SHA256")
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != expected_sha:
            raise AssemblyError("SHA256_MISMATCH")
        stream.seek(0)
        with zipfile.ZipFile(stream) as source:
            if len(source.infolist()) > 50000 or sum(i.file_size for i in source.infolist()) > 2_000_000_000:
                raise AssemblyError("ARCHIVE_LIMIT")
            result: dict[str, bytes] = {}
            seen: set[str] = set()
            for item in source.infolist():
                name = safe_name(item.orig_filename.rstrip("/"))
                if stat.S_ISLNK(item.external_attr >> 16):
                    raise AssemblyError("ARCHIVE_LINK_REJECTED")
                if name.casefold() in seen:
                    raise AssemblyError("ARCHIVE_COLLISION")
                seen.add(name.casefold())
                if not item.is_dir():
                    result[name] = source.read(item)
            return result


def pe_machine(data: bytes) -> int:
    try:
        if data[:2] != b"MZ":
            raise AssemblyError("INVALID_PE")
        offset = int(struct.unpack_from("<I", data, 0x3C)[0])
        if data[offset:offset + 4] != b"PE\0\0":
            raise AssemblyError("INVALID_PE")
        machine = int(struct.unpack_from("<H", data, offset + 4)[0])
        if machine != 0x8664:
            raise AssemblyError("WRONG_PE_ARCHITECTURE")
        if int(struct.unpack_from("<H", data, offset + 24)[0]) != 0x20B:
            raise AssemblyError("INVALID_PE64")
        return machine
    except (IndexError, struct.error):
        raise AssemblyError("TRUNCATED_PE") from None


def transform_interface(original: JsonObject) -> JsonObject:
    result = copy.deepcopy(original)
    agent = result.get("agent")
    source: JsonObject = {"child_exec": "python", "child_args": ["../agent/main.py"]}
    target: JsonObject = {"child_exec": "./python/python.exe", "child_args": ["-u", "./agent/main.py"]}
    if agent not in (source, target):
        raise AssemblyError("UNEXPECTED_AGENT_CONTRACT")
    result["agent"] = target
    return result


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def validate_project(files: FileMap) -> None:
    required = ["MaaPiCli.exe", *REQUIRED_DLLS, "interface.json", "agent/main.py",
                "python/python.exe", "python/python312.dll", "python/python312.zip",
                "python/Lib/site-packages/maa/__init__.py"]
    if any(name not in files for name in required):
        raise AssemblyError("MISSING_REQUIRED_FILE")
    if not any(n.startswith("MaaAgentBinary/") and n.endswith("minitouch") for n in files):
        raise AssemblyError("MISSING_AGENT_BINARY")
    pending = ["interface.json"]
    visited: set[str] = set()
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        visited.add(name)
        if name not in files:
            raise AssemblyError("MISSING_INTERFACE_IMPORT")
        try:
            document = json.loads(files[name])
        except (ValueError, UnicodeError):
            raise AssemblyError("INVALID_INTERFACE_JSON") from None
        if not isinstance(document, dict):
            raise AssemblyError("INVALID_INTERFACE_SHAPE")
        # Pinned MaaPiCli Parser resolves all imports from the project root.
        for imported in document.get("import", []):
            pending.append(safe_name(imported))
        for resource in document.get("resource", []):
            for directory in resource["path"]:
                prefix = safe_name(directory) + "/"
                if not any(n.startswith(prefix) for n in files):
                    raise AssemblyError("MISSING_RESOURCE")
    for name, data in files.items():
        if PurePosixPath(name).suffix.lower() in {".exe", ".dll", ".pyd", ".node"}:
            pe_machine(data)


def build_files(framework: FileMap, fgo: FileMap, python: FileMap,
                wheels: list[FileMap]) -> tuple[FileMap, JsonObject]:
    files: FileMap = {}
    folded: set[str] = set()

    def put(name: str, data: bytes) -> None:
        safe_name(name)
        if name.casefold() in folded:
            raise AssemblyError("OUTPUT_COLLISION")
        if any(p.casefold() in {"config", "debug", "__pycache__"} for p in name.split("/")):
            raise AssemblyError("FORBIDDEN_SOURCE_STATE")
        files[name] = data
        folded.add(name.casefold())

    for name, data in sorted(framework.items()):
        if name.startswith("bin/"):
            put(name[4:], data)
        elif name.startswith("share/MaaAgentBinary/"):
            put(name[6:], data)
        elif name == "LICENSE.md":
            put("licenses/MaaFramework-LICENSE.md", data)
    roots = {name.split("/")[0] for name in fgo}
    if len(roots) != 1:
        raise AssemblyError("INVALID_FGO_SNAPSHOT_ROOT")
    for name, data in sorted(fgo.items()):
        relative = name.split("/", 1)[-1]
        if relative.startswith("assets/"):
            relative = relative[7:]
            if relative.split("/")[0] in {"resource", "tasks", "options", "i18n"} or relative in {
                "interface.json", "Announcement.md",
            }:
                put(relative, data)
        elif relative.startswith("agent/") or relative in {"requirements.txt", "LICENSE", "README.md"}:
            put(relative, data)
        # bbcdll contains a replacement _ctypes and BBC server; never install it
        # into Python. No BBchannel executable is required for this no-business bundle.
    for name, data in sorted(python.items()):
        put("python/" + name, data)
    binding_seen = False
    for wheel in wheels:
        for name, data in sorted(wheel.items()):
            if name == "sympy-1.14.0.data/data/share/man/man1/isympy.1":
                put("python/share/man/man1/isympy.1", data)
                continue
            if ".data/" in name or (name.endswith(".pth") and name != "coloredlogs.pth"):
                raise AssemblyError("UNSUPPORTED_WHEEL_LAYOUT")
            if name.startswith("maa/bin/"):
                counterpart = name[len("maa/bin/"):]
                if files.get(counterpart) != data:
                    raise AssemblyError("PYTHON_NATIVE_VERSION_PAIR_UNRESOLVED")
                binding_seen = True
            put("python/Lib/site-packages/" + name, data)
    if not binding_seen:
        raise AssemblyError("MISSING_PYTHON_BINDING_NATIVE")
    if "interface.json" not in files:
        raise AssemblyError("MISSING_INTERFACE")
    original = json.loads(files["interface.json"])
    files["interface.json"] = json_bytes(transform_interface(original))
    # Isolated search path, no user site, PYTHONPATH, executable .pth, or get-pip.
    pth = "python/python312._pth"
    if pth not in files:
        raise AssemblyError("MISSING_PYTHON_PATH_CONFIG")
    files[pth] = b"python312.zip\n.\nLib/site-packages\n../agent\n"
    validate_project(files)
    transformed = transform_interface(original)
    return files, {"agent_before": original["agent"], "agent_after": transformed["agent"],
                   "python_path": ["python312.zip", ".", "Lib/site-packages", "../agent"],
                   "site_enabled": False, "bbc_installed": False,
                   "inert_pth": ["coloredlogs.pth"],
                   "wheel_data_mapping": {"sympy-1.14.0.data/data/share/man/man1/isympy.1":
                                          "python/share/man/man1/isympy.1"}}


def write_distribution(destination: Path, files: FileMap, manifest: Manifest) -> None:
    reject_links(destination)
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise AssemblyError("DESTINATION_NOT_EMPTY")
    # Only a private, quiescent output parent is supported. No cleanup on error.
    destination.mkdir(parents=True, exist_ok=True)
    for name, data in sorted(files.items()):
        output = destination / safe_name(name)
        reject_links(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as stream:
            stream.write(data)
        if digest(output.read_bytes()) != digest(data):
            raise AssemblyError("OUTPUT_HASH_MISMATCH")
    with (destination / "distribution-manifest.json").open("xb") as stream:
        stream.write(json_bytes(manifest))


def assemble(framework: Path, fgo: Path, python: Path, wheel_dir: Path, destination: Path) -> Manifest:
    reject_links(destination)
    if destination.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
        raise AssemblyError("DESTINATION_INSIDE_REPOSITORY")
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise AssemblyError("DESTINATION_NOT_EMPTY")
    lock = cast(JsonObject, json.loads(Path(__file__).with_name("maafgo-smoke-wheels.lock.json").read_bytes()))
    raw_wheels = lock.get("wheels")
    if not isinstance(raw_wheels, list):
        raise AssemblyError("INVALID_WHEEL_LOCK")
    wheels: list[FileMap] = []
    for item in raw_wheels:
        if not isinstance(item, dict):
            raise AssemblyError("INVALID_WHEEL_LOCK")
        filename_value = item.get("filename")
        sha_value = item.get("sha256")
        if not isinstance(filename_value, str) or not isinstance(sha_value, str):
            raise AssemblyError("INVALID_WHEEL_LOCK")
        filename = safe_name(filename_value)
        if "/" in filename:
            raise AssemblyError("INVALID_WHEEL_NAME")
        if filename == "maafw-5.13.0-py3-none-win_amd64.whl" and sha_value != BINDING_SHA:
            raise AssemblyError("INVALID_BINDING_LOCK")
        wheels.append(archive(wheel_dir / filename, sha_value))
    files, transformation = build_files(archive(framework, FRAMEWORK_SHA), archive(fgo, FGO_SHA),
                                        archive(python, PYTHON_SHA), wheels)
    manifest = {
        "schema_version": 1, "maaframework_version": FRAMEWORK_VERSION,
        "maaframework_release_commit": FRAMEWORK_COMMIT, "maaframework_zip_sha256": FRAMEWORK_SHA,
        "maafgo_commit": FGO_COMMIT, "maafgo_zip_sha256": FGO_SHA,
        "python_version": "3.12.10", "python_zip_sha256": PYTHON_SHA,
        "maafw_version": "5.13.0", "platform": "windows", "architecture": "x86_64",
        "wheels": raw_wheels, "transformation": transformation,
        "native_resolution": "RUNTIME_DLL_RESOLUTION_REQUIRES_GATE_B",
        "gate_a": "FILESYSTEM_PASS_RUNTIME_PENDING", "business_ready": False,
        "files": [{"path": n, "sha256": digest(d), "size": len(d)} for n, d in sorted(files.items())],
    }
    write_distribution(destination, files, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("framework", "maafgo", "python", "wheels", "output"):
        parser.add_argument("--" + option, required=True, type=Path)
    args = parser.parse_args()
    try:
        result = assemble(args.framework, args.maafgo, args.python, args.wheels, args.output)
    except AssemblyError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile):
        print("ASSEMBLY_FAILED", file=sys.stderr)
        return 1
    print(json.dumps({"status": result["gate_a"], "file_count": len(cast(list[object], result["files"]))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
