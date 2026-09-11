"""The observed smoke02 prefix and inline cleanup, never a qualified session."""
from __future__ import annotations

from pathlib import PurePosixPath

from tools.optimization_docker import build, client_evidence as client, evidence as docker
from tools.optimization_evidence.common import canonical, decode, fields, integer, read_json, require, sha256, uint, verify_artifact
from . import bootstrap_evidence, evidence, failure_evidence as failed, model, replay, services, transport_evidence as transport

REASON = "kubernetes-inline-failure-"
SOURCE = "7a655e7967dbde1431f0ff8a5b928443a5986832"


def _same(actual, expected, label):
    require(canonical(actual) == canonical(expected), REASON + label)


def client_prefix(root, parent, owners):
    """Validate all original 30 offers and the failed connection after group0."""
    directory = root / "failure-outputs/2"
    plan_data = client._read(directory / "plan.json", 4096)
    plan = decode(plan_data, 4096)
    _same(plan, parent["plan"], "client-plan")
    digest = sha256(plan_data)
    groups, sequence = client._plan(plan), client._sequence(client._plan(plan))
    commands, acks = parent["commands"], parent["acknowledgements"]
    require(len(commands) == 16 and len(acks) == 18, REASON + "client-prefix-count")
    parsed, receipts, targets, sent = [], [], {}, 0
    for index, row in enumerate(commands):
        fields(row, "line sent_nanos")
        line = row["line"].encode()
        require(len(line) <= 65536 and line.endswith(b"\n") and line.count(b"\n") == 1
                and sent <= uint(row["sent_nanos"]), REASON + "command-framing")
        sent = uint(row["sent_nanos"])
        value = fields(decode(line, 65536), client.COMMAND_FIELDS)
        _same([value[key] for key in ("schema", "ordinal", "plan_sha256", "command", "group", "phase", "barrier")],
              [model.CLIENT_PREFIX + "command.v1", index, digest, *sequence[index]], "command-order")
        if value["command"] == "begin-group":
            client._targets(value["targets"], groups[value["group"]], owners)
            targets[value["group"]] = value["targets"]
        else:
            require(value["targets"] is None, REASON + "command-targets")
        parsed.append(value)
        receipts.append({"command": value, "command_bytes": str(len(line)), "command_sha256": sha256(line)})
    attempt_data = client._read(directory / "attempts.jsonl", 1024**2)
    event_data = client._read(directory / "events.jsonl", 1024**2)
    offered, events = client._lines(attempt_data, 20 * 1024, 30), client._lines(event_data, 128 * 1024, 18)
    require(len(offered) == 30 and len(events) == 18, REASON + "raw-population")
    summary = read_json(directory / "summary.json", 16384)
    expected_summary = {"schema": model.CLIENT_PREFIX + "summary.v1", "status": "failed", "reason": "session-connect-failed",
        "plan_sha256": digest, "process_id": 1, "commands_completed": "15", "groups_completed": "1",
        "phases_completed": "9", "offers": "30", "management_calls": "3", "active_tasks_at_completion": 0,
        "channels_at_completion": 0, "runtime_dropped": True, "finish_command": None,
        "attempts": {"path": "attempts.jsonl", "bytes": str(len(attempt_data)), "sha256": sha256(attempt_data)},
        "session_elapsed_nanos": summary.get("session_elapsed_nanos")}
    _same(summary, expected_summary, "failed-summary")
    end = uint(summary["session_elapsed_nanos"])
    require(end <= 1800 * 10**9, REASON + "client-clock")
    previous = prefix = received = 0
    prefixes = []
    boundaries = {0, *(offset + len(line) for _, offset, line in offered)}
    for ordinal, ((event, offset, line), ack_parent) in enumerate(zip(events, acks)):
        fields(event, client.EVENT_FIELDS)
        _same([event[key] for key in ("schema", "event_ordinal", "process_id", "plan_sha256")],
              [model.CLIENT_PREFIX + "event.v1", ordinal, 1, digest], "event-identity")
        require(previous <= uint(event["session_elapsed_nanos"]) <= end, REASON + "event-clock")
        previous = uint(event["session_elapsed_nanos"])
        fields(ack_parent, "ack received_nanos")
        ack = fields(ack_parent["ack"], "schema event command_ordinal process_id plan_sha256 event_record attempts")
        _same({key: ack[key] for key in ("schema", "event", "command_ordinal", "process_id", "plan_sha256")},
            {"schema": model.CLIENT_PREFIX + "ack.v1", **{key: event[key] for key in
             ("event", "command_ordinal", "process_id", "plan_sha256")}}, "ack-event")
        _same(ack["event_record"], {"path": "events.jsonl", "offset": str(offset), "bytes": str(len(line)),
                                   "sha256": sha256(line)}, "ack-original-event")
        current = uint(ack["attempts"]["bytes"])
        require(prefix <= current <= len(attempt_data) and current in boundaries, REASON + "attempt-prefix")
        _same(ack["attempts"], {"path": "attempts.jsonl", "bytes": str(current),
                               "sha256": sha256(attempt_data[:current])}, "attempt-prefix-hash")
        prefix = current
        prefixes.append(current)
        require(received <= uint(ack_parent["received_nanos"]), REASON + "ack-clock")
        received = uint(ack_parent["received_nanos"])
        command = event["command_ordinal"]
        if command is not None:
            integer(command, 0, 15)
            require(uint(commands[command]["sent_nanos"]) <= received, REASON + "ack-before-command")
    require(prefix == len(attempt_data) and events[0][0]["event"] == "ready"
            and events[0][0]["command_ordinal"] is None and prefixes[0] == 0, REASON + "ready-event")
    client._ready(events[0][0]["payload"], plan, groups, 300)
    require(uint(acks[0]["received_nanos"]) <= uint(commands[0]["sent_nanos"]), REASON + "ready-before-command")
    cursor, count, before, pins, phases, inventories = 1, 0, uint(events[0][0]["session_elapsed_nanos"]), {}, [], {}
    for ordinal, command in enumerate(parsed[:14]):
        first = None
        if command["command"] == "phase" and command["phase"] == 0:
            first = events[cursor][0]
            require(first["event"] == "first-response" and first["command_ordinal"] == ordinal, REASON + "first-response")
            cursor += 1
        event = events[cursor][0]
        expected = {"begin-group": "group-ready", "inventory": "inventory", "phase": "phase-complete", "finish-group": "group-finished"}
        require(event["event"] == expected[command["command"]] and event["command_ordinal"] == ordinal, REASON + "event-order")
        payload = fields(event["payload"], "command command_bytes command_sha256 result")
        _same({key: payload[key] for key in payload if key != "result"}, receipts[ordinal], "event-command-bytes")
        value, after, group = payload["result"], uint(event["session_elapsed_nanos"]), groups[0]
        if command["command"] == "begin-group":
            client._connections(value, targets[0], before, after)
        elif command["command"] == "inventory":
            inventories["0/" + command["barrier"]] = client._inventory(value, group, command["barrier"], before, after)
        elif command["command"] == "phase":
            phase = group["phases"][command["phase"]]
            selected = offered[count:count + phase["offers"]]
            phases.append(client._phase(value, phase, group, plan, targets[0], owners, selected, count, before, after, pins))
            if first is not None:
                envelope, offset, line = selected[0]
                row = envelope["attempt"]
                response = uint(value["origin_session_nanos"]) + uint(row["completed_nanos"])
                _same(first["payload"], {"group": 0, "phase": 0, "index": 0, "global_ordinal": 0, "target_index": 0,
                    "owner_ref": envelope["owner_ref"], "app_process_id": envelope["app_process_id"],
                    "activation_id": row["activation_id"], "outcome": "success", "response_session_nanos": str(response)}, "first-response-binding")
                require(response <= uint(first["session_elapsed_nanos"]) <= after and prefixes[cursor - 1] == offset + len(line),
                        REASON + "first-response-prefix")
            count += phase["offers"]
        else:
            _same(value, {"status": "passed", "channels_dropped": 1, "active_tasks": 0}, "group-complete")
        require(prefixes[cursor] == (0 if count == 0 else offered[count - 1][1] + len(offered[count - 1][2])), REASON + "phase-prefix")
        require(uint(acks[cursor]["received_nanos"]) <= uint(commands[ordinal + 1]["sent_nanos"]), REASON + "overlapping-command")
        before, cursor = after, cursor + 1
    require(count == 30 and cursor == 16, REASON + "complete-group-count")
    event = events[16][0]
    require(event["event"] == "group-ready" and event["command_ordinal"] == 14, REASON + "failed-connect-event")
    payload = fields(event["payload"], "command command_bytes command_sha256 result")
    _same({key: payload[key] for key in payload if key != "result"}, receipts[14], "failed-connect-command")
    value = fields(payload["result"], "status reason connections independent_channels")
    require(value["status"] == "failed" and value["reason"] == "session-connect-failed" and value["independent_channels"] == 0
            and len(value["connections"]) == 1, REASON + "failed-connect-result")
    connection = value["connections"][0]
    _same({key: val for key, val in connection.items() if key not in ("started_nanos", "finished_nanos")},
          {**{key: targets[1][0][key] for key in ("endpoint", "owner_ref", "app_process_id")},
           "target_index": 0, "status": "failed", "reason": "session-connect-failed"}, "failed-connect-target")
    require(before <= uint(connection["started_nanos"]) <= uint(connection["finished_nanos"])
            <= uint(event["session_elapsed_nanos"]) and uint(acks[16]["received_nanos"]) <= uint(commands[15]["sent_nanos"]),
            REASON + "failed-connect-clock")
    last = events[17][0]
    require(last["event"] == "failed" and last["command_ordinal"] == 15 and prefixes[16:] == [len(attempt_data)] * 2,
            REASON + "terminal-failed-event")
    _same(last["payload"], {"active_tasks": 0, "channels": 0, "offers": "30", "reason": "session-connect-failed",
                            "runtime_dropped": True}, "terminal-client-cleanup")
    return {"offers": "30", "phases": phases, "inventories": inventories, "targets": targets, "summary": summary}


