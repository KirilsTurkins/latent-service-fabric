"""Combined runtime integration controls; not signed guest qualification."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.java_guest import enum_guard, exception_slots
from tools.tests import test_java_exception_frames as frames
from tools.tests import test_java_exception_slots as slots_tests

HEADER = frames.HEADER
function = slots_tests.function


class CombinedJavaAdapterTests(unittest.TestCase):
    def test_sealed_build_uses_one_slot_adapter_not_two_competing_passes(self):
        # Exercise both the enum-only and date-link routes, not just text shape.
        # The reference lowering must not run on production compiler inputs.
        original = exception_slots.stage
        with patch.object(enum_guard, 'compact_exception_frames',
                          side_effect=AssertionError('second exception lowering')) as old, \
                patch.object(exception_slots, 'stage', wraps=original) as active:
            control = slots_tests.ExceptionSlotsLinkTests(
                'test_both_guarded_link_routes_receive_only_post_adaptation_sealed_bytes')
            control.test_both_guarded_link_routes_receive_only_post_adaptation_sealed_bytes()
            self.assertEqual(active.call_count, 2, 'one pass per independently built route')
            old.assert_not_called()

    def test_both_lowerings_match_original_native_exception_lifetimes(self):
        fixture = frames.ExceptionFrameControls()
        outcomes = []
        for adapter in (None, enum_guard.compact_exception_frames, exception_slots.stage):
            with self.subTest(adapter=adapter), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                fixture.stage(root)
                if adapter:
                    adapter(root)
                    # The production macro is guarded by the actual compile profile.
                    with (root / 'definitions.h').open('a') as stream:
                        stream.write('#define LSF_JAVA_ACTIVATION_PROFILE 1\n')
                result = fixture.compile_control(root)
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                self.assertIn(b'fresh-frame: passed', result.stdout)
                outcomes.append(result.stdout)
        self.assertEqual(outcomes[0], outcomes[1])
        self.assertEqual(outcomes[0], outcomes[2])

    def test_production_live_slot_alias_mutation_cannot_pass_native_control(self):
        fixture = frames.ExceptionFrameControls()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture.stage(root)
            exception_slots.stage(root)
            with (root / 'definitions.h').open('a') as stream:
                stream.write('#define LSF_JAVA_ACTIVATION_PROFILE 1\n')
            path = root / 'c/control.c'
            source = path.read_bytes()
            old = b'LSF_TEAVM_TRY_SLOT(lsf_teavm_jump_slot_1)'
            self.assertIn(old, source)
            path.write_bytes(source.replace(old, b'LSF_TEAVM_TRY_SLOT(lsf_teavm_jump_slot_0)'))
            self.assertNotEqual(fixture.compile_control(root).returncode, 0)

    def test_late_source_entry_is_rejected_before_adapted_bytes_are_published(self):
        # Existing-byte checks alone miss files introduced during planning.
        for relative in ('late.h', 'nested/late.c'):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / 'exceptions.h').write_bytes(HEADER)
                (root / 'method.c').write_bytes(function())
                original = exception_slots.transform
                def add_file(raw):
                    value = original(raw)
                    path = root / relative
                    path.parent.mkdir(exist_ok=True)
                    path.write_bytes(b'/* late compiler input */\n')
                    return value
                with patch.object(exception_slots, 'transform', side_effect=add_file), \
                        self.assertRaisesRegex(ValueError, 'source-inventory-drift'):
                    exception_slots.stage(root)
                self.assertEqual((root / 'exceptions.h').read_bytes(), HEADER)
                self.assertEqual((root / 'method.c').read_bytes(), function())


if __name__ == '__main__':
    unittest.main()
