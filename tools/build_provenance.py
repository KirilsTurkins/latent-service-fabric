#!/usr/bin/env python3
"""Observe a bounded maintained echo build; emit unsigned builder assertions."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import time

if __name__ == "__main__" and not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import build_echo_capsule as echo
from tools.build_observation import (build_environment, file_identity, finish_observation,
                                     public_repository, recipe_identity, resolve_tools)
from tools.build_process import BuildProcessError, run_bounded
from tools.build_process_signals import owned_cancellation
from tools.build_snapshot import (SnapshotError, canonical, capture_source, digest,
                                  git_environment, is_reparse, owned_child, portable_path,
                                  remove_owned_directory)


ROOT = Path(__file__).resolve().parents[1]
WIT_INPUTS = (
    ("examples:echo@0.1.0", "wit/echo.wit", "examples/echo-contract/wit/echo.wit",
     ["latent:context@0.1.0", "latent:log@0.1.0"]),
    ("latent:context@0.1.0", "wit/context.wit", "wit/platform/context/package.wit", []),
    ("latent:log@0.1.0", "wit/log.wit", "wit/platform/log/package.wit", []),
)


def read_small(path: Path, maximum: int = 256 * 1024) -> bytes:
    if is_reparse(path) or not path.is_file():
        raise SnapshotError("required output is not a regular file")
    with path.open("rb") as stream:
        data = stream.read(maximum + 1)
    if not data or len(data) > maximum:
        raise SnapshotError("required output exceeds its byte limit")
    return data


def check_captured_inputs(root: Path, inventory: bytes) -> None:
    for row in json.loads(inventory):
        path = root.joinpath(*row["path"].split("/"))
        owned_child(path, root)
        if row["size"] == 0:
            if is_reparse(path) or not path.is_file() or path.stat().st_size != 0:
                raise SnapshotError("captured input changed during build")
        else:
            actual = file_identity(path, "captured-source", 4 * 1024 * 1024)
            if actual["digest"] != row["digest"] or actual["size"] != row["size"]:
                raise SnapshotError("captured input changed during build")
        if os.name != "nt" and path.stat().st_mode & 0o777 != row["mode"]:
            raise SnapshotError("captured input mode changed during build")


def package_ready_inputs(source: Path, built: Path, destination: Path, component: bytes) -> None:
    """Keep only exact small packaging inputs, never the unsigned legacy receipt."""
    layers = []
    for name, role, media_type in (
        ("echo-capsule.wasm", "component", "application/wasm"),
        ("capsule.json", "capsule-manifest", "application/vnd.latent.capsule.manifest.v1+json"),
        ("contracts.json", "contracts", "application/vnd.latent.contracts.v1+json"),
    ):
        data = component if role == "component" else read_small(built / name)
        (destination / name).write_bytes(data)
        layers.append({"path": name, "source": name, "role": role, "mediaType": media_type})
    capsule = json.loads((destination / "capsule.json").read_bytes())
    if capsule["component"]["digest"] != digest(component):
        raise SnapshotError("generated capsule output does not match observed component")
    packages = []
    for identity, name, original, dependencies in WIT_INPUTS:
        data = read_small(source / original)
        target = destination / name
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(data)
        packages.append({"id": identity, "sourcePath": name, "digest": digest(data),
                         "dependencies": dependencies})
        layers.append({"path": name, "source": name, "role": "asset", "mediaType": "text/plain"})
    lock = {"formatVersion": 1, "world": echo.SOURCE_WORLD,
            "contractsDigest": digest((destination / "contracts.json").read_bytes()),
            "packages": sorted(packages, key=lambda row: row["id"])}
    (destination / "wit-lock.json").write_bytes(canonical(lock))
    layers.append({"path": "wit-lock.json", "source": "wit-lock.json", "role": "wit-lock",
                   "mediaType": "application/vnd.latent.wit-lock.v1+json"})
    recipe = {"formatVersion": 1, "kind": "capsule", "name": "echo-provenance",
              "version": capsule["component"]["version"], "entrypoint": echo.ARTIFACT_NAME,
              "annotations": {}, "layers": sorted(layers, key=lambda row: row["path"])}
    (destination / "package-source.json").write_bytes(canonical(recipe))


def observed_build(*, repository: Path, revision: str, repository_label: str,
                   target_root: Path, output: Path, verify_reproducible: bool = False,
                   legacy_output: Path | None = None) -> dict:
    staged_cleanup: list[Path] = []
    with owned_cancellation() as cancellation:
        try:
            return _observed_build(repository=repository, revision=revision,
                repository_label=repository_label, target_root=target_root, output=output,
                verify_reproducible=verify_reproducible, legacy_output=legacy_output,
                staged_cleanup=staged_cleanup, cancellation=cancellation)
        finally:
            # Also executes if the snapshot owner's __exit__ reports failed cleanup.
            with cancellation.defer():
                for staged in staged_cleanup:
                    remove_owned_directory(staged, target_root.absolute())


def copy_legacy_fixture(source: Path, destination: Path) -> None:
    """Export a bounded compatibility fixture; its build.json remains unsigned."""
    pending = [source]
    entries = total = 0
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as iterator:
            for entry in iterator:
                entries += 1
                if entries > 128:
                    raise SnapshotError("legacy fixture entry limit exceeded")
                path = Path(entry.path)
                owned_child(path, source)
                relative = portable_path(path.relative_to(source).as_posix())
                target = destination.joinpath(*relative.split("/"))
                if is_reparse(path):
                    raise SnapshotError("legacy fixture contains a filesystem link")
                if entry.is_dir(follow_symlinks=False):
                    target.mkdir()
                    pending.append(path)
                elif entry.is_file(follow_symlinks=False):
                    maximum = echo.MAX_COMPONENT_BYTES if relative == echo.ARTIFACT_NAME else 256 * 1024
                    data = read_small(path, maximum)
                    total += len(data)
                    if total > echo.MAX_COMPONENT_BYTES + 2 * 1024 * 1024:
                        raise SnapshotError("legacy fixture total byte limit exceeded")
                    target.write_bytes(data)
                else:
                    raise SnapshotError("legacy fixture contains an unsupported file")


def _observed_build(*, repository: Path, revision: str, repository_label: str,
                    target_root: Path, output: Path, verify_reproducible: bool,
                    legacy_output: Path | None,
                    staged_cleanup: list[Path], cancellation) -> dict:
    cancellation.check()
    public_repository(repository_label)
    repository = repository.resolve(strict=True)
    target_root = target_root.absolute()
    target_root.mkdir(parents=True, exist_ok=True)
    target_root = target_root.resolve(strict=True)
    output = output.absolute()
    owned_child(output, target_root)
    if output.exists():
        raise SnapshotError("provenance output directory already exists")
    if legacy_output is not None:
        legacy_output = legacy_output.absolute()
        owned_child(legacy_output, target_root)
        if (legacy_output.exists() or legacy_output == output
                or output in legacy_output.parents or legacy_output in output.parents):
            raise SnapshotError("legacy output must be a distinct fresh directory")
    original_source = echo.ROOT
    original_commands = {key: list(value) for key, value in echo._TOOL_COMMANDS.items()}
    original_environment = echo._BUILD_ENVIRONMENT
    original_deadline = echo._BUILD_DEADLINE
    recipe_before = recipe_identity(ROOT / "tools")
    staged: Path | None = None
    legacy_staged: Path | None = None
    with capture_source(repository, revision, target_root) as snapshot:
        try:
            cancellation.check()
            echo.configure_source_root(snapshot.root)
            toolchain = echo.load_toolchain()
            temporary = snapshot.root.parent / "temporary"
            temporary.mkdir()
            environment = build_environment(temporary)
            tools, tool_materials = resolve_tools(toolchain, snapshot.root, environment)
            environment["RUSTC"] = str(tools["rustc"])
            # Build artifacts are sibling to captured inputs and are removed by
            # the snapshot owner even if the maintained builder fails midway.
            build_root = snapshot.root.parent / "build"
            build_root.mkdir()
            started = int(time.time())
            monotonic_start = time.monotonic()
            echo.configure_execution(
                {"CARGO": [str(tools["cargo"])], "RUSTC": [str(tools["rustc"])],
                 "WASM_TOOLS": [str(tools["wasm-tools"])]}, environment,
                monotonic_start + 3600,
            )
            echo.verify_tool_versions(toolchain)
            echo.validate_source_contract()
            component, reproducible = echo.build_component(build_root, verify_reproducible)
            cancellation.check()
            built = build_root / "echo-output"
            echo.validate_and_stage_output(component, output_directory=built,
                reproducibility_verified=reproducible, toolchain=toolchain)
            cancellation.check()
            check_captured_inputs(snapshot.root, snapshot.inventory)
            if recipe_identity(ROOT / "tools") != recipe_before:
                raise SnapshotError("build recipe changed during observation")
            for record in tool_materials:
                if file_identity(tools[record["name"]], record["name"]) != record:
                    raise SnapshotError("build tool changed during observation")
            materials = [recipe_before, *tool_materials,
                file_identity(snapshot.root / "Cargo.lock", "dependency-lock", 4 * 1024 * 1024),
                file_identity(snapshot.root / "tools/toolchain.toml", "toolchain-config", 256 * 1024)]
            observation = finish_observation(
                repository=repository_label, revision=snapshot.revision,
                inventory=snapshot.inventory, component=component, materials=materials,
                started=started, finished=int(time.time()), elapsed=time.monotonic() - monotonic_start,
                reproducible=reproducible,
            )
            output.parent.mkdir(parents=True, exist_ok=True)
            owned_child(output, target_root)
            with cancellation.defer():
                staged = Path(tempfile.mkdtemp(prefix=".provenance-output-", dir=output.parent))
                staged_cleanup.append(staged)
            owned_child(staged, target_root)
            package_ready_inputs(snapshot.root, built, staged, component)
            cancellation.check()
            (staged / "observation.json").write_bytes(canonical(observation))
            if legacy_output is not None:
                legacy_output.parent.mkdir(parents=True, exist_ok=True)
                owned_child(legacy_output, target_root)
                with cancellation.defer():
                    legacy_staged = Path(tempfile.mkdtemp(prefix=".legacy-output-", dir=legacy_output.parent))
                    staged_cleanup.append(legacy_staged)
                owned_child(legacy_staged, target_root)
                copy_legacy_fixture(built, legacy_staged)
                cancellation.check()
        except BaseException:
            if staged is not None:
                with cancellation.defer():
                    remove_owned_directory(staged, target_root)
            raise
        finally:
            echo.configure_source_root(original_source)
            echo.configure_execution(original_commands, original_environment, original_deadline)
    # Publish only after successful cleanup of captured source/build intermediates.
    if staged is None:
        raise SnapshotError("build observation output is unavailable")
    publications = [(staged, output)]
    if legacy_staged is not None:
        publications.append((legacy_staged, legacy_output))
    published = []
    try:
        for source, destination in publications:
            cancellation.check()
            owned_child(source, target_root)
            owned_child(destination, target_root)
            if destination.exists():
                raise SnapshotError("build output directory already exists")
            with cancellation.defer():
                source.rename(destination)
                published.append(destination)
    except BaseException:
        # Destinations were fresh and are owned by this operation. A failure in
        # the optional second export must not leave an apparent success record.
        with cancellation.defer():
            for destination in published:
                remove_owned_directory(destination, target_root)
        raise
    return observation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", help="exact committed Git identity; defaults to current HEAD")
    parser.add_argument("--repository", required=True, help="public operator-asserted HTTPS repository label")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--legacy-output-dir", type=Path,
                        help="optional fresh destination for the unsigned legacy echo fixture")
    parser.add_argument("--verify-reproducible", action="store_true")
    arguments = parser.parse_args()
    try:
        target = echo.resolve_target_root()
        output = arguments.output_dir or target / "capsules/echo-provenance"
        if not output.is_absolute():
            output = ROOT / output
        legacy_output = arguments.legacy_output_dir
        if legacy_output is not None and not legacy_output.is_absolute():
            legacy_output = ROOT / legacy_output
        revision = arguments.revision
        if revision is None:
            result = run_bounded(["git", "rev-parse", "--verify", "HEAD^{commit}"], cwd=ROOT,
                                 env=git_environment(), timeout_seconds=30, max_output_bytes=1024)
            revision = result.stdout.decode("ascii").strip()
        observation = observed_build(repository=ROOT, revision=revision,
            repository_label=arguments.repository, target_root=target, output=output,
            verify_reproducible=arguments.verify_reproducible, legacy_output=legacy_output)
    except (SnapshotError, BuildProcessError, echo.BuildError, OSError, ValueError, KeyError,
            tarfile.TarError):
        print("error: observed build failed; no observation published", file=sys.stderr)
        return 1
    print(json.dumps({"componentDigest": observation["componentDigest"],
                      "sourceSnapshotDigest": observation["source"]["snapshotDigest"],
                      "revision": observation["source"]["revision"],
                      "observation": "observation.json", "packageSource": "package-source.json"},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
