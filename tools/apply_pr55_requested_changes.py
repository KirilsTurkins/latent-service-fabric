from __future__ import annotations

from pathlib import Path

ROOT = Path.cwd()


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def write(relative: str, content: str) -> None:
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def replace_once(relative: str, old: str, new: str) -> None:
    text = read(relative)
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"expected one occurrence in {relative}, found {count}: {old[:160]!r}"
        )
    write(relative, text.replace(old, new, 1))


def replace_count(relative: str, old: str, new: str, expected: int) -> None:
    text = read(relative)
    count = text.count(old)
    if count != expected:
        raise RuntimeError(
            f"expected {expected} occurrences in {relative}, found {count}: {old[:160]!r}"
        )
    write(relative, text.replace(old, new))


def edit_method(relative: str, start_marker: str, end_marker: str, transform) -> None:
    text = read(relative)
    start = text.index(start_marker)
    end = text.index(end_marker, start + len(start_marker))
    segment = text[start:end]
    updated = transform(segment)
    if updated == segment:
        raise RuntimeError(f"method edit made no change in {relative}: {start_marker}")
    write(relative, text[:start] + updated + text[end:])


write(
    "crates/latent-wasmtime/build.rs",
    """fn main() {
    let target = std::env::var("TARGET").expect("TARGET must be set by Cargo");
    println!("cargo:rustc-env=LATENT_WASMTIME_HOST_TARGET={target}");
}
""",
)

replace_once(
    "tools/validate_foundation.py",
    (
        'LEGACY_BINDING_BUILD_SCRIPTS = (\n'
        '    "crates/latent-wasmtime/build.rs",\n'
        '    "tools/toolchain-smoke/build.rs",\n'
        ')\n'
    ),
    (
        'LEGACY_BINDING_BUILD_SCRIPTS = ("tools/toolchain-smoke/build.rs",)\n'
        'WASMTIME_TARGET_BUILD_SCRIPT = "crates/latent-wasmtime/build.rs"\n'
        'WASMTIME_TARGET_BUILD_REQUIRED_TOKENS = (\n'
        '    \'std::env::var("TARGET")\',\n'
        '    "cargo:rustc-env=LATENT_WASMTIME_HOST_TARGET={target}",\n'
        ')\n'
        'WASMTIME_TARGET_BUILD_FORBIDDEN_TOKENS = (\n'
        '    "OUT_DIR",\n'
        '    "stage_echo_world",\n'
        '    "copy_wit_tree",\n'
        '    "write_bindings_invocation",\n'
        '    "echo_bindings.rs",\n'
        '    "wasmtime::component::bindgen!",\n'
        '    "examples/echo-contract/wit",\n'
        '    "wit/platform/context",\n'
        '    "wit/platform/log",\n'
        ')\n'
    ),
)
replace_once(
    "tools/validate_foundation.py",
    (
        '    for relative in LEGACY_BINDING_BUILD_SCRIPTS:\n'
        '        if (root / relative).exists():\n'
        '            fail(f"legacy duplicated binding generator must be removed: {relative}")\n'
    ),
    (
        '    wasmtime_build_script = root / WASMTIME_TARGET_BUILD_SCRIPT\n'
        '    if not wasmtime_build_script.is_file():\n'
        '        fail(\n'
        '            "Wasmtime target-export build script missing: "\n'
        '            f"{WASMTIME_TARGET_BUILD_SCRIPT}"\n'
        '        )\n'
        '    else:\n'
        '        text = wasmtime_build_script.read_text(encoding="utf-8")\n'
        '        for token in WASMTIME_TARGET_BUILD_REQUIRED_TOKENS:\n'
        '            if token not in text:\n'
        '                fail(\n'
        '                    f"Wasmtime target-export build script does not reference {token}: "\n'
        '                    f"{WASMTIME_TARGET_BUILD_SCRIPT}"\n'
        '                )\n'
        '        for token in WASMTIME_TARGET_BUILD_FORBIDDEN_TOKENS:\n'
        '            if token in text:\n'
        '                fail(\n'
        '                    "Wasmtime target-export build script must not duplicate binding "\n'
        '                    f"generation ({token}): {WASMTIME_TARGET_BUILD_SCRIPT}"\n'
        '                )\n'
        '\n'
        '    for relative in LEGACY_BINDING_BUILD_SCRIPTS:\n'
        '        if (root / relative).exists():\n'
        '            fail(f"legacy duplicated binding generator must be removed: {relative}")\n'
    ),
)

