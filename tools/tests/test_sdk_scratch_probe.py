"""The oracle requires reached, caught standard API failures and real retirement."""
import unittest
from unittest.mock import patch
from tools import sdk_scratch_probe as probe
from tools.sdk_scratch_fixture import LANGUAGES


def invocation(value=None, *, trap=False):
    return {'exitCode': 4 if trap else 0, 'processReaped': True,
        'decoded': None if trap else [{'ok': value}], 'response': {'outcomeKnown': True,
            'error': {'code': 'guest-trap'} if trap else None,
            'data': {'terminalState': 'guest_trap' if trap else 'completed',
                'consumption': {'cpuFuel': 100, 'peakMemoryBytes': 4096,
                    'outboundRequests': 0, 'logBytes': 0, 'effectCount': 0}}}}


class ScratchProbe(unittest.TestCase):
    def test_only_bounded_exact_caught_results_count_and_not_found_is_not_unsupported(self):
        labels = {'rust': 'io-error|kind=unsupported', 'c': 'errno=nosys',
            'go': 'path-error|errno=52', 'java': 'unsupported-operation', 'dotnet': 'platform-not-supported'}
        for language, label in labels.items():
            with self.subTest(language=language):
                row = probe.refusal(language, [{'ok': 'scratch|' + language + '|' + label + '|fresh=1'}])
                self.assertTrue(row['unsupported'])
                self.assertFalse(row['genericTrapCauseInferred'])
        self.assertFalse(probe.refusal('rust', [{'ok': 'scratch|rust|io-error|kind=not-found|fresh=1'}])['unsupported'])
        self.assertFalse(probe.refusal('java', [{'ok': 'scratch|java|io-error|fresh=1'}])['unsupported'])

    def test_old_greeting_traps_unknown_and_malformed_values_do_not_become_api_evidence(self):
        for language in LANGUAGES:
            for value in (None, [], [{'err': 'unsupported'}], [{'ok': None}],
                    [{'ok': 'scratch|' + language + '|unexpected-success'}],
                    [{'ok': 'Hello, scratch:open!'}], [{'ok': 'private raw exception text'}],
                    [{'ok': 'scratch|go|path-error|errno=999999|fresh=1'}]):
                with self.subTest(language=language, value=value):
                    with self.assertRaisesRegex(RuntimeError, 'scratch-'):
                        probe.refusal(language, value)

    def execute(self, *, change=None, grants=None, idle_error=None):
        result = {'invocations': [], 'providerIdle': [], 'samples': []}
        rows = [invocation('scratch|rust|entry|fresh=1')]
        rows += [invocation('scratch|rust|io-error|kind=unsupported|fresh=1') for _ in range(3)]
        rows += [invocation(trap=True), invocation('scratch|rust|entry|fresh=1')]
        if change: change(rows)
        with patch('tools.rust_capsule_node.call', side_effect=rows) as called, \
                patch('tools.rust_capsule_node.assert_value') as assert_value, \
                patch('tools.rust_capsule_node.provider_idle', return_value={'idle': True}, side_effect=idle_error) as idle, \
                patch('tools.rust_capsule_node.sample', return_value={'retired': True}) as sample:
            probe.probe(object(), {'budget': {'cpuFuel': 1000, 'memoryBytes': 8192},
                'grants': [] if grants is None else grants}, object(), result, 5, language='rust')
        return result, called, assert_value, idle, sample

    def test_six_calls_include_original_bound_owner_retirement_and_explicit_trap_fresh_pair(self):
        result, called, values, idle, sample = self.execute()
        self.assertEqual([call.args[4] for call in called.call_args_list],
            [['scratch:' + mode] for mode in ('entry', 'open', 'create', 'temp-directory', 'trap', 'fresh')])
        self.assertEqual((len(result['invocations']), idle.call_count, sample.call_count, values.call_count), (6, 6, 6, 2))
        self.assertTrue(result['standardScratchRefusal']['allErrorsAreUnsupported'])
        self.assertFalse(result['standardScratchRefusal']['filesystemGrantsAdded'])
        self.assertFalse(result['standardScratchRefusal']['fullTicketQualification'])

    def test_no_filesystem_grants_or_inferred_unknown_outcome_and_no_false_retirement(self):
        changes = (
            lambda rows: rows[1].update(processReaped=False),
            lambda rows: rows[1]['response'].update(outcomeKnown=False),
            lambda rows: rows[1]['response']['data']['consumption'].update(effectCount=1),
            lambda rows: rows[1]['response']['data']['consumption'].update(cpuFuel=1001),
            lambda rows: rows[4]['response']['error'].update(code='guest-runtime-error'),
            lambda rows: rows[1].update(decoded=[{'ok': 'Hello, scratch:open!'}]),
        )
        for change in changes:
            with self.subTest(change=change):
                with self.assertRaisesRegex(RuntimeError, 'scratch-'):
                    self.execute(change=change)
        with self.assertRaisesRegex(RuntimeError, 'scratch-no-filesystem-or-storage-grant'):
            self.execute(grants=[{'capability': 'latent:blob/blob@0.1.0'}])
        with self.assertRaisesRegex(RuntimeError, 'actual-owner-not-retired'):
            self.execute(idle_error=RuntimeError('actual-owner-not-retired'))

    def test_selector_refuses_alias_foreign_language_and_competing_campaign_before_output(self):
        from pathlib import Path
        import tempfile
        from tools.run_rust_capsule_workflow import run
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)/'not-written'
            for kwargs in ({'language': 'typescript', 'standard_scratch_refusal': True},
                    {'language': 'rust', 'standard_scratch_refusal': 1},
                    {'language': 'rust', 'standard_scratch_refusal': True, 'rust_standard_entropy': True},
                    {'language': 'rust', 'standard_scratch_refusal': True, 'standard_typescript_clocks': True},
                    {'language': 'dotnet', 'standard_scratch_refusal': True, 'dotnet_task_runtime': True}):
                with self.subTest(kwargs=kwargs):
                    with self.assertRaisesRegex(RuntimeError, 'authoring-scratch-refusal-selection'):
                        run(Path('cli'), Path('node'), Path('fixture'), output, **kwargs)
                    self.assertFalse(output.exists())


if __name__ == '__main__': unittest.main()
