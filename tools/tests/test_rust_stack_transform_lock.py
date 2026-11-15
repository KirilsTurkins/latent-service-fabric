"""Keep the standalone source-transform lock aligned with its shared crate."""
from pathlib import Path
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]


class RustStackTransformLockTests(unittest.TestCase):
    def test_shared_exact_dependencies_are_locked_in_the_standalone_cli(self):
        manifest = tomllib.loads((ROOT / 'crates/latent-component-threading/Cargo.toml').read_text())
        lock = tomllib.loads((ROOT / 'sdk/rust-standard-runtime/stack-transform/Cargo.lock').read_text())
        shared = [row for row in lock['package'] if row['name'] == 'latent-component-threading']
        self.assertEqual(len(shared), 1)
        for section in ('dependencies', 'build-dependencies'):
            for name, specification in manifest.get(section, {}).items():
                version = specification if isinstance(specification, str) else specification.get('version', '')
                if not version.startswith('='):
                    continue
                with self.subTest(section=section, dependency=name):
                    expected = version.removeprefix('=')
                    matches = [row for row in lock['package']
                               if row['name'] == name and row['version'] == expected]
                    self.assertEqual(len(matches), 1, f'{name} {expected} missing from standalone lock')
                    references = shared[0].get('dependencies', [])
                    self.assertTrue(name in references or f'{name} {expected}' in references)


if __name__ == '__main__':
    unittest.main()
