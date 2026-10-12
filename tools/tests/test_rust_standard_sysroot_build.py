"""Exact successful emitted graph selection; no source-stage qualification claim."""
import json
from pathlib import Path
import tempfile
import unittest

from tools import rust_standard_sysroot_build as build
from tools import rust_standard_clock_profile as clock
from tools.dev_workflow.common import DevError


class EmittedStdLibraries(unittest.TestCase):
    def graph(self, root):
        rows = []
        for crate in ('std', 'core', 'alloc', 'panic_abort', 'compiler_builtins'):
            path = root / clock.TARGET / 'release/deps' / f'lib{crate}-current.rlib'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(crate.encode())
            rows.append({'reason': 'compiler-artifact', 'package_id': f'captured-{crate}',
                         'target': {'name': crate}, 'filenames': [str(path)]})
        rows.append({'reason': 'build-finished', 'success': True})
        return rows

    def encode(self, rows):
        return b'\n'.join(json.dumps(r).encode() for r in rows)

    def test_only_successful_emitted_graph_is_selected_despite_stale_rlibs_in_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = self.graph(root)
            stale = root / clock.TARGET / 'release/deps/libcore-stale.rlib'
            stale.write_bytes(b'earlier failed build')
            selected = build.emitted_libraries(self.encode(rows), root)
            self.assertEqual(len(selected), 5)
            self.assertNotIn(stale.name, selected)
            self.assertEqual(selected['libstd-current.rlib']['bytes'], b'std')

    def test_failed_missing_or_duplicate_terminal_record_never_installs_a_graph(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); rows = self.graph(root)
            for altered in (rows[:-1], [*rows[:-1], {'reason': 'build-finished', 'success': False}],
                            [*rows, rows[-1]]):
                with self.assertRaises(DevError): build.emitted_libraries(self.encode(altered), root)

    def test_incomplete_std_core_alloc_panic_and_builtins_graph_rejects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); rows = self.graph(root)
            for index in range(5):
                altered = rows[:index] + rows[index + 1:]
                with self.subTest(crate=rows[index]['target']['name']), self.assertRaisesRegex(DevError, 'incomplete-graph'):
                    build.emitted_libraries(self.encode(altered), root)

    def test_artifact_after_successful_terminal_cannot_poison_the_emitted_graph(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); rows = self.graph(root)
            with self.assertRaisesRegex(DevError, 'after-terminal'):
                build.emitted_libraries(self.encode([*rows, rows[0]]), root)

    def test_ambiguous_library_or_crate_does_not_choose_the_first_cached_member(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); rows = self.graph(root)
            for name in ('libstd-current.rlib', 'libstd-other.rlib'):
                other = root / clock.TARGET / 'release/deps' / name
                other.write_bytes(b'std')
                altered = [*rows[:-1], {**rows[0], 'filenames': [str(other)]}, rows[-1]]
                with self.assertRaisesRegex(DevError, 'ambiguous-library'):
                    build.emitted_libraries(self.encode(altered), root)

    def test_outside_traversal_and_relative_artifact_paths_reject(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); rows = self.graph(root)
            for name in ('relative.rlib', str(root.parent / 'libstd.rlib'), str(root / '..' / 'libstd.rlib')):
                altered = [{**rows[0], 'filenames': [name]}, *rows[1:]]
                with self.assertRaisesRegex(DevError, 'outside-target'):
                    build.emitted_libraries(self.encode(altered), root)

    def test_host_native_rlibs_are_not_a_wasm_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); rows = self.graph(root)
            host = root / 'release/deps/libnative.rlib'
            host.parent.mkdir(parents=True); host.write_bytes(b'native')
            rows.insert(0, {'reason': 'compiler-artifact', 'package_id': 'native',
                            'target': {'name': 'native'}, 'filenames': [str(host)]})
            self.assertEqual(len(build.emitted_libraries(self.encode(rows), root)), 5)

    def test_byte_record_and_filename_limits_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); rows = self.graph(root)
            for data in (b'x' * (4 * 1024 * 1024 + 1), b'{}\n' * 8193,
                         self.encode([{**rows[0], 'filenames': rows[0]['filenames'] * 17}, *rows[1:]])):
                with self.assertRaisesRegex(DevError, 'bound'):
                    build.emitted_libraries(data, root)

    def test_unapproved_source_rejects_before_output_and_compiler_invocation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); archive = root / 'source'; archive.write_bytes(b'wrong')
            output = root / 'output'
            with self.assertRaisesRegex(DevError, 'archive-pin'):
                build.build(archive, output, root / 'absent-compiler')
            self.assertFalse(output.exists())


if __name__ == '__main__': unittest.main()
