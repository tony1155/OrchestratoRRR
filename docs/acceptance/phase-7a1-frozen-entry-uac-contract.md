# Phase 7A1 - Frozen Entry and UAC Re-entry Contract

## Baseline and scope

This acceptance record is based on commit
6a7b4f3990cf68ff2813767858d15cc09692d4cb. It closes the source-versus-frozen
entry and UAC re-entry contract only. It does not implement packaging.

The Phase 7A0 audit found that the source relaunch shape always used
python.exe -m autogame_orchestrator, while a frozen executable must be
relaunched as OrchestratoRRR.exe run ....

## Explicit runtime model

EntryRuntimeKind has two stable values: SOURCE and FROZEN.
EntryRuntime is an immutable model containing:

- the detected kind;
- the current entry executable;
- the working directory captured during entry planning.

detect_entry_runtime() is the single detection boundary. It reads
getattr(sys, "frozen", False) when called, and captures sys.executable and
the current working directory without caching them. It does not use a
packager-private extraction attribute, import a packager, read configuration,
create logs, or start a process.

## Explicit elevation launch specification

ElevationLaunchSpec is an immutable, shell-free model containing
executable, arguments, and working_directory. Arguments never contain the
executable and are passed to the Windows platform layer for
subprocess.list2cmdline quoting.

The public run application builds these shapes:

| runtime | executable | argument prefix |
|---|---|---|
| source | current Python executable | -m autogame_orchestrator run |
| frozen | current frozen executable | run |

Both shapes include an absolute configuration path, finite deadline,
the exact real-execution confirmation, and one --_elevation-child marker.
An elevation child does not append the marker again.

The captured working directory is passed unchanged through
WorkflowCoordinator, WindowsElevationGateway, and the Windows platform
API. The platform layer does not reread os.getcwd() or sys.executable.

## Safety and compatibility

The marker recursion guard, UAC cancellation mapping, launch-failure mapping,
handle cleanup, and child exit-code forwarding remain unchanged. Runner,
executor-factory, and Adapter construction still happen only after the
permission decision.

The Phase 6 external-only gates remain unchanged: managed MuMu is blocked,
MAA Sync and Update remain disabled in run v1, AALC attempts remain one, the
exact confirmation remains required, the deadline remains finite, and the
external plan remains exactly eleven stages.

## Validation boundary

This phase is validated with Fake gateways, monkeypatches, Fake Windows API
objects, and automatic tests only. PyInstaller has not been installed, no
specification or EXE has been generated, and real UAC, ADB, MuMu, StarRail,
MAA, AALC, and production workflow execution have not been performed.

RunReport schema resource collection remains Phase 7A2 work. The installed
default entry, shortcut Start in policy, and final relative log/report
directory policy remain Phase 7D work. The legacy PowerShell entry must not be
removed.
