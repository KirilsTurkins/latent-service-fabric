"""Profiled reopen keeps its logical selector and owns a real allocation wrapper."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools.artifact_identity_runner import run
from tools.artifact_identity_runner.files import reference
from tools.optimization_backend_revision.catalog_mutations import collect, model


class CatalogMutationProfileRunnerTests(unittest.TestCase):
    def test_both_profile_owners_forward_only_the_declared_temporary_folded_allowance(self):
        class ReachedProbe(Exception):
            pass

        for mode in ("allocation", "allocation-reopen"):
            selection = next(row for row in model.population("smoke") if row["mode"] == mode)
            with self.subTest(mode=mode), TemporaryDirectory() as temporary:
                output = Path(temporary)
                binary = {"path": "builds/control/backend", "bytes": "1", "sha256": "sha256:" + "1" * 64}
                build = {"builds": {"control": {"executables": {"backend": binary}}},
                         "harness": {"echo": {"component": {"path": "fixtures/echo.wasm"}}}}
                suite = {"runs": [], "tools": {name: {"path": name}
                         for name in ("heaptrack", "heaptrack_print", "zstd")}}
                with patch.object(collect, "_host", return_value={}), patch.object(collect, "cgroup", return_value={}), \
                     patch.object(model, "identity", return_value={}), patch.object(collect, "inventory", return_value=[]), \
                     patch.object(collect, "collect_probe", side_effect=ReachedProbe) as probe:
                    with self.assertRaises(ReachedProbe):
                        collect._child(selection, SimpleNamespace(profile="smoke"), output, build, suite, output,
                                       output / "data", output / "group", {"path": "owner.json"}, 10**30, lambda: None)
                probe.assert_called_once()
                arguments, options = probe.call_args
                self.assertEqual(arguments[0]["mode"], mode)
                self.assertEqual(options["probe_mode"], "allocation")
                self.assertEqual(options["maximum_folded_bytes"], 512 * 1024**2)
                self.assertEqual(options["temporary_folded_bytes"], 512 * 1024**2)
                self.assertNotIn("maximum_total_bytes", options)
                self.assertEqual(model.MAX_TOTAL_BYTES, 1024**3)

    def test_reopen_exports_profiles_without_changing_the_logical_owner(self):
        with TemporaryDirectory() as temporary:
            output = Path(temporary)
            executable = output / "backend"
            executable.write_bytes(b"retained executable")
            binary = reference(executable, output)
            row = dict(mode="allocation-reopen", command=["heaptrack", "--output", "profile", "backend"],
                       ready=None, result=None, probe_process=None, cpu=None, profile_refs=None)
            source = dict(process_id=202, start_time_ticks="10", observed_exited=False)
            sample = dict(rss_bytes="4096", kernel_high_water_rss_bytes="8192")
            resource = SimpleNamespace(getrusage=Mock(side_effect=AssertionError("profile CPU conflated")))
            launches = []

            class Owner:
                def __init__(self, command, log, purpose, timeout, cwd, **kwargs):
                    launches.append((purpose, timeout, command))
                    log.write_bytes(b"source ready and completed\n")
                    self.receipt = {"process_id": 201, "exit_code": 0}
                    self.events = []
                    self.selector = SimpleNamespace(get_map=lambda: {})
                    self.done = False

                def exited(self):
                    return self.done

                def poll(self):
                    self.events = [{"record": {"event": "ready", "process_id": 202}},
                                   {"record": {"event": "measurement-complete", "process_id": 202,
                                               "outcome": "passed"}}]
                    self.done = True

                def close(self):
                    self.receipt.update(reaped=True, output_closed=True)

                def resources(self):
                    return {}

            refs = {"raw": {"path": "retained.heaptrack.zst"}}
            with patch.dict("sys.modules", resource=resource), patch.object(run, "OwnedProcess", Owner), \
                 patch.object(run.resources, "bind", return_value=source), \
                 patch.object(run.resources, "sample", return_value=sample), \
                 patch.object(run.resources, "exited", return_value=True), \
                 patch.object(run, "cgroup", return_value={}), patch.object(run.time, "sleep"), \
                 patch.object(run, "profile_reports", return_value=refs) as reports:
                run.collect(row, output / "probe", binary, None, output, 10**30, "printer", "zstd",
                            probe_mode="allocation")
            self.assertEqual(row["mode"], "allocation-reopen")
            self.assertEqual(launches, [("identity-allocation", 180, row["command"])])
            self.assertEqual(row["profile_refs"], refs)
            self.assertTrue(row["probe_process"]["observed_exited"])
            self.assertEqual(row["status"], "passed")
            self.assertIsNone(row["cpu"])
            reports.assert_called_once()
            resource.getrusage.assert_not_called()

    def test_unsupported_override_rejects_before_platform_import_or_spawn(self):
        for mode in ("normal", "allocation-reopen", True, 1, [], {}):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "unsupported-probe-mode-override"):
                run.collect({}, Path("unused"), {}, None, Path("unused"), 0, "printer", "zstd",
                            probe_mode=mode)
