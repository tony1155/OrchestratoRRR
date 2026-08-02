from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKUP_SCRIPT = ROOT / "scripts" / "backup-product-data.ps1"
UPDATE_SCRIPT = ROOT / "scripts" / "update-default-entry.ps1"
MODULE = ROOT / "scripts" / "lib" / "DefaultEntryMaintenance.psm1"
SCHEMA_RELATIVE = Path("_internal/autogame_orchestrator/_resources/run-report-v1.schema.json")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _tree_snapshot(root: Path) -> dict[str, tuple[int, str]]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): (path.stat().st_size, _sha256(path))
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _run(arguments: list[str], environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        arguments,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        shell=False,
        creationflags=0,
        env=environment,
        timeout=30,
    )


def _powershell_file(
    script: Path,
    parameters: list[str],
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            *parameters,
        ],
        environment,
    )


def _make_onedir(root: Path, marker: str) -> None:
    (root / SCHEMA_RELATIVE.parent).mkdir(parents=True)
    (root / "OrchestratoRRR.exe").write_bytes(f"exe-{marker}".encode())
    (root / SCHEMA_RELATIVE).write_bytes(f"schema-{marker}".encode())
    (root / "_internal" / "runtime.dat").write_bytes(f"runtime-{marker}".encode())


def _create_shortcut(environment: dict[str, str], target: Path, runtime: Path) -> Path:
    shortcut = (
        Path(environment["APPDATA"])
        / "Microsoft/Windows/Start Menu/Programs/OrchestratoRRR/OrchestratoRRR.lnk"
    )
    shortcut.parent.mkdir(parents=True)
    env = environment.copy()
    env.update(TEST_SHORTCUT=str(shortcut), TEST_TARGET=str(target), TEST_RUNTIME=str(runtime))
    command = (
        "$shell=New-Object -ComObject WScript.Shell;"
        "$link=$shell.CreateShortcut($env:TEST_SHORTCUT);"
        "$link.TargetPath=$env:TEST_TARGET;$link.Arguments='start';"
        "$link.WorkingDirectory=$env:TEST_RUNTIME;$link.Description='OrchestratoRRR';$link.Save()"
    )
    result = _run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command], env)
    assert result.returncode == 0, result.stderr
    return shortcut


@dataclass
class SyntheticEnvironment:
    root: Path
    environment: dict[str, str]
    local_app_data: Path
    app_data: Path
    product: Path
    install: Path
    source: Path
    backup_root: Path
    shortcut: Path

    @property
    def current_exe_hash(self) -> str:
        return _sha256(self.install / "OrchestratoRRR.exe")

    @property
    def source_exe_hash(self) -> str:
        return _sha256(self.source / "OrchestratoRRR.exe")

    @property
    def source_schema_hash(self) -> str:
        return _sha256(self.source / SCHEMA_RELATIVE)

    @property
    def source_file_count(self) -> int:
        return len(_tree_snapshot(self.source))


@pytest.fixture
def synthetic(tmp_path: Path) -> SyntheticEnvironment:
    real_local = Path(os.environ["LOCALAPPDATA"]).resolve()
    local = (tmp_path / "synthetic-localappdata").resolve()
    app = (tmp_path / "synthetic-appdata").resolve()
    assert local != real_local
    local.mkdir()
    app.mkdir()
    product = local / "OrchestratoRRR"
    (product / "config").mkdir(parents=True)
    (product / "logs").mkdir()
    (product / "run-results").mkdir()
    (product / "config/orchestrator.toml").write_text("[safe]\nvalue = true\n", encoding="utf-8")
    (product / "logs/run.jsonl").write_text('{"event":"test"}\n', encoding="utf-8")
    (product / "run-results/report.json").write_text('{"status":"failure"}\n', encoding="utf-8")
    assert not (product / "runtime").exists()
    install = local / "Programs/OrchestratoRRR"
    source = tmp_path / "source-onedir"
    backup_root = tmp_path / "backups"
    install.parent.mkdir(parents=True)
    source.mkdir()
    backup_root.mkdir()
    _make_onedir(install, "A")
    _make_onedir(source, "B")
    environment = os.environ.copy()
    environment.update(LOCALAPPDATA=str(local), APPDATA=str(app), NO_COLOR="1")
    shortcut = _create_shortcut(environment, install / "OrchestratoRRR.exe", product / "runtime")
    return SyntheticEnvironment(tmp_path, environment, local, app, product, install, source, backup_root, shortcut)


