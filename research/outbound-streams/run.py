#!/usr/bin/env python3
"""Run the opt-in #696 experiment and retain honest, source-bound evidence."""
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
ADR = REPO / "adr/0059-defer-general-outbound-streams.md"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_manifest() -> dict[str, str]:
    paths = sorted(p for p in HERE.iterdir() if p.suffix in {".go", ".py", ".json", ".wit", ".md"})
    paths += [ADR, HERE / "evidence/development-negative.json"]
    return {str(p.relative_to(REPO)): digest(p) for p in paths}


def verify_sources(receipt: dict, root: Path) -> None:
    if receipt.get("status") != "passed" or not receipt.get("sources"):
        raise ValueError("receipt is not a completed passing run")
    for relative, expected in receipt["sources"].items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file() or digest(path) != expected:
            raise ValueError(f"source identity mismatch: {relative}")
    if not receipt.get("commands") or any(c["exitCode"] != 0 for c in receipt["commands"]):
        raise ValueError("missing or failed command evidence")


def write_receipt(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=REPO / "target/outbound-streams/receipt.json")
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if args.verify:
        try:
            verify_sources(json.loads(args.verify.read_text()), REPO)
        except (OSError, ValueError, KeyError) as error:
            print(f"evidence verification failed: {error}", file=sys.stderr)
            return 1
        print("source-bound evidence verified (not a signature or production qualification)")
        return 0

    started = time.monotonic()
    report = {
        "formatVersion": 1, "status": "running", "baselineCommit": BASELINE,
        "observedAt": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(), "machine": platform.machine(),
        "pythonVersion": platform.python_version(), "commands": [],
        "testResults": [], "measurements": [], "sources": source_manifest(),
        "notRun": [
            "Rust production broker/admission/IoRuntime/descendant budget integration",
            "Real Wasmtime guest/component execution in any of the six languages",
            "Candidate WIT parser, binding generation and WASI composition",
            "Production DNS rebinding, credential rotation and durable audit conformance",
            "Allocator/kernel/TLS hostile-peer qualification and complete repository CI",
        ],
        "boundary": "Native local protocol proof and ownership model only; no production enablement",
    }
    write_receipt(args.output, report)
    env = dict(os.environ, GO111MODULE="off", GOWORK="off", GOTOOLCHAIN="local",
               GOPROXY="off", GOSUMDB="off")

    def command(argv: list[str]) -> str:
        remaining = max(1, min(120, 180 - (time.monotonic() - started)))
        begin = time.monotonic()
        try:
            result = subprocess.run(argv, cwd=HERE, env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, timeout=remaining,
                                    check=False)
            code, output = result.returncode, result.stdout
        except subprocess.TimeoutExpired as error:
            code = 124
            raw = error.stdout or b""
            output = raw.decode(errors="replace") if isinstance(raw, bytes) else raw
            output += "\nexplicit experiment timeout\n"
        record = {"argv": argv, "exitCode": code,
                  "elapsedSeconds": round(time.monotonic() - begin, 6),
                  "outputSha256": hashlib.sha256(output.encode()).hexdigest(),
                  "output": output.replace(str(REPO), "<checkout>")[-(131072 if code else 512):]}
        report["commands"].append(record)
        write_receipt(args.output, report)
        if code:
            raise RuntimeError(f"command failed ({code}): {' '.join(argv)}")
        return output

    try:
        go = shutil.which("go")
        gofmt = shutil.which("gofmt")
        if not go or not gofmt:
            raise RuntimeError("missing installed Go/gofmt; no automatic installation")
        report["goVersion"] = command([go, "version"]).strip()
        report["goBinarySha256"] = digest(Path(go))
        report["jsonschemaVersion"] = importlib.metadata.version("jsonschema")
        goroot = Path(command([go, "env", "GOROOT"]).strip())
        report["librarySources"] = {}
        for directory in ("net/smtp", "net/textproto", "crypto/tls"):
            files = {str(p.relative_to(goroot)): digest(p)
                     for p in sorted((goroot / "src" / directory).glob("*.go"))
                     if not p.name.endswith("_test.go")}
            if not files:
                raise RuntimeError("missing standard-library source: " + directory)
            report["librarySources"][directory] = {
                "fileCount": len(files),
                "manifestSha256": hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest(),
            }
        report["smtpSourceSha256"] = digest(goroot / "src/net/smtp/smtp.go")
        changed = command([gofmt, "-l", "gateway.go", "gateway_test.go"]).strip()
        if changed:
            raise RuntimeError("gofmt mismatch: " + changed)
        command([go, "vet", "."])
        output = command([go, "test", "-race", "-count=1", "-timeout=30s", "-json", "."])
        for line in output.splitlines():
            if not line.startswith("{"):
                continue
            event = json.loads(line)
            if event.get("Test") and event.get("Action") in {"pass", "fail", "skip"}:
                report["testResults"].append({"name": event["Test"], "result": event["Action"],
                                              "elapsedSeconds": event.get("Elapsed", 0)})
            if "MEASUREMENT " in event.get("Output", ""):
                report["measurements"].append(event["Output"].strip().split("MEASUREMENT ", 1)[1])
        expected = set(re.findall(r"func (Test\w+)\(", (HERE / "gateway_test.go").read_text()))
        actual = {t["name"] for t in report["testResults"] if t["result"] == "pass"}
        if not expected or not expected <= actual or any(t["result"] != "pass" for t in report["testResults"]):
            raise RuntimeError("missing, skipped or failed Go evidence")
        report["topLevelGoTests"] = len(expected)
        report["goCasesIncludingSubtests"] = len(report["testResults"])
        command([sys.executable, "-m", "unittest", "-v", "test_contract"])
        report["pythonContractTests"] = 5
        if source_manifest() != report["sources"]:
            raise RuntimeError("experiment sources changed during execution")
        report["status"] = "passed"
    except (OSError, RuntimeError, ValueError, importlib.metadata.PackageNotFoundError) as error:
        report["status"] = "failed"
        report["error"] = str(error)
    report["elapsedSeconds"] = round(time.monotonic() - started, 6)
    write_receipt(args.output, report)
    print(f"{report['status']}: {args.output}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
