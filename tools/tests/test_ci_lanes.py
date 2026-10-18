"""Compiler/network-free scheduling tests; not product qualification evidence."""

from dataclasses import replace
import json
from pathlib import Path
import random
import tempfile
import unittest

from tools import ci_suite_inventory
from tools.ci_lanes import (
    Completion, LaneError, Lease, Phase, Scheduler, Stage, State,
)
from tools.run_ci_lanes import CHILD_SCHEMA, _expected_cases, _read_receipt, stages


def stage(name, *, needs=(), group="runtime", exclusive=False, phase=Phase.EXECUTION):
    return Stage(name, phase, group, 30, needs,
                 (name + "::case",) if phase == Phase.EXECUTION else (),
                 (name + "-receipt",), exclusive)


def scheduler(*stages, workers=2):
    return Scheduler(tuple(stages), workers=workers,
                     capacities={"runtime": 1, "provider": 1, "renderer": 1})


def report(lease, outcome=State.SUCCESS):
    return Completion(lease.stage.name, outcome, lease.stage.cases, lease.stage.receipts)


def finish(sched, lease, outcome=State.SUCCESS):
    sched.complete(lease, report(lease, outcome))
    sched.retire(lease)


class GraphTests(unittest.TestCase):
    def test_requires_explicit_bounded_workers(self):
        for workers in (0, 3, -1, True, 1.0, None):
            with self.subTest(workers=workers), self.assertRaises(LaneError):
                scheduler(stage("test"), workers=workers)
        with self.assertRaises(TypeError):
            Scheduler((stage("test"),), capacities={"runtime": 1})

    def test_rejects_empty_duplicate_and_oversized_graphs(self):
        for stages in ((), (stage("a"), stage("a")),
                       tuple(stage(f"a{i}") for i in range(257))):
            with self.subTest(count=len(stages)), self.assertRaises(LaneError):
                scheduler(*stages)

    def test_rejects_missing_self_and_cyclic_dependencies(self):
        for stages in ((stage("a", needs=("missing",)),),
                       (stage("a", needs=("a",)),),
                       (stage("a", needs=("b",)), stage("b", needs=("a",)))):
            with self.subTest(stages=stages), self.assertRaises(LaneError):
                scheduler(*stages)

    def test_accepts_non_topological_declaration_order(self):
        sched = scheduler(stage("later", needs=("first",)), stage("first"))
        first, = sched.claim_ready()
        self.assertEqual(first.stage.name, "first")
        finish(sched, first)
        self.assertEqual(sched.claim_ready()[0].stage.name, "later")

    def test_rejects_undeclared_groups_and_invalid_capacities(self):
        with self.assertRaises(LaneError):
            scheduler(stage("a", group="not-declared"))
        for value in (0, 3, -1, True, 1.0):
            with self.subTest(value=value), self.assertRaises(LaneError):
                Scheduler((stage("a"),), workers=2, capacities={"runtime": value})

    def test_rejects_empty_execution_selection(self):
        with self.assertRaisesRegex(LaneError, "empty-execution"):
            scheduler(replace(stage("a"), cases=()))

    def test_requires_finite_stage_watchdog_without_activation_override(self):
        for value in (0, -1, 7201, float("inf"), True, 1.5):
            with self.subTest(value=value), self.assertRaises(LaneError):
                scheduler(replace(stage("a"), watchdog_seconds=value))
        self.assertFalse(hasattr(stage("a"), "activation_timeout"))

    def test_build_and_preparation_phases_are_distinct(self):
        stages = tuple(stage(f"p{i}", phase=phase) for i, phase in enumerate(Phase))
        sched = scheduler(*stages)
        self.assertEqual(len(sched.states), len(Phase))

    def test_rejects_duplicate_dependencies_cases_and_receipts(self):
        for values in ({"needs": ("b", "b")}, {"cases": ("a", "a")},
                       {"receipts": ("a", "a")}, {"cases": ["a"]}):
            with self.subTest(values=values), self.assertRaises(LaneError):
                scheduler(replace(stage("a"), **values), stage("b"))

    def test_rejects_invalid_stage_names_and_phases(self):
        for name in ("", "../a", "A", "a" * 97, None):
            with self.subTest(name=name), self.assertRaises(LaneError):
                scheduler(replace(stage("a"), name=name))
        with self.assertRaises(LaneError):
            scheduler(replace(stage("a"), phase="unknown"))

    def test_configuration_and_snapshots_do_not_expose_mutable_state(self):
        capacities = {"runtime": 1}
        sched = Scheduler((stage("a"),), workers=1, capacities=capacities)
        capacities["runtime"] = 0
        self.assertEqual(sched.capacities["runtime"], 1)
        with self.assertRaises(TypeError):
            sched.states["a"] = State.SUCCESS
        before = sched.states
        sched.claim_ready()
        self.assertEqual(before["a"], State.PENDING)


