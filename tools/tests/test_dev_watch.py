"""Watch state transitions and real identity-scoped Linux build cancellation."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from tools.dev_workflow import build_client, common, paths, process, project, snapshot, state, watch
from tools.tests.test_dev_contracts import descriptor


class WatchTransitions(unittest.TestCase):
    def test_new_edit_cancels_only_the_original_build_identity_once(self):
        calls = []
        class Connection:
            def call(self, operation, arguments, **options):
                calls.append((operation, arguments))
                return {"accepted": True}
        observer = build_client.Observer(Path.cwd(), ("recipe", "old"), Connection(), "a" * 32)
        with patch.object(build_client, "selection", return_value=("recipe", "new")), patch.object(build_client.time, "monotonic", side_effect=[1, 2]):
            observer.check()
            observer.check()
        self.assertTrue(observer.superseded)
        self.assertEqual(calls, [("cancel-build", {"buildId": "a" * 32, "reason": "superseded"})])

    def run_watch(self, *, build_failure=None, test_passed=True):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "test-watch"
        paths.new_directory(root)
        observations, events = [], []
        selected = ("recipe", "source-a")
        class Connection:
            def call(self, operation, arguments, **options):
                observations.append((operation, arguments))
                if operation == "status":
                    return {"state": "stopped" if len([o for o, _ in observations if o == "status"]) > (1 if build_failure else 2) else "ready"}
                if operation == "deploy":
                    return {"source": selected[1], "publication": "publication-a", "operation": "original-a"}
                if operation == "test":
                    return {"passed": test_passed, "results": [{"id": "focused", "status": "passed" if test_passed else "failed"}]}
                raise AssertionError(operation)
        def build(*args, **kwargs):
            if build_failure:
                raise build_failure
            return {"source": selected[1], "artifacts": {}}
        with patch.object(build_client, "selection", return_value=selected), patch.object(watch.time, "sleep"):
            result = watch.run(root, Connection(), root, "/tools", build=build, emit=events.append, test_selection=["focused"])
        self.assertEqual(result, {"state": "stopped"})
        return observations, events

    def test_focused_post_deploy_failure_is_visible_and_never_rolls_back(self):
        observations, events = self.run_watch(test_passed=False)
        self.assertEqual([name for name, _ in observations], ["status", "status", "deploy", "test", "status"])
        self.assertEqual(observations[3][1], {"environment": "node", "selection": ["focused"]})
        self.assertEqual(events[-1]["event"], "post-deploy-tests")
        self.assertFalse(events[-1]["passed"])
        self.assertFalse(events[-1]["rollbackPerformed"])
        self.assertEqual(events[-1]["currentDeployment"]["publication"], "publication-a")

    def test_superseded_build_cannot_publish_or_run_tests(self):
        observations, events = self.run_watch(build_failure=common.DevError("guest-build-superseded"))
        self.assertTrue(all(name == "status" for name, _ in observations))
        self.assertEqual(events[-1]["event"], "build-superseded")

    def test_uncertain_deployment_stops_watch_without_retry(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        calls = []
        class Connection:
            def call(self, operation, arguments):
                calls.append(operation)
                if operation == "status":
                    return {"state": "ready"}
                raise common.DevError("operation-outcome-uncertain-use-recover", uncertain=True)
        with patch.object(build_client, "selection", return_value=("recipe", "source")), patch.object(watch.time, "sleep"):
            with self.assertRaises(common.DevError) as error:
                watch.run(root, Connection(), root, "/tools", build=lambda *a, **kw: {}, emit=lambda _: None)
        self.assertTrue(error.exception.uncertain)
        self.assertEqual(calls.count("deploy"), 1)


@unittest.skipUnless(sys.platform == "linux", "actual Linux helper ownership")
class BuildCancellation(unittest.TestCase):
    def test_exact_cancellation_and_workspace_stop_reap_real_compiler_descendants(self):
        from tools import build_process
        from tools.build_process_signals import owned_cancellation
        from tools.dev_workflow import build_control
        for reason in ("superseded", "workspace-stopped"):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / "source"
                paths.new_directory(source)
                paths.new_directory(source / "src")
                program = b"""import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from tools.build_process import run_bounded_result
from tools.dev_workflow.process import environment
child="import os,time;from pathlib import Path;Path('../live').write_text(str(os.getpid()));time.sleep(60)"
run_bounded_result([sys.executable,'-c',child],cwd=Path.cwd(),env=environment(),timeout_seconds=12,max_output_bytes=1024)
"""
                paths.write_new(source / "src/slow.py", program)
                record, _ = snapshot.observe(source, ["src"])
                paths.write_new(source / "snapshot.json", common.encode(record))
                selected = descriptor()
                python = Path(sys.executable).resolve()
                selected["build"].update(argv=["python", "-I", "slow.py", str(Path.cwd())], timeoutSeconds=12,
                    tools=[{"name": "python", "path": python.name, "version": "3.13.5",
                            "sha256": paths.digest_file(python.parent, python.name, 268435456)[0]}])
                state.atomic(root, "inputs.json", selected)
                script = """import sys
from pathlib import Path
from tools.dev_workflow import build,build_control,common,project,state
root=Path(sys.argv[1]); selected=state.load(root,'inputs.json'); python=Path(sys.executable).resolve()
try:
    with state.lock(root),build_control.session(root,'a'*32) as control:
        build.execute(root,root/'source',selected,python.parent,trusted=project.trust_identity(selected),cli=python,control=control)
except common.DevError as error:
    print(error.code)
"""
                owner = build_process._new_owner()
                with owned_cancellation() as cancellation:
                    try:
                        owner.spawn([str(python), "-c", script, str(root)], Path.cwd(), process.environment(), time.monotonic() + 15)
                        deadline = time.monotonic() + 8
                        while time.monotonic() < deadline:
                            active = build_control.status(root)
                            live = root / "builds" / (active.get("attempt") or "absent") / "source/live"
                            if live.is_file():
                                break
                            time.sleep(0.02)
                        self.assertTrue(live.is_file(), "the actual compiler did not start")
                        descendant = int(live.read_text())
                        self.assertFalse(build_control.cancel(root, "b" * 32)["accepted"])
                        self.assertEqual(build_control.status(root)["state"], "running")
                        if reason == "workspace-stopped":
                            build_control.stop(root)
                        else:
                            self.assertTrue(build_control.cancel(root, "a" * 32, reason)["accepted"])
                        output, _ = build_process._capture(owner, time.monotonic() + 10, 4096, cancellation)
                        self.assertIn(("guest-build-" + reason).encode(), output)
                        self.assertEqual(build_control.wait_stopped(root)["state"], "reaped")
                        stat = Path(f"/proc/{descendant}/stat")
                        self.assertTrue(not stat.exists() or stat.read_text().rsplit(")", 1)[1].split()[0] in {"Z", "X"})
                    finally:
                        owner.finish(time.monotonic() + 5)
                        owner.close()


if __name__ == "__main__":
    unittest.main()