def _backup(
    item: SyntheticEnvironment,
    destination: Path | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any] | None]:
    destination = destination or item.backup_root
    result = _powershell_file(BACKUP_SCRIPT, ["-DestinationRoot", str(destination.resolve())], item.environment)
    payload = json.loads(result.stdout.splitlines()[-1]) if result.returncode == 0 else None
    return result, payload


def _update_parameters(
    item: SyntheticEnvironment,
    bundle: Path,
    manifest_hash: str,
    **overrides: object,
) -> list[str]:
    values: dict[str, object] = {
        "SourceOnedir": item.source.resolve(),
        "ProductDataBackup": bundle.resolve(),
        "ExpectedBackupManifestSha256": manifest_hash,
        "ExpectedCurrentExeSha256": item.current_exe_hash,
        "ExpectedSourceExeSha256": item.source_exe_hash,
        "ExpectedSourceSchemaSha256": item.source_schema_hash,
        "ExpectedSourceFileCount": item.source_file_count,
    }
    values.update(overrides)
    result: list[str] = []
    for key, value in values.items():
        result.extend([f"-{key}", str(value)])
    return result


def _prepare_backup(item: SyntheticEnvironment) -> tuple[Path, str]:
    result, payload = _backup(item)
    assert result.returncode == 0, result.stderr
    assert payload is not None
    return Path(payload["backup_directory"]), str(payload["manifest_sha256"])


def _public_update_with_file_count_expression(
    item: SyntheticEnvironment,
    bundle: Path,
    manifest_hash: str,
    expression: str,
) -> subprocess.CompletedProcess[str]:
    environment = {
        **item.environment,
        "UPDATE": str(UPDATE_SCRIPT),
        "SOURCE": str(item.source.resolve()),
        "BACKUP": str(bundle.resolve()),
        "BACKUP_HASH": manifest_hash,
        "CURRENT_HASH": item.current_exe_hash,
        "SOURCE_HASH": item.source_exe_hash,
        "SCHEMA_HASH": item.source_schema_hash,
    }
    command = (
        "try { & $env:UPDATE -SourceOnedir $env:SOURCE -ProductDataBackup $env:BACKUP "
        "-ExpectedBackupManifestSha256 $env:BACKUP_HASH -ExpectedCurrentExeSha256 $env:CURRENT_HASH "
        "-ExpectedSourceExeSha256 $env:SOURCE_HASH -ExpectedSourceSchemaSha256 $env:SCHEMA_HASH "
        f"-ExpectedSourceFileCount {expression}; exit $LASTEXITCODE }} "
        "catch { [Console]::Error.Write($_.Exception.Message); exit 2 }"
    )
    return _run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command], environment)


def _assert_rejected_without_changes(
    item: SyntheticEnvironment,
    bundle: Path,
    parameters: list[str],
    expected_error: str,
) -> None:
    install_before = _tree_snapshot(item.install)
    product_before = _tree_snapshot(item.product)
    source_before = _tree_snapshot(item.source)
    backup_before = _tree_snapshot(bundle)
    shortcut_before = item.shortcut.read_bytes()
    result = _powershell_file(UPDATE_SCRIPT, parameters, item.environment)
    assert result.returncode != 0
    assert expected_error in result.stderr
    assert _tree_snapshot(item.install) == install_before
    assert _tree_snapshot(item.product) == product_before
    assert _tree_snapshot(item.source) == source_before
    assert _tree_snapshot(bundle) == backup_before
    assert item.shortcut.read_bytes() == shortcut_before