class ExecutionPolicyTests(unittest.TestCase):
    def test_worker_and_group_bounds(self):
        sched = scheduler(stage("a"), stage("b"), stage("c", group="provider"),
                          stage("d", group="renderer"))
        leases = sched.claim_ready()
        self.assertEqual([lease.stage.name for lease in leases], ["a", "c"])
        self.assertEqual(sched.claim_ready(), ())
        finish(sched, leases[0])
        self.assertEqual([lease.stage.name for lease in sched.claim_ready()], ["b"])

    def test_serial_policy_has_one_live_stage(self):
        sched = scheduler(stage("a"), stage("b", group="provider"), workers=1)
        a, = sched.claim_ready()
        self.assertEqual(sched.claim_ready(), ())
        finish(sched, a)
        b, = sched.claim_ready()
        finish(sched, b)
        self.assertTrue(sched.finished)
        self.assertTrue(sched.passed)

    def test_same_group_capacity_two_is_explicit(self):
        sched = Scheduler((stage("a"), stage("b")), workers=2, capacities={"runtime": 2})
        self.assertEqual(len(sched.claim_ready()), 2)

    def test_requires_prerequisite_retirement_not_only_exit(self):
        sched = scheduler(stage("build", phase=Phase.HOST_BUILD),
                          stage("render", needs=("build",), group="renderer"))
        build, = sched.claim_ready()
        sched.complete(build, report(build))
        self.assertEqual(sched.claim_ready(), ())
        self.assertFalse(sched.passed)
        sched.retire(build)
        self.assertEqual(sched.claim_ready()[0].stage.name, "render")

    def test_exclusive_probe_drains_then_holds_every_group(self):
        sched = scheduler(stage("prepare"), stage("provider", group="provider"),
                          stage("physical", needs=("prepare",), exclusive=True),
                          stage("renderer", needs=("prepare",), group="renderer"))
        prepare, provider = sched.claim_ready()
        finish(sched, prepare)
        self.assertEqual(sched.claim_ready(), ())
        finish(sched, provider)
        physical, = sched.claim_ready()
        self.assertEqual(physical.stage.name, "physical")
        sched.complete(physical, report(physical))
        self.assertEqual(sched.claim_ready(), ())
        sched.retire(physical)
        self.assertEqual(sched.claim_ready()[0].stage.name, "renderer")

    def test_ready_exclusive_probe_cannot_starve(self):
        sched = scheduler(stage("ordinary", group="renderer"), stage("physical", exclusive=True))
        physical, = sched.claim_ready()
        self.assertEqual(physical.stage.name, "physical")

    def test_failed_preparation_blocks_transitive_consumers_not_diagnostics(self):
        sched = scheduler(stage("prepare", phase=Phase.COMPONENT_GENERATION),
                          stage("render", needs=("prepare",), group="renderer"),
                          stage("hydrate", needs=("render",), group="renderer"),
                          stage("provider", group="provider"))
        prepare, provider = sched.claim_ready()
        finish(sched, prepare, State.FAILURE)
        finish(sched, provider)
        self.assertEqual(sched.states["render"], State.BLOCKED)
        self.assertEqual(sched.states["hydrate"], State.BLOCKED)
        self.assertEqual(sched.states["provider"], State.SUCCESS)
        self.assertTrue(sched.finished)
        self.assertFalse(sched.passed)

    def test_failed_renderer_does_not_suppress_independent_provider(self):
        sched = scheduler(stage("renderer", group="renderer"), stage("provider", group="provider"))
        renderer, provider = sched.claim_ready()
        finish(sched, renderer, State.FAILURE)
        finish(sched, provider)
        self.assertTrue(sched.finished)
        self.assertFalse(sched.passed)
        self.assertEqual(sched.states["provider"], State.SUCCESS)

    def test_cancelled_provider_blocks_consumers(self):
        sched = scheduler(stage("provider", group="provider"),
                          stage("dependent", needs=("provider",)))
        provider, = sched.claim_ready()
        finish(sched, provider, State.CANCELLED)
        self.assertEqual(sched.states["dependent"], State.BLOCKED)
        self.assertFalse(sched.passed)

    def test_missing_wrong_duplicate_and_extra_completion_evidence_fail(self):
        for change in (None, {"stage": "wrong"}, {"outcome": []}, {"cases": ()},
                       {"cases": ("test::case", "test::case")},
                       {"cases": ("test::case", "extra")}, {"receipts": ()},
                       {"receipts": ("wrong-artifact-observation",)},
                       {"receipts": ("test-receipt", "test-receipt")}):
            with self.subTest(change=change):
                sched = scheduler(stage("test"))
                lease, = sched.claim_ready()
                completion = None if change is None else replace(report(lease), **change)
                sched.complete(lease, completion)
                sched.retire(lease)
                self.assertEqual(sched.states["test"], State.FAILURE)
                self.assertFalse(sched.passed)

    def test_case_order_does_not_change_case_parity(self):
        sched = scheduler(replace(stage("test"), cases=("a", "b")))
        lease, = sched.claim_ready()
        sched.complete(lease, replace(report(lease), cases=("b", "a")))
        sched.retire(lease)
        self.assertTrue(sched.passed)

    def test_foreign_run_and_reconstructed_leases_are_rejected(self):
        first, second = scheduler(stage("a")), scheduler(stage("a"))
        lease, = first.claim_ready()
        other, = second.claim_ready()
        for invalid in (lease, Lease(other.stage, other.token)):
            with self.subTest(invalid=invalid), self.assertRaises(LaneError):
                second.complete(invalid, report(other))
        finish(second, other)
        self.assertTrue(second.passed)

    def test_retirement_and_completion_are_single_use(self):
        sched = scheduler(stage("a"))
        lease, = sched.claim_ready()
        with self.assertRaisesRegex(LaneError, "retirement-before"):
            sched.retire(lease)
        sched.complete(lease, report(lease))
        with self.assertRaisesRegex(LaneError, "duplicate-completion"):
            sched.complete(lease, report(lease))
        sched.retire(lease)
        with self.assertRaisesRegex(LaneError, "retired-lease"):
            sched.retire(lease)

    def test_cancel_before_dispatch_never_runs_work(self):
        sched = scheduler(stage("a"))
        self.assertEqual(sched.cancel(), ())
        self.assertEqual(sched.claim_ready(), ())
        self.assertTrue(sched.finished)
        self.assertFalse(sched.passed)

    def test_cancel_during_execution_retains_resources_until_cleanup(self):
        sched = scheduler(stage("a"), stage("b", needs=("a",)))
        lease, = sched.claim_ready()
        self.assertEqual(sched.cancel(), (lease,))
        self.assertEqual(sched.cancel(), (lease,))
        self.assertEqual(sched.states["a"], State.CANCELLING)
        self.assertFalse(sched.finished)
        self.assertEqual(sched.claim_ready(), ())
        sched.complete(lease, report(lease))
        self.assertFalse(sched.finished)
        sched.retire(lease)
        self.assertEqual(sched.states["a"], State.CANCELLED)
        self.assertTrue(sched.finished)
        self.assertFalse(sched.passed)

    def test_cancel_between_exit_and_cleanup_is_not_success(self):
        sched = scheduler(stage("a"))
        lease, = sched.claim_ready()
        sched.complete(lease, report(lease))
        sched.cancel()
        sched.retire(lease)
        self.assertEqual(sched.states["a"], State.CANCELLED)
        self.assertFalse(sched.passed)

    def test_missing_retirement_cannot_pass_or_unblock_work(self):
        sched = scheduler(stage("a"), stage("b", needs=("a",)))
        lease, = sched.claim_ready()
        sched.complete(lease, report(lease))
        self.assertFalse(sched.finished)
        self.assertFalse(sched.passed)
        self.assertEqual(sched.claim_ready(), ())

    def test_missing_dispatch_receipt_cannot_pass(self):
        self.assertFalse(scheduler(stage("a")).passed)

    def test_fixed_seed_random_dags_preserve_bounds_and_coverage(self):
        # Model events, not real wall-clock measurements or LSF runtime probes.
        for workers in (1, 2):
            for seed in range(30):
                rng = random.Random(seed)
                stages = []
                for i in range(20):
                    needs = tuple(s.name for s in stages if rng.randrange(8) == 0)
                    stages.append(stage(f"stage{i}", needs=needs,
                                        group=rng.choice(("runtime", "provider", "renderer")),
                                        exclusive=rng.randrange(7) == 0))
                sched = scheduler(*stages, workers=workers)
                live = []
                executed = []
                for _ in range(100):
                    live.extend(sched.claim_ready())
                    self.assertLessEqual(len(live), workers)
                    self.assertEqual(len({lease.stage.group for lease in live}), len(live))
                    if any(lease.stage.exclusive for lease in live):
                        self.assertEqual(len(live), 1)
                    if sched.finished:
                        break
                    self.assertTrue(live)
                    lease = live.pop(rng.randrange(len(live)))
                    executed.append(lease.stage.name)
                    finish(sched, lease)
                self.assertTrue(sched.passed)
                self.assertCountEqual(executed, [s.name for s in stages])


