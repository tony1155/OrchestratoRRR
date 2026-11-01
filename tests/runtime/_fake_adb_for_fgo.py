import sys
import time
from pathlib import Path

argv = sys.argv[1:]
stop = argv.index("--record")
record = argv[stop + 1]
mode = argv[argv.index("--mode") + 1]
# 只记录模拟的 adb 参数（--record 之前的部分）。
with Path(record).open("a", encoding="utf-8") as stream:
    stream.write(repr(argv[:stop]) + chr(10))
if mode == "stop-ok":
    sys.exit(0)
if mode == "stop-fail":
    sys.exit(1)
if mode == "pidof-empty":
    sys.exit(1)
if mode == "pidof-empty-zero":
    sys.exit(0)
if mode == "pidof-alive":
    print("12345")
    sys.exit(0)
if mode == "hang":
    time.sleep(30)
sys.exit(0)
