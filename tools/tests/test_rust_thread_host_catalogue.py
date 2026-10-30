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
    def test_retained_linux_normal_envelope_matches_exact_hosted_receipt(self):
        import hashlib
        import json
        from pathlib import Path

        base = (Path(__file__).resolve().parents[2] /
                'crates/latent-component-threading/src/rust_catalogue')
        origin = json.loads((base / 'origin.json').read_text(encoding='utf-8'))
        envelope = origin['normalComponentEnvelope']
        component = (base / 'catalogue-normal-component.wasm').read_bytes()
        shell = (base / 'normal-component-shell.bin').read_bytes()
        records = (base.parent / 'rust_catalogue.rs').read_text(encoding='utf-8')
        self.assertEqual(origin['nodeCount'], 1225)
        self.assertIn('current2id3ID0', records)
        self.assertIn('current2id4ID32', records)
        self.assertNotIn('current2id2ID"', records)
        self.assertEqual(envelope['toolSha256'],
                         '3b91b4a168490b9290dd742d1ed4708c588083c81181c651376457db926599dd')
        self.assertEqual(envelope['candidateSource'], {
            'compilerRun': 41122296703,
            'compilerHead': 'eefea340b053d0f95185b6527e6caae5bf8bf457',
            'compilerArtifact': 13009371378,
            'platform': 'windows-x86_64-local-envelope-candidate',
            'toolReleaseAsset': 'installed-wasm-tools-1.254.0.exe',
            'toolSha256': '3b91b4a168490b9290dd742d1ed4708c588083c81181c651376457db926599dd',
            'hostedConfirmation': False,
        })
        self.assertEqual(envelope['previousHostedSource'], {
            'run': 41113065282,
            'job': 124260142818,
            'head': '9d9b4001bdefa57b6938c613d0fea13f8e638f83',
            'artifact': 13004447135,
            'artifactZipSha256': 'b7df73bbe827a016e45b1681db7304054a6d941c7d1844ebde87063417a58c37',
            'platform': 'ubuntu-24.04-x86_64-container',
            'componentDigest': 'sha256:1f49c19d412b36f9a28c6e867298f5f149df40452a2b179fad7eee46578f3a8f',
            'originalCoreDigest': 'sha256:ae5b68cec5fa2d68cdd65eb669844e0d2dd75d8a3fc7563d8fc0a272866b9c7b',
            'sourceControlsPassed': 76,
            'nativeControlsPassed': 29,
            'hostedConfirmation': True,
        })
        self.assertEqual(envelope['componentBytes'], len(component))
        self.assertEqual(envelope['componentDigest'],
                         'sha256:' + hashlib.sha256(component).hexdigest())
        retained_shell = next(row for row in envelope['files']
                              if row['name'] == 'normal-component-shell.bin')
        self.assertEqual(retained_shell, {
            'name': 'normal-component-shell.bin',
            'bytes': len(shell),
            'digest': 'sha256:' + hashlib.sha256(shell).hexdigest(),
        })

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
