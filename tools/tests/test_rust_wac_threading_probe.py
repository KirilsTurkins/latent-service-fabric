"""Authenticate the original retained WAC failure and bounded probe inputs."""
import copy
import hashlib
import io
import json
import tempfile
from pathlib import Path
import unittest
import warnings
import zipfile
from unittest.mock import patch

from tools import diagnose_rust_wac_threading as probe
from tools.phase2_operator_process import WorkflowError


class RetainedPreviewIdentity(unittest.TestCase):
    def metadata(self):
        return [
            {'id': probe.RUN, 'head_sha': probe.SOURCE, 'event': 'push',
             'head_branch': 'fix/rust-http-bindgen-20261104',
             'path': '.github/workflows/rust-http-thread-composition-diagnostic.yml',
             'status': 'completed', 'conclusion': 'failure', 'run_attempt': 1},
            {'jobs': [{'id': probe.JOB, 'head_sha': probe.SOURCE,
             'name': 'Capture one unadmitted composed HTTP and ThreadPool graph',
             'status': 'completed', 'conclusion': 'failure'}]},
            {'id': probe.ARTIFACT, 'name': 'rust-http-thread-composition-diagnostic-' + probe.SOURCE,
             'size_in_bytes': probe.ARCHIVE_SIZE, 'digest': 'sha256:' + probe.ARCHIVE_SHA,
             'expired': False, 'workflow_run': {'id': probe.RUN, 'head_sha': probe.SOURCE}},
        ]

    def test_exact_failed_run_job_and_artifact_are_all_required(self):
        values = self.metadata(); result = probe.official_metadata(lambda _path: values.pop(0))
        self.assertEqual((result['run'], result['job'], result['artifact']), (probe.RUN, probe.JOB, probe.ARTIFACT))
        for row, field, bad in ((0, 'head_sha', 'foreign'), (0, 'conclusion', 'success'),
                                (0, 'run_attempt', 2), (2, 'expired', True),
                                (2, 'digest', 'sha256:other')):
            values = self.metadata(); values[row][field] = bad
            with self.subTest(row=row, field=field), self.assertRaises(WorkflowError):
                probe.official_metadata(lambda _path: values.pop(0))
        values = self.metadata(); values[1]['jobs'][0]['id'] += 1
        with self.assertRaises(WorkflowError): probe.official_metadata(lambda _path: values.pop(0))
        values = self.metadata(); values[2]['workflow_run']['id'] += 1
        with self.assertRaises(WorkflowError): probe.official_metadata(lambda _path: values.pop(0))

    def test_compare_records_named_recipe_before_refusing_missing_artifact_authority(self):
        head = 'a' * 40
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / 'source'; source.mkdir()
            (source / 'recipe.txt').write_bytes(b'original recipe')
            composer = root / 'composer'; composer.write_bytes(b'wac')
            with patch.multiple(probe, ROOT=source, RECIPE=('recipe.txt',), NEW_WAC_SIZE=3,
                    NEW_WAC_SHA=hashlib.sha256(b'wac').hexdigest()), \
                 patch.object(probe.sys, 'platform', 'linux'), \
                 patch.object(probe.subprocess, 'check_output', side_effect=[head.encode(), b'']), \
                 patch.dict(probe.os.environ, {'GH_TOKEN': ''}):
                with self.assertRaisesRegex(WorkflowError, 'official-artifact-token-required'):
                    probe.compare(root / 'output', composer, head)
                failed = json.loads((root / 'output/FAILED.json').read_text())
                expected = {'name': 'recipe.txt', 'digest': 'sha256:' + hashlib.sha256(b'original recipe').hexdigest(),
                    'size': len(b'original recipe')}
                self.assertEqual(failed['recipe'], {'recipe.txt': expected})
                self.assertEqual(failed['stage'], 'verify-current-source')
                self.assertEqual(failed['attempts'], [])
                (source / 'recipe.txt').write_bytes(b'changed recipe')
                self.assertNotEqual(probe.recipe_identities(), failed['recipe'])

    def test_only_the_observed_transparent_field_alias_is_normalized(self):
        original = self.alias_graph(); flattened = copy.deepcopy(original)
        flattened['types'][1]['kind'] = {'type': 'string'}
        before, after = copy.deepcopy(original), copy.deepcopy(flattened)
        with self.assertRaises(ValueError):
            probe.unchanged_interfaces(original, flattened, probe.names(original, 'imports'), probe.names(flattened, 'imports'))
        self.assertTrue(probe.compare_public_graphs(original, flattened))
        self.assertFalse(probe.compare_public_graphs(original, copy.deepcopy(original)))
        self.assertEqual((original, flattened), (before, after))

    def test_alias_projection_refuses_changed_resource_ownership_kind_and_cycles(self):
        original = self.alias_graph()
        for change in ('resource-id', 'resource-owner', 'duplicate-resource', 'handle-ownership',
                       'function-kind', 'alias-target', 'alias-owner', 'recursive-alias',
                       'named-type-set', 'other-type'):
            selected = copy.deepcopy(original); selected['types'][1]['kind'] = {'type': 'string'}
            types = selected['types']; interface = selected['interfaces'][0]
            if change == 'resource-id': types[5]['kind']['handle']['own'] = 4
            elif change == 'resource-owner': types[3]['owner'] = {'interface': 1}
            elif change == 'duplicate-resource': types.append(copy.deepcopy(types[3]))
            elif change == 'handle-ownership': types[5]['kind']['handle'] = {'borrow': 3}
            elif change == 'function-kind': interface['functions']['read']['kind'] = {'async-method': 3}
            elif change == 'alias-target': types[1]['kind'] = {'type': 'u32'}
            elif change == 'alias-owner': types[0]['owner'] = {'interface': 1}
            elif change == 'recursive-alias': types[1]['kind'] = {'type': 1}
            elif change == 'named-type-set': del interface['types']['field-key']
            else: types[2]['kind'] = {'type': 'u32'}
            with self.subTest(change=change), self.assertRaises(ValueError):
                probe.compare_public_graphs(original, selected)

    @staticmethod
    def alias_graph():
        return {'worlds': [{'name': 'root', 'imports': {'http': {'interface': {'id': 0}}}, 'exports': {}}],
            'packages': [{'name': 'wasi:http@0.2.12'}, {'name': 'outside:foreign@1.0.0'}],
            'interfaces': [
                {'package': 0, 'name': 'types', 'types': {'field-key': 0, 'field-name': 1,
                    'field-value': 2, 'fields': 3, 'other': 4},
                 'functions': {'read': {'name': 'read', 'kind': {'method': 3},
                    'params': [{'name': 'self', 'type': 6}, {'name': 'key', 'type': 1}], 'result': 5}}},
                {'package': 1, 'name': 'types', 'types': {}, 'functions': {}}],
            'types': [
                {'name': 'field-key', 'owner': {'interface': 0}, 'kind': {'type': 'string'}},
                {'name': 'field-name', 'owner': {'interface': 0}, 'kind': {'type': 0}},
                {'name': 'field-value', 'owner': {'interface': 0}, 'kind': {'list': 'u8'}},
                {'name': 'fields', 'owner': {'interface': 0}, 'kind': 'resource'},
                {'name': 'other', 'owner': {'interface': 0}, 'kind': 'resource'},
                {'name': None, 'owner': None, 'kind': {'handle': {'own': 3}}},
                {'name': None, 'owner': None, 'kind': {'handle': {'borrow': 3}}}]}

    def test_exact_members_and_duplicate_or_tampered_archives_refuse(self):
        def archive(rows):
            data = io.BytesIO()
            with warnings.catch_warnings(), zipfile.ZipFile(data, 'w') as output:
                warnings.simplefilter('ignore', UserWarning)
                for name, body in rows: output.writestr(name, body)
            return data.getvalue()
        raw = archive([('retained/preview.wasm', b'preview')])
        members = {'retained/preview.wasm': (7, hashlib.sha256(b'preview').hexdigest())}
        with patch.multiple(probe, ARCHIVE_SIZE=len(raw), ARCHIVE_SHA=hashlib.sha256(raw).hexdigest(), MEMBERS=members):
            self.assertEqual(probe.selected_members(raw), {'retained/preview.wasm': b'preview'})
            with self.assertRaises(WorkflowError): probe.selected_members(raw[:-1])
            with patch.dict(members, {'retained/preview.wasm': (7, '0' * 64)}):
                with self.assertRaises(WorkflowError): probe.selected_members(raw)
        repeated = archive([('retained/preview.wasm', b'preview'), ('retained/preview.wasm', b'preview')])
        with patch.multiple(probe, ARCHIVE_SIZE=len(repeated), ARCHIVE_SHA=hashlib.sha256(repeated).hexdigest(), MEMBERS=members):
            with self.assertRaisesRegex(WorkflowError, 'archive-entries'): probe.selected_members(repeated)


if __name__ == '__main__':
    unittest.main()