def test_backup_success_preserves_source_and_writes_private_stable_manifest(synthetic: SyntheticEnvironment) -> None:
    source_before = _tree_snapshot(synthetic.product)
    result, payload = _backup(synthetic)
    assert result.returncode == 0, result.stderr
    assert payload is not None
    bundle = Path(payload["backup_directory"])
    manifest_bytes = (bundle / "manifest.json").read_bytes()
    assert not manifest_bytes.startswith(b"\xef\xbb\xbf")
    manifest = json.loads(manifest_bytes)
    assert manifest["format_version"] == 1
    assert manifest["directory_states"] == {
        "config": True,
        "runtime": False,
        "logs": True,
        "run-results": True,
    }
    paths = [entry["relative_path"] for entry in manifest["files"]]
    assert paths == sorted(paths)
    assert all(not Path(path).is_absolute() and ".." not in path.split("/") for path in paths)
    assert str(synthetic.root).casefold() not in manifest_bytes.decode("utf-8").casefold()
    assert "value = true" not in manifest_bytes.decode("utf-8")
    assert _sha256(bundle / "manifest.json") == (bundle / "manifest.sha256").read_text().strip()
    assert _tree_snapshot(synthetic.product) == source_before
    assert not (synthetic.product / "runtime").exists()


@pytest.mark.parametrize("location", ["product", "install", "product_child", "install_parent"])
def test_backup_rejects_related_destination(synthetic: SyntheticEnvironment, location: str) -> None:
    destinations = {
        "product": synthetic.product,
        "install": synthetic.install,
        "product_child": synthetic.product / "backup",
        "install_parent": synthetic.install.parent,
    }
    result, _ = _backup(synthetic, destinations[location])
    assert result.returncode != 0
    assert "BACKUP_DESTINATION_UNSAFE" in result.stderr


def test_backup_reparse_source_fails_closed(synthetic: SyntheticEnvironment) -> None:
    target = synthetic.root / "junction-target"
    target.mkdir()
    link = synthetic.product / "logs/junction"
    result = _run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "New-Item -ItemType Junction -Path $env:LINK -Target $env:TARGET | Out-Null",
        ],
        {**synthetic.environment, "LINK": str(link), "TARGET": str(target)},
    )
    if result.returncode != 0:
        pytest.skip("junction creation is unavailable")
    backup_result, _ = _backup(synthetic)
    assert backup_result.returncode != 0
    assert "BACKUP_REPARSE_POINT_FOUND" in backup_result.stderr


def test_backup_staging_failure_is_cleaned_and_old_bundle_is_preserved(synthetic: SyntheticEnvironment) -> None:
    _, payload = _backup(synthetic)
    assert payload is not None
    old_bundle = Path(payload["backup_directory"])
    old_snapshot = _tree_snapshot(old_bundle)
    environment = {**synthetic.environment, "MODULE": str(MODULE), "DESTINATION": str(synthetic.backup_root)}
    command = (
        "Import-Module $env:MODULE -Force;"
        "$hooks=@{BeforeBackupManifest={param($staging) "
        "[IO.File]::WriteAllText((Join-Path $staging 'config\\orchestrator.toml'),'tampered')}};"
        "try { & (Get-Module DefaultEntryMaintenance) { param($destination, $testHooks) "
        "Invoke-OrchestratoRRRProductDataBackupCore -DestinationRoot $destination -TestHooks $testHooks } "
        "$env:DESTINATION $hooks; exit 0 } "
        "catch { [Console]::Error.Write($_.Exception.Message); exit 2 }"
    )
    result = _run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command], environment)
    assert result.returncode != 0
    assert _tree_snapshot(old_bundle) == old_snapshot
    assert not list(synthetic.backup_root.glob(".*.staging"))


