"""Linux-only removal of exact recorded development outputs, never project sources."""
from pathlib import Path

from . import paths, state
from .common import require


def prune_snapshots(root: Path, *, incoming: str) -> None:
    from tools.native_runtime import files
    directory = root / "snapshots"
    if not directory.exists():
        return
    protected = {incoming}
    for name in ("last-deployment.json", "last-build.json", "project.json"):
        if (root / name).exists():
            value = state.load(root, name)
            protected.add(value.get("source", value.get("snapshot", value.get("receipt", {}).get("source"))))
    if (root / "operations.json").exists():
        pending = state.load(root, "operations.json")["pending"]
        if pending:
            protected.add(pending["intent"].get("source"))
    candidates = sorted(directory.iterdir(), key=lambda path: path.name)
    require(len(candidates) <= 4, "snapshot-retention-inventory-invalid")
    for path in candidates:
        if len(candidates) < 4:
            break
        if "sha256:" + path.name in protected:
            continue
        require(path.parent == directory and len(path.name) == 64 and all(c in "0123456789abcdef" for c in path.name),
                "unowned-snapshot-path")
        record = state.load(path, "snapshot.json")
        require(record["identity"] == "sha256:" + path.name, "snapshot-owner-identity")
        files.remove_tree(path, maximum=8192)
        candidates = [item for item in candidates if item != path]


def purge(root: Path, workspace: str, confirmation: str) -> dict:
    from tools.native_runtime import files, lifecycle
    from tools.native_runtime.layout import Layout
    from . import service
    require(workspace == confirmation, "confirm-exact-workspace-required")
    try:
        status = service.request(root, "status")
    except (FileNotFoundError, ConnectionRefusedError):
        status = state.load(root, "lifecycle.json") if (root / "lifecycle.json").exists() else {"state": "stopped"}
    require(status["state"] == "stopped", "stop-and-confirm-cleanup-before-purge")
    layout = Layout.local(root / "runtime")
    installed = lifecycle.read_state(layout)
    require(installed is not None, "owned-runtime-state-required")
    if installed["status"] not in {"removed", "purged"}:
        lifecycle.remove(layout)
    receipt = lifecycle.remove(layout, purge=installed["installationId"])
    snapshots = root / "snapshots"
    if snapshots.exists():
        files.remove_tree(snapshots, maximum=32768)
    state.atomic(root, "lifecycle.json", {"state": "purged", "dataRetained": False, "reaped": True})
    return {"workspace": workspace, "state": "purged", "runtime": receipt, "sourceTreeRetained": True}