write(
    "tools/tests/phase0_test_environment.py",
    """from __future__ import annotations

import os
from collections.abc import Mapping
from fnmatch import fnmatchcase

PHASE0_REJECTED_BUILD_OVERRIDE_PATTERNS = (
    "RUSTFLAGS",
    "RUSTDOCFLAGS",
    "RUSTC",
    "RUSTC_BOOTSTRAP",
    "RUSTC_WRAPPER",
    "RUSTC_WORKSPACE_WRAPPER",
    "RUSTUP_TOOLCHAIN",
    "CARGO_ENCODED_RUSTFLAGS",
    "CARGO_ENCODED_RUSTDOCFLAGS",
    "CARGO_INCREMENTAL",
    "CARGO_BUILD_*",
    "CARGO_PROFILE_*",
    "CARGO_TARGET_*_RUSTFLAGS",
    "CARGO_TARGET_*_LINKER",
    "CARGO_TARGET_*_RUNNER",
    "PHASE0_NATIVE_RELEASE_PATH_REMAP",
    "PHASE0_NATIVE_RELEASE_LINKER_BUILD_ID",
    "PHASE0_NATIVE_RELEASE_PROMOTED_LOCALS",
    "CC",
    "CXX",
    "AR",
    "CPPFLAGS",
    "CFLAGS",
    "CXXFLAGS",
    "ARFLAGS",
    "LDFLAGS",
    "CC_*",
    "CXX_*",
    "AR_*",
    "CPPFLAGS_*",
    "CFLAGS_*",
    "CXXFLAGS_*",
    "ARFLAGS_*",
    "LDFLAGS_*",
    "*_CC",
    "*_CXX",
    "*_AR",
    "*_CPPFLAGS",
    "*_CFLAGS",
    "*_CXXFLAGS",
    "*_ARFLAGS",
    "*_LDFLAGS",
)


def is_phase0_rejected_build_override(name: str) -> bool:
    return any(
        fnmatchcase(name, pattern)
        for pattern in PHASE0_REJECTED_BUILD_OVERRIDE_PATTERNS
    )


def sanitized_phase0_environment(
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    environment = dict(os.environ if base is None else base)
    return {
        name: value
        for name, value in environment.items()
        if not is_phase0_rejected_build_override(name)
    }
""",
)

write(
    "tools/tests/test_phase0_test_environment.py",
    """from __future__ import annotations

import unittest

from tools.tests.phase0_test_environment import (
    is_phase0_rejected_build_override,
    sanitized_phase0_environment,
)


class Phase0TestEnvironmentTests(unittest.TestCase):
    def test_sanitizes_fixed_and_patterned_build_overrides(self) -> None:
        environment = sanitized_phase0_environment(
            {
                "PATH": "/test/bin",
                "CARGO_HOME": "/test/cargo",
                "CARGO_INCREMENTAL": "0",
                "CARGO_PROFILE_RELEASE_LTO": "thin",
                "CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER": "clang",
                "X86_64_UNKNOWN_LINUX_GNU_CC": "clang",
            }
        )

        self.assertEqual(
            environment,
            {"PATH": "/test/bin", "CARGO_HOME": "/test/cargo"},
        )

    def test_explicit_rejection_tests_can_add_an_override_after_sanitizing(self) -> None:
        environment = sanitized_phase0_environment({"PATH": "/test/bin"})
        environment["CARGO_INCREMENTAL"] = "1"

        self.assertTrue(is_phase0_rejected_build_override("CARGO_INCREMENTAL"))
        self.assertEqual(environment["CARGO_INCREMENTAL"], "1")


if __name__ == "__main__":
    unittest.main()
""",
)

