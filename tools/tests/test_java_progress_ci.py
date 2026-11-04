"""Exercise the real sparse readers without changing the selected CI gates."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

class SparseCheckoutTests(unittest.TestCase):
    def test_ci_readers_materialize_case_helpers_and_fragments_with_real_sparse_checkout(self):
        import yaml
        root = Path(__file__).resolve().parents[2]
        workflow = yaml.safe_load((root / ".github/workflows/ci.yml").read_text())
        required = ("tools/ci_suite_inventory.py", "tools/ci_suite_cases.py",
                    "tools/ci/suites.json", "tools/ci/suites.d/ordinary.json",
                    "tools/ci/suites.cases.d/added.json")
        for job in ("profile", "result"):
            steps = workflow["jobs"][job]["steps"]
            checkout = next(step["with"] for step in steps if "sparse-checkout" in step.get("with", {}))
            self.assertIs(checkout["sparse-checkout-cone-mode"], False)
            patterns = checkout["sparse-checkout"].splitlines()
            for omitted in (None, "/tools/ci_suite_cases.py", "/tools/ci/suites.cases.d/"):
                with self.subTest(job=job, omitted=omitted), tempfile.TemporaryDirectory() as temporary:
                    tree = Path(temporary)
                    for name in (*required, "tools/unrelated.py"):
                        path = tree / name
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text("fixed sparse checkout fixture\n")
                    def git(*args, input=None):
                        return subprocess.run(["git", *args], cwd=tree, input=input, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=10)
                    git("init", "-q")
                    git("add", ".")
                    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                        "-c", "commit.gpgsign=false", "commit", "-qm", "sparse fixture")
                    selected = [name for name in patterns if name != omitted]
                    git("sparse-checkout", "set", "--no-cone", "--stdin", input="\n".join(selected)+"\n")
                    missing = {name for name in required if not (tree / name).is_file()}
                    expected = ({"tools/ci_suite_cases.py"} if omitted == "/tools/ci_suite_cases.py"
                        else {"tools/ci/suites.cases.d/added.json"} if omitted else set())
                    self.assertEqual(missing, expected)
                    self.assertFalse((tree / "tools/unrelated.py").exists())

    def test_sparse_reader_job_contracts_match_the_workflow(self):
        import yaml
        root = Path(__file__).resolve().parents[2]
        workflow = yaml.safe_load((root / ".github/workflows/ci.yml").read_text())
        for job in ("profile", "result"):
            record = json.loads((root / f"tools/ci/contracts/workflows/ci.yml/jobs/{job}.json").read_text())
            for field in ("sparse-checkout", "sparse-checkout-cone-mode", "persist-credentials"):
                with self.subTest(job=job, field=field):
                    self.assertEqual(workflow["jobs"][job]["steps"][0]["with"][field],
                        record["definition"]["steps"][0]["with"][field])

    def test_signed_job_preserves_the_common_historical_baseline(self):
        root = Path(__file__).resolve().parents[2]
        contracts = root / "tools/ci/contracts/workflows/java-checkpoint-context.yml/jobs"
        original = json.loads((contracts / "compiler-context.json").read_bytes())
        added = json.loads((contracts / "signed-progress.json").read_bytes())
        self.assertEqual(added["baselineRevision"], original["baselineRevision"])
        self.assertEqual(added["before"], {})
        self.assertEqual(added["coverage"], {})


if __name__ == "__main__":
    unittest.main()
