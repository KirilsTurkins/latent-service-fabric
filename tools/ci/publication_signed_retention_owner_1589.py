#!/usr/bin/env python3
"""Source-bound disposable signed-publication-retention diagnostic owner."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

SOURCE = "a59dc230d351c14e5e1b3983f0c516b2b2289218"
TREE = "c32526ee7d57f70122d0b24984c2f101a8769eb1"
ROOT = Path.cwd().resolve(strict=True)
sys.path.insert(0, str(ROOT))
from tools.owned_test_process import ProcessFailure, run_owned  # noqa: E402

TEST_NAMES = {
    "ControlTests.test_cli_call_limit_is_checked_before_spawning_the_next_process",
    "ControlTests.test_fixture_identity_is_order_independent_bounded_and_changes_with_content",
    "ControlTests.test_snapshot_requires_one_exact_tenant_publication_generation_and_fence",
    "ControlTests.test_receipt_requires_original_actor_selection_kind_and_durable_audit",
    "ControlTests.test_original_lookup_rejects_wrong_receipt_unknown_or_automatic_replay",
    "ControlTests.test_removed_publication_must_remain_hidden_like_an_unknown_publication",
    "ControlTests.test_restored_audit_requires_each_original_committed_attempt_and_outcome",
    "CoupledCopyTests.test_linux_copy_or_explicit_non_linux_refusal",
    "CoupledCopyTests.test_linux_path_refusals_or_explicit_non_linux_refusal",
}
FIXTURE = "supply_chain::tests::support::operator_fixture::export_publication_workflow_fixture"
PHASES = {"fixture", "signed-publication", "pin-and-retire", "delete-and-reclaim", "stopped-coupled-restore"}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def git(*args):
    value = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=30, check=True)
    require(len(value.stdout) <= 1024 * 1024, "git-output-bound")
    return value.stdout.strip()


def source_state():
    require(git("rev-parse", "HEAD") == SOURCE and git("rev-parse", "HEAD^{tree}") == TREE,
            "source-identity-mismatch")
    require(not git("status", "--porcelain=v1", "--untracked-files=all") and not git("clean", "-ndx"),
            "source-not-clean")


def paths():
    runner = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    supplied = [Path(os.environ[name]) for name in ("SIGNED_REPORTS", "SIGNED_SCRATCH", "CARGO_TARGET_DIR")]
    require(all(p.is_absolute() and not p.is_symlink() for p in supplied), "owner-path-invalid")
    reports, scratch, target = (p.resolve(strict=True) for p in supplied)
    require(all(p.is_dir() and p != runner and p.is_relative_to(runner) for p in (reports, scratch, target))
            and len({reports, scratch, target}) == 3 and reports.parent == scratch.parent == target.parent,
            "owner-paths-not-disposable-siblings")
    return reports, scratch, target


def write_report(path, value):
    data = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    require(len(data) <= 262144, "owner-report-bound")
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def summary(raw):
    text = re.sub(r"\x1b\[[0-9;]*m", "", raw.decode("utf-8", "replace"))
    codes = sorted(set(re.findall(r"\berror\[(E[0-9]{4})\]", text)))[:16]
    locations = []
    for match in re.finditer(r"^\s*-->\s+([A-Za-z0-9_./-]+\.(?:rs|py)):(\d{1,7}):(\d{1,5})\s*$", text, re.MULTILINE):
        path = match.group(1)
        if not path.startswith("/") and ".." not in path.split("/"):
            item = {"path": path[:200], "line": int(match.group(2)), "column": int(match.group(3))}
            if item not in locations:
                locations.append(item)
        if len(locations) >= 16:
            break
    return {"errorCodes": codes, "sourceLocations": locations}


def validate_tests(raw):
    pattern = re.compile(r"^test_[a-z0-9_]+ \(tools\.tests\.test_publication_retention_signed\.((?:ControlTests|CoupledCopyTests)\.test_[a-z0-9_]+)\) \.\.\. (ok|FAIL|ERROR|skipped.*)$")
    cases = {}
    for line in raw.decode("utf-8", "replace").splitlines():
        match = pattern.fullmatch(line)
        if match:
            cases.setdefault(match.group(1), []).append(match.group(2))
    require(set(cases) == TEST_NAMES and all(v == ["ok"] for v in cases.values()), "focused-test-outcomes")
    require(re.search(rb"Ran 9 tests in [0-9.]+s\s+OK\s*$", raw) is not None, "focused-test-summary")
    return sorted(cases)


def fixture_outcome(raw):
    text = raw.decode("utf-8", "replace")
    require(len(re.findall(r"^test " + re.escape(FIXTURE) + r" \.\.\. ok$", text, re.MULTILINE)) == 1,
            "signed-fixture-test-outcome")
    require(re.search(r"^test result: ok\. 1 passed; 0 failed; 0 ignored;", text, re.MULTILINE) is not None,
            "signed-fixture-test-summary")


def digest_file(path, maximum):
    require(path.is_file() and not path.is_symlink(), "binary-not-regular")
    h, total = hashlib.sha256(), 0
    with path.open("rb") as source:
        while chunk := source.read(65536):
            total += len(chunk)
            require(total <= maximum, "binary-size-bound")
            h.update(chunk)
    require(total > 0, "binary-empty")
    return "sha256:" + h.hexdigest()


def public_receipt(value, target):
    require(isinstance(value, dict) and value.get("tenant") == "tests"
            and value.get("actor", {}).get("subject") == "workflow-operator", "receipt-public-scope")
    command = value.get("command")
    require(isinstance(command, dict) and isinstance(command.get("selection"), dict), "receipt-public-command")
    selection = command["selection"]
    require(selection.get("operationId") in {"pin-blue", "delete-green"}
            and re.fullmatch(r"[0-9a-f]{64}", selection.get("catalogFence", "")) is not None
            and selection.get("targets") == [target], "receipt-public-selection")
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    require(len(raw) <= 16384, "receipt-public-size")
    return {"sha256": "sha256:" + hashlib.sha256(raw).hexdigest(), "stage": value.get("stage"),
            "operationId": selection["operationId"], "catalogFence": selection["catalogFence"],
            "target": target, "actor": "workflow-operator", "tenant": "tests"}


def scenario_result(raw, cli, node):
    require(len(raw) <= 65536, "scenario-output-bound")
    value = json.loads(raw)
    require(value.get("schemaVersion") == "latent.publication.signed-retention.v1"
            and value.get("passed") is True and value.get("signedNodeDeletionAndStoppedRestore") is True
            and value.get("physicalPowerLossQualified") is False
            and value.get("independentHistoryCompactionQualified") is False
            and value.get("temporaryOutputsRemoved") is True and value.get("syntheticTestEvidence") is True,
            "scenario-claims-invalid")
    ids = value.get("identities", {})
    require(ids.get("sourceCommit") == SOURCE and ids.get("sourceCommitKind") == "supplied-build-identity"
            and ids.get("cliDigest") == digest_file(cli, 1024**3)
            and ids.get("nodeDigest") == digest_file(node, 1024**3), "scenario-binary-identity")
    fixture = value.get("fixtureInventory", {})
    require(type(fixture.get("files")) is int and 1 <= fixture["files"] <= 512
            and re.fullmatch(r"sha256:[0-9a-f]{64}", fixture.get("sha256", "")) is not None,
            "scenario-fixture-identity")
    copied = value.get("copy", {})
    require(copied.get("contentModesAndHardlinksVerified") is True and copied.get("independentCopy") is True
            and copied.get("originalUnchangedAfterRestore") is True
            and type(copied.get("fileCount")) is int and 0 < copied["fileCount"] <= 4096
            and type(copied.get("uniqueCopiedBytes")) is int and 0 < copied["uniqueCopiedBytes"] <= 256 * 1024**2,
            "scenario-copy-evidence")
    audit = value.get("restoredAudit", {})
    require(audit.get("restoredAuditVerified") is True
            and isinstance(audit.get("committedAttemptSequences"), list)
            and len(set(audit["committedAttemptSequences"])) == 3
            and all(isinstance(x, str) and re.fullmatch(r"[1-9][0-9]{0,19}", x) for x in audit["committedAttemptSequences"]),
            "scenario-audit-evidence")
    shutdown = value.get("shutdown", [])
    require(isinstance(shutdown, list) and len(shutdown) == 2
            and all(x.get("reaped") is True and x.get("record", {}).get("clean") is True for x in shutdown)
            and type(value.get("cliProcesses")) is int and 0 < value["cliProcesses"] <= 64,
            "scenario-physical-cleanup")
    blue, green = value["publications"]["retained"], value["publications"]["reclaimed"]
    require(blue.get("tenant") == green.get("tenant") == "tests" and blue != green
            and all(re.fullmatch(r"publication:sha256:[0-9a-f]{64}", x.get("id", "")) for x in (blue, green)),
            "scenario-publication-identity")
    receipts = {}
    for key, publication, expected in (("pinReceipt", blue, "retention-updated"),
                                       ("deletionReceipt", green, "visibility-removed"),
                                       ("reclamationReceipt", green, "namespaces-reclaimed")):
        receipt = value[key]
        targets = receipt["command"]["selection"]["targets"]
        require(isinstance(targets, list) and len(targets) == 1 and targets[0].get("publication") == publication
                and receipt.get("stage") == expected, "scenario-receipt-target")
        receipts[key] = public_receipt(receipt, targets[0])
    return {"source": SOURCE, "binaryIdentities": {"cliDigest": ids["cliDigest"], "nodeDigest": ids["nodeDigest"]},
            "fixtureInventory": fixture, "receipts": receipts, "copy": copied, "audit": audit,
            "nodeShutdownsReaped": True, "cliProcesses": value["cliProcesses"],
            "physicalPowerLossQualified": False, "independentHistoryCompactionQualified": False}


def selftest():
    lines = [f"test_x (tools.tests.test_publication_retention_signed.{n}) ... ok" for n in sorted(TEST_NAMES)]
    raw = ("\n".join(lines) + "\nRan 9 tests in 0.01s\n\nOK\n").encode()
    require(len(validate_tests(raw)) == 9, "selftest-valid-tests")
    for bad in (raw.replace(b" ... ok", b" ... skipped", 1), raw.replace(b"Ran 9 tests", b"Ran 8 tests"),
                raw.replace(b" ... ok", b" ... FAIL", 1)):
        try:
            validate_tests(bad)
        except ValueError:
            continue
        raise ValueError("selftest-invalid-tests")
    fixture_outcome(("test " + FIXTURE + " ... ok\ntest result: ok. 1 passed; 0 failed; 0 ignored;\n").encode())
    try:
        fixture_outcome(("test " + FIXTURE + " ... FAILED\ntest result: FAILED. 0 passed; 1 failed; 0 ignored;\n").encode())
    except ValueError:
        pass
    else:
        raise ValueError("selftest-invalid-fixture")
    require(summary(b"error[E1234]: hidden\n  --> crate/file.rs:12:3\nsecret text") ==
            {"errorCodes": ["E1234"], "sourceLocations": [{"path": "crate/file.rs", "line": 12, "column": 3}]},
            "selftest-diagnostic-redaction")


def run():
    reports, scratch, target = paths()
    source_state()
    require(sys.platform == "linux" and os.uname().machine == "x86_64", "linux-x86-64-required")
    home = scratch / "home"
    home.mkdir(mode=0o700)
    real_home = Path(os.environ["HOME"])
    env = {"PATH": os.environ["PATH"], "HOME": str(home),
           "CARGO_HOME": os.environ.get("CARGO_HOME", str(real_home / ".cargo")),
           "RUSTUP_HOME": os.environ.get("RUSTUP_HOME", str(real_home / ".rustup")),
           "RUSTUP_TOOLCHAIN": "1.97.1", "CARGO_TARGET_DIR": str(target), "CARGO_BUILD_JOBS": "2",
           "CARGO_INCREMENTAL": "0", "CARGO_PROFILE_DEV_DEBUG": "0", "CARGO_PROFILE_TEST_DEBUG": "0",
           "CARGO_PROFILE_DEV_DEBUG_ASSERTIONS": "true", "CARGO_PROFILE_TEST_DEBUG_ASSERTIONS": "true",
           "CARGO_PROFILE_DEV_OVERFLOW_CHECKS": "true", "CARGO_PROFILE_TEST_OVERFLOW_CHECKS": "true",
           "CARGO_TERM_COLOR": "never", "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8", "TMPDIR": str(scratch)}
    for name in ("SSL_CERT_FILE", "SSL_CERT_DIR"):
        if name in os.environ:
            env[name] = os.environ[name]
    report = {"source": SOURCE, "tree": TREE, "ownerHead": os.environ.get("GITHUB_SHA"),
              "status": "started", "stages": [], "rawChildOutputRetained": False}
    report_path = reports / "owner.json"
    write_report(report_path, report)

    def stage(name, command, timeout, custom_env=None):
        source_state()
        item = {"name": name, "command": command, "status": "started"}
        report["stages"].append(item)
        write_report(report_path, report)
        result = None
        start = time.monotonic()
        try:
            result = run_owned(command, cwd=ROOT, env=custom_env or env, timeout=timeout,
                               maximum=16 * 1024 * 1024, separate_stderr=True)
            item.update(returncode=result.returncode, cleaned=result.cleaned,
                        elapsedSeconds=round(time.monotonic() - start, 3))
            require(result.cleaned and result.returncode == 0, "stage-failed-" + name)
            source_state()
            item["status"] = "passed"
            return result
        except ProcessFailure as error:
            result = error.result
            item["error"] = "owned-process-" + error.category
            raise ValueError(item["error"]) from None
        finally:
            if result is not None:
                item.update(stdoutBytes=len(result.output), stdoutSha256=hashlib.sha256(result.output).hexdigest(),
                            stderrBytes=len(result.stderr), stderrSha256=hashlib.sha256(result.stderr).hexdigest(),
                            diagnostics=summary(result.stderr))
                if item.get("status") != "passed" and name == "scenario":
                    try:
                        failure = json.loads(result.stderr.decode("utf-8", "replace").splitlines()[0])
                        if failure.get("schemaVersion") == "latent.publication.signed-retention.v1" and failure.get("phase") in PHASES:
                            item["failurePhase"] = failure["phase"]
                            observed = failure.get("failedCall")
                            if isinstance(observed, dict):
                                allowed = {k: v for k, v in observed.items() if k in {"call", "exitStatus", "command", "category", "publicCode", "grpcCode", "requestDispatched", "outcomeKnown"}}
                                if all(v is None or type(v) in (str, int, bool) and len(str(v)) <= 128 for v in allowed.values()):
                                    item["failedCall"] = allowed
                    except (ValueError, IndexError, AttributeError):
                        pass
            write_report(report_path, report)

    try:
        unit = stage("controls", [sys.executable, "-B", "-m", "unittest", "-v",
                                  "tools.tests.test_publication_retention_signed"], 120)
        report["controlCases"] = validate_tests(unit.stderr + unit.output)
        stage("build", ["cargo", "build", "--locked", "-p", "latent", "-p", "latentd"], 2400)
        cli, node = target / "debug/latent", target / "debug/latentd"
        with tempfile.TemporaryDirectory(prefix="signed-publication-fixture-", dir=scratch) as temporary:
            fixture = Path(temporary) / "inputs"
            fixture_env = dict(env, LSF_OPERATOR_FIXTURE_ROOT=str(fixture))
            exported = stage("fixture", ["cargo", "test", "--locked", "-p", "latent-policy", "--lib",
                "--all-features", FIXTURE, "--", "--exact", "--ignored", "--nocapture", "--test-threads=1"],
                900, fixture_env)
            fixture_outcome(exported.output + exported.stderr)
            from tools.run_phase2_operator_workflow import inventory
            before = inventory(fixture)
            require(set(p.name for p in fixture.iterdir()) == {"policy.json", "fixture.json", "blue", "green"},
                    "fixture-top-level")
            observed = stage("scenario", [sys.executable, "-B", "tools/run_publication_retention_signed.py",
                "--cli", str(cli), "--node", str(node), "--fixture-root", str(fixture), "--source-commit", SOURCE], 300)
            report["scenario"] = scenario_result(observed.output, cli, node)
            require(inventory(fixture) == before, "fixture-changed-after-scenario")
        require(not Path(temporary).exists(), "fixture-cleanup-unconfirmed")
        report["fixtureTemporaryDirectoryRemoved"] = True
        source_state()
        report["status"] = "passed"
    except (ValueError, OSError, KeyError, TypeError, AttributeError, subprocess.SubprocessError) as error:
        reason = str(error)
        report.update(status="failed", error=reason if re.fullmatch(r"[a-z0-9-]{1,120}", reason) else "unclassified-owner-failure")
        raise
    finally:
        write_report(report_path, report)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("self-test", "check-plan", "run"))
    args = parser.parse_args()
    try:
        selftest()
        if args.mode != "self-test":
            source_state()
        if args.mode == "run":
            run()
        print("signed-retention-owner-" + args.mode + ": passed")
        return 0
    except (ValueError, OSError, KeyError, TypeError, AttributeError, subprocess.SubprocessError) as error:
        reason = str(error)
        print("signed-retention-owner-" + args.mode + ": failed: "
              + (reason if re.fullmatch(r"[a-z0-9-]{1,120}", reason) else "unclassified-owner-failure"), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
