"""The execution selection must fail closed on partial or fabricated completion."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from tools import aot_test_inputs as inputs
from tools import run_aot_tests as runner


def output(suite):
    lines = []
    for name in sorted(runner.CASES[suite]):
        if suite == "aot_supervisor":
            lines.extend((f"LSF_AOT_CASE started {name}", f"LSF_AOT_CASE passed {name}"))
        else:
            lines.append(f"test {name} ... ok")
    lines.append('LSF_AOT_MEASURE {"stage":"production-executable-verification","elapsed_ns":1}')
    lines.append(f"test result: ok. {len(runner.CASES[suite])} passed; 0 failed; 0 ignored; 0 measured; 0 filtered out")
    return ("\n".join(lines) + "\n").encode()


class ExecutionTests(unittest.TestCase):
    def test_all_three_exact_selections_and_case_observations(self):
        for suite, names in runner.CASES.items():
            raw = ("\n".join(f"{name}: test" for name in sorted(names)) + f"\n\n{len(names)} tests, 0 benchmarks\n").encode()
            runner.listing(raw, names)
            self.assertEqual(runner.result(output(suite), suite)["cases"], sorted(names))

    def test_list_rejects_omissions_duplicates_zero_or_unknown_cases(self):
        suite = "aot_supervisor"
        for raw in (b"0 tests, 0 benchmarks\n", b"unexpected: test\n1 test, 0 benchmarks\n",
                    b"oversized: test\noversized: test\n2 tests, 0 benchmarks\n"):
            with self.assertRaises(runner.artifacts.ArtifactError):
                runner.listing(raw, runner.CASES[suite])

    def test_partial_ignored_duplicate_and_not_run_cannot_satisfy_selection(self):
        for suite in runner.CASES:
            raw = output(suite)
            for changed in (raw.replace(b"0 ignored", b"1 ignored"), raw + b"NOT RUN\n",
                            raw.replace(b"0 filtered out", b"1 filtered out"), raw + raw,
                            raw.replace(b"production-executable-verification", b"unmeasured"),
                            raw.replace(sorted(runner.CASES[suite])[0].encode(), b"missing-case")):
                with self.assertRaises(inputs.InputError):
                    runner.result(changed, suite)

    def test_real_path_sentinels_fail_and_record_every_forbidden_tool(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "bin"
            log = runner.sentinels(root)
            env = dict(os.environ, PATH=str(root), LSF_AOT_TOOL_LOG=str(log))
            for tool in runner.BUILD_TOOLS:
                self.assertEqual(subprocess.run([tool, "--version"], env=env, check=False).returncode, 97)
            self.assertEqual({Path(name).name for name in log.read_text().splitlines()}, set(runner.BUILD_TOOLS))

    def test_unsupported_platform_never_creates_success_report(self):
        with mock.patch.object(runner.platform, "system", return_value="Darwin"):
            with self.assertRaisesRegex(inputs.InputError, "not-run-linux"):
                runner.execute(Path("/unused"), Path("/unused"), Path("/unused"), True)


if __name__ == "__main__":
    unittest.main()
