"""Explicit executable-input approval with Linux namespace isolation.

Windows and hosts without working unprivileged Bubblewrap namespaces fail
closed. Namespace containment does not claim a hardened hostile-tenant VM.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys

from tools.application_dependency_store import DependencyError, directory_files, read_bytes, regular_path
from tools.build_process import run_bounded_result
from tools.build_snapshot import canonical, digest


def specification(executable: Path, arguments: list[str], inputs: Path, *, tool_version: str,
                  environment: dict[str, str] | None = None) -> dict:
    if (not isinstance(arguments, list) or len(arguments) > 64
            or any(not isinstance(arg, str) or not 0 < len(arg) <= 4096 or "\0" in arg for arg in arguments)
            or not isinstance(tool_version, str) or not 0 < len(tool_version) <= 80):
        raise DependencyError("dependency-generator-specification")
    selected = environment or {}
    if set(selected) - {"LANG", "LC_ALL", "TZ", "SOURCE_DATE_EPOCH"}:
        raise DependencyError("dependency-generator-environment-denied")
    return {"formatVersion": 1, "executableDigest": digest(read_bytes(executable)),
            "arguments": arguments, "inputsDigest": digest(canonical({
                name: digest(data) for name, data in directory_files(inputs).items()})),
            "toolVersion": tool_version, "environment": selected,
            "network": "denied", "outputPath": "/outputs", "isolation": "linux-bubblewrap-namespaces-v1"}


def execute(executable: Path, arguments: list[str], inputs: Path, outputs: Path, receipt: Path, *,
            tool_version: str, approved_identity: str, environment: dict[str, str] | None = None,
            timeout_seconds: int = 60, maximum_output_bytes: int = 1024 * 1024) -> dict:
    selected = specification(executable, arguments, inputs, tool_version=tool_version, environment=environment)
    identity = digest(canonical(selected))
    if approved_identity != identity:
        raise DependencyError("dependency-generator-approval-mismatch")
    if sys.platform != "linux" or not (sandbox := shutil.which("bwrap")):
        raise DependencyError("dependency-generator-isolation-host-unsupported")
    executable, inputs, outputs = map(regular_path, (executable, inputs, outputs))
    if inputs == outputs or inputs in outputs.parents or outputs in inputs.parents or outputs.exists():
        raise DependencyError("dependency-generator-output-owner")
    outputs.mkdir(mode=0o700)
    # No inherited home, credentials, signing keys or network namespace. Only
    # approved read-only tool/sysroot and input mounts, plus owned output/tmp.
    command = [sandbox, "--unshare-all", "--die-with-parent", "--new-session", "--clearenv",
               "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--dir", "/home",
               "--setenv", "HOME", "/home", "--setenv", "PATH", "/usr/bin:/bin",
               "--ro-bind", str(inputs), "/inputs", "--bind", str(outputs), "/outputs",
               "--ro-bind", str(executable), "/tool", "--chdir", "/inputs"]
    for name in ("/usr", "/bin", "/lib", "/lib64"):
        if Path(name).exists():
            command += ["--ro-bind", str(Path(name).resolve()), name]
    for key, value in selected["environment"].items():
        command += ["--setenv", key, value]
    command += ["--", "/tool", *arguments]
    record = {"formatVersion": 1, "identity": identity, "specification": selected,
              "sandboxDigest": digest(read_bytes(Path(sandbox))), "status": "failed", "cleanup": "unconfirmed"}
    try:
        result = run_bounded_result(command, cwd=inputs, env={"PATH": os.defpath},
                                    timeout_seconds=timeout_seconds, max_output_bytes=maximum_output_bytes)
        record.update(exitCode=result.returncode, cleanup="reaped", status="succeeded" if result.returncode == 0 else "failed")
        # Build tool diagnostics can contain source confidences. Retain only
        # digests publicly; bounded private logs belong to the calling recipe.
        record["diagnosticsDigest"] = digest(result.stdout + b"\n" + result.stderr)
        record["outputs"] = {name: digest(data) for name, data in directory_files(outputs).items()}
        if result.returncode != 0:
            raise DependencyError("dependency-generator-stage-failed")
        if specification(executable, arguments, inputs, tool_version=tool_version, environment=environment) != selected:
            raise DependencyError("dependency-generator-input-mutated")
        return record
    finally:
        with receipt.open("xb") as stream:
            stream.write(canonical(record) + b"\n")
