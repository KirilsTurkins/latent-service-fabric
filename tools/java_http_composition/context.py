"""Actual operator-authorized lineage and admitted grants for the Java fixture."""
from copy import deepcopy
from pathlib import Path
import time

from tools.java_http_composition.node import ADAPTER, CHILD_SUBJECT, CONTEXT_REQUIRED, decoded, idle, invoke, request, web_request, rebind, route
from tools.phase2_operator_process import require, read_json, write_json
from tools.run_rust_capsule_workflow import write_workflow_receipt
from tools.static_api.node import policy


def ordinary_import(client, targets, releases, publications, host):
    """Actual signed Java import, with its clocks installed and granted first."""
    descriptor = read_json(releases / "java-http-context-required/deployment.json")
    descriptor["spec"]["publication"] = publications["context-required"]
    descriptor["spec"]["grants"] = targets["domain"]["grants"]
    source = client.directory / "context-required-deployment.json"
    write_json(source, descriptor)
    applied = client.call("deployment", "apply", source, "--operation-id", "java-context-required-deploy",
                          "--expected-generation", 0, codes=(0, 4))
    result = {"publication": publications["context-required"], "deployment": applied,
              "contextInstallationProfile": "ordinary-installed-clocks-and-local-service-v1"}
    if applied["category"] == "success":
        invocation_targets = {**targets, "context-required": {
            "name": "java-http-context-required", "budget": targets["domain"]["budget"]}}
        denied = invoke(client, invocation_targets, "context-required", "status", [], "java-context-required", codes=(4,))
        result.update(stage="invocation", invocation=denied, tree=tree(client, "java-context-required"))
    else:
        denied = applied
        result["stage"] = "deployment"
    require(denied["category"] == "platform-failure" and denied["error"]["code"] in (
        "permission-denied", "incompatible-contract", "invalid-argument"), "java-context-ordinary-missing-binding-category")
    require(denied["outcomeKnown"], "java-context-ordinary-missing-binding-unknown")
    idle(client)
    require(request(host)[0] == 200, "java-context-unavailable-import-poisoned-ordinary-composition")
    result.update(status="rejected", trustedGuestContextValuesReturned=False, freshCompositionAfterRejection=True)
    return result


def roots(client):
    """Bounded supported discovery; neither counters nor response headers supply IDs."""
    rows, token = [], None
    for _ in range(4):
        arguments = ["activation", "roots", "--service", ADAPTER, "--page-size", 32]
        if token: arguments += ["--page-token", token]
        page = client.call(*arguments)["data"]
        require(page["schemaVersion"] == 1 and page["retainedHistoryOnly"], "java-context-root-schema")
        rows += page["nodes"]
        require(len(rows) <= 128, "java-context-root-observation-bound")
        token = page["nextPageToken"]
        if not token: return rows
    raise RuntimeError("java-context-root-pagination-bound")


def tree(client, activation):
    result = client.call("activation", "tree", activation, "--page-size", 8)["data"]
    require(result["historyAvailable"] and not result["nextPageToken"], "java-context-small-real-tree")
    return result


def capture_http(client, host, path="/api/status", *, headers=None, expected=(200,)):
    before = {row["activationId"] for row in roots(client)}
    started = int(time.time() * 1000)
    status, _body, _headers = request(host, path, headers=headers)
    discovered = [row for row in roots(client) if row["activationId"] not in before]
    require(len(discovered) <= 1, "java-context-unrelated-concurrent-http-root")
    require(status != 200 or len(discovered) == 1, "java-context-successful-http-root-not-discovered")
    observed = {"httpStatus": status, "observedFromUnixMillis": started,
                "tree": tree(client, discovered[0]["activationId"]) if discovered else None}
    count = getattr(client, "java_http_observations", 0)
    require(count < 32, "java-context-http-observation-bound")
    client.java_http_observations = count + 1
    write_json(client.evidence / f"http-observation-{count:02d}.json", observed)
    require(expected is None or status in expected, "java-context-http-outcome")
    return observed


def hops(observation):
    nodes = observation["tree"]["nodes"]
    parents = [row for row in nodes if row["parentActivationId"] is None]
    require(len(parents) == 1, "java-context-one-root")
    parent = parents[0]
    children = [row for row in nodes if row["parentActivationId"] == parent["activationId"]]
    require(len(children) == 1 and len(nodes) == 2, "java-context-one-accepted-child")
    child = children[0]
    require(parent["principalKind"] == "trigger" and parent["callerService"] is None,
            "java-context-ingress-host-trigger-identity")
    require(child["principalKind"] == "service" and child["callerService"] == ADAPTER,
            "java-context-child-host-derived-service-identity")
    require(parent["rootActivationId"] == parent["activationId"]
        and child["rootActivationId"] == parent["activationId"]
        and parent["terminalState"] == child["terminalState"] == "completed", "java-context-broker-lineage")
    return parent, child


