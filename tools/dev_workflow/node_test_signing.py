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
    if (root / "test-signing-intent.json").exists():
        require(state.load(root, "test-signing-intent.json") == intent, "test-signing-input-changed-use-new-workspace")
    else:
        require(not target.exists(), "test-signing-output-already-exists")
        state.atomic(root, "test-signing-intent.json", intent)
        with paths.opened(tool_root, pin["path"]):
            result = process.run([str(tool_root / pin["path"]), "demo-sign", str(target),
                                  str(source / descriptor["build"]["outputRoot"])], root,
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
            and isinstance(record.get("releases"), list) and len(record["releases"]) == 1,
            "test-signing-result-scope")
    release = record["releases"][0]
    identifier(release["name"])
    require(release["componentDigest"] == intent["component"], "test-signing-component-mismatch")
    require(record["policyDigest"] == digest(paths.read(target, "policy.json")), "test-signing-policy-digest")
    # Retain the exact exported file set. The ordinary package reader and
    # admission verifier still validate every byte and detached association.
    from . import snapshot
    inventory, _ = snapshot.observe(target, ["policy.json", "release-set.json", release["name"]])
    return {**intent, "trust": record["trust"], "expiresAtUnixSeconds": record["expiresAtUnixSeconds"],
            "policySha256": record["policyDigest"], "name": release["name"],
            "packageDigest": release["packageDigest"], "inventory": inventory["identity"]}


def selected(root: Path, build_receipt: dict) -> dict:
    require((root / "test-signing-receipt.json").exists(), "test-signing-incomplete-use-new-workspace")
    receipt = state.load(root, "test-signing-receipt.json")
    intent = state.load(root, "test-signing-intent.json")
    require(receipt["source"] == build_receipt["source"] and receipt["attempt"] == build_receipt["attempt"]
            and receipt["component"] == build_receipt["artifacts"]["component"],
            "signed-test-build-changed-use-new-workspace")
    require(receipt == _observe(root / "test-signing", intent), "signed-test-fixture-modified")
    require(type(receipt["expiresAtUnixSeconds"]) is int and time.time() < receipt["expiresAtUnixSeconds"],
            "signed-test-fixture-expired-use-new-workspace")
    return receipt
