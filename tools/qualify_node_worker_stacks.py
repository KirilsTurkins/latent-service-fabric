"""Exact-source node Tokio stack reference, not a full-node/TLS qualification."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import sys
import tomllib

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import ci_rust_artifacts as artifacts
from tools import ci_suite_discovery as discovery
from tools.owned_test_process import ProcessFailure, run_owned
from tools.rust_capsule_project import fresh
from tools.test_run import digest, redact

ROOT = Path(__file__).resolve().parents[1]
LOCK = "sdk/node-worker-stacks/reference-Cargo.lock"
LOCK_SHA256 = "7ea26385860428010c61ce075a9d6cfe612160301df44a4bab2538538a66084f"
PROFILE = "apps/latentd/src/worker_stacks.rs"
TESTS = "apps/latentd/src/worker_stacks/tests.rs"
STACK, GUARD, AMBIENT = 2 * 1024 * 1024, 64 * 1024, 8 * 1024 * 1024
CASES = frozenset("worker_stacks::tests::" + name for name in (
    "checked_profile_rejects_invalid_worker_and_blocking_counts",
    "two_blocking_workers_have_one_shared_checked_stack_envelope",
    "linux::stack_map_parser_rejects_missing_guard_ambiguous_and_oversized_ranges",
    "linux::actual_linux_worker_and_blocking_stacks_are_bounded_and_guarded",
    "linux::timed_out_shutdown_retains_live_blocking_thread_owner_until_real_stop",
))
ACTUAL = "worker_stacks::tests::linux::actual_linux_worker_and_blocking_stacks_are_bounded_and_guarded"
INPUTS = (PROFILE, TESTS, LOCK, "Cargo.lock", "Cargo.toml", "rust-toolchain.toml",
          "apps/latentd/src/lib_root.rs", "apps/latentd/src/config.rs",
          "apps/latentd/src/config/derive.rs", "apps/latentd/src/command/serve.rs",
          "apps/latentd/src/command/inspection.rs",
          "apps/latentd/src/standalone/observations/topology.rs",
          "crates/latent-wasmtime/src/config.rs", "crates/latent-wasmtime/src/config/engine.rs",
          "crates/latent-wasmtime/src/config/renderer.rs", "tools/qualify_node_worker_stacks.py")
MANIFEST = (b'[package]\nname="node-worker-stack-reference"\nversion="0.0.0"\nedition="2021"\n'
            b'[workspace]\nresolver="2"\n[dependencies]\n'
            b'tokio={version="=1.53.1",default-features=false,features=["macros","rt","sync","time","rt-multi-thread","net","signal","io-util"]}\n')


def read(root: Path, name: str, maximum: int = 4 * 1024 * 1024) -> bytes:
    path = root / name
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= maximum:
        raise ValueError("stack-reference-input")
    return path.read_bytes()


def locked(root: Path) -> bytes:
    raw = read(root, LOCK, 65536)
    if hashlib.sha256(raw).hexdigest() != LOCK_SHA256:
        raise ValueError("stack-reference-lock-identity")
    rows = tomllib.loads(raw.decode())["package"]
    workspace = tomllib.loads(read(root, "Cargo.lock").decode())["package"]
    if len(rows) != 17:
        raise ValueError("stack-reference-lock-size")
    for row in rows:
        if "source" not in row:
            if row != {"name": "node-worker-stack-reference", "version": "0.0.0", "dependencies": ["tokio"]}:
                raise ValueError("stack-reference-local-package")
        elif row not in workspace:
            raise ValueError("stack-reference-registry-coordinate")
    return raw


def original_semantics(source: bytes) -> bytes:
    anchor = b"            .thread_stack_size(THREAD_STACK_BYTES)\n"
    if source.count(anchor) != 1:
        raise ValueError("stack-reference-original-preimage")
    return source.replace(anchor, b"", 1)


def evidence(raw: bytes, cases: set[str]) -> list[str]:
    if len(raw) > 1024 * 1024:
        raise ValueError("stack-reference-result-size")
    names = [name.decode() for name in re.findall(rb"^test ([a-zA-Z0-9_:]+) \.\.\. ok$", raw, re.M)]
    summary = re.findall(rb"^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out;", raw, re.M)
    if len(names) != len(cases) or set(names) != cases or summary != [(str(len(cases)).encode(), b"0", b"0", b"0", b"0")]:
        raise ValueError("stack-reference-missing-case")
    return sorted(names)


def measurements(raw: bytes, *, old: bool) -> list[dict]:
    prefix = b"STACK_MAPPING_REFUSED" if old else b"STACK_MAPPING"
    rows = re.findall(rb"^" + prefix + rb" usable=(\d+) guard=(\d+) envelope=(\d+)$", raw, re.M)
    if len(rows) != (2 if old else 4):
        raise ValueError("stack-reference-mapping-count")
    result = []
    for values in rows:
        usable, guard, envelope = map(int, values)
        if not (0 < guard <= GUARD and envelope == STACK + GUARD):
            raise ValueError("stack-reference-guard")
        if old:
            if not AMBIENT <= usable + guard <= AMBIENT + GUARD:
                raise ValueError("stack-reference-original-ambient")
        elif not 0 < usable <= STACK or usable + guard > envelope:
            raise ValueError("stack-reference-new-envelope")
        result.append({"usableBytes": usable, "guardBytes": guard, "reservedEnvelopeBytes": envelope})
    return result


def qualify(root: Path, output: Path, revision: str) -> dict:
    environment = {**os.environ, "RUST_MIN_STACK": str(AMBIENT), "CARGO_BUILD_JOBS": "2", "CARGO_INCREMENTAL": "0"}
    artifacts.require_source(root, revision, environment)
    before = {name: hashlib.sha256(read(root, name)).hexdigest() for name in INPUTS}
    lock, source, tests = locked(root), read(root, PROFILE), read(root, TESTS)
    old = original_semantics(source)
    if sys.platform != "linux" or platform.machine() != "x86_64":
        raise ValueError("stack-reference-platform")
    kernel = platform.release()
    if not re.fullmatch(r"[A-Za-z0-9_.+-]{1,128}", kernel):
        raise ValueError("stack-reference-kernel-label")
    output = fresh(output)
    target = output / "target"
    environment["CARGO_TARGET_DIR"] = str(target)

    def command(args: list[str], label: str, timeout: int, maximum: int):
        try:
            result = run_owned(args, cwd=root, env=environment, timeout=timeout, maximum=maximum, separate_stderr=True)
        except ProcessFailure as error:
            result = error.result
            if result is not None:
                (output / (label + ".stdout.log")).write_bytes(result.output)
                (output / (label + ".stderr.log")).write_text(redact(result.stderr.decode("utf-8", "replace")))
            raise
        (output / (label + ".stdout.log")).write_bytes(result.output)
        (output / (label + ".stderr.log")).write_text(redact(result.stderr.decode("utf-8", "replace")))
        return result

    compiler = command(["rustc", "--version"], "compiler", 30, 4096).output.decode().strip()
    if not compiler.startswith("rustc 1.97.1 "):
        raise ValueError("stack-reference-compiler")
    executables, copied = {}, {}
    descriptor = artifacts.Suite("Cargo.toml", "node_worker_stack_reference", "src/lib.rs", "", CASES, False)
    for label, selected in (("old", old), ("new", source)):
        project = output / label
        (project / "src/worker_stacks").mkdir(parents=True)
        (project / "Cargo.toml").write_bytes(MANIFEST)
        (project / "Cargo.lock").write_bytes(lock)
        (project / "src/lib.rs").write_bytes(b"#![forbid(unsafe_code)]\nmod worker_stacks;\n")
        (project / "src/worker_stacks.rs").write_bytes(selected)
        (project / "src/worker_stacks/tests.rs").write_bytes(tests)
        copied[label] = {name: hashlib.sha256(read(project, name)).hexdigest()
                         for name in ("Cargo.toml", "Cargo.lock", "src/lib.rs",
                                      "src/worker_stacks.rs", "src/worker_stacks/tests.rs")}
        result = command(["cargo", "test", "--manifest-path", str(project / "Cargo.toml"), "--locked", "--lib", "--no-run", "--message-format=json"], label + "-build", 600, 8 * 1024 * 1024)
        if result.returncode != 0:
            raise ValueError("stack-reference-build:" + label)
        executable = artifacts.read_inventory(output / (label + "-build.stdout.log"), project, descriptor, target=target)
        if (project / "Cargo.lock").read_bytes() != lock:
            raise ValueError("stack-reference-lock-changed")
        executables[label] = executable.executable
    old_run = command([str(executables["old"]), ACTUAL, "--exact", "--show-output", "--test-threads=1"], "old-run", 30, 1024 * 1024)
    if old_run.returncode != 101 or b"1 failed" not in old_run.output:
        raise ValueError("stack-reference-original-not-red")
    old_mappings = measurements(old_run.output, old=True)
    listed = command([str(executables["new"]), "--list"], "new-list", 30, 65536)
    ignored = command([str(executables["new"]), "--ignored", "--list"], "new-ignored", 30, 65536)
    if listed.returncode or ignored.returncode or discovery.listing(listed.output) != CASES or discovery.listing(ignored.output):
        raise ValueError("stack-reference-case-inventory")
    new_run = command([str(executables["new"]), "--show-output", "--test-threads=1"], "new-run", 30, 1024 * 1024)
    if new_run.returncode != 0:
        raise ValueError("stack-reference-new-failed")
    cases = evidence(new_run.output, set(CASES))
    observed = measurements(new_run.output, old=False)
    for label, identities in copied.items():
        if identities != {name: hashlib.sha256(read(output / label, name)).hexdigest() for name in identities}:
            raise ValueError("stack-reference-copied-source-changed")
    after = {name: hashlib.sha256(read(root, name)).hexdigest() for name in INPUTS}
    if before != after:
        raise ValueError("stack-reference-source-changed")
    receipt = {"schemaVersion": "lsf.node-worker-stack-reference.v1", "sourceRevision": revision,
               "compiler": compiler, "kernelRelease": kernel,
               "sourceBefore": before, "sourceAfter": after,
               "copiedInputsBeforeAfter": copied,
               "referenceLockSha256": hashlib.sha256(lock).hexdigest(), "registryPackages": 16,
               "ambientMinimumStackBytes": AMBIENT, "oldSemanticDerivation": "remove-only-explicit-thread-stack-size",
               "oldExitCode": old_run.returncode, "oldMappings": old_mappings,
               "newExitCode": new_run.returncode, "newMappings": observed, "cases": cases, "ignored": [],
               "testExecutableSha256": {label: digest(binary, 256 * 1024 * 1024) for label, binary in executables.items()},
               "fullNodeQualified": False, "fullTlsAccountingQualified": False, "kernelAccountingQualified": False}
    (output / "receipt.json").write_bytes((json.dumps(receipt, indent=2) + "\n").encode())
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit", default=os.environ.get("GITHUB_SHA"))
    args = parser.parse_args()
    qualify(ROOT, args.output, args.source_commit)
    print("Exact node worker builder: old ambient-stack RED; five bounded reference cases PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
