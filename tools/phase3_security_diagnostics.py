"""Closed diagnostics for failed trusted libtest processes, never raw capture."""
from __future__ import annotations

from pathlib import Path
import re

from tools.phase3_security_artifacts import require

MAX_CAPTURE_BYTES = 1024 * 1024
MAX_ENTRIES = 8
SOURCE_FILE = re.compile(r"crates/[a-z][a-z0-9-]{0,63}/(?:src|tests)/[A-Za-z0-9_/-]{1,240}\.rs\Z")
PANIC = re.compile(r"(?m)^thread '[A-Za-z_0-9:-]{1,512}'(?: \([0-9]{1,20}\))? panicked at ([^\r\n]{1,512}\.rs):([0-9]{1,7}):([0-9]{1,5}):\r?$")
ASSERTION = re.compile(r"(?m)^assertion `left (==|!=) right` failed\r?\n +left: (-?[0-9]{1,20})\r?\n +right: (-?[0-9]{1,20})\r?$")
PLATFORM_CODES = (
    "Unavailable", "DeadlineExceeded", "Cancelled", "ResourceExhausted", "PermissionDenied",
    "Unauthenticated", "InvalidArgument", "NotFound", "AlreadyExists", "IncompatibleContract",
    "StateConflict", "DependencyFailed", "GuestTrap", "CorruptArtifact", "RouteUnavailable",
    "AdmissionRejected", "Internal",
)
# Closed public currentness reasons from latent-core, plus the injected test
# authority's fixed states. No arbitrary message or detail value is retained.
REASON_CODES = (
    "admission-authority-busy", "admission-authority-poisoned", "admission-control-busy",
    "admission-clock-lease-uncovered", "admission-clock-regression", "admission-durability-uncertain",
    "admission-owner-retired", "admission-restart-clock-floor", "admission-verification-busy",
    "signature-clock-regression", "signature-trust-conflict", "signature-stale-proof",
    "fixture-busy", "fixture-revoked", "fixture-expired", "fixture-owner",
)


def integer(value: object) -> bool:
    return type(value) is int and -(2 ** 63) <= value <= 2 ** 64 - 1


def validate(value: object) -> None:
    require(isinstance(value, dict) and set(value) == {
        "exitCode", "panicLocations", "integerAssertions", "platformCodes", "reasonCodes",
    }, "test-diagnostic-fields")
    require(type(value["exitCode"]) is int and -(2 ** 31) <= value["exitCode"] < 2 ** 32
            and value["exitCode"] != 0, "test-diagnostic-exit")
    for field in ("panicLocations", "integerAssertions", "platformCodes", "reasonCodes"):
        require(isinstance(value[field], list) and len(value[field]) <= MAX_ENTRIES,
                "test-diagnostic-count")
    for location in value["panicLocations"]:
        require(isinstance(location, dict) and set(location) == {"file", "line", "column"},
                "test-diagnostic-location")
        require(isinstance(location["file"], str) and SOURCE_FILE.fullmatch(location["file"]) is not None,
                "test-diagnostic-file")
        require(type(location["line"]) is int and 0 < location["line"] <= 1_000_000
                and type(location["column"]) is int and 0 < location["column"] <= 10_000,
                "test-diagnostic-coordinate")
    for assertion in value["integerAssertions"]:
        require(isinstance(assertion, dict) and set(assertion) == {"relation", "left", "right"}
                and assertion["relation"] in ("==", "!=")
                and integer(assertion["left"]) and integer(assertion["right"]),
                "test-diagnostic-assertion")
    for field, allowed in (("platformCodes", PLATFORM_CODES), ("reasonCodes", REASON_CODES)):
        require(all(isinstance(item, str) and item in allowed for item in value[field])
                and len(set(value[field])) == len(value[field]), "test-diagnostic-code")


def extract(result, repo: Path, cwd: Path) -> dict:
    require(len(result.stdout) + len(result.stderr) <= MAX_CAPTURE_BYTES, "test-diagnostic-capture")
    raw = (result.stdout + b"\n" + result.stderr).decode("utf-8", errors="replace")
    locations = []
    for match in PANIC.finditer(raw):
        filename, line, column = match.groups()
        # Rust reports workspace-relative or crate-relative source coordinates.
        # Absolute/private paths, traversal and non-source files are discarded.
        if filename.startswith("crates/"):
            candidate = repo / filename
        elif filename.startswith(("src/", "tests/")):
            candidate = cwd / filename
        else:
            continue
        try:
            relative = candidate.relative_to(repo).as_posix()
        except ValueError:
            continue
        if (SOURCE_FILE.fullmatch(relative) is not None and candidate.is_file()
                and not candidate.is_symlink() and 0 < int(line) <= 1_000_000
                and 0 < int(column) <= 10_000):
            location = {"file": relative, "line": int(line), "column": int(column)}
            if location not in locations:
                locations.append(location)
        if len(locations) == MAX_ENTRIES:
            break
    assertions = []
    for relation, left, right in ASSERTION.findall(raw):
        if integer(int(left)) and integer(int(right)):
            assertions.append({"relation": relation, "left": int(left), "right": int(right)})
        if len(assertions) == MAX_ENTRIES:
            break
    value = {"exitCode": result.returncode, "panicLocations": locations, "integerAssertions": assertions,
             "platformCodes": [code for code in PLATFORM_CODES
                               if re.search(r"\bcode: " + code + r"\b", raw)][:MAX_ENTRIES],
             "reasonCodes": [code for code in REASON_CODES if '"' + code + '"' in raw][:MAX_ENTRIES]}
    validate(value)
    return value
