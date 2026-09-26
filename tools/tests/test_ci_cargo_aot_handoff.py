"""Keep authenticated AOT preparation between the Cargo prepare and test recipes."""
from pathlib import Path
import shlex
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]


def handoff(workflow):
    """Select exactly one unconditional producer, preparation and consumer."""
    steps = workflow["jobs"]["rust"]["steps"]
    names = (
        "Build workspace binaries and test harnesses",
        "Prepare authenticated AOT test inputs",
        "Run tests",
    )
    selected = []
    indices = []
    for name in names:
        matches = [(index, step) for index, step in enumerate(steps) if step.get("name") == name]
        if len(matches) != 1:
            raise ValueError("missing or duplicate AOT handoff step")
        index, step = matches[0]
        if "if" in step or step.get("continue-on-error", False):
            raise ValueError("AOT handoff must remain unconditional and fail closed")
        indices.append(index)
        selected.append(step["run"])
    if indices != sorted(indices):
        raise ValueError("AOT preparation must follow inventory creation and precede tests")
    return selected


class AotRecipeHandoffTests(unittest.TestCase):
    def setUp(self):
        self.workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())

    def test_same_inventory_reaches_authenticated_preparation_before_tests(self):
        prepare, aot, test = handoff(self.workflow)
        producer = shlex.split(prepare)
        commands = [shlex.split(line) for line in aot.splitlines() if line and not line.lstrip().startswith("#")]
        self.assertEqual(producer[:4], ["python3", "tools/ci_cargo.py", "run", "prepare"])
        self.assertEqual(commands[0], ["python3", "-m", "unittest", "tools.tests.test_aot_test_inputs", "tools.tests.test_run_aot_tests"])
        consumer = commands[1]
        self.assertEqual(consumer[:3], ["python3", "tools/aot_test_inputs.py", "prepare"])
        self.assertEqual(producer[producer.index("--inventory") + 1], consumer[consumer.index("--inventory") + 1])
        from tools import ci_cargo
        lines = [shlex.split(line) for line in test.splitlines()]
        self.assertEqual(lines[0], ['set', '-o', 'pipefail'])
        recipes = ['workspace-tests', 'doctests', 'signing-compatibility']
        logs = ['ci-workspace-tests.log', 'ci-doctests.log', 'ci-signing-compatibility.log']
        coverage = [None, 'explicit-doctests', 'signing-compatibility']
        for index, (recipe, log, selection) in enumerate(zip(recipes, logs, coverage)):
            self.assertEqual(lines[1 + index * 2], ['python3', 'tools/ci_cargo.py', 'run', recipe,
                             '2>&1', '|', 'tee', '$RUNNER_TEMP/' + log])
            expected = ['python3', 'tools/ci_suite_discovery.py']
            if selection:
                expected += ['--recipe', selection]
            self.assertEqual(lines[2 + index * 2], expected + ['--execution-log', '$RUNNER_TEMP/' + log])
        self.assertEqual(len(lines), 7)
        self.assertEqual([ci_cargo.RECIPES[name][0] for name in recipes], list(ci_cargo.RECIPES['test']))

    def test_only_aot_selectors_are_exported_from_the_prepared_manifest(self):
        _, aot, _ = handoff(self.workflow)
        commands = [shlex.split(line) for line in aot.splitlines() if line and not line.lstrip().startswith("#")]
        prepare, environment = commands[1:]
        output = prepare[prepare.index("--output") + 1]
        self.assertEqual(environment, [
            "python3", "tools/aot_test_inputs.py", "environment", "--manifest", output + "/manifest.json",
            "|", "grep", "^LSF_AOT_", ">>", "$GITHUB_ENV",
        ])

    def test_missing_preparation_is_not_a_valid_merge(self):
        steps = self.workflow["jobs"]["rust"]["steps"]
        steps[:] = [step for step in steps if step.get("name") != "Prepare authenticated AOT test inputs"]
        with self.assertRaisesRegex(ValueError, "missing or duplicate"):
            handoff(self.workflow)

    def test_preparation_after_tests_is_not_a_valid_merge(self):
        steps = self.workflow["jobs"]["rust"]["steps"]
        aot = next(step for step in steps if step.get("name") == "Prepare authenticated AOT test inputs")
        steps.remove(aot)
        steps.append(aot)
        with self.assertRaisesRegex(ValueError, "precede tests"):
            handoff(self.workflow)

    def test_skipped_or_ignored_preparation_is_not_a_valid_merge(self):
        steps = self.workflow["jobs"]["rust"]["steps"]
        aot = next(step for step in steps if step.get("name") == "Prepare authenticated AOT test inputs")
        for field, value in (("if", "false"), ("continue-on-error", True)):
            with self.subTest(field=field):
                aot[field] = value
                with self.assertRaisesRegex(ValueError, "fail closed"):
                    handoff(self.workflow)
                del aot[field]


if __name__ == "__main__":
    unittest.main()
