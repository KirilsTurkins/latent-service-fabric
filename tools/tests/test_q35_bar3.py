"""Refusal controls for BAR3 source capture, markers and trace observations."""
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import q35_bar3_trace as bar_trace
from tools import host_stream_kernel_native_vm as owner
from tools import q35_intx_trace as intx_trace
from tools.tests import test_kernel_native_constructor_vm as prior


ROOT = Path(__file__).resolve().parents[2]


class Q35Bar3Trace(unittest.TestCase):
    @staticmethod
    def trace():
        base = prior.example()
        suffix = b'\n'.join(prior.cfg(b'read', off, value)
            for off, value in reversed(intx_trace.PREFIX)) + b'\n'
        assert base.endswith(suffix)
        added = b'\n'.join((prior.cfg(b'read', 0x1c, 0), prior.cfg(b'write', 0x1c, 0xffffffff),
            bar_trace.GUARDS[0], prior.cfg(b'read', 0x1c, 0), prior.cfg(b'write', 0x1c, 0),
            bar_trace.GUARDS[1], prior.cfg(b'read', 0x1c, 0))) + b'\n'
        return base[:-len(suffix)] + added + suffix

    def test_two_exact_guarded_noop_writes_and_no_general_sizing(self):
        raw = self.trace()
        result = bar_trace.inspect(raw, 0x103, 1, 0xff)
        self.assertEqual(result['guardedWrites'], 2)
        self.assertFalse(result['fullBarSizing'])
        with self.assertRaises(ValueError):
            intx_trace.inspect(raw, 0x103, 1, 0xff)

    def test_write_restore_guard_and_mapping_failures_are_rejected(self):
        raw = self.trace()
        write = prior.cfg(b'write', 0x1c, 0xffffffff)
        cases = (
            raw.replace(write, prior.cfg(b'write', 0x1c, 0xfffffffe), 1),
            raw.replace(prior.cfg(b'write', 0x1c, 0), prior.cfg(b'write', 0x1c, 1), 1),
            raw.replace(bar_trace.GUARDS[0], b'', 1),
            raw.replace(bar_trace.GUARDS[1], bar_trace.GUARDS[0], 1),
            raw.replace(write+b'\n', write+b'\npci_update_mappings_add virtio-net-pci 00:03.0 1,0x0+0x1000\n', 1),
            raw.replace(write+b'\n', write+b'\nx86_gsi_interrupt GSI interrupt #20 level:1\n', 1),
            raw.replace(prior.cfg(b'read', 0x1c, 0), prior.cfg(b'read', 0x1c, 1), 1),
        )
        for candidate in cases:
            with self.subTest(candidate=candidate[:50]), self.assertRaises(ValueError):
                bar_trace.inspect(candidate, 0x103, 1, 0xff)


class Q35Bar3Observation(unittest.TestCase):
    def test_source_capture_and_unbound_projection_refuse(self):
        captured = owner.node_bar3_capture(ROOT)
        self.assertEqual(set(captured), {owner.BAR3_PROJECTOR, owner.BAR3_FACTORY,
            owner.BAR3_PROBE, owner.BAR3_QEMU})
        with self.assertRaises(ValueError):
            owner.node_bar3_compose({}, captured)
        with self.assertRaises(ValueError):
            owner.node_bar3_compose({}, {})

    def test_guest_marker_is_exact_and_reports_the_partial_probe(self):
        raw = prior.Q35NodePciIntxControls.serial().replace(b'barProbe=0', b'barProbe=1')
        ack = next(row for row in raw.splitlines() if b'LSFNODESETUP1' in row)
        marker = (b'[    2.345681] LSFQ35PCIBAR3 saved=00000000 '
            b'restored=1 fullSizing=0 registered=0')
        raw = raw.replace(ack, marker+b'\n'+ack, 1)
        observation = owner.node_bar3_serial(raw)
        self.assertTrue(observation['pciEarlyFixup']['barProbeReached'])
        self.assertTrue(observation['pciBar3']['savedWordRestored'])
        self.assertFalse(observation['pciBar3']['fullBarSizing'])
        for bad in (raw.replace(b'saved=00000000', b'saved=00000001'),
                    raw.replace(b'restored=1 fullSizing=0', b'restored=0 fullSizing=0'),
                    raw.replace(b'fullSizing=0', b'fullSizing=1'),
                    raw.replace(marker+b'\n', b''), raw+marker+b'\n'):
            with self.subTest(bad=bad[:50]), self.assertRaises(ValueError):
                owner.node_bar3_serial(bad)


class Q35RejectedNativeEvidence(unittest.TestCase):
    def test_oversized_candidate_is_retained_but_never_admitted(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            child = root/'candidate'
            child.write_bytes(b'X'*(owner.MAX_NATIVE_INIT+1))
            receipt = {}
            prior.programme.retain_native_candidate(child, root, receipt)
            self.assertTrue(receipt['nativeCandidate']['regularFile'])
            self.assertEqual(receipt['nativeCandidate']['bytes'], owner.MAX_NATIVE_INIT+1)
            rejected = receipt['rejectedNativeProduct']
            self.assertFalse(rejected['admitted'])
            self.assertFalse(rejected['executed'])
            self.assertFalse(rejected['includedInVm'])
            self.assertEqual((root/rejected['path']).read_bytes(), child.read_bytes())
            with self.assertRaises(ValueError):
                prior.programme.read_file(child, owner.MAX_NATIVE_INIT)

    def test_nonregular_and_over_forensic_limit_are_not_copied(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            candidate = root/'candidate'
            candidate.write_bytes(b'')
            with candidate.open('r+b') as output:
                output.truncate(prior.programme.MAX_REJECTED_NATIVE+1)
            receipt = {}
            prior.programme.retain_native_candidate(candidate, root, receipt)
            self.assertNotIn('rejectedNativeProduct', receipt)
            self.assertFalse((root/'native-init.rejected.elf').exists())
            link = SimpleNamespace(st_mode=stat.S_IFLNK, st_size=10)
            with patch.object(Path, 'lstat', return_value=link), \
                 patch.object(prior.programme, 'read_file') as read:
                receipt = {}
                prior.programme.retain_native_candidate(candidate, root, receipt)
                read.assert_not_called()
                self.assertFalse(receipt['nativeCandidate']['regularFile'])
                self.assertTrue(receipt['nativeCandidate']['symlink'])


if __name__ == '__main__':
    unittest.main()
