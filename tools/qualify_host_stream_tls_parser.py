"""Measure an authenticated private rustls parser; grant no TLS installation."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import host_stream_tls_patch as captured
from tools.rust_capsule_project import fresh, read_file

CASES = {
    "allowed-tls13-eight-small-certificates": True,
    "allowed-tls12-eight-small-certificates": True,
    "allowed-tls12-sixteen-authorities": True,
    "huge-declared-truncated-handshake": False,
    "tls13-nine-certificates": False,
    "tls12-seventeen-authorities": False,
    "tls13-owned-extension-over4096": False,
    "tls13-five-thousand-tiny-certificates": False,
}
OLD_CASE = "tls13-five-thousand-tiny-certificates-old"
PARSER_CEILING = 64 * 1024


def observations(raw: bytes, *, original: bool) -> list[dict]:
    if len(raw) > 65536:
        raise ValueError("tls-parser-reference-output-bound")
    rows = [json.loads(line) for line in raw.splitlines()]
    expected = {OLD_CASE: True} if original else CASES
    if len(rows) != len(expected) or {row.get("case") for row in rows} != set(expected):
        raise ValueError("tls-parser-reference-case-set")
    fields = {"case", "inputBytes", "accepted", "expectedAccepted", "peakAllocationBytes",
              "cumulativeAllocationBytes", "liveAfterDropBytes"}
    for row in rows:
        if (set(row) != fields or type(row["accepted"]) is not bool
                or row["accepted"] is not expected[row["case"]]
                or row["expectedAccepted"] is not expected[row["case"]]
                or any(type(row[key]) is not int or not 0 <= row[key] <= 16 * 1024 * 1024
                       for key in fields - {"case", "accepted", "expectedAccepted"})
                or row["liveAfterDropBytes"] != 0
                or row["cumulativeAllocationBytes"] < row["peakAllocationBytes"]
                or (row["peakAllocationBytes"] <= PARSER_CEILING) is original):
            raise ValueError("tls-parser-reference-allocation-witness")
    return rows


def qualify(archive: Path, output: Path, cargo: Path, rustc: Path) -> dict:
    output = fresh(output)
    compiler = subprocess.run([str(rustc), "--version"], capture_output=True, check=True,
                              timeout=30).stdout.decode().strip()
    if not compiler.startswith("rustc 1.97.1 "):
        raise ValueError("tls-parser-reference-compiler-pin")
    provenance = captured.apply(archive, output / "bounded-rustls")
    original = output / "original-rustls"
    shutil.copytree(output / "bounded-rustls", original)
    with tarfile.open(archive, "r:gz") as source:
        for row in provenance["patch"]["files"]:
            data = source.extractfile("rustls-0.23.45/" + row["path"]).read()
            if hashlib.sha256(data).hexdigest() != row["beforeSha256"]:
                raise ValueError("tls-parser-reference-original-preimage")
            (original / row["path"]).write_bytes(data)
    reference = read_file(captured.PATCH_ROOT / "allocation-reference.rs", 65536)
    packets = {}
    for mode, dependency in (("old", "original-rustls"), ("new", "bounded-rustls")):
        project = output / mode
        (project / "src").mkdir(parents=True)
        (project / "src/main.rs").write_bytes(reference)
        (project / "Cargo.toml").write_text(
            '[package]\nname="tls-parser-reference"\nversion="0.0.0"\nedition="2024"\n'
            f'[dependencies]\nrustls={{path="../{dependency}",default-features=false,features=["ring","std","tls12"]}}\n',
            encoding="utf-8")
        environment = {**os.environ, "CARGO_TARGET_DIR": str(output / (mode + "-target")),
                       "CARGO_BUILD_JOBS": "2", "CARGO_PROFILE_DEV_DEBUG": "0",
                       "CARGO_INCREMENTAL": "0"}
        with (output / (mode + "-build.log")).open("wb") as log:
            subprocess.run([str(cargo), "generate-lockfile", "--offline"], cwd=project,
                           env=environment, stdout=log, stderr=log, check=True, timeout=120)
            subprocess.run([str(cargo), "build", "--offline", "--locked"], cwd=project,
                           env=environment, stdout=log, stderr=log, check=True, timeout=600)
        binary = output / (mode + "-target/debug/tls-parser-reference")
        run = subprocess.run([str(binary), mode], capture_output=True, timeout=30)
        (output / (mode + "-stdout.jsonl")).write_bytes(run.stdout)
        (output / (mode + "-stderr.log")).write_bytes(run.stderr)
        if (run.returncode != 0) is not (mode == "old"):
            raise ValueError("tls-parser-reference-process-outcome")
        packets[mode] = {"binarySha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                         "lockSha256": hashlib.sha256((project / "Cargo.lock").read_bytes()).hexdigest(),
                         "exitCode": run.returncode,
                         "observations": observations(run.stdout, original=mode == "old")}
    result = {"schemaVersion": "lsf.host-tls-parser-reference.v1", "compiler": compiler,
              "upstream": provenance["patch"]["upstream"], "files": provenance["patch"]["files"],
              "patchSha256": provenance["patch"]["patchSha256"],
              "referenceSha256": hashlib.sha256(reference).hexdigest(),
              "parserCeilingBytes": PARSER_CEILING, "executions": packets,
              "parserReferenceExecuted": True, "accountingQualified": False,
              "hostTlsInstalled": False, "sharedRegistryModified": False}
    (output / "receipt.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cargo", required=True, type=Path)
    parser.add_argument("--rustc", required=True, type=Path)
    arguments = parser.parse_args()
    result = qualify(arguments.archive, arguments.output, arguments.cargo, arguments.rustc)
    print(json.dumps({"parserReferenceExecuted": result["parserReferenceExecuted"],
                      "accountingQualified": False, "hostTlsInstalled": False}))


if __name__ == "__main__":
    main()
