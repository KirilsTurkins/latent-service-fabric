#!/usr/bin/env python3
"""Observe current Java compiler candidates; never assert guest qualification."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import tomllib

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "research/java-capsules"
LIMIT = 8 * 1024 * 1024


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return "sha256:" + hashlib.file_digest(source, "sha256").hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def snapshot(root: Path = ROOT) -> dict:
    paths = [root / name for name in (
        "Cargo.toml", "Cargo.lock", "tools/toolchain.toml",
        "tools/build_process.py", "tools/build_process_linux.py",
        "tools/build_process_windows.py", "tools/build_process_signals.py",
        "sdk/java-client/tools/java_toolchain.py",
        "crates/latent-wasmtime/src/config.rs",
        "crates/latent-wasmtime/src/config/engine.rs",
        "crates/latent-wasmtime/src/surface.rs")]
    for directory in ("research/java-capsules", "wit/platform"):
        paths.extend(path for path in (root / directory).rglob("*")
                     if path.is_file() and not set(path.relative_to(root / directory).parts)
                     & {"build", ".gradle", "__pycache__"})
    if len(paths) > 2048 or sum(path.stat().st_size for path in paths) > 32 * LIMIT:
        raise ValueError("source-snapshot-limit")
    return {path.relative_to(root).as_posix(): {"sha256": digest(path), "bytes": path.stat().st_size}
            for path in sorted(paths)}


def version_matches(output: str, expected: str) -> bool:
    """Match the version token, not a prefix; allow wasm-tools build identity."""
    if expected.startswith("wasm-tools "):
        return re.fullmatch(re.escape(expected) + r"(?: \([0-9a-f]{7,40} \d{4}-\d{2}-\d{2}\))?",
                            output.strip()) is not None
    return expected in output.splitlines()


def child(arguments: list[str]) -> None:
    """Preserve a trusted compiler's nonzero status inside the owned supervisor.

    The outer run_bounded owns this entire process group, output cap, deadline,
    and descendant cleanup. This child never catches cancellation or uses a shell.
    A zero child status means status capture completed, NOT compilation succeeded.
    """
    status, *command = arguments
    try:
        result = subprocess.run(command, check=False)
        value = {"started": True, "returncode": result.returncode}
    except OSError as error:
        value = {"started": False, "error": type(error).__name__}
    write_json(Path(status), value)


class Attempt:
    def __init__(self, output: Path, environment: dict[str, str]):
        self.output = output
        self.environment = environment
        self.deadline = time.monotonic() + 900
        self.phases: list[dict] = []

    def run(self, name: str, command: list[str], cwd: Path = ROOT) -> dict:
        from tools.build_process import BuildProcessError, run_bounded
        directory = self.output / "phases" / name
        directory.mkdir(parents=True)
        record = {"name": name, "argv": command, "status": "not-started"}
        self.phases.append(record)
        started = time.monotonic()
        try:
            result = run_bounded(
                [sys.executable, str(PROJECT / "probe.py"), "--child",
                 str(directory / "exit.json"), *command], cwd, self.environment,
                timeout_seconds=min(300, max(0.001, self.deadline - started)),
                max_output_bytes=LIMIT)
            (directory / "stdout.txt").write_bytes(result.stdout)
            (directory / "stderr.txt").write_bytes(result.stderr)
            status = json.loads((directory / "exit.json").read_text())
            record.update(status)
            record["status"] = ("passed" if status.get("returncode") == 0 else
                                "failed" if status.get("started") else "environment-error")
            for stream in ("stdout", "stderr"):
                path = directory / (stream + ".txt")
                record[stream] = {"path": str(path.relative_to(self.output)),
                                  "sha256": digest(path), "bytes": path.stat().st_size}
            print(f"{name}: {record['status']}", flush=True)
            if record["status"] != "passed":
                print(result.stderr.decode("utf-8", errors="replace")[-8192:], flush=True)
        except BuildProcessError as error:
            record.update(status="supervision-error", reason=error.reason)
        finally:
            record["elapsedSeconds"] = round(time.monotonic() - started, 6)
            write_json(directory / "phase.json", record)
        return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--capture-dependencies", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    if output == ROOT or (output.is_relative_to(ROOT) and not output.is_relative_to(ROOT / "target")):
        parser.error("output must be outside source directories")
    output.mkdir(parents=True, exist_ok=False)
    receipt = {"formatVersion": 1, "issue": 548, "qualification": "not-qualified",
               "attemptKind": "compiler-feasibility", "startedAt": int(time.time()),
               "dependencyInputs": "captured-not-reviewed" if args.capture_dependencies else "locked",
               "nodeExecution": "not-attempted", "phases": [],
               "measurements": {"guestStartupSeconds": None, "activeGuestBytes": None,
                                "gcBytes": None, "cancellationCleanupSeconds": None}}
    write_json(output / "receipt.json", receipt)
    sys.path.insert(0, str(ROOT))
    try:
        inputs = snapshot()
        write_json(output / "source-inputs.json", inputs)
        receipt["sourceSnapshotSha256"] = digest(output / "source-inputs.json")
        config = tomllib.loads((ROOT / "tools/toolchain.toml").read_text())
        receipt["pins"] = {"java": config["sdk"]["java"], "gradle": config["sdk"]["gradle"],
                           "zig": config["sdk"]["zig"], "wasmTools": config["contracts"]["wasm-tools"],
                           "wasmtime": config["rust"]["dependencies"]["wasmtime"], "teaVM": "0.15.0"}
        tools = {}
        for name in ("java", "javac", "gradle", "zig", "wasm-tools"):
            executable = shutil.which(name)
            if executable is None:
                raise ValueError("missing-tool-" + name)
            tools[name] = str(Path(executable).resolve(strict=True))
        receipt["tools"] = {name: {"path": path, "sha256": digest(Path(path))}
                            for name, path in tools.items()}
        project = output / "project"
        shutil.copytree(PROJECT, project, ignore=shutil.ignore_patterns("build", ".gradle", "__pycache__"))
        if not args.capture_dependencies and not all((project / path).is_file() for path in
                ("gradle.lockfile", "gradle/verification-metadata.xml")):
            raise ValueError("dependency-locks-not-captured-and-reviewed")
        environment = {key: value for key, value in os.environ.items()
                       if key in {"PATH", "JAVA_HOME", "HOME", "TMPDIR", "TEMP", "SYSTEMROOT"}}
        environment.update({"GRADLE_USER_HOME": str(output / "gradle-home"),
                            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"})
        attempt = Attempt(output, environment)
        receipt["phases"] = attempt.phases
        versions = [
            ("java-toolchain", [sys.executable, str(ROOT / "sdk/java-client/tools/java_toolchain.py"), "check"], None),
            ("gradle-version", [tools["gradle"], "--version"], "Gradle " + config["sdk"]["gradle"]),
            ("zig-version", [tools["zig"], "version"], config["sdk"]["zig"]),
            ("wasm-tools-version", [tools["wasm-tools"], "--version"], "wasm-tools " + config["contracts"]["wasm-tools"])]
        for name, command, expected in versions:
            phase = attempt.run(name, command)
            if phase["status"] != "passed":
                raise ValueError("toolchain-check-failed-" + name)
            if expected and not version_matches((output / phase["stdout"]["path"]).read_text(), expected):
                raise ValueError("toolchain-version-mismatch-" + name)
        gradle = [tools["gradle"], "--no-daemon", "--console=plain", "--max-workers=2",
                  "-p", str(project), "-PlsfOutput=" + str(output / "build")]
        gradle += (["--write-locks", "--write-verification-metadata", "sha256"]
                   if args.capture_dependencies else ["--dependency-verification", "strict"])
        sanity = attempt.run("java-source-sanity-not-guest-execution", [*gradle, "checkSourceSemantics"])
        if sanity["status"] != "passed":
            raise ValueError("java-source-sanity-failed")
        for name, task, directory in (("c", "compileC", "C"), ("gc", "compileGC", "WEBASSEMBLY_GC")):
            built = attempt.run("teavm-" + name, [*gradle, task])
            if built["status"] != "passed":
                continue
            generated = output / "build" / directory
            if name == "c":
                built = attempt.run("c-wasi-link", [tools["zig"], "cc", "-target", "wasm32-wasi",
                    "-O2", "-mexec-model=reactor", "-Wl,--export=java_probe",
                    str(generated / "all.c"), "-o", str(generated / "probe.wasm")])
                if built["status"] != "passed":
                    continue
            core = generated / "probe.wasm"
            if not core.is_file() or core.stat().st_size > 16 * LIMIT:
                raise ValueError("core-output-missing-or-oversized-" + name)
            attempt.run(name + "-validate", [tools["wasm-tools"], "validate", str(core)])
            attempt.run(name + "-inspect", [tools["wasm-tools"], "print", str(core)])
            embedded = generated / "embedded.wasm"
            built = attempt.run(name + "-embed-wit", [tools["wasm-tools"], "component", "embed",
                str(project / "probe.wit"), str(core), "--world", "capsule", "-o", str(embedded)])
            if built["status"] == "passed":
                attempt.run(name + "-component", [tools["wasm-tools"], "component", "new", str(embedded),
                    "-o", str(generated / "component.wasm")])
        if snapshot() != inputs:
            raise ValueError("source-inputs-changed-during-attempt")
        receipt["observation"] = "completed"
        receipt["remainingGate"] = "maintained-canonical-bindings-and-real-node-conformance-required"
    except (ValueError, OSError) as error:
        receipt["observation"] = "environment-or-recipe-error"
        receipt["reason"] = str(error)
    finally:
        receipt["finishedAt"] = int(time.time())
        write_json(output / "receipt.json", receipt)
        print(json.dumps(receipt, indent=2), flush=True)
    # A core module, a failed feasibility attempt, or a JVM sanity check never
    # establishes the issue's guest-authoring acceptance criteria.
    return 2


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        child(sys.argv[2:])
    else:
        raise SystemExit(main())
