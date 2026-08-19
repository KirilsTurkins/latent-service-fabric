from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import build_echo_capsule as builder  # noqa: E402


VALID_COMPONENT_WIT = """
package root:component;

world root {
    import latent:context/context@0.1.0;
    import latent:log/log@0.1.0;
    export examples:echo/api@0.1.0;
}
"""


class EchoCapsuleBuildTests(unittest.TestCase):
    def test_component_wit_accepts_the_exact_contract_surface(self) -> None:
        builder.validate_component_wit(VALID_COMPONENT_WIT)

    def test_component_wit_rejects_wrong_component_world(self) -> None:
        invalid = VALID_COMPONENT_WIT.replace("world root", "world other")
        with self.assertRaisesRegex(builder.BuildError, "root component world"):
            builder.validate_component_wit(invalid)

    def test_component_wit_rejects_missing_context_authority(self) -> None:
        invalid = VALID_COMPONENT_WIT.replace(
            "    import latent:context/context@0.1.0;\n", ""
        )
        with self.assertRaisesRegex(builder.BuildError, "exactly the context and log"):
            builder.validate_component_wit(invalid)

    def test_component_wit_rejects_ambient_authority(self) -> None:
        invalid = VALID_COMPONENT_WIT.replace(
            "    export examples:echo/api@0.1.0;",
            "    import wasi:filesystem/types@0.2.0;\n    export examples:echo/api@0.1.0;",
        )
        with self.assertRaisesRegex(builder.BuildError, "exactly the context and log"):
            builder.validate_component_wit(invalid)

    def test_component_wit_rejects_an_unexpected_export(self) -> None:
        invalid = VALID_COMPONENT_WIT.replace(
            "    export examples:echo/api@0.1.0;",
            "    export examples:echo/api@0.1.0;\n    export examples:other/api@0.1.0;",
        )
        with self.assertRaisesRegex(builder.BuildError, "must export exactly"):
            builder.validate_component_wit(invalid)

    def test_reproducible_environment_replaces_ambient_rust_flags(self) -> None:
        target = Path("/tmp/latent-echo-target")
        original = os.environ.copy()
        try:
            os.environ["RUSTFLAGS"] = "-C target-cpu=native"
            os.environ["CARGO_ENCODED_RUSTFLAGS"] = "ambient"
            os.environ["CARGO_PROFILE_RELEASE_DEBUG"] = "2"
            environment = builder.reproducible_environment(target)
        finally:
            os.environ.clear()
            os.environ.update(original)

        self.assertNotIn("RUSTFLAGS", environment)
        self.assertNotIn("CARGO_PROFILE_RELEASE_DEBUG", environment)
        self.assertEqual(
            environment["CARGO_ENCODED_RUSTFLAGS"],
            f"--remap-path-prefix={builder.ROOT}=/workspace",
        )
        self.assertEqual(environment["CARGO_TARGET_DIR"], str(target))
        self.assertEqual(environment["SOURCE_DATE_EPOCH"], "0")

    def test_generated_metadata_is_stable_and_path_independent(self) -> None:
        baseline = {
            "rust": {"toolchain": "1.97.1"},
            "contracts": {"wasm-tools": "1.254.0"},
        }
        metadata = builder.build_metadata(
            digest="sha256:" + "a" * 64,
            baseline=baseline,
            reproducibility_verified=True,
        )
        first = builder.deterministic_json(metadata)
        second = builder.deterministic_json(metadata)
        self.assertEqual(first, second)
        self.assertNotIn(str(Path.cwd()), first)
        self.assertNotIn("timestamp", first.lower())

    def test_output_bundle_uses_one_computed_digest_everywhere(self) -> None:
        baseline = {
            "rust": {"toolchain": "1.97.1"},
            "contracts": {"wasm-tools": "1.254.0"},
        }
        component = b"phase-0-echo-component"
        expected_digest = builder.sha256_digest(component)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "bundle"
            digest = builder.write_outputs(
                output_directory=output,
                component_bytes=component,
                inferred_wit=VALID_COMPONENT_WIT,
                baseline=baseline,
                reproducibility_verified=True,
            )

            self.assertEqual(digest, expected_digest)
            self.assertEqual((output / builder.COMPONENT_FILE).read_bytes(), component)
            self.assertTrue(
                (output / builder.DIGEST_FILE)
                .read_text(encoding="utf-8")
                .startswith(expected_digest)
            )
            manifest = json.loads(
                (output / builder.MANIFEST_FILE).read_text(encoding="utf-8")
            )
            metadata = json.loads(
                (output / builder.METADATA_FILE).read_text(encoding="utf-8")
            )
            trust = json.loads(
                (output / builder.TRUST_FILE).read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["component"]["digest"], expected_digest)
            self.assertEqual(metadata["contentDigest"], expected_digest)
            self.assertEqual(trust["contentDigest"], expected_digest)
            self.assertTrue(metadata["reproducibility"]["verified"])


if __name__ == "__main__":
    unittest.main()
