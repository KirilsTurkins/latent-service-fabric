#!/usr/bin/env python3
"""Opt-in Cargo observations; never a replacement for test/artifact qualification.

Use the existing TestRun stage/descendant owner. Cargo JSON freshness is reported
as artifact records, not an invented count of compiler processes. Fingerprint
contents and environment values are never published. Normal ci_cargo execution
and cache policy are deliberately unchanged.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import ci_cargo, ci_cargo_cache
from tools.owned_test_process import ProcessFailure
from tools.test_run import TestRun, redact

SCHEMA = "latent.ci.cargo-observation.v1"
MAX_BYTES = 16 * 1024 * 1024
MAX_FILES = 20000
MAX_LINE = 1024 * 1024
TIME_FORMAT = "elapsedSeconds=%e\nuserSeconds=%U\nsystemSeconds=%S\nmaximumChildRssKiB=%M\nexitCode=%x"


def atomic_json(path: Path, value: object) -> None:
    encoded = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    if len(encoded) > MAX_BYTES:
        raise ValueError("observation-byte-limit")
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".observation-", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def output_directory(path: Path, repo: Path) -> Path:
    """Only fresh diagnostic directories; never overwrite sources or old evidence."""
    absolute = path.absolute()
    if any(parent.is_symlink() for parent in (absolute, *absolute.parents)):
        raise ValueError("linked-observation-directory")
    repo = repo.resolve()
    if absolute.is_relative_to(repo) and not absolute.is_relative_to(repo / "target"):
        raise ValueError("in-checkout-observations-must-be-under-target")
    absolute.mkdir(parents=True, exist_ok=False)
    return absolute


def fingerprint_snapshot(target: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    total = 0
    if any(p.is_symlink() for p in (target, *target.parents)):
        raise ValueError("linked-fingerprint-target")
    # Exact Cargo host/target roots, not arbitrary recursively discovered trees.
    roots = [target / "debug/.fingerprint"]
    if target.exists():
        roots += [child / "debug/.fingerprint" for child in target.iterdir()
                  if child.is_dir() and not child.is_symlink() and child.name not in {"debug", "release"}]
    for root in roots:
        if not root.exists():
            continue
        if root.is_symlink() or root.parent.is_symlink():
            raise ValueError("linked-fingerprint-root")
        for path in root.glob("*/*.json"):
            if len(result) >= MAX_FILES or path.is_symlink() or path.parent.is_symlink() or not path.is_file():
                raise ValueError("fingerprint-file-limit-or-link")
            size = path.stat().st_size
            total += size
            if size > MAX_LINE or total > MAX_BYTES:
                raise ValueError("fingerprint-byte-limit")
            data = path.read_bytes()
            if len(data) != size:
                raise ValueError("fingerprint-changed-during-observation")
            result[path.relative_to(target).as_posix()] = hashlib.sha256(data).hexdigest()
    return result


def observed_argv(invocation: ci_cargo.Invocation, configuration: str) -> list[str]:
    argv = invocation.command(configuration, timings=True)
    if invocation.args[0] == "fmt":
        raise ValueError("format-is-not-a-build-observation")
    separator = argv.index("--") if "--" in argv else len(argv)
    if not any(arg.startswith("--message-format") for arg in argv[:separator]):
        argv.insert(separator, "--message-format=json,json-render-diagnostics")
    return argv


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate-cargo-json-key")
        value[key] = item
    return value


def cargo_records(raw: bytes) -> tuple[list[dict], list[dict]]:
    if len(raw) > MAX_BYTES:
        raise ValueError("cargo-observation-output-limit")
    records, units = [], []
    finished = False
    for line in raw.splitlines():
        if len(line) > MAX_LINE:
            raise ValueError("cargo-observation-line-limit")
        if not line.startswith(b'{"'):
            continue  # libtest and fingerprint diagnostics are not Cargo JSON.
        try:
            record = json.loads(line, object_pairs_hook=unique_object)
        except json.JSONDecodeError:
            continue  # User tests may legitimately print a non-JSON line.
        if not isinstance(record, dict) or record.get("reason") not in {
                "compiler-artifact", "compiler-message", "build-script-executed", "build-finished"}:
            continue
        if finished:
            raise ValueError("cargo-record-after-build-finished")
        if len(records) >= MAX_FILES:
            raise ValueError("cargo-observation-record-limit")
        records.append(record)
        if record["reason"] == "compiler-artifact":
            if (type(record.get("fresh")) is not bool or not isinstance(record.get("target"), dict)
                    or not isinstance(record.get("profile"), dict)
                    or not isinstance(record.get("features"), list)
                    or not isinstance(record.get("package_id"), str)):
                raise ValueError("invalid-cargo-artifact-record")
            # Paths/flags remain private; content-address the full observed unit.
            material = {name: record.get(name) for name in ("package_id", "target", "profile", "features", "filenames")}
            units.append({"identity": ci_cargo_cache.canonical_digest(material),
                          "target": record["target"].get("name"),
                          "kind": record["target"].get("kind"),
                          "profile": record["profile"], "features": record["features"],
                          "fresh": record["fresh"]})
        if record["reason"] == "build-finished":
            finished = True
            if record.get("success") is not True:
                raise ValueError("cargo-build-did-not-complete")
    if not finished or not units:
        raise ValueError("cargo-build-completion-or-artifacts-missing")
    return records, units


def time_metrics(path: Path) -> dict:
    if not path.is_file() or path.stat().st_size > 4096:
        raise ValueError("gnu-time-observation-missing-or-oversized")
    result = {}
    for line in path.read_text().splitlines():
        name, separator, raw = line.partition("=")
        if not separator or name not in {"elapsedSeconds", "userSeconds", "systemSeconds", "maximumChildRssKiB", "exitCode"}:
            continue
        if name in result:
            raise ValueError("duplicate-gnu-time-field")
        value = float(raw)
        if not math.isfinite(value) or value < 0:
            raise ValueError("invalid-gnu-time-value")
        result[name] = value
    if len(result) != 5:
        raise ValueError("incomplete-gnu-time-observation")
    result["rssDefinition"] = "GNU time maximum child RSS; not simultaneous process-tree RSS"
    return result


def observe(invocation: ci_cargo.Invocation, *, repo: Path, output: Path,
            configuration: str = "current", environment: dict[str, str] | None = None,
            timeout: int = 3600, inventory: Path | None = None,
            target: Path | None = None) -> dict:
    repo = repo.resolve()
    if not 1 <= timeout <= 7200:
        raise ValueError("observation-timeout-limit")
    argv = observed_argv(invocation, configuration)
    if inventory is not None:
        inventory = inventory.absolute()
        if (not invocation.inventory
                or any(p.is_symlink() for p in (inventory, *inventory.parents))
                or inventory.is_relative_to(repo) and not inventory.is_relative_to(repo / "target")):
            raise ValueError("unsafe-inventory-destination")
        inventory.unlink(missing_ok=True)
    output = output_directory(output, repo)
    env = dict(os.environ if environment is None else environment)
    env.update(CARGO_TERM_COLOR="never", CARGO_LOG="cargo::core::compiler::fingerprint=debug")
    target = target or Path(env.get("CARGO_TARGET_DIR", str(repo / "target")))
    if not target.is_absolute():
        target = repo / target
    if any(parent.is_symlink() for parent in (target, *target.parents)):
        raise ValueError("linked-cargo-target-directory")
    item = {"schemaVersion": SCHEMA, "invocation": asdict(invocation),
            "configuration": configuration, "passed": False,
            "environmentDigest": ci_cargo_cache.canonical_digest(ci_cargo_cache.environment_identity(env)),
            "metrics": None, "units": [], "fingerprints": None}
    # No shell, no user-supplied command, no second process owner.
    run = TestRun("cargo-" + invocation.name, {"timeoutSeconds": timeout}, repo=repo,
                  reproduction={"recipe": invocation.name}, diagnostic_root=output / "stages")
    try:
        with run:
            run.source_identity()
            run.mark("fingerprint-before")
            before = fingerprint_snapshot(target)
            run.mark("cargo-command")
            timer = Path("/usr/bin/time")
            command = [str(timer), "-f", TIME_FORMAT, "-o", str(output / "time.txt"), *argv] if timer.is_file() else argv
            result = run.command(command, timeout=timeout, maximum=MAX_BYTES, env=env, check=False)
            # The bounded owner captured private output. Publish only redacted text.
            (output / "cargo.log").write_text(redact(result.output.decode("utf-8", "replace"),
                (str(repo), str(Path.home())), run.secrets), encoding="utf-8")
            item["exitCode"] = result.returncode
            item["metrics"] = time_metrics(output / "time.txt") if timer.is_file() else None
            run.mark("fingerprint-after")
            after = fingerprint_snapshot(target)
            item["fingerprints"] = {"before": before, "after": after,
                "changed": sorted(name for name, digest in after.items() if before.get(name) != digest),
                "removed": sorted(set(before) - set(after))}
            if result.returncode != 0:
                raise ProcessFailure("assertion-failure", "cargo-command-failed", result)
            records, units = cargo_records(result.output)
            item["units"] = units
            item["freshArtifactRecords"] = sum(unit["fresh"] for unit in units)
            item["builtArtifactRecords"] = sum(not unit["fresh"] for unit in units)
            if inventory is not None:
                # This is the existing preparation handoff, NOT executable trust.
                inventory.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=inventory.parent, delete=False) as stream:
                    temporary = Path(stream.name)
                    try:
                        stream.write(b"".join(json.dumps(row).encode() + b"\n" for row in records))
                        stream.flush()
                        ci_cargo.validate_inventory(temporary)
                        temporary.replace(inventory)
                    finally:
                        temporary.unlink(missing_ok=True)
            run.mark("retain-cargo-timings")
            timings = target / "cargo-timings/cargo-timing.html"
            if timings.is_file():
                if timings.is_symlink() or timings.stat().st_size > MAX_BYTES:
                    raise ValueError("cargo-timings-file-limit-or-link")
                shutil.copyfile(timings, output / "cargo-timing.html")
        item["passed"] = True
        return item
    finally:
        item["stageDiagnostic"] = run.record
        atomic_json(output / "observation.json", item)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recipe", choices=tuple(ci_cargo.RECIPES))
    parser.add_argument("--configuration", choices=ci_cargo.CONFIGURATIONS, default="current")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--inventory", type=Path)
    args = parser.parse_args()
    try:
        invocations = ci_cargo.RECIPES[args.recipe]
        if any(row.inventory for row in invocations) != (args.inventory is not None):
            raise ValueError("inventory-required-only-for-prepare")
        if args.inventory is not None:
            destination = args.inventory.absolute()
            if (any(p.is_symlink() for p in (destination, *destination.parents))
                    or destination.is_relative_to(ci_cargo.ROOT) and not destination.is_relative_to(ci_cargo.ROOT / "target")):
                raise ValueError("unsafe-inventory-destination")
            destination.unlink(missing_ok=True)
        for invocation in invocations:
            observe(invocation, repo=ci_cargo.ROOT, output=args.output / invocation.name,
                    configuration=args.configuration, inventory=args.inventory if invocation.inventory else None)
        return 0
    except (ProcessFailure, OSError, ValueError) as error:
        print("Cargo observation failed: " + str(error), file=sys.stderr)
        if isinstance(error, ProcessFailure) and error.result and error.result.returncode:
            status = error.result.returncode
            return status if status > 0 else 128 - status
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
