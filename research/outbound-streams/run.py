#!/usr/bin/env python3
"""Run the opt-in #696 experiment and retain source-bound, profile-specific evidence."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
BASELINE = "a7b5d2088471b7368cd85ab74f3292afcdfca00e"
MAX_RECEIPT = 2 * 1024 * 1024
COMMANDS = ["go-version", "go-root", "format", "vet", "go-tests", "python-tests"]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_manifest(native_only: bool = False, root: Path = REPO) -> dict[str, str]:
    here = root / "research/outbound-streams"
    suffixes = {".go", ".py"} if native_only else {".go", ".py", ".json", ".wit", ".md"}
    paths = sorted(p for p in here.iterdir() if p.suffix in suffixes)
    paths += [here / "evidence/deepening-negative.json"]
    if not native_only:
        paths += [root / "adr/0059-defer-general-outbound-streams.md", here / "evidence/development-negative.json"]
    for path in paths:
        if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
            raise ValueError("source escapes checkout")
    return {str(p.relative_to(root)): digest(p) for p in paths}


def verify_sources(receipt: dict, root: Path) -> None:
    """Byte-identity primitive; verify_receipt additionally checks completeness."""
    if receipt.get("status") != "passed" or not receipt.get("sources"):
        raise ValueError("receipt is not a completed passing run")
    for relative, expected in receipt["sources"].items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file() or digest(path) != expected:
            raise ValueError(f"source identity mismatch: {relative}")
    if not receipt.get("commands") or any(type(c.get("exitCode")) is not int or c["exitCode"] != 0 for c in receipt["commands"]):
        raise ValueError("missing or failed command evidence")


def expected_tests(root: Path) -> set[str]:
    here = root / "research/outbound-streams"
    return {name for path in here.glob("*_test.go") for name in re.findall(r"func (Test\w+)\(", path.read_text())}


def verify_receipt(receipt: dict, root: Path = REPO) -> None:
    if receipt.get("formatVersion") != 2 or receipt.get("profile") not in {"native", "full"}:
        raise ValueError("unsupported receipt profile; historical v1 requires its original source")
    native = receipt["profile"] == "native"
    # A valid hash for a caller-selected subset cannot authenticate the complete
    # experiment. Recompute the exact input set, including newly added sources.
    if receipt.get("sources") != source_manifest(native, root):
        raise ValueError("source set or identity mismatch")
    verify_sources(receipt, root)
    if [c.get("id") for c in receipt["commands"]] != COMMANDS:
        raise ValueError("missing, duplicated or reordered command evidence")
    if receipt["commands"][4].get("argv", [])[1:] != ["test", "-race", "-count=1", "-timeout=30s", "-json", "."]:
        raise ValueError("test command profile mismatch")
    results = receipt.get("testResults", [])
    names = [t.get("name", "") for t in results]
    expected = expected_tests(root)
    if not expected or len(names) != len(set(names)) or any(t.get("result") != "pass" for t in results):
        raise ValueError("duplicate, skipped or failed cases")
    if {n for n in names if "/" not in n} != expected or any(n.split("/")[0] not in expected for n in names):
        raise ValueError("missing or unexpected test coverage")
    if receipt.get("topLevelGoTests") != len(expected) or receipt.get("goCasesIncludingSubtests") != len(results):
        raise ValueError("case count mismatch")
    modules = ["test_evidence"] if native else ["test_contract", "test_evidence"]
    here = root / "research/outbound-streams"
    count = sum(len(re.findall(r"^    def test_\w+\(", (here / (m + ".py")).read_text(), re.M)) for m in modules)
    if receipt.get("pythonContractTests") != count:
        raise ValueError("Python coverage mismatch")


def write_receipt(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def unique_json(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate receipt key")
        result[key] = value
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=REPO / "target/outbound-streams/receipt.json")
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--native-only", action="store_true", help="Run Go and evidence checks; do not claim schema/WIT/broker execution")
    args = parser.parse_args()
    if args.verify:
        try:
            with args.verify.open("rb") as source:
                raw = source.read(MAX_RECEIPT + 1)
            if len(raw) > MAX_RECEIPT:
                raise ValueError("receipt size limit")
            verify_receipt(json.loads(raw, object_pairs_hook=unique_json))
        except (OSError, ValueError, KeyError, TypeError) as error:
            print(f"evidence verification failed: {error}", file=sys.stderr)
            return 1
        print("complete source/case profile verified (not a signature or execution attestation)")
        return 0
    if args.output.parent.resolve() == HERE.resolve():
        parser.error("write receipts under evidence/ or target/, not among hashed inputs")
    started = time.monotonic()
    report = {
        "formatVersion": 2, "status": "running", "baselineCommit": BASELINE,
        "profile": "native" if args.native_only else "full",
        "observedAt": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(), "machine": platform.machine(),
        "pythonVersion": platform.python_version(), "commands": [], "testResults": [], "measurements": [],
        "sources": source_manifest(args.native_only),
        "notRun": [
            "Rust broker gateway regression (run through the registered latent-http CI suite separately)",
            "Real Wasmtime guest/component execution in any of the six languages",
            "Candidate WIT parser, binding generation and WASI composition",
            "Production DNS rebinding, credentials, durable audit and descendant budget conformance",
            "Allocator/kernel/TLS hostile-peer qualification and complete repository CI",
        ],
        "boundary": "Native local SMTP proof and ownership model only; no production enablement",
    }
    if args.native_only:
        report["notRun"].append("Five research JSON-schema/acceptance-map contract tests (native-only profile)")
    write_receipt(args.output, report)
    env = dict(os.environ, GO111MODULE="off", GOWORK="off", GOTOOLCHAIN="local", GOPROXY="off", GOSUMDB="off")

    def command(identity: str, argv: list[str]) -> str:
        remaining = max(1, min(120, 180 - (time.monotonic() - started)))
        begin = time.monotonic()
        try:
            result = subprocess.run(argv, cwd=HERE, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, timeout=remaining, check=False)
            code, output = result.returncode, result.stdout
        except subprocess.TimeoutExpired as error:
            code = 124
            raw = error.stdout or b""
            output = raw.decode(errors="replace") if isinstance(raw, bytes) else raw
            output += "\nexplicit experiment timeout\n"
        report["commands"].append({"id": identity, "argv": argv, "exitCode": code,
                                   "elapsedSeconds": round(time.monotonic() - begin, 6),
                                   "outputSha256": hashlib.sha256(output.encode()).hexdigest(),
                                   "output": output.replace(str(REPO), "<checkout>")[-(131072 if code else 512):]})
        write_receipt(args.output, report)
        if code:
            raise RuntimeError(f"command failed ({code}): {' '.join(argv)}")
        return output

    try:
        go, gofmt = shutil.which("go"), shutil.which("gofmt")
        if not go or not gofmt:
            raise RuntimeError("missing installed Go/gofmt; no automatic installation")
        report["goVersion"] = command("go-version", [go, "version"]).strip()
        report["goBinarySha256"] = digest(Path(go))
        report["jsonschemaVersion"] = importlib.metadata.version("jsonschema")
        goroot = Path(command("go-root", [go, "env", "GOROOT"]).strip())
        report["librarySources"] = {}
        for directory in ("net/smtp", "net/textproto", "crypto/tls"):
            files = {str(p.relative_to(goroot)): digest(p) for p in sorted((goroot / "src" / directory).glob("*.go"))
                     if not p.name.endswith("_test.go")}
            if not files:
                raise RuntimeError("missing standard-library source: " + directory)
            report["librarySources"][directory] = {"fileCount": len(files), "manifestSha256": hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()}
        changed = command("format", [gofmt, "-l", *sorted(p.name for p in HERE.glob("*.go"))]).strip()
        if changed:
            raise RuntimeError("gofmt mismatch: " + changed)
        command("vet", [go, "vet", "."])
        output = command("go-tests", [go, "test", "-race", "-count=1", "-timeout=30s", "-json", "."])
        for line in output.splitlines():
            event = json.loads(line)
            if event.get("Test") and event.get("Action") in {"pass", "fail", "skip"}:
                report["testResults"].append({"name": event["Test"], "result": event["Action"], "elapsedSeconds": event.get("Elapsed", 0)})
            if "MEASUREMENT " in event.get("Output", ""):
                report["measurements"].append(event["Output"].strip().split("MEASUREMENT ", 1)[1])
        report["topLevelGoTests"] = len(expected_tests(REPO))
        report["goCasesIncludingSubtests"] = len(report["testResults"])
        modules = ["test_evidence"] if args.native_only else ["test_contract", "test_evidence"]
        output = command("python-tests", [sys.executable, "-m", "unittest", "-v", *modules])
        count = re.search(r"Ran (\d+) tests?", output)
        if not count:
            raise RuntimeError("missing Python test count")
        report["pythonContractTests"] = int(count[1])
        report["status"] = "passed"
        verify_receipt(report)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, importlib.metadata.PackageNotFoundError) as error:
        report["status"] = "failed"
        report["error"] = str(error)
    report["elapsedSeconds"] = round(time.monotonic() - started, 6)
    write_receipt(args.output, report)
    print(f"{report['status']}: {args.output}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
