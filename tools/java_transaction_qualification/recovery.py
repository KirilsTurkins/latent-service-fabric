"""Observe the installed native offline owner; inputs and receipts are no grants."""
from __future__ import annotations

from pathlib import Path
import re
import time

from . import configuration as cfg, lifecycle
from .evidence import encoded, native
from .inputs import decode, require

REPORT_FIELDS = {"schemaVersion", "operationSucceeded", "failure", "result", "retirement", "catalogsRetired"}
RETIREMENT_FIELDS = {"clean", "physicallyRetired", "liveWorkers", "acceptedJobs", "threadsJoined"}
ACTIONS = {"snapshot", "inspect-namespace", "inspect-restore", "restore", "stage-migration",
           "complete-migration", "resume-migration", "resume-restored-migration", "review", "resume",
           "inspect-close-effects", "close-effects"}
FAILURES = {"configuration", "busy", "destination", "input", "review", "target", "protected"}
FAILURE_REASONS = {
    "platform": {"unavailable", "deadline-exceeded", "cancelled", "resource-exhausted", "permission-denied",
                 "unauthenticated", "invalid-argument", "not-found", "already-exists", "incompatible-contract",
                 "state-conflict", "dependency-failed", "guest-trap", "corrupt-artifact", "route-unavailable",
                 "admission-rejected", "internal"},
    "dispatcher": {"invalidConfiguration", "unsupportedOrdering", "invalidAdapter", "checkpointRequired",
                   "admissionClosed", "staleEpoch"},
    "authority": {"invalid", "capacity", "policyBlocked", "unsupportedFormat", "expired", "clockDiscontinuity",
                  "stale", "unavailable"},
    "protected": {"invalidConfiguration", "unsupportedPlatform", "unsupportedFilesystem", "unsafeRoot",
                  "foreignView", "commitUncertain"},
    "storage": {"invalid", "capacity", "conflict", "corrupt", "unsupportedFormat", "unavailable",
                "commitUncertain", "snapshotExpired"},
    "worker": {"invalidLimits", "admissionClosed", "recoveryUnavailable", "queueFull", "acceptedFull",
               "byteBudget", "jobTooLarge", "exhausted", "poisoned", "workerStartFailed", "recoveryRequired",
               "initializationFailed", "notStarted", "finalizationFailed", "drainWaiterBusy", "alreadyDelivered"},
}


def decoder_sources(items, publications):
    """Explicit signed byte identities, never old deployment or decoder grants."""
    names = ("put-once-legacy-v1", "put-once-compatible-v2", "put-once-writer-v2", "put-once-diagnostics")
    require(isinstance(publications, dict) and set(names) <= set(publications),
            "four-explicit-current-decoder-publications")
    selected = []
    for name in names:
        require(name in items, "original-current-decoder-item-required")
        component, publication = items[name].component_digest, publications[name]
        original_digest(component)
        require(isinstance(publication, str) and re.fullmatch(r"publication:sha256:[0-9a-f]{64}", publication),
                "current-decoder-publication-identity")
        selected.append({"componentDigest": component, "publication": publication})
    require(len({row["componentDigest"] for row in selected}) == 4
            and len({row["publication"] for row in selected}) == 4,
            "distinct-current-decoder-byte-identities")
    return selected


def byte_array(value, maximum):
    require(isinstance(value, list) and len(value) <= maximum
            and all(type(byte) is int and 0 <= byte <= 255 for byte in value),
            "native-original-byte-array")
    return bytes(value)


def original_view(value):
    raw = byte_array(value, 67)
    require(len(raw) == 67 and raw.startswith(b"NV\x02")
            and all(int.from_bytes(raw[offset:offset + 8], "little") > 0
                    for offset in (35, 43, 51, 59)), "native-original-view-token")
    return list(raw)


def original_digest(value):
    require(isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value)
            and value[7:] != "0" * 64, "native-original-digest")
    return value


def report(raw):
    value = decode(raw, 1048576)
    require(isinstance(value, dict) and set(value) == REPORT_FIELDS
            and value["schemaVersion"] in {"latent.native-transaction-recovery.v1",
                                           "latent.native-transaction-recovery.v2"}
            and type(value["operationSucceeded"]) is bool
            and type(value["catalogsRetired"]) is bool, "closed-native-recovery-report")
    if value["operationSucceeded"]:
        require(value["failure"] is None and isinstance(value["result"], dict),
                "native-success-keeps-original-result")
    else:
        failure = value["failure"]
        if value["schemaVersion"] == "latent.native-transaction-recovery.v2":
            require(value["result"] is None and isinstance(failure, dict)
                    and set(failure) == {"code", "message", "retryable"}
                    and failure["code"] in FAILURE_REASONS["platform"]
                    and isinstance(failure["message"], str) and len(failure["message"]) <= 1024
                    and type(failure["retryable"]) is bool, "closed-current-native-producer-failure")
        else:
            require(value["result"] is None and isinstance(failure, dict)
                and failure.get("stage") in FAILURES
                and set(failure) == ({"stage"} if failure.get("stage") in {"configuration", "busy", "destination"}
                                    else {"stage", "failure"}), "native-failure-is-not-success")
        if value["schemaVersion"] == "latent.native-transaction-recovery.v1" and "failure" in failure:
            detail = failure["failure"]
            require(isinstance(detail, dict) and set(detail) == {"owner", "reason"}
                    and isinstance(detail["owner"], str) and isinstance(detail["reason"], str)
                    and detail["reason"] in FAILURE_REASONS.get(detail["owner"], set()),
                    "closed-native-producer-failure")
    retired = value["retirement"]
    if retired is not None:
        require(isinstance(retired, dict) and set(retired) == RETIREMENT_FIELDS
                and all(type(retired[name]) is bool for name in ("clean", "physicallyRetired"))
                and all(type(retired[name]) is int and 0 <= retired[name] <= 4096
                        for name in ("liveWorkers", "acceptedJobs"))
                and (retired["threadsJoined"] is None
                     or type(retired["threadsJoined"]) is int and 0 <= retired["threadsJoined"] <= 16),
                "closed-native-physical-retirement")
    # A failed/uncertain writer result never becomes KnownNotCommitted merely
    # because its process or physical workers retired.
    return value


