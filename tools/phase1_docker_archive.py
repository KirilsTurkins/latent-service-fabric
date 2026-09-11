"""Offline Docker publication replay with one shared build and two fixed populations.

The root aggregate belongs to run/ (full); smoke/aggregate.json belongs to smoke/.
Retained source files are evidence bytes and are never imported or executed.
"""
import base64
import binascii
import json
from pathlib import Path
import re

from tools import package_phase0_evidence as paths
from tools.optimization_docker import aggregate, evidence, model
from tools.optimization_evidence.common import (
    canonical, decode, fields, integer, read_json, require, sha256, text, uint, verify_artifact,
)


def _failed_journal(directory, started, finished):
    """Bind complete HTTP error responses too, without making them successes."""
    rows, previous, total = [], started, 0
    path = paths.existing_regular_file_path(directory / "engine.ndjson", "failed Docker journal")
    with path.open("rb") as stream:
        while line := stream.readline(24 * 1024**2 + 1):
            total += len(line)
            require(len(rows) < 20_000 and total <= model.MAX_FILE_BYTES
                    and len(line) <= 24 * 1024**2 and line.endswith(b"\n"), "docker-failed-journal-bound")
            row = fields(decode(line, 24 * 1024**2),
                         "ordinal method path request response receipt error response_bytes_base64")
            receipt = fields(row["receipt"], "method path begin_nanos end_nanos status request_bytes request_sha256 "
                             "response_bytes response_sha256 response_complete connection_closed failure")
            route = text(row["path"], 16384)
            require(integer(row["ordinal"]) == len(rows) and route.startswith("/") and not route.startswith("//")
                    and all(33 <= ord(c) <= 126 for c in route) and row["method"] in ("GET", "POST", "DELETE")
                    and receipt["method"] == row["method"]
                    and receipt["path"] == "/v" + evidence.API_VERSION + route, "docker-failed-api-identity")
            begin, end = uint(receipt["begin_nanos"]), uint(receipt["end_nanos"])
            require(previous <= begin <= end <= finished and end - begin <= 600 * 10**9
                    and receipt["response_complete"] is True and receipt["connection_closed"] is True,
                    "docker-failed-api-incomplete")
            previous = end
            encoded = text(row["response_bytes_base64"], 12 * 1024**2, empty=True)
            try:
                raw = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error) as error:
                raise ValueError("docker-failed-api-base64") from error
            require(len(raw) <= evidence.MAXIMUM_JSON and base64.b64encode(raw).decode() == encoded
                    and uint(receipt["response_bytes"]) == len(raw)
                    and receipt["response_sha256"] == sha256(raw), "docker-failed-api-response-bytes")
            status = integer(receipt["status"], 200, 599)
            if row["error"] is None:
                require(receipt["failure"] is None, "docker-failed-api-hidden-failure")
                evidence.equal(row["response"], decode(raw, evidence.MAXIMUM_JSON) if raw else None,
                               "docker-failed-api-response")
            else:
                require(row["error"] == "EngineError" and receipt["failure"] == "engine-http-status"
                        and status >= 400 and row["response"] is None, "docker-failed-api-error")
                if raw:
                    decode(raw, evidence.MAXIMUM_JSON)
            request = b"" if row["request"] is None else json.dumps(row["request"], ensure_ascii=False,
                         allow_nan=False, separators=(",", ":")).encode()
            require(len(request) <= evidence.MAXIMUM_JSON and uint(receipt["request_bytes"]) == len(request)
                    and receipt["request_sha256"] == sha256(request), "docker-failed-api-request-bytes")
            rows.append(row)
    require(rows, "docker-failed-empty-journal")
    return rows


