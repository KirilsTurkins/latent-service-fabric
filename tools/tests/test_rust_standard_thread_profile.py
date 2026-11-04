"""Authenticated owned std/executor source selection, not runtime execution."""
import hashlib
from pathlib import Path
import tempfile
import unittest

from tools import rust_standard_thread_profile as profile
from tools import rust_standard_sysroot_build as build
from tools.dev_workflow.common import DevError

ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = ROOT / 'sdk/rust-standard-runtime/upstream'


class StandardThreadSource(unittest.TestCase):
    def originals(self):
        return {name: (UPSTREAM / name).read_bytes()
                for name in {*profile.ORIGINALS, *profile.tls.ORIGINALS}}

    def runtime(self):
        return {name: (ROOT / name).read_bytes() for name in profile.RECIPE}

    def test_composed_tls_thread_and_packet_selectors_preserve_original_other_targets(self):
        original, runtime = self.originals(), self.runtime()
        changes = profile.complete_overlay(original, runtime)
        self.assertEqual(set(changes), {*profile.ORIGINALS, *profile.SOURCES,
                                       'std/src/sys/thread_local/mod.rs'})
        for name, before in original.items():
            if name not in profile.ORIGINALS and name != 'std/src/sys/thread_local/mod.rs':
                self.assertNotIn(name, changes)
                continue
            after = changes[name]
            if name == 'std/src/sys/thread_local/mod.rs':
                self.assertEqual(after.count(profile.SELECTOR.encode()), 3)
                after = after.replace(profile.SELECTOR.encode(), profile.tls.SELECTOR)
                for old, new in reversed(profile.tls.BRANCHES):
                    self.assertEqual(after.count(new), 1)
                    after = after.replace(new, old)
                self.assertEqual(after, before)
            elif name == profile.CURRENT:
                needle = b'    cfg_select! {\n        target_thread_local => {'
                branch = ('    cfg_select! {\n        all(target_thread_local, not('
                          + profile.SELECTOR + ')) => {').encode()
                self.assertEqual(after.count(branch), 1)
                self.assertEqual(after.replace(branch, needle, 1), before)
            elif name != profile.LIFECYCLE:
                selected = ('cfg_select! {\n    ' + profile.SELECTOR + ' => {\n        '
                            + profile.BRANCHES[name] + '\n    }\n').encode()
                self.assertEqual(after.count(selected), 1)
                self.assertEqual(after.replace(selected, b'cfg_select! {\n'), before)
        for name, source in profile.SOURCES.items():
            self.assertEqual(changes[name], runtime[source])

    def test_changed_upstream_selector_or_packet_is_refused_before_derivation(self):
        for name in profile.ORIGINALS:
            original = self.originals(); original[name] += b'\n'
            with self.subTest(name=name), self.assertRaisesRegex(DevError, 'preimage'):
                profile.complete_overlay(original, self.runtime())

    def test_exact_runtime_source_closure_and_tls_reference_are_required(self):
        original = {name: self.originals()[name] for name in profile.ORIGINALS}
        runtime = {name: self.runtime()[name] for name in profile.SOURCES.values()}
        for kind in ('missing', 'extra', 'empty', 'tls-reference'):
            altered, tls = dict(runtime), (ROOT / 'sdk/rust-standard-runtime/tls.rs').read_bytes()
            if kind == 'missing': altered.pop(next(iter(altered)))
            elif kind == 'extra': altered['foreign.rs'] = b'x'
            elif kind == 'empty': altered[next(iter(altered))] = b''
            else: tls += b'\n'
            with self.subTest(kind=kind), self.assertRaises(DevError):
                profile.overlay(original, altered, tls_reference=tls)

    def test_source_build_keeps_legacy_recipe_and_closes_first_thread_profile_combinations(self):
        import builtins
        from unittest.mock import patch
        original_import = builtins.__import__
        def isolated_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == 'tools.rust_standard_thread_profile' or 'rust_standard_thread_profile' in fromlist:
                raise AssertionError('legacy isolated recipe imported absent thread implementation')
            return original_import(name, globals, locals, fromlist, level)
        with patch('builtins.__import__', side_effect=isolated_import):
            self.assertIs(build.recipe(), build.RECIPE)
        self.assertIs(build.recipe(), build.RECIPE)
        self.assertEqual(set(build.recipe(threads=True)),
                         {*build.RECIPE, 'tools/rust_thread_path_remap.py', *profile.RECIPE})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for flags in ({'threads': True, 'logging': True},
                          {'threads': True, 'entropy': True}, {'threads': 1}):
                with self.subTest(flags=flags), self.assertRaisesRegex(DevError, 'first-profile'):
                    build.build(root / 'absent', root / 'output', root / 'absent-tool', **flags)
                self.assertFalse((root / 'output').exists())

    def test_captured_executor_overlay_preserves_original_crate_selection_and_support_sources(self):
        original = {name: (UPSTREAM / 'futures-executor-0.3.31' / name).read_bytes()
                    for name in profile.EXECUTOR_ORIGINALS}
        runtime = {name: (ROOT / name).read_bytes() for name in profile.EXECUTOR_SOURCES.values()}
        for name, raw in original.items():
            self.assertEqual(hashlib.sha256(raw).hexdigest(), profile.EXECUTOR_ORIGINALS[name])
        selected = profile.executor_overlay(original, runtime, package=profile.EXECUTOR,
                    version=profile.EXECUTOR_VERSION, archive_sha256=profile.EXECUTOR_ARCHIVE_SHA256)
        declaration = ('#[cfg(all(feature = "thread-pool", feature = "std", '
                       + profile.SELECTOR + '))]\nmod lsf_thread_pool;\n').encode()
        attribute = ('#[cfg_attr(' + profile.SELECTOR
                     + ', path = "lsf_thread_pool_impl.rs")]\n').encode()
        lib = selected['src/lib.rs']
        self.assertEqual(lib.count(declaration), 1)
        self.assertEqual(lib.count(attribute), 1)
        self.assertEqual(lib.replace(declaration, b'').replace(attribute, b''), original['src/lib.rs'])
        self.assertEqual(set(selected), {'src/lib.rs', *profile.EXECUTOR_SOURCES})
        for name, source in profile.EXECUTOR_SOURCES.items():
            self.assertEqual(selected[name], runtime[source])
        for name in ('src/thread_pool.rs', 'src/unpark_mutex.rs', 'src/enter.rs'):
            self.assertNotIn(name, selected)

    def test_captured_executor_identity_target_and_original_closure_cannot_drift(self):
        original = {name: (UPSTREAM / 'futures-executor-0.3.31' / name).read_bytes()
                    for name in profile.EXECUTOR_ORIGINALS}
        runtime = {name: (ROOT / name).read_bytes() for name in profile.EXECUTOR_SOURCES.values()}
        valid = {'package': profile.EXECUTOR, 'version': profile.EXECUTOR_VERSION,
                 'archive_sha256': profile.EXECUTOR_ARCHIVE_SHA256}
        for kind in ('package', 'version', 'archive_sha256', 'target', 'rust',
                     'missing-original', 'extra-original', 'changed-original'):
            args, altered = dict(valid), dict(original)
            if kind in {'package', 'version', 'archive_sha256', 'target', 'rust'}: args[kind] = 'foreign'
            elif kind == 'missing-original': altered.pop('src/enter.rs')
            elif kind == 'extra-original': altered['src/foreign.rs'] = b'x'
            else: altered['src/unpark_mutex.rs'] += b'\n'
            with self.subTest(kind=kind), self.assertRaises(DevError):
                profile.executor_overlay(altered, runtime, **args)


if __name__ == '__main__': unittest.main()
