# Phase 7D3 composed-evidence closure

Baseline commit: `f125874b9be513f5388a3e9d654575d1008deaf5`.

Phase 7D3 originally planned to execute the packaged `start` command in a
real interactive TTY, reach its confirmation prompt with a fully synthetic
configuration, and cancel before the formal run boundary. The computer-use
backend was unavailable, and the PowerShell transcript probe did not produce
usable evidence. The original fail-closed gate therefore stopped before the
packaged executable was started. Packaged execution count was zero; neither a
correct nor an incorrect confirmation was entered, and no workflow ran.

Before that stop, the synthetic configuration passed five source-only gates:
configuration parsing, the default-entry absolute-path policy, the run-v1
gate, path existence checks, and the exact external execution-plan gate. The
plan contained the expected 11 stages in the expected order. Artifact hashes
and the dist file count remained unchanged, and all temporary evidence was
removed.

Phase 7D3 is closed using three consistent evidence sets:

1. Source control-flow and automatic-test evidence covers the complete
   synthetic preflight, exact 11-stage preview, interactive confirmation,
   incorrect-confirmation cancellation, zero run-executor calls, pause
   behavior, runtime/log/report preparation, and write-probe cleanup.
2. Phase 7D2 packaged-inclusion evidence proves that the same committed
   `start` and `default_entry` implementation is included in the formal
   onedir. It also verifies the packaged command and option contracts,
   packaged imports, non-interactive fail-closed behavior, and artifact
   integrity.
3. The failed Phase 7D3 attempt's source-only synthetic evidence proves that
   the proposed fixture satisfies every pre-confirmation configuration and
   plan gate without real side effects.

The missing interactive transcript is an acceptance-environment limitation,
not an observed product defect. Repeating fragile TTY automation would add
more environmental risk than product evidence because the target control flow
already has source-level automatic coverage and packaged-inclusion evidence.
Accordingly, direct packaged interactive execution is waived for Phase 7D3.

This closure does not claim that packaged interactive `start` ran or that a
packaged confirmation cancellation was directly observed. It does not verify
packaged UAC, a real workflow, or any real business program. Correctly
confirmed packaged external execution remains exclusively in Phase 7C.

Phase 7D3 is complete on this composed-evidence basis. Phase 7D4 next owns
parallel canonical deployment, shortcut creation, and authorized manual
operation. Phase 7E alone may decide whether the legacy PowerShell entry can
be replaced or removed. The legacy entry remains retained,
`legacy_powershell_replacement_ready=false`, and neither Phase 7D nor Phase 7
is complete.
