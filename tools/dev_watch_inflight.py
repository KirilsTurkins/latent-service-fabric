"""One separately owned actual Invoke spanning a controller deployment change."""
import secrets
import time

from tools import build_process
from tools.build_process_signals import owned_cancellation
from tools.dev_workflow import build, helper, paths, process, state
from tools.dev_workflow.common import decode, require


class Inflight:
    def __init__(self, root, descriptor, deadline):
        self.root, self.descriptor, self.deadline = root, descriptor, deadline
        self.cli, _ = helper.client(root, deadline=deadline)
        self.activation = "qualification-" + secrets.token_hex(16)
        self.owner = None
        self.cancel_sent = False
        self.report = {"activationId": self.activation, "invokeCalls": 0, "cancelCalls": 0}

    def start(self):
        source, _ = build.accepted(self.root, state.load(self.root, "project.json"))
        budget = decode(paths.read(source, self.descriptor["artifacts"]["capsule"]))["execution"]["limits"]
        state.atomic(self.root, "qualification-budget.json", budget)
        paths.write_new(self.root / "qualification-spin-input.json", b"[]")
        state.atomic(self.root, "qualification-spin-intent.json", {"id": self.activation, "kind": "invoke",
            "deployment": state.load(self.root, "last-deployment.json"), "maximumSeconds": 125})
        argv = [str(self.cli.binary), "--config", str(self.cli.config), "--output", "json", "--rpc-timeout-ms", "125000",
            "invoke", "--service", self.descriptor["service"], "--contract", "examples:greeting/api@1.0.0",
            "--function", "spin", "--input", str(self.root / "qualification-spin-input.json"),
            "--media-type", "application/vnd.latent.wit-values.v1+json", "--activation-id", self.activation,
            "--budget", str(self.root / "qualification-budget.json"), "--budget-profile", "phase3"]
        with owned_cancellation() as cancellation, cancellation.defer():
            self.owner = build_process._new_owner()
            self.owner.spawn(argv, self.root, process.environment(), min(self.deadline, time.monotonic() + 125))
        self.report["invokeCalls"] = 1
        until = min(self.deadline, time.monotonic() + 5)
        while time.monotonic() < until:
            value = self.cli.lookup("invoke", self.activation)
            if value["category"] == "success":
                self.report["beforeEdit"] = value
                require(value["data"].get("terminalState") is None, "old-invocation-ended-before-source-edit")
                if value["data"].get("phase") == "running":
                    return
            else:
                require(value["category"] == "not-found" and value["outcomeKnown"] is True,
                        "old-invocation-status-uncertain")
            time.sleep(0.02)
        require(False, "old-invocation-never-observed-running")

    def stop(self):
        if self.owner is None:
            return
        try:
            if not self.cancel_sent:
                self.cancel_sent = True
                self.report["cancelCalls"] = 1
                state.atomic(self.root, "qualification-spin-cancel.json", {"activationId": self.activation, "calls": 1})
                self.report["cancellation"] = self.cli.call("activation", "cancel", self.activation,
                    "--reason", "explicit-watch-qualification")
            with owned_cancellation() as cancellation:
                raw, _errors = build_process._capture(self.owner, min(self.deadline, time.monotonic() + 8), 1048576, cancellation)
                self.report["result"] = decode(raw, 1048576)
        finally:
            self.owner.finish(time.monotonic() + 5)
            self.owner.close()
            self.owner = None

    def switched(self, before, after):
        require(before["publication"] != after["publication"], "watch-did-not-publish-new-bytes")
        observed = self.cli.lookup("invoke", self.activation)
        self.report["afterSwitch"] = observed
        require(observed["category"] == "success" and observed["outcomeKnown"] is True
                and observed["data"].get("phase") == "running" and observed["data"].get("terminalState") is None,
                "old-invocation-did-not-span-committed-switch")
        self.stop()
        result = self.report["result"]
        revision = result["data"].get("resolvedRevision", {})
        require(result["outcomeKnown"] is True and result["category"] == "platform-failure"
                and result["data"].get("terminalState") == "cancelled"
                and result["error"]["code"] == "cancelled"
                and revision.get("publicationId") == before["publication"]
                and revision.get("releaseDigest") == before["componentDigest"],
                "old-invocation-revision-changed-during-switch")
        self.report["oldRevisionRetained"] = True
        return self.report
