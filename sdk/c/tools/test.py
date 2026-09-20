from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys


SDK = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-dir", type=Path, required=True)
    args = parser.parse_args()
    build = args.build_dir.resolve()
    environment = dict(os.environ, PYTHONPATH=os.pathsep.join([str(build / "python"), str(build / "generated")]),
                       ASAN_OPTIONS="detect_leaks=1:halt_on_error=1", UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
    for program in ("semantic-tests", "wire-tests", "owner-bounds", "private-config-tests"):
        subprocess.run([str(build / program)], check=True, timeout=20, env=environment)
    peer = subprocess.Popen([sys.executable, str(SDK / "tests/peer.py")], env=environment,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(peer.stdout, selectors.EVENT_READ)
            if not selector.select(10):
                raise RuntimeError("controlled peer startup deadline")
        ready = json.loads(peer.stdout.readline(1024))
        endpoint = f"http://127.0.0.1:{ready['port']}"
        subprocess.run([str(build / "transport-tests"), endpoint], env=environment, check=True, timeout=90)
        output, errors = peer.communicate(b"stop\n", timeout=10)
        if peer.returncode or errors or len(output) > 4096:
            raise RuntimeError(f"controlled peer failure: {errors[:2048]!r}")
        summary = json.loads(output)
        if summary["defaultCapabilityPages"] < 2:
            raise RuntimeError("capability default page contract not exercised")
        print("C controlled TCP peer: " + json.dumps(summary, sort_keys=True))
    finally:
        if peer.poll() is None:
            peer.kill()
            peer.communicate(timeout=5)


if __name__ == "__main__":
    main()
