"""Run the selected provider's real-peer unit controls; enable no TLS profile."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import host_stream_tls_provider as provider
from tools import ci_rust_artifacts as artifacts
from tools import ci_suite_discovery as discovery
from tools import ci_suite_inventory as registry
from tools.owned_test_process import ProcessFailure, run_owned
from tools.rust_capsule_project import fresh
from tools.test_run import digest, redact

SUITE = "latent-streams.lib.latent-streams"
TLS_CASES = frozenset("tests::tls::" + name for name in (
    "direct_host_tls_validates_peer_transfers_and_retires_original_charges",
    "wrong_tls_hostname_fails_closed_without_cleartext_fallback",
    "stalled_tls_handshake_uses_original_deadline_and_physical_owner",
    "tls_rotation_preserves_pending_original_owner_until_peer_socket_retires",
))
DENIAL = "tests::tls::unqualified_tls_installation_fails_before_contact_and_leaves_no_owner"


def digest_file(path: Path, maximum: int) -> str:
    return digest(path, maximum).removeprefix("sha256:")


def snapshot(root: Path) -> dict:
    selected = provider.verify(root)
    names = {"Cargo.toml", "Cargo.lock", "rust-toolchain.toml", provider.RECORD,
             "crates/latent-streams/Cargo.toml", "tools/ci/suites.d/outbound-streams.json",
             "tools/qualify_host_stream_tls_provider.py"}
    names.update(path.relative_to(root).as_posix()
                 for path in (root / "crates/latent-streams/src").rglob("*.rs"))
    if not 10 <= len(names) <= 128:
        raise ValueError("tls-provider-reference-source-count")
    return {"selectedProvider": selected,
            "inputs": {name: digest_file(root / name, 4 * 1024 * 1024) for name in sorted(names)}}


def suite_contract(root: Path) -> dict:
    data = registry.load(root / "tools/ci/suites.json")
    matches = [row for row in data["suites"] if row["id"] == SUITE]
    if len(matches) != 1:
        raise ValueError("tls-provider-reference-suite-owner")
    row = matches[0]
    if (row["minimumCases"] != 23 or len(row["expectedCases"]) != 23
            or not (TLS_CASES | {DENIAL}) <= set(row["expectedCases"])
            or row["expectedIgnored"] or row["ignoredLeaves"] or row["timeoutSeconds"] != 900):
        raise ValueError("tls-provider-reference-suite-contract")
    return row


def outcomes(raw: bytes, expected: set[str]) -> list[str]:
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError("tls-provider-reference-result-bound")
    passed = re.findall(rb"^test ([a-zA-Z0-9_:]+) \.\.\. ok$", raw, re.M)
    names = [name.decode("ascii") for name in passed]
    totals = re.findall(rb"^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out;", raw, re.M)
    if (len(names) != len(expected) or set(names) != expected
            or totals != [(str(len(expected)).encode(), b"0", b"0", b"0", b"0")]):
        raise ValueError("tls-provider-reference-missing-or-failed-case")
    return sorted(names)


def compiled_tls(root: Path, inventory: Path, target: Path) -> dict:
    rows = discovery.artifact_records(inventory)
    selected = {}
    for label, manifest in (("boundedProvider", root / provider.PROVIDER / "Cargo.toml"),
                            ("upstreamPeer", None)):
        matches = [row for row in rows
                   if row.get("target", {}).get("kind") == ["lib"]
                   and row["target"].get("name") == "rustls"
                   and (Path(row["manifest_path"]).resolve() == manifest.resolve() if manifest
                        else row["package_id"].startswith("registry+")
                        and row["package_id"].endswith("#rustls@0.23.46"))]
        if len(matches) != 1:
            raise ValueError("tls-provider-reference-compiled-identity")
        row = matches[0]
        libraries = [Path(name) for name in row["filenames"] if name.endswith(".rlib")]
        if len(libraries) != 1 or not libraries[0].resolve().is_relative_to((target / "debug/deps").resolve()):
            raise ValueError("tls-provider-reference-compiled-path")
        selected[label] = {"packageId": row["package_id"], "features": row["features"],
                           "librarySha256": digest_file(libraries[0], 128 * 1024 * 1024)}
    if set(selected["boundedProvider"]["features"]) != {"ring", "std", "tls12"}:
        raise ValueError("tls-provider-reference-feature-profile")
    return selected


def qualify(root: Path, output: Path, revision: str) -> dict:
    target = root / "target"
    environment = {**os.environ, "CARGO_BUILD_JOBS": "2", "CARGO_INCREMENTAL": "0",
                   "CARGO_TARGET_DIR": str(target)}
    artifacts.require_source(root, revision, environment)
    before = snapshot(root)
    suite = suite_contract(root)
    output = fresh(output)

    def command(args: list[str], name: str, timeout: int, maximum: int):
        try:
            result = run_owned(args, cwd=root, env=environment, timeout=timeout,
                               maximum=maximum, separate_stderr=True)
        except ProcessFailure as error:
            result = error.result
            if result is not None:
                (output / (name + ".stdout.log")).write_bytes(result.output)
                (output / (name + ".stderr.log")).write_text(redact(result.stderr.decode("utf-8", "replace")))
            raise
        (output / (name + ".stdout.log")).write_bytes(result.output)
        (output / (name + ".stderr.log")).write_text(redact(result.stderr.decode("utf-8", "replace")))
        if result.returncode != 0:
            raise ValueError("tls-provider-reference-command-failed:" + name)
        return result.output

    def clean():
        if command(["git", "status", "--porcelain", "--untracked-files=no"], "source-status", 30, 65536).strip():
            raise ValueError("tls-provider-reference-dirty-source")

    clean()
    compiler = command(["rustc", "--version"], "compiler", 30, 4096).decode().strip()
    if not compiler.startswith("rustc 1.97.1 "):
        raise ValueError("tls-provider-reference-compiler-pin")
    inventory = output / "cargo.stdout.log"
    command(["cargo", "test", "--locked", "--all-features", "-p", "latent-streams", "--lib",
             "--no-run", "--message-format=json"], "cargo", 2400, 16 * 1024 * 1024)
    descriptor = artifacts.Suite(suite["manifest"], suite["target"], suite["source"], "",
                                 frozenset(suite["expectedCases"]), False)
    executable = artifacts.read_inventory(inventory, root, descriptor, target=target)
    libraries = compiled_tls(root, inventory, target)
    environment = artifacts.cargo_environment(root, executable, environment, target=target)
    listed = command([str(executable.executable), "--list"], "list", 30, 65536)
    ignored = command([str(executable.executable), "--ignored", "--list"], "ignored", 30, 65536)
    discovery.validate_cases(suite, discovery.listing(listed), discovery.listing(ignored), {})
    raw = command([str(executable.executable), "--test-threads=1"], "tests", suite["timeoutSeconds"], 4 * 1024 * 1024)
    cases = outcomes(raw, set(suite["expectedCases"]))
    clean()
    after = snapshot(root)
    if before != after:
        raise ValueError("tls-provider-reference-input-changed")
    receipt = {"schemaVersion": "lsf.host-tls-provider-reference.v1", "sourceRevision": revision,
               "compiler": compiler, "compiledTls": libraries, "sourceBefore": before,
               "sourceAfter": after, "testExecutableSha256": digest_file(executable.executable, 1024 * 1024 * 1024),
               "cases": cases, "ignored": [], "testExitCode": 0,
               "accountingQualified": False, "productionInstallation": False,
               "nativeStackQualified": False, "kernelAccountingQualified": False,
               "signedComponentQualified": False}
    (output / "receipt.json").write_bytes((json.dumps(receipt, indent=2) + "\n").encode())
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-commit", default=os.environ.get("GITHUB_SHA"))
    args = parser.parse_args()
    qualify(provider.ROOT, args.output, args.source_commit)
    print("Actual bounded TLS provider: 23 cases passed; accounting remains unqualified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
