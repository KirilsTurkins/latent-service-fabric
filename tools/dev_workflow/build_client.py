"""Source synchronization and identity-scoped cancellation of a remote build."""
import base64
from pathlib import Path
import secrets
import sys
import time

from . import diagnostics, project, snapshot, state
from .common import DevError, require


def selection(source: Path) -> tuple[str, str]:
    descriptor, _ = project.load(source)
    record, _ = snapshot.observe(source, descriptor["inputRoots"], tuple(descriptor["exclude"]))
    return project.trust_identity(descriptor), record["identity"]


class Observer:
    def __init__(self, source: Path, expected: tuple, connection, build_id: str):
        self.source, self.expected, self.connection, self.build_id = source, expected, connection, build_id
        self.previous, self.superseded, self.cancelled = 0.0, False, False

    def check(self):
        now = time.monotonic()
        if now - self.previous < 0.5:
            return
        self.previous = now
        try:
            changed = selection(self.source) != self.expected
        except (DevError, OSError, ValueError):
            changed = True  # An intermediate editor save is not the captured source.
        self.superseded |= changed
        if self.superseded and not self.cancelled:
            result = self.connection.call("cancel-build", {"buildId": self.build_id, "reason": "superseded"}, timeout=10)
            self.cancelled = result["accepted"]


def cancel_and_confirm(connection, selected: str) -> None:
    from tools.build_process_signals import owned_cancellation
    with owned_cancellation() as cancellation, cancellation.defer():
        try:
            connection.call("cancel-build", {"buildId": selected, "reason": "cancelled"}, timeout=10)
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                observed = connection.call("build-status", {}, timeout=5)
                if observed.get("id") == selected:
                    if observed["state"] == "reaped":
                        return
                    if observed["state"] == "uncertain":
                        break
                time.sleep(0.05)
        except (OSError, DevError):
            pass
        raise DevError("build-cleanup-unconfirmed-inspect-owned-workspace", uncertain=True)


def run(workspace: Path, connection, source: Path, tool_root: str, *, editor_diagnostics: bool = False,
        selected: tuple[str, str] | None = None) -> dict:
    require(source is not None and tool_root is not None, "explicit-project-and-tool-root-required")
    source = source.absolute()
    descriptor, _raw_identity = project.load(source)
    identity = project.trust_identity(descriptor)
    require(state.load(workspace, "trust.json") == {"project": str(source), "recipe": identity}, "workspace-recipe-trust-required")
    record, content = snapshot.observe(source, descriptor["inputRoots"], tuple(descriptor["exclude"]))
    expected = identity, record["identity"]
    require(selected is None or selected == expected, "guest-build-superseded")
    connection.call("snapshot", {"snapshot": record, "project": descriptor, "trustedRecipe": identity,
                    "content": {name: base64.b64encode(raw).decode() for name, raw in content.items()}}, timeout=120)
    build_id = secrets.token_hex(16)
    observer = Observer(source, expected, connection, build_id) if selected is not None else None
    try:
        try:
            result = connection.call("build", {"toolRoot": tool_root, "buildId": build_id},
                timeout=descriptor["build"]["timeoutSeconds"] + 15, check=observer.check if observer else None)
        except BaseException as error:
            if not isinstance(error, DevError) or error.uncertain:
                cancel_and_confirm(connection, build_id)
            raise
        if observer is not None:
            require(not observer.superseded and selection(source) == expected, "guest-build-superseded")
    except DevError as error:
        error.diagnostics = diagnostics.for_host(error.diagnostics, source)
        if editor_diagnostics:
            for line in diagnostics.editor_lines(error.diagnostics):
                print(line, file=sys.stderr)
        raise
    result["diagnostics"] = diagnostics.for_host(result.get("diagnostics", []), source)
    if editor_diagnostics:
        for line in diagnostics.editor_lines(result["diagnostics"]):
            print(line, file=sys.stderr)
    return result
