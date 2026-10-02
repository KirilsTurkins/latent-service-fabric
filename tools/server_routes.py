"""Explicit finite server-source routes through the authenticated existing CLI.

Each trigger has its own catalog CAS and durable original-operation record.
There is no atomic multi-trigger promise, implicit publication, retry of an
accepted mutation, or authority derived from an application's bind address.
"""
from __future__ import annotations

import copy
import re
import secrets
from pathlib import Path

from tools import server_source as source
from tools.dev_workflow import state
from tools.dev_workflow.common import DevError, decode, digest, encode, members, require, sha

SCHEMA = "lsf.server.routes.v1"
MAX_TRIGGERS = 32


def counter(value: str, *, positive=False) -> int:
    require(isinstance(value, str) and re.fullmatch(r"0|[1-9][0-9]{0,19}", value)
            and int(value) < 2**64 and (not positive or int(value) > 0), "server-route-counter")
    return int(value)


def pin(value: dict) -> dict:
    members(value, {"tenant", "service", "route", "publication", "revision", "deploymentGeneration", "componentDigest"})
    for key in ("tenant", "service", "route"):
        source.token(value[key])
    for key, prefix in (("publication", "publication:"), ("revision", "revision-v1:")):
        require(isinstance(value[key], str) and value[key].startswith(prefix), "server-route-pin")
        sha(value[key][len(prefix):])
    counter(value["deploymentGeneration"], positive=True)
    sha(value["componentDigest"])
    return value


def observed_pin(cli, tenant: str, route: str, component_digest: str) -> dict:
    """Use published catalog observations, never build-time placeholder IDs."""
    deployment = known(cli.call("deployment", "get", route))["deployment"]
    require(isinstance(deployment, dict), "server-route-deployment-missing")
    manifest = deployment["manifest"]
    require(manifest["metadata"]["tenant"] == tenant and manifest["metadata"]["name"] == route
            and manifest["spec"]["release"] == component_digest, "server-route-deployment-association")
    publication = deployment.get("publication")
    require(isinstance(publication, dict) and publication.get("tenant") == tenant
            and publication.get("id") == manifest["spec"].get("publication"), "server-route-publication-required")
    snapshot = known(cli.call("route", "get"))["snapshot"]
    require(isinstance(snapshot, dict) and isinstance(snapshot.get("services"), list)
            and len(snapshot["services"]) <= 4096, "server-route-catalog-bound")
    selected = [row for row in snapshot["services"] if row.get("tenant") == tenant
                and row.get("service") == manifest["spec"]["service"] and row.get("routeId") == route]
    require(len(selected) == 1 and len(selected[0]["revisions"]) == 1, "server-route-exact-revision-required")
    revision = selected[0]["revisions"][0]
    require(revision["releaseDigest"] == component_digest and revision["weight"] == 10000,
            "server-route-no-inferred-canary")
    return pin({"tenant": tenant, "service": manifest["spec"]["service"], "route": route,
        "publication": publication["id"], "revision": revision["revisionId"],
        "deploymentGeneration": deployment["generation"], "componentDigest": component_digest})


def plan(raw: bytes, configuration: bytes, selected: dict, *, source_digest: str, profile_digest: str) -> list[dict]:
    selected = pin(selected)
    declaration = source.validate(raw, component_digest=selected["componentDigest"],
                                  source_digest=source_digest, profile_digest=profile_digest)
    mounts = source.mounts(configuration, declaration)
    manifests = []
    target = {"service": selected["service"], "contract": source.WEB, "function": "handle",
        "route": selected["route"], "publication": selected["publication"], "revision": selected["revision"],
        "deploymentGeneration": int(selected["deploymentGeneration"])}
    for mount in mounts:
        for method in mount["methods"]:
            manifests.append({"apiVersion": "latent.dev/v1alpha1", "kind": "HttpTrigger",
                "metadata": {"name": mount["name"] + "-" + method.lower(), "tenant": selected["tenant"]},
                "spec": {"target": copy.deepcopy(target), "configuration": {"profile": "buffered-v1",
                    **{key: mount[key] for key in ("scheme", "host", "path", "pathMatch")}, "method": method}}})
            require(len(manifests) <= MAX_TRIGGERS, "server-route-trigger-limit")
    return manifests


def known(result: dict) -> dict:
    if result.get("outcomeKnown") is not True:
        raise DevError("server-route-outcome-uncertain-use-recover", uncertain=True)
    require(result.get("category") == "success" and isinstance(result.get("data"), dict),
            "server-route-request-rejected-last-good-retained")
    return result["data"]


