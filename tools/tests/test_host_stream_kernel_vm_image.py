"""Image format/boundary controls; no kernel compilation or VM execution."""
from pathlib import Path
import struct
import unittest

from tools import host_stream_kernel_vm_image as owner


def static_image():
    raw = bytearray(512)
    raw[:7] = b'\x7fELF\x02\x01\x01'
    struct.pack_into('<HHIQQ', raw, 16, 2, 62, 1, 0x400100, 64)
    struct.pack_into('<HHH', raw, 52, 64, 56, 1)
    struct.pack_into('<IIQQQQQQ', raw, 64, 1, 5, 0, 0x400000, 0,
                     len(raw), len(raw), 4096)
    return bytes(raw)


class KernelConstructorVmImages(unittest.TestCase):
    def test_success_label_cannot_replace_complete_physical_counter_observations(self):
        def snapshot(name, state, fields):
            return (f'LSFVM1 snapshot={name} state={state} error=0'
                    + ''.join(f' field{index}={value}' for index, value in enumerate(fields)))
        rows = ['LSFVM1 boot=constructor-only production-sockets=disabled',
                snapshot('opened', 0, [0]*6+[2, 0, 0, 0]),
                snapshot('ready', 2, [3, 0, 1, 1, 1, 0, 10, 0, 0, 0]),
                snapshot('child-retired-root-held', 4, owner.TERMINAL_FIELDS),
                'LSFVM1 result=PASS stage=actual-child-retirement-root-final-free-unqualified']
        raw = ('\r\n'.join(rows)+'\r\n').encode()
        self.assertFalse(owner.serial_observation(raw)['rootFinalFree'])
        for index in range(10):
            changed = list(owner.TERMINAL_FIELDS)
            changed[index] += 1
            wrong = raw.replace(rows[3].encode(), snapshot('child-retired-root-held', 4, changed).encode())
            with self.subTest(field=index), self.assertRaises(ValueError):
                owner.serial_observation(wrong)
        for wrong in (rows[-1].encode(), raw+rows[-1].encode(),
                      raw.replace(rows[2].encode()+b'\r\n', b''),
                      raw.replace(b'snapshot=ready state=2', b'snapshot=ready state=1'),
                      raw+b'Kernel panic', raw+bytes(owner.MAX_SERIAL)):
            with self.subTest(size=len(wrong)), self.assertRaises(ValueError):
                owner.serial_observation(wrong)

    def test_static_init_rejects_dynamic_writable_code_and_declared_unbacked_ranges(self):
        original = static_image()
        self.assertTrue(owner.init_elf(original)['staticX86_64'])
        for label, offset, encoding, value in (
                ('interpreter', 64, '<I', 3), ('dynamic', 64, '<I', 2),
                ('write-execute', 68, '<I', 7), ('file-range', 96, '<Q', 513),
                ('bss', 104, '<Q', owner.MAX_INIT_LOAD + 1),
                ('no-entry', 24, '<Q', 0x900000), ('alignment', 112, '<Q', 3),
                ('architecture', 18, '<H', 183), ('headers', 56, '<H', 65)):
            changed = bytearray(original)
            struct.pack_into(encoding, changed, offset, value)
            with self.subTest(label=label), self.assertRaises(ValueError):
                owner.init_elf(bytes(changed))
        with self.assertRaisesRegex(ValueError, 'init-byte-bound'):
            owner.init_elf(original + bytes(owner.MAX_INIT))
        # A second independently described segment cannot overlap the first.
        changed = bytearray(original)
        struct.pack_into('<H', changed, 56, 2)
        struct.pack_into('<IIQQQQQQ', changed, 120, 1, 4, 256, 0x400100, 0, 128, 128, 1)
        with self.assertRaisesRegex(ValueError, 'overlapping-loads'):
            owner.init_elf(bytes(changed))

    def test_bzimage_checks_linux_protocol_bits_before_recording_an_image(self):
        raw = bytearray(4096)
        raw[0x1fe:0x200] = b'\x55\xaa'
        raw[0x202:0x206] = b'HdrS'
        struct.pack_into('<H', raw, 0x206, 0x20f)
        struct.pack_into('<H', raw, 0x236, 1)
        raw[0x211] = 1
        self.assertEqual(owner.kernel_image(bytes(raw))['bootProtocol'], 0x20f)
        for offset in (0x1fe, 0x202, 0x236, 0x211):
            changed = bytearray(raw)
            changed[offset] = 0
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                owner.kernel_image(bytes(changed))

    def test_real_boot_configuration_is_required_without_rewriting_missing_options(self):
        from tools.qualify_host_stream_kernel_objects import configuration
        rows = [f'{name}=y' for name in owner.REQUIRED_CONFIG]
        rows += ['CONFIG_INITRAMFS_SOURCE=""']
        raw = ('\n'.join(rows) + '\n').encode()
        self.assertFalse(owner.check_boot_configuration(raw, configuration)['configurationMutated'])
        for name in owner.REQUIRED_CONFIG:
            changed = raw.replace(f'{name}=y'.encode(), f'# {name} is not set'.encode())
            with self.subTest(option=name), self.assertRaises(ValueError):
                owner.check_boot_configuration(changed, configuration)
        with self.assertRaisesRegex(ValueError, 'external-initramfs-required'):
            owner.check_boot_configuration(raw.replace(b'SOURCE=""', b'SOURCE="/unsafe"'), configuration)


if __name__ == '__main__':
    unittest.main()
