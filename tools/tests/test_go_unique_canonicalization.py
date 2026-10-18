"""Exact pinned standard-library cache adaptation; no Go code executes here."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.go_guest import activation, runtime
from tools.rust_capsule_project import ROOT


class GoUniqueCanonicalizationTests(unittest.TestCase):
    def stage(self, root):
        source = (ROOT / 'tools/tests/fixtures/go-unique/canonmap.go').read_bytes()
        path = root / 'src/unique/canonmap.go'
        path.parent.mkdir(parents=True)
        path.write_bytes(source)
        return path, source.decode()

    def test_only_internal_cleanup_and_its_unused_bindings_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, original = self.stage(root)
            adapted = activation.canonical_map_source(root)
            self.assertEqual(path.read_text(), original)
            self.assertNotIn('runtime.AddCleanup(', adapted)
            self.assertIn('_ "runtime"', adapted)
            self.assertIn('newEntry, canon, _ := newEntryNode(key, hash)', adapted)
            # Reconstruct the full authenticated original, including all weak
            # pointer, canonical equality, locking and prune implementations.
            restored = adapted.replace('\t_ "runtime"\n', '\t"runtime"\n', 1)
            restored = restored.replace('newEntry, canon, _ :=', 'newEntry, canon, wp :=', 1)
            restored = restored.replace('\treturn canon\n}', activation.CANONMAP_CLEANUP + '\treturn canon\n}', 1)
            self.assertEqual(restored, original)
            for behavior in ('wp := weak.Make(k)', 's := e.key.Value()', 's != nil && *s == key',
                             'oldEntry = oldEntry.prune()', 'defer i.mu.Unlock()', 'return canon'):
                self.assertIn(behavior, adapted)

    def test_full_source_drift_including_weak_lookup_and_callback_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, original = self.stage(root)
            for before, after in [('m.cleanup(hash, wp)', 'm.cleanup(0, wp)'),
                                  ('s != nil && *s == key', 's != nil'),
                                  ('wp := weak.Make(k)', 'wp := weak.Make(new(T))'),
                                  ('Copyright 2025', 'Copyright 2026')]:
                with self.subTest(change=before):
                    self.assertIn(before, original)
                    path.write_text(original.replace(before, after, 1))
                    with self.assertRaisesRegex(ValueError, 'source-drift'):
                        activation.canonical_map_source(root)
            path.unlink()
            with self.assertRaises((OSError, ValueError)):
                activation.canonical_map_source(root)

    def test_activation_installs_cache_derivation_and_still_rejects_application_cleanups(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _path, _original = self.stage(root)
            sources = {'runtime/proc.go': '\n'.join([
                '\tmp := acquirem() // disable preemption because we hold M and P in local vars.',
                '\tnewg.parentGoid = callergp.goid', 'func gdestroy(gp *g) {',
                'func ready(gp *g, traceskip int, next bool) {',
                'func execute(gp *g, inheritTime bool) {',
                '\tcasgstatus(gp, _Grunning, _Gwaiting)\n\tif trace.ok() {',
                '\t\tif !ok {\n\t\t\ttrace := traceAcquire()']),
                'runtime/os_wasip1.go': ''}
            checked = {'runtime/runtime2.go': '\tvalgrindStackID uintptr\n}',
                'runtime/time.go': 'func timeSleep(ns int64) {\nfunc newTimer(when, period int64, f func(arg any, seq uintptr, delay int64), arg any, c *hchan) *timeTimer {',
                'runtime/mfinal.go': 'func SetFinalizer(obj any, finalizer any) {',
                'runtime/mcleanup.go': 'func AddCleanup[T, S any](ptr *T, cleanup func(S), arg S) Cleanup {\nORIGINAL_APPLICATION_CLEANUP_BODY\n}'}
            real_check = runtime.checked_sources
            def selected(goroot, preimages):
                return checked if preimages is activation.PREIMAGES else real_check(goroot, preimages)
            with patch.object(activation, 'checked_sources', side_effect=selected):
                activation.runtime_sources(root, sources, ROOT / 'sdk/go-guest')
            self.assertEqual(sources['unique/canonmap.go'], activation.canonical_map_source(root))
            cleanup = sources['runtime/mcleanup.go']
            self.assertIn('Cleanup {\n\tlsfFail("LSF Go cleanup callbacks are not qualified")', cleanup)
            self.assertIn('ORIGINAL_APPLICATION_CLEANUP_BODY', cleanup)
            self.assertNotIn('unique', cleanup)
            self.assertIn('default: lsfFail("LSF Go application finalizer callbacks are not qualified")', sources['runtime/mfinal.go'])


if __name__ == '__main__':
    unittest.main()
