from __future__ import annotations

import copy
import hashlib
import tempfile
import unittest
from pathlib import Path

from tools.phase0_collector_identity import (
    CollectorIdentityError,
    EXPECTED_RELEASE_BUILD_CONFIGURATION,
    require_native_collector_identity,
    verify_retained_native_collector,
)


class Phase0CollectorIdentityTests(unittest.TestCase):
    def identity(self) -> dict[str, object]:
        return {
            "schema_version": "latent.phase0.native-collector.v1",
            "collector": "phase0-baseline",
            "executable_digest": "sha256:" + "a" * 64,
            "executable_bytes": 123,
            "build_configuration": dict(EXPECTED_RELEASE_BUILD_CONFIGURATION),
        }

    def test_accepts_exact_release_collector_identity(self) -> None:
        self.assertEqual(
            require_native_collector_identity(
                self.identity(), "test collector", "phase0-baseline"
            ),
            self.identity(),
        )

    def test_rejects_build_or_executable_drift(self) -> None:
        for path, value in (
            (("executable_digest",), "sha256:" + "b" * 63),
            (("executable_bytes",), 0),
            (("build_configuration", "debug_info"), 0),
            (("build_configuration", "debug_info"), True),
            (("build_configuration", "incremental"), True),
            (("build_configuration", "path_remap_policy"), "none"),
            (("build_configuration", "linker_build_id"), "none"),
            (("build_configuration", "promoted_local_symbols"), "module-hash"),
        ):
            with self.subTest(path=path):
                identity = copy.deepcopy(self.identity())
                target = identity
                for part in path[:-1]:
                    target = target[part]  # type: ignore[assignment,index]
                target[path[-1]] = value  # type: ignore[index]
                with self.assertRaises(CollectorIdentityError):
                    require_native_collector_identity(
                        identity, "test collector", "phase0-baseline"
                    )

    def test_verifies_retained_executable_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            collector = root / "collector/phase0-baseline"
            collector.parent.mkdir()
            collector.write_bytes(b"native collector bytes")
            identity = self.identity()
            identity["executable_bytes"] = collector.stat().st_size
            identity["executable_digest"] = (
                "sha256:" + hashlib.sha256(collector.read_bytes()).hexdigest()
            )
            verify_retained_native_collector(
                root, identity, "test collector", "phase0-baseline"
            )
            (collector.parent / "decoy").write_bytes(b"another executable")
            with self.assertRaisesRegex(
                CollectorIdentityError, "must contain exactly"
            ):
                verify_retained_native_collector(
                    root, identity, "test collector", "phase0-baseline"
                )
            (collector.parent / "decoy").unlink()
            collector.write_bytes(b"tampered native collector")
            with self.assertRaisesRegex(
                CollectorIdentityError, "retained executable .* does not match"
            ):
                verify_retained_native_collector(
                    root, identity, "test collector", "phase0-baseline"
                )


if __name__ == "__main__":
    unittest.main()
