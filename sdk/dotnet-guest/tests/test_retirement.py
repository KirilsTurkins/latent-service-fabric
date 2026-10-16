"""Private ABI/bridge controls, separate from signed native retirement proof."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tools.dotnet_guest import async_exports, retirement


class RetirementTests(unittest.TestCase):
    def test_unselected_profile_preserves_public_source_without_compiler_commands(self):
        from types import SimpleNamespace
        from tools.dotnet_guest import runtime
        compiler = SimpleNamespace(run=lambda *args:self.fail('unselected retirement invoked the compiler'))
        source, output = Path('unselected-source'), Path('unselected-retirement-output')
        self.assertEqual(retirement.prepare(compiler,source,'test:app/service@1.0.0',output,[runtime.CLOCK]),
            (source,None))

    def graph(self):
        imported = {'owner':{'interface':{'id':0}}}
        return {'worlds':[{'imports':imported},{'imports':copy.deepcopy(imported)}],
            'interfaces':[{'name':'owner','package':0,'types':{},'functions':{
                'drain':{'name':'drain','kind':'async-freestanding','params':[]}}}],
            'packages':[{'name':retirement.PACKAGE}], 'types':[]}

    def test_only_exact_parameterless_async_private_drain_is_recognized(self):
        self.assertTrue(retirement.private_import(self.graph()))
        for field, value in (('params',[{'name':'borrow','type':'u32'}]), ('kind','freestanding'), ('result','u32')):
            with self.subTest(field=field):
                graph = self.graph()
                graph['interfaces'][0]['functions']['drain'][field] = value
                with self.assertRaisesRegex(ValueError,'private-import-shape'):
                    retirement.private_import(graph)
        graph = self.graph()
        graph['interfaces'][0]['types']['resource'] = 0
        with self.assertRaisesRegex(ValueError,'private-interface-shape'):
            retirement.private_import(graph)

    def test_private_strip_cannot_remove_changed_function_or_additional_import(self):
        public = 'package test:app;\nworld service {\n  export run: async func();\n}\n'
        private = public.replace('world service {','world service {\n  import '+retirement.IDENTITY+';')+retirement.PRIVATE
        self.assertEqual(retirement.without_private(private).strip(), public.strip())
        for changed in (private.replace('drain: async func();','drain: async func(value: u32);'),
                        private.replace('  import '+retirement.IDENTITY+';',('  import '+retirement.IDENTITY+';\n')*2),
                        private.replace('drain: async func();','drain: async func();\n    extra: func();')):
            with self.assertRaisesRegex(ValueError,'private-source-shape'):
                retirement.without_private(changed)

    def test_private_drain_precedes_real_task_return_and_original_unpin(self):
        fixture = Path(__file__).parent/'fixtures'
        baseline = (fixture/'stackful-baseline-export.cs').read_text()
        asynchronous = (fixture/'stackful-async-export.cs').read_text()
        call = 'global::TestWorld.wit.Imports.latent.dotnetRetirement.IOwnerImports.Drain()'
        selected, count = async_exports.bridge(baseline, asynchronous, call)
        self.assertEqual(count,1)
        self.assertEqual(selected.count(call+';'),1)
        self.assertLess(selected.index('ApiExportsImpl.Run((str))'), selected.index(call+';'))
        self.assertLess(selected.index(call+';'), selected.index('RunTaskReturn(strPtr.ToInt32(), length);'))
        self.assertLess(selected.index('RunTaskReturn(strPtr.ToInt32(), length);'),selected.index('cleanup();'))
        changed = asynchronous.replace('RunTaskReturn(strPtr.ToInt32(), length);','UnexpectedReturn(strPtr.ToInt32(), length);')
        with self.assertRaisesRegex(ValueError,'task-return-shape'):
            async_exports.bridge(baseline,changed,call)

    def test_ambiguous_private_interfaces_are_rejected(self):
        graph = self.graph()
        graph['interfaces'].append(copy.deepcopy(graph['interfaces'][0]))
        graph['worlds'][1]['imports']['owner']['interface']['id'] = 1
        with self.assertRaisesRegex(ValueError,'private-interface-shape'):
            retirement.private_import(graph)


if __name__ == '__main__': unittest.main()
