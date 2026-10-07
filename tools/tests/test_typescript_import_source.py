"""Parser-based async selection; these controls do not qualify engine/LSF APIs."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from tools.typescript_guest.import_engine import async_imports, IMPORT_PROFILE
from tools.typescript_guest.runtime_profile import selected_profile

FIXTURES = Path(__file__).parent/'fixtures/typescript_runtime_profile'

class AsyncImportSourceTests(unittest.TestCase):
    def graph(self):
        return json.loads((FIXTURES/'original.json').read_bytes())['graph']

    def test_private_import_candidate_is_not_yet_a_selectable_profile(self):
        with self.assertRaisesRegex(ValueError,'unsupported-typescript-runtime-profile'):
            selected_profile({'runtimeProfile':IMPORT_PROFILE})

    def test_selection_uses_actual_function_kind_not_package_or_name(self):
        graph = self.graph()
        graph['worlds'][0]['imports'] = {'timer-async': {'function': {
            'name':'timer-async','kind':'freestanding','params':[],'result':'u32'}}}
        self.assertEqual(async_imports(graph, 'lsf:typescript-probe/capsule@1.0.0'), [])
        graph['worlds'][0]['imports']['timer-async']['function']['kind'] = 'async-freestanding'
        self.assertEqual(async_imports(graph, 'lsf:typescript-probe/capsule@1.0.0'), [
            {'interface':'$root','function':'timer-async','kind':'async-freestanding','params':[],'result':'u32'}])

    def test_exact_parameter_result_and_resource_identities_are_retained(self):
        graph = self.graph()
        function = {'name':'lookup','kind':{'async-method':3},
                    'params':[{'name':'self','type':4},{'name':'request','type':5}],'result':6}
        graph['worlds'][0]['imports'] = {'lookup':{'function':deepcopy(function)}}
        self.assertEqual(async_imports(graph,'lsf:typescript-probe/capsule@1.0.0')[0],
            dict(interface='$root',function='lookup',kind=function['kind'],params=function['params'],result=6))

    def test_unknown_parser_kind_fails_closed(self):
        graph = self.graph()
        graph['worlds'][0]['imports'] = {'lookup':{'function':{
            'name':'lookup','kind':{},'params':[],'result':None}}}
        with self.assertRaisesRegex(ValueError,'unknown-async-import-function-kind'):
            async_imports(graph,'lsf:typescript-probe/capsule@1.0.0')

    def test_native_layout_ownership_is_a_captured_source_input(self):
        from tools.typescript_guest.activation_engine import NATIVE_SOURCES, engine_input_paths
        names = {'native_import_lifecycle.h','native_imports.h','broker_import_accounting.h','native_ownership.h'}
        self.assertTrue(names <= set(NATIVE_SOURCES))
        self.assertTrue({'sdk/typescript-guest/activation/'+name for name in names} <= set(engine_input_paths()))

if __name__ == '__main__': unittest.main()
