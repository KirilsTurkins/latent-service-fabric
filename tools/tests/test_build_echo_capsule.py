from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "build_echo_capsule.py"
COMPONENT_SOURCE = (
    ROOT
    / "tools"
    / "toolchain-smoke"
    / "examples"
    / "echo_capsule"
    / "component.rs"
)
SPEC = importlib.util.spec_from_file_location("build_echo_capsule", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
build_echo_capsule = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_echo_capsule)


class BuildEchoCapsuleTests(unittest.TestCase):
    def test_wit_bindgen_loads_dependencies_before_the_echo_world(self) -> None:
        source = COMPONENT_SOURCE.read_text(encoding="utf-8")
        context_index = source.index('"../../wit/platform/context"')
        log_index = source.index('"../../wit/platform/log"')
        echo_index = source.index('"../../examples/echo-contract/wit"')

        self.assertLess(context_index, echo_index)
        self.assertLess(log_index, echo_index)
        self.assertIn(
            'world: "examples:echo/service@0.1.0"',
            source,
        )

    def test_root_world_surface_is_exact(self) -> None:
        wit = """\
package root:component;

world root {
  import latent:context/context@0.1.0;
  import latent:log/log@0.1.0;
  export examples:echo/api@0.1.0;
}
"""
        imports, exports = build_echo_capsule.parse_root_world(wit)
        self.assertEqual(imports, build_echo_capsule.EXPECTED_IMPORTS)
        self.assertEqual(exports, build_echo_capsule.EXPECTED_EXPORTS)

    def test_extracted_interface_requires_echo_and_domain_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "component.wit").write_text(
                """\
package root:component;
world root {
  import latent:context/context@0.1.0;
  import latent:log/log@0.1.0;
  export examples:echo/api@0.1.0;
}
""",
                encoding="utf-8",
            )
            dependencies = directory / "deps"
            dependencies.mkdir()
            (dependencies / "echo.wit").write_text(
                """\
package examples:echo@0.1.0;
interface api {
  variant echo-error { empty-message, message-too-large, }
  echo: func(message: string) -> result<string, echo-error>;
}
""",
                encoding="utf-8",
            )
            build_echo_capsule.validate_extracted_interface(directory)

    def test_extracted_interface_rejects_ambient_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "component.wit").write_text(
                """\
package root:component;
world root {
  import latent:context/context@0.1.0;
  import latent:log/log@0.1.0;
  import wasi:filesystem/preopens@0.2.0;
  export examples:echo/api@0.1.0;
}
""",
                encoding="utf-8",
            )
            dependencies = directory / "deps"
            dependencies.mkdir()
            (dependencies / "echo.wit").write_text(
                """\
package examples:echo@0.1.0;
interface api {
  variant echo-error { empty-message, message-too-large, }
  echo: func(message: string) -> result<string, echo-error>;
}
""",
                encoding="utf-8",
            )
            with self.assertRaises(build_echo_capsule.BuildError):
                build_echo_capsule.validate_extracted_interface(directory)

    def test_generated_manifest_uses_the_computed_digest_and_local_trust(self) -> None:
        digest = "a" * 64
        manifest = build_echo_capsule.build_capsule_manifest(digest)
        self.assertEqual(manifest["component"]["digest"], f"sha256:{digest}")
        self.assertEqual(
            manifest["metadata"]["annotations"]["latent.dev/trust"],
            "local-build",
        )

    def test_cargo_artifact_selection_uses_the_echo_example(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifact = Path(temporary) / "echo-capsule.wasm"
            artifact.write_bytes(b"component")
            cargo_output = json.dumps(
                {
                    "reason": "compiler-artifact",
                    "target": {"name": "echo-capsule", "kind": ["example"]},
                    "filenames": [str(artifact)],
                }
            )
            self.assertEqual(
                build_echo_capsule.extract_cargo_artifact(cargo_output), artifact
            )

    def test_output_directory_must_be_below_target_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target_root = Path(temporary) / "target"
            target_root.mkdir()
            resolved = build_echo_capsule.resolve_output_directory(
                Path("target/custom/echo"), ROOT / "target"
            )
            self.assertEqual(resolved, (ROOT / "target/custom/echo").resolve())

            with self.assertRaises(build_echo_capsule.BuildError):
                build_echo_capsule.resolve_output_directory(target_root, target_root)
            with self.assertRaises(build_echo_capsule.BuildError):
                build_echo_capsule.resolve_output_directory(
                    target_root.parent, target_root
                )

    def test_canonical_environment_removes_ambient_rust_flags(self) -> None:
        previous_rustflags = os.environ.get("RUSTFLAGS")
        previous_encoded = os.environ.get("CARGO_ENCODED_RUSTFLAGS")
        previous_target = os.environ.get("CARGO_TARGET_DIR")
        try:
            os.environ["RUSTFLAGS"] = "-C target-cpu=native"
            os.environ["CARGO_ENCODED_RUSTFLAGS"] = "-C\x1ftarget-feature=+simd128"
            os.environ["CARGO_TARGET_DIR"] = "ambient-target"
            environment = build_echo_capsule.canonical_build_environment()
        finally:
            self._restore_environment("RUSTFLAGS", previous_rustflags)
            self._restore_environment("CARGO_ENCODED_RUSTFLAGS", previous_encoded)
            self._restore_environment("CARGO_TARGET_DIR", previous_target)

        self.assertNotIn("RUSTFLAGS", environment)
        self.assertNotIn("CARGO_ENCODED_RUSTFLAGS", environment)
        self.assertNotIn("CARGO_TARGET_DIR", environment)
        self.assertEqual(environment["CARGO_INCREMENTAL"], "0")
        self.assertEqual(environment["SOURCE_DATE_EPOCH"], "0")

    @staticmethod
    def _restore_environment(name: str, value: str | None) -> None:
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


if __name__ == "__main__":
    unittest.main()