def narrowed(parent, child):
    before, actual = parent["grantedBudget"], child["grantedBudget"]
    require(before is not None and actual is not None, "java-context-admitted-grants-available")
    require(0 < int(actual["cpuFuel"]) * 2 < int(before["cpuFuel"]), "java-context-used-parent-cpu-is-not-available-to-child")
    require(0 < int(actual["memoryBytes"]) * 2 <= int(before["memoryBytes"]), "java-context-child-memory-narrowing")
    require(0 < int(actual["wallTimeLimitMillis"]) * 2 <= int(before["wallTimeLimitMillis"]), "java-context-child-remaining-wall-narrowing")
    require(actual["childCalls"] <= max(0, before["childCalls"] - 1) // 2, "java-context-child-call-reservation")
    require(0 < int(child["effectiveDeadlineUnixMillis"]) <= int(parent["effectiveDeadlineUnixMillis"]),
            "java-context-child-deadline-never-extends-parent")
    for field in ("outboundRequests", "stateReadBytes", "stateWriteBytes", "blobReadBytes", "blobWriteBytes", "logBytes", "effectCount"):
        require(int(actual[field]) <= int(before[field]), "java-context-child-grant-dimension-widened")
    return {"parentGranted": before, "childGranted": actual,
            "parentEffectiveDeadlineUnixMillis": parent["effectiveDeadlineUnixMillis"],
            "childEffectiveDeadlineUnixMillis": child["effectiveDeadlineUnixMillis"],
            "remainingCpuEffectObserved": True}


def qualify(client, targets, releases, publications, host, evidence: Path):
    result = {"schemaVersion": "latent.java-http.context.v1", "status": "in-progress",
        "guestContextImport": "omitted-ordinary-profile", "sourceActorObservations": "unavailable-to-ordinary-guest"}
    try:
        absent = capture_http(client, host)
        parent, child = hops(absent)
        result["absentChildDeadline"] = {**absent, "limits": narrowed(parent, child), "requestedChildDeadline": None}
        present = capture_http(client, host, "/api/status-deadline")
        parent, child = hops(present)
        require(int(child["effectiveDeadlineUnixMillis"]) <= present["observedFromUnixMillis"] + 2500,
                "java-context-explicit-child-deadline-was-not-narrowed")
        result["presentChildDeadline"] = {**present, "limits": narrowed(parent, child), "requestedChildDeadlineOffsetMillis": 2000}
        result["expiredChildDeadline"] = capture_http(client, host, "/api/status-expired", expected=(504,))
        idle(client)
        require(request(host)[0] == 200, "java-context-expired-deadline-poisoned-fresh-call")

        reduced = deepcopy(targets["adapter"]["budget"])
        reduced.update(cpuFuel=int(reduced["cpuFuel"]) - 100000, memoryBytes=96 * 1024 * 1024,
                       wallTimeLimitMillis=60000, childCalls=2)
        invoked = invoke(client, targets, "adapter", "handle", web_request(host), "java-context-reduced-parent", budget_override=reduced)
        require(decoded(invoked)[0]["status"] == 200, "java-context-reduced-parent-call")
        reduced_tree = tree(client, "java-context-reduced-parent")
        parent = next(row for row in reduced_tree["nodes"] if row["activationId"] == "java-context-reduced-parent")
        child = next(row for row in reduced_tree["nodes"] if row["parentActivationId"] == parent["activationId"])
        require(parent["principalKind"] == "administrator" and child["principalKind"] == "service"
            and child["callerService"] == ADAPTER, "java-context-operator-child-does-not-inherit-administrator")
        result["reducedParent"] = {"requestedBudget": reduced, "tree": reduced_tree, "limits": narrowed(parent, child)}

        record = client.call("policy", "get", "--id", "clockMonotonic-allow")["data"]["policy"]
        wrong = deepcopy(record["document"])
        for rule in wrong["rules"]:
            for principal in rule["principals"]:
                if principal["kind"] == "service" and principal["subject"] == CHILD_SUBJECT:
                    principal["subject"] = "service:8:examples:22:examples/wrong-adapter"
        changed = policy(client, "policy", "clockMonotonic-allow", wrong, int(record["generation"]))
        try:
            result["wrongClockPolicyRebinding"] = rebind(client, targets, releases, publications, ("domain", "adapter"))
            route(client, host, publications["adapter"])
            denied = capture_http(client, host, expected=(403, 500))
            require(denied["tree"] is not None, "java-context-wrong-child-grant-observation-missing")
            children = [row for row in denied["tree"]["nodes"] if row["parentActivationId"] is not None]
            require(len(children) == 1 and len(denied["tree"]["nodes"]) == 2,
                    "java-context-wrong-child-grant-real-child-required")
            child = children[0]
            diagnostic = child["diagnostic"]
            require(child["principalKind"] == "service" and child["callerService"] == ADAPTER
                and child["terminalState"] != "completed"
                and diagnostic is not None and diagnostic["stage"] == 4 and diagnostic["reason"] == 8,
                "java-context-wrong-child-grant-producer-diagnosis-required")
            result["wrongChildPrincipalGrant"] = denied
        finally:
            policy(client, "policy", "clockMonotonic-allow", record["document"], int(changed["generation"]))
            result["restoredClockPolicyRebinding"] = rebind(client, targets, releases, publications, ("domain", "adapter"))
            route(client, host, publications["adapter"])
        idle(client)
        require(request(host)[0] == 200, "java-context-restored-child-grant-not-fresh")

        result["headerSpoofs"] = []
        for headers in ({"Host": "spoofed.invalid"}, {"Forwarded": "for=203.0.113.1;host=spoofed.invalid"},
            {"X-Forwarded-For": "203.0.113.1"}, {"X-LSF-Principal": "administrator"},
            {"X-LSF-Deadline-Unix-Millis": "18446744073709551615"},
            {"X-LSF-Root-Activation-Id": "forged-root", "X-LSF-Parent-Activation-Id": "forged-parent"}):
            observed = capture_http(client, host, headers=headers, expected=(200, 400, 401, 403))
            if observed["httpStatus"] == 200:
                parent, child = hops(observed)
                narrowed(parent, child)
                require(parent["activationId"] != "forged-root" and child["parentActivationId"] != "forged-parent",
                        "java-context-header-lineage-became-authority")
            result["headerSpoofs"].append({"headerNames": sorted(headers), **observed})

        bounded_metadata = ["guest.synthetic" + str(index) + "=" + "x" * 4096 for index in range(5)]
        accepted = invoke(client, targets, "domain", "status", [], "java-context-bounded-metadata",
                          context_flags=tuple(value for entry in bounded_metadata for value in ("--metadata", entry)))
        require(accepted["category"] == "success", "java-context-bounded-metadata-rejected")
        result["boundedMetadata"] = {"requestedUtf8Bytes": sum(len(entry.encode()) for entry in bounded_metadata),
                                     "response": accepted}
        oversized_metadata = ["guest.synthetic" + str(index) + "=" + "x" * 4096 for index in range(9)]
        oversized_bytes = sum(len(entry.encode()) for entry in oversized_metadata)
        require(oversized_bytes > 32 * 1024, "java-context-oversized-vector-must-exceed-cli-bound")
        for name, flags, codes in (
            ("lineage", ("--root-activation-id", "forged-root", "--parent-activation-id", "forged-parent"), (4,)),
            ("oversized-context", tuple(value for entry in oversized_metadata for value in ("--metadata", entry)), (2,))):
            denied = invoke(client, targets, "domain", "status", [], "java-context-denied-" + name,
                            context_flags=flags, codes=codes)
            if name == "lineage":
                require(denied["category"] == "platform-failure" and denied["error"]["code"] == "permission-denied"
                    and denied["requestDispatched"] and denied["outcomeKnown"], "java-context-supplied-authority-accepted")
            else:
                require(denied["category"] == "local-error" and denied["error"]["code"] == "invalid-arguments"
                    and not denied["requestDispatched"] and denied["outcomeKnown"], "java-context-oversized-metadata-outcome")
                result["oversizedMetadataBounds"] = {"requestedUtf8Bytes": oversized_bytes,
                    "maximumCliMetadataUtf8Bytes": 32 * 1024, "rejectedBeforeDispatch": True}
            result[name + "Denied"] = denied
            idle(client)
            require(request(host)[0] == 200, "java-context-denied-input-poisoned-fresh-call")
        result.update(status="passed", freshAfterDenials=True)
        return result
    except BaseException as error:
        result.update(status="failed", reason=str(error) if isinstance(error, (RuntimeError, ValueError)) else type(error).__name__)
        raise
    finally:
        write_workflow_receipt(evidence / "context.json", result)
