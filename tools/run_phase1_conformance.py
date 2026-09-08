#!/usr/bin/env python3
"""Run only the bounded Phase 1 profile; never scale, soak or calibrate.

Fixtures must already exist (tools/validate_contracts.sh builds them). Every run
uses a new artifact directory; failed/missing drivers cannot reuse old evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import selectors
import signal
import subprocess
import sys
import tempfile
import time

from validate_phase1_conformance import load_bounded

ROOT = Path(__file__).resolve().parents[1]
MAX_LOG = 4 * 1024 * 1024
PARITY_TEST = "standalone::parity::adapter_and_rpc_have_equivalent_selected_outcomes"
PROCESS_TEST = "phase1_bounded_child_conformance"


def bounded_run(command: list[str], log: Path, timeout: float, env: dict[str, str]) -> bytes:
    """Bound pipes, wall time and the entire disposable driver process group."""
    deadline = time.monotonic() + timeout
    output = bytearray()
    with log.open("xb") as sink, selectors.DefaultSelector() as selector:
        child = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 start_new_session=True)
        assert child.stdout is not None
        try:
            os.set_blocking(child.stdout.fileno(), False)
            selector.register(child.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError(f"driver deadline exceeded: {log.name}")
                for key, _ in selector.select(min(remaining, 0.1)):
                    data = os.read(key.fd, 16 * 1024)
                    if not data:
                        selector.unregister(key.fileobj)
                        continue
                    if len(output) + len(data) > MAX_LOG:
                        raise RuntimeError(f"driver output exceeded 4 MiB: {log.name}")
                    output.extend(data)
                    sink.write(data)
                    sink.flush()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(f"driver deadline exceeded: {log.name}")
            code = child.wait(timeout=remaining)
            if code:
                raise RuntimeError(f"driver exited {code}: {log.name}")
        finally:
            # Also handles a failed test that left its owned node behind.
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait(timeout=5)
            child.stdout.close()
    return bytes(output)


def digest(path: Path, maximum: int = 1024 * 1024 * 1024) -> tuple[str, int]:
    size = path.stat().st_size
    if not path.is_file() or size <= 0 or size > maximum:
        raise ValueError(f"missing or oversized required artifact: {path}")
    result = hashlib.sha256()
    with path.open("rb") as source:
        total = 0
        while chunk := source.read(64 * 1024):
            total += len(chunk)
            if total > maximum:
                raise ValueError("artifact changed beyond read limit")
            result.update(chunk)
    if total != size:
        raise ValueError("artifact changed while hashing")
    return "sha256:" + result.hexdigest(), size


def identity(name: str, path: Path, maximum: int = 1024 * 1024 * 1024) -> dict:
    sha, size = digest(path, maximum)
    return {"name": name, "sha256": sha, "bytes": str(size)}


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True,
                          text=True, timeout=10).stdout.strip()


def build_test(package: str, selection: list[str], name: str, output: Path,
               env: dict[str, str]) -> Path:
    data = bounded_run(["cargo", "test", "-p", package, *selection, "--no-run",
                        "--message-format=json", "--locked"], output / f"build-{name}.log", 600, env)
    matches = []
    for line in data.splitlines():
        try:
            row = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            continue
        if (row.get("reason") == "compiler-artifact" and row.get("executable")
                and row.get("profile", {}).get("test")
                and row.get("target", {}).get("name") == name):
            matches.append(Path(row["executable"]))
    if len(matches) != 1:
        raise RuntimeError(f"expected one built test executable: {name}")
    return matches[0]


def run(output: Path, target: Path) -> None:
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(target)
    fixtures = {"echo": target / "capsules/echo/echo-capsule.wasm",
                "generic": target / "capsules/generic/generic-capsule.wasm",
                "capabilities": target / "capsules/capabilities/capabilities-capsule.wasm"}
    binaries = {"latent": target / "debug/latent", "latentd": target / "debug/latentd"}
    # Required fixtures fail before execution, never silently skip a scenario.
    for path in (*fixtures.values(), *binaries.values()):
        if not path.is_file() or path.stat().st_size <= 0:
            raise ValueError(f"missing required profile input: {path}")
    parity = build_test("latentd", ["--lib"], "latentd", output, env)
    process = build_test("latent", ["--test", "phase1_conformance"], "phase1_conformance", output, env)
    fixture_ids = [identity(name, path, 16 * 1024 * 1024) for name, path in fixtures.items()]
    binary_ids = [identity(name, path) for name, path in binaries.items()]
    source = {"source_commit": git("rev-parse", "HEAD"), "source_tree": git("rev-parse", "HEAD^{tree}"),
              "source_dirty": bool(git("status", "--porcelain", "--untracked-files=normal")),
              "cargo_lock_sha256": digest(ROOT / "Cargo.lock")[0], "config_sha256": "sha256:" + "0" * 64,
              "binaries": binary_ids + [identity("adapter-test", parity), identity("process-test", process)],
              "fixtures": fixture_ids}
    identity_path = output / "identity.json"
    identity_path.write_text(json.dumps(source, indent=2) + "\n", encoding="utf-8")
    parity_path = output / "adapter.json"
    env.update({"LSF_PHASE1_OUTPUT_DIR": str(output), "LSF_PHASE1_IDENTITY": str(identity_path),
                "LSF_PHASE1_PARITY_REPORT": str(parity_path), "LSF_LATENTD_BIN": str(binaries["latentd"]),
                "LSF_ECHO_COMPONENT": str(fixtures["echo"]), "LSF_GENERIC_COMPONENT": str(fixtures["generic"]),
                "LSF_CAPABILITIES_COMPONENT": str(fixtures["capabilities"])})
    env["LSF_PHASE1_RUST_VERSION"] = subprocess.run(["rustc", "--version"], check=True, capture_output=True, text=True, timeout=10).stdout.strip()
    started = time.monotonic()
    bounded_run([str(parity), "--exact", PARITY_TEST, "--ignored", "--nocapture", "--test-threads=1"],
                output / "adapter.log", 50, env)
    digest(parity_path, MAX_LOG)
    remaining = min(65, 120 - (time.monotonic() - started))
    bounded_run([str(process), "--exact", PROCESS_TEST, "--ignored", "--nocapture", "--test-threads=1"],
                output / "process.log", remaining, env)
    report_path = output / "conformance.json"
    digest(report_path, MAX_LOG)
    # The driver cannot hash its own output until the parent has closed the pipe.
    report = load_bounded(report_path)
    existing = {entry["path"] for entry in report["artifacts"]}
    for name in ("adapter.log", "process.log", "adapter.json", "identity.json"):
        if name not in existing:
            sha, size = digest(output / name, MAX_LOG)
            report["artifacts"].append({"path": name, "sha256": sha, "bytes": str(size)})
    report["environment"]["profile_elapsed_millis"] = str(int((time.monotonic() - started) * 1000))
    encoded = bytearray()
    for chunk in json.JSONEncoder(indent=2, ensure_ascii=False).iterencode(report):
        data = chunk.encode("utf-8")
        if len(encoded) + len(data) + 1 > MAX_LOG:
            raise ValueError("final evidence exceeds report cap")
        encoded.extend(data)
    encoded.extend(b"\n")
    report_path.write_bytes(encoded)
    validation = [sys.executable, "tools/validate_phase1_conformance.py", str(report_path),
                  "--artifacts-root", str(output), "--expected-source-commit", source["source_commit"],
                  "--cargo-lock", str(ROOT / "Cargo.lock")]
    for name, path in {**binaries, "adapter-test": parity, "process-test": process}.items():
        validation.extend(["--binary", f"{name}={path}"])
    for name, path in fixtures.items():
        validation.extend(["--fixture", f"{name}={path}"])
    bounded_run(validation, output / "validation.log", 10, env)
    print(f"Bounded Phase 1 evidence passed: {report_path}")
    print(f"Invoke attempts: {report['work']['invoke_attempts']}/64; full Phase 1 gate remains incomplete.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="new or empty artifact directory")
    parser.add_argument("--target-root", type=Path, default=Path(os.environ.get("CARGO_TARGET_DIR", "target")))
    args = parser.parse_args()
    if platform.system() != "Linux":
        parser.error("the actual standalone child resource profile requires Linux")
    target = args.target_root.resolve()
    if args.output is None:
        parent = target / "phase1-conformance"
        parent.mkdir(parents=True, exist_ok=True)
        output = Path(tempfile.mkdtemp(prefix="run-", dir=parent))
    else:
        output = args.output.resolve()
        output.mkdir(parents=True, exist_ok=True)
        if any(output.iterdir()):
            parser.error("artifact directory must be empty; old evidence cannot satisfy a new run")
    try:
        run(output, target)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, KeyError) as error:
        (output / "failure.json").write_text(json.dumps({"schema": "latent.phase1.runner-failure.v1",
            "deterministic_status": "failed", "phase1_completion": "incomplete", "reason": str(error)}) + "\n", encoding="utf-8")
        print(f"Bounded Phase 1 profile failed; diagnostics: {output}\n{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
