"""Bind application-test evidence to a confirmed, still-selected deployment."""
from pathlib import Path

from . import state
from .common import require


def target(root: Path, descriptor: dict, receipt: dict, cli) -> tuple[dict, dict]:
    require((root / "last-deployment.json").exists(), "test-requires-confirmed-deployment")
    deployed = state.load(root, "last-deployment.json")
    require(deployed["source"] == receipt["source"]
            and deployed["componentDigest"] == receipt["artifacts"]["component"],
            "test-build-is-not-confirmed-deployment")
    observed = cli.call("deployment", "get", deployed["deployment"], "--operation-snapshot")
    require(observed["outcomeKnown"] and observed["category"] == "success",
            "test-deployment-observation-unavailable")
    current = observed["data"].get("deployment")
    require(isinstance(current, dict) and current["generation"] == deployed["generation"],
            "test-deployment-changed-no-invocation")
    manifest = current["manifest"]
    require(manifest["metadata"]["tenant"] == descriptor["tenant"]
            and manifest["metadata"]["name"] == deployed["deployment"]
            and manifest["spec"]["service"] == descriptor["service"]
            and manifest["spec"]["publication"] == deployed["publication"]
            and manifest["spec"]["release"] == deployed["componentDigest"],
            "test-deployment-target-mismatch")
    generation = observed["data"]["routeGeneration"]
    require(isinstance(generation, str) and generation.isdecimal(), "test-route-generation-required")
    return deployed, {"publicationId": deployed["publication"], "releaseDigest": deployed["componentDigest"],
                      "routeGeneration": generation}
