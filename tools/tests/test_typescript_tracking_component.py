"""Reject unsuccessful/mixed component provenance before reusing guest bytes."""
import copy
from pathlib import Path
import tempfile
import unittest

from tools import typescript_tracking_component as component
from tools.phase2_operator_process import WorkflowError


def metadata():
    run = {'id': component.RUN, 'head_sha': component.SOURCE, 'event': 'push',
        'head_branch': 'feat/typescript-tracking-limits-20261021',
        'path': '.github/workflows/typescript-tracking-limits.yml',
        'status': 'completed', 'conclusion': 'success'}
    job = {'id': component.JOB, 'run_id': component.RUN, 'head_sha': component.SOURCE,
        'name': 'Signed independent task queue native timer and memory boundaries',
        'status': 'completed', 'conclusion': 'success', 'steps': [{'conclusion': 'success'}]}
    artifact = {'id': component.ARTIFACT, 'expired': False,
        'workflow_run': {'id': component.RUN, 'head_sha': component.SOURCE},
        'name': 'typescript-tracking-limits-'+component.SOURCE,
        'size_in_bytes': component.ARCHIVE_BYTES, 'digest': 'sha256:'+component.ARCHIVE_SHA}
    return run, job, artifact


class TrackingComponent(unittest.TestCase):
    def test_unsuccessful_or_mixed_producers_never_qualify(self):
        original = metadata()
        component.provenance(*original)
        changes = ((0, 'id', 1), (0, 'head_sha', '0'*40), (0, 'event', 'pull_request'),
            (0, 'head_branch', 'development'), (0, 'path', 'other.yml'),
            (0, 'status', 'in_progress'), (0, 'conclusion', 'cancelled'),
            (1, 'id', 1), (1, 'run_id', 1), (1, 'head_sha', '0'*40),
            (1, 'name', 'other'), (1, 'status', 'in_progress'), (1, 'conclusion', 'failure'),
            (1, 'steps', [{'conclusion': 'failure'}]), (1, 'steps', []),
            (2, 'id', 1), (2, 'expired', True), (2, 'size_in_bytes', 1),
            (2, 'digest', 'sha256:'+'0'*64), (2, 'name', 'other'),
            (2, 'workflow_run', {'id': component.RUN, 'head_sha': '0'*40}),
            (2, 'workflow_run', {'id': 1, 'head_sha': component.SOURCE}))
        for index, key, value in changes:
            changed = copy.deepcopy(original)
            changed[index][key] = value
            with self.subTest(index=index, key=key), self.assertRaises(WorkflowError):
                component.provenance(*changed)

    def test_changed_archive_refuses_before_creating_any_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)/'build'
            with self.assertRaisesRegex(WorkflowError, 'tracking-component-whole-archive'):
                component.unpack(b'changed original archive', destination)
            self.assertFalse(destination.exists())

    def test_missing_signing_sources_restore_only_exact_archived_wit_layers(self):
        import hashlib
        import json
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            names = [f'wit/{index}.wit' for index in range(5)]
            members, inputs = {}, {}
            for index,name in enumerate(names):
                path = root/'package/layers'/name
                path.parent.mkdir(parents=True,exist_ok=True)
                raw = ('package test:fixture'+str(index)+';\n').encode()
                path.write_bytes(raw)
                identity = {'bytes':len(raw),'sha256':'sha256:'+hashlib.sha256(raw).hexdigest()}
                members['package/layers/'+name] = identity
                inputs[name] = {'size':len(raw),'digest':identity['sha256']}
            declaration = {'layers':[{'source':name,'path':name} for name in names]}
            (root/'package-source.json').write_text(json.dumps(declaration))
            (root/'package-inputs.json').write_text(json.dumps(inputs))
            restored = component.package_sources(root,members,restore=True)
            self.assertEqual(len(restored),5)
            self.assertEqual(component.package_sources(root,members),restored)
            (root/names[0]).write_bytes(b'changed')
            with self.assertRaises(WorkflowError):component.package_sources(root,members)
            declaration['layers'][0]['source'] = declaration['layers'][0]['path'] = 'missing-component.wasm'
            (root/'package-source.json').write_text(json.dumps(declaration))
            with self.assertRaisesRegex(WorkflowError,'only-authenticated-wit'):
                component.package_sources(root,members)


if __name__ == '__main__':
    unittest.main()
