# MaaFgo Agent import safety — Phase 2A.1

Source: MaaFgo `d7f3a474f50b9a0631ee9acd6df67998c1933f2b`;
binding/native: MaaFramework v5.13.0. This is an import audit, not permission to
execute action methods. No upstream module was patched or monkeypatched.

An AST inventory covered all 61 Agent Python sources. Module bodies, class
decorators and class-level expressions were examined; `if __name__ == '__main__'`
bodies were distinguished manually from import-time code. Function bodies are
not presumed safe just because they do not run on import. Dynamic imports and
native registration remain a boundary to the partial result.

| Modules / group | Import classification | Evidence / execution boundary |
| --- | --- | --- |
| `custom/bbc_process_utils.py` | SAFE_IMPORT | Only `os`, constants and function definitions; imported in smoke, predicate not invoked |
| `custom/bond_matcher.py` | SAFE_IMPORT | Standard-library math/types/dataclass and pure definitions; imported |
| `battle/core/enums.py`, `models.py`, `policy.py`, `validator.py` and their package initializers | SAFE_IMPORT | Standard-library enums/dataclasses/types; imported |
| `custom/mfaalog.py` | WRITES_LOCAL_STATE | Reconfigures stdout/stderr on import; no file write or external connection; not imported by the smoke |
| `custom/bbc_connection_manager.py` | UNKNOWN transitively; no eager manager creation found | Module defines paths, logger, lock and `_manager_instance=None`; `get_manager()` lazily constructs manager; no import smoke |
| `custom/bbc_action.py`, `bbc_start.py`, `bbc_stop.py` | LOADS_NATIVE_ONLY at registration, transitive audit not certified | `AgentServer.custom_action` instantiates/registers classes; action methods can launch/connect/kill BBC; not imported |
| `custom/bbc_stop_listener.py` | LOADS_NATIVE_ONLY at registration, dangerous registered callback | `AgentServer.tasker_sink()` installs a callback that globally kills matching BBC on `MaaTaskerPostStop`; not imported |
| `custom/ocr_logger.py` | LOADS_NATIVE_ONLY at registration | Context sink registration; not imported |
| `custom/box_action.py`, `servant_up_action.py`, `formation_action.py`, `bond_completion_action.py`, `current_bond_completion_action.py`, `inventory_scan_action.py`, `support_action.py` | UNKNOWN transitively / LOADS_NATIVE_ONLY direct | NumPy/OpenCV, Maa registration, local helper imports; actions perform device work and some persist data; not imported |
| `custom/general_navigation_action.py` | UNKNOWN transitively / LOADS_NATIVE_ONLY direct | Module NumPy arrays and action registration; model construction occurs in methods; not imported |
| `custom/chaldea_import_action.py`, `auto_battle_action.py`, `auto_battle_repeat_action.py` | UNKNOWN transitively / LOADS_NATIVE_ONLY direct | Registration and helper imports; native combat may fetch a Chaldea share at action execution; not imported |
| Other `battle/core`, `battle/data`, `battle/execution`, `battle/perception`, `battle/runtime` | SAFE_IMPORT candidates, not experimentally certified | Pure definitions/dataclasses/coordinate computations plus transitive `mfaalog`; runtime actions use the controller only when called |
| `battle/vision/*` | UNKNOWN transitively | Provider defines HTTP transport, but requests occur in methods; not on the observed main import route; not imported |
| `chaldea/*` | UNKNOWN transitively | Logger/constants at top level; network, cache/config writes occur in functions; no network call found in module body; not imported |
| `chaldea_converter.py` | UNKNOWN, script entry excluded | CLI work under main guard includes fetch/config I/O; not imported or run |
| `mission_solver/*` | UNKNOWN transitively | Solver/data loaders and optional native dependencies not needed for chosen subset; CLI main excluded |
| `utils/yolo_onnx.py` | LOADS_NATIVE_ONLY candidate | NumPy import; model use remains untested |
| `agent/main.py` | UNKNOWN aggregate — not imported | Adjusts `sys.path`, prints paths and unconditionally imports all registered action/sink modules, including BBC modules |

The official `maa/__init__.py` and `maa/agent/__init__.py` choose native paths
through `MAAFW_BINARY_PATH` or package-local `bin`. `Library.open` selects mode
and paths; API property initialization/registration subsequently loads native
libraries. Merely importing a decorated action is not just parsing Python.
The complete native callback registration graph was not exercised, so the
aggregate entry is not declared SAFE_IMPORT.

## Specific hazards that must not be called during import smoke

`bbc_connection_manager.BbcConnectionManager.__init__` calls `_cleanup_port`
and starts the callback listener. `_cleanup_port` runs `netstat -ano`, matches
port 25002 and invokes `taskkill /F /PID` without a BBC executable/ownership
check. It can therefore threaten an unrelated process occupying that port.
This is broader than the earlier basename-only ownership finding.
`get_manager()` calls were found in action methods, not at module scope.
No manager was instantiated or imported during the actual smoke.

`bbc_stop_listener` registers regardless of selected tasks. Its callback checks
only the stop entry, not whether this run started BBC. It has no owned-process
tracking. The direct `stop_bbc` action likewise enumerates and kills external
matching basenames. These are runtime hazards even if import itself succeeds.

## Actual Gate B experiment

Only embedded Python was started, from the private distribution cwd, using
`-I -B -S`, disabled site processing and a restricted child environment.
`MAAFW_BINARY_PATH` explicitly named the verified private binding native folder.
The harness did not change any upstream file or replace functions.

- Interpreter: **3.12.10**.
- `Library.version()`: **v5.13.0**.
- Explicit native loads succeeded: `MaaFramework.dll`, `MaaAgentClient.dll`,
  `MaaAgentServer.dll`, `MaaToolkit.dll`, `MaaAdbControlUnit.dll`.
- Equivalent dependency check: `importlib.metadata` plus locked `packaging`
  requirement/marker/specifier evaluation; **zero missing/incompatible dependencies**.
  This checks metadata, not imports of all native Python extensions.
- In-memory `compile()` of **61** Agent sources succeeded; no bytecode writes.
- Imported **six** modules: `bbc_process_utils`, `bond_matcher`,
  `battle.core.enums`, `battle.core.models`, `battle.core.policy`,
  `battle.core.validator`. These instantiate no BBC manager or Maa server.
- No Agent aggregate import, Toolkit initialization/discovery, AgentServer
  startup, sockets, ADB, MuMu detection, process enumeration or game action.

Result: **PARTIAL_PASS**. Full native dependency portability and the entire
Agent dependency graph remain unverified. An import-only pass would not remove
the global cleanup hazard or validate business success.
