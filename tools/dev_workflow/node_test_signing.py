"""Opt-in, short-lived package signing confined to one disposable test node."""
from __future__ import annotations

from pathlib import Path
import time

from . import build, paths, process, state, tool_inventory
from .common import decode, digest, identifier, require


def prepare(root: Path, descriptor: dict, tool_root: Path) -> dict:
    require(root.name.startswith("test-"), "disposable-test-signing-only")
    saved = state.load(root, "project.json")
    require(saved["descriptor"] == descriptor, "test-signing-project-changed")
    source, receipt = build.accepted(root, saved)
    pins = [tool for tool in descriptor["build"]["tools"] if tool["name"] == "test-signer"]
    require(len(pins) == 1 and tool_root.is_absolute(), "pinned-test-signer-required")
    pin = pins[0]
    inventory = tool_inventory.check(tool_root, descriptor, "linux-x86_64")
    require(inventory is not None, "test-signer-inventory-required")
    target = root / "test-signing"
    intent = {"source": receipt["source"], "attempt": receipt["attempt"],
              "component": receipt["artifacts"]["component"], "toolInventory": inventory, "signer": pin["sha256"]}
    additional = []
    if (root / "local-service-build.json").exists():
        from .local_service_fixture import signing_input
        child_source, child_descriptor, child_receipt = signing_input(root)
        require(child_receipt["artifacts"]["component"] != intent["component"], "distinct-local-fixture-component-required")
        additional.append(str(child_source / child_descriptor["build"]["outputRoot"]))
        intent["dependencies"] = [{"source": child_receipt["source"], "attempt": child_receipt["attempt"],
                                   "component": child_receipt["artifacts"]["component"]}]
    if (root / "test-signing-intent.json").exists():
        require(state.load(root, "test-signing-intent.json") == intent, "test-signing-input-changed-use-new-workspace")
    else:
        require(not target.exists(), "test-signing-output-already-exists")
        state.atomic(root, "test-signing-intent.json", intent)
        with paths.opened(tool_root, pin["path"]):
            result = process.run([str(tool_root / pin["path"]), "demo-sign", str(target),
                                  str(source / descriptor["build"]["outputRoot"]), *additional], root,
                                 timeout=60, maximum=1048576)
        require(result.returncode == 0, "test-signing-failed-private-output-retained")
        require(tool_inventory.check(tool_root, descriptor, "linux-x86_64") == inventory,
                "test-signer-inventory-changed")
        require(build.accepted(root, saved)[1] == receipt, "test-build-changed-during-signing")
        state.atomic(root, "test-signing-receipt.json", _observe(target, intent))
    # A partial signing attempt is never reported as completed or silently
    # replaced. Its exact private directory remains available for owned purge.
    return selected(root, receipt)


def _observe(target: Path, intent: dict) -> dict:
    record = decode(paths.read(target, "release-set.json"))
    require(record.get("schemaVersion") == "latent.capsule.demo.v1" and record.get("tenant") == "examples"
            and record.get("trust") == "isolated-short-lived-demo-only"
            and isinstance(record.get("releases"), list) and len(record["releases"]) == 1 + len(intent.get("dependencies", [])),
            "test-signing-result-scope")
    expected = [intent, *intent.get("dependencies", [])]
    require(len({item["component"] for item in expected}) == len(expected), "test-signing-distinct-components-required")
    ordered = []
    for item in expected:
        matching = [entry for entry in record["releases"] if entry["componentDigest"] == item["component"]]
        require(len(matching) == 1, "test-signing-component-mismatch")
        identifier(matching[0]["name"])
        ordered.append(matching[0])
    require(len({item["name"] for item in ordered}) == len(ordered), "test-signing-distinct-names-required")
    release = ordered[0]
    require(release["componentDigest"] == intent["component"], "test-signing-component-mismatch")
    require(record["policyDigest"] == digest(paths.read(target, "policy.json")), "test-signing-policy-digest")
    # Retain the exact exported file set. The ordinary package reader and
    # admission verifier still validate every byte and detached association.
    from . import snapshot
    inventory, _ = snapshot.observe(target, ["policy.json", "release-set.json", *[item["name"] for item in ordered]])
    return {**intent, "trust": record["trust"], "expiresAtUnixSeconds": record["expiresAtUnixSeconds"],
            "policySha256": record["policyDigest"], "name": release["name"],
            "packageDigest": release["packageDigest"], "inventory": inventory["identity"],
            **({"dependencyPackages": [{**item, "name": signed["name"], "packageDigest": signed["packageDigest"]}
                                      for item, signed in zip(intent["dependencies"], ordered[1:], strict=True)]}
               if "dependencies" in intent else {})}


def selected(root: Path, build_receipt: dict) -> dict:
    require((root / "test-signing-receipt.json").exists(), "test-signing-incomplete-use-new-workspace")
    receipt = state.load(root, "test-signing-receipt.json")
    intent = state.load(root, "test-signing-intent.json")
    if "dependencies" in intent:
        from .local_service_fixture import signing_input
        _source, _descriptor, child = signing_input(root)
        require(intent["dependencies"] == [{"source": child["source"], "attempt": child["attempt"],
                                           "component": child["artifacts"]["component"]}], "signed-test-dependency-changed")
    require(receipt["source"] == build_receipt["source"] and receipt["attempt"] == build_receipt["attempt"]
            and receipt["component"] == build_receipt["artifacts"]["component"],
            "signed-test-build-changed-use-new-workspace")
    require(receipt == _observe(root / "test-signing", intent), "signed-test-fixture-modified")
    require(type(receipt["expiresAtUnixSeconds"]) is int and time.time() < receipt["expiresAtUnixSeconds"],
            "signed-test-fixture-expired-use-new-workspace")
    return receipt


def dependency_selected(root: Path, build_receipt: dict) -> dict:
    _source, owner = build.accepted(root, state.load(root, "project.json"))
    receipt = selected(root, owner)
    matching = [item for item in receipt.get("dependencyPackages", [])
                if item["source"] == build_receipt["source"] and item["attempt"] == build_receipt["attempt"]
                and item["component"] == build_receipt["artifacts"]["component"]]
    require(len(matching) == 1, "signed-test-dependency-not-selected")
    return {**receipt, **matching[0]}
