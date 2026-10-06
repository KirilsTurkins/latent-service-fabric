"""Linux-only removal of exact recorded development outputs, never project sources."""
from pathlib import Path

from . import paths, state
from .common import require


def snapshot_bound(directory: Path) -> int:
    from . import snapshot
    name = 'snapshot.json' if (directory / 'snapshot.json').exists() else 'snapshot-intent.json'
    record = state.load(directory, name)
    snapshot.validate(record)
    require(record['identity'] == 'sha256:' + directory.name, 'snapshot-owner-identity')
    return 8192 + (record['capturedInputs']['objectCount'] + 512 if 'capturedInputs' in record else 0)


def prune_snapshots(root: Path, *, incoming: str) -> None:
    from tools.native_runtime import files
    directory = root / "snapshots"
    if not directory.exists():
        return
    protected = {incoming}
    for name in ("last-deployment.json", "last-build.json", "project.json"):
        if (root / name).exists():
            value = state.load(root, name)
            protected.add(value.get("snapshot", value.get("source", value.get("receipt", {}).get("source"))))
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
        files.remove_tree(path, maximum=snapshot_bound(path))
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
    require(status["state"] in {"stopped", "purged"}, "stop-and-confirm-cleanup-before-purge")
    from . import fixture_cleanup
    # Validate every private fixture before deleting any owned runtime or build
    # state. Reject an existing foreign file or link before the first removal.
    fixtures = fixture_cleanup.plan(root)
    from . import local_service_fixture
    local_service_fixture.purge(root)
    builds = root / "builds"
    if builds.exists():
        from . import build_cache
        attempts = list(builds.iterdir())
        require(len(attempts) <= build_cache.MAX_ATTEMPTS, "build-cache-entry-limit")
        for attempt in attempts:
            require(build_cache.owner(attempt)["state"] not in {"running", "uncertain"},
                    "build-cleanup-unconfirmed-inspect-owned-workspace")
        files.remove_tree(builds, maximum=(build_cache.MAX_ENTRIES + 8) * build_cache.MAX_ATTEMPTS)
    layout = Layout.local(root / "runtime")
    installed = lifecycle.read_state(layout)
    if installed is None:
        require(not layout.prefix.exists(), "interrupted-native-install-requires-explicit-resume")
        receipt = {"state": "not-installed"}
    else:
        if installed["status"] not in {"removed", "purged"}:
            lifecycle.remove(layout)
        receipt = lifecycle.remove(layout, purge=installed["installationId"])
    snapshots = root / "snapshots"
    if snapshots.exists():
        entries = list(snapshots.iterdir())
        require(len(entries) <= 4, 'snapshot-retention-inventory-invalid')
        files.remove_tree(snapshots, maximum=sum(snapshot_bound(path) for path in entries) + 4)
    from .tool_install import purge as purge_tools
    purge_tools(root)
    assets = root / "assets"
    if assets.exists():
        files.remove_tree(assets, maximum=256)
    captures = root / 'captures'
    if captures.exists():
        from . import assets as transfers, captured_inputs
        entries = list(captures.iterdir())
        require(len(entries) <= 4, 'captured-input-retention-inventory-invalid')
        for path in entries:
            value = transfers.manifest(state.load(path, 'transfer.json'))
            require(value.get('domain') == captured_inputs.DOMAIN and value['identity'] == 'sha256:' + path.name,
                    'captured-input-cleanup-owner')
        files.remove_tree(captures, maximum=64)
    if (root / "test-profile-plan.json").exists():
        paths.read(root, "test-profile-plan.json")
        (root / "test-profile-plan.json").unlink()
    if (root / "test-signing").exists():
        require(root.name.startswith("test-") and (root / "test-signing-intent.json").exists(), "test-signing-owner-required")
        paths.read(root, "test-signing-intent.json")
        files.remove_tree(root / "test-signing", maximum=8192)
    removed_fixtures = fixture_cleanup.purge(root, fixtures)
    state.atomic(root, "lifecycle.json", {"state": "purged", "dataRetained": False, "reaped": True})
    return {"workspace": workspace, "state": "purged", "runtime": receipt, "sourceTreeRetained": True,
            "fixtureDirectoriesRemoved": removed_fixtures}
