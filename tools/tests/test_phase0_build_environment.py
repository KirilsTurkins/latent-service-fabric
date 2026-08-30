from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
BUILD_ENVIRONMENT = ROOT / "tools" / "phase0_build_environment.sh"


def clean_environment(**updates: str) -> dict[str, str]:
    environment = {
        "HOME": os.environ.get("HOME", "/tmp"),
        "LC_ALL": "C",
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    }
    environment.update(updates)
    return environment


def run_policy(
    script: str, *, environment: dict[str, str], cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            "--noprofile",
            "--norc",
            "-c",
            f'source "{BUILD_ENVIRONMENT}"; {script}',
        ],
        text=True,
        capture_output=True,
        check=False,
        env=environment,
        cwd=cwd,
    )


class Phase0BuildEnvironmentTests(unittest.TestCase):
    def test_rejects_inherited_build_override_families(self) -> None:
        rejected_names = (
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
            "CARGO_BUILD_TARGET",
            "CARGO_PROFILE_RELEASE_LTO",
            "CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_RUSTFLAGS",
            "CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER",
            "CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_RUNNER",
            "CC",
            "CXX",
            "AR",
            "CPPFLAGS",
            "CFLAGS",
            "CXXFLAGS",
            "ARFLAGS",
            "LDFLAGS",
            "CC_x86_64_unknown_linux_gnu",
            "x86_64_unknown_linux_gnu_CC",
        )
        for name in rejected_names:
            with self.subTest(name=name):
                result = run_policy(
                    "phase0_reject_inherited_build_overrides",
                    environment=clean_environment(**{name: "host-override"}),
                )
                self.assertEqual(result.returncode, 2, result)
                self.assertIn(name, result.stderr)

    def test_accepts_an_inherited_cargo_target_directory(self) -> None:
        result = run_policy(
            "phase0_reject_inherited_build_overrides",
            environment=clean_environment(CARGO_TARGET_DIR="/tmp/phase0-target"),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")

    def test_release_cargo_exports_the_committed_recipe(self) -> None:
        expected = {
            "CARGO_INCREMENTAL": "0",
            "CARGO_PROFILE_RELEASE_CODEGEN_UNITS": "16",
            "CARGO_PROFILE_RELEASE_DEBUG": "1",
            "CARGO_PROFILE_RELEASE_DEBUG_ASSERTIONS": "false",
            "CARGO_PROFILE_RELEASE_INCREMENTAL": "false",
            "CARGO_PROFILE_RELEASE_LTO": "false",
            "CARGO_PROFILE_RELEASE_OPT_LEVEL": "3",
            "CARGO_PROFILE_RELEASE_OVERFLOW_CHECKS": "false",
            "CARGO_PROFILE_RELEASE_PANIC": "unwind",
            "CARGO_PROFILE_RELEASE_STRIP": "none",
        }
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            fake_cargo = temporary / "cargo"
            fake_cargo.write_text(
                "#!/usr/bin/env bash\n"
                "env\n"
                "printf 'PHASE0_ARG=%s\\n' \"$@\"\n",
                encoding="utf-8",
            )
            fake_cargo.chmod(0o755)
            environment = clean_environment(
                CARGO_TARGET_DIR="/tmp/phase0-target",
                PATH=f"{temporary}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            )

            result = run_policy(
                "phase0_release_cargo build --release --locked",
                environment=environment,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        observed = dict(
            line.split("=", 1)
            for line in result.stdout.splitlines()
            if "=" in line and not line.startswith("PHASE0_ARG=")
        )
        for name, value in expected.items():
            self.assertEqual(observed.get(name), value, name)
        self.assertEqual(observed.get("CARGO_TARGET_DIR"), "/tmp/phase0-target")
        self.assertEqual(
            [
                line.removeprefix("PHASE0_ARG=")
                for line in result.stdout.splitlines()
                if line.startswith("PHASE0_ARG=")
            ],
            ["build", "--release", "--locked"],
        )

    def test_release_rejects_hidden_cargo_home_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cargo_home = Path(directory) / "cargo-home"
            cargo_home.mkdir()
            (cargo_home / "config.toml").write_text(
                "[build]\nrustflags = ['-Ctarget-cpu=native']\n",
                encoding="utf-8",
            )
            result = run_policy(
                "phase0_release_cargo build --release --locked",
                environment=clean_environment(CARGO_HOME=str(cargo_home)),
            )

        self.assertEqual(result.returncode, 2, result)
        self.assertIn("reject hidden Cargo configuration", result.stderr)

    def test_release_rejects_command_line_cargo_configuration(self) -> None:
        result = run_policy(
            "phase0_release_cargo build --config profile.release.lto=true --release --locked",
            environment=clean_environment(),
        )

        self.assertEqual(result.returncode, 2, result)
        self.assertIn("reject Cargo --config overrides", result.stderr)

    def test_release_rejects_ancestor_cargo_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            invocation = root / "workspace" / "nested"
            invocation.mkdir(parents=True)
            cargo_config = root / "workspace" / ".cargo"
            cargo_config.mkdir()
            (cargo_config / "config.toml").write_text(
                "[target.x86_64-unknown-linux-gnu]\nlinker = 'untrusted-linker'\n",
                encoding="utf-8",
            )
            result = run_policy(
                "phase0_release_cargo build --release --locked",
                environment=clean_environment(),
                cwd=invocation,
            )

        self.assertEqual(result.returncode, 2, result)
        self.assertIn("reject hidden Cargo configuration", result.stderr)


if __name__ == "__main__":
    unittest.main()
