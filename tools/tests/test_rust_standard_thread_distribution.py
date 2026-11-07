"""Owned-thread compiler-distribution binding; no guest execution is claimed."""
import shutil
import tempfile
import unittest
from pathlib import Path

from tools import rust_owned_thread_component as component
from tools import rust_standard_logging_inputs as standard
from tools import rust_standard_sysroot_build as std
from tools.build_observation import file_identity
from tools.captured_compiler_isolation import distribution
from tools.dev_workflow.common import DevError, encode
from tools.rust_capsule_project import digest, inventory
from tools.rust_thread_path_remap import standard_flags
from tools.tests import test_rust_standard_logging as logging_controls


def thread_prepared(root):
    """Small real file trees with a receipt shaped like the source build."""
    fixture = logging_controls.StandardLogging()
    storage = root / 'prepared-build'
    storage.mkdir()
    prepared, original_compiler, value = fixture.prepared(storage)
    toolchain = root / 'toolchain'
    compiler = toolchain / 'bin/rustc'
    compiler.parent.mkdir(parents=True)
    compiler.write_bytes(original_compiler.read_bytes())
    (compiler.parent / 'cargo').write_bytes(b'cargo')
    target = toolchain / 'lib/rustlib/wasm32-unknown-unknown/lib'
    target.mkdir(parents=True)
    (target / 'libcore.rlib').write_bytes(b'compiler target input')
    (target.parent.parent / 'multirust-config.toml').write_bytes(b'install metadata')
    value.update(profile=std.THREAD_PROFILE, standardStdio='explicit-unsupported-v1',
        standardThreads='lsf-rust-std-owned-thread-runtime-v1',
        standardThreadSourceSelected=True, standardThreadRuntimeQualified=False,
        recipeDigest=digest(inventory({name: (standard.ROOT / name).read_bytes()
            for name in std.recipe(threads=True)})))
    value['tools']['rustc'] = file_identity(compiler, 'rustc')
    value['rustEncodedFlags'], value['threadSourcePathRemap'] = standard_flags(root, std.FLAGS)
    value['compilerDistributionDigest'] = digest(encode(distribution(toolchain)))
    fixture.publish(prepared, value)
    return prepared, compiler, value, fixture, toolchain


class StandardThreadDistribution(unittest.TestCase):
    def test_changed_compiler_companions_or_target_are_refused_with_identical_rustc(self):
        for relative in ('bin/cargo', 'lib/rustlib/wasm32-unknown-unknown/lib/libcore.rlib'):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as temporary:
                prepared, compiler, _, _, toolchain = thread_prepared(Path(temporary))
                selected = standard.Prepared(prepared, compiler, standard.THREAD)
                original_rustc = compiler.read_bytes()
                (toolchain / relative).write_bytes(b'changed')
                self.assertEqual(compiler.read_bytes(), original_rustc)
                with self.assertRaisesRegex(DevError, 'rust-standard-thread-compiler-distribution-drift'):
                    selected.check()
                with self.assertRaisesRegex(DevError, 'rust-standard-thread-compiler-distribution-drift'):
                    standard.Prepared(prepared, compiler, standard.THREAD)

    def test_absent_or_malformed_distribution_identity_is_refused(self):
        for invalid in (None, '', 'sha256:short', 'sha256:' + 'A' * 64, 7):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as temporary:
                prepared, compiler, value, fixture, _ = thread_prepared(Path(temporary))
                if invalid is None:
                    value.pop('compilerDistributionDigest')
                else:
                    value['compilerDistributionDigest'] = invalid
                fixture.publish(prepared, value)
                with self.assertRaisesRegex(DevError, 'rust-standard-thread-compiler-distribution-drift'):
                    standard.Prepared(prepared, compiler, standard.THREAD)

    def test_identical_tree_at_another_root_matches_but_metadata_or_inventory_drift_refuses(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prepared, _, _, _, toolchain = thread_prepared(root)
            copied = root / 'separate-installation'
            shutil.copytree(toolchain, copied)
            compiler = copied / 'bin/rustc'
            selected = standard.Prepared(prepared, compiler, standard.THREAD)
            selected.check()
            metadata = copied / 'lib/rustlib/multirust-config.toml'
            metadata.write_bytes(b'different installation metadata')
            with self.assertRaisesRegex(DevError, 'rust-standard-thread-compiler-distribution-drift'):
                selected.check()
            metadata.write_bytes(b'install metadata')
            selected.check()
            (copied / 'bin/new-companion').write_bytes(b'extra')
            with self.assertRaisesRegex(DevError, 'rust-standard-thread-compiler-distribution-drift'):
                selected.check()
    def test_matching_distribution_still_refuses_the_unqualified_component(self):
        with tempfile.TemporaryDirectory() as temporary:
            prepared, compiler, _, _, _ = thread_prepared(Path(temporary))
            selected = standard.Prepared(prepared, compiler, standard.THREAD)
            selected.check()
            with self.assertRaisesRegex(ValueError, 'private-executor-and-canonical-graph-unqualified'):
                component.select(selected, compiler)


if __name__ == '__main__':
    unittest.main()