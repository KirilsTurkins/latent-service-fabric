"""Missing, skipped, mocked or portable evidence cannot qualify Windows nodes."""
from __future__ import annotations

from .common import members, require, sha

WINDOWS_ENTRIES = {"windows-wsl2", "windows-portable", "linux-direct", "linux-ssh", "devcontainer"}
LANGUAGES = {"rust", "c", "typescript", "go", "java", "dotnet"}
REQUIRED = {"verify-offline", "tamper-rejection", "create", "build", "readiness", "invoke", "declared-error",
            "denied-capability", "watch-revision", "compile-failure-last-good", "lost-response-recovery",
            "restart-retained", "cancel", "workspace-isolation", "down", "owned-purge"}


def validate(report: dict) -> dict:
    members(report, {"schemaVersion", "scope", "sourceCommit", "receipts", "failedAttempts", "newcomerReview"})
    require(report["schemaVersion"] == "latent.dev.qualification.v1" and report["scope"] == "windows-only",
            "qualification-scope")
    import re
    require(isinstance(report["sourceCommit"], str) and re.fullmatch(r"[0-9a-f]{40}", report["sourceCommit"]), "qualification-source")
    require(isinstance(report["receipts"], list) and len(report["receipts"]) == len(WINDOWS_ENTRIES), "required-platform-receipts-missing")
    seen = set()
    for receipt in report["receipts"]:
        members(receipt, {"entry", "execution", "sourceCommit", "artifactSha256", "environment", "host", "guest",
                          "profile", "scenarios", "languages", "cleanup", "sourceCheckout", "runtimeCompiler"})
        entry = receipt["entry"]
        require(entry in WINDOWS_ENTRIES - seen, "duplicate-or-unsupported-platform-receipt")
        seen.add(entry)
        require(receipt["execution"] == "actual-packaged-clean-host" and receipt["sourceCommit"] == report["sourceCommit"],
                "mock-cross-build-or-stale-evidence-cannot-qualify")
        sha(receipt["artifactSha256"])
        require(receipt["sourceCheckout"] is False and receipt["runtimeCompiler"] is False, "clean-host-prerequisite-failed")
        require(isinstance(receipt["host"], dict) and receipt["host"].get("osVersion")
                and receipt["host"].get("architecture"), "actual-host-observation-required")
        require(receipt["cleanup"] == "owned-resources-reaped", "qualification-cleanup-unconfirmed")
        if entry == "windows-portable":
            require(receipt["environment"] == "portable" and receipt["guest"] is None
                    and receipt["profile"] == "controlled-development-test", "portable-environment-misrepresented")
            required = {"invoke", "declared-error", "denied-capability", "cancel"}
        else:
            require(receipt["environment"] == "node" and isinstance(receipt["guest"], dict)
                    and receipt["guest"].get("os") == "linux" and receipt["guest"].get("kernel"),
                    "real-linux-node-observation-required")
            require(receipt["profile"] in {"local-experimental-v1", "external-capsule-v1"}, "node-profile-required")
            required = REQUIRED
        require(isinstance(receipt["scenarios"], dict) and required <= receipt["scenarios"].keys()
                and all(receipt["scenarios"][name] == "passed" for name in required), "required-scenario-missing-or-not-passed")
        require(isinstance(receipt["languages"], dict), "language-receipts-required")
        if entry == "windows-wsl2":
            require(LANGUAGES <= receipt["languages"].keys() and all(receipt["languages"][name] == "passed" for name in LANGUAGES),
                    "all-six-real-guest-integrations-required")
    require(isinstance(report["failedAttempts"], list) and len(report["failedAttempts"]) <= 128, "failure-history-limit")
    require(report["newcomerReview"] == "executed-and-reviewed", "newcomer-review-required")
    return report
