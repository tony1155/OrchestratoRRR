"""Synthetic official-format logs; does not load BetterGI or a game."""

import os
import subprocess
import sys
import time
from pathlib import Path

mode, directory, name = sys.argv[1:]
root = Path(directory)
root.mkdir(parents=True, exist_ok=True)
path = root / "better-genshin-impact20260907.log"
pid = os.getpid() + (1 if mode == "other_instance" else 0)
identity = f"Primary:S1:P{pid}:T{int(time.time() * 1000)}"
source = "BetterGenshinImpact.ViewModel.Pages.OneDragonFlowViewModel"


def event(message: str, level: str = "INF") -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(f"[12:00:00.000] [{level}] [{identity}] {source}\n{message}\n\n")


if mode == "early_exit":
    sys.exit(0)
if mode == "child":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    (root / "child.pid").write_text(str(child.pid))
event(f"启用一条龙配置：{'wrong' if mode == 'wrong_config' else name}")
if mode == "failure":
    event("Synthetic task failure", "ERR")
if mode == "caught_failure":
    event("执行配置组任务时失败", "DBG")
if mode == "cancelled":
    event("任务被取消，退出执行")
if mode == "interrupt":
    event("任务中断:需人工处理")
if mode == "overflow":
    with path.open("a", encoding="utf-8") as stream:
        stream.write("x" * (3 * 1024 * 1024))
if mode != "hang":
    event("一条龙和配置组任务结束")
if mode in {"hang", "completed_but_alive"}:
    time.sleep(30)
sys.exit(2 if mode == "nonzero" else 0)
