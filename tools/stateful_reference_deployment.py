"""Derive exact app HTTP triggers and installed targets from published inputs."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.dev_workflow.transaction_binding import validate

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = "examples:order-draft/api@1.0.0"
HOST = "stateful.test:19092"
MAX_U64 = (1 << 64) - 1
ENTITIES = ("alice", "bob")


def digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def pinned(value: object, prefix: str) -> str:
    require(isinstance(value, str) and re.fullmatch(re.escape(prefix) + r"[0-9a-f]{64}", value) is not None,
            "published order-draft identity is invalid")
    return value


def derive(companion: bytes, published: dict, *, entity: str, incarnation: str,
           result_policy: str, state_policies: list[str]) -> dict:
    """Emit constraints only. Signing, namespace creation and grants stay separate."""
    require(entity in ENTITIES, "only the two finite synthetic draft entities are supported")
    require(isinstance(incarnation, str) and re.fullmatch(r"[1-9][0-9]{0,19}", incarnation) is not None
            and int(incarnation) <= MAX_U64, "namespace incarnation must be exact positive u64")
    require(isinstance(published, dict) and set(published) == {
        "componentDigest", "publication", "revision", "deploymentGeneration", "companionDigest"},
        "published order-draft inputs must be closed")
    component = pinned(published["componentDigest"], "sha256:")
    publication = pinned(published["publication"], "publication:sha256:")
    revision = pinned(published["revision"], "revision-v1:sha256:")
    companion_digest = pinned(published["companionDigest"], "sha256:")
    require(companion_digest == digest(companion), "published companion does not match its exact bytes")
    generation = published["deploymentGeneration"]
    require(type(generation) is int and 1 <= generation <= MAX_U64, "published deployment generation must be u64")
    require(isinstance(result_policy, str) and re.fullmatch(r"[a-z][a-z0-9-]{0,127}", result_policy) is not None,
            "result-read policy identity is invalid")
    require(isinstance(state_policies, list) and 1 <= len(state_policies) <= 8
            and len(set(state_policies)) == len(state_policies)
            and all(isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9-]{0,127}", value) for value in state_policies),
            "state policy identities must be finite and unique")
    require(len(companion) <= 128 * 1024, "order-draft companion exceeds its existing bound")
    declaration = json.loads(companion)
    declaration = validate(companion, capsule=declaration.get("capsule"),
        deployment=declaration.get("deployment"), binding=declaration.get("binding"))
    require(declaration["namespace"] == "order-drafts-" + entity, "companion belongs to another draft namespace")
    require(declaration["stateSchema"] == digest((ROOT / "examples/stateful-reference/state-schema.json").read_bytes()),
            "companion state schema differs from the maintained application")
    require(declaration["operations"] == [
        {"operation": name, "mode": mode, "inputFormat": "lsf-wit-values-v1", "resultFormat": "lsf-wit-values-v1"}
        for name, mode in (("edit", "strict-command"), ("query", "fresh-query"))],
        "companion does not describe the exact common application operations")
    base = "/drafts/" + entity
    triggers, operations = [], []
    for mode, function, method, host in (
        ("command", "edit", "POST", HOST), ("query", "query", "GET", HOST),
        ("result", "edit", "GET", HOST), ("query", "query", "GET", entity + "-read.test:19092"),
    ):
        name = "order-draft-" + entity + "-" + mode + ("-ssr" if host != HOST else "")
        suffix = "edit" if mode == "command" else mode
        route = {
            "profile": "transaction-http-v1", "scheme": "http", "host": host,
            "path": base + "/" + suffix, "pathMatch": "exact", "method": method,
            "transactionMode": mode, "namespace": declaration["namespace"], "incarnation": incarnation,
            "stateSchema": declaration["stateSchema"], "companionDigest": companion_digest,
            "stateBinding": declaration["binding"], "resultPolicy": result_policy, "entity": entity,
        }
        if mode == "command":
            route["preconditionKey"] = base64.b64encode(("drafts/" + entity + "/draft").encode()).decode()
        triggers.append({"apiVersion": "latent.dev/v1alpha1", "kind": "HttpTrigger",
            "metadata": {"name": name, "tenant": "examples"}, "spec": {"target": {
                "service": declaration["capsule"], "contract": CONTRACT, "function": function,
                "route": declaration["deployment"], "publication": publication, "revision": revision,
                "deploymentGeneration": generation}, "configuration": route}})
    for function in ("edit", "query"):
        operations.append({"tenant": "examples", "componentDigest": component, "publication": publication,
            "contract": CONTRACT, "function": function, "deployment": declaration["deployment"],
            "route": declaration["deployment"], "binding": declaration["binding"], "companionDigest": companion_digest,
            "incarnation": int(incarnation), "resultPolicy": result_policy, "statePolicies": list(state_policies),
            "entity": entity})
    return {"schemaVersion": "latent.stateful-reference.deployment-inputs.v1", "entity": entity,
            "namespace": declaration["namespace"], "triggers": triggers, "stateOperations": operations,
            "createsGrants": False, "signed": False, "nodeQualified": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--companion", type=Path, required=True)
    parser.add_argument("--published", type=Path, required=True)
    parser.add_argument("--entity", choices=ENTITIES, required=True)
    parser.add_argument("--incarnation", required=True)
    parser.add_argument("--result-policy", required=True)
    parser.add_argument("--state-policy", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(args.companion.is_file() and not args.companion.is_symlink()
            and args.companion.stat().st_size <= 128 * 1024, "companion must be a bounded regular file")
    require(args.published.is_file() and not args.published.is_symlink()
            and args.published.stat().st_size <= 16384, "publication inputs must be a bounded regular file")
    value = derive(args.companion.read_bytes(), json.loads(args.published.read_bytes()), entity=args.entity,
                   incarnation=args.incarnation, result_policy=args.result_policy, state_policies=args.state_policy)
    with args.output.open("x", encoding="utf8", newline="\n") as stream:
        stream.write(json.dumps(value, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