replace_once(
    "tools/tests/test_validate_repository.py",
    "    @staticmethod\n    def _write_foundation(root: Path) -> None:\n",
    (
        '    def test_rejects_wasmtime_build_script_binding_generation(self) -> None:\n'
        '        with tempfile.TemporaryDirectory() as temporary:\n'
        '            root = Path(temporary)\n'
        '            self._write_foundation(root)\n'
        '            build_script = root / foundation.WASMTIME_TARGET_BUILD_SCRIPT\n'
        '            build_script.write_text(\n'
        '                \'fn main() { let _ = std::env::var("OUT_DIR"); \'\n'
        '                \'wasmtime::component::bindgen!(); }\',\n'
        '                encoding="utf-8",\n'
        '            )\n'
        '\n'
        '            foundation.validate_generated_contract_boundaries(root)\n'
        '\n'
        '            self.assertTrue(\n'
        '                any(\n'
        '                    "must not duplicate binding generation" in error\n'
        '                    for error in foundation.ERRORS\n'
        '                )\n'
        '            )\n'
        '\n'
        '    @staticmethod\n'
        '    def _write_foundation(root: Path) -> None:\n'
    ),
)
replace_once(
    "tools/tests/test_validate_repository.py",
    (
        '        component.write_text(\n'
        '            "OUT_DIR wit/platform/runtime examples/echo-contract/wit", encoding="utf-8"\n'
        '        )\n'
    ),
    (
        '        component.write_text(\n'
        '            "OUT_DIR wit/platform/runtime examples/echo-contract/wit", encoding="utf-8"\n'
        '        )\n'
        '        wasmtime = root / foundation.WASMTIME_TARGET_BUILD_SCRIPT\n'
        '        wasmtime.parent.mkdir(parents=True)\n'
        '        wasmtime.write_text(\n'
        '            \'fn main() { let target = std::env::var("TARGET").unwrap(); \'\n'
        '            \'println!("cargo:rustc-env=LATENT_WASMTIME_HOST_TARGET={target}"); }\',\n'
        '            encoding="utf-8",\n'
        '        )\n'
    ),
)

replace_once(
    "tools/tests/test_aggregate_phase0_calibration.py",
    (
        'from tools.phase0_collector_identity import (\n'
        '    COLLECTOR_SCHEMA,\n'
        '    EXPECTED_RELEASE_BUILD_CONFIGURATION,\n'
        ')\n'
    ),
    (
        'from tools.phase0_collector_identity import (\n'
        '    COLLECTOR_SCHEMA,\n'
        '    EXPECTED_RELEASE_BUILD_CONFIGURATION,\n'
        ')\n'
        'from tools.tests.phase0_test_environment import sanitized_phase0_environment\n'
    ),
)


def calibration_missing_aggregate(segment: str) -> str:
    old_header = ') -> None:\n        completed = subprocess.run('
    new_header = (
        ') -> None:\n'
        '        environment = sanitized_phase0_environment()\n'
        '        completed = subprocess.run('
    )
    if segment.count(old_header) != 1:
        raise RuntimeError("unexpected hot-profile missing-aggregate method header")
    segment = segment.replace(old_header, new_header, 1)
    old_call = '            capture_output=True,\n        )'
    if segment.count(old_call) != 1:
        raise RuntimeError("unexpected hot-profile missing-aggregate call shape")
    return segment.replace(
        old_call,
        '            capture_output=True,\n            env=environment,\n        )',
        1,
    )


edit_method(
    "tools/tests/test_aggregate_phase0_calibration.py",
    "    def test_hot_profile_runner_requires_a_fresh_calibration_path",
    "    def test_hot_profile_runner_rejects_a_missing_calibration_path_before_tool_checks",
    calibration_missing_aggregate,
)


def calibration_missing_path(segment: str) -> str:
    old_header = ') -> None:\n        with tempfile.TemporaryDirectory() as directory:'
    new_header = (
        ') -> None:\n'
        '        environment = sanitized_phase0_environment()\n'
        '        with tempfile.TemporaryDirectory() as directory:'
    )
    if segment.count(old_header) != 1:
        raise RuntimeError("unexpected hot-profile missing-path method header")
    segment = segment.replace(old_header, new_header, 1)
    old_call = '                capture_output=True,\n            )'
    if segment.count(old_call) != 1:
        raise RuntimeError("unexpected hot-profile missing-path call shape")
    return segment.replace(
        old_call,
        '                capture_output=True,\n                env=environment,\n            )',
        1,
    )


edit_method(
    "tools/tests/test_aggregate_phase0_calibration.py",
    "    def test_hot_profile_runner_rejects_a_missing_calibration_path_before_tool_checks",
    "    def test_calibration_runner_requires_durable_ref_and_external_output",
    calibration_missing_path,
)


