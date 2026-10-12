"""Bounded real packaged frontend operations with original process ownership."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import time

from tools.dev_workflow import preflight
from tools.dev_workflow.common import encode
from tools.phase2_operator_process import Process, file_digest, require, write_json


class Frontend:
    """One finite controlled schedule; execution is separate from its input checks."""
    def __init__(self, binary: Path, expected: str, root: Path, client, *,
                 state_root: Path | None = None, workspace: str | None = None):
        require(root.is_dir() and not root.is_symlink(), "composition-probe-private-root-required")
        require(re.fullmatch(r"sha256:[0-9a-f]{64}", expected) is not None,
                "composition-probe-exact-frontend-required")
        require((state_root is None) == (workspace is None), "composition-probe-workspace-selection")
        self.binary, self.expected, self.root, self.client = binary, expected, root, client
        self.state_root, self.workspace = state_root, workspace
        self.cases = []
        self._verify()
        self.operator_digest = file_digest(Path(client.executable), 256 * 1024 * 1024,
            client.cancellation, client.deadline)

    def _verify(self):
        actual = file_digest(self.binary, 256 * 1024 * 1024,
                                         self.client.cancellation, self.client.deadline)
        require(actual == self.expected, "composition-probe-frontend-changed")

    def check(self, name: str, value: dict, *, mode="standalone", passed=True, checks=()):
        require(len(self.cases) < 24 and re.fullmatch(r"[a-z][a-z0-9-]{0,63}", name) is not None
                and name not in {row["name"] for row in self.cases}, "composition-probe-case-bound")
        require(mode in {"structural", "standalone", "workspace"}, "composition-probe-entry")
        require(mode != "workspace" or self.workspace is not None, "composition-probe-provisioned-workspace-required")
        self._verify()
        input_path = self.root / (name + ".input.json")
        write_json(input_path, value)
        argv = [str(self.binary)]
        if mode == "workspace":
            argv.extend(("--state-root", str(self.state_root)))
        argv.extend(("dev", "preflight", "--input", str(input_path), "--output", "json"))
        if mode == "standalone":
            argv.extend(("--operator", str(self.client.executable), "--operator-sha256", self.operator_digest,
                         "--config", str(self.client.config)))
        elif mode == "workspace":
            argv.extend(("--workspace", self.workspace))
        # Use the native executable outside a source/Python/compiler search
        # path. The separately provisioned helper remains the backend owner.
        environment = {name: os.environ[name] for name in ("HOME", "LANG", "LC_ALL", "TMPDIR") if name in os.environ}
        environment.update(PATH="/usr/bin:/bin", PYTHONNOUSERSITE="1", PYTHONUTF8="1")
        began = time.monotonic_ns()
        process = Process(argv, self.root, environment, self.client.cancellation, maximum=524288)
        try:
            completed = process.complete(min(self.client.deadline, time.monotonic() + 140))
        finally:
            process.close()
        require(process.owner.finished, "composition-probe-frontend-not-reaped")
        # Preserve the actual bounded outcome before any oracle can reject it.
        # These private logs are evidence, not a public result or authority.
        for suffix, raw in (("stdout", completed.stdout), ("stderr", completed.stderr)):
            path = self.root / (name + "." + suffix + ".log")
            with path.open("xb") as stream:
                stream.write(raw)
            path.chmod(0o600)
        self._verify()
        require(completed.returncode == (0 if passed else 3), "composition-probe-command-exit")
        reply = json.loads(completed.stdout)
        require(reply["schemaVersion"] == "latent.dev.result.v1"
                and reply["code"] == ("success" if passed else "composition-checks-failed"),
                "composition-probe-command-result")
        result = reply["result"]
        require(result["schemaVersion"] == preflight.RESULT and result["passed"] is passed
                and len(encode(result)) <= preflight.MAX_DOCUMENT, "composition-probe-bounded-result")
        for flag in ("fullyChecked", "executionAuthorized", "grantCreated", "reservationCreated", "trafficEnabled"):
            require(result[flag] is False, "composition-probe-preflight-claimed-authority")
        for level, state, code in checks:
            require(any(row["evidenceLevel"] == level and row["state"] == state and row["code"] == code
                        for row in result["checks"]), "composition-probe-required-evidence-missing")
        receipt = {"name": name, "entry": mode, "frontendDigest": self.expected,
                   "operatorDigest": self.operator_digest if mode == "standalone" else None,
                   "processReaped": True, "elapsedNanos": str(time.monotonic_ns() - began), "result": result}
        write_json(self.root / (name + ".receipt.json"), receipt)
        self.cases.append({key: receipt[key] for key in ("name", "entry", "frontendDigest", "processReaped")})
        return result