def _failed_cleanup(rows, suite, cleanup):
    calls = evidence.Calls(rows)
    run, network = suite["run_id"], cleanup["network_id"]
    require(re.fullmatch(r"[a-z0-9-]{1,24}", text(run, 24)) is not None
            and re.fullmatch(r"[0-9a-f]{64}", text(network, 64)) is not None, "docker-failed-owner-identity")
    created, network_created = {}, None
    for row in rows:
        method, path = row["method"], row["path"]
        if method == "GET":
            require(row["request"] is None, "docker-failed-get-body")
            continue
        if path.startswith("/containers/create?"):
            config = row["request"]
            require(isinstance(config, dict), "docker-failed-container-config")
            labels = fields(config.get("Labels"), evidence.LABEL + " " + evidence.ROLE)
            role = labels[evidence.ROLE]
            require(role in ("seed-d1", "seed-d8", "seed-d32") and labels[evidence.LABEL] == run
                    and config.get("Image") == suite["images"]["lsf"]["image_id"]
                    and config.get("OpenStdin", False) is False
                    and path == "/containers/create?name=" + run + "-" + role
                    and method == "POST" and row["error"] is None and row["receipt"]["status"] == 201,
                    "docker-failed-workload-client-or-create")
            cid = text(row["response"]["Id"], 64)
            require(re.fullmatch(r"[0-9a-f]{64}", cid) is not None and cid not in created
                    and role not in [item[1] for item in created.values()]
                    and network_created is not None, "docker-failed-created-id")
            probe = calls.find("GET", "/containers/" + run + "-" + role + "/json", status=404)
            require(probe["ordinal"] < row["ordinal"], "docker-failed-container-name-probe")
            created[cid] = (row["ordinal"], role, config)
        elif path == "/networks/create":
            require(network_created is None and method == "POST" and row["error"] is None and row["receipt"]["status"] == 201
                    and row["response"]["Id"] == network
                    and row["request"]["Name"] == run + "-bridge"
                    and row["request"]["Labels"] == {evidence.LABEL: run, evidence.ROLE: "bridge"},
                    "docker-failed-network-create")
            probe = calls.find("GET", "/networks/" + run + "-bridge", status=404)
            require(probe["ordinal"] < row["ordinal"], "docker-failed-network-name-probe")
            network_created = row["ordinal"]
        elif path in ("/networks/" + network, "/networks/" + network + "/connect",
                      "/networks/" + network + "/disconnect"):
            require(method == ("DELETE" if path.endswith(network) else "POST"), "docker-failed-network-api")
        else:
            match = re.fullmatch(r"/containers/([0-9a-f]{64})(/start|/stop\?t=30|/wait\?condition=not-running|\?v=false&force=false)", path)
            require(match is not None and match[1] in created
                    and method == ("DELETE" if match[2].startswith("?") else "POST"),
                    "docker-failed-unowned-or-client-api")
    removals = cleanup["containers"]
    require(network_created is not None and isinstance(removals, list)
            and len(removals) == len(created) <= 3, "docker-failed-cleanup-population")
    seen, last_absence = set(), -1
    for item in removals:
        fields(item, "container_id name removed absence_call exit_code oom_killed")
        cid = item["container_id"]
        require(cid in created and cid not in seen and item["removed"] is True, "docker-failed-cleanup-id")
        seen.add(cid)
        begin, role, config = created[cid]
        require(item["name"] == "/" + run + "-" + role, "docker-failed-cleanup-name")
        deleted = calls.find("DELETE", "/containers/" + cid + "?v=false&force=false", after=begin, status=204)
        before = [row for row in rows[:deleted["ordinal"]] if row["method"] == "GET"
                  and row["path"] == "/containers/" + cid + "/json" and row["receipt"]["status"] == 200]
        require(before and before[-1]["ordinal"] > begin, "docker-failed-cleanup-inspect")
        observed = before[-1]["response"]
        require(observed["Id"] == cid and observed["Name"] == item["name"]
                and observed["Config"]["Labels"] == config["Labels"] and observed["Image"] == config["Image"]
                and observed["State"]["Running"] is False
                and type(item["exit_code"]) is int and observed["State"]["ExitCode"] == item["exit_code"]
                and type(item["oom_killed"]) is bool and observed["State"]["OOMKilled"] is item["oom_killed"],
                "docker-failed-cleanup-inspect-binding")
        absent = calls.at(item["absence_call"], "GET", "/containers/" + cid + "/json")
        require(absent["ordinal"] > deleted["ordinal"] and absent["error"] is None
                and absent["receipt"]["status"] == 404
                and not any(cid in row["path"] for row in rows[absent["ordinal"]+1:]),
                "docker-failed-container-absence")
        last_absence = max(last_absence, absent["ordinal"])
    deleted = calls.find("DELETE", "/networks/" + network, after=last_absence, status=204)
    before = [row for row in rows[:deleted["ordinal"]] if row["method"] == "GET"
              and row["path"] == "/networks/" + network and row["receipt"]["status"] == 200]
    require(before and before[-1]["ordinal"] > max(last_absence, network_created)
            and before[-1]["response"]["Id"] == network
            and before[-1]["response"]["Labels"] == {evidence.LABEL: run, evidence.ROLE: "bridge"}
            and before[-1]["response"]["Containers"] == {}, "docker-failed-network-empty-owner")
    absent = calls.find("GET", "/networks/" + network, after=deleted["ordinal"], status=404)
    require(absent["error"] is None and not any(network in row["path"] for row in rows[absent["ordinal"]+1:]),
            "docker-failed-network-absence")


