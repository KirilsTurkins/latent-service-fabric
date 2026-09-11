"""Replay every original offer in the five completed groups; no synthetic finish."""
from tools.optimization_docker import client_evidence as client, evidence as docker
from tools.optimization_evidence.common import decode, fields, read_json, require, sha256, uint
from .. import model


def _equal(actual, expected, suffix):
    docker.equal(actual, expected, "kubernetes-full01-prefix-" + suffix)


def _rows(path, maximum=1024**2, count=100):
    return client._lines(client._read(path, maximum), 256 * 1024, count)


def validate(root, suite, recovered, completed, checked, recovery_root):
    directory = recovery_root / "failure-outputs/2"
    raw_plan = client._read(directory / "plan.json", 4096)
    plan = decode(raw_plan, 4096)
    _equal(plan, {"schema": model.CLIENT_PREFIX + "plan.v1", "run_id": "full-01", "profile": "full",
                  "pair": 0, "token_file": "/fixtures/token"}, "plan")
    require(raw_plan == client._read(root / "clients/0/plan.json", 4096), "kubernetes-full01-client-plan-bytes")
    digest, groups = sha256(raw_plan), client._plan(plan)
    commands = [row[0] for row in _rows(root / "clients/0/parent-commands.ndjson")]
    acks = [row[0] for row in _rows(root / "clients/0/parent-acks.ndjson")]
    observations = [row[0] for row in _rows(root / "clients/0/parent-observations.ndjson")]
    expected = [item for item in client._sequence(groups) if item[1] is not None and item[1] < 5]
    require(len(commands) == len(expected), "kubernetes-full01-prefix-command-count")
    owners = {}
    for group in completed:
        for owner in group["owners"]:
            item = owner["parent"]
            targets = {target["service"]: target["endpoint"] for target in group["targets"] if target["owner_ref"] == item["owner_ref"]}
            value = {"app_process_id": item["app_process_id"], "container_id": item["container_id"],
                "endpoint": next(iter(targets.values())), "service_endpoints": targets,
                "arm": group["arm"], "density": group["density"], "group": group["group"]}
            if group["arm"] == "lsf":
                value["release_digests"] = {service: checked.fixture_releases[service]["release"] for service in targets}
            owners[item["owner_ref"]] = value
    parsed, receipts, targets, previous = [], [], {}, 0
    for ordinal, (parent, shape) in enumerate(zip(commands, expected)):
        fields(parent, "line sent_nanos")
        line = parent["line"].encode()
        require(line.endswith(b"\n") and line.count(b"\n") == 1 and previous <= uint(parent["sent_nanos"]),
                "kubernetes-full01-command-framing-clock")
        previous = uint(parent["sent_nanos"])
        command = fields(decode(line, 65536), client.COMMAND_FIELDS)
        _equal([command[k] for k in ("schema", "ordinal", "plan_sha256", "command", "group", "phase", "barrier")],
               [model.CLIENT_PREFIX + "command.v1", ordinal, digest, *shape], "command")
        if shape[0] == "begin-group":
            client._targets(command["targets"], groups[shape[1]], owners)
            _equal(command["targets"], completed[shape[1]]["targets"], "service-targets")
            targets[shape[1]] = command["targets"]
        else:
            require(command["targets"] is None, "kubernetes-full01-nontarget-command")
        parsed.append(command)
        receipts.append({"command": command, "command_bytes": str(len(line)), "command_sha256": sha256(line)})
    attempt_data = client._read(directory / "attempts.jsonl", 4 * 1024**2)
    offered = client._lines(attempt_data, 20 * 1024, 1500)
    events = _rows(directory / "events.jsonl")
    total = sum(phase["offers"] for group in groups[:5] for phase in group["phases"])
    require(len(offered) == total == 1130 and len(events) == len(acks) == len(commands) + 6,
            "kubernetes-full01-prefix-population")
    boundaries = {0, *(offset + len(line) for _, offset, line in offered)}
    prefixes, previous, clock, received = [], 0, 0, 0
    for ordinal, ((event, offset, line), parent) in enumerate(zip(events, acks)):
        fields(event, client.EVENT_FIELDS)
        fields(parent, "ack received_nanos")
        _equal([event[key] for key in ("schema", "event_ordinal", "process_id", "plan_sha256")],
               [model.CLIENT_PREFIX + "event.v1", ordinal, 1, digest], "event-identity")
        require(clock <= uint(event["session_elapsed_nanos"]) <= 1800 * 10**9 and received <= uint(parent["received_nanos"]),
                "kubernetes-full01-event-clock")
        clock, received = uint(event["session_elapsed_nanos"]), uint(parent["received_nanos"])
        ack = fields(parent["ack"], "schema event command_ordinal process_id plan_sha256 event_record attempts")
        _equal({key: ack[key] for key in ("schema", "event", "command_ordinal", "process_id", "plan_sha256")},
            {"schema": model.CLIENT_PREFIX + "ack.v1", **{key: event[key] for key in ("event", "command_ordinal", "process_id", "plan_sha256")}}, "ack")
        _equal(ack["event_record"], {"path": "events.jsonl", "offset": str(offset), "bytes": str(len(line)), "sha256": sha256(line)}, "event-reference")
        length = uint(ack["attempts"]["bytes"])
        require(previous <= length <= len(attempt_data) and length in boundaries, "kubernetes-full01-attempt-prefix")
        _equal(ack["attempts"], {"path": "attempts.jsonl", "bytes": str(length), "sha256": sha256(attempt_data[:length])}, "attempt-reference")
        previous = length
        prefixes.append(length)
        if event["command_ordinal"] is not None:
            require(uint(commands[event["command_ordinal"]]["sent_nanos"]) <= received, "kubernetes-full01-ack-before-command")
    ready = events[0][0]
    require(ready["event"] == "ready" and ready["command_ordinal"] is None and prefixes[0] == 0, "kubernetes-full01-ready-event")
    client._ready(ready["payload"], plan, groups, sum(phase["offers"] for group in groups for phase in group["phases"]))
    cursor, count, before, pins, inventories = 1, 0, uint(ready["session_elapsed_nanos"]), {}, {}
    for ordinal, command in enumerate(parsed):
        group = groups[command["group"]]
        first = None
        if command["command"] == "phase" and command["phase"] == 0:
            first = events[cursor][0]
            require(first["event"] == "first-response" and first["command_ordinal"] == ordinal, "kubernetes-full01-first-response-order")
            cursor += 1
        event = events[cursor][0]
        expected_event = {"begin-group": "group-ready", "inventory": "inventory", "phase": "phase-complete", "finish-group": "group-finished"}[command["command"]]
        require(event["event"] == expected_event and event["command_ordinal"] == ordinal, "kubernetes-full01-prefix-event-order")
        payload = fields(event["payload"], "command command_bytes command_sha256 result")
        _equal({key: payload[key] for key in payload if key != "result"}, receipts[ordinal], "original-command")
        value, after = payload["result"], uint(event["session_elapsed_nanos"])
        if command["command"] == "begin-group":
            client._connections(value, targets[group["ordinal"]], before, after)
        elif command["command"] == "inventory":
            inventories[f"{group['ordinal']}/{command['barrier']}"] = client._inventory(value, group, command["barrier"], before, after)
        elif command["command"] == "phase":
            phase = group["phases"][command["phase"]]
            selected = offered[count:count + phase["offers"]]
            client._phase(value, phase, group, plan, targets[group["ordinal"]], owners, selected, count, before, after, pins)
            if first is not None:
                envelope, offset, line = selected[0]
                attempt = envelope["attempt"]
                response = uint(value["origin_session_nanos"]) + uint(attempt["completed_nanos"])
                _equal(first["payload"], {"group": group["ordinal"], "phase": 0, "index": 0, "global_ordinal": count,
                    "target_index": 0, "owner_ref": envelope["owner_ref"], "app_process_id": envelope["app_process_id"],
                    "activation_id": attempt["activation_id"], "outcome": "success", "response_session_nanos": str(response)}, "first-response")
                require(response <= uint(first["session_elapsed_nanos"]) <= after and prefixes[cursor - 1] == offset + len(line),
                        "kubernetes-full01-first-response-prefix")
            count += phase["offers"]
        else:
            _equal(value, {"status": "passed", "channels_dropped": group["density"], "active_tasks": 0}, "group-finished")
        require(prefixes[cursor] == (offered[count - 1][1] + len(offered[count - 1][2]) if count else 0), "kubernetes-full01-prefix-boundary")
        if ordinal + 1 < len(commands):
            require(uint(acks[cursor]["received_nanos"]) <= uint(commands[ordinal + 1]["sent_nanos"]), "kubernetes-full01-overlapping-command")
        before, cursor = after, cursor + 1
    require(count == 1130 and cursor == len(events) and prefixes[-1] == len(attempt_data)
            and not (directory / "summary.json").exists(), "kubernetes-full01-no-invented-session-finish")
    attachment = read_json(root / "clients/0/attachment.json")
    _equal(suite["cleanup"]["attachments"], [attachment], "original-attachment")
    require(attachment["forced_kill"] is True and attachment["exit_code"] == -9 and attachment["failure"] is None
            and all(attachment[key] is True for key in ("reaped", "output_closed", "process_group_gone")),
            "kubernetes-full01-original-attachment-terminal")
    initial = client._read(root / "clients/0/initial-pod-stdout.log", 65536)
    stdout = client._read(root / "clients/0/attach-stdout.ndjson", 1024**2)
    stderr = client._read(root / "clients/0/attach-stderr.bin", 65536)
    _equal([row[0] for row in client._lines(initial + stdout, 65536, 100)], [row["ack"] for row in acks], "ack-stream")
    for key, raw in (("stdin", b"".join(row["line"].encode() for row in commands)), ("stdout", stdout), ("stderr", stderr)):
        _equal(attachment["streams"][key], {"bytes": str(len(raw)), "sha256": sha256(raw)}, "attach-stream-hash")
    require(not stderr, "kubernetes-full01-attach-stderr")
    require([row["stage"] for row in observations] == ["ready", *[f"group-{group}-{stage}" for group in range(5)
            for stage in ("ready", "served", "final")]], "kubernetes-full01-client-observation-order")
    candidates = [row["response_json"] for row in checked.journal["rows"] if row["raw"]["provider"] == "kubernetes"
                  and row["raw"]["method"] == "GET" and row["raw"]["path"] == f"/api/v1/namespaces/{suite['namespace']}/pods/client-p0"
                  and row["raw"]["status"] == 200 and row["response_json"]["status"].get("phase") == "Running"
                  and row["response_json"]["status"].get("containerStatuses", [{}])[0].get("ready") is True]
    require(candidates, "kubernetes-full01-client-ready-pod")
    for row in observations:
        checked.client_observation(row["observation"], candidates[0], row["stage"])
    parent = {"pair": 0, "commands": commands, "acknowledgements": acks, "observations": observations}
    checked.client_barriers(parent, completed, {"inventories": inventories})
    return {"offers": 1130, "completed_groups": 5, "completed_session": False}
