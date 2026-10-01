"""Bounded, source-bound observations; never a package eligibility decision."""
from __future__ import annotations

import re

from tools.dev_workflow.common import decode, digest, encode, integer, members, require, sha

SCHEMA = "lsf.guest.compatibility.v1"
LANGUAGES = ("rust", "c", "typescript", "go", "java", "dotnet")
MAX_FINDINGS = 64
MAX_BYTES = 65536
CLASSIFICATIONS = {
    "resolution-failure": "Capture the selected dependency closure before an offline build.",
    "target-incompatible": "The selected compiler, target, ABI or feature cannot represent this operation.",
    "unsupported-eliminated": "Compiler evidence eliminated this operation from the selected entry points.",
    "unsupported-reached": "Execution reached an operation the selected runtime does not implement.",
    "unresolved-behavior": "Analysis or execution evidence is incomplete; compatibility remains unknown.",
    "missing-runtime-port": "The selected standard runtime API has no maintained implementation.",
    "unqualified-profile": "This profile is proposed or lacks qualification for the selected inputs.",
    "optional-extension": "This path uses an application extension; it does not qualify default construction.",
    "missing-provider": "The recognized interface has no installed provider in the inspected configuration.",
    "missing-grant": "The inspected activation has no grant for this operation.",
    "denied-grant": "The inspected activation policy denied the requested operation.",
    "resource-exhausted": "The named activation resource limit was exhausted.",
    "deadline": "The original or narrower operation deadline expired.",
    "cancelled": "Cancellation was requested; physical retirement needs separate evidence.",
    "lifecycle-unproven": "Accepted work or physical ownership has not been proven quiescent.",
    "external-uncertain": "External completion is uncertain; this finding grants no retry right.",
    "unknown-import": "The final component imports an interface absent from its recognized ABI profile.",
    "surface-mismatch": "The final linked component disagrees with its declared WIT surface.",
    "stale-input": "Captured runtime, patch or compiler input identity does not match the selected input.",
}
BLOCKERS = frozenset(CLASSIFICATIONS) - {
    "unsupported-eliminated", "unresolved-behavior", "optional-extension", "lifecycle-unproven",
}
PHASES = ("resolution", "compile", "link", "initialization", "invocation", "retirement")
EVIDENCE = ("final-component", "compiler", "actual-component", "native-reference", "model", "not-evaluated")
RESOURCES = ("tasks", "threads", "frames", "queues", "timers", "guest-memory", "native-memory", "provider", "fuel")
TOKEN = re.compile(r"[A-Za-z0-9_.:/@+\[\]-]{1,192}")


def token(value: str) -> str:
    # No URLs, credentials, query strings, raw exception messages or backtraces.
    require(isinstance(value, str) and TOKEN.fullmatch(value) is not None
            and "://" not in value and ".." not in value and "\\" not in value,
            "compatibility-attribution-token")
    return value


def finding(classification: str, phase: str, evidence: str, *, operation: str | None = None,
            owner_issue: int | None = None, resource: str | None = None,
            package_digest: str | None = None, source_digest: str | None = None,
            symbol: str | None = None, location: dict | None = None) -> dict:
    value = {"classification": classification, "phase": phase, "evidence": evidence}
    for key, item in (("operation", operation), ("ownerIssue", owner_issue), ("resource", resource),
                      ("packageDigest", package_digest), ("sourceDigest", source_digest),
                      ("symbol", symbol), ("location", location)):
        if item is not None:
            value[key] = item
    validate_finding(value)
    return value


def validate_finding(value: dict) -> None:
    members(value, {"classification", "phase", "evidence"}, {
        "operation", "ownerIssue", "resource", "packageDigest", "sourceDigest", "symbol", "location"})
    require(value["classification"] in CLASSIFICATIONS and value["phase"] in PHASES
            and value["evidence"] in EVIDENCE, "compatibility-classification")
    for key in ("operation", "symbol"):
        if key in value:
            token(value[key])
    for key in ("sourceDigest", "packageDigest"):
        if key in value:
            sha(value[key])
    if "ownerIssue" in value:
        integer(value["ownerIssue"], 1, 10000000)
    if "resource" in value:
        require(value["resource"] in RESOURCES, "compatibility-resource")
        require(value["classification"] == "resource-exhausted", "compatibility-resource-class")
    if "location" in value:
        location = members(value["location"], {"path", "line", "column"})
        path = token(location["path"])
        require(not path.startswith("/") and ":" not in path
                and all(part not in {"", ".", ".."} for part in path.split("/")), "compatibility-relative-location")
        integer(location["line"], 1, 10000000)
        integer(location["column"], 1, 10000000)
    # An eliminated operation requires actual compiler evidence, never a name scan.
    if value["classification"] == "unsupported-eliminated":
        require(value["evidence"] == "compiler" and "sourceDigest" in value, "compatibility-elimination-evidence")


def status(findings: list[dict], omitted: int) -> str:
    if any(item["classification"] in BLOCKERS for item in findings):
        return "blocked"
    if omitted or any(item["classification"] in {"unresolved-behavior", "lifecycle-unproven", "optional-extension"}
                      for item in findings):
        return "incomplete"
    return "observed"


