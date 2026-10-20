"""Refusal controls for fixed component replay, without running native products."""
import json
from pathlib import Path
import tempfile
import unittest
from tools import replay_java_http_phases as replay
from tools.phase2_operator_process import WorkflowError


class JavaPhasePreparedReplay(unittest.TestCase):
    def test_wrong_archive_refuses_before_creating_any_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)/'output'
            with self.assertRaisesRegex(WorkflowError, 'archive-identity'):
                replay.extract(b'not-the-original-successful-build', output)
            self.assertFalse(output.exists())

    def test_only_relative_canonical_paths_and_fixed_bounded_members_are_selected(self):
        for bad in ('../escape', '/absolute', 'a/../escape', 'a\\file', './file', '', None, True):
            with self.subTest(bad=bad), self.assertRaises(WorkflowError): replay.safe(bad)
        pins = replay.pins()
        self.assertEqual(len(pins), 55)
        self.assertEqual(pins['component.wasm']['bytes'], 17_034_179)
        self.assertTrue(all(not n.startswith('../') and n != 'retrieval.json' for n in pins))

    def test_missing_original_layer_restores_only_after_exact_package_input_identity(self):
        from tools.rust_capsule_project import digest
        with tempfile.TemporaryDirectory() as temporary:
            build = Path(temporary);original = b'exact-original-public-layer'
            expected = {'public.wit': {'digest': digest(original), 'size': len(original)}}
            (build/'package-inputs.json').write_text(json.dumps(expected))
            (build/'package-source.json').write_text(json.dumps({'layers': [
                {'source': 'public.wit', 'path': 'public.wit'}]}))
            layer = build/'package/layers/public.wit';layer.parent.mkdir(parents=True)
            layer.write_bytes(b'changed-package-layer')
            with self.assertRaisesRegex(WorkflowError, 'layer-original-identity'):
                replay.restore_layers(build)
            self.assertFalse((build/'public.wit').exists())
            layer.write_bytes(original)
            self.assertEqual(replay.restore_layers(build), expected)
            self.assertEqual((build/'public.wit').read_bytes(), original)
            (build/'public.wit').write_bytes(b'tampered-restored-input')
            with self.assertRaisesRegex(WorkflowError, 'original-package-inputs'):
                replay.restore_layers(build)

    def test_compilation_recipe_drift_refuses_before_original_git_source_selection(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            build = Path(temporary)
            source = {'vendor/lsf/'+str(i): {'digest': 'sha256:'+'1'*64, 'size': 1} for i in range(199)}
            source.update({'src/dev/latent/app/Capsule.java': {'digest': 'sha256:'+'1'*64, 'size': 1},
                'wit/world.wit': {'digest': 'sha256:'+'1'*64, 'size': 1}})
            (build/'source-inputs.json').write_text(json.dumps(source))
            (build/'recipe-inputs.json').write_text(json.dumps({'tools/java_guest/compiler.py': {
                'digest': 'sha256:'+'0'*64, 'size': 1}}))
            with patch.object(replay.subprocess, 'check_output') as git, \
                    patch.object(replay, 'file_identity', return_value={'sha256': 'sha256:'+'1'*64, 'bytes': 1}):
                with self.assertRaisesRegex(WorkflowError, 'current-compilation-recipe-drift'):
                    replay.source_proof(build)
            git.assert_not_called()


    def test_explicit_manual_lane_restores_complete_original_workflow_and_command_guards(self):
        import subprocess
        import yaml
        name = '.github/workflows/java-guest-feasibility.yml'
        before = yaml.safe_load(subprocess.check_output(['git', 'show', replay.SOURCE+':'+name],
            cwd=replay.ROOT, text=True))
        selected = yaml.safe_load((replay.ROOT/name).read_text())
        flag = selected[True]['workflow_dispatch']['inputs'].pop('java_http_phase_prepared')
        self.assertEqual(flag['type'], 'boolean');self.assertIs(flag['default'], False)
        job = selected['jobs'].pop('http-phase-prepared')
        self.assertEqual(job['if'], "${{ github.event_name == 'workflow_dispatch' && inputs.java_http_phase_prepared }}")
        self.assertEqual(selected['jobs']['compiler-component'].pop('if'),
            "${{ github.event_name != 'workflow_dispatch' || !inputs.java_http_phase_prepared }}")
        self.assertEqual(selected['jobs']['dependency-ingestion']['if'],
            "${{ (github.event_name != 'workflow_dispatch' || !inputs.qualify-scratch-refusals) && (github.event_name != 'workflow_dispatch' || !inputs.java_http_phase_prepared) }}")
        selected['jobs']['dependency-ingestion']['if'] = before['jobs']['dependency-ingestion']['if']
        self.assertEqual(selected, before)
        commands = '\n'.join(step.get('run', '') for step in job['steps'])
        for forbidden in ('cargo ', 'gradle ', 'setup-java', 'java_capsule.py', 'qualify_java_http_phases.py'):
            self.assertNotIn(forbidden, commands)
