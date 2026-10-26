"""The reader repair cannot select a different compiled guest or loosen provenance."""
import copy
import hashlib
import io
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import replay_dotnet_resource_late as replay
from tools import ci_lane_inventory as lanes
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import ROOT, read_file


class DotnetResourceLateReplay(unittest.TestCase):
    def origin(self):
        metadata = dict(replay.ARTIFACT, expired=False, workflow_run={'id': replay.RUN, 'head_sha': replay.SOURCE})
        job = {'id': replay.JOB, 'run_id': replay.RUN, 'head_sha': replay.SOURCE,
            'status': 'completed', 'conclusion': 'failure'}
        run = {'id': replay.RUN, 'head_sha': replay.SOURCE, 'head_branch': 'feat/java-dotnet-late-facilities-20261021',
            'path': replay.WORKFLOW, 'event': 'workflow_dispatch', 'status': 'completed', 'conclusion': 'failure'}
        return metadata, job, run

    def test_exact_failed_original_origin_and_archive_identity_are_mandatory(self):
        replay.validate_origin(*self.origin())
        for index, key, value in ((0, 'digest', 'sha256:'+'0'*64), (0, 'expired', True),
                (1, 'conclusion', 'success'), (1, 'head_sha', '0'*40), (2, 'event', 'pull_request'),
                (2, 'path', '.github/workflows/java-resource-runtime.yml')):
            rows = list(self.origin()); rows[index][key] = value
            with self.assertRaises(WorkflowError): replay.validate_origin(*rows)
        with self.assertRaises(WorkflowError): list(replay.archive_members(b'wrong archive'))

    def test_every_member_is_crc_checked_and_private_or_escaping_members_refuse(self):
        for mutation in ('valid', 'escape', 'link', 'private-key', 'foreign-prefix', 'duplicate'):
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, 'w') as archive:
                for index in range(223):
                    name = 'dotnet-resource-late/build/row-'+str(index)+'.json'
                    if index == 222:
                        name = {'escape': '../escape', 'private-key': 'dotnet-resource-late/key.pem',
                            'foreign-prefix': 'other/public.json', 'duplicate': 'dotnet-resource-late/build/row-0.json'}.get(mutation, name)
                    info = zipfile.ZipInfo(name)
                    if index == 222 and mutation == 'link': info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    archive.writestr(info, b'{}')
            raw = stream.getvalue(); expected = {'size_in_bytes': len(raw), 'digest': replay.digest(raw)}
            with patch.object(replay, 'ARTIFACT', expected):
                if mutation == 'valid': self.assertEqual(len(list(replay.archive_members(raw))), 223)
                else:
                    with self.assertRaises(WorkflowError): list(replay.archive_members(raw))

    def test_source_allowance_is_only_reader_and_workflow_not_sdk_or_recipe(self):
        names = [*replay.CHANGED, 'sdk/dotnet-guest/source.cs']
        blobs = {name: (name+' original').encode() for name in names}
        identities = {name: {'sha256': replay.digest(raw), 'bytes': len(raw)} for name, raw in blobs.items()}
        batch = b''
        for name in sorted(names):
            raw = blobs[name]; oid = hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
            batch += (oid+' blob '+str(len(raw))+'\n').encode()+raw+b'\n'
        original = {'source': replay.SOURCE, 'status': 'failed', 'stage': 'one-fresh-offline-normal-native-aot-component',
            'newGuestComponentsCompiled': 1, 'newNativeProductsBuilt': 0, 'consumerNativeCompiledByThisCampaign': False,
            'consumerNativeSourceObservation': {'exact': 'source'},
            'materials': {name: identities[name] for name in replay.CHANGED},
            'sdkSources': {'source.cs': {'digest': identities[names[-1]]['sha256'], 'size': identities[names[-1]]['bytes']}}}
        def identity(path):
            name = Path(path).relative_to(ROOT).as_posix()
            return identities[name] if name not in replay.CHANGED else replay.CHANGED[name]
        with patch.object(replay, 'git_source_identity', return_value={'exact': 'source'}), \
                patch.object(replay.subprocess, 'check_output', return_value=batch), \
                patch.object(replay, 'read_json', return_value={}), patch.object(replay, 'file_identity', side_effect=identity):
            proof = replay.original_materials(original, Path('controlled-build'))
            self.assertEqual(set(proof['reviewedConsumerChanges']), set(replay.CHANGED))
            broken = copy.deepcopy(original); broken['sdkSources']['source.cs']['size'] += 1
            with self.assertRaises(WorkflowError): replay.original_materials(broken, Path('controlled-build'))
            with patch.object(replay, 'file_identity', side_effect=lambda path:
                    {'sha256': 'sha256:'+'f'*64, 'bytes': 10} if Path(path) == ROOT/replay.READER else identity(path)):
                with self.assertRaises(WorkflowError): replay.original_materials(original, Path('controlled-build'))

    def test_node_only_workflow_has_no_compiler_and_restores_exact_df4_workflow(self):
        raw = read_file(ROOT/replay.WORKFLOW).decode()
        original, job = raw.split('\n  replay-late-facilities:\n')
        selector = ('      replay_late_facilities:\n'
            '        description: Reuse the exact completed df4 AOT package after its managed-profile reader repair\n'
            '        type: boolean\n        default: false\n')
        self.assertEqual(original.count(selector), 1)
        original = original.replace(selector, '', 1)
        original = original.replace('(!inputs.late_facilities && !inputs.replay_late_facilities)', '!inputs.late_facilities', 1)
        original = original.replace('inputs.late_facilities && !inputs.replay_late_facilities', 'inputs.late_facilities', 1)
        self.assertEqual(hashlib.sha256((original.rstrip()+'\n').encode()).hexdigest(),
            'ec927e58aa04f8f643abe123435fed56fb9fba7e71892083c17aa241e24eb174')
        model = lanes.workflow_model(raw); selected = model['jobs']['replay-late-facilities']
        self.assertFalse(model['on']['workflow_dispatch']['inputs']['replay_late_facilities']['default'])
        self.assertEqual(selected['if'], "${{ github.event_name == 'workflow_dispatch' && inputs.replay_late_facilities && !inputs.late_facilities }}")
        commands = [step.get('run', '') for step in selected['steps']]
        self.assertFalse(any(text in command for command in commands for text in ('install-tools', 'cargo build', 'dotnet ', 'java ', 'gradle ')))
        self.assertEqual(sum('replay_dotnet_resource_late.py run ' in command for command in commands), 1)
        for step in selected['steps']:
            if 'GH_TOKEN' in step.get('env', {}):
                self.assertNotIn(' run ', step['run'])
                self.assertTrue(' acquire ' in step['run'] or 'release_preparation_cli_native_products.py' in step['run'])


if __name__ == '__main__': unittest.main()
