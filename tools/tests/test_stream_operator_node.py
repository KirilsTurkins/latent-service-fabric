"""Fixed-origin archive and actual-node consumer controls; no node is executed."""
from pathlib import Path
import json
import stat
import subprocess
from types import SimpleNamespace
import unittest

from tools import stream_operator_frontend_products as products
from tools import qualify_stream_operator_node as programme
from tools.dev_workflow.common import DevError, encode
from tools.phase2_operator_process import WorkflowError

FIXTURE = Path(__file__).parent / 'fixtures/stream-operator-frontend-380-build.json'


class ArchiveMetadata:
    """Explicit metadata double carrying the authentic retained build receipt."""
    def __init__(self):
        self.raw = FIXTURE.read_bytes()
        self.record = products.manifest(self.raw)
        rows = self.record['files'] | {'build.json': {'size': len(self.raw)}}
        self.entries = {name: SimpleNamespace(file_size=row['size'], compress_size=row['size'],
            external_attr=stat.S_IFREG << 16, flag_bits=0, is_dir=lambda: False)
            for name, row in rows.items()}

    def getinfo(self, name):
        return self.entries[name]

    def namelist(self):
        return list(self.entries)

    def read(self, info):
        assert info is self.entries['build.json']
        return self.raw


class StreamOperatorNode(unittest.TestCase):
    def test_authentic_frontend_receipt_and_fixed_origin_do_not_relabel_process_double_as_node(self):
        record = products.manifest(FIXTURE.read_bytes())
        self.assertEqual(record['sourceCommit'], products.SOURCE)
        self.assertFalse(record['streamOperatorSmoke']['realLatentd'])
        reader = products.FrozenOperatorFrontend()
        reader.branch = 'development'
        with self.assertRaisesRegex(WorkflowError, 'fixed-completed-origin'):
            reader._pins()
        with self.assertRaisesRegex(WorkflowError, 'exact-receipt-preimage'):
            products.manifest(FIXTURE.read_bytes() + b' ')
        for raw in (FIXTURE.read_bytes(), bytes(products.ARTIFACT['size_in_bytes'])):
            with self.assertRaisesRegex(WorkflowError, 'exact-whole-archive-preimage'):
                products.sealed_archive(raw)
        class BoundedRanges:
            """Explicit range double enforces the unchanged per-request bound."""
            def __init__(self, missing_tail):
                self.counts, self.position, self.missing_tail = [], None, missing_tail
            def seek(self, offset):
                self.position = offset
            def read(self, count):
                assert 0 < count <= 8 * 1024**2
                self.counts.append(count)
                return bytes(count - int(self.missing_tail and len(self.counts) == 4))
        for missing_tail in (False, True):
            remote = BoundedRanges(missing_tail)
            reason = 'whole-archive-chunk' if missing_tail else 'exact-whole-archive-preimage'
            with self.assertRaisesRegex(WorkflowError, reason):
                products.acquire_archive(remote)
            self.assertEqual(remote.position, 0)
            self.assertEqual(remote.counts, [8388608, 8388608, 8388608, 595225])

    def test_closed_frontend_index_requires_exact_members_sizes_compression_and_regular_files(self):
        reader = products.FrozenOperatorFrontend()
        archive = ArchiveMetadata()
        self.assertEqual(len(reader.preflight(archive)), 154)
        archive.entries['../foreign'] = archive.entries['build.json']
        with self.assertRaisesRegex(WorkflowError, 'closed-archive-members'):
            reader.preflight(archive)
        for property_name, value in (('file_size', 1), ('compress_size', 64 * 1024**2),
                                     ('external_attr', stat.S_IFLNK << 16), ('flag_bits', 1)):
            archive = ArchiveMetadata()
            setattr(archive.entries['dist/latent-dev/latent-dev'], property_name, value)
            with self.assertRaisesRegex(WorkflowError, 'fixed-member'):
                reader.preflight(archive)
        archive = ArchiveMetadata()
        archive.entries['build.json'].compress_size = 64 * 1024**2
        with self.assertRaisesRegex(WorkflowError, 'receipt-length'):
            reader.preflight(archive)

    def test_actual_node_refusal_parser_rejects_uncertainty_foreign_fields_and_success(self):
        value = {'schemaVersion': 'latent.outbound-stream.operator.result.v1', 'command': 'prepare',
                 'status': 'failed', 'code': 'stream-operator-node-check-rejected-prepared-file-retained',
                 'uncertain': False}
        result = subprocess.CompletedProcess([], 1, b'', encode(value))
        self.assertFalse(programme.operator_refusal(result, value['code'])['uncertain'])
        for row in ({**value, 'uncertain': True}, {**value, 'privateInput': 'DO-NOT-DISCLOSE'},
                    {**value, 'status': 'completed'}):
            with self.assertRaisesRegex(DevError, 'exact-redacted-refusal'):
                programme.operator_refusal(subprocess.CompletedProcess([], 1, b'', encode(row)), value['code'])
        with self.assertRaisesRegex(DevError, 'refusal-exit-and-channel'):
            programme.operator_refusal(subprocess.CompletedProcess([], 0, b'', encode(value)), value['code'])

    def test_complete_original_baseline_is_preserved_while_stream_addition_is_explicit(self):
        base = programme.configuration(4096, True)
        before = encode(base)
        selected = programme.installation()
        value = programme.expected_configuration(base, selected)
        self.assertEqual(encode(base), before)
        self.assertEqual(value['credentials'], base['credentials'])
        self.assertEqual(value['providers']['blob'], base['providers']['blob'])
        self.assertEqual(value['providers']['bindings'][:-1], base['providers']['bindings'])
        self.assertEqual(value['providers']['outboundStreams'], selected['installation'])
        self.assertEqual(value['budgetProfile']['mode'], 'phase3')
        self.assertEqual(value['audit']['mode'], 'durable')
        self.assertEqual(value['capabilityPolicies'], {'formatVersion': 1})


