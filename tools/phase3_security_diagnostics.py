"""Closed diagnostics for failed trusted libtest processes, never raw capture."""
from __future__ import annotations

from pathlib import Path
import re

from tools.phase3_security_artifacts import require

MAX_CAPTURE_BYTES = 1024 * 1024
MAX_ENTRIES = 8
MAX_CHILD_RECORDS = 32
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
# These are the existing test recorder's closed enum variants. An exact snapshot
# line supplies stage and incompleteness; arbitrary error text cannot supply it.
CHILD_REASONS = {
    "AdmissionAuthorityBusy": "admission-authority-busy",
    "AdmissionAuthorityPoisoned": "admission-authority-poisoned",
    "AdmissionControlBusy": "admission-control-busy",
    "AdmissionClockLeaseUncovered": "admission-clock-lease-uncovered",
    "AdmissionClockRegression": "admission-clock-regression",
    "AdmissionDurabilityUncertain": "admission-durability-uncertain",
    "AdmissionOwnerRetired": "admission-owner-retired",
    "AdmissionRestartClockFloor": "admission-restart-clock-floor",
    "AdmissionVerificationBusy": "admission-verification-busy",
    "SignatureClockRegression": "signature-clock-regression",
    "SignatureTrustConflict": "signature-trust-conflict",
    "SignatureStaleProof": "signature-stale-proof",
    "SchedulerShutdown": "scheduler-shutdown",
    "SchedulerHandoffClosed": "scheduler-handoff-closed",
    "SchedulerSequenceExhausted": "scheduler-sequence-exhausted",
    "SchedulerAllCellsQuarantined": "scheduler-all-cells-quarantined",
    "SchedulerImmediateCapacityUnavailable": "scheduler-immediate-capacity-unavailable",
    "SchedulerQueueFull": "scheduler-queue-full",
    "QuotaStateUnavailable": "quota-state-unavailable",
    "PreparationReadyCapacity": "preparation-ready-capacity",
    "PreparationReadyBytes": "preparation-ready-bytes",
    "CompilerStopping": "compiler-stopping",
    "CompilerWaiterCapacity": "compiler-waiter-capacity",
    "CompilerGenerationAbandoned": "compiler-generation-abandoned",
    "CompilerWaiterGenerationExhausted": "compiler-waiter-generation-exhausted",
    "CompilerJobCapacity": "compiler-job-capacity",
    "CompilerQueueCapacity": "compiler-queue-capacity",
    "CompilerJobGenerationExhausted": "compiler-job-generation-exhausted",
    "CompilerDocumentCapacity": "compiler-document-capacity",
    "CompilerJobNoLongerPending": "compiler-job-no-longer-pending",
    "CompilerDocumentAlreadyReserved": "compiler-document-already-reserved",
    "CompilerCreatorAbandoned": "compiler-creator-abandoned",
    "CompilerJobPanicked": "compiler-job-panicked",
    "CompilerJobAbandoned": "compiler-job-abandoned",
    "ReleaseLifecycleBusy": "release-lifecycle-busy",
    "ReleaseLifecycleUnavailable": "release-lifecycle-unavailable",
    "AdmissionRepositoryRetired": "admission-repository-retired",
    "PreparationSourceAssociation": "preparation-source-association",
    "PreparationMetadataBound": "preparation-metadata-bound",
    "PreparationMetadataOverflow": "preparation-metadata-overflow",
    "PreparationComponentBound": "preparation-component-bound",
    "PreparationCacheBound": "preparation-cache-bound",
    "PreparationDeclaredBudget": "preparation-declared-budget",
    "ReleaseLifecycleCapacity": "release-lifecycle-capacity",
    "Unclassified": "unclassified",
}
CHILD_STAGES = {"Start": "start", "InvocationError": "invocation-error", "ChildFailure": "child-failure"}
CHILD_RECORD_PATTERN = (r"FailureRecord \{ stage: (" + "|".join(CHILD_STAGES)
                        + r"), code: (" + "|".join(PLATFORM_CODES)
                        + r"), reason: (" + "|".join(CHILD_REASONS) + r") \}")
