#!/usr/bin/env python3
"""Execute the real renderer/node gates from explicitly prepared artifacts."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import sys

try:
    from tools.test_run import ProcessFailure, TestRun, contract, require, selected_contract
    from tools.prepared_test_harness import execute, wasm
    from tools import ci_suite_inventory as registry, ci_rust_artifacts as artifacts
except ModuleNotFoundError as error:
    if error.name != "tools":
        raise
    from test_run import ProcessFailure, TestRun, contract, require, selected_contract
    from prepared_test_harness import execute, wasm
    import ci_suite_inventory as registry
    import ci_rust_artifacts as artifacts

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-manifest", type=Path)
    parser.add_argument("--component", type=Path)
    parser.add_argument("--preflight", action="store_true", help="environment only, before builds")
    parser.add_argument("--diagnostic-root", type=Path)
    parser.add_argument("--inject-failure", choices=["after-discovery"], help="no execution after a real harness discovery")
    args = parser.parse_args(argv)
    policy, rows = selected_contract("angular-renderer", repo=ROOT, diagnostic_root=args.diagnostic_root)
    with TestRun("angular-renderer", policy, repo=ROOT, diagnostic_root=args.diagnostic_root,
                 reproduction={"suite": "angular-renderer", "preflight": args.preflight,
                               "fault": args.inject_failure or "none"}) as owner:
        owner.source_identity()
        owner.prerequisites(before_build=True)
        if args.preflight:
            return 0
        require(args.component is not None and args.test_manifest is not None,
                "invalid-fixture", "explicit-renderer-artifacts-required")
        private = args.component.parent / "renderer.wasm"
        owner.prerequisites({"test-manifest": args.test_manifest, "component": args.component,
                             "private-renderer": private})
        component = wasm(owner, "component", args.component)
        private = wasm(owner, "private-renderer", private)
        data = registry.load(ROOT / "tools/ci/suites.json")
        selections = registry.process_cases(data, "angular-renderer")
        owner.declare_cases([case for cases in selections.values() for case in cases])
        owner.reproduction.update(recipe=rows[policy["suiteIds"][0]]["recipe"],
                                  recipeIdentity=registry.process_recipe_identity(data, "angular-renderer"),
                                  mode="process")
        environment = owner.execution_environment(dict(
            os.environ, LSF_ANGULAR_COMPONENT=str(component),
            LSF_ANGULAR_PRIVATE_COMPONENT=str(private)))
        target = Path(environment.get("CARGO_TARGET_DIR", ROOT / "target"))
        if not target.is_absolute():
            target = ROOT / target
        # Capture every intended owner before discovery/fault injection, not just
        # the prefix reached before the first failure.
        for key, selected in selections.items():
            row = rows[key]
            suite = artifacts.Suite(row["manifest"], row["target"], row["source"], "",
                                    frozenset(row["expectedIgnored"]), False, row["kind"])
            artifact = artifacts.read_inventory(args.test_manifest, ROOT, suite, target=target.resolve())
            owner.artifact(key, artifact.executable, 1024 * 1024 * 1024)
        for key, selected in selections.items():
            execute(owner, rows[key], args.test_manifest, environment,
                    selected=selected, fault=args.inject_failure)
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ProcessFailure, OSError, ValueError, KeyboardInterrupt) as error:
        reason = error.reason if isinstance(error, ProcessFailure) else type(error).__name__
        print("Angular renderer test failed: " + reason, file=sys.stderr)
        raise SystemExit(1)
