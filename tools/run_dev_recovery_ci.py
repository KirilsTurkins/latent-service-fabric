#!/usr/bin/env python3
"""Give installed-helper probes a fresh private account on ephemeral CI."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import pwd
import secrets
import shutil
import subprocess
import sys
import tempfile

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.dev_workflow import process
from tools.dev_workflow.common import decode, encode, require
from tools.native_runtime import files


PROBES = {"recovery": "dev_recovery_fixture_probe.py",
          "isolation": "dev_workspace_isolation_probe.py", "watch": "dev_watch_fixture_probe.py"}


def run(payload: Path, supplied: Path, output: Path, probe: str = "recovery"):
    require(probe in PROBES, "unknown-installed-helper-ci-probe")
    require(sys.platform == "linux" and os.geteuid() == 0
            and os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("RUNNER_OS") == "Linux",
            "fresh-recovery-account-only-on-ephemeral-linux-ci")
    require(not output.exists(), "new-recovery-ci-output-required")
    # The helper deliberately selects the passwd home, never an environment
    # override. Do not alter the runner's home, account or inherited ACLs.
    home = Path(tempfile.mkdtemp(prefix="lsf-" + probe + "-ci-", dir="/tmp"))
    with files.directory(home, {0}):
        pass
    name = "lsf-" + probe + "-" + secrets.token_hex(4)
    subprocess.run(["/usr/sbin/useradd", "--system", "--user-group", "--no-create-home",
                    "--home-dir", str(home), "--shell", "/usr/sbin/nologin", name], check=True, timeout=30)
    account = pwd.getpwnam(name)
    require(account.pw_uid != 0 and account.pw_dir == str(home), "fresh-recovery-account-identity")
    staged = home / "source"
    staged.mkdir(mode=0o700)
    root = Path(__file__).resolve().parents[1]
    # Copies stay entirely inside the new home. Symlinks are copied as links,
    # and are subsequently subject to the usual owned-input validation.
    for source, destination in ((root / "tools", staged / "tools"), (payload, home / "payload"),
                                (supplied, home / "source-node")):
        shutil.copytree(source, destination, symlinks=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for parent, directories, names in os.walk(home, followlinks=False):
        for path in (Path(parent), *(Path(parent) / name for name in (*directories, *names))):
            os.chown(path, account.pw_uid, account.pw_gid, follow_symlinks=False)
    public = home / "public"
    result = None
    try:
        result = process.run(["/usr/sbin/runuser", "-u", name, "--", str(Path(sys.executable).resolve()),
            "-B", str(staged / "tools" / PROBES[probe]), "--payload", str(home / "payload"),
            "--source-node", str(home / "source-node"), "--output", str(public)],
            home, timeout=1000, graceful=15, maximum=262144)
    finally:
        # Export only the probe's bounded public receipts. Its private pending
        # intent and account remain until the ephemeral runner is discarded.
        output.mkdir(mode=0o755)
        if public.is_dir() and not public.is_symlink():
            for path in public.glob("*.json"):
                raw = files.read(path, 4 * 1024 * 1024, owners={0, account.pw_uid})
                (output / path.name).write_bytes(raw)
        (output / "ci-account.json").write_bytes(encode({"purpose": "ephemeral-source-" + probe + "-probe",
            "privatePasswdHome": True, "dedicatedUnprivilegedAccount": True,
            "runnerAclChanged": False, "cleanup": "private-intent-retained-until-runner-teardown"}))
    if result.returncode:
        print(result.stderr.decode("utf-8", errors="replace"), file=sys.stderr)
        raise SystemExit(result.returncode)
    report = decode((output / "observation.json").read_bytes(), 4 * 1024 * 1024)
    require(report["passed"] is True, "recovery-ci-probe-failed")
    print("Installed-helper " + probe + " passed under a fresh unprivileged CI account")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("payload", "source-node", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--probe", choices=sorted(PROBES), default="recovery")
    args = parser.parse_args()
    run(args.payload.resolve(strict=True), args.source_node.resolve(strict=True), args.output.absolute(), args.probe)
