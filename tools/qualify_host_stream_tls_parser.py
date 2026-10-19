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
import tomllib

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
CURRENT_LOCK_SHA256 = "334b1e01f646aae3ff92b8fb039172082a08273b8d088c6d6e184fe94a34760b"


def current_reference_lock() -> bytes:
    raw = read_file(captured.CURRENT_PATCH_ROOT / "reference-Cargo.lock", 65536)
    if hashlib.sha256(raw).hexdigest() != CURRENT_LOCK_SHA256:
        raise ValueError("tls-parser-reference-lock-identity")
    packages = tomllib.loads(raw.decode("utf-8")).get("package", [])
    workspace = tomllib.loads(read_file(captured.ROOT / "Cargo.lock", 4 * 1024 * 1024).decode("utf-8"))
    if not isinstance(packages, list) or not 2 <= len(packages) <= 64:
        raise ValueError("tls-parser-reference-lock-bound")
    local = []
    for row in packages:
        if "source" not in row:
            local.append((row.get("name"), row.get("version")))
            continue
        matches = [p for p in workspace.get("package", [])
                   if all(row.get(k) == p.get(k) for k in ("name", "version", "source", "checksum"))]
        if row.get("source") != "registry+https://github.com/rust-lang/crates.io-index" or len(matches) != 1:
            raise ValueError("tls-parser-reference-current-dependency")
    if sorted(local) != [("rustls", "0.23.46"), ("tls-parser-reference", "0.0.0")]:
        raise ValueError("tls-parser-reference-local-dependency")
    return raw


def project_manifest(dependency: str, *, current: bool) -> bytes:
    if dependency not in {"original-rustls", "bounded-rustls"}:
        raise ValueError("tls-parser-reference-project")
    text = ('[package]\nname="tls-parser-reference"\nversion="0.0.0"\nedition="2024"\n'
            f'[dependencies]\nrustls={{path="../{dependency}",default-features=false,features=["ring","std","tls12"]}}\n')
    if current:
        # The probe is independent even if its output is inside a checkout.
        text += '[workspace]\nresolver="3"\n'
    return text.encode("utf-8")


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


def profile(version: str):
    if version == "0.23.45":
        return captured.PATCH_ROOT, captured.apply
    if version == "0.23.46":
        return captured.CURRENT_PATCH_ROOT, captured.apply_current
    raise ValueError("tls-parser-reference-profile")


def qualify(archive: Path, output: Path, cargo: Path, rustc: Path,
            *, parser_version: str = "0.23.45", fetch_current_dependencies: bool = False) -> dict:
    patch_root, apply = profile(parser_version)
    current = parser_version == "0.23.46"
    if fetch_current_dependencies and not current:
        raise ValueError("tls-parser-reference-fetch-current-only")
    locked = current_reference_lock() if current else None
    output = fresh(output)
    compiler = subprocess.run([str(rustc), "--version"], capture_output=True, check=True,
                              timeout=30).stdout.decode().strip()
    if not compiler.startswith("rustc 1.97.1 "):
        raise ValueError("tls-parser-reference-compiler-pin")
    provenance = apply(archive, output / "bounded-rustls")
    original = output / "original-rustls"
    shutil.copytree(output / "bounded-rustls", original)
    with tarfile.open(archive, "r:gz") as source:
        for row in provenance["patch"]["files"]:
            data = source.extractfile(f"rustls-{parser_version}/" + row["path"]).read()
            if hashlib.sha256(data).hexdigest() != row["beforeSha256"]:
                raise ValueError("tls-parser-reference-original-preimage")
            (original / row["path"]).write_bytes(data)
    reference = read_file(patch_root / "allocation-reference.rs", 65536)
    packets = {}
    for mode, dependency in (("old", "original-rustls"), ("new", "bounded-rustls")):
        project = output / mode
        (project / "src").mkdir(parents=True)
        (project / "src/main.rs").write_bytes(reference)
        (project / "Cargo.toml").write_bytes(project_manifest(dependency, current=current))
        if locked is not None:
            (project / "Cargo.lock").write_bytes(locked)
        environment = {**os.environ, "CARGO_TARGET_DIR": str(output / (mode + "-target")),
                       "CARGO_BUILD_JOBS": "2", "CARGO_PROFILE_DEV_DEBUG": "0",
                       "CARGO_INCREMENTAL": "0"}
        with (output / (mode + "-build.log")).open("wb") as log:
            if locked is None:
                subprocess.run([str(cargo), "generate-lockfile", "--offline"], cwd=project,
                               env=environment, stdout=log, stderr=log, check=True, timeout=120)
            elif mode == "old" and fetch_current_dependencies:
                subprocess.run([str(cargo), "fetch", "--locked"], cwd=project,
                               env=environment, stdout=log, stderr=log, check=True, timeout=120)
            subprocess.run([str(cargo), "build", "--offline", "--locked"], cwd=project,
                           env=environment, stdout=log, stderr=log, check=True, timeout=600)
        if locked is not None and (project / "Cargo.lock").read_bytes() != locked:
            raise ValueError("tls-parser-reference-lock-changed")
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
    if locked is not None:
        result["selectedReferenceLockSha256"] = CURRENT_LOCK_SHA256
        result["registryDependenciesMatchWorkspace"] = True
    (output / "receipt.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cargo", required=True, type=Path)
    parser.add_argument("--rustc", required=True, type=Path)
    parser.add_argument("--parser-version", choices=("0.23.45", "0.23.46"), default="0.23.45")
    parser.add_argument("--fetch-current-dependencies", action="store_true")
    arguments = parser.parse_args()
    result = qualify(arguments.archive, arguments.output, arguments.cargo, arguments.rustc,
                     parser_version=arguments.parser_version,
                     fetch_current_dependencies=arguments.fetch_current_dependencies)
    print(json.dumps({"parserReferenceExecuted": result["parserReferenceExecuted"],
                      "accountingQualified": False, "hostTlsInstalled": False}))


if __name__ == "__main__":
    main()
