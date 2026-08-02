# Phase 7D2 rebuild and packaged non-business entry tests

Baseline commit: 4dcb3b89a76fce90e58e0b3152d1e59822c5da79.

Phase 7D1 was committed before this acceptance round. The formal
scripts/build-package.ps1 entry was run exactly once, producing a new
PyInstaller onedir without changes to the spec or build script. Static
inspection confirmed that the Analysis includes the default_entry module and
all required production dependencies. The bundled RunReport schema matches
the canonical schema, no required module is missing, and the dist privacy and
project-resource boundaries pass.

The packaged executable was started exactly four times, in this order:

1. version
2. root --help
3. start --help
4. non-interactive start

Version passed. Root help exposed exactly version, validate, plan, run, and
start as public commands; the hidden isolated command and elevation marker
were absent. Start help exposed the bounded deadline option and did not expose
config, real-confirmation, workspace, executable, ADB, mode, working-directory,
or elevation-child options.

The final start invocation used DEVNULL stdin from an empty system-temporary
runner with synthetic LOCALAPPDATA and APPDATA paths that did not exist. It
failed closed with exit code 2 and START_INTERACTIVE_CONSOLE_REQUIRED before
canonical path resolution, directory creation, config loading, preview,
confirmation, or workflow execution. The runner stayed empty and neither
synthetic application-data path was created.

No correct confirmation was supplied. Public run, validate, plan, and the
hidden isolated workflow were not executed. The installer was not run, no
shortcut was created, no real configuration was read, and no UAC, ADB, TCP
probe, or business program was invoked. EXE hash, bundled-schema hash, and
dist file count were unchanged by the packaged tests. Temporary directories
and the ignored harness were removed.

Phase 7D2 is complete. Phase 7D3 owns a separately authorized packaged
default-entry synthetic preflight and confirmation-cancel check. Phase 7C
still requires separate real-execution authorization, and Phase 7E owns any
legacy PowerShell replacement decision. The legacy entry remains retained,
Phase 7D is not complete, and Phase 7 is not complete.
