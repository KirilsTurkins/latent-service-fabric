"""Historical source proof and fixed replay inputs; no local native execution."""
import copy
from pathlib import Path
import unittest
from tools import replay_go_standard_entropy as replay, go_entropy_replay_inputs as inputs
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import digest, ROOT


class EntropyReplay(unittest.TestCase):
    def source(self):
        before = b'before\n' + replay.BEFORE + b'\nafter'
        after = before.replace(replay.BEFORE, replay.AFTER)
        identity = lambda raw: {'sha256': digest(raw), 'bytes': len(raw)}
        old = {'helpers': {replay.RUNNER: identity(before), 'compiler': {'sha256': 'exact'}}, 'runtime': {'exact': 1}}
        new = copy.deepcopy(old); new['helpers'][replay.RUNNER] = identity(after)
        return old, new, before, after

    def test_only_exact_reviewed_authority_call_may_differ_from_historical_compiled_source(self):
        old, new, before, after = self.source()
        actual = replay.historical_source(old, new, before, after)
        self.assertEqual(actual['compiledSourceCommit'], inputs.TESTED)
        self.assertTrue(actual['otherPreparedSourceFieldsUnchanged'])
        self.assertNotEqual(actual['originalRunner'], actual['currentRunner'])

    def test_changed_native_compiler_helper_sdk_or_extra_runner_edit_refuses(self):
        for change in ('runtime', 'compiler', 'sdk', 'runner'):
            old, new, before, after = self.source()
            if change == 'runtime': new['runtime']['exact'] = 2
            elif change == 'compiler': new['helpers']['compiler']['sha256'] = 'foreign'
            elif change == 'sdk': new['sdk'] = {'foreign': True}
            else: after += b'\nextra-command'
            with self.subTest(change=change), self.assertRaisesRegex(WorkflowError, 'go-entropy-replay-'):
                replay.historical_source(old, new, before, after)

    def test_fixed_source_allowlist_excludes_compiler_cache_private_material_and_other_component(self):
        self.assertEqual(inputs.ARTIFACT, 12212440772)
        for name in ('go-capsule-dependencies/node/workflow.json',
                     'go-standard-entropy/build/package-inputs.json',
                     'go-standard-entropy/build/component.wasm',
                     'go-capsule-dependencies/native-binaries/latentd'):
            self.assertTrue(inputs.selected(name), name)
        for name in ('go-standard-entropy/project/src/main.go',
                     'go-standard-entropy/build/compiler-inputs.json',
                     'go-capsule-dependencies/project/dependency-inputs/private-key',
                     'go-capsule-dependencies/native-binaries/../outside',
                     'go-standard-http-signed/build/component.wasm'):
            self.assertFalse(inputs.selected(name), name)

    def test_explicit_replay_preserves_original_45_minute_default_programme(self):
        from tools import ci_lane_inventory
        value = ci_lane_inventory.workflow_model((ROOT / '.github/workflows/go-guest.yml').read_text())
        self.assertEqual(value['jobs']['upstream-probe']['timeout-minutes'], 45)
        self.assertEqual(value['jobs']['upstream-probe']['if'],
            "${{ github.event_name != 'workflow_dispatch' || !inputs.replay-entropy-authority }}")
        self.assertEqual(value['jobs']['entropy-authority-replay']['timeout-minutes'], 20)
        self.assertEqual(value['jobs']['entropy-authority-replay']['if'],
            "${{ github.event_name == 'workflow_dispatch' && inputs.replay-entropy-authority }}")


if __name__ == '__main__': unittest.main()