def test_update_success_replaces_only_install_and_leaves_no_residue(synthetic: SyntheticEnvironment) -> None:
    bundle, manifest_hash = _prepare_backup(synthetic)
    source_before = _tree_snapshot(synthetic.source)
    product_before = _tree_snapshot(synthetic.product)
    backup_before = _tree_snapshot(bundle)
    shortcut_before = synthetic.shortcut.read_bytes()
    result = _powershell_file(
        UPDATE_SCRIPT,
        _update_parameters(synthetic, bundle, manifest_hash),
        synthetic.environment,
    )
    assert result.returncode == 0, result.stderr
    assert _tree_snapshot(synthetic.install) == source_before
    assert _tree_snapshot(synthetic.product) == product_before
    assert _tree_snapshot(synthetic.source) == source_before
    assert _tree_snapshot(bundle) == backup_before
    assert synthetic.shortcut.read_bytes() == shortcut_before
    assert not (synthetic.product / "runtime").exists()
    assert not list(synthetic.install.parent.glob("OrchestratoRRR.__*__.*"))


@pytest.mark.parametrize(
    ("case", "error"),
    [
        ("source_hash", "UPDATE_SOURCE_INVALID"),
        ("schema_hash", "UPDATE_SOURCE_INVALID"),
        ("file_count", "UPDATE_SOURCE_INVALID"),
        ("current_hash", "UPDATE_CURRENT_INSTALL_INVALID"),
        ("backup_hash", "UPDATE_BACKUP_INVALID"),
        ("invalid_hash", "UPDATE_ARGUMENT_INVALID"),
        ("invalid_count", "UPDATE_ARGUMENT_INVALID"),
    ],
)
def test_update_rejects_invalid_arguments_and_artifact_contracts(
    synthetic: SyntheticEnvironment, case: str, error: str
) -> None:
    bundle, manifest_hash = _prepare_backup(synthetic)
    overrides: dict[str, object] = {}
    if case == "source_hash":
        overrides["ExpectedSourceExeSha256"] = "A" * 64
    elif case == "schema_hash":
        overrides["ExpectedSourceSchemaSha256"] = "A" * 64
    elif case == "file_count":
        overrides["ExpectedSourceFileCount"] = synthetic.source_file_count + 1
    elif case == "current_hash":
        overrides["ExpectedCurrentExeSha256"] = "A" * 64
    elif case == "backup_hash":
        overrides["ExpectedBackupManifestSha256"] = "A" * 64
    elif case == "invalid_hash":
        overrides["ExpectedSourceExeSha256"] = "not-a-hash"
    else:
        overrides["ExpectedSourceFileCount"] = "true"
    _assert_rejected_without_changes(
        synthetic,
        bundle,
        _update_parameters(synthetic, bundle, manifest_hash, **overrides),
        error,
    )


@pytest.mark.parametrize("expression", ["$true", "@(3,4)"])
def test_update_rejects_boolean_and_array_file_count_through_public_parameter_binding(
    synthetic: SyntheticEnvironment, expression: str
) -> None:
    bundle, manifest_hash = _prepare_backup(synthetic)
    install_before = _tree_snapshot(synthetic.install)
    product_before = _tree_snapshot(synthetic.product)
    source_before = _tree_snapshot(synthetic.source)
    backup_before = _tree_snapshot(bundle)
    result = _public_update_with_file_count_expression(synthetic, bundle, manifest_hash, expression)
    assert result.returncode != 0
    assert "UPDATE_ARGUMENT_INVALID" in result.stderr
    assert _tree_snapshot(synthetic.install) == install_before
    assert _tree_snapshot(synthetic.product) == product_before
    assert _tree_snapshot(synthetic.source) == source_before
    assert _tree_snapshot(bundle) == backup_before


def test_update_rejects_unbound_public_argument_without_changes(synthetic: SyntheticEnvironment) -> None:
    bundle, manifest_hash = _prepare_backup(synthetic)
    parameters = _update_parameters(synthetic, bundle, manifest_hash) + ["-UnexpectedArgument", "value"]
    install_before = _tree_snapshot(synthetic.install)
    product_before = _tree_snapshot(synthetic.product)
    source_before = _tree_snapshot(synthetic.source)
    backup_before = _tree_snapshot(bundle)
    result = _powershell_file(UPDATE_SCRIPT, parameters, synthetic.environment)
    assert result.returncode != 0
    assert _tree_snapshot(synthetic.install) == install_before
    assert _tree_snapshot(synthetic.product) == product_before
    assert _tree_snapshot(synthetic.source) == source_before
    assert _tree_snapshot(bundle) == backup_before


