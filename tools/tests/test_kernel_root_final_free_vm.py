"""Raw observation/source controls only; no Linux or VM execution here."""
import hashlib
import unittest

from tools import host_stream_kernel_vm_image as image
from tools import host_stream_kernel_root_final_free as source


def serial(marker=image.PHYSICAL_MARKER):
    def snapshot(name, state, fields):
        return (f'LSFVM1 snapshot={name} state={state} error=0'
            + ''.join(f' field{index}={value}' for index, value in enumerate(fields))).encode()
    return b'\r\n'.join((
        b'LSFVM1 boot=constructor-only production-sockets=disabled',
        snapshot('opened', 0, (0, 0, 0, 0, 0, 0, 2, 0, 0, 0)),
        snapshot('ready', 2, (3, 0, 0, 1, 1, 0, 17, 0, 0, 0)),
        snapshot('child-retired-root-held', 4, image.TERMINAL_FIELDS), marker,
        image.ROOT_RELEASE_CHECK)) + b'\r\n'


class KernelRootPhysicalObservation(unittest.TestCase):
    def test_exact_unique_kernel_marker_preserves_the_raw_observation_identity(self):
        for marker in (image.PHYSICAL_MARKER, b'[    2.345678] '+image.PHYSICAL_MARKER):
            raw = serial(marker)
            observed = image.root_physical_serial_observation(raw)
            self.assertTrue(observed['rootFinalFree'])
            self.assertEqual(observed['sha256'], hashlib.sha256(raw).hexdigest())
            self.assertEqual(observed['bytes'], len(raw))
            self.assertEqual(observed['snapshots']['child-retired-root-held']['fields'][6], 2)
            self.assertFalse(observed['physicalReturn']['nativeQuotaRelease'])
            self.assertFalse(observed['physicalReturn']['productionInstallation'])

    def test_missing_duplicate_forged_prefix_early_late_and_bad_child_observations_refuse(self):
        raw = serial()
        for wrong in (raw.replace(image.PHYSICAL_MARKER, b''),
                raw+image.PHYSICAL_MARKER+b'\n', serial(b'private-prefix '+image.PHYSICAL_MARKER),
                serial(b'[1.2.3] '+image.PHYSICAL_MARKER),
                serial(b'[1.2] '+image.PHYSICAL_MARKER),
                serial(b'[           1.234567] '+image.PHYSICAL_MARKER),
                image.PHYSICAL_MARKER+b'\n'+raw.replace(image.PHYSICAL_MARKER, b''),
                raw.replace(image.PHYSICAL_MARKER+b'\r\n', b'')+image.PHYSICAL_MARKER+b'\n',
                raw.replace(b'snapshot=child-retired-root-held state=4',
                    b'snapshot=child-retired-root-held state=2'),
                raw.replace(b'field6=2 field7=0', b'field6=0 field7=0'),
                raw+b'Kernel panic', raw+bytes(image.MAX_SERIAL)):
            with self.subTest(bytes=len(wrong)), self.assertRaises(ValueError):
                image.root_physical_serial_observation(wrong)

    def test_only_original_kernel_return_emits_marker_and_pid1_cannot_self_certify(self):
        kernel = (source.OWNED/'factory-cleanup-root-final-free.c').read_bytes()
        probe = (source.OWNED/'constructor-vm-init.c').read_bytes()
        self.assertEqual(kernel.count(image.PHYSICAL_MARKER), 1)
        self.assertGreater(kernel.index(image.PHYSICAL_MARKER), kernel.index(b'mmdrop(release.mm)'))
        self.assertNotIn(image.PHYSICAL_MARKER, probe)
        self.assertIn(b'finish(1, "actual-child-retirement-root-release-check")', probe)
        self.assertNotIn(b'finish(1, "physical', probe)


if __name__ == '__main__':
    unittest.main()
