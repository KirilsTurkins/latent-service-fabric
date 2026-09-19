"""Fresh RustSec and OSV observations, never an empty-on-error advisory result."""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
from pathlib import Path
import re
import time
import tomllib
import urllib.request

from tools.security_common import decode_json, digest, read_file, require, run
from tools.security_findings import Finding, finding
from tools.security_install import verify_tool
from tools.security_inventory import Package, inventory

RUSTSEC_URL = "https://github.com/RustSec/advisory-db.git"
OSV_URL = "https://api.osv.dev/v1/querybatch"
MAX_DATABASE_AGE_SECONDS = 14 * 24 * 60 * 60


def validate_database_identity(local: str, remote: str, timestamp: int, now: int) -> None:
    require(re.fullmatch(r"[0-9a-f]{40}", local) is not None, "invalid-database-identity")
    require(local == remote, "stale-database-head")
    require(-300 <= now - timestamp <= MAX_DATABASE_AGE_SECONDS, "stale-or-future-database")


def fetch_rustsec(scratch: Path) -> tuple[Path, dict]:
    database = scratch / "rustsec-advisory-db"
    run(["git", "-c", "credential.helper=", "clone", "--quiet", "--depth", "1", "--single-branch",
         "--branch", "main", RUSTSEC_URL, str(database)], scratch, timeout=90)
    _, output = run(["git", "-C", str(database), "show", "-s", "--format=%H%n%ct", "HEAD"], scratch, timeout=15)
    identity, timestamp = output.decode().strip().splitlines()
    _, advertised = run(["git", "-c", "credential.helper=", "ls-remote", RUSTSEC_URL,
                         "refs/heads/main"], scratch, timeout=30)
    remote, branch = advertised.decode().strip().split("\t")
    require(branch == "refs/heads/main", "missing-database-branch")
    now = datetime.now(timezone.utc)
    validate_database_identity(identity, remote, int(timestamp), int(now.timestamp()))
    require((database / "crates").is_dir(), "missing-advisory-data")
    return database, {"url": RUSTSEC_URL, "commit": identity, "commit_timestamp": int(timestamp),
                      "verified_at": now.isoformat(), "max_age_seconds": MAX_DATABASE_AGE_SECONDS}


def audit_lock(payload: bytes, path: str, binary: Path, database: Path, identity: dict,
               scratch: Path) -> tuple[list[Finding], dict]:
    lock = tomllib.loads(payload.decode())
    require(bool(lock.get("package")), "empty-cargo-lock")
    lockfile = scratch / "scan.Cargo.lock"
    lockfile.write_bytes(payload)
    status, output = run([str(binary), "audit", "--db", str(database), "--no-fetch", "--no-yanked",
                          "--deny", "warnings", "--file", str(lockfile), "--json"], scratch,
                         timeout=180, accepted=(0, 1))
    report = decode_json(output)
    require(isinstance(report, dict), "invalid-rustsec-report")
    require(report["database"]["last-commit"] in {None, identity["commit"]}, "rustsec-report-database-mismatch")
    _, observed = run(["git", "-C", str(database), "rev-parse", "HEAD"], scratch, timeout=15)
    require(observed.decode().strip() == identity["commit"], "rustsec-database-changed-during-scan")
    _, modified = run(["git", "-C", str(database), "status", "--porcelain"], scratch, timeout=15)
    require(not modified.strip(), "rustsec-database-dirty")
    require(report["database"]["advisory-count"] > 0, "empty-advisory-database")
    vulnerabilities = report["vulnerabilities"]
    entries = vulnerabilities["list"]
    require(vulnerabilities["count"] == len(entries) and vulnerabilities["found"] == bool(entries),
            "inconsistent-rustsec-report")
    for warnings in report["warnings"].values():
        require(isinstance(warnings, list), "invalid-rustsec-warning")
        entries.extend(warnings)
    findings = [finding("rustsec", entry["advisory"]["id"], path,
                        f"{entry['package']['name']}@{entry['package']['version']}") for entry in entries]
    require(status == int(bool(findings)), "rustsec-exit-report-mismatch")
    return findings, {"database": identity, "lock_sha256": digest(payload),
                      "packages": len(lock["package"]), "advisories": report["database"]["advisory-count"]}


def rustsec(repo: Path, scratch: Path, tools: Path) -> tuple[list[Finding], dict]:
    payload = read_file(repo, "Cargo.lock")
    binary = verify_tool("cargo-audit", tools)
    database, identity = fetch_rustsec(scratch)
    return audit_lock(payload, "Cargo.lock", binary, database, identity, scratch)


def osv_transport(payload: bytes) -> tuple[bytes, str]:
    request = urllib.request.Request(OSV_URL, data=payload, headers={
        "Content-Type": "application/json", "User-Agent": "lsf-security-baseline/1",
    }, method="POST")
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=20) as response:
        require(response.status == 200 and response.url == OSV_URL, "osv-unavailable")
        content = bytearray()
        while chunk := response.read1(65536):
            content.extend(chunk)
            require(len(content) <= 8 * 1024 * 1024, "osv-response-size-limit")
            require(time.monotonic() - started <= 30, "osv-response-deadline")
        return bytes(content), response.headers.get("Date", "")


def query_osv(packages: list[Package], transport=osv_transport) -> tuple[list[Finding], list[dict]]:
    require(0 < len(packages) <= 5000, "invalid-osv-package-count")
    findings, receipts = [], []
    started = time.monotonic()
    for offset in range(0, len(packages), 100):
        require(time.monotonic() - started <= 240, "osv-deadline")
        batch = packages[offset:offset + 100]
        request = json.dumps({"queries": [{"package": {"ecosystem": package.ecosystem, "name": package.name},
                                          "version": package.version} for package in batch]}, separators=(",", ":")).encode()
        response, header_date = transport(request)
        now = datetime.now(timezone.utc)
        observed = parsedate_to_datetime(header_date)
        require(observed.tzinfo is not None and abs((now - observed).total_seconds()) <= 3600,
                "stale-osv-response")
        document = decode_json(response)
        require(isinstance(document, dict) and isinstance(document.get("results"), list), "invalid-osv-result")
        require(len(document["results"]) == len(batch), "incomplete-osv-result")
        for package, result in zip(batch, document["results"], strict=True):
            require(isinstance(result, dict) and not result.get("next_page_token"), "incomplete-osv-page")
            require(set(result) <= {"vulns", "next_page_token"}, "unknown-osv-result-field")
            vulnerabilities = result.get("vulns", [])
            require(isinstance(vulnerabilities, list), "invalid-osv-findings")
            for vulnerability in vulnerabilities:
                require(isinstance(vulnerability, dict) and "modified" in vulnerability, "invalid-osv-advisory")
                findings.append(finding("osv", vulnerability["id"], package.path,
                                        f"{package.ecosystem}:{package.name}@{package.version}"))
        receipts.append({"url": OSV_URL, "http_date": header_date, "observed_at": now.isoformat(),
                         "request_sha256": digest(request), "response_sha256": digest(response), "packages": len(batch)})
    return findings, receipts


def dependencies(repo: Path) -> tuple[list[Finding], dict]:
    packages, records = inventory(repo)
    findings, observations = query_osv(packages)
    return findings, {"manifests": records, "packages": len(packages), "osv_observations": observations}