class UnavailableInspection(unittest.TestCase):
    """Pure public-result parsers; these do not execute or qualify a node."""

    def test_unavailable_inspection_requires_exact_publication_and_never_invents_usage_or_authority(self):
        import copy
        publication = 'publication:sha256:' + 'a' * 64
        value = {'executionPermission': False, 'state': 'compiled-plan', 'nextPageToken': None,
            'revision': {'deploymentId': 'blue', 'publicationId': publication}, 'capabilities': [],
            'nodeUsage': {'scope': 'node', 'counters': {}}}
        self.assertFalse(programme.inspection_view(value, publication)['streamUsageObserved'])
        variants = [dict(value, executionPermission=True), dict(value, state='binding-plan-unavailable'),
                    dict(value, nextPageToken='another-page'), dict(value, capabilities=[{}]),
                    dict(value, nodeUsage=None),
                    dict(value, nodeUsage={'scope': 'node', 'counters': {'stream_owners': '0'}})]
        for changed in variants:
            with self.assertRaises(DevError):
                programme.inspection_view(changed, publication)
        for field in ('deploymentId', 'publicationId'):
            changed = copy.deepcopy(value)
            changed['revision'][field] = 'foreign'
            with self.assertRaisesRegex(DevError, 'exact-publication'):
                programme.inspection_view(changed, publication)
        ordinary = copy.deepcopy(value)
        ordinary['capabilities'] = [{'id': programme.CLOCK, 'contract': programme.CLOCK,
            'provider': programme.CLOCK_PROFILE,
            'inspection': {'providerProfile': programme.CLOCK_PROFILE}}]
        self.assertEqual(len(programme.inspection_view(ordinary, publication, clock=True)['capabilities']), 1)
        ordinary['capabilities'][0]['provider'] = 'foreign'
        with self.assertRaisesRegex(DevError, 'ordinary-clock-control'):
            programme.inspection_view(ordinary, publication, clock=True)

    def test_frozen_frontend_projection_keeps_failed_scope_and_publication_outcomes_closed(self):
        value = {'schemaVersion': 'latent.outbound-stream.operator.result.v1', 'command': 'inspect',
            'status': 'completed', 'result': {'executionPermission': False}}
        success = subprocess.CompletedProcess([], 0, encode(value), b'')
        self.assertEqual(programme.inspection_frontend(success), value['result'])
        refusal = 'stream-operator-inspection-publication-changed'
        failed = {'schemaVersion': value['schemaVersion'], 'command': 'inspect', 'status': 'failed',
                  'code': refusal, 'uncertain': False}
        result = subprocess.CompletedProcess([], 1, b'', encode(failed))
        self.assertEqual(programme.inspection_frontend(result, refusal=refusal)['code'], refusal)
        for changed in (dict(failed, uncertain=True), dict(failed, command='grant'),
                        dict(failed, code='operator-outcome-uncertain'), dict(failed, raw='forbidden')):
            with self.assertRaises(DevError):
                programme.inspection_frontend(subprocess.CompletedProcess([], 1, b'', encode(changed)),
                                               refusal=refusal)
        with self.assertRaises(DevError):
            programme.inspection_frontend(subprocess.CompletedProcess([], 0, encode(value), b'error'))
        self.assertEqual(len(programme.INSPECT_CASES), len(set(programme.INSPECT_CASES)))
        self.assertEqual(len(programme.INSPECT_CASES), 8)


if __name__ == '__main__':
    unittest.main()