class IntegrationContractTests(unittest.TestCase):
    def test_renderer_worker_and_coordinator_require_the_exact_http_policy_proof(self):
        from tools.ci_lane_worker import RENDERER_STEPS, _renderer_cases
        from tools.ci_rust_artifacts import registered_suites
        data = ci_suite_inventory.load()
        case = data["selections"]["http-response-policy"]["names"][0]
        renderer, = (item for item in stages(True) if item.name == "renderer-integrations")
        self.assertEqual(list(renderer.cases), RENDERER_STEPS)
        self.assertEqual(tuple(_renderer_cases(data)), _expected_cases(data, "renderer"))
        self.assertIn("http-response-policy", renderer.cases)
        self.assertEqual(_expected_cases(data, "renderer").count(case), 1)
        self.assertEqual(_expected_cases(data, "renderer-public").count(case), 1)
        self.assertNotIn(case, _expected_cases(data, "renderer-angular"))
        self.assertIn("http-response-policy", stages(True, "renderer-public")[0].cases)
        self.assertNotIn("http-response-policy", stages(True, "renderer-angular")[0].cases)
        selection = registered_suites()["http-response-policy"]
        self.assertTrue(selection.exact)
        self.assertEqual(selection.names, frozenset({case}))
        self.assertLessEqual(selection.timeout, 180)
        del data["selections"]["http-response-policy"]
        with self.assertRaisesRegex(LaneError, "http-response-policy-selection-contract"):
            _expected_cases(data, "renderer")
        with self.assertRaisesRegex(ValueError, "http-response-policy-selection-contract"):
            _renderer_cases(data)

    def test_renderer_receipt_cannot_omit_the_executed_http_operator_proof(self):
        data = ci_suite_inventory.load()
        sched = Scheduler(stages(True), workers=2, capacities={"provider": 1, "renderer": 1})
        lease, = (item for item in sched.claim_ready() if item.stage.name == "renderer-integrations")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "renderer.json"
            receipt = {
                "schemaVersion": CHILD_SCHEMA, "lane": "renderer", "outcome": "passed",
                "steps": list(lease.stage.cases),
                "selectedCases": list(_expected_cases(data, "renderer")),
                "timings": [{"stage": "renderer-http-response-policy", "elapsedMs": 1.0}],
            }
            path.write_text(json.dumps(receipt), encoding="utf-8")
            self.assertEqual(_read_receipt(path, lease, data)["outcome"], "passed")
            case = data["selections"]["http-response-policy"]["names"][0]
            receipt["selectedCases"].remove(case)
            path.write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaisesRegex(LaneError, "lane-selected-case-parity"):
                _read_receipt(path, lease, data)

    def test_split_renderer_keeps_every_case_and_step_exactly_once(self):
        from tools.ci_lane_worker import _renderer_cases
        data = ci_suite_inventory.load()
        public = _expected_cases(data, "renderer-public")
        angular = _expected_cases(data, "renderer-angular")
        self.assertTrue(public and angular)
        self.assertFalse(set(public) & set(angular))
        self.assertEqual(public + angular, _expected_cases(data, "renderer"))
        self.assertEqual(list(public), _renderer_cases(data, "public"))
        self.assertEqual(list(angular), _renderer_cases(data, "angular"))
        left, = stages(True, "renderer-public")
        right, = stages(True, "renderer-angular")
        whole = stages(True, "renderer")[0]
        self.assertEqual(left.cases + right.cases, whole.cases)

    def test_explicit_lanes_cannot_silently_drop_renderer_selection(self):
        for lane in ("renderer", "renderer-public", "renderer-angular", "unknown"):
            with self.subTest(lane=lane), self.assertRaises(LaneError):
                stages(False, lane)
        self.assertEqual([s.name for s in stages(True, "provider")], ["provider-integrations"])

    def test_each_renderer_receipt_still_rejects_an_omitted_case(self):
        data = ci_suite_inventory.load()
        for lane in ("renderer-public", "renderer-angular"):
            sched = Scheduler(stages(True, lane), workers=1, capacities={"provider": 1, "renderer": 1})
            lease, = sched.claim_ready()
            value = {"schemaVersion": CHILD_SCHEMA, "lane": lane, "outcome": "passed",
                     "steps": list(lease.stage.cases), "selectedCases": list(_expected_cases(data, lane)),
                     "timings": [{"stage": "execution", "elapsedMs": 1}]}
            with self.subTest(lane=lane), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "receipt.json"
                path.write_text(json.dumps(value), encoding="utf-8")
                _read_receipt(path, lease, data)
                value["selectedCases"].pop()
                path.write_text(json.dumps(value), encoding="utf-8")
                with self.assertRaisesRegex(LaneError, "lane-selected-case-parity"):
                    _read_receipt(path, lease, data)

    def test_current_inventory_supplies_nonempty_exact_lane_cases(self):
        data = ci_suite_inventory.load()
        provider = _expected_cases(data, "provider")
        renderer = _expected_cases(data, "renderer")
        self.assertGreater(len(provider), 10)
        self.assertGreater(len(renderer), 4)
        self.assertEqual(len(provider), len(set(provider)))
        self.assertEqual(len(renderer), len(set(renderer)))
        self.assertTrue(set(data["selections"]["browser-boundary"]["names"]) <= set(renderer))

    def test_real_lane_graph_dispatches_provider_and_renderer_together(self):
        sched = Scheduler(stages(True), workers=2, capacities={"provider": 1, "renderer": 1})
        leases = sched.claim_ready()
        self.assertEqual({lease.stage.name for lease in leases},
                         {"provider-integrations", "renderer-integrations"})

    def test_receipt_requires_exact_steps_cases_and_timing(self):
        data = ci_suite_inventory.load()
        sched = Scheduler(stages(False), workers=1, capacities={"provider": 1, "renderer": 1})
        lease, = sched.claim_ready()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "provider.json"
            valid = {
                "schemaVersion": CHILD_SCHEMA,
                "lane": "provider",
                "outcome": "passed",
                "steps": list(lease.stage.cases),
                "selectedCases": list(_expected_cases(data, "provider")),
                "timings": [{"stage": "execution", "elapsedMs": 1.0}],
                "diagnostic": "diagnostic.json",
                "reason": None,
            }
            path.write_text(json.dumps(valid), encoding="utf-8")
            self.assertEqual(_read_receipt(path, lease, data)["outcome"], "passed")
            for key, value in (
                ("steps", valid["steps"][:-1]),
                ("selectedCases", valid["selectedCases"][:-1]),
                ("timings", []),
            ):
                changed = dict(valid)
                changed[key] = value
                path.write_text(json.dumps(changed), encoding="utf-8")
                with self.subTest(key=key), self.assertRaises(LaneError):
                    _read_receipt(path, lease, data)

    def test_missing_lane_receipt_fails_closed(self):
        data = ci_suite_inventory.load()
        sched = Scheduler(stages(False), workers=1, capacities={"provider": 1, "renderer": 1})
        lease, = sched.claim_ready()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(LaneError, "missing-lane-receipt"):
                _read_receipt(Path(directory) / "missing.json", lease, data)