def test_update_rejects_same_executable_hash(synthetic: SyntheticEnvironment) -> None:
    bundle, manifest_hash = _prepare_backup(synthetic)
    (synthetic.source / "OrchestratoRRR.exe").write_bytes((synthetic.install / "OrchestratoRRR.exe").read_bytes())
    _assert_rejected_without_changes(
        synthetic,
        bundle,
        _update_parameters(synthetic, bundle, manifest_hash),
        "UPDATED_CODE_NOT_PACKAGED",
    )


@pytest.mark.parametrize("change", ["backup", "product", "runtime"])
def test_update_rejects_backup_or_product_data_changes(synthetic: SyntheticEnvironment, change: str) -> None:
    bundle, manifest_hash = _prepare_backup(synthetic)
    if change == "backup":
        (bundle / "logs/run.jsonl").write_text("tampered", encoding="utf-8")
        error = "UPDATE_BACKUP_INVALID"
    elif change == "product":
        (synthetic.product / "logs/run.jsonl").write_text("changed", encoding="utf-8")
        error = "PRODUCT_DATA_CHANGED_SINCE_BACKUP"
    else:
        (synthetic.product / "runtime").mkdir()
        error = "PRODUCT_DATA_CHANGED_SINCE_BACKUP"
    _assert_rejected_without_changes(
        synthetic,
        bundle,
        _update_parameters(synthetic, bundle, manifest_hash),
        error,
    )


@pytest.mark.parametrize("kind", ["product", "install", "reparse"])
def test_update_rejects_unsafe_source(synthetic: SyntheticEnvironment, kind: str) -> None:
    bundle, manifest_hash = _prepare_backup(synthetic)
    if kind == "product":
        unsafe = synthetic.product / "source"
        unsafe.mkdir()
        _make_onedir(unsafe, "C")
    elif kind == "install":
        unsafe = synthetic.install / "source"
        unsafe.mkdir()
        _make_onedir(unsafe, "C")
    else:
        unsafe = synthetic.source
        target = synthetic.root / "source-junction-target"
        target.mkdir()
        result = _run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "New-Item -ItemType Junction -Path $env:LINK -Target $env:TARGET | Out-Null",
            ],
            {**synthetic.environment, "LINK": str(unsafe / "linked"), "TARGET": str(target)},
        )
        if result.returncode != 0:
            pytest.skip("junction creation is unavailable")
    parameters = _update_parameters(
        synthetic,
        bundle,
        manifest_hash,
        SourceOnedir=unsafe.resolve(),
        ExpectedSourceExeSha256=_sha256(unsafe / "OrchestratoRRR.exe"),
        ExpectedSourceSchemaSha256=_sha256(unsafe / SCHEMA_RELATIVE),
        ExpectedSourceFileCount=len(_tree_snapshot(unsafe)),
    )
    _assert_rejected_without_changes(synthetic, bundle, parameters, "UPDATE_")


@pytest.mark.parametrize("field", ["target", "arguments", "working"])
def test_update_rejects_changed_shortcut(synthetic: SyntheticEnvironment, field: str) -> None:
    bundle, manifest_hash = _prepare_backup(synthetic)
    env = {**synthetic.environment, "SHORTCUT": str(synthetic.shortcut), "FIELD": field, "ROOT": str(synthetic.root)}
    command = (
        "$s=New-Object -ComObject WScript.Shell;$l=$s.CreateShortcut($env:SHORTCUT);"
        "if($env:FIELD -eq 'target'){$l.TargetPath=Join-Path $env:ROOT 'wrong.exe'};"
        "if($env:FIELD -eq 'arguments'){$l.Arguments='run'};"
        "if($env:FIELD -eq 'working'){$l.WorkingDirectory=$env:ROOT};$l.Save()"
    )
    result = _run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command], env)
    assert result.returncode == 0
    _assert_rejected_without_changes(
        synthetic,
        bundle,
        _update_parameters(synthetic, bundle, manifest_hash),
        "SHORTCUT_STATE_INVALID",
    )


