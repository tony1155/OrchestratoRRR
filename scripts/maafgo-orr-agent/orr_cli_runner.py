"""Run MaaPiCli unattended with bounded local logs and exact device verification."""
import json
import logging
import logging.handlers
import os
import subprocess
import sys
import threading
import time
from pathlib import Path


def run():
    root = Path.cwd()
    directory = Path(os.environ["ORR_MAAFGO_RESULT_PATH"]).parent
    logger = logging.getLogger("orr-cli")
    logger.setLevel(logging.INFO)
    handler = logging.handlers.RotatingFileHandler(
        directory / "maafgo-cli.log", maxBytes=1024 * 1024, backupCount=2, encoding="utf-8"
    )
    logger.addHandler(handler)
    profile = json.loads((root / "config/maa_pi_config.json").read_text("utf-8-sig"))
    from maa.toolkit import Toolkit
    saved = profile["adb"]
    devices = Toolkit.find_adb_devices()
    matches = [device for device in devices if device.name == saved["name"]
        and os.path.normcase(str(device.adb_path)) == os.path.normcase(saved["adb_path"])]
    if len(matches) != 1 or matches[0].address != saved["address"]:
        logger.error("ADB identity mismatch; CLI was not started")
        return 2
    logger.info("ADB identity verified; launching CLI with stdin closed")
    child = subprocess.Popen([str(root / "MaaPiCli.exe"), "-d"], cwd=root,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW)

    def drain(stream, label):
        while chunk := stream.read1(4096):
            logger.info("%s %s", label, chunk.decode("utf-8", errors="replace"))
        stream.close()

    threads = [threading.Thread(target=drain, args=(stream, label), daemon=True)
        for stream, label in ((child.stdout, "stdout"), (child.stderr, "stderr"))]
    for thread in threads:
        thread.start()
    started = time.monotonic()
    while child.poll() is None:
        if time.monotonic() - started > 120 and not Path(os.environ["ORR_MAAFGO_RESULT_PATH"]).exists():
            logger.error("Startup timeout: Agent did not report a task within 120 seconds")
            child.kill()
            child.wait()
            return 124
        time.sleep(0.2)
    for thread in threads:
        thread.join(timeout=2)
    logger.info("CLI exited with code %s", child.returncode)
    return child.returncode


if __name__ == "__main__":
    raise SystemExit(run())
