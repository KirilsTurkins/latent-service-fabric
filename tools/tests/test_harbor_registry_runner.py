"""Closed service graph, filesystem ownership and immutable cleanup identities."""
from __future__ import annotations

import copy
import json
import socket
import struct
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.harbor_registry import config, owner
from tools.harbor_registry.dns import Fixture, response
from tools.run_harbor_registry_tests import source_receipt

TOKEN = 'a' * 32
PROJECT = 'lsf-harbor-' + TOKEN


def services():
    result = {'log': {}}
    for name, image in config.IMAGES.items():
        if name == 'prepare':
            continue
        result[name] = {'image': image.split('@')[0] + ':v2.15.2',
                        'container_name': name, 'depends_on': ['log'],
                        'ports': ['0.0.0.0:443:8443'], 'restart': 'always',
                        'env_file': ['./common/config/' + name + '/env'],
                        'volumes': ['./common/config/' + name + ':/config:z']}
    result['postgresql']['volumes'].append('/fixture-root/data/database:/var/lib/postgresql/data:z')
    result['redis']['volumes'].append('/fixture-root/data/redis:/var/lib/redis:z')
    result['jobservice']['depends_on'].append('core')
    return {'services': result}


class HarborRunnerTests(unittest.TestCase):
    def test_source_receipt_does_not_claim_untracked_or_supplied_code_as_verified(self):
        clean = {'commit': 'a' * 40, 'trackedClean': True, 'untrackedFiles': False}
        self.assertTrue(source_receipt(clean, clean, None)['sourceTreeClean'])
        changed = dict(clean, commit='b' * 40)
        self.assertFalse(source_receipt(clean, changed, None)['trackedTreeClean'])
        untracked = dict(clean, untrackedFiles=True)
        self.assertFalse(source_receipt(untracked, untracked, None)['sourceTreeClean'])
        dirty = dict(clean, trackedClean=False)
        self.assertFalse(source_receipt(dirty, dirty, None)['sourceTreeClean'])
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / 'test-binary'
            binary.write_bytes(b'not a source correspondence claim')
            receipt = source_receipt(clean, clean, binary)
            self.assertIn('not established', receipt['testBinarySource'])
            self.assertEqual(len(receipt['testBinarySha256']), 64)

    def test_dns_fixture_is_name_bound_and_retires_its_socket_and_thread(self):
        query = struct.pack('!6H', 41, 0x100, 1, 0, 0, 0) + b'\x06harbor\x04test\0' + struct.pack('!HH', 1, 1)
        expected = response(query)
        self.assertEqual(expected[-4:], socket.inet_aton('127.0.0.1'))
        fixture = Fixture()
        try:
            host, port = fixture.address.rsplit(':', 1)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                client.settimeout(2)
                client.sendto(query, (host, int(port)))
                self.assertEqual(client.recv(512), expected)
            self.assertEqual(fixture.count, 1)
        finally:
            fixture.close()
        self.assertFalse(fixture.worker.is_alive())

    def test_dns_fixture_rejects_unknown_names_compression_counts_and_oversize(self):
        query = struct.pack('!6H', 41, 0x100, 1, 0, 0, 0) + b'\x06harbor\x04test\0' + struct.pack('!HH', 1, 1)
        for packet in [b'', b'x' * 513, query.replace(b'harbor', b'secret'), query[:12] + b'\xc0\x0c\0\1\0\1',
                       query[:4] + b'\0\2' + query[6:], query[:-4] + struct.pack('!HH', 16, 1)]:
            with self.subTest(packet=packet), self.assertRaises(ValueError):
                response(packet)

    def test_compose_is_scoped_pinned_finite_and_loopback_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = config.bounded_compose(services(), root, PROJECT, TOKEN, 45678)
            self.assertEqual(len(result['services']), 8)
            self.assertTrue(result['networks']['harbor']['internal'])
            self.assertFalse(result['networks']['edge']['internal'])
            self.assertEqual(result['services']['proxy']['networks'], ['harbor', 'edge'])
            for name, service in result['services'].items():
                self.assertEqual(service['image'], config.IMAGES[name])
                self.assertEqual(service['restart'], 'no')
                self.assertEqual(service['pids_limit'], 256)
                self.assertEqual(service['cap_drop'], ['ALL'])
                self.assertEqual(service['security_opt'], ['no-new-privileges:true'])
                self.assertNotIn('container_name', service)
                self.assertEqual(service['labels'][config.LABEL], TOKEN)
                if name != 'proxy':
                    self.assertNotIn('ports', service)
                for mount in service['volumes']:
                    if mount['type'] == 'bind':
                        self.assertTrue(Path(mount['source']).is_relative_to(root.resolve()))
            self.assertEqual(result['services']['proxy']['ports'][0]['host_ip'], '127.0.0.1')
            self.assertEqual(result['services']['jobservice']['depends_on'], {'core': {'condition': 'service_healthy'}})
            self.assertEqual(set(result['volumes']), {'database', 'redis'})

    def test_compose_rejects_unexpected_images_mounts_privilege_and_service_graph(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = services()
            for field, value in [('image', 'unreviewed:latest'), ('privileged', True),
                                 ('cap_add', ['SYS_ADMIN']), ('pid', 'host'),
                                 ('volumes', ['/etc:/host']), ('env_file', ['./../../unowned'])]:
                with self.subTest(field=field):
                    malformed = copy.deepcopy(baseline)
                    malformed['services']['core'][field] = value
                    with self.assertRaises(RuntimeError):
                        config.bounded_compose(malformed, root, PROJECT, TOKEN, 45678)
            baseline['services']['unexpected'] = {}
            with self.assertRaises(RuntimeError):
                config.bounded_compose(baseline, root, PROJECT, TOKEN, 45678)

    def test_cleanup_uses_verified_immutable_container_and_network_ids(self):
        controlled = owner.Owner(Path('.'), TOKEN)
        container, network = 'b' * 64, 'c' * 64
        volume = PROJECT + '_database'
        replies = [container, json.dumps({'id': container, 'labels': {config.LABEL: TOKEN}}), '',
                   volume, json.dumps({'id': volume, 'labels': {config.LABEL: TOKEN}}), '',
                   network, json.dumps({'id': network, 'labels': {config.LABEL: TOKEN}}), '']
        with patch.object(owner, 'command', side_effect=replies) as execute:
            controlled.close()
        removed = [call.args[0] for call in execute.call_args_list if 'rm' in call.args[0]]
        self.assertEqual(removed, [['docker', 'container', 'rm', '--force', container],
                                   ['docker', 'volume', 'rm', volume], ['docker', 'network', 'rm', network]])

    def test_cleanup_rejects_foreign_or_malformed_ownership_before_removal(self):
        controlled = owner.Owner(Path('.'), TOKEN)
        for value in [{'id': 'b' * 64, 'labels': {config.LABEL: 'other'}},
                      {'id': 'untrusted-name', 'labels': {config.LABEL: TOKEN}},
                      {'id': 'b' * 64, 'labels': None}]:
            with self.subTest(value=value), patch.object(owner, 'command', side_effect=['b' * 64, json.dumps(value)]) as execute:
                with self.assertRaises(RuntimeError):
                    controlled.close()
                self.assertFalse(any('rm' in call.args[0] for call in execute.call_args_list))

    def test_installer_cache_requires_exact_reviewed_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            (cache / 'harbor-online-installer-v2.15.2.tgz').write_bytes(b'untrusted')
            with self.assertRaises(RuntimeError):
                config.installer_template(cache)


if __name__ == '__main__':
    unittest.main()