def test_transaction_residue_fails_closed(synthetic: SyntheticEnvironment) -> None:
    bundle, manifest_hash = _prepare_backup(synthetic)
    residue = synthetic.install.parent / ("OrchestratoRRR.__BACKUP__." + "A" * 32)
    residue.mkdir()
    _assert_rejected_without_changes(
        synthetic,
        bundle,
        _update_parameters(synthetic, bundle, manifest_hash),
        "TRANSACTION_RESIDUE_FOUND",
    )


def _run_core_with_hook(
    synthetic: SyntheticEnvironment,
    bundle: Path,
    manifest_hash: str,
    hook: str,
) -> subprocess.CompletedProcess[str]:
    env = synthetic.environment.copy()
    env.update(
        MODULE=str(MODULE),
        SOURCE=str(synthetic.source.resolve()),
        BACKUP=str(bundle.resolve()),
        BACKUP_HASH=manifest_hash,
        CURRENT_HASH=synthetic.current_exe_hash,
        SOURCE_HASH=synthetic.source_exe_hash,
        SCHEMA_HASH=synthetic.source_schema_hash,
        FILE_COUNT=str(synthetic.source_file_count),
        HOOK=hook,
    )
    command = (
        "Import-Module $env:MODULE -Force;$hooks=@{};"
        "if($env:HOOK -eq 'before'){$hooks.AfterBackupRename={throw 'INJECT_BEFORE_ACTIVATION'}};"
        "if($env:HOOK -eq 'after'){$hooks.AfterActivation={throw 'INJECT_AFTER_ACTIVATION'}};"
        "if($env:HOOK -eq 'rollback'){$hooks.AfterActivation={throw 'INJECT_AFTER_ACTIVATION'};"
        "$hooks.BeforeRollbackRestore={throw 'INJECT_ROLLBACK_FAILURE'}};"
        "if($env:HOOK -eq 'source'){$hooks.AfterStaging={param($staging) "
        "[IO.File]::WriteAllText((Join-Path $env:SOURCE 'source-mutated.dat'),'changed')}};"
        "try{& (Get-Module DefaultEntryMaintenance) { "
        "param($source, $backup, $backupHash, $currentHash, $sourceHash, $schemaHash, "
        "$fileCount, $testHooks) "
        "Invoke-OrchestratoRRRInstallUpdateCore -SourceOnedir $source -ProductDataBackup $backup "
        "-ExpectedBackupManifestSha256 $backupHash -ExpectedCurrentExeSha256 $currentHash "
        "-ExpectedSourceExeSha256 $sourceHash -ExpectedSourceSchemaSha256 $schemaHash "
        "-ExpectedSourceFileCount $fileCount -TestHooks $testHooks } "
        "$env:SOURCE $env:BACKUP $env:BACKUP_HASH $env:CURRENT_HASH $env:SOURCE_HASH "
        "$env:SCHEMA_HASH $env:FILE_COUNT $hooks;exit 0}"
        "catch{[Console]::Error.Write($_.Exception.Message);exit 2}"
    )
    return _run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command], env)


@pytest.mark.parametrize("hook", ["before", "after"])
def test_true_backup_rollback_restores_old_install(synthetic: SyntheticEnvironment, hook: str) -> None:
    bundle, manifest_hash = _prepare_backup(synthetic)
    install_before = _tree_snapshot(synthetic.install)
    product_before = _tree_snapshot(synthetic.product)
    result = _run_core_with_hook(synthetic, bundle, manifest_hash, hook)
    assert result.returncode != 0
    assert _tree_snapshot(synthetic.install) == install_before
    assert _tree_snapshot(synthetic.product) == product_before
    assert not list(synthetic.install.parent.glob("OrchestratoRRR.__*__.*"))


