"""复用既有原子 writer 的生产 RunReport sink。"""

from pathlib import Path

from autogame_orchestrator.models import RunReport
from autogame_orchestrator.reporter import write_report_atomic


class ProductionReportSink:
    """写入配置的报告目录，不在异常中暴露路径。"""

    def __init__(self, report_dir: str) -> None:
        self._report_dir = Path(report_dir)

    def write(self, report: RunReport) -> None:
        _path, errors = write_report_atomic(report, self._report_dir)
        if errors:
            raise OSError("运行报告写入失败")