CHILD_RECORD = re.compile(CHILD_RECORD_PATTERN)
CHILD_SNAPSHOT = re.compile(
    r"(?m)^local-service-child-failures Snapshot \{ records: \[(?P<records>"
    + r"(?:" + CHILD_RECORD_PATTERN + r"(?:, " + CHILD_RECORD_PATTERN + r"){0,31})?"
    + r")\], incomplete: (?P<incomplete>true|false) \}\r?$")
ALL_REASON_CODES = tuple(dict.fromkeys((*REASON_CODES, *CHILD_REASONS.values())))


def integer(value: object) -> bool:
    return type(value) is int and -(2 ** 63) <= value <= 2 ** 64 - 1


def validate(value: object) -> None:
    required = {
        "exitCode", "panicLocations", "integerAssertions", "platformCodes", "reasonCodes",
    }
    require(isinstance(value, dict) and required <= set(value)
            and set(value) <= required | {"childFailureSnapshot"}, "test-diagnostic-fields")
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
    for field, allowed in (("platformCodes", PLATFORM_CODES), ("reasonCodes", ALL_REASON_CODES)):
        require(all(isinstance(item, str) and item in allowed for item in value[field])
                and len(set(value[field])) == len(value[field]), "test-diagnostic-code")
    if "childFailureSnapshot" in value:
        snapshot = value["childFailureSnapshot"]
        require(isinstance(snapshot, dict) and set(snapshot) == {
            "records", "incomplete", "recordedCount", "omittedCount",
        }, "test-diagnostic-child-fields")
        require(type(snapshot["incomplete"]) is bool
                and type(snapshot["recordedCount"]) is int
                and 0 <= snapshot["recordedCount"] <= MAX_CHILD_RECORDS
                and type(snapshot["omittedCount"]) is int
                and isinstance(snapshot["records"], list)
                and len(snapshot["records"]) == min(snapshot["recordedCount"], MAX_ENTRIES)
                and snapshot["omittedCount"] == snapshot["recordedCount"] - len(snapshot["records"]),
                "test-diagnostic-child-bounds")
        for record in snapshot["records"]:
            require(isinstance(record, dict) and set(record) == {"stage", "code", "reason"}
                    and record["stage"] in CHILD_STAGES.values()
                    and record["code"] in PLATFORM_CODES
                    and record["reason"] in CHILD_REASONS.values(), "test-diagnostic-child-record")


def child_failure_snapshot(raw: str) -> dict | None:
    matches = list(CHILD_SNAPSHOT.finditer(raw))
    # A failed assertion emits one snapshot. Duplicate/mixed snapshots have no
    # unambiguous association with this command's failure and remain absent.
    if len(matches) != 1:
        return None
    match = matches[0]
    records = [dict(stage=CHILD_STAGES[stage], code=code, reason=CHILD_REASONS[reason])
               for stage, code, reason in CHILD_RECORD.findall(match.group("records"))]
    if len(records) > MAX_CHILD_RECORDS:
        return None
    return {"records": records[:MAX_ENTRIES], "incomplete": match.group("incomplete") == "true",
            "recordedCount": len(records), "omittedCount": max(0, len(records) - MAX_ENTRIES)}


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
    snapshot = child_failure_snapshot(raw)
    if snapshot is not None:
        value["childFailureSnapshot"] = snapshot
        value["platformCodes"] = list(dict.fromkeys([
            *value["platformCodes"], *(record["code"] for record in snapshot["records"]),
        ]))[:MAX_ENTRIES]
        value["reasonCodes"] = list(dict.fromkeys([
            *value["reasonCodes"], *(record["reason"] for record in snapshot["records"]),
        ]))[:MAX_ENTRIES]
    validate(value)
    return value