class Routes:
    """One protected local owner; callers hold state.lock for every public call."""
    def __init__(self, root: Path, cli, owner: dict):
        members(owner, {"tenant", "route", "clientConfigDigest"})
        source.token(owner["tenant"])
        source.token(owner["route"])
        sha(owner["clientConfigDigest"])
        self.root, self.cli, self.owner = root, cli, owner

    def read(self) -> dict:
        if not (self.root / "server-routes.json").exists():
            return {"schemaVersion": SCHEMA, "owner": self.owner, "pending": None, "routes": {}}
        value = state.load(self.root, "server-routes.json")
        members(value, {"schemaVersion", "owner", "pending", "routes"})
        require(value["schemaVersion"] == SCHEMA and value["owner"] == self.owner, "server-route-owner-mismatch")
        require(isinstance(value["routes"], dict) and len(value["routes"]) <= MAX_TRIGGERS, "server-route-retention-limit")
        return value

    def observe(self, name: str) -> dict:
        result = self.cli.call("trigger", "get", name)
        if result.get("outcomeKnown") is not True:
            raise DevError("server-route-observation-uncertain", uncertain=True)
        require(result.get("category") in {"success", "not-found"}, "server-route-observation-rejected")
        data = result["data"]
        counter(data["stateVersion"])
        trigger = data.get("trigger")
        if trigger is not None:
            require(trigger["manifest"]["metadata"] == {"name": name, "tenant": self.owner["tenant"]},
                    "server-route-observed-scope")
            counter(trigger["generation"], positive=True)
        return data

    def check_owned(self, name: str, observed: dict, value: dict) -> None:
        prior = value["routes"].get(name)
        trigger = observed.get("trigger")
        require((prior is None and trigger is None) or (prior is not None and trigger is not None
                and trigger["generation"] == prior["generation"] and trigger["manifest"] == prior["manifest"]),
                "server-route-concurrent-change-no-overwrite")

    def apply(self, manifests: list[dict]) -> dict:
        require(isinstance(manifests, list) and 0 < len(manifests) <= MAX_TRIGGERS, "server-route-trigger-limit")
        value = self.read()
        require(value["pending"] is None, "server-route-recover-original-operation-first")
        names = [row["metadata"]["name"] for row in manifests]
        require(len(set(names)) == len(names) and all(row["metadata"]["tenant"] == self.owner["tenant"]
                and row["spec"]["target"]["route"] == self.owner["route"] for row in manifests), "server-route-plan-scope")
        require(set(value["routes"]) <= set(names), "server-route-remove-old-mounts-explicitly-first")
        # Validate all ownership observations before dispatching the first write.
        # Each later write still has an independent current catalog fence.
        for name in names:
            self.check_owned(name, self.observe(name), value)
        for manifest in manifests:
            name = manifest["metadata"]["name"]
            current = self.read()
            observed = self.observe(name)
            self.check_owned(name, observed, current)
            if observed.get("trigger") and observed["trigger"]["manifest"] == manifest:
                continue
            self.mutate("apply", name, manifest, observed, current)
        return self.read()

    def remove(self, names: list[str]) -> dict:
        require(isinstance(names, list) and 0 < len(names) <= MAX_TRIGGERS and len(set(names)) == len(names),
                "server-route-removal-selection")
        for name in names:
            value = self.read()
            require(value["pending"] is None and name in value["routes"], "server-route-owned-removal-required")
            observed = self.observe(name)
            self.check_owned(name, observed, value)
            self.mutate("delete", name, value["routes"][name]["manifest"], observed, value)
        return self.read()

    def rollback(self, names: list[str]) -> dict:
        value = self.read()
        require(value["pending"] is None and isinstance(names, list) and 0 < len(names) <= MAX_TRIGGERS
                and len(set(names)) == len(names), "server-route-rollback-selection")
        manifests = []
        for name in names:
            prior = value["routes"].get(name)
            require(isinstance(prior, dict) and prior.get("previous") is not None, "server-route-no-retained-rollback")
            manifests.append(prior["previous"])
        # Rollback is a new CAS mutation. The server independently denies a
        # revoked/missing old publication or revision; no replay grants authority.
        for manifest in manifests:
            name = manifest["metadata"]["name"]
            current = self.read()
            observed = self.observe(name)
            self.check_owned(name, observed, current)
            self.mutate("apply", name, manifest, observed, current)
        return self.read()

    def mutate(self, action: str, name: str, manifest: dict, observed: dict, value: dict) -> None:
        require(value["pending"] is None, "server-route-recover-original-operation-first")
        operation = {"id": "server-" + secrets.token_hex(16), "action": action, "name": name,
            "manifest": manifest, "expectedGeneration": observed["trigger"]["generation"] if observed["trigger"] else "0",
            "expectedStateVersion": observed["stateVersion"]}
        value["pending"] = operation
        state.atomic(self.root, "server-routes.json", value)
        # The exact file is retained before the request, including uncertain exit.
        state.atomic(self.root, "selected-server-trigger.json", manifest)
        arguments = ("trigger", action, self.root / "selected-server-trigger.json" if action == "apply" else name,
            "--operation-id", operation["id"], "--expected-generation", operation["expectedGeneration"],
            "--expected-state-version", operation["expectedStateVersion"])
        result = self.cli.call(*arguments)  # Exactly one mutation; no retry handler.
        if result.get("outcomeKnown") is True and result.get("category") != "success":
            value["pending"] = None
            state.atomic(self.root, "server-routes.json", value)
            known(result)
        # Apply has a full receipt. Delete's small response is completed only by
        # an explicit lookup of this same operation, never a second Delete.
        if action == "delete" and result.get("outcomeKnown") is True and result.get("category") == "success":
            result = self.cli.call("trigger", "operation", operation["id"])
        try:
            self.finish(operation, result)
        except DevError as error:
            raise DevError(error.code, uncertain=True) from None

    def finish(self, operation: dict, result: dict) -> None:
        value = self.read()
        require(value["pending"] == operation, "server-route-journal-conflict")
        data = known(result)
        receipt = data.get("receipt")
        require(isinstance(receipt, dict) and receipt.get("operationId") == operation["id"]
                and receipt.get("tenant") == self.owner["tenant"] and receipt.get("triggerId") == operation["name"]
                and receipt.get("action") == "TRIGGER_OPERATION_ACTION_" + operation["action"].upper()
                and receipt.get("expectedGeneration") == operation["expectedGeneration"]
                and receipt.get("expectedStateVersion") == operation["expectedStateVersion"], "server-route-receipt-scope")
        target = receipt.get("target", {})
        expected = operation["manifest"]["spec"]["target"]
        require(target.get("kind") == "application" and target.get("publication", {}).get("tenant") == self.owner["tenant"]
                and target.get("publication", {}).get("id") == expected["publication"]
                and target.get("deploymentId") == expected["route"] and target.get("revision") == expected["revision"]
                and target.get("deploymentGeneration") == str(expected["deploymentGeneration"]), "server-route-receipt-pin")
        sha(receipt.get("receiptDigest"))
        generation = receipt.get("objectGeneration")
        counter(generation, positive=True)
        counter(receipt.get("stateVersion"), positive=True)
        require(int(receipt["stateVersion"]) == int(operation["expectedStateVersion"]) + 1
                and (generation == receipt["stateVersion"] if operation["action"] == "apply"
                     else generation == operation["expectedGeneration"]), "server-route-receipt-generation")
        observed = self.observe(operation["name"])
        if operation["action"] == "apply":
            trigger = observed.get("trigger")
            require(trigger is not None and trigger["generation"] == generation
                    and trigger["manifest"] == operation["manifest"], "server-route-original-operation-changed-no-replay")
            prior = value["routes"].get(operation["name"])
            value["routes"][operation["name"]] = {"manifest": operation["manifest"], "generation": generation,
                "receiptDigest": receipt["receiptDigest"], "previous": prior["manifest"] if prior else None}
        else:
            require(observed.get("trigger") is None, "server-route-original-operation-changed-no-replay")
            del value["routes"][operation["name"]]
        value["pending"] = None
        state.atomic(self.root, "server-routes.json", value)

    def recover(self) -> dict:
        pending = self.read()["pending"]
        require(pending is not None, "server-route-no-pending-operation")
        try:
            self.finish(pending, self.cli.call("trigger", "operation", pending["id"]))
        except DevError as error:
            raise DevError(error.code, uncertain=True) from None
        return self.read()

    def inspect(self) -> dict:
        value = self.read()
        return {"schemaVersion": SCHEMA, "owner": self.owner, "pending": value["pending"] is not None,
                "routes": [{"declared": row["manifest"], "published": self.observe(name).get("trigger"),
                            "reachability": "not-observed"} for name, row in value["routes"].items()],
                "atomicMultiRoutePublication": False, "executionPermission": False}
