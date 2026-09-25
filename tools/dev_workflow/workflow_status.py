"""Bounded last-confirmed identities, separate from live node readiness."""
from pathlib import Path

from . import build_control, state


def observe(root: Path) -> dict:
    def optional(name):
        return state.load(root, name) if (root / name).exists() else None
    project = optional("project.json")
    accepted = optional("last-build.json")
    operations = optional("operations.json")
    pending = operations.get("pending") if operations else None
    receipt = accepted["receipt"] if accepted else {}
    result = {"selectedSource": project["snapshot"] if project else None,
        "lastAcceptedBuild": {name: receipt.get(name) for name in ("source", "recipe", "attempt", "buildKey")} if accepted else None,
        "lastConfirmedPublication": optional("last-publication.json"),
        "lastConfirmedDeployment": optional("last-deployment.json"),
        "pendingOperation": {name: pending[name] for name in ("id", "kind", "node", "tenant", "requestDigest", "intent")} if pending else None,
        "buildProcess": build_control.status(root)}
    from .local_service_fixture import CHILD
    if (root / "local-service-build.json").exists() or (root / CHILD / "project.json").exists():
        child = root / CHILD
        # One fixed child only; do not recurse through arbitrary fixture state.
        operations = state.load(child, "operations.json") if (child / "operations.json").exists() else {}
        pending = operations.get("pending")
        result["localService"] = {"pendingOperation": {key: pending[key] for key in
            ("id", "kind", "node", "tenant", "requestDigest", "intent")} if pending else None,
            "lastConfirmedDeployment": state.load(child, "last-deployment.json") if (child / "last-deployment.json").exists() else None,
            "buildProcess": build_control.status(child)}
    return result
