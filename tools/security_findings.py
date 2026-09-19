"""Exact, expiring finding exceptions; no scanner-native blanket ignores."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re

from tools.security_common import POLICY, decode_json, digest, read_file, relative_path, require


@dataclass(frozen=True, order=True)
class Finding:
    scanner: str
    finding: str
    path: str
    package: str
    fingerprint: str
    line: int = 0
    column: int = 0

    def public(self) -> dict:
        return asdict(self)


def finding(scanner: str, identifier: str, path: str, package: str = "",
            line: int = 0, column: int = 0, content: bytes = b"") -> Finding:
    relative_path(path)
    require(re.fullmatch(r"[A-Za-z0-9_.:/-]{1,160}", identifier) is not None, "invalid-finding-id")
    require(isinstance(package, str) and len(package) <= 256 and "\n" not in package, "invalid-finding-package")
    require(type(line) is int and 0 <= line <= 1000000, "invalid-finding-line")
    require(type(column) is int and 0 <= column <= 16777216, "invalid-finding-column")
    identity = [scanner, identifier, path, package, line, column, digest(content.replace(b"\r\n", b"\n"))]
    fingerprint = digest(json.dumps(identity, separators=(",", ":"), ensure_ascii=True).encode())
    return Finding(scanner, identifier, path, package, fingerprint, line, column)


def load_exceptions(policy: Path = POLICY, today: date | None = None) -> list[dict]:
    today = today or datetime.now(timezone.utc).date()
    document = decode_json(read_file(policy, "exceptions.json"))
    require(isinstance(document, dict) and set(document) == {"schema", "exceptions"}
            and document["schema"] == 1, "invalid-exception-document")
    exceptions = document["exceptions"]
    require(isinstance(exceptions, list) and len(exceptions) <= 128, "exception-count-limit")
    seen = set()
    required = {"scanner", "finding", "path", "package", "fingerprint", "owner", "rationale",
                "created", "expires", "review"}
    for entry in exceptions:
        require(isinstance(entry, dict) and set(entry) == required, "invalid-exception-fields")
        require(all(isinstance(value, str) for value in entry.values()), "invalid-exception-value")
        require(entry["scanner"] in {"rustsec", "osv", "gitleaks", "source", "zizmor"}, "invalid-exception-scanner")
        relative_path(entry["path"])
        require(not any(char in entry["path"] + entry["finding"] + entry["package"] for char in "*?[]"),
                "wildcard-exception")
        require(re.fullmatch(r"[A-Za-z0-9_.:/-]{1,160}", entry["finding"]) is not None, "invalid-exception-id")
        require(re.fullmatch(r"[0-9a-f]{64}", entry["fingerprint"]) is not None, "invalid-exception-fingerprint")
        require(re.fullmatch(r"@[A-Za-z0-9-]{1,39}", entry["owner"]) is not None, "invalid-exception-owner")
        require(40 <= len(entry["rationale"]) <= 1500, "missing-reachability-rationale")
        require(re.fullmatch(r"https://github.com/KirilsTurkins/latent-service-fabric/(issues|pull)/[0-9]+",
                             entry["review"]) is not None, "missing-exception-review")
        created, expires = date.fromisoformat(entry["created"]), date.fromisoformat(entry["expires"])
        require(created <= today < expires, "expired-or-future-exception")
        require(0 < (expires - created).days <= 30, "exception-expiry-limit")
        if entry["scanner"] in {"rustsec", "osv"}:
            require("@" in entry["package"] and bool(entry["package"].rsplit("@", 1)[1]), "missing-exact-package-version")
        identity = tuple(entry[key] for key in ("scanner", "finding", "path", "package", "fingerprint"))
        require(identity not in seen, "duplicate-exception")
        seen.add(identity)
    return exceptions


def apply_exceptions(findings: list[Finding], exceptions: list[dict]) -> tuple[list[Finding], list[Finding]]:
    fields = ("scanner", "finding", "path", "package", "fingerprint")
    accepted = {tuple(entry[field] for field in fields) for entry in exceptions}
    remaining, waived = [], []
    for item in sorted(set(findings)):
        identity = tuple(getattr(item, field) for field in fields)
        (waived if identity in accepted else remaining).append(item)
    return remaining, waived
