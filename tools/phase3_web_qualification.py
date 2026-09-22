"""Real CLI admission, lifecycle, failure and cancellation assertions."""
from __future__ import annotations

import json
import time

from tools.phase2_operator_process import Process, require, write_json
from tools.phase3_web_scenario import (
    deploy, deployment_manifest, http_response, idle_inventory, invocation_arguments, invoke, prepare,
    publication_receipt, publish, selected_client_asset, trigger,
)


def admission(client, fixture):
    for name, evidence, operation in (
        ("angular", "no-publisher-evidence", "reject-publisher"),
        ("angular", "no-builder-evidence", "reject-builder"),
        ("missing-sbom", "evidence", "reject-sbom"),
    ):
        result = publish(client, fixture, name, operation, evidence, codes=(4,))
        require(result["category"] == "platform-failure", "web-admission-not-enforced")
        lookup = client.call("web", "operation", operation)
        require(not lookup["outcomeKnown"] and lookup["data"]["operation"] is None,
                "denied-web-publication-became-committed")
    publications = {}
    for name in ("angular", "alternate"):
        receipt = publish(client, fixture, name)
        replay = publish(client, fixture, name)
        require(replay["replayed"] is True and receipt["replayed"] is False
                and {key: value for key, value in replay.items() if key != "replayed"}
                == {key: value for key, value in receipt.items() if key != "replayed"}, "web-publish-replay")
        lookup = client.call("web", "operation", "publish-" + name)
        require(lookup["outcomeKnown"] and lookup["data"]["operation"] == replay,
                "web-operation-durable-identity")
        publications[name] = receipt["publication"]["id"]
    require(publications["angular"] != publications["alternate"], "web-publication-collapsed")
    return publications


def tenant_denial(client, profile, publication):
    original = client.config
    client.config = profile
    try:
        result = client.call("web", "get", "--publication", publication, codes=(4, 6))
        require(result["category"] != "success", "web-cross-tenant-selection")
        lookup = client.call("web", "operation", "publish-angular")
        require(not lookup["outcomeKnown"] and lookup["data"]["operation"] is None,
                "web-cross-tenant-operation")
    finally:
        client.config = original


def native_cache_audit(client, record, kind, *, allow_empty=False):
    # Only a pre-restart baseline may be empty. A claimed native hit/miss still
    # requires an actual matching audit event; prepared-memory hits are distinct.
    require(type(allow_empty) is bool, "native-cache-audit-empty-bound")
    found = []
    token = None
    tokens = set()
    for _ in range(16):
        arguments = ["audit", "query", "--scope", "tenant", "--kind", kind,
                     "--actor", "native-aot-cache", "--page-size", "32"]
        if token:
            arguments += ["--page-token", token]
        data = client.call(*arguments)["data"]
        for row in data["records"]:
            observation = row["data"].get("observation")
            require(observation is not None and observation["cacheKind"].endswith("NATIVE"),
                    "native-cache-audit-kind")
            identity = observation["identities"]
            if identity["packageDigest"] == record["packageDigest"]:
                require(identity["componentDigest"] == record["componentDigest"], "native-cache-source-identity")
                require(len(found) < 32, "native-cache-audit-match-overflow")
                found.append({"sequence": row["sequence"], "kind": observation["kind"],
                              "packageDigest": identity["packageDigest"],
                              "componentDigest": identity["componentDigest"]})
        token = data["page"]["nextPageToken"]
        if not token:
            break
        require(token not in tokens and len(token) <= 4096, "native-cache-audit-page")
        tokens.add(token)
    require(not token and (allow_empty or bool(found)) and len(found) <= 32, "native-cache-audit-missing-or-overflow")
    return found


