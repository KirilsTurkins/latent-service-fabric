"""Exact scoped clock derivation inputs; no engine or API support inference."""
from pathlib import Path
import unittest
from tools.typescript_guest.clock_engine import derive_clock_source, GENERATED

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).parent/'fixtures/typescript_clock_profile'


def inputs():
    return [(FIXTURE/'original-install.cpp').read_bytes(),
            (ROOT/'sdk/typescript-guest/activation/clock_globals.js').read_bytes(),
            (ROOT/'wit/platform/clock/package.wit').read_bytes(),
            {name:(FIXTURE/name).read_bytes() for name in GENERATED}]


class TypeScriptClockSourceTests(unittest.TestCase):
    def test_actual_clock_ABI_and_original_install_are_exact_preconditions(self):
        source = inputs()
        for index in (0,2):
            changed = list(source)
            changed[index] += b'changed'
            with self.subTest(index=index), self.assertRaisesRegex(ValueError, 'unreviewed-'):
                derive_clock_source(*changed)
        for name in GENERATED:
            changed = list(source)
            changed[3] = dict(source[3], **{name:source[3][name]+b'changed'})
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'unreviewed-generated-clock-ABI'):
                derive_clock_source(*changed)

    def test_clock_module_is_installed_after_original_builtins_before_app_evaluation(self):
        values, receipt = derive_clock_source(*inputs())
        source = values['StarlingMonkey/builtins/install_builtins.cpp']
        self.assertLess(source.rindex(b'#include "builtins.incl"'), source.index(b'install_clock_globals(engine->cx()'))
        self.assertEqual(receipt['clockSource'], 'separately-installed-granted-latent-clock-0.1.0')
        self.assertFalse(receipt['ambientClockPermissionAdded'])

    def test_original_typed_C_clock_signatures_and_metadata_are_retained_byteexact(self):
        values, _ = derive_clock_source(*inputs())
        for name in GENERATED:
            self.assertEqual(values['lsf/'+name], (FIXTURE/name).read_bytes())
        header = values['lsf/clocks.h']
        self.assertIn(b'uint64_t latent_clock_monotonic_now_nanos(void)', header)
        self.assertIn(b'uint64_t latent_clock_wall_now_unix_millis(void)', header)

    def test_source_literal_cannot_escape_the_compiled_clock_module(self):
        source = inputs()
        for invalid in (b'\0', b')LSF_CLOCK_SOURCE"'):
            changed = list(source)
            changed[1] += invalid
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, 'invalid-clock-source-literal'):
                derive_clock_source(*changed)

    def test_phase_lifetime_and_unknown_qualification_are_explicit(self):
        _, receipt = derive_clock_source(*inputs())
        self.assertEqual(receipt['snapshotClockObservation'], 'denied')
        self.assertIn('per-fresh-Store', receipt['performanceOrigin'])
        self.assertFalse(receipt['supportedAsyncProfile'])
        self.assertFalse(receipt['signedLSFComponentQualified'])


if __name__ == '__main__':
    unittest.main()