def calibration_runner_boundaries(segment: str) -> str:
    old_header = ') -> None:\n        missing_ref = subprocess.run('
    new_header = (
        ') -> None:\n'
        '        environment = sanitized_phase0_environment()\n'
        '        missing_ref = subprocess.run('
    )
    if segment.count(old_header) != 1:
        raise RuntimeError("unexpected calibration boundary method header")
    segment = segment.replace(old_header, new_header, 1)
    old_call = '            capture_output=True,\n        )'
    if segment.count(old_call) != 3:
        raise RuntimeError("unexpected calibration boundary call count")
    segment = segment.replace(
        old_call,
        '            capture_output=True,\n            env=environment,\n        )',
    )
    if segment.count("environment = dict(os.environ)") != 3:
        raise RuntimeError("unexpected calibration environment count")
    return segment.replace(
        "environment = dict(os.environ)",
        "environment = sanitized_phase0_environment()",
    )


edit_method(
    "tools/tests/test_aggregate_phase0_calibration.py",
    "    def test_calibration_runner_requires_durable_ref_and_external_output",
    "    def test_calibration_runner_rejects_a_local_tag_when_origin_fetch_fails",
    calibration_runner_boundaries,
)


def calibration_local_tag(segment: str) -> str:
    if segment.count("environment = dict(os.environ)") != 1:
        raise RuntimeError("unexpected local-tag environment count")
    return segment.replace(
        "environment = dict(os.environ)",
        "environment = sanitized_phase0_environment()",
        1,
    )


edit_method(
    "tools/tests/test_aggregate_phase0_calibration.py",
    "    def test_calibration_runner_rejects_a_local_tag_when_origin_fetch_fails",
    '\n\nif __name__ == "__main__":',
    calibration_local_tag,
)

replace_once(
    "tools/tests/test_aggregate_phase0_resource_soak.py",
    'from tools.phase0_collector_identity import EXPECTED_RELEASE_BUILD_CONFIGURATION\n',
    (
        'from tools.phase0_collector_identity import EXPECTED_RELEASE_BUILD_CONFIGURATION\n'
        'from tools.tests.phase0_test_environment import sanitized_phase0_environment\n'
    ),
)


def soak_required_inputs(segment: str) -> str:
    old_header = ') -> None:\n        with tempfile.TemporaryDirectory() as directory:'
    new_header = (
        ') -> None:\n'
        '        environment = sanitized_phase0_environment()\n'
        '        with tempfile.TemporaryDirectory() as directory:'
    )
    if segment.count(old_header) != 1:
        raise RuntimeError("unexpected soak required-input method header")
    segment = segment.replace(old_header, new_header, 1)
    old_call = '                capture_output=True,\n            )'
    if segment.count(old_call) != 2:
        raise RuntimeError("unexpected soak required-input call count")
    return segment.replace(
        old_call,
        '                capture_output=True,\n                env=environment,\n            )',
    )


edit_method(
    "tools/tests/test_aggregate_phase0_resource_soak.py",
    "    def test_runner_requires_explicit_calibration_and_durable_ref_before_outputs",
    "    def test_runner_requires_fresh_external_nonoverlapping_output_and_build_paths",
    soak_required_inputs,
)


def soak_paths(segment: str) -> str:
    old_relative = (
        '            relative_output = subprocess.run(\n'
        '                arguments("relative-output"), check=False, text=True, capture_output=True\n'
        '            )'
    )
    new_relative = (
        '            relative_output = subprocess.run(\n'
        '                arguments("relative-output"),\n'
        '                check=False,\n'
        '                text=True,\n'
        '                capture_output=True,\n'
        '                env=sanitized_phase0_environment(),\n'
        '            )'
    )
    if segment.count(old_relative) != 1:
        raise RuntimeError("unexpected relative soak call")
    segment = segment.replace(old_relative, new_relative, 1)

    old_in_tree = (
        '            in_tree_output = subprocess.run(\n'
        '                arguments(ROOT / "target" / "phase0-soak-test-output"),\n'
        '                check=False,\n'
        '                text=True,\n'
        '                capture_output=True,\n'
        '            )'
    )
    new_in_tree = (
        '            in_tree_output = subprocess.run(\n'
        '                arguments(ROOT / "target" / "phase0-soak-test-output"),\n'
        '                check=False,\n'
        '                text=True,\n'
        '                capture_output=True,\n'
        '                env=sanitized_phase0_environment(),\n'
        '            )'
    )
    if segment.count(old_in_tree) != 1:
        raise RuntimeError("unexpected in-tree soak call")
    segment = segment.replace(old_in_tree, new_in_tree, 1)
    if segment.count("environment = dict(os.environ)") != 1:
        raise RuntimeError("unexpected soak path environment count")
    return segment.replace(
        "environment = dict(os.environ)",
        "environment = sanitized_phase0_environment()",
        1,
    )