class AngularTargetPreparationTests(unittest.TestCase):
    def _renderer(self, part, calls, failure=None):
        import os
        from types import SimpleNamespace
        from unittest.mock import patch
        from tools import ci_lane_worker as worker
        from tools.owned_test_process import Result

        stage = None

        def mark(value):
            nonlocal stage
            stage = value

        def command(args, *, cwd, timeout, maximum, env, check):
            calls.append({"stage": stage, "args": args, "cwd": cwd,
                          "timeout": timeout, "maximum": maximum, "check": check})
            if stage == "renderer-angular-dependencies" and failure is not None:
                raise failure
            return Result(1 if stage == "renderer-negative-control" else 0, b"")

        run = SimpleNamespace(mark=mark, command=command, artifact=lambda *args: None)
        with tempfile.TemporaryDirectory() as directory:
            component = Path(directory) / "browser-component/application.wasm"
            component.parent.mkdir()
            component.write_bytes(b"command-order-fixture")
            with patch.dict(os.environ, RUNNER_TEMP=directory), patch.object(
                    worker.shutil, "which", side_effect=lambda name: "/qualified/" + name):
                return worker.renderer(run, Path(directory) / "inventory.jsonl",
                                       ci_suite_inventory.load(), part)

    def test_angular_and_combined_workers_fetch_locked_target_before_offline_package(self):
        from tools import ci_lane_worker as worker

        for part, lane in (("angular", "renderer-angular"), ("both", "renderer")):
            with self.subTest(part=part):
                calls = []
                steps, cases = self._renderer(part, calls)
                fetches = [index for index, call in enumerate(calls)
                           if call["stage"] == "renderer-angular-dependencies"]
                self.assertEqual(len(fetches), 1)
                fetch = calls[fetches[0]]
                self.assertEqual(fetch, {
                    "stage": "renderer-angular-dependencies",
                    "args": ["cargo", "fetch", "--locked", "--target", "wasm32-unknown-unknown"],
                    "cwd": worker.ROOT, "timeout": 300, "maximum": 8 * 1024 * 1024,
                    "check": True,
                })
                package = calls[fetches[0] + 1]
                self.assertEqual(package["stage"], "renderer-angular-package")
                self.assertEqual(package["args"][1], "tools/build_angular_package.py")
                self.assertEqual(package["timeout"], 780)
                self.assertEqual(steps, worker.RENDERER_STEPS[5:] if part == "angular"
                                 else worker.RENDERER_STEPS)
                self.assertEqual(tuple(cases), _expected_cases(ci_suite_inventory.load(), lane))

    def test_target_fetch_failure_propagates_without_starting_package_or_runtime(self):
        from tools.owned_test_process import ProcessFailure

        for part in ("angular", "both"):
            with self.subTest(part=part):
                calls = []
                failure = ProcessFailure("assertion-failure", "child-exit-failure")
                with self.assertRaises(ProcessFailure) as caught:
                    self._renderer(part, calls, failure)
                self.assertIs(caught.exception, failure)
                self.assertEqual(calls[-1]["stage"], "renderer-angular-dependencies")
                self.assertEqual(sum(call["stage"] == "renderer-angular-dependencies"
                                     for call in calls), 1)
                self.assertFalse({"renderer-angular-package", "renderer-angular-runtime",
                                  "renderer-angular-hydration"}
                                 & {call["stage"] for call in calls})

    def test_public_worker_keeps_its_original_commands_without_the_new_fetch(self):
        from tools import ci_lane_worker as worker

        calls = []
        steps, cases = self._renderer("public", calls)
        self.assertEqual([call["stage"] for call in calls], [
            "renderer-npm-prepare", "renderer-profile-build", "renderer-node-candidate",
            "renderer-ssr", "renderer-profile-hydration", "renderer-browser-unit",
            "renderer-browser-build", "renderer-browser-boundary", "renderer-http-response-policy",
            "renderer-public-fixture", "renderer-generic-cells", "renderer-negative-control",
            "renderer-negative-control-proof",
        ])
        self.assertFalse(any(call["args"][:2] == ["cargo", "fetch"] for call in calls))
        self.assertEqual(steps, worker.RENDERER_STEPS[:5])
        self.assertEqual(tuple(cases), _expected_cases(ci_suite_inventory.load(), "renderer-public"))

    def test_t1_workflow_fetch_is_bounded_to_the_original_angular_condition_and_order(self):
        import yaml
        from tools import ci_lane_worker as worker

        workflow = yaml.safe_load((worker.ROOT / ".github/workflows/ci.yml").read_text())
        steps = workflow["jobs"]["rust"]["steps"]
        positions = [index for index, step in enumerate(steps)
                     if step.get("name") == "Fetch locked Angular target dependencies"]
        self.assertEqual(len(positions), 1)
        fetch = steps[positions[0]]
        self.assertEqual(fetch, {
            "name": "Fetch locked Angular target dependencies",
            "if": "matrix.lane == 'angular-t1' && needs.profile.outputs.renderer == 'true'",
            "timeout-minutes": 5,
            "run": "cargo fetch --locked --target wasm32-unknown-unknown",
        })
        package = steps[positions[0] + 1]
        self.assertEqual(package["name"], "Prepare fresh actual Angular package for T1")
        self.assertEqual(fetch["if"], package["if"])
        self.assertNotIn("continue-on-error", fetch)
        self.assertEqual(package["run"].splitlines(), [
            "npm ci --prefix examples/renderer-profile --ignore-scripts --no-audit --no-fund",
            'mkdir -p "$RUNNER_TEMP/phase2-gate"',
            'objcopy --strip-debug "$PWD/target/debug/latent" "$RUNNER_TEMP/lsf-angular-package-assembler"',
            'python3 tools/build_angular_package.py --input-root examples/angular-application '
            '--toolchain-root examples/renderer-profile --cli "$RUNNER_TEMP/lsf-angular-package-assembler" '
            '--target-root "$RUNNER_TEMP/angular-build" --output "$RUNNER_TEMP/angular-build/actual" '
            '--cargo-target-dir "$PWD/target" --repository https://example.com/source',
        ])


if __name__ == "__main__":
    unittest.main()
