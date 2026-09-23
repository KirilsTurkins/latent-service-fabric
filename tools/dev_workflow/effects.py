"""Idempotent local consequences of a confirmed original remote operation."""
from pathlib import Path

from . import state
from .common import require


def settle(root: Path, operation: dict, result: dict) -> None:
    if operation["kind"] == "invoke" or result["category"] != "success":
        return
    data, intent = result["data"], operation["intent"]
    receipt = data.get("receipt", data.get("operation"))
    require(isinstance(receipt, dict) and receipt.get("operationId") == operation["id"]
            and receipt.get("tenant") == operation["tenant"], "confirmed-effect-receipt-required")
    for name in ("expectedGeneration", "expectedStateVersion", "componentDigest"):
        if name in intent:
            require(receipt.get(name) == intent[name], "confirmed-effect-input-mismatch")
    publication = receipt.get("publication")
    require(isinstance(publication, dict) and publication.get("tenant") == operation["tenant"]
            and isinstance(publication.get("id"), str), "confirmed-publication-scope-required")
    retained = {"source": intent["source"], "componentDigest": intent["componentDigest"],
                "publication": publication["id"], "operation": operation["id"]}
    retained.update({name: intent[name] for name in ("attempt", "buildKey", "publicationInput") if name in intent})
    if operation["kind"] == "release":
        require(receipt.get("disposition") == "RELEASE_OPERATION_DISPOSITION_COMMITTED",
                "committed-publication-required")
        state.atomic(root, "last-publication.json", retained)
    else:
        require(publication["id"] == intent["publication"] and receipt.get("deploymentId") == intent["deployment"],
                "confirmed-deployment-target-mismatch")
        generation = receipt.get("objectGeneration")
        require(isinstance(generation, str) and generation.isdecimal()
                and int(generation) == int(intent["expectedGeneration"]) + 1, "confirmed-deployment-generation")
        require(data.get("durability") in {"confirmed", "DEPLOYMENT_DURABILITY_CONFIRMED"},
                "deployment-durability-unconfirmed")
        state.atomic(root, "last-deployment.json", {**retained, "generation": generation, "deployment": intent["deployment"]})
