"""Revoke an owned previous publication, then reject its preconditioned restore."""
import copy
import secrets

from tools.dev_workflow import helper, state
from tools.dev_workflow.common import require


def run(root, previous, deadline):
    cli, _ = helper.client(root, deadline=deadline)
    observed = cli.call("release", "lifecycle", "--publication", previous["publication"])
    require(observed["category"] == "success" and observed["outcomeKnown"] is True,
            "previous-publication-lifecycle-unavailable")
    record = observed["data"]["status"]["record"]
    require(record["publication"]["id"] == previous["publication"]
            and record["componentDigest"] == previous["componentDigest"], "previous-publication-identity-changed")
    operation = "qualification-" + secrets.token_hex(16)
    state.atomic(root, "qualification-revoke-intent.json", {"id": operation,
        "publication": previous["publication"], "expectedGeneration": record["generation"]})
    revoked = cli.call("release", "revoke", "--publication", previous["publication"],
        "--operation-id", operation, "--expected-generation", record["generation"])
    require(revoked["category"] == "success" and revoked["outcomeKnown"] is True
            and revoked["data"]["operation"]["operationId"] == operation,
            "original-publication-revocation-unconfirmed-no-retry")
    after = cli.call("release", "lifecycle", "--publication", previous["publication"])
    require(after["category"] == "success" and after["outcomeKnown"] is True
            and after["data"]["status"]["record"]["state"] == "RELEASE_LIFECYCLE_STATE_REVOKED",
            "previous-publication-not-revoked")
    selected = state.load(root, "last-deployment.json")
    current = cli.call("deployment", "get", selected["deployment"], "--operation-snapshot")
    require(current["category"] == "success" and current["outcomeKnown"] is True
            and current["data"]["deployment"]["generation"] == selected["generation"],
            "current-deployment-unconfirmed-before-revoked-restore")
    deployment = copy.deepcopy(current["data"]["deployment"]["manifest"])
    deployment["spec"].update(publication=previous["publication"], release=previous["componentDigest"])
    operation = "qualification-" + secrets.token_hex(16)
    state.atomic(root, "qualification-restore-input.json", deployment)
    state.atomic(root, "qualification-restore-intent.json", {"id": operation,
        "publication": previous["publication"], "expectedGeneration": selected["generation"],
        "expectedStateVersion": current["data"]["stateVersion"]})
    rejected = cli.call("deployment", "apply", root / "qualification-restore-input.json", "--operation-id", operation,
        "--expected-generation", selected["generation"], "--expected-state-version", current["data"]["stateVersion"])
    require(rejected["outcomeKnown"] is True and rejected["category"] == "platform-failure"
            and rejected.get("error", {}).get("code") in {"permission-denied", "failed-precondition"},
            "revoked-publication-restore-not-known-rejected")
    retained = cli.call("deployment", "get", selected["deployment"], "--operation-snapshot")
    require(retained["category"] == "success" and retained["outcomeKnown"] is True
            and retained["data"]["deployment"] == current["data"]["deployment"]
            and state.load(root, "last-deployment.json") == selected,
            "revoked-restore-changed-last-working-deployment")
    return {"original": observed, "revoke": revoked, "revoked": after, "restore": rejected,
        "revokeCalls": 1, "restoreCalls": 1, "statePreconditionRefreshedForRetry": False,
        "controllerDeploymentUnchanged": True, "serverDeploymentUnchanged": True}
