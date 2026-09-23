#!/usr/bin/env python3
"""Retain Java compiler/component feasibility evidence; never certify an SDK."""
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
PROJECT = Path("research/java-capsules")
TEAVM_VERSION = "0.15.0"
MAX_CAPTURE = 4 * 1024 * 1024
REMAINING = [
    "maintained-generated-java-wit-bindings", "canonical-abi-and-async-resource-ownership",
    "all-eight-guest-capability-wrappers", "real-node-allowed-and-denied-capabilities",
    "authoritative-greeting-word-count-shipping-contracts", "signed-package-admission-lifecycle",
    "real-node-deadline-cancellation-trap-exhaustion-and-fresh-state",
    "runtime-gc-startup-cache-memory-and-reclamation-measurements",
    "verified-transitive-dependency-lock-and-binding-drift-ci", "newcomer-guide-and-review",
]


def identity(path: Path) -> dict:
    """Hash a bounded regular file without loading a compiler binary into memory."""
    if not path.is_file() or path.stat().st_size > 256 * 1024 * 1024:
        raise ValueError("input-not-a-bounded-file")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while block := source.read(65536):
            size += len(block)
            if size > 256 * 1024 * 1024:
                raise ValueError("input-byte-limit")
            digest.update(block)
    return {"sha256": digest.hexdigest(), "size": size}