edit_method(
    "tools/tests/test_aggregate_phase0_resource_soak.py",
    "    def test_runner_requires_fresh_external_nonoverlapping_output_and_build_paths",
    "    def test_runner_rejects_a_local_commit_not_reachable_from_origin_ref",
    soak_paths,
)


def soak_local_commit(segment: str) -> str:
    if segment.count("environment = dict(os.environ)") != 1:
        raise RuntimeError("unexpected soak local-commit environment count")
    return segment.replace(
        "environment = dict(os.environ)",
        "environment = sanitized_phase0_environment()",
        1,
    )


edit_method(
    "tools/tests/test_aggregate_phase0_resource_soak.py",
    "    def test_runner_rejects_a_local_commit_not_reachable_from_origin_ref",
    "    def make_archive",
    soak_local_commit,
)

replace_once(
    "tools/tests/test_run_phase0_hot_path_profiles.py",
    "from pathlib import Path\n",
    (
        "from pathlib import Path\n\n"
        "from tools.tests.phase0_test_environment import sanitized_phase0_environment\n"
    ),
)
replace_once(
    "tools/tests/test_run_phase0_hot_path_profiles.py",
    (
        '    ) -> subprocess.CompletedProcess[str]:\n'
        '        return subprocess.run(\n'
    ),
    (
        '    ) -> subprocess.CompletedProcess[str]:\n'
        '        if environment is None:\n'
        '            environment = sanitized_phase0_environment()\n'
        '        return subprocess.run(\n'
    ),
)
replace_count(
    "tools/tests/test_run_phase0_hot_path_profiles.py",
    "environment = dict(os.environ)",
    "environment = sanitized_phase0_environment()",
    2,
)

workflow_replacements = {
    ".github/workflows/ci.yml": (
        "      - name: Validate contracts, echo component, and generated bindings\n"
        "        run: tools/validate_contracts.sh\n",
        "      - name: Validate contracts, echo component, and generated bindings\n"
        "        run: |\n"
        "          unset CARGO_INCREMENTAL\n"
        "          tools/validate_contracts.sh\n",
    ),
    ".github/workflows/issue-22-validation.yml": (
        "      - name: Build and execute real containment fixtures\n"
        "        run: tools/validate_contracts.sh\n",
        "      - name: Build and execute real containment fixtures\n"
        "        run: |\n"
        "          unset CARGO_INCREMENTAL\n"
        "          tools/validate_contracts.sh\n",
    ),
    ".github/workflows/issue-23-validation.yml": (
        "        run: make phase0-spike-demo\n",
        "        run: |\n"
        "          unset CARGO_INCREMENTAL\n"
        "          make phase0-spike-demo\n",
    ),
    ".github/workflows/issue-25-validation.yml": (
        "      - name: Run the clean-checkout Phase 0 smoke sequence\n"
        "        run: make phase0-gate-smoke\n",
        "      - name: Run the clean-checkout Phase 0 smoke sequence\n"
        "        run: |\n"
        "          unset CARGO_INCREMENTAL\n"
        "          make phase0-gate-smoke\n",
    ),
}
for path, (old, new) in workflow_replacements.items():
    replace_once(path, old, new)

replace_once(
    ".github/workflows/issue-24-validation.yml",
    (
        "      - name: Run deterministic Phase 0 baseline smoke\n"
        '        run: tools/run_phase0_baselines.sh smoke "${RUNNER_TEMP}/phase0-baseline"\n'
    ),
    (
        "      - name: Run deterministic Phase 0 baseline smoke\n"
        "        run: |\n"
        "          unset CARGO_INCREMENTAL\n"
        '          tools/run_phase0_baselines.sh smoke "${RUNNER_TEMP}/phase0-baseline"\n'
    ),
)
replace_once(
    ".github/workflows/issue-24-validation.yml",
    (
        "      - name: Generate full reference evidence\n"
        "        run: tools/run_phase0_baselines.sh full benchmarks/phase0\n"
    ),
    (
        "      - name: Generate full reference evidence\n"
        "        run: |\n"
        "          unset CARGO_INCREMENTAL\n"
        "          tools/run_phase0_baselines.sh full benchmarks/phase0\n"
    ),
)