def test_source_change_after_staging_is_rejected_before_swap(synthetic: SyntheticEnvironment) -> None:
    bundle, manifest_hash = _prepare_backup(synthetic)
    install_before = _tree_snapshot(synthetic.install)
    product_before = _tree_snapshot(synthetic.product)
    result = _run_core_with_hook(synthetic, bundle, manifest_hash, "source")
    assert result.returncode != 0
    assert "UPDATE_SOURCE_INVALID" in result.stderr
    assert _tree_snapshot(synthetic.install) == install_before
    assert _tree_snapshot(synthetic.product) == product_before
    assert (synthetic.source / "source-mutated.dat").exists()
    (synthetic.source / "source-mutated.dat").unlink()
    assert not list(synthetic.install.parent.glob("OrchestratoRRR.__*__.*"))


def test_rollback_failure_preserves_transaction_evidence(synthetic: SyntheticEnvironment) -> None:
    bundle, manifest_hash = _prepare_backup(synthetic)
    product_before = _tree_snapshot(synthetic.product)
    result = _run_core_with_hook(synthetic, bundle, manifest_hash, "rollback")
    assert result.returncode != 0
    assert "UPDATE_ROLLBACK_FAILED" in result.stderr
    assert _tree_snapshot(synthetic.product) == product_before
    assert list(synthetic.install.parent.glob("OrchestratoRRR.__backup__.*"))
    assert list(synthetic.install.parent.glob("OrchestratoRRR.__failed__.*"))


def test_static_maintenance_safety_contract() -> None:
    backup = BACKUP_SCRIPT.read_text(encoding="utf-8").casefold()
    update = UPDATE_SCRIPT.read_text(encoding="utf-8").casefold()
    module = MODULE.read_text(encoding="utf-8").casefold()
    public = backup + update
    assert "build-package.ps1" not in update
    assert "pyinstaller" not in update
    assert "install-default-entry.ps1" not in update
    assert "& $installed" not in update and "start-process" not in update
    assert "testhooks" not in update
    assert "reconstructed_from_dist" not in module
    assert "copy-item" not in public + module
    assert "robocopy" not in public + module
    assert "remove-item" not in public + module
    assert "get-productdatastate" in module
    assert "assert-productmatchesbackup" in module
    assert "remove-ownedtree" in module
    assert (
        "export-modulemember -function "
        "invoke-orchestratorrrproductdatabackup, invoke-orchestratorrrinstallupdate"
    ) in module
    assert "wildcard" not in module
    for forbidden in (
        "createdirectory($paths.runtime",
        "createdirectory($paths.product",
        "directory]::delete($paths.product",
    ):
        assert forbidden not in module


def test_public_module_exports_do_not_expose_test_hooks() -> None:
    environment = os.environ.copy()
    environment["MODULE"] = str(MODULE)
    command = (
        "Import-Module $env:MODULE -Force;"
        "$update=(Get-Command Invoke-OrchestratoRRRInstallUpdate).Parameters.ContainsKey('TestHooks');"
        "$core=$null -ne (Get-Command Invoke-OrchestratoRRRInstallUpdateCore -ErrorAction SilentlyContinue);"
        "if($update -or $core){exit 1}"
    )
    result = _run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command], environment)
    assert result.returncode == 0, result.stderr


def test_powershell_files_parse_without_execution() -> None:
    environment = os.environ.copy()
    environment["PARSE_PATHS"] = os.pathsep.join(map(str, (BACKUP_SCRIPT, UPDATE_SCRIPT, MODULE)))
    command = (
        "$failed=$false;foreach($path in ($env:PARSE_PATHS -split ';')){"
        "$tokens=$null;$errors=$null;[Management.Automation.Language.Parser]::ParseFile($path,[ref]$tokens,[ref]$errors)|Out-Null;"
        "if($errors.Count -ne 0){$failed=$true}};if($failed){exit 1}"
    )
    result = _run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command], environment)
    assert result.returncode == 0, result.stderr
