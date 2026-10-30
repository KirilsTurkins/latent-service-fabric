"""Bounded host-side catalogue generation; no runtime qualification claim."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from tools import rust_thread_host_catalogue as host
from tools import rust_thread_object_graph as graph


def number(value: int) -> bytes:
    result = bytearray()
    while value >= 128:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def section(kind: int, payload: bytes) -> bytes:
    return bytes([kind]) + number(len(payload)) + payload


class HostCatalogueTests(unittest.TestCase):
    def test_reviewed_roots_require_public_lifecycle_and_private_pool_entrypoints(self):
        nodes = ([{'id': index, 'originalSymbol': name}
                  for index, name in enumerate(host.ROOT_EXPORTS)]
                 + [{'id': index + len(host.ROOT_EXPORTS), 'originalSymbol': name}
                    for index, name in enumerate(host.ADDITIONAL_ROOT_SYMBOLS)])
        manifest = {'nodes': nodes, 'roots': [
            {'node': index, 'export': name} for index, name in enumerate(host.ROOT_EXPORTS)] + [
            {'node': index + len(host.ROOT_EXPORTS), 'export': None}
            for index, _ in enumerate(host.ADDITIONAL_ROOT_SYMBOLS)]}
        host.reviewed_roots(manifest)
        for change in ('missing', 'wrong-public', 'wrong-private'):
            with self.subTest(change=change):
                altered = {'nodes': [row.copy() for row in nodes],
                           'roots': [row.copy() for row in manifest['roots']]}
                if change == 'missing':
                    altered['roots'].pop()
                elif change == 'wrong-public':
                    altered['roots'][0]['export'] = 'forged'
                else:
                    altered['nodes'][-1]['originalSymbol'] = 'forged'
                with self.assertRaisesRegex(ValueError, 'rust-host-catalogue-reviewed-roots'):
                    host.reviewed_roots(altered)

    def test_component_section_bound_precedes_next_read_and_allocation(self):
        class CountingReader(graph.Reader):
            reads = 0

            def byte(self):
                CountingReader.reads += 1
                return super().byte()

        component = b'\0asm\x0d\0\x01\0' + b'\0\0' * 257
        with patch.object(graph, 'Reader', CountingReader):
            with self.assertRaisesRegex(ValueError, 'rust-host-normal-component-section-bound'):
                host.normal_component_envelope(b'', component)
        # One section id and one one-byte payload length, at most256sections.
        self.assertEqual(CountingReader.reads, 512)
        module = b'\0asm\x01\0\0\0'
        component = b'\0asm\x0d\0\x01\0' + section(1, module) * 3
        with self.assertRaisesRegex(ValueError, 'rust-host-normal-core-section-bound'):
            host.normal_component_envelope(module + b'\0\0' * 513, component)

    def test_main_bytes_preserved_except_exact_consumed_metadata_and_producer_merge(self):
        module = b'\0asm\x01\0\0\0'
        metadata = b'\x10component-type:xoriginal-metadata'
        producers = b'\x09producersoriginal'
        encoded_producers = b'\x09producersnormal-merge'
        code = section(10, b'\x01\x02\0\x0b')
        original = module + code + section(0, metadata) + section(0, producers)
        main = module + code + section(0, encoded_producers)
        component = (b'\0asm\x0d\0\x01\0' + section(1, main)
                     + section(1, module) + section(1, module))
        product = host.normal_component_envelope(original, component)
        self.assertEqual(product['original-wit-metadata.bin'], metadata)
        self.assertEqual(product['normal-component-shell.bin'],
                         b'\0asm\x0d\0\x01\0\x01\0' + section(1, module) * 2)
        changed = component.replace(code, code[:-1] + b'\x01', 1)
        with self.assertRaisesRegex(ValueError, 'rust-host-normal-main-byte-preservation'):
            host.normal_component_envelope(original, changed)


if __name__ == '__main__':
    unittest.main()
