"""Replay one fixed persistent client session against actual parent/owner receipts."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import stat

from tools.optimization_evidence import attempts, workload
from tools.optimization_evidence.common import (
    EvidenceError, canonical, decode, digest, fields, integer, require, sha256, text, uint,
)
from . import model

PREFIX = model.CLIENT_PREFIX
MAXIMUM = 32 * 1024**2
EVENT_FIELDS = "schema event event_ordinal command_ordinal process_id plan_sha256 session_elapsed_nanos payload"
COMMAND_FIELDS = "schema ordinal plan_sha256 command group phase barrier targets"
ENVELOPE_FIELDS = ("schema pair group arm density phase phase_name phase_kind global_ordinal target_index "
                   "owner_ref app_process_id attempt")


def _equal(actual, expected, reason):
    require(canonical(actual) == canonical(expected), reason)


def _read(path, maximum):
    try:
        before = path.lstat()
        require(stat.S_ISREG(before.st_mode) and not path.is_symlink()
                and not getattr(before, "st_file_attributes", 0) & 0x400
                and before.st_size <= maximum, "docker-client-file-bound")
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            require((before.st_dev, before.st_ino) == (opened.st_dev, opened.st_ino), "docker-client-file-crossed")
            data = stream.read(maximum + 1)
            after = os.fstat(stream.fileno())
        closed = path.lstat()
        require(len(data) == before.st_size <= maximum
                and (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                == (closed.st_dev, closed.st_ino, closed.st_size, closed.st_mtime_ns),
                "docker-client-file-changed")
        return data
    except OSError as error:
        raise EvidenceError("docker-client-file-unreadable") from error


def _lines(data, maximum, count):
    rows, offset = [], 0
    for line in data.splitlines(keepends=True):
        require(len(rows) < count and line.endswith(b"\n") and 1 < len(line) <= maximum,
                "docker-client-line-bound")
        rows.append((decode(line, maximum), offset, line))
        offset += len(line)
    require(offset == len(data), "docker-client-line-framing")
    return rows


def _reference(value, path, data):
    fields(value, "path bytes sha256")
    require(value["path"] == path and uint(value["bytes"]) == len(data)
            and digest(value["sha256"]) == sha256(data), "docker-client-reference")


def _plan(value):
    fields(value, "schema run_id profile pair token_file")
    require(value["schema"] == PREFIX + "plan.v1"
            and re.fullmatch(r"[A-Za-z0-9-]{1,24}", text(value["run_id"], 24)), "docker-client-plan")
    text(value["token_file"], 4096)
    return model.groups(value["profile"], value["pair"])


def _sequence(groups):
    rows = []
    for group in groups:
        index = group["ordinal"]
        rows += [("begin-group", index, None, None), ("inventory", index, None, "ready")]
        for phase in group["phases"]:
            rows.append(("phase", index, phase["ordinal"], None))
            if phase["ordinal"] == 0:
                rows.append(("inventory", index, None, "served"))
        rows += [("inventory", index, None, "final"), ("finish-group", index, None, None)]
    return [*rows, ("finish", None, None, None)]


def _targets(value, group, owners):
    require(isinstance(value, list) and len(value) == group["density"], "docker-client-target-count")
    refs, endpoints = set(), set()
    first = None
    for index, target in enumerate(value):
        fields(target, "service endpoint owner_ref app_process_id")
        require(target["service"] == model.SERVICES[index], "docker-client-target-service")
        owner_ref = text(target["owner_ref"], 128)
        require(re.fullmatch(r"[A-Za-z0-9_-]+", owner_ref) and owner_ref in owners, "docker-client-target-owner")
        endpoint = text(target["endpoint"], 2048)
        require(endpoint.startswith("http://") and not any(ord(char) < 32 or ord(char) == 127 for char in endpoint),
                "docker-client-target-endpoint")
        pid = integer(target["app_process_id"], 1, 2**31 - 1)
        owner = fields(owners[owner_ref], "app_process_id endpoint arm density group container_id",
                       "service_endpoints release_digests" if group["arm"] == "lsf" else "service_endpoints")
        owner_endpoint = owner["endpoint"]
        if "service_endpoints" in owner:
            service_endpoints = owner["service_endpoints"]
            expected_services = model.SERVICES[:group["density"]] if group["arm"] == "lsf" else [target["service"]]
            require(isinstance(service_endpoints, dict) and set(service_endpoints) == set(expected_services),
                    "docker-client-owner-service-endpoints")
            for service_endpoint in service_endpoints.values():
                service_endpoint = text(service_endpoint, 2048)
                require(service_endpoint.startswith("http://") and not any(ord(char) < 32 or ord(char) == 127
                        for char in service_endpoint), "docker-client-owner-service-endpoint")
            require(len(set(service_endpoints.values())) == len(service_endpoints)
                    and owner_endpoint in service_endpoints.values(), "docker-client-owner-service-alias")
            owner_endpoint = service_endpoints[target["service"]]
        _equal([owner["app_process_id"], owner_endpoint, owner["arm"], owner["density"], owner["group"]],
               [pid, endpoint, group["arm"], group["density"], group["ordinal"]], "docker-client-owner-crossed")
        require(re.fullmatch(r"[0-9a-f]{64}", text(owner["container_id"], 64)), "docker-client-container-id")
        if group["arm"] == "lsf":
            releases = owner.get("release_digests")
            require(isinstance(releases, dict) and set(releases) == set(model.SERVICES[:group["density"]]),
                    "docker-client-fixture-releases")
            for release in releases.values():
                digest(release)
            if first is not None:
                require(first == (owner_ref, pid), "docker-client-lsf-owner-crossed")
            first = (owner_ref, pid)
        else:
            require(owner_ref not in refs and endpoint not in endpoints, "docker-client-native-owner-alias")
        refs.add(owner_ref)
        endpoints.add(endpoint)
    return refs


def _commands(rows, groups, plan_digest, owners):
    expected = _sequence(groups)
    require(isinstance(rows, list) and len(rows) == len(expected) == 61, "docker-client-command-count")
    parsed, receipts, targets, used = [], [], {}, set()
    previous = 0
    for ordinal, (parent, shape) in enumerate(zip(rows, expected)):
        fields(parent, "line sent_nanos")
        sent = uint(parent["sent_nanos"])
        require(sent >= previous, "docker-client-parent-command-clock")
        previous = sent
        line = text(parent["line"], 64 * 1024).encode("utf-8")
        require(line.endswith(b"\n") and line.count(b"\n") == 1, "docker-client-command-line")
        command = fields(decode(line, 64 * 1024), COMMAND_FIELDS)
        _equal([command[key] for key in ("schema", "ordinal", "plan_sha256", "command", "group", "phase", "barrier")],
               [PREFIX + "command.v1", ordinal, plan_digest, *shape], "docker-client-command-order")
        if shape[0] == "begin-group":
            group = groups[shape[1]]
            own = _targets(command["targets"], group, owners)
            require(not used & own, "docker-client-owner-reused-across-groups")
            used |= own
            targets[group["ordinal"]] = command["targets"]
        else:
            require(command["targets"] is None, "docker-client-command-override")
        parsed.append(command)
        receipts.append({"command": command, "command_bytes": str(len(line)), "command_sha256": sha256(line)})
    require(used == set(owners), "docker-client-unused-owner")
    return parsed, receipts, targets


def _acknowledgements(rows, events, attempt_data, summary_data, commands, plan_digest, process_id):
    require(isinstance(rows, list) and len(rows) == len(events) + 1 == 68, "docker-client-ack-count")
    previous_time = previous_attempt = 0
    completed = {}
    stream = hashlib.sha256()
    boundaries = {0, *[offset + len(line) for _, offset, line in _lines(attempt_data, 20 * 1024, 1418)]}
    prefixes = []
    for parent, (event, offset, line) in zip(rows[:-1], events):
        fields(parent, "ack received_nanos")
        received = uint(parent["received_nanos"])
        require(received >= previous_time, "docker-client-ack-parent-clock")
        previous_time = received
        ack = fields(parent["ack"], "schema event command_ordinal process_id plan_sha256 event_record attempts")
        _equal([ack[key] for key in ("schema", "event", "command_ordinal", "process_id", "plan_sha256")],
               [PREFIX + "ack.v1", event["event"], event["command_ordinal"], process_id, plan_digest],
               "docker-client-ack-crossed")
        ref = fields(ack["event_record"], "path offset bytes sha256")
        require(ref["path"] == "events.jsonl" and uint(ref["offset"]) == offset
                and uint(ref["bytes"]) == len(line) and digest(ref["sha256"]) == sha256(line),
                "docker-client-event-range")
        ref = fields(ack["attempts"], "path bytes sha256")
        end = uint(ref["bytes"])
        require(ref["path"] == "attempts.jsonl" and previous_attempt <= end <= len(attempt_data)
                and end in boundaries, "docker-client-attempt-prefix")
        stream.update(attempt_data[previous_attempt:end])
        require(digest(ref["sha256"]) == "sha256:" + stream.hexdigest(), "docker-client-attempt-prefix-hash")
        previous_attempt = end
        prefixes.append(end)
        ordinal = event["command_ordinal"]
        if ordinal is not None:
            integer(ordinal, 0, 59)
            require(uint(commands[ordinal]["sent_nanos"]) <= received, "docker-client-ack-before-send")
            if event["event"] != "first-response":
                require(ordinal not in completed, "docker-client-duplicate-command-ack")
                completed[ordinal] = received
        else:
            require(event["event"] == "ready", "docker-client-ack-unbound")
    require(set(completed) == set(range(60)), "docker-client-missing-command-ack")
    require(uint(commands[0]["sent_nanos"]) >= uint(rows[0]["received_nanos"]), "docker-client-send-before-ready")
    for ordinal in range(1, 61):
        require(uint(commands[ordinal]["sent_nanos"]) >= completed[ordinal - 1], "docker-client-overlapping-commands")
    final_parent = fields(rows[-1], "ack received_nanos")
    require(uint(final_parent["received_nanos"]) >= max(previous_time, uint(commands[60]["sent_nanos"])),
            "docker-client-final-ack-clock")
    final = fields(final_parent["ack"], "schema event command_ordinal process_id plan_sha256 summary")
    _equal({key: final[key] for key in final if key != "summary"},
           {"schema": PREFIX + "ack.v1", "event": "complete", "command_ordinal": 60,
            "process_id": process_id, "plan_sha256": plan_digest}, "docker-client-final-ack")
    _reference(final["summary"], "summary.json", summary_data)
    require(previous_attempt == len(attempt_data), "docker-client-unacknowledged-attempts")
    return prefixes


def _ready(value, plan, groups, total):
    fields(value, "plan groups logical_offers commands runtime_workers maximum_channels maximum_output_bytes "
                  "maximum_command_bytes group_timeout_seconds session_timeout_seconds")
    _equal(value, {"plan": {key: plan[key] for key in plan if key != "token_file"}, "groups": groups,
                  "logical_offers": str(total), "commands": 61, "runtime_workers": 2, "maximum_channels": 32,
                  "maximum_output_bytes": str(MAXIMUM), "maximum_command_bytes": 64 * 1024,
                  "group_timeout_seconds": 300, "session_timeout_seconds": 1800}, "docker-client-ready-plan")


def _connections(value, targets, before, after):
    fields(value, "status reason connections independent_channels")
    require(value["status"] == "passed" and value["reason"] is None, "docker-client-connect-failed")
    integer(value["independent_channels"], len(targets), len(targets))
    require(isinstance(value["connections"], list) and len(value["connections"]) == len(targets),
            "docker-client-connection-count")
    for index, (row, target) in enumerate(zip(value["connections"], targets)):
        fields(row, "target_index owner_ref app_process_id endpoint started_nanos finished_nanos status reason")
        _equal([row[key] for key in ("target_index", "owner_ref", "app_process_id", "endpoint", "status", "reason")],
               [index, target["owner_ref"], target["app_process_id"], target["endpoint"], "connected", None],
               "docker-client-connection-owner")
        begin, end = uint(row["started_nanos"]), uint(row["finished_nanos"])
        require(before <= begin <= end <= after and end - begin <= 5_100_000_000, "docker-client-connect-clock")
        before = end


def _request(phase):
    payload = canonical(phase["payload"])
    result = workload.expected(phase["function"], phase["payload"])
    return {"tenant": model.TENANT, "contract": model.CONTRACT, "function": phase["function"], "route": None,
            "cpu_fuel": "10000000000", "memory_bytes": "67108864", "log_bytes": "16384", "budget_millis": "1000",
            "response_timeout_millis": "5000", "payload_sha256": sha256(payload), "payload_bytes": str(len(payload)),
            "expected_output_sha256": sha256(result), "expected_output_bytes": str(len(result))}


def _phase(value, phase, group, plan, targets, owners, selected, base, before, after, pins):
    fields(value, "status reason phase origin_session_nanos origin_unix_nanos clock_anchor_uncertainty_nanos "
                  "phase_elapsed_nanos request counts active_tasks")
    require(value["status"] == "passed" and value["reason"] is None, "docker-client-phase-failed")
    integer(value["active_tasks"], 0, 0)
    _equal(value["phase"], {key: phase[key] for key in phase if key != "payload"}, "docker-client-phase-plan")
    request = _request(phase)
    _equal(value["request"], request, "docker-client-request-semantic-input")
    origin, elapsed = uint(value["origin_session_nanos"]), uint(value["phase_elapsed_nanos"])
    wall = uint(value["origin_unix_nanos"])
    uncertainty = uint(value["clock_anchor_uncertainty_nanos"])
    require(before <= origin <= origin + elapsed <= after and uncertainty <= origin, "docker-client-phase-clock")
    require(len(selected) == phase["offers"], "docker-client-phase-offer-count")
    indices, rows, timing = set(), [], []
    kind = "warmup" if phase["kind"] == "warmup" else "measured"
    for envelope, _, _ in selected:
        fields(envelope, ENVELOPE_FIELDS)
        require(isinstance(envelope["attempt"], dict), "docker-client-attempt-object")
        index = uint(envelope["attempt"].get("index"))
        require(index < phase["offers"] and index not in indices, "docker-client-offer-index")
        indices.add(index)
        target_index = index % group["density"]
        target = targets[target_index]
        expected = {"schema": PREFIX + "attempt.v1", "pair": plan["pair"], "group": group["ordinal"],
                    "arm": group["arm"], "density": group["density"], "phase": phase["ordinal"],
                    "phase_name": phase["name"], "phase_kind": phase["kind"], "global_ordinal": base + index,
                    "target_index": target_index, "owner_ref": target["owner_ref"], "app_process_id": target["app_process_id"]}
        _equal({key: envelope[key] for key in envelope if key != "attempt"}, expected, "docker-client-offer-owner")
        legacy = {"run_id": f"{plan['run_id']}-p{plan['pair']}-g{group['ordinal']}-s{phase['ordinal']}",
                  "arm": group["arm"], "services": [target["service"]], "batch_size": phase["offers"],
                  "warmup_attempts": phase["offers"], "measured_attempts": phase["offers"],
                  "schedule": {"mode": "closed-loop"}, "budget_millis": 1000,
                  "cpu_fuel": 10_000_000_000, "memory_bytes": 67_108_864, "log_bytes": 16_384}
        row = envelope["attempt"]
        components = owners[target["owner_ref"]].get("release_digests", {})
        attempts.attempt(row, legacy, kind, wall,
                         {"sha256": request["expected_output_sha256"], "bytes": int(request["expected_output_bytes"])}, components)
        require(row["outcome"] == "success" and uint(row["completed_nanos"]) <= elapsed, "docker-client-nonsuccess-or-late-row")
        require(uint(row["completed_nanos"]) - uint(row["dispatch_nanos"]) <= 5_100_000_000,
                "docker-client-outer-observation-bound")
        identity = tuple(row["response"][key] for key in ("revision_id", "release_digest", "route_generation"))
        key = (target["owner_ref"], target["service"])
        require(key not in pins or pins[key] == identity, "docker-client-response-pin-changed")
        pins[key] = identity
        rows.append(row)
        timing += [(uint(row["scheduled_nanos"]), 1), (uint(row["completed_nanos"]), -1)]
    _equal(value["counts"], attempts.counts(rows), "docker-client-phase-counts")
    active = maximum = 0
    for _, delta in sorted(timing):
        active += delta
        require(active >= 0, "docker-client-concurrency-clock")
        maximum = max(maximum, active)
    require(active == 0 and maximum <= phase["concurrency"], "docker-client-global-concurrency")
    return {"group": group["ordinal"], "arm": group["arm"], "density": group["density"], "phase": phase,
            "origin_session_nanos": str(origin), "origin_unix_nanos": str(wall), "phase_elapsed_nanos": str(elapsed),
            "request": request, "metrics": attempts.metrics(rows), "maximum_observed_in_flight": maximum}


def _inventory(value, group, barrier, before, after):
    fields(value, "status barrier rpc_calls inventory reason channel_index started_nanos finished_nanos")
    require(value["status"] == "passed" and value["barrier"] == barrier, "docker-client-inventory-failed")
    begin, end = uint(value["started_nanos"]), uint(value["finished_nanos"])
    require(before <= begin <= end <= after and end - begin <= 5_100_000_000, "docker-client-inventory-clock")
    if group["arm"] == "native":
        _equal([value[key] for key in ("rpc_calls", "inventory", "reason", "channel_index")],
               [0, None, "native-no-management-api", None], "docker-client-native-management-work")
    else:
        _equal([value[key] for key in ("rpc_calls", "reason", "channel_index")], [1, None, 0],
               "docker-client-management-channel")
        inventory = fields(value["inventory"], "node cellCapacity memoryPressureMilli queueDepth routeGeneration cacheEntries "
                            "observedAtUnixMillis cacheSummary pressure health topology quotas retainedBytes")
        _inventory_fields(inventory)
        # Retain the complete CLI-compatible public DTO. The parent validates
        # configured capacity/health/topology against the retained node config.
        cache = fields(inventory["cacheSummary"], "available entries maximumEntries sourceBytes maximumSourceBytes metadataBytes "
                       "maximumMetadataBytes compiledImageBytes maximumCompiledImageBytes preparing maximumConcurrentPreparations "
                       "preparingSourceBytes preparingMetadataBytes hits misses evictions invalidations")
        require(cache["available"] is True and uint(cache["entries"]) == (0 if barrier == "ready" else group["density"])
                and uint(cache["preparing"]) == 0, "docker-client-inventory-preparation")
        for key, number in cache.items():
            if key != "available":
                uint(number)
        for key in ("queueDepth", "routeGeneration", "observedAtUnixMillis", "retainedBytes"):
            uint(inventory[key])
        require(inventory["queueDepth"] == "0", "docker-client-inventory-not-idle")
    return {"group": group["ordinal"], "arm": group["arm"], "density": group["density"], **value}


def _strings(value, maximum=512):
    require(isinstance(value, list) and len(value) <= 512, "docker-client-inventory-list")
    for item in value:
        text(item, maximum)


def _attributes(value):
    require(isinstance(value, dict) and len(value) <= 512, "docker-client-inventory-attributes")
    for key, item in value.items():
        text(key, 512)
        text(item, 4096, empty=True)


def _inventory_fields(value):
    """Closed maintained public DTO; configuration equality remains parent-owned."""
    node = fields(value["node"], "id architecture operatingSystem cpuFeatures trustClasses region zone endpoint identity attributes")
    require(node["id"] == "optimization-node", "docker-client-inventory-node")
    for key in ("id", "architecture", "operatingSystem", "endpoint", "identity"):
        text(node[key], 2048, empty=key in ("endpoint", "identity"))
    for key in ("region", "zone"):
        if node[key] is not None:
            text(node[key], 512)
    _strings(node["cpuFeatures"])
    _strings(node["trustClasses"])
    _attributes(node["attributes"])
    integer(value["memoryPressureMilli"], 0, 1000)
    cells = value["cellCapacity"]
    require(isinstance(cells, list) and len(cells) <= 32, "docker-client-inventory-cells")
    for cell in cells:
        fields(cell, "class observationAvailable accepting total available active quarantined queueDepth queueCapacity queuedTenants "
                     "rejected cancellations expired granted totalWaitMicros maxWaitMicros oldestLeaseAgeMicros")
        text(cell["class"], 128)
        require(type(cell["observationAvailable"]) is bool and type(cell["accepting"]) is bool,
                "docker-client-inventory-cell-flags")
        for key in ("total", "available", "active", "quarantined", "queueDepth", "queueCapacity", "queuedTenants"):
            integer(cell[key])
        for key in ("rejected", "cancellations", "expired", "granted", "totalWaitMicros", "maxWaitMicros", "oldestLeaseAgeMicros"):
            uint(cell[key])
        if cell["observationAvailable"]:
            require(cell["available"] + cell["active"] + cell["quarantined"] == cell["total"]
                    and cell["active"] == cell["quarantined"] == cell["queueDepth"] == cell["queuedTenants"] == 0,
                    "docker-client-inventory-cell-ownership")
    entries = value["cacheEntries"]
    require(isinstance(entries, list) and len(entries) <= 64, "docker-client-inventory-cache-list")
    for entry in entries:
        fields(entry, "key releaseDigest tier sizeBytes lastAccessUnixMillis")
        text(entry["key"], 4096)
        digest(entry["releaseDigest"])
        text(entry["tier"], 128)
        uint(entry["sizeBytes"])
        uint(entry["lastAccessUnixMillis"])
    pressure = fields(value["pressure"], "loadAvailable loadSampleAgeMillis cpuPressureMilli memoryPressureMilli queuePressureMilli cachePressureMilli")
    require(type(pressure["loadAvailable"]) is bool, "docker-client-inventory-load-flag")
    if pressure["loadSampleAgeMillis"] is not None:
        uint(pressure["loadSampleAgeMillis"])
    for key in ("cpuPressureMilli", "memoryPressureMilli", "queuePressureMilli", "cachePressureMilli"):
        integer(pressure[key], 0, 1000)
    health = fields(value["health"], "status ready healthy reasons observedAtUnixMillis")
    require(health["status"] in ("healthy", "degraded", "unhealthy") and type(health["ready"]) is bool
            and type(health["healthy"]) is bool and health["ready"], "docker-client-inventory-health")
    _strings(health["reasons"])
    uint(health["observedAtUnixMillis"])
    topology = fields(value["topology"], "available complete entries")
    require(type(topology["available"]) is bool and type(topology["complete"]) is bool
            and isinstance(topology["entries"], list) and len(topology["entries"]) <= 128,
            "docker-client-inventory-topology")
    for entry in topology["entries"]:
        fields(entry, "name kind ownership configuredCount activeCount attributes")
        text(entry["name"], 512)
        text(entry["kind"], 512)
        require(entry["ownership"] in ("node-fixed", "activation-scoped", "service-resident"), "docker-client-topology-owner")
        uint(entry["configuredCount"])
        if entry["activeCount"] is not None:
            uint(entry["activeCount"])
        _attributes(entry["attributes"])
    if value["quotas"] is not None:
        quotas = fields(value["quotas"], "usage limits retainedTenants")
        usage = fields(quotas["usage"], "activeActivations queuedActivations reservedCpuFuel reservedMemoryBytes")
        for key in ("activeActivations", "queuedActivations"):
            integer(usage[key], 0, 0)
        require(uint(usage["reservedCpuFuel"]) == uint(usage["reservedMemoryBytes"]) == 0,
                "docker-client-inventory-quota-ownership")
        limits = fields(quotas["limits"], "maximumConcurrentActivations maximumQueuedActivations maximumReservedCpuFuel maximumReservedMemoryBytes")
        integer(limits["maximumConcurrentActivations"])
        integer(limits["maximumQueuedActivations"])
        uint(limits["maximumReservedCpuFuel"])
        uint(limits["maximumReservedMemoryBytes"])
        uint(quotas["retainedTenants"])


def validate(directory: Path, plan: dict, commands: list[dict], acknowledgements: list[dict], owners: dict) -> dict:
    """Require one complete session; preserve original failures by rejecting them."""
    directory = Path(directory)
    require(directory.is_dir() and not directory.is_symlink(), "docker-client-directory")
    plan_data = _read(directory / "plan.json", 64 * 1024)
    _equal(decode(plan_data, 64 * 1024), plan, "docker-client-original-plan")
    groups = _plan(plan)
    plan_digest = sha256(plan_data)
    require(isinstance(owners, dict) and len(owners) == 44, "docker-client-owner-population")
    parsed, receipts, targets = _commands(commands, groups, plan_digest, owners)
    require(len({owner["container_id"] for owner in owners.values()}) == 44, "docker-client-container-reused")
    attempt_data = _read(directory / "attempts.jsonl", MAXIMUM)
    event_data = _read(directory / "events.jsonl", MAXIMUM)
    summary_data = _read(directory / "summary.json", 16 * 1024)
    require(len(attempt_data) + len(event_data) + len(summary_data) <= MAXIMUM, "docker-client-total-byte-bound")
    total = 1418 if plan["profile"] == "full" else 300
    offered = _lines(attempt_data, 20 * 1024, total)
    events = _lines(event_data, 2 * 1024 * 1024, 67)
    require(len(offered) == total and len(events) == 67, "docker-client-complete-file-population")
    summary = fields(decode(summary_data, 16 * 1024), "schema status reason plan_sha256 process_id commands_completed groups_completed "
                     "phases_completed offers management_calls active_tasks_at_completion channels_at_completion runtime_dropped "
                     "session_elapsed_nanos attempts finish_command")
    process_id = integer(summary["process_id"], 1, 2**31 - 1)
    end = uint(summary["session_elapsed_nanos"])
    require(end <= 1800 * 10**9, "docker-client-session-deadline")
    _equal({key: summary[key] for key in summary if key not in ("attempts", "process_id", "session_elapsed_nanos", "finish_command")},
           {"schema": PREFIX + "summary.v1", "status": "complete", "reason": None, "plan_sha256": plan_digest,
            "commands_completed": "61", "groups_completed": "6", "phases_completed": "30", "offers": str(total),
            "management_calls": "9", "active_tasks_at_completion": 0, "channels_at_completion": 0, "runtime_dropped": True},
           "docker-client-incomplete-summary")
    _equal(summary["finish_command"], receipts[60], "docker-client-final-command-line")
    _reference(summary["attempts"], "attempts.jsonl", attempt_data)
    previous = 0
    for ordinal, (event, _, _) in enumerate(events):
        fields(event, EVENT_FIELDS)
        _equal([event[key] for key in ("schema", "event_ordinal", "process_id", "plan_sha256")],
               [PREFIX + "event.v1", ordinal, process_id, plan_digest], "docker-client-event-identity")
        elapsed = uint(event["session_elapsed_nanos"])
        require(previous <= elapsed <= end, "docker-client-event-clock")
        previous = elapsed
    prefixes = _acknowledgements(acknowledgements, events, attempt_data, summary_data, commands, plan_digest, process_id)
    ready = events[0][0]
    require(ready["event"] == "ready" and ready["command_ordinal"] is None and prefixes[0] == 0, "docker-client-ready-event")
    _ready(ready["payload"], plan, groups, total)
    cursor, offer_cursor, base = 1, 0, 0
    phases, inventories, first_responses, connections, pins = [], {}, [], [], {}
    group_started = {}
    before = uint(ready["session_elapsed_nanos"])
    for ordinal, command in enumerate(parsed[:-1]):
        group = groups[command["group"]]
        first = None
        if command["command"] == "phase" and command["phase"] == 0:
            first = events[cursor][0]
            require(first["event"] == "first-response" and first["command_ordinal"] == ordinal, "docker-client-first-response-event")
            cursor += 1
        event = events[cursor][0]
        expected_event = {"begin-group": "group-ready", "inventory": "inventory", "phase": "phase-complete",
                          "finish-group": "group-finished"}[command["command"]]
        require(event["event"] == expected_event and event["command_ordinal"] == ordinal, "docker-client-event-command-order")
        payload = fields(event["payload"], "command command_bytes command_sha256 result")
        _equal({key: payload[key] for key in payload if key != "result"}, receipts[ordinal], "docker-client-command-original-line")
        after = uint(event["session_elapsed_nanos"])
        value = payload["result"]
        if command["command"] == "begin-group":
            _connections(value, targets[group["ordinal"]], before, after)
            group_started[group["ordinal"]] = uint(value["connections"][0]["started_nanos"])
            connections.append({"group": group["ordinal"], **value})
        elif command["command"] == "inventory":
            item = _inventory(value, group, command["barrier"], before, after)
            inventories[f"{group['ordinal']}/{command['barrier']}"] = item
        elif command["command"] == "phase":
            selected_phase = group["phases"][command["phase"]]
            count = selected_phase["offers"]
            selected = offered[offer_cursor:offer_cursor + count]
            phases.append(_phase(value, selected_phase, group, plan, targets[group["ordinal"]], owners,
                                 selected, base, before, after, pins))
            if first is not None:
                envelope, offset, line = selected[0]
                row = envelope["attempt"]
                response_time = uint(value["origin_session_nanos"]) + uint(row["completed_nanos"])
                expected = {"group": group["ordinal"], "phase": 0, "index": 0, "global_ordinal": base,
                            "target_index": 0, "owner_ref": envelope["owner_ref"], "app_process_id": envelope["app_process_id"],
                            "activation_id": row["activation_id"], "outcome": row["outcome"], "response_session_nanos": str(response_time)}
                _equal(first["payload"], expected, "docker-client-first-response-binding")
                require(response_time <= uint(first["session_elapsed_nanos"]) <= after
                        and prefixes[cursor - 1] == offset + len(line), "docker-client-first-response-prefix")
                first_responses.append(expected)
            offer_cursor += count
            base += count
        else:
            _equal(value, {"status": "passed", "channels_dropped": group["density"], "active_tasks": 0},
                   "docker-client-group-owners-live")
        require(after - group_started[group["ordinal"]] <= 300 * 10**9, "docker-client-group-deadline")
        expected_prefix = 0 if offer_cursor == 0 else offered[offer_cursor - 1][1] + len(offered[offer_cursor - 1][2])
        require(prefixes[cursor] == expected_prefix, "docker-client-barrier-attempt-prefix")
        before = after
        cursor += 1
    require(cursor == len(events) and offer_cursor == total, "docker-client-extra-events-or-offers")
    return {"schema": PREFIX + "derived.v1", "status": "complete", "plan_sha256": plan_digest, "process_id": process_id,
            "pair": plan["pair"], "profile": plan["profile"], "offers": str(total), "successful": str(total),
            "semantic_mismatches": "0", "outcomes": {"success": str(total)}, "management_calls": "9",
            "phases": phases, "inventories": inventories, "first_responses": first_responses, "connections": connections,
            "session_elapsed_nanos": str(end), "summary": summary}