def _failed_attempts(directory):
    root = directory / "attempts"
    if not root.exists() and not root.is_symlink():
        return None
    root = paths.existing_directory_path(root, "failed Docker attempts")
    index = fields(read_json(paths.existing_regular_file_path(root / "index.json", "failed attempt index"),
                             model.MAX_HELPER_BYTES), "schema attempts")
    require(index["schema"] == "latent.optimization.docker-failed-attempts.v1"
            and isinstance(index["attempts"], list) and 1 <= len(index["attempts"]) <= 8, "docker-failed-index")
    names = []
    for row in index["attempts"]:
        fields(row, "qualified directory suite cleanup failure workload_offers")
        name = text(row["directory"], 64)
        require(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", name) is not None
                and row["qualified"] is False and row["workload_offers"] == "0", "docker-failed-index-entry")
        names.append(name)
        attempt = paths.existing_directory_path(root / name, "failed Docker attempt")
        for key in ("suite", "cleanup"):
            fields(row[key], "path bytes sha256")
            require(row[key]["path"] == name + "/" + key + ".json", "docker-failed-index-reference")
            verify_artifact(root, row[key], 32 * 1024**2)
        suite = read_json(attempt / "suite.json", 32 * 1024**2)
        cleanup = fields(read_json(attempt / "cleanup.json"),
                         "schema containers network_id network_removed errors remaining_containers journal_closed pending_names")
        failure = fields(suite["failure"], "type reason")
        text(failure["type"], 128)
        text(failure["reason"], 2048)
        evidence.equal(row["failure"], failure, "docker-failed-index-failure")
        require(suite["schema"] == model.PREFIX + "suite.v1" and suite["profile"] == "smoke"
                and suite["clients"] == suite["groups"] == suite["failed_attachments"] == [], "docker-failed-client-ledger")
        clients = attempt / "clients"
        require(not clients.exists() or (not clients.is_symlink() and clients.is_dir() and not any(clients.iterdir())),
                "docker-failed-client-files")
        evidence.equal(suite["cleanup"], cleanup, "docker-failed-cleanup-sidecar")
        require(cleanup["schema"] == model.PREFIX + "cleanup.v1" and cleanup["network_removed"] is True
                and cleanup["journal_closed"] is True
                and cleanup["errors"] == cleanup["remaining_containers"] == cleanup["pending_names"] == [],
                "docker-failed-incomplete-cleanup")
        started, finished = uint(suite["started_nanos"]), uint(suite["finished_nanos"])
        require(started <= finished and finished-started <= 7200*10**9, "docker-failed-clock")
        _failed_cleanup(_failed_journal(attempt, started, finished), suite, cleanup)
    require(names == sorted(set(names)) and {entry.name for entry in root.iterdir()} == {"index.json", *names},
            "docker-failed-index-coverage")
    return index


def _replay(directory, build, aggregate_path, profile):
    paths.existing_regular_file_path(directory / "suite.json", "Docker suite")
    retained = read_json(paths.existing_regular_file_path(aggregate_path, "Docker aggregate"),
                         model.MAX_HELPER_BYTES)
    derived = evidence.validate(directory, build)
    require(derived.get("status") == "passed" and derived.get("profile") == profile,
            "docker-archive-campaign-profile")
    regenerated = aggregate.aggregate(derived)
    require(canonical(retained) == canonical(regenerated),
            "docker archive aggregate differs from replayed evidence")
    expected_plan = model.plan(profile)
    pairs = model.repetitions(profile)
    require(regenerated.get("schema") == aggregate.SCHEMA
            and regenerated.get("profile") == profile
            and regenerated.get("status") == "complete"
            and regenerated.get("completed_paired_run") is True
            and regenerated.get("full_population_completed") is (profile == "full")
            and regenerated.get("acceptance_qualified") is (profile == "full")
            and type(regenerated.get("validated_pairs")) is int
            and regenerated["validated_pairs"] == pairs
            and regenerated.get("logical_offers") == expected_plan["logical_offers"]
            and canonical(regenerated.get("plan")) == canonical(expected_plan),
            "docker archive requires complete full and smoke populations")
    counts = regenerated.get("counts")
    expected_counts = {
        "offers": expected_plan["logical_offers"], "successful": expected_plan["logical_offers"],
        "seed_management_rpcs": "88", "seed_invokes": "0",
        "measured_application_owners": str(44 * pairs), "client_owners": str(pairs),
        "all_containers_removed": str(45 * pairs + 3),
    }
    require(isinstance(counts, dict)
            and all(counts.get(key) == value for key, value in expected_counts.items()),
            "docker-archive-offer-and-owner-populations")
    return regenerated


def verify(directory: Path):
    """Replay both original campaigns against the same retained build closure."""
    directory = paths.existing_directory_path(Path(directory), "Docker archive evidence")
    build = paths.existing_directory_path(directory / "build", "Docker shared build")
    run = paths.existing_directory_path(directory / "run", "Docker full campaign")
    smoke = paths.existing_directory_path(directory / "smoke", "Docker smoke campaign")
    full = _replay(run, build, directory / "aggregate.json", "full")
    checked_smoke = _replay(smoke, build, smoke / "aggregate.json", "smoke")
    # Each replay already binds executable/fixture bytes to this build directory.
    # Compare the resulting identities too; collector Python commits can differ
    # while their separately retained controls and unchanged binary inputs bind.
    for key in ("build_source", "images"):
        require(key in full and key in checked_smoke
                and canonical(full[key]) == canonical(checked_smoke[key]),
                "docker-archive-crossed-build-or-images")
    result = {"full": full, "smoke": checked_smoke}
    failed = _failed_attempts(directory)
    if failed is not None:
        result["failed_attempts"] = failed
    return result
