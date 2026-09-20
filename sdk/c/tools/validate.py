from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys


SDK = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-dir", type=Path, default=SDK.parents[1] / "target/c-sdk")
    parser.add_argument("--sanitize", action="store_true")
    args = parser.parse_args()
    build = args.build_dir.resolve()
    subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(SDK / "tests"),
                    "-p", "test_*.py"], check=True, timeout=30)
    command = [sys.executable, str(SDK / "tools/build.py"), "--build-dir", str(build)]
    if args.sanitize:
        command.append("--sanitize")
    subprocess.run(command, check=True, timeout=900)
    environment = dict(os.environ, PYTHONPATH=str(build / "python"),
                       PATH=str(build / "deps/protoc/bin") + os.pathsep + os.environ["PATH"])
    subprocess.run([sys.executable, str(SDK / "tools/generate.py"), "--build-dir", str(build), "--check"],
                   check=True, env=environment, timeout=120)
    subprocess.run([sys.executable, str(SDK / "tools/test.py"), "--build-dir", str(build)], check=True, timeout=120)


if __name__ == "__main__":
    main()