def cancel_render(client, record, activation, disconnect=False):
    arguments = invocation_arguments(client, record, "/spin", activation)
    process = Process([client.executable, "--output", "json", "--config", str(client.config),
                       "--profile", "operator", *map(str, arguments)],
                      client.directory, client.environment, client.cancellation, maximum=65536)
    client.calls += 1
    try:
        active = None
        deadline = min(client.deadline, time.monotonic() + 3)
        for _ in range(32):
            process.drain()
            state = client.call("activation", "get", activation, codes=(0, 6))
            if state["category"] == "success":
                active = state["data"]
                if active.get("phase") == "running":
                    break
                require(active.get("terminalState") is None, "angular-spin-ended-before-cancellation")
            require(time.monotonic() < deadline and not process.owner.exited(), "angular-spin-not-running")
            time.sleep(0.01)
        require(active is not None and active.get("phase") == "running", "angular-spin-not-observed")
        if disconnect:
            process.close()
        else:
            result = client.call("activation", "cancel", activation, "--reason", "T1 qualification")
            require(result["outcomeKnown"] and result["data"]["disposition"] == "accepted",
                    "angular-cancellation-uncertain")
            finished = process.complete(min(client.deadline, time.monotonic() + 8))
            response = json.loads(finished.stdout)
            require(finished.returncode == 4 and response["category"] == "platform-failure"
                    and response["error"]["code"] == "cancelled", "angular-cancelled-result")
        terminal = None
        for _ in range(32):
            terminal = client.call("activation", "get", activation)["data"]
            if terminal.get("terminalState") is not None:
                break
            require(time.monotonic() < deadline + 5, "angular-cancellation-not-terminal")
            time.sleep(0.02)
        require(terminal is not None and terminal.get("terminalState") == "cancelled",
                "angular-cancellation-terminal")
        idle_inventory(client)
        return {"activationId": activation, "disconnect": disconnect, "terminal": "cancelled"}
    finally:
        process.close()


def failure_recovery(client, record, publication):
    for path, activation in (("/exception", "angular-exception"),
                             ("/large-hydration", "angular-hydration-limit")):
        result = invoke(client, record, publication, activation, path, codes=(4,))
        require(result["category"] == "platform-failure", "angular-invalid-render-succeeded")
        invoke(client, record, publication, activation + "-recovery")
        idle_inventory(client)
    cancellations = [cancel_render(client, record, "angular-explicit-cancel"),
                     cancel_render(client, record, "angular-disconnect", disconnect=True)]
    invoke(client, record, publication, "angular-cancellation-recovery")
    return cancellations


def renewal(client, fixture, record, publication, deployment):
    operation = "renew-angular"
    arguments = ("--rpc-timeout-ms", "30000", "web", "renew-evidence", "--publication", publication,
                 "--package-digest", record["packageDigest"],
                 "--evidence", fixture / "angular/renewed-evidence/index.json",
                 "--operation-id", operation, "--expected-generation", "1")
    deadline = min(client.deadline, time.monotonic() + 45)
    receipt = None
    for attempt in range(3):
        client.cancellation.check()
        remaining = deadline - time.monotonic()
        require(remaining > 0, "web-renewal-setup-deadline")
        result = client.call(*arguments, codes=(0, 4), timeout=remaining)
        if result["category"] == "success":
            receipt = publication_receipt(result, operation)
            break
        require(result["category"] == "platform-failure"
                and result.get("error", {}).get("code") == "unavailable",
                "web-renewal-rejected")
        # Renewal is keyed by one immutable evidence upload and operation ID.
        # Reconcile that key before retrying so an unavailable response can never
        # duplicate or replace a mutation that the node already committed.
        lookup = client.call("web", "operation", operation,
                             timeout=max(0.001, deadline - time.monotonic()))
        if lookup["outcomeKnown"]:
            retained = lookup["data"]["operation"]
            require(isinstance(retained, dict)
                    and retained["operationId"] == operation
                    and retained["publication"]["id"] == publication
                    and retained["publication"]["tenant"] == TENANT
                    and retained["actor"]["subject"] == "workflow-operator",
                    "web-renewal-recovery-identity")
            receipt = retained
            break
        require(lookup["data"]["operation"] is None,
                "web-renewal-uncertain-requires-recovery")
        require(attempt < 2 and time.monotonic() + 0.025 < deadline,
                "web-renewal-admission-busy")
        time.sleep(0.025)
    require(receipt is not None, "web-renewal-receipt")
    require(receipt["resultingGeneration"] == "2", "angular-evidence-generation")
    rejected = prepare(client, publication, 1, wait=5000, codes=(4,))
    require(rejected["category"] == "platform-failure", "stale-preparation-generation")
    invoke(client, record, publication, "angular-stale-deployment", codes=(4,))
    updated = deploy(client, record, publication, "refresh-angular", deployment["generation"])
    prepare(client, publication, 2, wait=15000)
    invoke(client, record, publication, "angular-renewal-recovery")
    return updated, receipt


def independent_publications(client, records, publications, deployment):
    alternate = publications["alternate"]
    deployment = staged_web_rollout(client, records["alternate"], alternate, deployment)
    prepare(client, alternate, 1)
    candidate = deploy(client, records["alternate"], alternate, "select-alternate", deployment["generation"])
    invoke(client, records["alternate"], alternate, "angular-selected-alternate")
    reverted = deploy(client, records["angular"], publications["angular"], "rollback-angular", candidate["generation"])
    rendered = invoke(client, records["angular"], publications["angular"], "angular-selected-rollback")
    revoked = publication_receipt(client.call("web", "revoke", "--publication", alternate,
                                             "--operation-id", "revoke-alternate", "--expected-generation", "1"),
                                  "revoke-alternate")
    prepare(client, alternate, 2, wait=5000, codes=(4,))
    require(client.call("web", "get", "--publication", alternate)["data"]["record"]["state"].endswith("REVOKED"),
            "independent-web-revocation")
    invoke(client, records["angular"], publications["angular"], "angular-after-independent-revocation")
    return reverted, rendered["revision"], revoked


