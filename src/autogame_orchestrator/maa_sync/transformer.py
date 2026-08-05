"""旧 GUI JSON 到 MAA CLI JSON 的纯白名单转换。"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence


class MAATransformError(ValueError):
    """输入不满足已确认的旧转换契约。"""


def _select_current(root: object) -> Mapping[str, object]:
    if not isinstance(root, Mapping):
        raise MAATransformError("顶层必须是对象")
    configurations = root.get("Configurations")
    if not isinstance(configurations, Mapping) or not configurations:
        raise MAATransformError("配置集合为空")
    current = root.get("Current")
    key = current.strip() if isinstance(current, str) else ""
    if key:
        if key not in configurations:
            raise MAATransformError("当前配置不存在")
        selected = configurations[key]
    else:
        selected = next(iter(configurations.values()))
    if not isinstance(selected, Mapping):
        raise MAATransformError("当前配置必须是对象")
    return selected


def _bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().casefold()
    if normalized in {"true", "1"}:
        return True
    if normalized in {"false", "0"}:
        return False
    return default


def _integer(value: object, default: int = 0) -> int:
    if value is None or isinstance(value, bool):
        return default
    try:
        return int(str(value))
    except (TypeError, ValueError) as exc:
        raise MAATransformError("整数值无效") from exc


def _text(value: object) -> str:
    return "" if value is None else str(value)


def _list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in re.split(r"[,;；，\r\n]+", str(value)) if part.strip()]


def _touch_mode(value: object) -> str:
    text = _text(value).strip()
    known = {"minitouch": "MiniTouch", "maatouch": "MaaTouch", "adb": "ADB"}
    return known.get(text.casefold(), text or "MiniTouch")


def _connect_settings(task_config: Mapping[str, object]) -> Mapping[str, object]:
    """取新版布局的 ``Gui.ConnectSettings``；不存在时返回空映射。

    旧版 MAA 将连接配置以扁平 ``Connect.*`` 键存于 settings；新版改存于 tasks 侧
    ``Gui.ConnectSettings``。两种布局均需支持，否则新版会同步出空连接配置并使
    MAA 无法连上模拟器。
    """
    gui = task_config.get("Gui")
    if not isinstance(gui, Mapping):
        return {}
    settings = gui.get("ConnectSettings")
    return settings if isinstance(settings, Mapping) else {}


def _connect_value(
    settings: Mapping[str, object],
    connect: Mapping[str, object],
    legacy_key: str,
    modern_key: str,
) -> object:
    """优先旧版扁平键，缺失时回退到新版 ``ConnectSettings``。

    旧键优先保证已验证的旧布局行为不变；仅当其不存在或为空串时才采新布局值。
    """
    legacy = settings.get(legacy_key)
    if legacy is not None and _text(legacy).strip():
        return legacy
    return connect.get(modern_key)


def _post_actions_close_game(settings: Mapping[str, object], task_config: Mapping[str, object]) -> bool:
    """判定 GUI 是否要求完成后退出明日方舟。

    新版使用 ``Gui.PostActions``（如 ``"ExitArknights"``），旧版使用
    ``MainFunction.ActionAfterCompleted``。两者任一表达退出游戏即视为真，
    对应 maa-cli 侧追加 ``CloseDown`` 任务。
    """
    gui = task_config.get("Gui")
    modern = _text(gui.get("PostActions")) if isinstance(gui, Mapping) else ""
    legacy = _text(settings.get("MainFunction.ActionAfterCompleted"))
    return any("exitarknights" in value.casefold() for value in (modern, legacy))


def _infrast_mode(value: object) -> int:
    text = _text(value).strip().casefold()
    known = {"default": 0, "normal": 0, "rotation": 20000, "custom": 10000, "user_defined": 10000, "userdefined": 10000}
    if text in known:
        return known[text]
    return _integer(text)


def _convert_task(task: object, settings: Mapping[str, object], index: int) -> dict[str, object] | None:
    if not isinstance(task, Mapping):
        raise MAATransformError("任务必须是对象")
    task_type = _text(task.get("TaskType"))
    enabled = _bool(task.get("IsEnable"), True)
    params: dict[str, object]
    if task_type == "StartUp":
        params = {
            "enable": enabled,
            "client_type": _text(settings.get("Start.ClientType")),
            "start_game_enabled": _bool(settings.get("Start.StartGame"), True),
        }
        account = _text(task.get("AccountName")).strip()
        if account:
            params["account_name"] = account
        return {"name": "StartUp", "type": "StartUp", "params": params}
    if task_type == "Recruit":
        confirm = [level for level in (3, 4, 5, 6) if _bool(settings.get(f"Recruit.ChooseLevel{level}"), level >= 4)]
        if _bool(task.get("Level1NotChoose"), True):
            confirm.insert(0, 1)
        select = [level for level in (4, 5, 6) if _bool(settings.get(f"Recruit.ChooseLevel{level}"), level <= 5)]
        params = {
            "enable": enabled,
            "refresh": _bool(task.get("RefreshLevel3"), True),
            "force_refresh": _bool(task.get("ForceRefresh")),
            "select": select,
            "confirm": list(dict.fromkeys(confirm)),
            "times": _integer(task.get("MaxTimes")),
            "set_time": _bool(settings.get("Recruit.AutoSetTime"), True),
            "expedite": _bool(task.get("UseExpedited")),
            "skip_robot": _bool(task.get("Level1NotChoose"), True),
            "extra_tags_mode": _integer(task.get("ExtraTagMode")),
            "first_tags": _list(task.get("Level3PreferTags")),
            "recruitment_time": {
                "3": _integer(task.get("Level3Time")),
                "4": _integer(task.get("Level4Time")),
                "5": _integer(task.get("Level5Time")),
            },
        }
        return {"name": "Recruit", "type": "Recruit", "params": params}
    if task_type == "Infrast":
        rooms = task.get("RoomList", [])
        if not isinstance(rooms, Sequence) or isinstance(rooms, (str, bytes, bytearray)):
            raise MAATransformError("设施列表无效")
        facilities = [
            _text(room.get("Room"))
            for room in rooms
            if isinstance(room, Mapping) and _bool(room.get("IsEnabled"), True) and _text(room.get("Room")).strip()
        ]
        mode = _infrast_mode(task.get("Mode"))
        params = {
            "enable": enabled,
            "mode": mode,
            "facility": facilities,
            "drones": _text(task.get("UsesOfDrones")),
            "continue_training": _bool(task.get("ContinueTraining")),
            "threshold": _integer(task.get("DormThreshold")) / 100.0,
            "dorm_notstationed_enabled": _bool(task.get("DormFilterNotStationed")),
            "dorm_trust_enabled": _bool(task.get("DormTrustEnabled")),
            "replenish": _bool(task.get("OriginiumShardAutoReplenishment")),
            "reception_message_board": _bool(task.get("ReceptionMessageBoard"), True),
            "reception_clue_exchange": _bool(task.get("ReceptionClueExchange"), True),
            "reception_send_clue": _bool(task.get("SendClue"), True),
        }
        if mode == 10000:
            filename = _text(task.get("Filename")).strip()
            if not filename:
                raise MAATransformError("自定义基建计划缺少文件名")
            params["filename"] = filename
            plan = _integer(task.get("PlanSelect"), -1)
            if plan >= 0:
                params["plan_index"] = plan
        return {"name": "Infrast", "type": "Infrast", "params": params}
    if task_type == "Mall":
        params = {
            "enable": enabled,
            "credit_fight": _bool(task.get("CreditFight")),
            "formation_index": _integer(task.get("CreditFightFormation")),
            "visit_friends": _bool(task.get("VisitFriends"), True),
            "shopping": _bool(task.get("Shopping"), True),
            "buy_first": _list(task.get("FirstList")),
            "blacklist": _list(task.get("BlackList")),
            "force_shopping_if_credit_full": _bool(task.get("ShoppingIgnoreBlackListWhenFull")),
            "only_buy_discount": _bool(task.get("OnlyBuyDiscount")),
            "reserve_max_credit": _bool(task.get("ReserveMaxCredit")),
        }
        return {"name": "Mall", "type": "Mall", "params": params}
    if task_type == "Fight":
        stages = _list(task.get("StagePlan"))
        if not stages:
            raise MAATransformError(f"战斗任务 {index} 缺少关卡")
        stage = stages[0]
        params = {
            "enable": enabled,
            "stage": stage,
            "medicine": _integer(task.get("MedicineCount")) if _bool(task.get("UseMedicine")) else 0,
            "expiring_medicine": 1000 if _bool(task.get("UseExpiringMedicine")) else 0,
            "stone": _integer(task.get("StoneCount")) if _bool(task.get("UseStone")) else 0,
            "series": _integer(task.get("Series")),
            "DrGrandet": _bool(task.get("IsDrGrandet")),
            "client_type": _text(settings.get("Start.ClientType")),
        }
        if _bool(task.get("EnableTimesLimit")):
            params["times"] = _integer(task.get("TimesLimit"))
        drop_id = _text(task.get("DropId")).strip()
        drop_count = _integer(task.get("DropCount"))
        if _bool(task.get("EnableTargetDrop")) and drop_id and drop_count > 0:
            params["drops"] = {drop_id: drop_count}
        return {"name": f"Fight-{stage.replace('/', '-')}", "type": "Fight", "params": params}
    if task_type == "Award":
        params = {
            "enable": enabled,
            "award": _bool(task.get("Award"), True),
            "mail": _bool(task.get("Mail"), True),
            "recruit": _bool(task.get("FreeGacha")),
            "orundum": _bool(task.get("Orundum")),
            "mining": _bool(task.get("Mining")),
            "specialaccess": _bool(task.get("SpecialAccess")),
        }
        return {"name": "Award", "type": "Award", "params": params}
    if enabled:
        raise MAATransformError("启用的任务类型不受支持")
    return None


def transform_gui_configuration(gui_settings: object, gui_tasks: object) -> tuple[dict[str, object], dict[str, object]]:
    """纯转换两个 GUI 根对象，且不修改输入。"""
    settings = _select_current(gui_settings)
    task_config = _select_current(gui_tasks)
    connect = _connect_settings(task_config)
    profile: dict[str, object] = {
        "connection": {
            "type": "ADB",
            "adb_path": _text(_connect_value(settings, connect, "Connect.AdbPath", "AdbPath")),
            "address": _text(_connect_value(settings, connect, "Connect.Address", "Address")),
            "config": _text(_connect_value(settings, connect, "Connect.ConnectConfig", "Config")),
        },
        "instance_options": {
            "touch_mode": _touch_mode(_connect_value(settings, connect, "Connect.TouchMode", "TouchMode")),
            "deployment_with_pause": False,
            "adb_lite_enabled": _bool(_connect_value(settings, connect, "Connect.AdbLiteEnabled", "EnableAdbLite")),
            "kill_adb_on_exit": _bool(_connect_value(settings, connect, "Connect.KillAdbOnExit", "KillAdbOnExit")),
        },
    }
    queue = task_config.get("TaskQueue")
    if not isinstance(queue, Sequence) or isinstance(queue, (str, bytes, bytearray)) or not queue:
        raise MAATransformError("任务集合为空")
    converted = [_convert_task(task, settings, index) for index, task in enumerate(queue)]
    tasks = [task for task in converted if task is not None]
    if not tasks:
        raise MAATransformError("任务转换结果为空")
    if _post_actions_close_game(settings, task_config):
        # GUI 要求完成后退出明日方舟；maa-cli 侧以显式 CloseDown 任务表达。
        # 不追加则同步后游戏会持续驻留于模拟器中。
        tasks.append({"name": "CloseDown", "type": "CloseDown", "params": {"enable": True, "client_type": "Official"}})
    return profile, {"tasks": tasks}
