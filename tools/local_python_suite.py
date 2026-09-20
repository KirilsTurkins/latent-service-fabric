"""Exact unittest adapter for the existing compiler-free artifact-runner tests.

Not a generic module/command executor. Discovery parity is mandatory before tests.
The parent owns process lifetime/output bounds using ci_rust_artifacts.run_owned.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import unittest

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.local_tests import MARKER, MODULE, REPO, TOOLING, plan_suite


def flatten(suite: unittest.TestSuite) -> list[unittest.TestCase]:
    cases = []
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            cases.extend(flatten(item))
        else:
            cases.append(item)
    return cases


def result_summary(cases: list[str], result: unittest.TestResult) -> tuple[int, dict]:
    failed = sorted({test.id().split(" (", 1)[0] for test, _ in [*result.errors, *result.failures]}
                    | {test.id() for test in result.unexpectedSuccesses})
    # A skipped required case is not passing coverage. Expected failures retain
    # unittest's existing assertion semantics; unexpected successes still fail.
    if not result.wasSuccessful():
        code, state = 1, "failed"
    elif result.skipped or result.testsRun != len(cases) or not cases:
        code, state = 3, "not-run"
    else:
        code, state = 0, "passed"
    return code, {"cases": cases, "observed_cases": result.testsRun,
                  "failed_cases": failed, "state": state}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--case")
    args = parser.parse_args(argv)
    plan = plan_suite(REPO, TOOLING, args.case)
    discovered = flatten(unittest.defaultTestLoader.loadTestsFromName(MODULE))
    expected = plan_suite(REPO, TOOLING)["cases"]
    actual = sorted(test.id() for test in discovered)
    if actual != expected:
        print("unittest discovery does not match the declared nonempty case inventory", file=sys.stderr)
        print(MARKER.decode() + json.dumps({"cases": plan["cases"], "observed_cases": 0,
                                          "failed_cases": [], "state": "not-run"}), flush=True)
        return 3
    selected = unittest.TestSuite(test for test in discovered if test.id() in plan["cases"])
    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=2).run(selected)
    code, summary = result_summary(plan["cases"], result)
    print(MARKER.decode() + json.dumps(summary, sort_keys=True), flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