def staged_web_rollout(client, record, publication, deployment):
    from tools.phase2_operator_canary import rollback_target
    from tools.phase2_operator_scenario import change, receipt

    candidate = client.directory / "compatible-web-rollout.json"
    write_json(candidate, deployment_manifest(record, publication, "web-candidate", 2500))
    started = receipt(client.call("rollout", "start", "web-staged", "--base", "angular",
                         "--expected-base-generation", deployment["generation"], "--candidate", candidate,
                         "--weights", "2500,10000", "--operation-id", "start-web-rollout",
                         "--expected-revision", "0"), "start-web-rollout")
    target = rollback_target(client, "web-staged", started)
    advanced = receipt(change(client, "advance", "web-staged", started["revision"], "advance-web-rollout",
                              "--next-step", "1"), "advance-web-rollout")
    rolled = receipt(change(client, "rollback", "web-staged", advanced["revision"], "rollback-web-rollout",
                            "--target-generation", target), "rollback-web-rollout")
    require(rolled["state"].endswith("ROLLED_BACK"), "web-staged-rollback-state")
    require(client.call("deployment", "get", "web-candidate", "--operation-snapshot", codes=(6,))["data"]["deployment"] is None,
            "web-staged-rollback-retained-candidate")
    return client.call("deployment", "get", "angular")["data"]["deployment"]


def http_rendering(client, node, record, publication, deployment, revision):
    triggers = {host: trigger(client, record, publication, deployment, revision, host)
                for host in ("alice.angular.test", "bob.angular.test", "foreign.angular.test")}
    html_by_subject = {}
    for host, subject, forbidden in (("alice.angular.test", "Alice&lt;unsafe&gt;", "Hello Bob"),
                                     ("bob.angular.test", "Bob", "Alice&lt;unsafe&gt;"),
                                     ("alice.angular.test", "Alice&lt;unsafe&gt;", "Hello Bob")):
        body, _ = http_response(client, node, host)
        html = body.decode("utf-8")
        require("ngh=" in html and subject in html and forbidden not in html
                and "lsf-private-server-fixture-234" not in html, "http-render-principal-or-private-state")
        selected_client_asset(record, publication, html)
        html_by_subject[host] = html
    http_response(client, node, "foreign.angular.test", expected=403)
    lifecycle = trigger_lifecycle(client, node, triggers)
    idle_inventory(client)
    return {"responses": 3, "isolatedPrincipals": 2, "foreignTenantDenied": True,
            "hydratedMarkup": all("ngh=" in html for html in html_by_subject.values()),
            "triggerLifecycle": lifecycle}


def trigger_lifecycle(client, node, triggers):
    page = client.call("trigger", "list", "--page-size", "8")["data"]
    require(page["nextPageToken"] is None and
            {entry["manifest"]["metadata"]["name"] for entry in page["triggers"]} == set(triggers.values()),
            "angular-trigger-page")
    name = triggers["bob.angular.test"]
    state = client.call("trigger", "get", name)["data"]
    generation = state["trigger"]["generation"]
    operation = "delete-bob-trigger"
    result = client.call("trigger", "delete", name, "--operation-id", operation,
                         "--expected-generation", generation, "--expected-state-version", state["stateVersion"])
    require(result["outcomeKnown"] and result["data"]["generation"] == generation,
            "angular-trigger-delete-outcome")
    lookup = client.call("trigger", "operation", operation)
    require(lookup["outcomeKnown"] and lookup["data"]["disposition"] == "found"
            and lookup["data"]["executionPermission"] is False
            and lookup["data"]["receipt"]["objectGeneration"] == generation
            and lookup["data"]["receipt"]["stateVersion"] == result["data"]["stateVersion"],
            "angular-trigger-delete-receipt")
    require(client.call("trigger", "get", name, codes=(6,))["data"]["trigger"] is None,
            "angular-trigger-delete-retained-route")
    http_response(client, node, "bob.angular.test", expected=404)
    return {"listedTriggers": len(page["triggers"]), "deletedRouteAbsent": True,
            "deletionOperationRetained": True, "removedGenerationPreserved": True}
