"""Selected Rust recipe exposes its staged compiler to captured-input isolation."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import dev_guest_recipe as adapter
from tools import rust_capsule_build
from tools.dev_workflow.common import DevError


@unittest.skipUnless(sys.platform == "linux", "Maintained Rust compiler discovery requires Linux")
class StagedRustLinker(unittest.TestCase):
    def fixture(self, root, *, version=adapter.ZIG_VERSION, sdk_shadow=False):
        payload, attempt, ambient = root / "payload", root / "attempt", root / "ambient"
        sdk = payload / "sdk"
        for path in (sdk / "bin", sdk / "registry/index", attempt / "app", attempt / "build-cache/zig", ambient):
            path.mkdir(parents=True)
        (sdk / "registry/index/record").write_bytes(b"immutable captured Cargo index")
        zig = attempt / "build-cache/zig/zig"
        zig.write_text("#!/bin/sh\nprintf '%s\\n' '" + version + "'\n", encoding="utf-8")
        zig.chmod(0o700)
        competitor = sdk / "bin/zig" if sdk_shadow else ambient / "zig"
        competitor.write_text("#!/bin/sh\nprintf '%s\\n' 'ambient-compiler'\n", encoding="utf-8")
        competitor.chmod(0o700)
        return payload, attempt / "app", attempt / "output", zig, ambient

    def test_captured_compiler_discovers_staged_zig_without_inherited_tool_paths(self):
        for sdk_shadow in (False, True):
            with self.subTest(sdk_shadow=sdk_shadow), tempfile.TemporaryDirectory(prefix="rust linker spaces-") as temporary:
                payload, project, output, zig, ambient = self.fixture(Path(temporary), sdk_shadow=sdk_shadow)
                sdk = payload / "sdk"
                approval = "sha256:" + "a" * 64

                def selected_build(*args, **kwargs):
                    # This is the same executable lookup used by captured Rust
                    # isolation; the fixture contains no native compiler products.
                    selected = shutil.which("zig", path=os.environ["PATH"])
                    self.assertIsNotNone(selected, "Already staged Zig must be discoverable by the captured compiler")
                    self.assertEqual(Path(selected).resolve(), zig.resolve())
                    self.assertIsNotNone(shutil.which("sh", path=os.environ["PATH"]))
                    self.assertNotIn(str(ambient), os.environ["PATH"].split(os.pathsep))
                    self.assertEqual(args, (project, output, sdk / "bin/capsule-contracts", None,
                                           "https://github.com/KirilsTurkins/latent-service-fabric"))
                    self.assertEqual(kwargs, {"offline": True, "host_linker": project.parent / "build-cache/host-linker",
                                              "rust_bin": sdk / "rust/bin", "executable_approval": approval})

                with patch.dict(os.environ, {"PATH": str(ambient), "CARGO_HOME": str(ambient / "cargo")}), \
                        patch.object(adapter.platform, "machine", return_value="x86_64"), \
                        patch.object(adapter, "unpack_zig", return_value=zig) as unpacked, \
                        patch.object(adapter, "run_bounded", wraps=adapter.run_bounded) as version_probe, \
                        patch.object(rust_capsule_build, "build", side_effect=selected_build) as built:
                    adapter.compile_rust(payload, project, output, lambda: None, executable_approval=approval)
                    built.assert_called_once()
                    unpacked.assert_called_once_with(sdk / "zig.tar.xz", project.parent / "build-cache/zig", unittest.mock.ANY)
                    self.assertEqual(version_probe.call_args.args[0], [str(zig), "version"])
                    self.assertEqual(version_probe.call_args.kwargs["timeout_seconds"], 10)
                    self.assertEqual(version_probe.call_args.kwargs["max_output_bytes"], 1024)
                self.assertEqual((sdk / "registry/index/record").read_bytes(), b"immutable captured Cargo index")
                self.assertEqual((project.parent / "build-cache/cargo/registry/index/record").read_bytes(),
                                 b"immutable captured Cargo index")

    def test_wrong_staged_zig_version_fails_before_linker_or_compiler_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            payload, project, output, zig, ambient = self.fixture(Path(temporary), version="0.15.0")
            with patch.dict(os.environ, {"PATH": str(ambient)}), \
                    patch.object(adapter.platform, "machine", return_value="x86_64"), \
                    patch.object(adapter, "unpack_zig", return_value=zig), \
                    patch.object(adapter, "linker") as linker, \
                    patch.object(rust_capsule_build, "build") as built:
                with self.assertRaisesRegex(DevError, "guest-linker-version"):
                    adapter.compile_rust(payload, project, output, lambda: None)
                linker.assert_not_called()
                built.assert_not_called()
                self.assertNotIn(str(zig.parent), os.environ["PATH"].split(os.pathsep))
            self.assertFalse(output.exists())
            self.assertFalse((project.parent / "build-cache/host-linker").exists())


if __name__ == "__main__":
    unittest.main()