def write_json(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as target:
        json.dump(value, target, indent=2, sort_keys=True)
        target.write("\n")


def source_snapshot(root: Path) -> tuple[dict, list[str]]:
    required = ["Cargo.toml", "Cargo.lock", "rust-toolchain.toml", "tools/toolchain.toml",
                "tools/stage_runtime_wit.py", "tools/build_process.py",
                "tools/build_process_linux.py", "tools/build_process_windows.py",
                "tools/build_process_signals.py", "crates/latent-wasmtime/src/surface.rs",
                "crates/latent-wasmtime/src/config.rs", "crates/latent-wasmtime/src/config/engine.rs"]
    paths = {root / name for name in required}
    missing = []
    for directory, suffixes in ((root / PROJECT, {".py", ".java", ".kts", ".wit"}),
                                (root / "wit/platform", {".wit"})):
        selected = {path for path in directory.rglob("*") if path.suffix in suffixes
                    and ".gradle" not in path.parts and "build" not in path.parts}
        if not selected:
            missing.append(directory.relative_to(root).as_posix())
        paths.update(selected)
    if len(paths) > 4096:
        raise ValueError("source-count-limit")
    records, total = {}, 0
    for path in sorted(paths):
        name = path.relative_to(root).as_posix()
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            missing.append(name)
            continue
        record = identity(path)
        total += record["size"]
        if total > 32 * 1024 * 1024:
            raise ValueError("source-byte-limit")
        records[name] = record
    return records, sorted(missing)


def environment(output: Path) -> dict[str, str]:
    result = {"PATH": os.environ.get("PATH", os.defpath), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
    for name in ("JAVA_HOME", "SYSTEMROOT", "WINDIR"):
        if name in os.environ:
            result[name] = os.environ[name]
    for directory, names in (("home", ("HOME", "USERPROFILE")),
                              ("tmp", ("TMPDIR", "TEMP", "TMP")),
                              ("gradle-home", ("GRADLE_USER_HOME",))):
        path = output / directory
        path.mkdir()
        result.update({name: str(path) for name in names})
    return result


def bounded(command: list[str], cwd: Path, env: dict, timeout: float, maximum: int):
    sys.path.insert(0, str(ROOT))
    from tools.build_process import run_bounded
    return run_bounded(command, cwd, env, timeout_seconds=timeout, max_output_bytes=maximum)


def capture_status(arguments: list[str]) -> int:
    """Trusted child shim: preserve a compiler's nonzero exit without losing logs.

    The existing process owner bounds inherited pipes and owns all descendants.
    This shim does not capture, retry, detach, or interpret compiler output.
    """
    status, *command = arguments
    try:
        result = {"exitCode": subprocess.run(command, check=False).returncode}
    except OSError:
        result = {"launchError": True}
    write_json(Path(status), result)
    return 0


class Probe:
    def __init__(self, root: Path, output: Path, runner=bounded, timeout: float = 1800):
        if not 0 < timeout <= 1800:
            raise ValueError("invalid-probe-deadline")
        self.root, self.output, self.runner = root.resolve(), output.resolve(), runner
        target = self.root / "target"
        if self.output == target or not self.output.is_relative_to(target):
            raise ValueError("output-must-be-a-new-directory-below-target")
        self.output.mkdir(parents=True, exist_ok=False)
        self.env = environment(self.output)
        self.deadline = time.monotonic() + timeout
        self.report = {"schemaVersion": "latent.java-guest.feasibility.v1", "issue": 548,
                       "qualification": "not-qualified", "probeStatus": "incomplete",
                       "canCloseIssue": False, "nodeInvoked": False, "admissionExercised": False,
                       "runtimeMeasurements": None, "remaining": REMAINING.copy(),
                       "compiler": {"name": "TeaVM", "version": TEAVM_VERSION},
                       "dependencyCompleteness": "unverified-transitive-graph",
                       "steps": [], "artifacts": {}, "inputs": {}, "missingInputs": []}
        self.tools: dict[str, str] = {}

    def note(self, name: str, status: str, reason: str) -> None:
        self.report["steps"].append({"name": name, "status": status, "reason": reason})

    def step(self, name: str, command: list[str], cwd: Path | None = None) -> dict:
        number = len(self.report["steps"])
        prefix = self.output / f"{number:02d}-{name}"
        status_path = prefix.with_suffix(".exit.json")
        record = {"name": name, "command": command, "status": "infrastructure-error"}
        started = time.monotonic()
        try:
            seconds = min(600.0, self.deadline - started)
            if seconds <= 0:
                raise ValueError("probe-deadline")
            result = self.runner([sys.executable, str(Path(__file__).resolve()), "_capture",
                                  str(status_path), *command], cwd or self.root, self.env,
                                 seconds, MAX_CAPTURE)
            outcome = json.loads(status_path.read_text(encoding="utf-8"))
            if type(outcome.get("exitCode")) is not int or set(outcome) != {"exitCode"}:
                raise ValueError("command-status-invalid-or-launch-failed")
            record.update(exitCode=outcome["exitCode"],
                          status="passed" if outcome["exitCode"] == 0 else "failed")
            for stream in ("stdout", "stderr"):
                path = prefix.with_suffix(f".{stream}.log")
                with path.open("xb") as target:
                    target.write(getattr(result, stream))
                record[stream] = {"path": path.name, **identity(path)}
        except (RuntimeError, ValueError, OSError) as error:
            # The shared runner deliberately discards capture on deadline,
            # overflow or cleanup failure. Record that absence, not a fake log.
            record.update(reason=getattr(error, "reason", type(error).__name__), captureDiscarded=True)
        finally:
            record["elapsedSeconds"] = round(time.monotonic() - started, 6)
            self.report["steps"].append(record)
        return record

    def text(self, step: dict) -> str:
        return "\n".join((self.output / step[name]["path"]).read_text(encoding="utf-8", errors="replace")
                         for name in ("stdout", "stderr") if name in step)

    def check_tools(self, config: dict) -> None:
        java = config["sdk"]["java"]
        expected = {
            "java": ("--version", rf"(?m)^.*(?:build|Runtime Environment).*\b{re.escape(java)}(?:-LTS)?[)\s]"),
            "javac": ("--version", rf"(?m)^javac {re.escape(java.split('+')[0])}$"),
            "gradle": ("--version", rf"(?m)^Gradle {re.escape(config['sdk']['gradle'])}$"),
            "wasm-tools": ("--version", rf"(?m)^wasm-tools {re.escape(config['contracts']['wasm-tools'])}(?:\s|$)"),
            "wit-bindgen": ("--version", rf"(?m)^wit-bindgen(?:-cli)? {re.escape(config['rust']['dependencies']['wit-bindgen'])}(?:\s|$)"),
            "zig": ("version", rf"^{re.escape(config['sdk']['zig'])}\s*$"),
        }
        self.report["toolchain"] = {"java": java, "gradle": config["sdk"]["gradle"],
                                    "wasmtime": config["rust"]["dependencies"]["wasmtime"],
                                    "witBindgen": config["rust"]["dependencies"]["wit-bindgen"],
                                    "wasmTools": config["contracts"]["wasm-tools"], "zig": config["sdk"]["zig"]}
        for name, (argument, pattern) in expected.items():
            located = shutil.which(name, path=self.env["PATH"])
            if located is None:
                self.note(name, "infrastructure-error", "tool-not-found")
                continue
            path = Path(located).resolve(strict=True)
            record = self.step(name, [str(path), argument])
            record["executable"] = identity(path)
            if record["status"] != "passed" or not re.search(pattern, self.text(record)):
                record.update(status="infrastructure-error", reason="pinned-tool-version-unavailable")
                continue
            self.tools[name] = str(path)
            if name == "java":
                # Gradle must use the JVM that was checked, not another inherited
                # JAVA_HOME. Runtime invocation remains outside this probe.
                self.env["JAVA_HOME"] = str(path.parent.parent)
        if "java" in self.tools and "javac" in self.tools:
            if Path(self.tools["java"]).parent != Path(self.tools["javac"]).parent:
                self.note("java-home", "infrastructure-error", "java-and-javac-installations-differ")
                self.tools.pop("javac")

    def componentize(self, name: str, core: Path) -> None:
        if not core.is_file():
            self.note(name, "failed", "compiler-output-missing")
            return
        self.report["artifacts"][core.relative_to(self.output).as_posix()] = identity(core)
        if "wasm-tools" not in self.tools:
            self.note(name, "not-run", "wasm-tools-prerequisite")
            return
        wasm_tools = self.tools["wasm-tools"]
        if self.step(name + "-validate", [wasm_tools, "validate", str(core)])["status"] != "passed":
            return
        self.step(name + "-inspect", [wasm_tools, "print", str(core)])
        embedded, component = core.with_name("embedded.wasm"), core.with_name("component.wasm")
        if self.step(name + "-embed", [wasm_tools, "component", "embed", str(self.root / PROJECT / "probe.wit"),
                                      str(core), "--world", "probe", "-o", str(embedded)])["status"] == "passed":
            # No stub exports, fabricated imports or permissive adapter. Raw
            # componentization failure is NOT proof that an adapter is impossible.
            result = self.step(name + "-componentize", [wasm_tools, "component", "new", str(embedded), "-o", str(component)])
            if result["status"] == "passed" and component.is_file():
                self.report["artifacts"][component.relative_to(self.output).as_posix()] = identity(component)
                self.note(name + "-node", "not-run", "no-qualified-java-wit-bridge-or-node-harness")

    def compile_candidates(self) -> None:
        project = self.root / PROJECT
        build = (project / "build.gradle.kts").read_text(encoding="utf-8")
        if f'val teavmVersion = "{TEAVM_VERSION}"' not in build:
            raise ValueError("compiler-pin-drift")
        if not {"java", "javac", "gradle"}.issubset(self.tools):
            self.note("java-compilation", "not-run", "pinned-java-gradle-prerequisites")
            return
        command = [self.tools["gradle"], "--no-daemon", "--console=plain", "--max-workers=2",
                   "--project-cache-dir", str(self.output / "project-cache"), "-p", str(project),
                   f"-PlsfProbeOutput={self.output}", "prepareProbe"]
        if self.step("prepare-java", command)["status"] != "passed":
            self.note("dependency-resolution-or-javac", "infrastructure-error", "inspect-prepare-java-logs")
            return
        classpath = (self.output / "classpath.txt").read_text(encoding="utf-8")
        if not classpath or len(classpath) > 24000:
            raise ValueError("classpath-invalid")
        self.report["artifacts"]["resolved-artifacts.tsv"] = identity(self.output / "resolved-artifacts.tsv")
        java = [self.tools["java"], "-Xmx512m", "-cp", classpath]
        self.step("jvm-corpus-not-node-evidence", [*java, "lsf.qualification.FeatureProbe"])
        targets = self.step("compiler-targets", [*java, "lsf.qualification.CompileProbe", "--targets"])
        if targets["status"] == "passed":
            self.report["compiler"]["observedTargets"] = self.text(targets).split()
        for target, directory in (("WEBASSEMBLY_GC", "wasm-gc"), ("C", "c")):
            output = self.output / directory
            if self.step("compile-" + directory, [*java, "lsf.qualification.CompileProbe", target, str(output)])["status"] != "passed":
                continue
            if target == "C":
                if "zig" not in self.tools:
                    self.note("c-to-wasm", "not-run", "zig-prerequisite")
                    continue
                if self.step("c-to-wasm", [self.tools["zig"], "cc", "-target", "wasm32-wasi", "-O2",
                                           "-D_GNU_SOURCE", "-D_XOPEN_SOURCE=700", "all.c", "-o", "probe.wasm"], output)["status"] != "passed":
                    continue
            self.componentize(directory, output / "probe.wasm")

    def run(self) -> int:
        snapshot = None
        try:
            config = tomllib.loads((self.root / "tools/toolchain.toml").read_text(encoding="utf-8"))
            self.check_tools(config)
            snapshot = source_snapshot(self.root)
            self.report["inputs"], self.report["missingInputs"] = snapshot
            if snapshot[1]:
                self.note("source-snapshot", "infrastructure-error", "required-source-inputs-missing")
                return 3
            if "wit-bindgen" in self.tools:
                legacy = self.step("removed-java-generator", [self.tools["wit-bindgen"], "teavm-java", "--help"])
                if legacy.get("exitCode") == 2 and re.search(r"unrecognized subcommand ['`]teavm-java['`]", self.text(legacy)):
                    legacy.update(status="blocked", reason="obsolete-java-generator-unavailable-no-fallback")
                sys.path.insert(0, str(self.root))
                from tools.stage_runtime_wit import stage
                staged = self.output / "platform-wit"
                stage(staged, self.root / "wit/platform/runtime-phase3-blobs")
                self.step("current-platform-c-bindings-reference-only", [self.tools["wit-bindgen"], "c", str(staged),
                          "--out-dir", str(self.output / "platform-c-bindings")])
            self.compile_candidates()
        except (KeyboardInterrupt, SystemExit):
            self.note("probe-cancellation", "cancelled", "interrupted-no-qualification")
            raise
        except (OSError, ValueError, KeyError, RuntimeError, ImportError) as error:
            self.note("probe", "infrastructure-error", getattr(error, "reason", type(error).__name__))
        finally:
            if snapshot is not None:
                try:
                    if snapshot != source_snapshot(self.root):
                        self.note("source-snapshot", "infrastructure-error", "source-inputs-changed")
                except (OSError, ValueError):
                    self.note("source-snapshot", "infrastructure-error", "source-recheck-failed")
            statuses = {step["status"] for step in self.report["steps"]}
            status = "cancelled" if "cancelled" in statuses else (
                "infrastructure-error" if "infrastructure-error" in statuses else (
                    "blocked" if statuses & {"failed", "blocked"} else "incomplete"))
            self.report["probeStatus"] = status
            write_json(self.output / "report.json", self.report)
        return 3 if self.report["probeStatus"] == "infrastructure-error" else 2


def main(arguments: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if arguments is None else arguments
    if arguments and arguments[0] == "_capture":
        return capture_status(arguments[1:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="new directory below repository target/")
    args = parser.parse_args(arguments)
    try:
        probe = Probe(ROOT, args.output)
        status = probe.run()
        print(f"Java guest: {probe.report['probeStatus']}; NOT QUALIFIED; evidence: {probe.output / 'report.json'}")
        return status
    except (OSError, ValueError) as error:
        print(f"Java guest probe failed before execution: {error}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
