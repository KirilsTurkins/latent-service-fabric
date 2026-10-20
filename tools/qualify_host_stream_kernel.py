"""Execute one real current-provider kernel-tail witness, never a retirement proof."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import qualify_host_stream_tls_provider as provider
from tools import ci_rust_artifacts as artifacts
from tools import host_stream_kernel_observer as observer
from tools import ci_suite_discovery as discovery
from tools.owned_test_process import ProcessFailure, run_owned
from tools.rust_capsule_project import fresh
from tools.test_run import redact

EXTRA = ("tools/host_stream_kernel_observer.py", "tools/qualify_host_stream_kernel.py")
STAGES = ("connected", "send-pressure", "after-fd-drop", "after-peer-drop")


def snapshot(root: Path) -> dict:
    value = provider.snapshot(root)
    value["kernelObserverInputs"] = {name: provider.digest_file(root / name, 65536) for name in EXTRA}
    return value


def outcomes(raw: bytes, total: int) -> list[dict]:
    if len(raw) > 65536 or type(total) is not int or total != 26:
        raise ValueError("kernel-reference-output-bound")
    names = re.findall(rb"^test ([a-zA-Z0-9_:]+) \.\.\. ok$", raw, re.M)
    summaries = re.findall(rb"^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out;", raw, re.M)
    if names != [provider.KERNEL_CASE.encode()] or summaries != [(b"1", b"0", b"0", b"0", b"25")]:
        raise ValueError("kernel-reference-missing-case")
    rows = [json.loads(value) for value in re.findall(rb"^KERNEL_OWNER_OBSERVATION (.+)$", raw, re.M)]
    if [r.get("stage") for r in rows] != list(STAGES):
        raise ValueError("kernel-reference-barriers")
    for row in rows:
        if set(row) != {"stage", "observation", "hostMemoryBytes", "poolConnections"}:
            raise ValueError("kernel-reference-private-or-unknown-field")
        if (type(row["hostMemoryBytes"]) is not int or not 0 <= row["hostMemoryBytes"] <= 1024 * 1024
                or type(row["poolConnections"]) is not int or row["poolConnections"] not in (0, 1)):
            raise ValueError("kernel-reference-owner-bounds")
        observer.validate_projection(row["observation"])
    if (rows[1]["hostMemoryBytes"] < 98304 or rows[1]["poolConnections"] != 1
            or rows[2]["hostMemoryBytes"] != 0 or rows[2]["poolConnections"] != 0
            or rows[2]["observation"]["matchingRows"] != 1
            or rows[2]["observation"]["state"] not in ("FIN-WAIT-1", "FIN-WAIT-2", "TIME-WAIT")):
        raise ValueError("kernel-reference-tail-witness-missing")
    return rows



def compiler_diagnostics(raw: bytes, root: Path) -> dict:
    """Keep bounded error identity/spans, never Cargo payloads or environment."""
    if len(raw) > 16 * 1024 * 1024:
        raise ValueError("kernel-reference-compiler-output-bound")
    errors = []
    for line in raw.splitlines():
        row = json.loads(line)
        if row.get("reason") != "compiler-message":
            continue
        message = row["message"]
        if message.get("level") != "error":
            continue
        if len(errors) >= 16:
            raise ValueError("kernel-reference-compiler-error-count")
        spans = []
        for span in message.get("spans", []):
            if not span.get("is_primary"):
                continue
            name = Path(span["file_name"])
            if name.is_absolute():
                name = name.relative_to(root)
            if name.is_absolute() or ".." in name.parts or len(name.as_posix()) > 256:
                raise ValueError("kernel-reference-compiler-source-path")
            if len(spans) >= 8:
                raise ValueError("kernel-reference-compiler-span-count")
            spans.append({"file": name.as_posix(), "line": span["line_start"], "column": span["column_start"]})
        code = message.get("code")
        code = code.get("code") if isinstance(code, dict) else None
        if code is not None and not re.fullmatch(r"E[0-9]{4}", code):
            raise ValueError("kernel-reference-compiler-error-code")
        text = redact(message["message"])
        if len(text) > 2048:
            raise ValueError("kernel-reference-compiler-message-bound")
        errors.append({"code": code, "message": text, "spans": spans})
    result = {"schemaVersion": "lsf.kernel-reference-compiler-diagnostics.v1", "errors": errors}
    if len(json.dumps(result).encode()) > 65536:
        raise ValueError("kernel-reference-compiler-diagnostics-bound")
    return result


def qualify(root: Path, output: Path, revision: str) -> dict:
    environment = {**os.environ, "CARGO_BUILD_JOBS": "2", "CARGO_INCREMENTAL": "0", "CARGO_TARGET_DIR": str(root / "target")}
    artifacts.require_source(root, revision, environment)
    if sys.platform != "linux" or platform.machine() != "x86_64":
        raise ValueError("kernel-reference-linux-required")
    kernel = platform.release()
    if not re.fullmatch(r"[A-Za-z0-9_.+-]{1,128}", kernel):
        raise ValueError("kernel-reference-release-label")
    before = snapshot(root)
    suite = provider.suite_contract(root)
    output = fresh(output)

    def command(args: list[str], name: str, timeout: int, maximum: int):
        try:
            result = run_owned(args, cwd=root, env=environment, timeout=timeout, maximum=maximum, separate_stderr=True)
        except ProcessFailure as error:
            result = error.result
            if result is not None:
                (output / (name + ".stdout.log")).write_bytes(result.output)
                (output / (name + ".stderr.log")).write_text(redact(result.stderr.decode("utf-8", "replace")))
            raise
        (output / (name + ".stdout.log")).write_bytes(result.output)
        (output / (name + ".stderr.log")).write_text(redact(result.stderr.decode("utf-8", "replace")))
        if name == "cargo":
            diagnostics = compiler_diagnostics(result.output, root)
            (output / "cargo-diagnostics.json").write_bytes((json.dumps(diagnostics, indent=2) + "\n").encode())
        if result.returncode:
            raise ValueError("kernel-reference-command-failed:" + name)
        return result.output

    compiler = command(["rustc", "--version"], "compiler", 30, 4096).decode().strip()
    if not compiler.startswith("rustc 1.97.1 "):
        raise ValueError("kernel-reference-compiler")
    command(["cargo", "test", "--locked", "--all-features", "-p", "latent-streams", "--lib", "--no-run", "--message-format=json"], "cargo", 1200, 16 * 1024 * 1024)
    descriptor = artifacts.Suite(suite["manifest"], suite["target"], suite["source"], "", frozenset(suite["expectedCases"]), False)
    inventory = output / "cargo.stdout.log"
    executable = artifacts.read_inventory(inventory, root, descriptor, target=root / "target")
    libraries = provider.compiled_tls(root, inventory, root / "target")
    environment = artifacts.cargo_environment(root, executable, environment, target=root / "target")
    listed = command([str(executable.executable), "--list"], "list", 30, 65536)
    ignored = command([str(executable.executable), "--ignored", "--list"], "ignored", 30, 65536)
    discovery.validate_cases(suite, discovery.listing(listed), discovery.listing(ignored), {})
    raw = command([str(executable.executable), provider.KERNEL_CASE, "--exact", "--show-output", "--test-threads=1"], "tests", 30, 65536)
    rows = outcomes(raw, len(suite["expectedCases"]))
    after = snapshot(root)
    if before != after:
        raise ValueError("kernel-reference-source-changed")
    receipt = {"schemaVersion": "lsf.host-stream-kernel-tail-reference.v1", "sourceRevision": revision,
               "compiler": compiler, "kernelRelease": kernel, "sourceBefore": before, "sourceAfter": after, "compiledTls": libraries,
               "testExecutableSha256": provider.digest_file(executable.executable, 1024 * 1024 * 1024),
               "executedCases": [provider.KERNEL_CASE], "registeredCases": sorted(suite["expectedCases"]), "ignored": [],
               "barriers": rows, "oldFdRefundIsNotKernelRetirement": True,
               "kernelAccountingQualified": False, "productionInstallation": False, "fullTlsAccountingQualified": False}
    (output / "receipt.json").write_bytes((json.dumps(receipt, indent=2) + "\n").encode())
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit", default=os.environ.get("GITHUB_SHA"))
    args = parser.parse_args()
    qualify(provider.provider.ROOT, args.output, args.source_commit)
    print("Actual kernel tail after FD refund observed; kernel accounting remains unqualified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
