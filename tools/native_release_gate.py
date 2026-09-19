#!/usr/bin/env python3
"""Validate an explicitly selected release identity and exact native VM receipts."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tomllib

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.native_runtime import files, verify
from tools.native_runtime.common import InstallError, document, encode, execute, require

ROOT = Path(__file__).resolve().parents[1]
ENVIRONMENT = "native-runtime-publish"


def github_environment():
    return {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "GH_HOST": "github.com",
            "GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1", "GH_TOKEN": os.environ["GH_TOKEN"]}


def github(path):
    status, output = execute(["gh", "api", "repos/" + verify.REPOSITORY + "/" + path],
                             environment=github_environment(), timeout=30, maximum=1_048_576, stdout_only=True)
    require(status == 0, "release-gate-github-read-failed")
    return document(output)


def reviewed_ci(run: dict, commit: str) -> None:
    require(run.get("head_sha") == commit and run.get("status") == "completed" and run.get("conclusion") == "success",
            "successful-exact-head-reviewed-ci-required")
    require(run.get("path") == ".github/workflows/ci.yml"
            and run.get("head_repository", {}).get("full_name") == verify.REPOSITORY
            and run.get("event") in {"push", "pull_request", "workflow_dispatch"}, "maintained-own-repository-ci-required")


def select_predecessor(run: dict, compatibility: dict) -> dict:
    require(run.get("path") == verify.RELEASE_WORKFLOW
            and run.get("head_repository", {}).get("full_name") == verify.REPOSITORY
            and run.get("event") == "workflow_dispatch", "predecessor-must-use-exact-release-workflow")
    matches = [item for item in compatibility["upgradeFrom"] if item["sourceCommit"] == run.get("head_sha")]
    require(len(matches) == 1, "one-committed-exact-native-predecessor-required")
    return matches[0]


def require_remote_tag(version: str, commit: str) -> None:
    reference = github("git/ref/tags/" + verify.version(version))["object"]
    for depth in range(3):
        require(verify.SOURCE.fullmatch(reference["sha"]), "invalid-remote-tag-object")
        if reference["type"] == "commit":
            require(reference["sha"] == commit, "remote-release-tag-moved-from-reviewed-commit")
            return
        require(reference["type"] == "tag" and depth < 2, "bounded-commit-or-annotated-tag-required")
        reference = github("git/tags/" + reference["sha"])["object"]
    raise InstallError("remote-release-tag-not-resolved")


def receipts(root: Path, manifest: dict) -> dict:
    reports = {}
    for profile in ("local-experimental-v1", "external-capsule-v1"):
        path = root / (profile + ".json")
        report = document(files.read(path, 262144), 262144)
        require(report.get("schemaVersion") == "latent.native-vm-result.v1" and report.get("profile") == profile
                and report.get("purpose") == "release" and report.get("passed") is True
                and report.get("acceptanceComplete") is True and report.get("gaps") == [], "complete-real-native-vm-receipts-required")
        require(report.get("sourceCommit") == manifest["sourceCommit"] and report.get("version") == manifest["version"]
                and report.get("archiveSha256") == manifest["archive"]["sha256"], "vm-receipt-exact-source-and-artifact-required")
        for name in ("initialBootId", "rebootedBootId"):
            require(isinstance(report.get(name), str) and re.fullmatch(r"[0-9a-f-]{36}", report[name]), "vm-boot-identity-required")
        require(report["initialBootId"] != report["rebootedBootId"], "real-vm-reboot-required")
        expected = {"initial", "retained", "upgrade"} | ({"rootless"} if profile == "local-experimental-v1" else set())
        results = report.get("guestResults", [])
        require(len(results) == len(expected) and {item.get("phase") for item in results} == expected
                and all(item.get("passed") is True and item.get("sourceCommit") == manifest["sourceCommit"] for item in results),
                "packaged-artifact-retention-upgrade-and-rootless-required")
        upgrade = next(item for item in results if item["phase"] == "upgrade").get("details", {}).get("upgrade", {})
        predecessor = report.get("predecessor")
        require(predecessor in manifest["compatibility"]["upgradeFrom"]
                and upgrade.get("fromVersion") == predecessor["version"] and upgrade.get("fromCommit") == predecessor["sourceCommit"]
                and upgrade.get("toVersion") == manifest["version"] and upgrade.get("toCommit") == manifest["sourceCommit"]
                and upgrade.get("unsupportedDowngradeRejected") is True, "actual-declared-version-pair-required")
        prerequisite = report.get("guestPrerequisites", {})
        require(prerequisite.get("noGuestPackageInstallation") is True and prerequisite.get("ghTrustedBeforeBundle") is True
                and prerequisite.get("sshHostKeyPinnedBeforeBoot") is True, "clean-native-guest-verification-prerequisites-required")
        policy = verify.publisher_policy(report["authentication"]["policy"], manifest["version"])
        require(policy["sourceCommit"] == manifest["sourceCommit"], "release-not-candidate-publisher-identity-required")
        reports[profile] = {"receiptSha256": files.digest(path), "initialBootId": report["initialBootId"],
                            "rebootedBootId": report["rebootedBootId"], "predecessor": predecessor,
                            "kernel": results[0]["kernel"], "imageSha256": report["image"]["imageSha256"]}
    return reports


def gate(arguments):
    verify.version(arguments.version)
    require(verify.SOURCE.fullmatch(arguments.commit) and re.fullmatch(r"[1-9][0-9]{0,14}", arguments.ci_run), "exact-release-gate-inputs-required")
    require(os.environ.get("GITHUB_REPOSITORY") == verify.REPOSITORY
            and os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
            and os.environ.get("GITHUB_REF") == "refs/tags/" + arguments.version
            and os.environ.get("GITHUB_SHA") == arguments.commit, "release-dispatch-must-use-approved-exact-tag-and-commit")
    status, head = execute(["git", "rev-parse", "HEAD"], cwd=str(ROOT))
    require(status == 0 and head.decode().strip() == arguments.commit, "release-checkout-must-be-exact-reviewed-commit")
    version = tomllib.loads((ROOT / "Cargo.toml").read_text())["workspace"]["package"]["version"]
    require(version == arguments.version, "release-version-must-match-reviewed-source")
    require_remote_tag(arguments.version, arguments.commit)
    ci = github("actions/runs/" + arguments.ci_run)
    reviewed_ci(ci, arguments.commit)
    compatibility = document(files.read(ROOT / "packaging/linux/compatibility.json"))
    predecessor = None
    if arguments.predecessor_run:
        require(re.fullmatch(r"[1-9][0-9]{0,14}", arguments.predecessor_run), "invalid-predecessor-run")
        predecessor = select_predecessor(github("actions/runs/" + arguments.predecessor_run), compatibility)
    if arguments.publish:
        require(predecessor is not None, "publication-requires-reviewed-compatible-native-pair")
        environment = github("environments/" + ENVIRONMENT)
        require(any(rule.get("type") == "required_reviewers" and rule.get("reviewers")
                    for rule in environment.get("protection_rules", [])), "configure-required-reviewer-release-environment-before-publication")
    result = {"schemaVersion": "latent.native-release-decision.v1", "version": arguments.version,
              "sourceCommit": arguments.commit, "reviewedCiRun": arguments.ci_run, "reviewedCiUrl": ci["html_url"],
              "predecessor": predecessor, "predecessorRun": arguments.predecessor_run, "publicationRequested": arguments.publish,
              "publisherPolicy": {"schemaVersion": "latent.native-publisher-policy.v1", "repository": verify.REPOSITORY,
                                  "workflow": verify.RELEASE_WORKFLOW, "sourceRef": "refs/tags/" + arguments.version,
                                  "sourceCommit": arguments.commit, "version": arguments.version, "purpose": "release"}}
    if arguments.receipts is not None:
        require(arguments.release_directory is not None, "release-directory-required-with-vm-receipts")
        manifest = verify.manifest(document(files.read(arguments.release_directory / "release.json")), arguments.version)
        require(manifest["sourceCommit"] == arguments.commit, "release-manifest-must-match-approved-commit")
        result["vmReceipts"] = receipts(arguments.receipts, manifest)
        result["archiveSha256"] = manifest["archive"]["sha256"]
    arguments.output = files.absolute(arguments.output)
    require(arguments.output.is_relative_to(ROOT / "target") and not arguments.output.exists(), "new-owned-release-gate-output-required")
    arguments.output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    files.create(arguments.output, encode(result))
    if arguments.github_output:
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
            stream.write("version=" + arguments.version + "\n")
            stream.write("predecessor-version=" + (predecessor["version"] if predecessor else "") + "\n")
            stream.write("predecessor-commit=" + (predecessor["sourceCommit"] if predecessor else "") + "\n")
    return result


def publish_assets(arguments):
    require(arguments.receipts is not None and arguments.release_directory is not None
            and arguments.acceptance_bundle is not None, "publication-requires-complete-receipts-and-attestation")
    arguments.publish = True
    decision = gate(arguments)
    acceptance = ROOT / "target/native-release-acceptance.json"
    accepted = document(files.read(acceptance, 262144), 262144)
    require(accepted == decision, "reviewed-acceptance-record-changed-before-publication")
    trust = Path(os.environ["NATIVE_TRUST"])
    publisher = verify.PublisherTrust(trust / "publisher-policy.json", trust / "trusted_root.jsonl",
                                      Path(shutil.which("gh")).resolve())
    with verify.release(arguments.release_directory, arguments.version, publisher) as release:
        require(release.metadata["sourceCommit"] == arguments.commit, "publication-artifact-source-mismatch")
        archive = release.metadata["archive"]["name"]
        command = verify.verification_command(str(publisher.verifier), acceptance, arguments.acceptance_bundle,
                                               publisher.roots, decision["publisherPolicy"])
        status, _observed = execute(command, timeout=60, maximum=2_097_152)
        require(status == 0, "acceptance-attestation-identity-mismatch")
    notes = ROOT / "target/native-release-notes.md"
    require(not notes.exists(), "new-owned-release-notes-required")
    files.create(notes, ("# Experimental native Linux runtime\n\n"
                         + "Exact source: `" + arguments.commit + "`. Version: `" + arguments.version + "`.\n\n"
                         + "Ubuntu 24.04 x86_64 only. No production or hostile-multitenancy certification. "
                         + "Verify SHA256SUMS using an independently trusted GitHub CLI, provisioned Sigstore roots "
                         + "and the exact repository/release-workflow/tag/source identity before executing lsf-install.pyz. "
                         + "The archive includes INSTALL.md, SPDX SBOM, build provenance and all three native executables.\n\n"
                         + "CI: " + decision["reviewedCiUrl"] + ". Both packaged-artifact VM profiles, real reboot, "
                         + "retained deployments, rootless evaluation and the declared native upgrade pair are bound "
                         + "in native-release-acceptance.json and the independently verifiable VM receipts. "
                         + "Capsule admission authority is separate from runtime publisher authentication.\n").encode())
    bundle = ROOT / "target/VM-EVIDENCE.sigstore.json"
    files.create(bundle, files.read(arguments.acceptance_bundle, 1_048_576))
    assets = [arguments.release_directory / name for name in
              (archive, "release.json", "lsf-install.pyz", "SHA256SUMS", "SHA256SUMS.sigstore.json")]
    assets += [acceptance, bundle] + [arguments.receipts / (profile + ".json")
                                     for profile in ("local-experimental-v1", "external-capsule-v1")]
    expected = {asset.name: {"size": asset.stat().st_size, "sha256": files.digest(asset)} for asset in assets}
    require_remote_tag(arguments.version, arguments.commit)
    decision["publicationAttempted"] = True
    decision["publicationOutcome"] = "uncertain-inspect-remote-release-before-any-retry"
    files.replace(arguments.output, encode(decision))
    status, output = execute(["gh", "release", "create", arguments.version, "--repo", verify.REPOSITORY,
                              "--verify-tag", "--prerelease", "--title", arguments.version + " native experimental",
                              "--notes-file", str(notes), *map(str, assets)],
                             environment=github_environment(), timeout=180, maximum=65536, stdout_only=True)
    require(status == 0, "publication-outcome-uncertain-inspect-remote-release-do-not-retry")
    remote = github("releases/tags/" + arguments.version)
    require(remote.get("tag_name") == arguments.version and remote.get("draft") is False
            and remote.get("prerelease") is True and len(remote.get("assets", [])) == len(expected), "published-release-inspection-required")
    for asset in remote["assets"]:
        require(asset["name"] in expected and asset.get("state") == "uploaded"
                and asset["size"] == expected[asset["name"]]["size"]
                and asset.get("digest") == "sha256:" + expected[asset["name"]]["sha256"], "published-asset-digest-inspection-required")
    require_remote_tag(arguments.version, arguments.commit)
    decision.update({"publicationOutcome": "created-and-asset-digests-verified", "releaseUrl": remote["html_url"], "assets": expected})
    files.replace(arguments.output, encode(decision))
    return decision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("version", "commit", "ci-run"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--predecessor-run", default="")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--publish-assets", action="store_true")
    parser.add_argument("--acceptance-bundle", type=Path)
    parser.add_argument("--github-output", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipts", type=Path)
    parser.add_argument("--release-directory", type=Path)
    arguments = parser.parse_args()
    try:
        result = publish_assets(arguments) if arguments.publish_assets else gate(arguments)
    except (InstallError, OSError, KeyError, TypeError, ValueError) as error:
        print(json.dumps({"releaseGatePassed": False, "diagnostic": str(error) if isinstance(error, InstallError)
                          else "exact-source-ci-identity-predecessor-or-vm-release-gate-rejected"}), file=sys.stderr)
        return 1
    print(json.dumps({"releaseGatePassed": True, "version": result["version"], "sourceCommit": result["sourceCommit"],
                      "publicationRequested": result["publicationRequested"], "vmAcceptanceChecked": "vmReceipts" in result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
