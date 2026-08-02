# Phase 7D4B authorized canonical installation

Baseline commit: `71dd5456525a111071560788f4b5a76e8a15e60a`.

The Git-ignored, machine-local configuration candidate was revalidated and
copied byte-for-byte to the canonical configuration location using a temporary
file and atomic rename. Its contents, local absolute paths, and business
arguments are intentionally not recorded here. Both the candidate and the
canonical copy passed config parsing, the default-entry absolute-path policy,
the run-v1 gate, path checks, and the exact external 11-stage plan gate.

The committed installer was invoked exactly once with the retained Phase 7D2
onedir as `SourceOnedir`. It completed successfully without running the
product or requesting elevation. The installed EXE and bundled schema hashes
match the source artifact, and the installed tree contains the same 106 files.
The canonical runtime, log, and report directories were created and remained
empty; no formal log or RunReport was generated.

The Start Menu shortcut was created and inspected statically. Its target is
the canonical installed EXE, its arguments are exactly `start`, its working
directory is the canonical runtime directory, and its description is
`OrchestratoRRR`. The shortcut was not opened. Neither the installed nor dist
EXE was executed, and no UAC, ADB, TCP probe, or business program was invoked.

The legacy PowerShell entry remains present for parallel operation and was not
modified or executed. Phase 7D4B is complete. Phase 7D4C owns the separately
authorized manual shortcut preflight and incorrect-confirmation cancellation.
Correctly confirmed real packaged workflow execution remains in Phase 7C;
Phase 7E owns any legacy-entry replacement decision. Phase 7D and Phase 7 are
not complete.
