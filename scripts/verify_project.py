#!/usr/bin/env python3
"""Run the repository regression, frontend syntax, protocol sync and WS smokes.

Use the project's virtual environment interpreter. --skip-ws omits only the
network smokes when ports 8888/8889 are unavailable.
"""

import argparse
import socket
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    command = [sys.executable, *args]
    print(f"$ {' '.join(command)}", flush=True)
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode:
        raise SystemExit(result.returncode)


def port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return True
    except OSError:
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-ws", action="store_true")
    args = parser.parse_args()
    run("-m", "pytest", "-q", "--tb=short", "-p", "no:cacheprovider")
    run("scripts/check_frontend_js.py")
    run("-c", "from scripts.gen_protocol_js import generate_js, OUTPUT_PATH; "
        "import sys; ok = OUTPUT_PATH.read_text(encoding='utf-8') == generate_js(); "
        "print('protocol sync:', 'OK' if ok else 'MISMATCH'); sys.exit(0 if ok else 1)")
    if args.skip_ws:
        return
    if port_open(8888) or port_open(8889):
        raise SystemExit("WS 冒烟需要空闲的 8888/8889 端口")
    with (ROOT / "logs" / "runtime" / "verify_server.log").open("w", encoding="utf-8") as log:
        server = subprocess.Popen([sys.executable, "-u", "game_server.py"], cwd=ROOT,
                                  stdout=log, stderr=subprocess.STDOUT)
        try:
            for _ in range(100):
                if server.poll() is not None:
                    raise SystemExit(f"服务器提前退出: {server.returncode}")
                if port_open(8889):
                    break
                time.sleep(0.1)
            else:
                raise SystemExit("服务器 10 秒内未启动 WebSocket")
            run("scripts/manual/ws_diag_smoke.py")
            run("scripts/manual/ws_engine_smoke.py")
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
    print("VERIFY_OK", flush=True)


if __name__ == "__main__":
    main()
