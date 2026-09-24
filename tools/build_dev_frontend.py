#!/usr/bin/env python3
"""Build the Windows frontend and Linux helper, without publishing or signing."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
import zipfile

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.dev_workflow.common import HOST_ABI, PROTOCOL, digest, encode, require

ROOT = Path(__file__).resolve().parents[1]


def python_inventory(output: Path) -> None:
    """Retain actual Python and bootloader license texts, including vendored terms."""
    import shutil
    import re
    licenses = output / "licenses"
    licenses.mkdir()
    shutil.copyfile(Path(sys.base_prefix) / "LICENSE.txt", licenses / "CPython-3.13.5.txt")
    shutil.copyfile(ROOT / "LICENSE", licenses / "LSF.txt")
    packages = []
    for line in (ROOT / "tools/dev-frontend-windows.lock").read_text().splitlines():
        match = re.fullmatch(r"([a-z0-9-]+)==([^ ]+) --hash=sha256:([a-f0-9]{64})", line)
        require(match is not None, "frontend-wheel-lock-format")
        name, version, checksum = match.groups()
        distribution = importlib.metadata.distribution(name)
        require(distribution.version == version, "frontend-build-dependency-version")
        retained = []
        for entry in distribution.files or []:
            if not any(part.lower().startswith(("license", "licence", "copying", "notice")) for part in entry.parts):
                continue
            source = Path(distribution.locate_file(entry))
            if source.is_file():
                directory = licenses / (name + "-" + version)
                directory.mkdir(exist_ok=True)
                destination = directory / (str(len(retained)) + "-" + source.name)
                shutil.copyfile(source, destination)
                retained.append(destination.relative_to(output).as_posix())
        require(retained, "frontend-dependency-license-missing-" + name)
        packages.append({"name": name, "version": version, "wheelSha256": checksum, "licenses": retained,
                         "licenseDeclared": distribution.metadata.get("License-Expression") or "NOASSERTION"})
    (output / "python-inventory.json").write_bytes(encode({"python": platform.python_version(), "packages": packages,
        "pythonLicense": "licenses/CPython-3.13.5.txt", "scope": "CPython distribution and exact bootloader build inputs"}))


def helper(output: Path) -> str:
    entries = {"__main__.py": b"from tools.dev_workflow.helper import main\nraise SystemExit(main())\n",
               "tools/__init__.py": b""}
    for directory in ("tools/dev_workflow", "tools/native_runtime"):
        for path in sorted((ROOT / directory).glob("*.py")):
            # Windows implementation is omitted from the Linux helper.
            if path.name == "windows.py":
                continue
            entries[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    for name in ("build_process", "build_process_linux", "build_process_signals", "guest_runtime_profiles"):
        entries[f"tools/{name}.py"] = (ROOT / f"tools/{name}.py").read_bytes()
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in sorted(entries.items()):
            entry = zipfile.ZipInfo(name, (2026, 9, 23, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, raw)
    return digest(output.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--helper-only", action="store_true")
    arguments = parser.parse_args()
    output = arguments.output.absolute()
    require(output.is_relative_to(ROOT / "target") and not output.exists(), "new-owned-build-directory-required")
    output.mkdir(parents=True)
    helper_digest = helper(output / "helper.pyz")
    if arguments.helper_only:
        print(encode({"helperSha256": helper_digest}).decode(), end="")
        return 0
    require(sys.platform == "win32" and platform.machine().lower() == "amd64"
            and sys.version_info[:3] == (3, 13, 5), "windows-x64-python-3-13-5-required")
    require(importlib.metadata.version("pyinstaller") == "6.22.3", "pinned-pyinstaller-required")
    python_inventory(output)
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
        "--noupx", "--name", "latent-dev", "--distpath", str(output / "dist"),
        "--workpath", str(output / "work"), "--specpath", str(output), str(ROOT / "tools/latent_dev.py")],
        cwd=ROOT, check=True, timeout=300)
    executable = output / "dist/latent-dev/latent-dev.exe"
    require(executable.is_file(), "native-frontend-output-missing")
    # Run the packaged binary from outside the checkout, with no Python in PATH.
    import tempfile
    import os
    with tempfile.TemporaryDirectory(prefix="lsf-native-smoke-") as temporary:
        environment = {"SystemRoot": os.environ["SystemRoot"], "WINDIR": os.environ["WINDIR"],
                       "TEMP": temporary, "TMP": temporary, "PATH": str(Path(os.environ["SystemRoot"]) / "System32")}
        help_result = subprocess.run([str(executable), "--help"], cwd=temporary, env=environment,
                                     capture_output=True, timeout=30)
        require(help_result.returncode == 0 and b"latent-dev" in help_result.stdout, "packaged-frontend-start-failed")
        smoke = subprocess.run([str(executable), "dev", "doctor"], cwd=temporary, env=environment,
                               capture_output=True, timeout=30)
    require(smoke.returncode in {0, 2} and json.loads(smoke.stdout).get("schemaVersion") == "latent.dev.result.v1",
            "packaged-frontend-doctor-failed")
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT).strip())
    record = {"schemaVersion": "latent.dev.frontend-build.v1", "sourceCommit": source, "sourceDirty": dirty,
              "target": "windows-x86_64", "hostAbi": HOST_ABI, "protocol": PROTOCOL,
              "frontendSha256": digest(executable.read_bytes()), "helperSha256": helper_digest,
              "python": platform.python_version(), "packager": "pyinstaller-6.22.3",
              "lockSha256": digest((ROOT / "tools/dev-frontend-windows.lock").read_bytes()),
              "doctor": json.loads(smoke.stdout), "publisherAuthenticated": False,
              "qualification": "native-frontend-smoke-only"}
    (output / "build.json").write_bytes(encode(record))
    print(encode(record).decode(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
