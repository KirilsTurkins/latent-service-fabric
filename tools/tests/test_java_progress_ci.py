"""Exercise the real sparse readers without changing the selected CI gates."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

class SparseCheckoutTests(unittest.TestCase):
    def test_ci_readers_materialize_the_tooling_subtree_with_real_sparse_checkout(self):
        import yaml
        root = Path(__file__).resolve().parents[2]
        workflow = yaml.safe_load((root / ".github/workflows/ci.yml").read_text())
        required = ("tools/ci_profile.py", "tools/ci_result.py", "tools/ci_suite_inventory.py",
                    "tools/ci/suites.json", "tools/ci/suites.d/ordinary.json")
        for job in ("profile", "result"):
            steps = workflow["jobs"][job]["steps"]
            checkout = next(step["with"] for step in steps if "sparse-checkout" in step.get("with", {}))
            self.assertIs(checkout["sparse-checkout-cone-mode"], False)
            patterns = checkout["sparse-checkout"].splitlines()
            for omitted in (None, "/tools/"):
                with self.subTest(job=job, omitted=omitted), tempfile.TemporaryDirectory() as temporary:
                    tree = Path(temporary)
                    for name in (*required, "outside/unrelated.py"):
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
                    expected = set(required) if omitted else set()
                    self.assertEqual(missing, expected)
                    self.assertFalse((tree / "outside/unrelated.py").exists())

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

    def test_signed_job_uses_the_current_reviewed_contract_format(self):
        root = Path(__file__).resolve().parents[2]
        contracts = root / "tools/ci/contracts/workflows/java-checkpoint-context.yml/jobs"
        added = json.loads((contracts / "signed-progress.json").read_bytes())
        from tools.ci_contracts import semantic_record
        self.assertEqual(semantic_record(added), added)
        self.assertEqual(added['jobId'], 'signed-progress')


if __name__ == "__main__":
    unittest.main()
