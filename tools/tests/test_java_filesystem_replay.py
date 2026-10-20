"""Private retained-native adapter must prove current five components and39 cases."""
import copy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from tools import replay_java_closed_filesystem as replay
from tools.ci_lane_inventory import workflow_model
from tools.rust_capsule_node import ACTIVE_COUNTERS
from tools.rust_capsule_project import inventory, snapshot, write_json


def observed_node():
    return {'status': 'passed', 'invocations': [{'processReaped': True,
        'response': {'outcomeKnown': True}} for _ in range(39)],
        'nodeShutdown': {'reaped': True, 'record': {'clean': True}},
        'providerIdle': [{'unavailable': [], 'counters': {name: '0' for name in ACTIVE_COUNTERS}}
                         for _ in range(18)], 'samples': [{} for _ in range(36)],
        'standardScratchRefusal': {'status': 'passed', 'language': 'java', 'cases': [
            {'mode': mode, 'observation': {'unsupported': True},
             'invocation': {'decoded': [{'ok': 'scratch|java|unsupported-operation|fresh=1'}]}}
            for mode in ('open', 'create', 'temp')]},
        'javaFilesystemArguments': {'status': 'passed', 'cases': [
            {'mode': mode, 'category': category, 'invocation': {'decoded': [{'ok': 'scratch|java|' + category + '|fresh=1'}]}}
            for mode, category in replay.JAVA_ARGUMENTS.items()]}}


class JavaFilesystemReplay(unittest.TestCase):
    def test_full_original_workflow_and_job_bodies_survive_manual_projection(self):
        source = '.github/workflows/java-guest-feasibility.yml'
        original = workflow_model(replay.subprocess.check_output(
            ['git', 'show', replay.PRODUCTION + ':' + source], cwd=replay.ROOT, timeout=30).decode())
        actual = workflow_model((replay.ROOT / source).read_bytes().decode())
        self.assertEqual(actual['on']['workflow_dispatch']['inputs']['replay-closed-filesystem'], {
            'description': 'Fresh five Java components and39 signed filesystem outcomes using exact retained native products',
            'type': 'boolean', 'default': False})
        for name in original['jobs']:
            before, after = copy.deepcopy(original['jobs'][name]), copy.deepcopy(actual['jobs'][name])
            if name == 'dependency-ingestion':
                self.assertEqual(after['if'], "${{ github.event_name != 'workflow_dispatch' || (!inputs.qualify-scratch-refusals && !inputs.replay-closed-filesystem) }}")
                after['if'] = before['if']
            else:
                self.assertEqual(after.pop('if'), "${{ github.event_name != 'workflow_dispatch' || !inputs.replay-closed-filesystem }}")
            self.assertEqual(after, before)
        projected = {**actual, 'on': original['on'], 'jobs': original['jobs']}
        self.assertEqual(projected, original)
        job = actual['jobs']['closed-filesystem-reference']
        self.assertEqual(job['timeout-minutes'], 20)
        self.assertNotIn('needs', job)
        commands = '\n'.join(step.get('run', '') for step in job['steps'])
        for revision in (replay.PRODUCTION, replay.historical.HOST_SOURCE, replay.acquisition.SOURCE):
            self.assertIn(revision, commands)
        for forbidden in ('cargo build', 'cargo test', 'install-tools'):
            self.assertNotIn(forbidden, commands)
        self.assertIn('sudo apt-get install --yes bubblewrap', commands)

    def test_production_guard_denies_changed_source_or_dirty_tree(self):
        for result, status in ((SimpleNamespace(returncode=1, stdout=b'changed'), b''),
                               (SimpleNamespace(returncode=0, stdout=b''), b'?? unexpected')):
            with self.subTest(status=status), patch.object(replay.subprocess, 'run', return_value=result), \
                    patch.object(replay.subprocess, 'check_output', return_value=status), \
                    self.assertRaisesRegex(RuntimeError, 'java-filesystem-'):
                replay.production_inputs()

    def test_exact39_requires_three_unsupported_six_original_errors_and_every_owner_retired(self):
        self.assertEqual(replay.node_observation(observed_node())['invocations'], 39)
        changes = (
            lambda row: row['invocations'].pop(),
            lambda row: row['invocations'][0].update(processReaped=False),
            lambda row: row['standardScratchRefusal']['cases'][0]['observation'].update(unsupported=False),
            lambda row: row['javaFilesystemArguments']['cases'][0].update(category='unsupported-operation'),
            lambda row: row['javaFilesystemArguments']['cases'][0]['invocation'].update(decoded=[{'ok': 'wrong'}]),
            lambda row: row['providerIdle'].pop(),
            lambda row: row['providerIdle'][0]['counters'].update({ACTIVE_COUNTERS[0]: '1'}),
            lambda row: row['nodeShutdown']['record'].update(clean=False),
        )
        for change in changes:
            row = observed_node(); change(row)
            with self.subTest(change=change), self.assertRaisesRegex(RuntimeError, 'java-filesystem-'):
                replay.node_observation(row)

    def test_current_five_components_are_built_and_signed_without_fabricating_a_normal_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            products = {name: root / name.replace('/', '-') for name in (
                'latent', 'latentd', 'examples/package', 'examples/capsule_contracts', 'examples/capsule_authoring')}
            built = []
            def build(app, destination, *_args, **_kwargs):
                destination.mkdir(parents=True)
                (destination / 'source-inputs.json').write_bytes(inventory(snapshot(app)))
                (destination / 'component.wasm').write_bytes(b'controlled-component')
                write_json(destination / 'BUILD-COMPLETE.json', {'fresh': app.name})
                write_json(destination / 'bindings.json', {'closedFilesystem': replay.filesystem.stage(replay.ROOT / 'sdk/java-guest')})
                built.append((app, destination))
                return destination
            def run(_cli, _host, _signed, output, **_kwargs):
                output.mkdir(); row = observed_node();write_json(output / 'workflow.json', row);return row
            with patch.object(replay.sys, 'platform', 'linux'), patch.object(replay.sys, 'version_info', (3, 13)), \
                    patch.object(replay.os, 'geteuid', return_value=1000, create=True), \
                    patch.object(replay, 'production_inputs', return_value={'controlledSource': True}), \
                    patch.object(replay, 'selected_products', return_value=(products, {'normalJavaReceiptFabricated': False})), \
                    patch.object(replay, 'build', side_effect=build), patch.object(replay, 'run', side_effect=run), \
                    patch.object(replay, 'package_identity'), patch.object(replay, 'execution_report', return_value={'identity': 'control'}), \
                    patch('tools.rust_capsule_build.Commands.run') as signed:
                result = replay.qualify(root / 'observed', root / 'prepared', root / 'wasi')
            self.assertEqual([app.name for app, _ in built], list(replay.TEMPLATES))
            self.assertEqual(len(built), 5)
            self.assertEqual(signed.call_args.args[4:], tuple(path for _, path in built))
            self.assertEqual(result['observation']['invocations'], 39)
            self.assertFalse(result['inherited']['normalJavaReceiptFabricated'])
            self.assertFalse((root / 'observed/qualification.json').exists())
            self.assertTrue((root / 'observed/qualified.json').is_file())


if __name__ == '__main__': unittest.main()
