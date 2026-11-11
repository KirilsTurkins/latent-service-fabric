"""Protocol controls, not substitutes for the actual Rust storage qualification."""

import contextlib
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import qualify_local_payload_recovery as qualification


def output(names: list[str]) -> str:
    return "\n".join([
        *(f"test {name} ... ok" for name in names),
        f"test result: ok. {len(names)} passed; 0 failed; 0 ignored; "
        "0 measured; 12 filtered out; finished in 0.01s",
    ])


class TestOutputControls(unittest.TestCase):
    def test_exact_export_runs_once(self):
        qualification.verify_test_output(output(["export"]), "export", exact=True)

    def test_current_writer_cases_do_not_require_a_frozen_count(self):
        for count in (1, 2, 5):
            with self.subTest(count=count):
                names = [f"local::write::tests::case_{number}" for number in range(count)]
                qualification.verify_test_output(output(names), "local::write::tests::", exact=False)

    def test_successful_zero_match_is_not_evidence(self):
        for exact in (False, True):
            with self.subTest(exact=exact), self.assertRaises(RuntimeError):
                qualification.verify_test_output(output([]), "export", exact=exact)

    def test_exact_export_cannot_be_substituted(self):
        with self.assertRaises(RuntimeError):
            qualification.verify_test_output(output(["other"]), "export", exact=True)

    def test_writer_filter_cannot_be_satisfied_by_an_unrelated_test(self):
        with self.assertRaises(RuntimeError):
            qualification.verify_test_output(output(["other::case"]), "local::write::tests::", exact=False)

    def test_bare_prefix_is_not_an_executed_case(self):
        with self.assertRaises(RuntimeError):
            qualification.verify_test_output(output(["local::write::tests::"]), "local::write::tests::", exact=False)

    def test_duplicate_execution_is_rejected(self):
        for exact in (False, True):
            with self.subTest(exact=exact), self.assertRaises(RuntimeError):
                qualification.verify_test_output(output(["export", "export"]), "export", exact=exact)

    def test_exact_export_does_not_accept_additional_cases(self):
        with self.assertRaises(RuntimeError):
            qualification.verify_test_output(output(["export", "other"]), "export", exact=True)

    def test_inconsistent_pass_count_is_rejected(self):
        with self.assertRaises(RuntimeError):
            qualification.verify_test_output(output(["export"]).replace("1 passed", "2 passed"), "export", exact=True)

    def test_failed_ignored_or_measured_results_are_not_success(self):
        for before, after in (("0 failed", "1 failed"), ("0 ignored", "1 ignored"), ("0 measured", "1 measured")):
            with self.subTest(after=after), self.assertRaises(RuntimeError):
                qualification.verify_test_output(output(["export"]).replace(before, after), "export", exact=True)

    def test_failed_test_line_cannot_hide_beside_a_success_summary(self):
        with self.assertRaises(RuntimeError):
            qualification.verify_test_output("test other ... FAILED\n" + output(["export"]), "export", exact=True)

    def test_missing_or_duplicate_summary_is_rejected(self):
        valid = output(["export"])
        for text in ("test export ... ok", valid + "\n" + valid.splitlines()[-1]):
            with self.subTest(text=text), self.assertRaises(RuntimeError):
                qualification.verify_test_output(text, "export", exact=True)


class QualificationProcessControls(unittest.TestCase):
    def run_main(self, parent: str, runner):
        with patch.object(qualification.tempfile, "gettempdir", return_value=parent), \
                patch.object(qualification, "run_bounded_result", side_effect=runner), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            qualification.main()

    def test_writer_regressions_precede_real_export_and_recovery_under_original_bounds(self):
        calls = []
        def runner(command, repository, environment, timeout, maximum):
            calls.append((command, repository, environment.copy(), timeout, maximum))
            selected = command[6]
            names = [selected + "case"] if selected.endswith("::") else [selected]
            return subprocess.CompletedProcess(command, 0, output(names).encode(), b"")
        with tempfile.TemporaryDirectory() as parent:
            self.run_main(parent, runner)
            self.assertEqual([call[0][4] for call in calls], ["latent-local-blobs", "latent-commit", "latentd"])
            roots = {call[2]["TMPDIR"] for call in calls}
            self.assertEqual(len(roots), 1)
            root = Path(roots.pop())
            self.assertEqual(root.parent, Path(parent).resolve())
            self.assertFalse(root.exists())
            for command, repository, environment, timeout, maximum in calls:
                self.assertEqual(repository, Path(qualification.__file__).resolve().parent.parent)
                self.assertEqual((timeout, maximum), (420, 16 * 1024 * 1024))
                self.assertEqual(environment["LSF_LINKED_PAYLOAD_REPORT"], str(root / "producer-root.txt"))
                self.assertIn("--locked", command)
                self.assertIn("--test-threads=1", command)
            self.assertNotIn("--ignored", calls[0][0])
            for command, *_ in calls[1:]:
                self.assertIn("--ignored", command)
                self.assertIn("--exact", command)

    def test_zero_writer_tests_stop_before_export_and_clean_only_retired_files(self):
        roots = []
        def runner(command, _repository, environment, _timeout, _maximum):
            roots.append(Path(environment["TMPDIR"]))
            return subprocess.CompletedProcess(command, 0, output([]).encode(), b"")
        with tempfile.TemporaryDirectory() as parent:
            with self.assertRaises(RuntimeError):
                self.run_main(parent, runner)
            self.assertEqual(len(roots), 1)
            self.assertFalse(roots[0].exists())

    def test_nonzero_child_exit_stops_before_export_even_with_successful_output(self):
        roots = []
        def runner(command, _repository, environment, _timeout, _maximum):
            roots.append(Path(environment["TMPDIR"]))
            return subprocess.CompletedProcess(command, 1, output([command[6] + "case"]).encode(), b"")
        with tempfile.TemporaryDirectory() as parent:
            with self.assertRaises(subprocess.CalledProcessError):
                self.run_main(parent, runner)
            self.assertEqual(len(roots), 1)
            self.assertFalse(roots[0].exists())

    def test_unestablished_child_retirement_keeps_original_files(self):
        roots = []
        def runner(_command, _repository, environment, _timeout, _maximum):
            root = Path(environment["TMPDIR"])
            roots.append(root)
            (root / "still-owned").write_text("keep", encoding="utf-8")
            raise RuntimeError("retirement-not-established")
        with tempfile.TemporaryDirectory() as parent:
            with self.assertRaisesRegex(RuntimeError, "retirement-not-established"):
                self.run_main(parent, runner)
            self.assertEqual(len(roots), 1)
            self.assertEqual((roots[0] / "still-owned").read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
