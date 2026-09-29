#!/usr/bin/env python3
"""Real-compiler cache fault trials in a disposable, explicitly synthetic workspace.

This is a mechanism experiment, NOT a complete LSF-suite cache benchmark. Local
archive costs are not GitHub cache-service transfer costs. Neither diagnostics
nor positive test results are restored as build inputs. No shared cache is read,
written, cleared, or repaired. Failure trials never retry to green.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile
import time

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import ci_cargo, ci_cargo_observe as observations
from tools.owned_test_process import ProcessFailure, run_owned

ARCHIVE_LIMIT = 256 * 1024 * 1024
ENTRY_LIMIT = 10000
CACHE_PATHS = ("debug/.fingerprint", "debug/build", "debug/deps")
APP = "lsf-cache-probe"
DEP = "lsf-cache-dependency"


def execute(argv: list[str], repo: Path, env: dict[str, str]) -> bytes:
    result = run_owned(argv, cwd=repo, env=env, timeout=120, maximum=1024 * 1024)
    if result.returncode:
        raise ProcessFailure("assertion-failure", "probe-preparation-failed", result)
    return result.output


def fixture(root: Path) -> Path:
    app, dependency = root / "app", root / "dependency"
    for path in (app / "src", dependency / "src"):
        path.mkdir(parents=True)
    (app / "Cargo.toml").write_text('''[package]
name = "lsf-cache-probe"
version = "0.1.0"
edition = "2021"
[workspace]
[dependencies]
lsf-cache-dependency = { path = "../dependency" }
[features]
alternate = ["lsf-cache-dependency/alternate"]
[lints.rust]
unexpected_cfgs = { level = "deny", check-cfg = ['cfg(lsf_cache_probe_flag)'] }
''')
    (dependency / "Cargo.toml").write_text('''[package]
name = "lsf-cache-dependency"
version = "0.1.0"
edition = "2021"
[features]
alternate = []
''')
    (dependency / "src/lib.rs").write_text('pub fn value() -> u32 { if cfg!(feature = "alternate") { 2 } else { 1 } }\n')
    (app / "src/lib.rs").write_text('''pub fn value() -> u32 { lsf_cache_dependency::value() }
#[cfg(test)] mod tests {
    #[test] fn dependency_value_is_current() {
        let expected: u32 = std::env::var("LSF_CACHE_PROBE_EXPECTED").unwrap().parse().unwrap();
        assert_eq!(super::value(), expected);
    }
    #[test] fn compiler_flags_are_current() {
        assert_eq!(cfg!(lsf_cache_probe_flag), std::env::var("LSF_CACHE_PROBE_FLAG").unwrap() == "1");
    }
    #[test] fn debug_assertions_remain_enabled() { assert!(cfg!(debug_assertions)); }
}
''')
    return app / "Cargo.toml"


def save_archive(target: Path, archive: Path) -> dict:
    """Archive only explicit dependency paths AFTER Cargo removed the app outputs."""
    began = time.monotonic()
    if any(p.is_symlink() for p in (target, *target.parents, archive, *archive.parents)):
        raise ValueError("linked-probe-archive-path")
    files, size = [], 0
    for name in CACHE_PATHS:
        root = target / name
        if root.is_symlink() or root.parent.is_symlink():
            raise ValueError("linked-probe-cache-root")
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_symlink() or not (path.is_dir() or path.is_file()):
                raise ValueError("probe-cache-link-or-special-file")
            if path.is_file():
                size += path.stat().st_size
                files.append(path)
                if len(files) > ENTRY_LIMIT or size > ARCHIVE_LIMIT:
                    raise ValueError("probe-cache-size-limit")
                if APP in path.as_posix() or APP.replace("-", "_") in path.name:
                    raise ValueError("workspace-product-survived-probe-pruning")
    if not files:
        raise ValueError("empty-probe-dependency-cache")
    with tarfile.open(archive, "w:gz", compresslevel=1) as output:
        for path in files:
            output.add(path, arcname=path.relative_to(target).as_posix(), recursive=False)
    return {"seconds": time.monotonic() - began, "archiveBytes": archive.stat().st_size,
            "uncompressedBytes": size, "files": len(files),
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}


def restore_archive(target: Path, archive: Path, expected_digest: str) -> dict:
    """Validate the whole local archive before any extraction; no shared state."""
    began = time.monotonic()
    if any(p.is_symlink() for p in (target, *target.parents, archive, *archive.parents)) or target.exists() or archive.is_symlink() or not archive.is_file() or archive.stat().st_size > ARCHIVE_LIMIT:
        raise ValueError("invalid-probe-restore-destination-or-archive")
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected_digest:
        raise ValueError("probe-archive-integrity-failure")
    with tarfile.open(archive, "r:gz") as source:
        members, names, total = [], set(), 0
        for member in source:
            name = Path(member.name)
            if (len(members) >= ENTRY_LIMIT or not member.isfile() or name.is_absolute()
                    or ".." in name.parts or member.name in names
                    or not any(name.is_relative_to(Path(prefix)) for prefix in CACHE_PATHS)):
                raise ValueError("invalid-probe-archive-member")
            total += member.size
            if total > ARCHIVE_LIMIT:
                raise ValueError("expanded-probe-archive-limit")
            members.append(member)
            names.add(member.name)
        if not members:
            raise ValueError("empty-probe-archive")
        target.mkdir()
        source.extractall(target, members=members, filter="data")
    return {"seconds": time.monotonic() - began, "archiveBytes": archive.stat().st_size,
            "uncompressedBytes": total, "files": len(members)}


def probe(repo: Path, output: Path, *, include_msrv: bool = False) -> dict:
    output = observations.output_directory(output, repo)
    report = {"schemaVersion": "latent.ci.cargo-cache-probe.v1", "passed": False,
              "scope": "synthetic-three-test-workspace-real-compiler",
              "eligibleForDefaultPromotion": False,
              "networkTransferSeconds": None, "sharedCacheWrites": False,
              "archiveBackend": "disposable-local-tar-gzip-not-GitHub-cache",
              "samples": [], "faults": [], "toolchains": {}}
    try:
        with tempfile.TemporaryDirectory(prefix="lsf-cargo-cache-probe-") as directory:
            private = Path(directory)
            manifest = fixture(private)
            base = dict(os.environ)
            # This experiment must not inherit an ambient feature/target/flag override.
            forbidden = {"RUSTFLAGS", "RUSTDOCFLAGS", "CARGO_ENCODED_RUSTFLAGS", "CARGO_ENCODED_RUSTDOCFLAGS",
                         "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER", "RUSTC", "RUSTDOC", "CARGO_BUILD_TARGET"}
            if any(base.get(key) for key in forbidden):
                raise ValueError("probe-requires-unmodified-pinned-build-environment")
            base.update(CARGO_INCREMENTAL="0", LSF_CACHE_PROBE_EXPECTED="1", LSF_CACHE_PROBE_FLAG="0")
            report["toolchains"]["pinned"] = execute(["rustc", "-vV"], repo, base).decode().strip()
            if include_msrv:
                report["toolchains"]["msrv"] = execute(["rustc", "+" + ci_cargo.msrv_version(repo), "-vV"], repo, base).decode().strip()
            execute(["cargo", "generate-lockfile", "--manifest-path", str(manifest), "--offline"], repo, base)
            report["fixtureDigest"] = hashlib.sha256(b"".join(p.read_bytes() for p in sorted(private.rglob("*")) if p.is_file())).hexdigest()
            base_invocation = ci_cargo.Invocation("cache-probe", ("test", "--manifest-path", str(manifest),
                "--lib", "--locked", "--offline"), (APP,), "default", "host/lib;three-tests", "test",
                "disposable cache mechanism controls, not LSF qualification")

            def trial(name, invocation, env, configuration="current", allow_failure=False):
                destination = output / name
                try:
                    item = observations.observe(replace(invocation, name=name), repo=repo, output=destination,
                        configuration=configuration, environment=env, timeout=300,
                        target=Path(env["CARGO_TARGET_DIR"]))
                except ProcessFailure as error:
                    if not allow_failure or error.reason != "cargo-command-failed" or not error.result or not error.result.returncode:
                        raise
                    return {"name": name, "outcome": "clear-cargo-failure", "exitCode": error.result.returncode,
                            "observation": str(destination.relative_to(output) / "observation.json")}
                if invocation.args[0] == "test":
                    text = (destination / "cargo.log").read_text()
                    if "test result: ok. 3 passed; 0 failed; 0 ignored;" not in text:
                        raise ValueError("probe-test-selection-or-completion-mismatch")
                return {"name": name, "outcome": "passed", "exitCode": 0,
                        "observation": str(destination.relative_to(output) / "observation.json"),
                        "builtArtifactRecords": item["builtArtifactRecords"],
                        "freshArtifactRecords": item["freshArtifactRecords"], "metrics": item["metrics"],
                        "elapsedMs": item["stageDiagnostic"]["elapsedMs"]}

            for configuration in ("current", "ci-correctness"):
                target = private / ("target-" + configuration)
                env = base | {"CARGO_TARGET_DIR": str(target)}
                cold = trial(configuration + "-cold", base_invocation, env, configuration)
                prune_began = time.monotonic()
                execute(["cargo", "clean", "--manifest-path", str(manifest), "--package", APP], repo, env)
                prune_seconds = time.monotonic() - prune_began
                archive = private / (configuration + ".tar.gz")
                saved = save_archive(target, archive)
                cold.update(state="cold", configuration=configuration, save=saved, pruneSeconds=prune_seconds, restore=None)
                report["samples"].append(cold)
                for repetition in (1, 2):
                    shutil.rmtree(target)  # Only this TemporaryDirectory's products.
                    restored = restore_archive(target, archive, saved["sha256"])
                    sample = trial(configuration + "-warm-" + str(repetition), base_invocation, env, configuration)
                    if sample["freshArtifactRecords"] < 1 or sample["builtArtifactRecords"] < 1:
                        raise ValueError("probe-warm-must-reuse-dependency-and-rebuild-application")
                    sample.update(state="warm", configuration=configuration, restore=restored, save=None,
                                  archiveSavedOnce=True)
                    report["samples"].append(sample)
                if configuration == "current":
                    original_archive, original_digest = archive, saved["sha256"]
            # A fresh destination for every fault; application artifacts never restored.
            target = private / "fault-target"
            env = base | {"CARGO_TARGET_DIR": str(target)}

            def restored_target():
                if target.exists():
                    shutil.rmtree(target)
                restore_archive(target, original_archive, original_digest)

            for fault in ("corrupt-fingerprint", "corrupt-dependency-product"):
                restored_target()
                matches = list((target / "debug/.fingerprint").glob(DEP + "-*/lib-lsf_cache_dependency")) if fault == "corrupt-fingerprint" else list((target / "debug/deps").glob("liblsf_cache_dependency-*.rlib"))
                if len(matches) != 1:
                    raise ValueError("probe-fault-target-not-unique")
                matches[0].write_bytes(b"corrupted-cache-control")
                observed = trial(fault, base_invocation, env, allow_failure=True)
                if observed["outcome"] == "passed" and observed["builtArtifactRecords"] < 2:
                    raise ValueError("corrupt-product-was-not-rebuilt")
                report["faults"].append(observed)
            # Corrupt compressed archive is rejected before populating a target.
            broken = private / "broken.tar.gz"
            broken.write_bytes(original_archive.read_bytes()[:32])
            try:
                restore_archive(private / "broken-target", broken, original_digest)
            except ValueError as error:
                if str(error) != "probe-archive-integrity-failure" or (private / "broken-target").exists():
                    raise
                report["faults"].append({"name": "corrupt-local-archive", "outcome": "rejected-before-extraction"})
            else:
                raise ValueError("corrupt-archive-was-accepted")
            variants = [
                ("changed-flags", base_invocation, env | {"RUSTFLAGS": "--cfg lsf_cache_probe_flag", "LSF_CACHE_PROBE_FLAG": "1"}),
                ("changed-features", replace(base_invocation, args=(*base_invocation.args, "--features", "alternate"), features="alternate"), env | {"LSF_CACHE_PROBE_EXPECTED": "2"}),
                ("changed-target", replace(base_invocation, args=("check", "--manifest-path", str(manifest), "--locked", "--offline", "--target", "wasm32-wasip2"), targets="wasm32-wasip2/lib", profile="dev"), env),
            ]
            if include_msrv:
                variants.append(("changed-toolchain", replace(base_invocation, toolchain="msrv"), env))
            for name, invocation, changed_env in variants:
                restored_target()
                changed = trial(name, invocation, changed_env)
                if changed["builtArtifactRecords"] < 2:
                    raise ValueError("probe-change-did-not-invalidate-products")
                report["faults"].append(changed)
            restored_target()
            dep_manifest = private / "dependency/Cargo.toml"
            dep_manifest.write_text(dep_manifest.read_text().replace('version = "0.1.0"', 'version = "0.1.1"'))
            (private / "dependency/src/lib.rs").write_text('pub fn value() -> u32 { 7 }\n')
            execute(["cargo", "generate-lockfile", "--manifest-path", str(manifest), "--offline"], repo, env)
            changed = trial("changed-dependency", base_invocation, env | {"LSF_CACHE_PROBE_EXPECTED": "7"})
            if changed["builtArtifactRecords"] < 2:
                raise ValueError("changed-dependency-was-not-rebuilt")
            report["faults"].append(changed)
            shutil.rmtree(target)
            report["faults"].append(trial("absent-cache", base_invocation, env | {"LSF_CACHE_PROBE_EXPECTED": "7"}))
            report["passed"] = True
    finally:
        observations.atomic_json(output / "probe.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--include-msrv", action="store_true")
    args = parser.parse_args()
    try:
        result = probe(ci_cargo.ROOT, args.output, include_msrv=args.include_msrv)
        print(json.dumps({"passed": result["passed"], "samples": len(result["samples"]),
                          "faults": len(result["faults"]), "eligibleForDefaultPromotion": False}))
        return 0
    except (ProcessFailure, OSError, ValueError, tarfile.TarError) as error:
        print("Cargo cache mechanism probe failed: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