def _transfers(root, suite, checked, build_root):
    expected = ["fixtures", "tools", "clients/0", "owners/p0-g0-lsf-0", "data/p0-g0-lsf-0", "owners/p0-g1-native-0"]
    require([row["relative"] for row in suite["preparations"]] == expected, REASON + "preparation-order")
    for row in suite["preparations"]:
        destination = model.host_path(suite["owner"], suite["run_id"], row["relative"])
        require(row["destination"] == destination, REASON + "preparation-owner")
        checked.command(row["create_call"] - 1, ["mkdir", "-p", str(PurePosixPath(destination).parent)])
        checked.command(row["create_call"], ["mkdir", "-m", "700", destination])
        if row["upload_call"] is None:
            require(row["relative"].startswith("owners/") and row.get("transfer") is None, REASON + "empty-preparation")
            continue
        transfer = row["transfer"]
        transport._inventory(transfer["inventory"])
        original = verify_artifact(root, row["archive"], transport.MAX_TRANSFER)
        replay._tar(original, transfer["inventory"])
        call = checked.call(row["upload_call"], provider="docker", operation="worker-upload")
        require(call["raw"]["destination"] == destination and call["archive"] ==
                {key: row["archive"][key] for key in ("bytes", "sha256")}
                and row["archive"]["bytes"] == transfer["archive_bytes"]
                and row["archive"]["sha256"] == transfer["archive_sha256"], REASON + "upload-binding")
        if row["relative"] == "fixtures":
            docker.inventory(build_root / "fixtures", transfer["inventory"])
        elif row["relative"] == "tools":
            observer = suite["collector_inputs"]["tools/optimization_kubernetes/observer.sh"]
            files = [item for item in transfer["inventory"]["entries"] if item["kind"] == "file"]
            require(len(files) == 1 and files[0]["path"] == "observer.sh"
                    and all(files[0][key] == observer[key] for key in ("bytes", "sha256")), REASON + "observer-source")
        elif row["relative"].startswith("data/"):
            _same(transfer["inventory"], checked.seeds[1]["template"]["inventory"], "seed-input")
        else:
            plan = client._read(root / "clients/0/plan.json", 4096)
            files = [item for item in transfer["inventory"]["entries"] if item["kind"] == "file"]
            _same(files, [{"path": "plan.json", "kind": "file", "mode": "0644", "bytes": str(len(plan)),
                           "sha256": sha256(plan)}], "uploaded-client-plan")
    require(len(suite["transfers"]) == 3 and suite["cleanup"]["failure_diagnostics"] == suite["transfers"][1:], REASON + "downloads")
    expected_downloads = [("owners/p0-g0-lsf-0/raw", "owners/p0-g0-lsf-0"),
                          ("failure-outputs/2", "clients/0"), ("failure-outputs/5", "owners/p0-g1-native-0")]
    for row, (local, suffix) in zip(suite["transfers"], expected_downloads):
        require(row["local"] == local and row["remote"] == model.host_path(suite["owner"], suite["run_id"], suffix),
                REASON + "download-path")
        checked.downloaded(row, row["remote"], row["local"])
        replay._tar(verify_artifact(root, row["archive"], transport.MAX_TRANSFER), row["inventory"],
                    root_name=PurePosixPath(row["remote"]).name)


