"""Sync the FGO GUI profile and optionally enable it in the existing workflow."""

from __future__ import annotations

import argparse
import re
import shutil
from datetime import datetime
from pathlib import Path

from autogame_orchestrator.config_loader import load_config
from autogame_orchestrator.maafgo_config import MaaFgoConfigurationError
from autogame_orchestrator.maafgo_gui import sync_mxu_profile


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "enable", "disable"))
    parser.add_argument(
        "--config", type=Path, default=Path(__file__).resolve().parents[1] / "config/orchestrator.local.toml"
    )
    args = parser.parse_args()
    config, errors = load_config(args.config)
    if config is None or errors:
        print("无法加载运行配置：", [e.value for e in errors])
        return 1
    if args.action != "disable":
        try:
            config.maafgo.check_distribution()
            sync_mxu_profile(config.maafgo, adb_path=config.mumu.adb_executable, serial=config.mumu.adb_serial)
            config.maafgo.check_profile(config.mumu.adb_serial)
            config.maafgo.check_profile_policy()
        except MaaFgoConfigurationError as exc:
            print("FGO 任务配置尚未完成：", exc.code.value)
            print("请打开 Configure-FGO.cmd，保持登录为第一项，选择并勾选需要的业务任务。")
            print("战斗方式选原生自动战斗，确认关卡、队伍和次数，关闭 GUI 保存后重新检查。")
            return 1
    if args.action in {"enable", "disable"}:
        original = args.config.read_text(encoding="utf-8-sig")
        pattern = r"(?ms)(^\[fgo\]\s*\n)(.*?)(?=^\[|\Z)"
        value = "true" if args.action == "enable" else "false"

        def replace_section(match: re.Match[str]) -> str:
            body = match.group(2)
            if re.search(r"(?m)^append_to_workflow\s*=", body):
                body = re.sub(r"(?m)^append_to_workflow\s*=.*$", f"append_to_workflow = {value}", body)
            else:
                body = f"append_to_workflow = {value}\n" + body
            return match.group(1) + body

        updated, count = re.subn(pattern, replace_section, original)
        if count != 1:
            print("配置中需要且只能有一个 [fgo] 段。")
            return 1
        if updated != original:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            shutil.copy2(args.config, args.config.with_name(args.config.name + f".before-fgo-{stamp}.bak"))
            temporary = args.config.with_name(args.config.name + ".fgo.tmp")
            temporary.write_text(updated, encoding="utf-8")
            temporary.replace(args.config)
    messages = {
        "check": "FGO 配置检查通过。",
        "enable": "已把 FGO 接入日常流程，排在 MAA 之后。",
        "disable": "已从日常流程中停用 FGO，任务配置保留。",
    }
    print(messages[args.action])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
