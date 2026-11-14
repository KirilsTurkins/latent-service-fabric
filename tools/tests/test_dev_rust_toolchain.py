"""Linux portable builds own a complete Rust installation before invoking Cargo."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import tomllib
import unittest

from tools.ci_lane_inventory import workflow_model

ROOT = Path(__file__).resolve().parents[2]


class LinuxPortableRustToolchain(unittest.TestCase):
    def setUp(self):
        workflow = workflow_model(
            (ROOT / ".github/workflows/developer-tools.yml").read_text(encoding="utf-8"))
        self.job = workflow["jobs"]["linux-portable"]
        self.steps = self.job["steps"]
        self.isolation = next(step for step in self.steps
                              if step.get("name") == "Isolate the Linux portable Rust toolchain")
        self.setup = next(step for step in self.steps
                          if step.get("uses", "").startswith("dtolnay/rust-toolchain@"))

    def test_installation_is_complete_before_the_unchanged_locked_build(self):
        toolchain = tomllib.loads(
            (ROOT / "rust-toolchain.toml").read_text(encoding="utf-8"))["toolchain"]
        for field in ("components", "targets"):
            self.assertEqual(set(self.setup["with"][field].split(",")),
                             set(toolchain[field]))
        # The immutable action selects the repository's pinned Rust version.
        self.assertNotIn("toolchain", self.setup["with"])
        self.assertNotIn("RUSTUP_TOOLCHAIN", self.job.get("env", {}))
        self.assertEqual(self.isolation["shell"], "bash")
        build = next(step for step in self.steps
                     if step.get("name") == "Build native production component execution host")
        self.assertEqual(build["run"],
                         "cargo build -p latent-portable-test-host --release --locked")
        self.assertLess(self.steps.index(self.isolation), self.steps.index(self.setup))
        self.assertLess(self.steps.index(self.setup), self.steps.index(build))
        for step in (self.isolation, self.setup, build):
            self.assertNotIn("if", step)
            self.assertFalse(step.get("continue-on-error", False))

    @unittest.skipUnless(os.name == "posix" and shutil.which("bash"),
                         "requires the Linux workflow shell")
    def test_repeated_setup_owns_fresh_private_homes_without_touching_inherited_tools(self):
        with tempfile.TemporaryDirectory(prefix="portable rustup ") as temporary:
            root = Path(temporary)
            inherited = root / "inherited"
            inherited.mkdir()
            sentinel = inherited / "cargo-clippy"
            sentinel.write_bytes(b"inherited toolchain must remain untouched")
            observed = []
            for attempt in range(2):
                output = root / f"github-env-{attempt}"
                env = dict(os.environ, RUNNER_TEMP=str(root), GITHUB_ENV=str(output),
                           RUSTUP_HOME=str(inherited))
                result = subprocess.run(
                    ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c",
                     self.isolation["run"]], env=env, capture_output=True, text=True,
                    timeout=10, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                records = output.read_text(encoding="utf-8").splitlines()
                self.assertEqual(len(records), 1)
                name, value = records[0].split("=", 1)
                self.assertEqual(name, "RUSTUP_HOME")
                home = Path(value)
                self.assertEqual(home.parent, root)
                self.assertTrue(home.name.startswith("lsf-linux-portable-rustup."))
                self.assertEqual(stat.S_IMODE(home.stat().st_mode), 0o700)
                self.assertEqual(list(home.iterdir()), [])
                self.assertNotIn(home, observed)
                observed.append(home)
            self.assertEqual(sentinel.read_bytes(), b"inherited toolchain must remain untouched")


if __name__ == "__main__":
    unittest.main()