def _cleanup(root, suite, checked, pods):
    value = suite["cleanup"]
    require(value["errors"] == [] and value["remaining_pods"] == {} and value["namespace_absent"] is True
            and value["remote_removed"] is True and value["private_tls_removed"] is True, REASON + "cleanup-incomplete")
    _same(read_json(root / "cleanup.json"), value, "cleanup-sidecar")
    require({row["name"]: row["uid"] for row in value["pods"]} == pods and len(value["pods"]) == 3, REASON + "cleanup-pods")
    base = "/api/v1/namespaces/" + suite["namespace"]
    for row in value["pods"]:
        grace = 0 if row["name"] == "p0-g0-lsf-0" else 40
        body = {"apiVersion": "v1", "kind": "DeleteOptions", "preconditions": {"uid": row["uid"]},
                "gracePeriodSeconds": grace, "propagationPolicy": "Background"}
        checked.api(row["call"], "DELETE", base + "/pods/" + row["name"], body=body)
        checked.api(row["absence_call"], "GET", base + "/pods/" + row["name"], status=404)
    namespace_delete = []
    for index in value["namespace_calls"]:
        selected = checked.call(index, provider="kubernetes")
        raw = selected["raw"]
        require(raw["path"] in (base, base + "/pods"), REASON + "cleanup-namespace-path")
        if raw["method"] == "DELETE":
            _same(selected["request_json"], {"apiVersion": "v1", "kind": "DeleteOptions",
                "preconditions": {"uid": suite["namespace_uid"]}, "propagationPolicy": "Foreground"}, "namespace-delete")
            namespace_delete.append(index)
        elif raw["status"] == 200 and raw["path"] == base:
            failed._namespace(selected["response_json"], suite)
        elif raw["status"] == 200:
            failed._pod_list(selected["response_json"], suite, {key: val for key, val in pods.items() if key != "p0-g0-lsf-0"})
    require(len(namespace_delete) == 1 and checked.journal["rows"][value["namespace_calls"][-1]]["raw"]["status"] == 404,
            REASON + "namespace-absence")
    calls = failed._Calls(checked.journal)
    ordinal = failed._runtime(calls, value, suite, pods, value["cri_calls"][0])
    checked.used.update(calls.used)
    require(ordinal == value["failure_diagnostics"][0]["call"], REASON + "post-runtime-download-order")
    script = ('set -eu; p="$1"; [ "$(readlink -f -- "$p")" = "$p" ]; '
              '[ ! -L "$p" ]; if [ -d "$p" ]; then rm -rf --one-file-system -- "$p"; fi; [ ! -e "$p" ]')
    checked.command(value["remote_remove_call"], ["sh", "-c", script, "owned-cleanup", model.host_path(suite["owner"], suite["run_id"])])


