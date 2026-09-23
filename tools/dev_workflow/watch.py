"""One active build and one latest edit, followed by an explicit focused test hook."""
from pathlib import Path
import time

from . import build_client, state
from .common import DevError, require


def run(workspace: Path, connection, source: Path, tool_root: str, *, build, emit,
        editor_diagnostics: bool = False, check_session=lambda: None, test_selection: list[str] | None = None) -> dict:
    from tools.build_process_signals import owned_cancellation
    require(source is not None and tool_root is not None, "watch-project-and-tools-required")
    selection = test_selection or []
    require(not selection or workspace.name.startswith("test-"), "focused-watch-tests-require-test-workspace")
    require(len(selection) <= 128 and len(set(selection)) == len(selection), "focused-test-selection-limit")
    source = source.absolute()
    last_observed, last_error = None, None
    current = state.load(workspace, "watch-deployment.json") if (workspace / "watch-deployment.json").exists() else None
    def event(name: str, **fields):
        emit({"event": name, "workspace": workspace.name, "currentDeployment": current, **fields})
    with owned_cancellation() as cancellation:
        while True:
            cancellation.check()
            check_session()
            observed = connection.call("status", {})
            if observed.get("state") != "ready":
                return observed
            try:
                selected = build_client.selection(source)
                if selected == last_observed:
                    time.sleep(0.25)
                    continue
                # Two coherent full observations; only the latest identity is pending.
                time.sleep(0.2)
                if build_client.selection(source) != selected:
                    continue
            except (DevError, OSError, ValueError) as error:
                code = error.code if isinstance(error, DevError) else "source-unavailable-during-edit"
                if code != last_error:
                    event("edit-failed", phase="source", code=code, uncertain=False)
                    last_error = code
                time.sleep(0.25)
                continue
            last_observed, last_error = selected, None
            phase = "build"
            try:
                with state.lock(workspace):
                    built = build(workspace, connection, source, tool_root, selected=selected,
                                  editor_diagnostics=editor_diagnostics)
                    require(build_client.selection(source) == selected, "guest-build-superseded")
                    require(connection.call("status", {}).get("state") == "ready", "workspace-stopped-before-deployment")
                    phase = "deploy"
                    # Once dispatched, this mutation completes or becomes uncertain.
                    # A subsequent edit never cancels it into an automatic replay.
                    deployed = connection.call("deploy", {})
                    current = deployed
                    state.atomic(workspace, "watch-deployment.json", deployed)
                    event("deployed", build=built, deployment=deployed)
                    if selection:
                        phase = "test"
                        report = connection.call("test", {"environment": "node", "selection": selection}, timeout=315)
                        event("post-deploy-tests", passed=report["passed"], report=report, rollbackPerformed=False)
                    else:
                        event("post-deploy-tests-not-selected")
            except DevError as error:
                event("build-superseded" if error.code == "guest-build-superseded" else "edit-failed",
                      phase=phase, source=selected[1], code=error.code, uncertain=error.uncertain,
                      diagnostics=error.diagnostics, rollbackPerformed=False)
                if error.uncertain:
                    raise
            time.sleep(0.25)
