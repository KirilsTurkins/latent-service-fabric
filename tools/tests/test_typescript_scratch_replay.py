"""Historical tool reuse cannot masquerade as a new native/runtime pass."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import run_typescript_scratch_refusals as replay
from tools.rust_capsule_project import read_json, write_json


class ScratchReplay(unittest.TestCase):
    def execute(self, *, changed=False, incomplete=False):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root/'refused'
            original = {'compiledSourceMerge': 'original-compiled-source', 'historicalNormalOutcomes': 30,
                'currentNormalReceiptFabricated': False}
            products = {name: root/name.replace('/', '-') for name in
                ('examples/capsule_contracts', 'examples/package')}
            def qualify(destination, tools, contracts, packager):
                destination.mkdir()
                result = {'status': 'passed', 'cases': [{'case': case, 'observation': {
                    'status': 'refused', 'runtimeFilesystemExecutionClaimed': False}}
                    for case in replay.CASES]}
                if incomplete: result['cases'].pop()
                write_json(destination/'qualification.json', result)
                return result
            final = dict(original, compiledSourceMerge='foreign') if changed else original
            with patch.object(replay, 'historical', side_effect=[(products, {}, original), (products, {}, final)]) as history, \
                    patch.object(replay, 'qualify', side_effect=qualify) as compiler:
                if changed or incomplete:
                    with self.assertRaisesRegex(RuntimeError, 'scratch-typescript-'):
                        replay.run(root/'original', root/'tools', output)
                    self.assertFalse((output/'historical-inputs.json').exists())
                    return
                result = replay.run(root/'original', root/'tools', output)
                self.assertEqual(history.call_count, 2)
                self.assertEqual(compiler.call_args.args[2:],
                    (products['examples/capsule_contracts'], products['examples/package']))
                self.assertEqual(result['historicalProducts'], original)
                self.assertFalse(result['newNativeBuild'])
                self.assertFalse(result['nodeInvoked'])
                self.assertFalse(result['runtimeFilesystemExecutionClaimed'])
                self.assertEqual(read_json(output/'historical-inputs.json'), result)

    def test_exact_historical_tools_are_checked_before_and_after_three_refusals(self):
        self.execute()

    def test_changed_original_products_or_incomplete_refusal_never_publish_replay_pass(self):
        self.execute(changed=True)
        self.execute(incomplete=True)

    def test_manual_only_job_cannot_trigger_original_language_jobs_or_build_a_host(self):
        from tools.ci_lane_inventory import workflow_model
        from tools.rust_capsule_project import ROOT
        model = workflow_model((ROOT/'.github/workflows/typescript-guest.yml').read_text())
        selection = model['on']['workflow_dispatch']['inputs']['qualify-scratch-refusals']
        self.assertEqual(selection['type'], 'boolean')
        self.assertIs(selection['default'], False)
        for name in ('source-splicer', 'boundary'):
            self.assertIn('!inputs.qualify-scratch-refusals', model['jobs'][name]['if'])
        job = model['jobs']['scratch-refusals']
        self.assertEqual(job['if'], "${{ github.event_name == 'workflow_dispatch' && inputs.qualify-scratch-refusals }}")
        self.assertEqual(job['timeout-minutes'], 20)
        commands = '\n'.join(step.get('run', '') for step in job['steps'])
        self.assertIn('tools/run_typescript_scratch_refusals.py', commands)
        self.assertNotIn('cargo build', commands)
        self.assertNotIn('cargo test', commands)
        self.assertNotIn('qualify_typescript_capsules.py', commands)


if __name__ == '__main__': unittest.main()