def _prefix_owner(item, target, group, fixture_releases):
    value = {"app_process_id": item["app_process_id"], "endpoint": target["endpoint"], "arm": item["arm"],
             "density": 1, "group": group, "container_id": item["container_id"]}
    if group == 0:
        value["release_digests"] = {model.SERVICES[0]: fixture_releases[model.SERVICES[0]]["release"]}
    return value


def _finish(root, suite, boot, checked, complete, build_root):
    parent = read_json(root / "clients/0/failure.json", 1024**2)
    require(parent["failure"] == "EvidenceError: kubernetes-client-ack-order-identity" and parent["pair"] == 0,
            REASON + "parent-failure")
    for key, name in (("commands", "parent-commands.ndjson"), ("acknowledgements", "parent-acks.ndjson"),
                      ("observations", "parent-observations.ndjson")):
        rows = client._lines(client._read(root / "clients/0" / name, 1024**2), 128 * 1024, 32)
        _same([row[0] for row in rows], parent[key], "parent-journal")
    progress = client._lines(client._read(root / "progress.ndjson", 4 * 1024**2), 256 * 1024, 64)
    previous, native = uint(suite["started_nanos"]), None
    for ordinal, (row, _, _) in enumerate(progress):
        fields(row, "ordinal kind observed_nanos value")
        require(row["ordinal"] == ordinal and previous <= uint(row["observed_nanos"]) <= uint(suite["finished_nanos"]),
                REASON + "progress-order")
        previous = uint(row["observed_nanos"])
        if row["kind"] == "application-ready" and row["value"].get("role") == "p0-g1-native-0":
            require(native is None, REASON + "duplicate-native")
            native = row["value"]
    require(native is not None, REASON + "missing-native")
    base, remote = "/api/v1/namespaces/" + suite["namespace"], model.host_path(suite["owner"], suite["run_id"])
    checked.call(0, provider="docker", operation="worker-identity")
    checked.command(suite["remote_create_call"], ["mkdir", "-m", "700", remote])
    checked.api(suite["namespace_absence_call"], "GET", base, status=404)
    checked.api(suite["namespace_create_call"], "POST", "/api/v1/namespaces", body=model.namespace(suite["owner"], suite["run_id"]),
                response=suite["namespace_create"], status=201)
    failed._namespace(suite["namespace_create"], suite)
    _transfers(root, suite, checked, build_root)
    pods = {}
    for item, arm, role, output in ((parent, "client", "client-p0", remote + "/clients/0"),
                                   (native, "native", "p0-g1-native-0", remote + "/owners/p0-g1-native-0")):
        command = (["--session", "/output/plan.json", "--output", "/output"] if arm == "client" else
            ["--app", "native", "--executable", "/opt/lsf/optimization-native", "--output", "/output",
             "--token-file", "/fixtures/token", "--service", model.SERVICES[0]])
        manifest = model.pod(boot["images"][arm]["tag"], command, arm=arm, density=1, owner=suite["owner"],
            run_id=suite["run_id"], role=role, fixtures=remote + "/fixtures", output=output)
        _same(item["manifest"], manifest, "partial-pod-manifest")
        checked.created(item["create"], manifest)
        uid = item["create"]["pod"]["metadata"]["uid"]
        pods[role] = uid
        ready = item["ready"]["pod"] if arm == "client" else item["pod_ready"]
        call = item["ready"]["call"] if arm == "client" else item["ready_call"]
        failed._pod(ready, suite, role, uid)
        checked.api(call, "GET", base + "/pods/" + role, response=ready, status=200)
    complete_parent = complete["owners"][0]["parent"]
    pods[complete_parent["role"]] = complete_parent["create"]["pod"]["metadata"]["uid"]
    _same(parent["manifest"], read_json(root / "clients/0/manifest.json"), "client-manifest-sidecar")
    log = parent["initial_log"]
    raw = verify_artifact(root, {key: log[key] for key in ("path", "bytes", "sha256")}, 1024**2).read_bytes()
    require(log["calls"] == [log["call"]] and parent["initial_log_calls"] == log["calls"], REASON + "initial-log-calls")
    require(checked.api(log["call"], "GET", base + "/pods/client-p0/log?container=client", status=200)["response_bytes"] == raw,
            REASON + "initial-ack-bytes")
    require([row["stage"] for row in parent["observations"]] == ["ready", "group-0-ready", "group-0-served", "group-0-final"],
            REASON + "client-observation-count")
    for row in parent["observations"]:
        checked.client_observation(row["observation"], parent["ready"]["pod"], row["stage"])
    attach = parent["attach"]
    _same(read_json(root / "clients/0/attachment.json"), attach, "attachment-sidecar")
    _same(suite["cleanup"]["attachments"], [attach], "attachment-cleanup")
    expected_argv = [boot["output"] + "/tools/kubectl", "--kubeconfig", boot["output"] + "/private/kubeconfig",
        "--context", "kind-" + suite["owner"], "--server", "https://" + suite["owner"] + "-control-plane:6443",
        "-n", suite["namespace"], "attach", "-i", "client-p0", "-c", "client", "--quiet=true"]
    require(attach["argv"] == expected_argv and attach["failure"] is None and attach["exit_code"] == -9
            and all(attach[key] is True for key in ("forced_kill", "reaped", "process_group_gone", "output_closed"))
            and attach["descendant_reaps"] == [] and attach["subreaper"] == {"enabled": True, "previous": 0, "restored": True},
            REASON + "attach-closure")
    integer(attach["process_id"], 1)
    require(uint(attach["start_time_ticks"]) > 0, REASON + "attach-identity")
    stdout = client._read(root / "clients/0/attach-stdout.ndjson", 1024**2)
    stderr = client._read(root / "clients/0/attach-stderr.bin", 262144)
    stdin = b"".join(row["line"].encode() for row in parent["commands"])
    _same(attach["streams"], {key: {"bytes": str(len(data)), "sha256": sha256(data)}
                              for key, data in (("stdin", stdin), ("stdout", stdout), ("stderr", stderr))}, "attach-streams")
    require(stderr == b"", REASON + "attach-stderr")
    original_acks = client._lines(raw + stdout, 4096, 18)
    _same([row[0] for row in original_acks], [row["ack"] for row in parent["acknowledgements"]], "ack-original-stream")
    require(uint(parent["acknowledgements"][0]["received_nanos"]) <= uint(attach["started_nanos"])
            <= uint(parent["commands"][0]["sent_nanos"])
            <= uint(parent["acknowledgements"][-1]["received_nanos"]) <= uint(attach["finished_nanos"])
            <= uint(suite["cleanup"]["started_nanos"]), REASON + "attach-window")
    # The second owner reached wrapper/EndpointSlice readiness but no RPC Invoke.
    container = native["container_id"]
    transport._id(container)
    require(native["owner_ref"] == "owner-" + container and native["remote_output"] == remote + "/owners/p0-g1-native-0",
            REASON + "native-owner")
    checked.command(native["cri_ready_call"], ["crictl", "inspect", container], response=native["cri_ready"])
    evidence._image(native["pod_ready"], native["cri_ready"], "native", boot)
    pid = integer(native["cri_ready"]["info"]["pid"], 1)
    proc = checked.command(native["identity_call"], ["cat", f"/proc/{pid}/stat"])
    require(evidence.wrapper._stat(proc["stdout"].decode(), pid)[0] == native["start_time_ticks"], REASON + "native-process")
    native_files = root / "failure-outputs/5"
    lifecycle = evidence.wrapper.validate_observations(native_files, arm="native", density=1, container_id=container,
        identity={"pod_uid": pods["p0-g1-native-0"]}, controls=model.resources("native", 1), expected_snapshots=0,
        expected_connections=1)
    require(lifecycle["identity"]["child_pid"] == native["app_process_id"], REASON + "native-child")
    events = client._lines(client._read(native_files / "events.ndjson", 16384), 8192, 3)
    initial = checked.command(native["identity_call"] - 1, ["tail", "-c", "+1", native["remote_output"] + "/events.ndjson"])
    require(initial["stdout"] == events[0][2] + events[1][2], REASON + "native-startup-bytes")
    pod_call, service_call, slice_call = native["identity_call"] + 1, native["identity_call"] + 2, native["identity_call"] + 3
    pod_rows = services.list_items(checked.api(pod_call, "GET", base + "/pods", status=200)["response_json"], "Pod")
    service_rows = services.list_items(checked.api(service_call, "GET", base + "/services", status=200)["response_json"], "Service")
    slice_rows = services.list_items(checked.api(slice_call, "GET", "/apis/discovery.k8s.io/v1/namespaces/" + suite["namespace"] + "/endpointslices",
                                                status=200)["response_json"], "EndpointSlice")
    desired_service = model.service(owner=suite["owner"], run_id=suite["run_id"], pair=0, group=1, arm="native", density=1, index=0)
    service = checked.api(native["create"]["call"] - 1, "POST", base + "/services", body=desired_service, status=201)["response_json"]
    services.subset(service, desired_service)
    active_services = {service["metadata"]["name"]: service["metadata"]["uid"]}
    slices = evidence._current_slices(slice_rows, active_services, {**checked.created_services, **active_services},
        owner=suite["owner"], run_id=suite["run_id"], embedded_items=True)
    graph = services.graph(service_rows, slices, [row for row in pod_rows if row["metadata"]["name"] == "p0-g1-native-0"],
        owner=suite["owner"], run_id=suite["run_id"], pair=0, group=1, arm="native", density=1,
        worker_name=boot["nodes"]["worker"]["name"], embedded_items=True)
    native_target = [{"service": row["service"], "endpoint": row["endpoint"], "owner_ref": native["owner_ref"],
                      "app_process_id": native["app_process_id"]} for row in graph["targets"]]
    owners = {}
    for group, item, targets in ((0, complete_parent, complete["targets"]), (1, native, native_target)):
        owners[item["owner_ref"]] = _prefix_owner(item, targets[0], group, checked.fixture_releases)
    prefix = client_prefix(root, parent, owners)
    _same(prefix["targets"][0], complete["targets"], "first-group-targets")
    _same(prefix["targets"][1], native_target, "failed-native-service-targets")
    checked.client_barriers(parent, [complete], prefix, require_proxy=False)
    for row in suite["background"]:
        for observation in row["observations"]:
            call = checked.call(observation["call"], provider="docker", operation="node-stats", role=observation["role"])
            _same(call["response_json"], observation["stats"], "background-bytes")
            require(observation["container_id"] == boot["nodes"][observation["role"]]["container_id"], REASON + "background-owner")
    _cleanup(root, suite, checked, pods)
    # All remaining calls must be identity-stable Pod polling, never an
    # unrecognized command, additional operation, or hidden Invoke.
    for index, call in enumerate(checked.journal["rows"]):
        if index in checked.used:
            continue
        raw = call["raw"]
        require(raw["provider"] == "kubernetes" and raw["method"] == "GET"
                and raw["path"].startswith(base + "/pods/"), REASON + "unconsumed-operation")
        name = raw["path"].removeprefix(base + "/pods/")
        require(name in pods and raw["status"] == 200, REASON + "unconsumed-poll")
        failed._pod(call["response_json"], suite, name, pods[name])
        checked.call(index, provider="kubernetes", method="GET", path=raw["path"], status=200)
    require(checked.used == set(range(210)), REASON + "unconsumed-calls")
    return suite


