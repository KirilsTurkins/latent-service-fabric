"""Canonical task/export source guards; these are not managed guest execution."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tools.dotnet_guest import async_exports as exports
from tools.dotnet_guest_bindings import stackful_projection


class AsyncExportTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).parent / 'fixtures'
        self.baseline = (root / 'stackful-baseline-export.cs').read_text()
        self.asynchronous = (root / 'stackful-async-export.cs').read_text()

    def test_pinned_marshalling_runs_real_work_before_task_return_and_unpins_after(self):
        result, count = exports.bridge(self.baseline, self.asynchronous)
        self.assertEqual(count, 1)
        self.assertIn('public static unsafe void RunAsync(nint p0, int p1)', result)
        self.assertEqual(result.count('UTF8.GetString((byte*)p0, p1)'),1)
        self.assertLess(result.index('UTF8.GetString((byte*)p0, p1)'),result.index('ApiExportsImpl.Run((str))'))
        work = result.index('var ret = ApiExportsImpl.Run((str));')
        pin = result.index('GCHandle.Alloc(utf8Bytes')
        returned = result.index('RunTaskReturn(strPtr.ToInt32(), length);')
        release = result.index('cleanup();')
        self.assertLess(work, pin)
        self.assertLess(pin, returned)
        self.assertLess(returned, release)
        for value in ('AsyncSupport.', 'Task.FromResult', 'TaskCompletionSource', 'async Task'):
            self.assertNotIn(value, result)

    def test_unrelated_public_csharp_interface_is_preserved_exactly(self):
        contract = 'public interface IApiExports { static abstract string Run(string value); }\n'
        result, count = exports.bridge(contract + self.baseline, self.asynchronous)
        self.assertEqual(count, 1)
        self.assertTrue(result.startswith(contract))

    def test_entry_has_real_async_lift_and_fail_closed_unexpected_callback(self):
        result, _ = exports.bridge(self.baseline, self.asynchronous)
        self.assertIn('EntryPoint = "[async-lift]probe:boundary/api#run"', result)
        self.assertIn('EntryPoint = "[task-return]run"', result)
        self.assertIn('stackful canonical export received a callback', result)
        self.assertNotIn('IsCompletedSuccessfully', result)

    def test_added_work_between_call_and_completion_is_not_silently_removed(self):
        changed = self.asynchronous.replace('if (task.IsCompletedSuccessfully)', 'Unexpected();\n            if (task.IsCompletedSuccessfully)')
        with self.assertRaisesRegex(ValueError, 'pinned-entry-drift'):
            exports.bridge(self.baseline, changed)

    def test_changed_callback_cannot_supply_a_fake_completion(self):
        changed = self.asynchronous.replace('return (uint)AsyncSupport.Callback(e);', 'return 0;')
        with self.assertRaisesRegex(ValueError, 'pinned-callback-drift'):
            exports.bridge(self.baseline, changed)

    def test_unknown_helper_task_shape_fails_closed(self):
        changed = self.asynchronous.replace('public static async Task RunAsync', 'public static Task RunAsync')
        with self.assertRaisesRegex(ValueError, 'unaccounted-generated-task-support'):
            exports.bridge(self.baseline, changed)

    def test_missing_and_ambiguous_baseline_class_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'missing-baseline-class'):
            exports.bridge('', self.asynchronous)
        with self.assertRaisesRegex(ValueError, 'ambiguous-interop-class'):
            exports.bridge(self.baseline + '\n' + self.baseline, self.asynchronous)

    def test_synchronous_bindings_do_not_gain_an_async_task(self):
        result, count = exports.bridge(self.baseline, self.baseline)
        self.assertEqual((result, count), (self.baseline, 0))

    def test_pinned_aggregate_record_arguments_retain_original_lifting_and_result_lowering(self):
        root = Path(__file__).parent/'fixtures'
        baseline = (root/'stackful-record-baseline-export.cs').read_text()
        asynchronous = (root/'stackful-record-async-export.cs').read_text()
        result, count = exports.bridge(baseline,asynchronous)
        self.assertEqual(count,3)
        self.assertIn('public static unsafe void UpdateAsync(int p0, int p1)',result)
        self.assertIn('UpdateAsync(p0, p1);',result)
        self.assertIn('var ret = ApiExportsImpl.Update((new global::',result)
        self.assertIn('unchecked((uint)(p0)), (p1 != 0))));',result)
        self.assertEqual(result.count('new byte[p1]'),1)
        self.assertEqual(result.count('ScanTaskReturn(lowered28, lowered29, lowered30, lowered31, lowered32, lowered33, lowered34, lowered35);'),1)
        self.assertNotIn('async Task',result)
        self.assertNotIn('var task =',result)

    def test_unbalanced_or_statement_injected_record_call_is_rejected(self):
        for call in ('RunAsync((record); Unexpected());','RunAsync((record);','RunAsync(/* hidden */record);'):
            changed = self.asynchronous.replace('RunAsync((str));',call)
            with self.subTest(call=call), self.assertRaisesRegex(ValueError,'pinned-entry-drift'):
                exports.bridge(self.baseline,changed)

    def graph(self):
        function = {'name': 'run', 'kind': 'async-freestanding', 'params': [], 'result': 'u64'}
        return {'worlds': [{'name': 'test', 'package': 0, 'imports': {'read': {'function': dict(function)}},
                           'exports': {'run': {'function': dict(function)}}}],
                'interfaces': [], 'types': [], 'packages': [{'name': 'tests:boundary@1.0.0'}]}

    def test_only_selected_exports_keep_async_implementation_annotations(self):
        original = ('package tests:boundary@1.0.0;\nworld test {\n'
                    '  import read: async func() -> u64;\n  export run: async func() -> u64;\n}\n')
        graph = self.graph()
        selected, expected, count = exports.projection(original, graph, 'test', stackful_projection)
        self.assertEqual(count, 1)
        self.assertIn('import read: func()', selected)
        self.assertIn('export run: async func()', selected)
        self.assertEqual(expected['worlds'][0]['imports']['read']['function']['kind'], 'freestanding')
        self.assertEqual(expected['worlds'][0]['exports']['run']['function']['kind'], 'async-freestanding')
        self.assertEqual(graph['worlds'][0]['imports']['read']['function']['kind'], 'async-freestanding')

    def test_wrong_world_cannot_select_another_export(self):
        with self.assertRaisesRegex(ValueError, 'world-selection'):
            exports.projection('package tests:boundary@1.0.0;\nworld other {}\n', self.graph(), 'other', stackful_projection)

    def test_changed_export_name_cannot_silently_keep_a_synchronous_root(self):
        original = 'package tests:boundary@1.0.0;\nworld test {\n  export other: async func() -> u64;\n}\n'
        with self.assertRaisesRegex(ValueError, 'function-source-drift'):
            exports.projection(original, self.graph(), 'test', stackful_projection)

    def test_unbalanced_or_noncanonical_source_does_not_bypass_graph_validation(self):
        for original in ('package tests:boundary@1.0.0;\nworld test {',
                         'package tests:boundary@1.0.0;\n// export run: async func();\nworld test {}'):
            with self.subTest(original=original), self.assertRaises(ValueError):
                exports.projection(original, self.graph(), 'test', stackful_projection)


if __name__ == '__main__':
    unittest.main()