def report(language: str, source: str, component: str | None, profile: str,
           inputs: list[dict], findings, *, omitted: int = 0) -> dict:
    retained = []
    # Bound traversal too: callers cannot conceal an infinite stream behind truncation.
    for ordinal, item in enumerate(findings):
        require(ordinal < 4096, "compatibility-finding-input-limit")
        validate_finding(item)
        if len(retained) < MAX_FINDINGS:
            retained.append(item)
        else:
            omitted += 1
    value = {"schemaVersion": SCHEMA, "language": language, "sourceDigest": source,
             "componentDigest": component, "runtimeProfile": profile, "inputs": inputs,
             "findings": retained, "omittedFindings": omitted, "status": status(retained, omitted),
             "authority": "none", "analysisCompleteness": "selected-observations"}
    value["identity"] = digest(encode(value))
    validate(value)
    return value


def validate(value: dict) -> dict:
    members(value, {"schemaVersion", "language", "sourceDigest", "componentDigest", "runtimeProfile", "inputs",
                    "findings", "omittedFindings", "status", "authority", "analysisCompleteness", "identity"})
    require(value["schemaVersion"] == SCHEMA and value["language"] in LANGUAGES, "compatibility-version-or-language")
    sha(value["sourceDigest"])
    if value["componentDigest"] is not None:
        sha(value["componentDigest"])
    token(value["runtimeProfile"])
    require(isinstance(value["inputs"], list) and len(value["inputs"]) <= 64, "compatibility-input-limit")
    identities = set()
    for item in value["inputs"]:
        members(item, {"kind", "digest"}, {"originalDigest", "transformDigest", "profile"})
        require(item["kind"] in {"application", "sdk", "compiler", "runtime", "patch", "build-tool"}, "compatibility-input-kind")
        sha(item["digest"])
        for key in ("originalDigest", "transformDigest"):
            if key in item:
                sha(item[key])
        if "profile" in item:
            token(item["profile"])
        if item["kind"] == "patch":
            require({"originalDigest", "transformDigest"} <= item.keys(), "compatibility-patch-preimage-required")
        identity = encode(item)
        require(identity not in identities, "compatibility-duplicate-input")
        identities.add(identity)
    require(isinstance(value["findings"], list) and len(value["findings"]) <= MAX_FINDINGS, "compatibility-finding-limit")
    for item in value["findings"]:
        validate_finding(item)
    integer(value["omittedFindings"], 0, 10000000)
    require(value["status"] == status(value["findings"], value["omittedFindings"]), "compatibility-status-mismatch")
    require(value["authority"] == "none" and value["analysisCompleteness"] == "selected-observations",
            "compatibility-report-cannot-grant-authority")
    raw = encode({key: item for key, item in value.items() if key != "identity"})
    require(len(encode(value)) <= MAX_BYTES and digest(raw) == sha(value["identity"]), "compatibility-report-identity-or-size")
    return value


def present(value: dict) -> str:
    validate(value)
    lines = [f"Compatibility: {value['status']} ({value['language']}, {value['runtimeProfile']})."]
    for item in value["findings"]:
        text = f"{item['classification']} [{item['phase']}; {item['evidence']}]: {CLASSIFICATIONS[item['classification']]}"
        if "operation" in item:
            text += " Operation: " + item["operation"] + "."
        if "ownerIssue" in item:
            text += " Implementation: #" + str(item["ownerIssue"]) + "."
        lines.append(text)
    if value["omittedFindings"]:
        lines.append(f"Additional findings omitted: {value['omittedFindings']}.")
    lines.append("Selected observations only; package membership, runtime authority and retry safety are not inferred.")
    return "\n".join(lines) + "\n"


def import_findings(actual: list[str], declared: list[str], host_abi: dict,
                    *, installed: set[str] | None = None, granted: set[str] | None = None) -> list[dict]:
    require(len(actual) <= 128 and len(declared) <= 128, "compatibility-import-count")
    require(len(set(actual)) == len(actual) and len(set(declared)) == len(declared), "compatibility-duplicate-import")
    for name in [*actual, *declared]:
        token(name)
    known = {row["interface"] for row in host_abi["interfaces"]}
    result = []
    if set(actual) != set(declared):
        result.append(finding("surface-mismatch", "link", "final-component"))
    for name in sorted(actual):
        if name not in known:
            result.append(finding("unknown-import", "link", "final-component", operation=name))
        elif installed is not None and name not in installed:
            result.append(finding("missing-provider", "invocation", "not-evaluated", operation=name))
        elif granted is not None and name not in granted:
            result.append(finding("missing-grant", "invocation", "not-evaluated", operation=name))
    if installed is None or granted is None:
        result.append(finding("unresolved-behavior", "invocation", "not-evaluated"))
    return result


def read(raw: bytes) -> dict:
    return validate(decode(raw, MAX_BYTES))


def main() -> int:
    import argparse
    from pathlib import Path
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--json", action="store_true", help="validate and emit the bounded machine report")
    args = parser.parse_args()
    with args.report.open("rb") as source:
        value = read(source.read(MAX_BYTES + 1))
    print(encode(value).decode().rstrip() if args.json else present(value), end="\n" if args.json else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