def validate(root, bootstrap_root, build_root, docker_root):
    suite = read_json(root / "suite.json", 8 * 1024**2)
    require(suite["schema"] == model.PREFIX + "suite.v1" and suite["source"]["commit"] == SOURCE
            and suite["profile"] == "smoke" and suite["run_id"] == "smoke-02"
            and suite["failure"] == {"type": "EvidenceError", "reason": "kubernetes-client-ack-order-identity"}
            and suite["source_after"] is None and len(suite["groups"]) == 1 and suite["clients"] == [], REASON + "unsupported")
    require(not (root / "recovery.json").exists() and not (root / "recovery.json").is_symlink(), REASON + "fabricated-recovery")
    boot = bootstrap_evidence.validate(bootstrap_root)
    verify_artifact(bootstrap_root, suite["bootstrap"], 8 * 1024**2)
    built = build.validate_receipt(read_json(verify_artifact(build_root, suite["build_receipt"], 16 * 1024**2)), build_root)
    verify_artifact(docker_root, suite["docker_suite"], 32 * 1024**2)
    require(suite["build_source"] == built["source"] and suite["owner"] == boot["owner"]
            and suite["images"] == {key: row["tag"] for key, row in boot["images"].items()}
            and suite["plan"] == model.plan("smoke", owner=boot["owner"]), REASON + "input-binding")
    require(suite["collection_path"] == boot["output"] + "/smoke-02"
            and suite["bootstrap_path"] == boot["output"] + "/bootstrap.json", REASON + "original-path")
    _same(read_json(root / "plan.json"), suite["plan"], "plan-sidecar")
    times = list(map(uint, [boot["finished_nanos"], suite["started_nanos"], suite["cleanup"]["started_nanos"],
                           suite["cleanup"]["finished_nanos"], suite["finished_nanos"]]))
    require(times == sorted(times) and times[-1] - times[1] <= 7200 * 10**9, REASON + "campaign-clock")
    docker.source(suite["source"])
    require(1 <= len(suite["collector_inputs"]) <= 3500, REASON + "source-count")
    require({"tools/optimization_kubernetes/" + name for name in
             ("collect.py", "services.py", "transport.py", "session.py", "attach.py", "observer.sh")} <= suite["collector_inputs"].keys(),
            REASON + "source-closure")
    for name, ref in suite["collector_inputs"].items():
        require(ref["path"] == "collector/source/" + name and name.startswith("tools/"), REASON + "source-path")
        verify_artifact(root, ref, 16 * 1024**2)
    expected_inputs = {name: {key: row[key] for key in ("bytes", "sha256")}
                       for name, row in built["inputs"].items() if not name.endswith(".py")}
    _same(suite["build_inputs"], expected_inputs, "binary-inputs")
    require(suite["source"]["cargo_lock_sha256"] == expected_inputs["Cargo.lock"]["sha256"], REASON + "source-lock")
    require((root / "api.ndjson").stat().st_size <= 16 * 1024**2, REASON + "journal-bound")
    journal = transport.validate(root / "api.ndjson", worker_container_id=boot["nodes"]["worker"]["container_id"],
        node_container_ids={key: row["container_id"] for key, row in boot["nodes"].items()},
        started_nanos=suite["started_nanos"], finished_nanos=suite["finished_nanos"])
    require(len(journal["rows"]) == 210, REASON + "call-count")
    checked = evidence.Replay(root, suite, journal, boot, built, build_root, docker_root)
    complete = checked.group(suite["groups"][0], 0, model.groups("smoke", 0)[0], require_proxy=False)
    return _finish(root, suite, boot, checked, complete, build_root)
