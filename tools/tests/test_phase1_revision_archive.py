"""Revision archive dispatch and semantic replay; no processes or workloads."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import package_phase1_evidence as package
from tools import validate_phase1_archive as verify


class RevisionArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='phase1-revision-archive-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.sequence = 0

    def inputs(self, backend=False):
        self.sequence += 1
        parent = self.root / str(self.sequence)
        source, output = parent / 'source', parent / 'package'
        source.mkdir(parents=True)
        kind = 'backend-revision' if backend else 'revision'
        aggregate = {
            'schema': f'latent.optimization.{kind}-aggregate.v1',
            'profile': 'full', 'status': 'complete',
            'population_complete': True, 'attempt_count_complete': True,
            'statistics': [{'name': 'elapsed_nanos', 'median': '123'}],
        }
        self.write_aggregate(source, aggregate)
        (source / 'suite.json').write_bytes(verify.canonical({
            'schema': f'latent.optimization.{kind}-suite.v1'}))
        (source / 'binary').write_bytes(b'fixed synthetic executable\0')
        (source / 'empty.log').write_bytes(b'')
        return source, output, aggregate

    @staticmethod
    def write_aggregate(source, value):
        (source / 'aggregate.json').write_bytes(verify.canonical(value))

    @staticmethod
    def validator_name(backend):
        return 'validate_backend_revision_suite' if backend else 'validate_revision_suite'

    def archive(self, source, output):
        output.mkdir()
        return package.create_archive(source, output, self.root / 'absent-policy.json')

    def test_each_format_replays_extracted_bytes_before_publication_without_policy(self):
        for backend in (False, True):
            with self.subTest(backend=backend):
                source, output, value = self.inputs(backend)
                before = {p.name: p.read_bytes() for p in source.iterdir()}

                def replay(path):
                    self.assertEqual(path.name, 'suite.json')
                    self.assertNotEqual(path.parent, source)
                    self.assertFalse(output.exists())
                    self.assertEqual(before, {p.name: p.read_bytes() for p in path.parent.iterdir()})
                    return value

                # Only full-population success is substituted. Safe archive I/O,
                # extraction, aggregate comparison and final publication are real.
                with patch.object(verify, self.validator_name(backend), side_effect=replay) as called:
                    with patch.object(verify, self.validator_name(not backend)) as other:
                        manifest = package.package(source, output, self.root / 'absent-policy.json')
                        called.assert_called_once()
                        other.assert_not_called()
                self.assertEqual(before, {p.name: p.read_bytes() for p in source.iterdir()})
                self.assertEqual({row['path'] for row in manifest['files']}, set(before))
                self.assertEqual(next(row['bytes'] for row in manifest['files'] if row['path'] == 'empty.log'), '0')
                self.assertFalse((output / 'measurement-policy.json').exists())
                self.assertFalse((output / 'comparison.json').exists())

    def test_rehashed_changed_statistic_never_publishes(self):
        for backend in (False, True):
            with self.subTest(backend=backend):
                source, output, value = self.inputs(backend)
                self.write_aggregate(source, {**value, 'statistics': []})
                with patch.object(verify, self.validator_name(backend), return_value=value):
                    with self.assertRaisesRegex(ValueError, 'differs from replayed'):
                        package.package(source, output, self.root / 'absent-policy.json')
                self.assertFalse(output.exists())

    def test_full_qualification_requires_exact_schema_and_boolean_flags(self):
        for backend in (False, True):
            for change in ({'profile': 'smoke'}, {'status': 'incomplete'}, {'status': 'failed'},
                           {'population_complete': False}, {'population_complete': 1},
                           {'attempt_count_complete': False}, {'attempt_count_complete': 1},
                           {'schema': 'latent.optimization.aggregate.v1'}):
                with self.subTest(backend=backend, change=change):
                    source, _, value = self.inputs(backend)
                    value = {**value, **change}
                    self.write_aggregate(source, value)
                    with patch.object(verify, self.validator_name(backend), return_value=value):
                        with self.assertRaisesRegex(ValueError, 'complete full-population'):
                            verify.verify_revision(source, backend=backend)

    def test_shape_only_is_explicit_and_semantic_failure_propagates(self):
        for backend in (False, True):
            with self.subTest(backend=backend):
                source, output, value = self.inputs(backend)
                self.write_aggregate(source, {**value, 'profile': 'smoke', 'status': 'incomplete'})
                self.archive(source, output)
                with patch.object(verify, self.validator_name(backend), side_effect=ValueError('raw semantic failure')) as replay:
                    verify.verify_package(output, replay=False)
                    replay.assert_not_called()
                    with self.assertRaisesRegex(ValueError, 'raw semantic failure'):
                        verify.verify_package(output)

    def test_suite_is_required_even_without_semantic_replay(self):
        for backend in (False, True):
            with self.subTest(backend=backend):
                source, output, _ = self.inputs(backend)
                (source / 'suite.json').unlink()
                self.archive(source, output)
                with self.assertRaisesRegex(ValueError, 'omits suite'):
                    verify.verify_package(output, replay=False)

    def test_compressed_expanded_and_file_caps_apply_before_replay(self):
        self.assertEqual((verify.MAX_COMPRESSED, verify.MAX_EXPANDED, verify.MAX_FILES),
                         (99_000_000, 1024**3, 5000))
        for backend in (False, True):
            source, output, _ = self.inputs(backend)
            self.archive(source, output)
            for name, reason in [('MAX_COMPRESSED', 'exceeds bound'),
                                 ('MAX_EXPANDED', 'expanded bound'),
                                 ('MAX_FILES', 'file count')]:
                with self.subTest(backend=backend, bound=name):
                    with patch.object(verify, name, 1), patch.object(verify, self.validator_name(backend)) as replay:
                        with self.assertRaisesRegex(ValueError, reason):
                            verify.verify_package(output)
                        replay.assert_not_called()

    def test_aggregate_byte_cap_precedes_dispatch_and_replay(self):
        self.assertEqual(verify.MAX_AGGREGATE_BYTES, 8 * 1024 * 1024)
        for backend in (False, True):
            with self.subTest(backend=backend):
                source, _, value = self.inputs(backend)
                encoded = verify.canonical(value)
                with patch.object(verify, 'MAX_AGGREGATE_BYTES', len(encoded) - 1):
                    with patch.object(verify, self.validator_name(backend)) as replay:
                        with self.assertRaisesRegex(ValueError, 'json-byte-bound'):
                            verify.evidence_kind(source)
                        with self.assertRaisesRegex(ValueError, 'json-byte-bound'):
                            verify.verify_revision(source, backend=backend)
                        replay.assert_not_called()

    def test_unknown_revision_version_cannot_masquerade_as_supported(self):
        for backend in (False, True):
            with self.subTest(backend=backend):
                source, _, value = self.inputs(backend)
                self.write_aggregate(source, {**value, 'schema': value['schema'].replace('.v1', '.v2')})
                with self.assertRaisesRegex(ValueError, 'unsupported evidence schema'):
                    verify.evidence_kind(source)

    def test_rehashed_external_response_corruption_fails_real_replay(self):
        from tools.tests.test_optimization_revision_evidence import Fixture
        source, output, _ = self.inputs()
        fixture = Fixture(source)
        retained = verify.validate_revision_suite(source / 'suite.json')
        self.assertEqual(retained['status'], 'incomplete')
        batch = fixture.suite['runs'][0]['batches'][0]
        rows = [json.loads(line) for line in (source / batch['attempts']['path']).read_bytes().splitlines()]
        rows[0]['response']['payload_sha256'] = 'sha256:' + '0' * 64
        fixture.replace(batch['attempts'], b''.join(verify.canonical(row) + b'\n' for row in rows))
        self.write_aggregate(source, retained)
        self.archive(source, output)
        verify.verify_package(output, replay=False)
        with self.assertRaisesRegex(ValueError, 'false-semantic-success'):
            verify.verify_package(output)
        unpublished = output.parent / 'unpublished'
        with self.assertRaisesRegex(ValueError, 'false-semantic-success'):
            package.package(source, unpublished, self.root / 'absent-policy.json')
        self.assertFalse(unpublished.exists())

    def test_rehashed_backend_missing_warmup_fails_real_replay(self):
        from tools.tests.test_optimization_backend_revision_suite import Fixture
        source, output, _ = self.inputs(True)
        fixture = Fixture(source)
        retained = verify.validate_backend_revision_suite(source / 'suite.json')
        self.assertEqual(retained['status'], 'incomplete')
        row = fixture.suite['runs'][0]['raw']
        raw = json.loads((source / row['path']).read_bytes())
        raw['samples'].pop(0)
        fixture.replace(row, raw)
        self.write_aggregate(source, retained)
        self.archive(source, output)
        verify.verify_package(output, replay=False)
        with self.assertRaisesRegex(ValueError, 'sample-count'):
            verify.verify_package(output)
        unpublished = output.parent / 'unpublished'
        with self.assertRaisesRegex(ValueError, 'sample-count'):
            package.package(source, unpublished, self.root / 'absent-policy.json')
        self.assertFalse(unpublished.exists())


if __name__ == '__main__':
    unittest.main()
