"""Execute the profile loader with only its declared Git sparse-checkout inputs."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

from tools import ci_suite_inventory as registry
from tools.tests.test_ci_result import successful

ROOT = Path(__file__).resolve().parents[2]


class SparseProfileTests(unittest.TestCase):
    @contextmanager
    def sparse_checkout(self, job: str):
        workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
        checkout = workflow["jobs"][job]["steps"][0]["with"]
        self.assertFalse(checkout["sparse-checkout-cone-mode"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = root / "tools"
            tools.mkdir()
            for name in ("ci_profile.py", "ci_result.py", "ci_suite_inventory.py", "ci_suite_cases.py"):
                shutil.copyfile(ROOT / "tools" / name, tools / name)
            (tools / "ci").mkdir()
            shutil.copyfile(ROOT / "tools/ci/suites.json", tools / "ci/suites.json")
            for name in ("suites.d", "suites.cases.d"):
                shutil.copytree(ROOT / "tools/ci" / name, tools / "ci" / name)
            self.git(root, "init", "--quiet")
            self.git(root, "add", ".")
            self.git(root, "-c", "user.name=Sparse profile fixture", "-c",
                     "user.email=sparse@example.invalid", "commit", "--quiet", "-m", "fixture")
            self.git(root, "sparse-checkout", "set", "--no-cone", "--stdin",
                     input=checkout["sparse-checkout"])
            # -I ignores the parent's PYTHONPATH and user packages. Only the
            # actual declared checkout supplies project modules on the child.
            script = (
                "import json,sys;sys.path.insert(0,'.');"
                "from tools.ci_suite_inventory import load;"
                "print(json.dumps(load()['suites'],sort_keys=True))"
            )
            result = subprocess.run([sys.executable, "-I", "-c", script], cwd=root,
                                    text=True, capture_output=True, timeout=30, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), registry.load()["suites"])
            yield root

    def test_declared_sparse_inputs_run_profile_and_preserve_all_additive_cases(self) -> None:
        with self.sparse_checkout("profile") as root:
            event = root / "event.json"
            event.write_text("{}")
            environment = {key: value for key, value in os.environ.items()
                           if not key.startswith("GITHUB_")}
            result = subprocess.run(
                [sys.executable, "-I", "tools/ci_profile.py", "--event-name", "workflow_dispatch",
                 "--event-path", str(event)], cwd=root, env=environment,
                text=True, capture_output=True, timeout=30, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("CI profile: full", result.stdout)
            self.assertIn('"catalog"', result.stdout)

    def test_declared_result_checkout_executes_the_unchanged_fail_closed_gate(self) -> None:
        with self.sparse_checkout("result") as root:
            for result_name, expected in (("success", 0), ("failure", 1)):
                results = successful("full")
                results["catalog"]["result"] = result_name
                environment = {**os.environ, "CI_JOB_RESULTS": json.dumps(results)}
                result = subprocess.run(
                    [sys.executable, "-I", "tools/ci_result.py"], cwd=root, env=environment,
                    text=True, capture_output=True, timeout=30, check=False,
                )
                self.assertEqual(result.returncode, expected, result.stderr)

    @staticmethod
    def git(root: Path, *args: str, input: str | None = None) -> None:
        subprocess.run(["git", *args], cwd=root, input=input, text=True,
                       capture_output=True, timeout=30, check=True)


if __name__ == "__main__":
    unittest.main()
