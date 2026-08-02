# Phase 7D4C manual shortcut preflight cancellation

Baseline commit: `3674ff0c7d5f1e34113649bf18b54a2381413a84`.

The evidence for this acceptance round is user direct observation. No
automated transcript or computer capture is available, and Codex did not
repeat the launch. The user opened the installed Start Menu shortcut exactly
once, which launched the installed packaged `start` entry.

The interactive entry displayed the exact external 11-stage preview in the
expected order, the real-program warning, and the confirmation prompt. The
user entered the fixed incorrect value `PHASE_7D4C_CANCEL`. The entry rejected
that value, displayed its close pause, and the window closed normally after
the user pressed Enter. The user observed no UAC prompt, business-program
launch, or unexpected output.

The committed control flow places preview and warning before confirmation and
places `execute_run_request()` only after an exact successful confirmation.
Therefore the observed rejection did not reach the run executor. The
post-observation static audit found no entries in the canonical runtime, log,
or report directories and found no formal log, RunReport, workflow state, or
business output. Installed EXE and schema hashes, the 106-file installation,
the canonical config hash, and all shortcut properties remained intact.

Phase 7D3 retains its original composed-evidence basis. This later direct
observation strengthens the packaged interactive confirmation-cancel boundary
without claiming a correctly confirmed workflow. Phase 7D4C, Phase 7D4, and
Phase 7D are complete. Phase 7C still owns the separately authorized real
packaged external workflow after correct confirmation. Phase 7E still owns the
legacy PowerShell replacement decision; that entry remains available in
parallel. Phase 7 is not complete.