def require_success(value):
    require(value["operationSucceeded"] and value["failure"] is None,
            "actual-native-offline-action-required")
    retired = value["retirement"]
    require(retired is not None and retired["clean"] and retired["physicallyRetired"]
            and retired["liveWorkers"] == retired["acceptedJobs"] == 0
            and type(retired["threadsJoined"]) is int and retired["threadsJoined"] > 0
            and value["catalogsRetired"] is True, "actual-native-offline-retirement-required")
    return value["result"]


def require_stopped_owner(client, node):
    require(client.node is None and node.process is None and node.shutdown,
            "positive-original-node-retirement-required")
    stopped = node.shutdown[-1]
    require(stopped["reaped"] is True and stopped["record"]["event"] == "stopped"
            and stopped["record"]["clean"] is True, "original-node-stopped-record-required")
    lifecycle.require_retirement(stopped["record"]["report"])


class Recovery:
    """One stopped-node action on actual signed settings and transport caller.

    The native owner authenticates this exact configured token and enforces the
    current purpose, package, schema, namespace, checkpoint and physical fences.
    Nothing here derives a grant, native profile, schema review or continuity.
    """
    def __init__(self, client, helper: Path, configuration, directory: Path, node, *, sources=None):
        self.client, self.helper, self.configuration = client, helper, configuration
        self.node = node
        self.sources = sources
        directory.mkdir(mode=0o700)
        self.directory, self.calls = directory, 0
        callers = [entry for entry in configuration.value["credentials"]
                   if entry.get("subject") == cfg.OPERATOR and entry.get("tenant") == cfg.TENANT
                   and entry.get("role") == "operator"]
        require(len(callers) == 1 and isinstance(callers[0].get("token"), str),
                "actual-configured-native-operator-required")
        token = callers[0]["token"].encode()
        require(0 < len(token) <= 512, "native-original-credential-bound")
        self.credential = directory / "operator-token"
        with self.credential.open("xb") as target:
            target.write(token)
        self.credential.chmod(0o600)

    def run(self, configuration: Path, publication: str, request: dict):
        require_stopped_owner(self.client, self.node)
        require(self.client.node is None and self.calls < 12 and time.monotonic() < self.client.deadline,
                "original-stopped-node-recovery-owner-required")
        require(isinstance(publication, str) and re.fullmatch(r"publication:sha256:[0-9a-f]{64}", publication)
                and isinstance(request, dict) and request.get("action") in ACTIONS
                and not ({"approved", "grant", "deadline", "continuity"} & set(request)),
                "closed-native-recovery-action-data")
        envelope = {"publication": publication, "request": request}
        if self.sources is not None:
            require(isinstance(self.sources, list) and len(self.sources) == 4
                    and all(isinstance(row, dict) and set(row) == {"componentDigest", "publication"}
                            for row in self.sources)
                    and len({row["publication"] for row in self.sources}) == 4
                    and publication in {row["publication"] for row in self.sources},
                    "closed-four-current-decoder-source-selectors")
            for row in self.sources:
                original_digest(row["componentDigest"])
                require(isinstance(row["publication"], str)
                        and re.fullmatch(r"publication:sha256:[0-9a-f]{64}", row["publication"]),
                        "current-decoder-publication-identity")
            envelope["decoderSources"] = [row for row in self.sources if row["publication"] != publication]
        raw = encoded(envelope)
        require(len(raw) <= 16384, "original-native-recovery-input-bound")
        self.calls += 1
        stage = f"native-recovery-{self.calls:02d}"
        path = self.directory / (stage + ".json")
        with path.open("xb") as target:
            target.write(raw)
        path.chmod(0o600)
        self.client.evidence.write(stage + ".input", raw)
        result = report(native(self.client, self.helper, stage, "--config", configuration,
            "--credential-file", self.credential, "--tenant", cfg.TENANT, "--request-file", path,
            timeout=90))
        self.client.evidence.record(stage + "-report", result)
        if result['schemaVersion'] == 'latent.native-transaction-recovery.v2':
            require(result['catalogsRetired'] is True, 'current-native-control-catalog-retirement-required')
            lifecycle.admission_lease_interval(self.client)
        return result
