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
        # The verified source candidate now has a named selector. A declaration
        # still cannot select a compiler/runtime without its exact tool inputs.
        from tools.typescript_guest.compiler import Compiler
        with self.assertRaisesRegex(ValueError,'requires actual source-bound compiler inputs'):
            Compiler(Path('unused-tools'),None,{},runtime_profile=IMPORT_PROFILE)
        with self.assertRaisesRegex(ValueError,'unsupported-typescript-runtime-profile'):
            selected_profile({'runtimeProfile':IMPORT_PROFILE+'-unknown'})

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

        # The pinned Engine starts Uninitialized. Its private initializer runs
        # before ScriptPreInitializing, so the selected import derivation must
        # enter EngineInitializing rather than accepting an uninitialized
        # engine in the native ownership guard. These are source controls, not
        # a SpiderMonkey execution substitute.
        from tools.typescript_guest.import_engine import (
            extend_native_import_source, NATIVE_IMPORT_SOURCES)
        root = Path(__file__).resolve().parents[2]
        constructor = (b'  config_ = std::move(config);\n'
                       b'  if (!init_js(*config_)) { abort("init"); }\n'
                       b'  JS_SetContextPrivate(cx(), this);\n'
                       b'  if (config_->initializer_script_path) {\n'
                       b'    if (!run_initialization_script()) { abort("initializer"); }\n'
                       b'  }\n'
                       b'  state_ = EngineState::ScriptPreInitializing;\n')
        execute = b'  return JS_ExecuteScript(cx, script, &result);\n'
        base = {
            'StarlingMonkey/runtime/engine.cpp': constructor + execute,
            'StarlingMonkey/builtins/install_builtins.cpp':
                b'#include "extension-api.h"\n'
                b'  return lsf::typescript::activation::install_clock_globals(engine->cx(), engine->global());\n',
            'embedding/embedding.cpp':
                b'using componentize::embedding::ReportAndClearException;\n'
                b'using componentize::embedding::Runtime;\n'
                b'  void *ret = JS_realloc(Runtime.cx, ptr, orig_size, new_size);\n',
        }
        original = dict(base)
        native = {name: (root/'sdk/typescript-guest/activation'/name).read_bytes()
                  for name in NATIVE_IMPORT_SOURCES}
        derived, receipt = extend_native_import_source(base, native)
        engine = derived['StarlingMonkey/runtime/engine.cpp']
        transition = b'  state_ = EngineState::EngineInitializing;\n'
        self.assertEqual(engine.count(transition), 1)
        self.assertLess(engine.index(b'config_ = std::move(config)'), engine.index(transition))
        self.assertLess(engine.index(transition), engine.index(b'init_js(*config_)'))
        self.assertLess(engine.index(b'run_initialization_script()'),
                        engine.index(b'state_ = EngineState::ScriptPreInitializing'))
        sealed = (b'  if (!JS_ExecuteScript(cx, script, &result)) return false;\n'
                  b'  return lsf::typescript::activation::seal_import_own_plans(cx);\n')
        self.assertEqual(engine.count(sealed), 1)
        self.assertEqual(engine.replace(transition, b'').replace(sealed, execute), constructor + execute)
        self.assertEqual(base, original)
        self.assertFalse(receipt['activationInterfaceChanged'])
        self.assertFalse(receipt['clockAuthorityGranted'])
        self.assertFalse(receipt['signedLSFComponentQualified'])
        for name, raw in native.items():
            self.assertEqual(derived['lsf/'+name], raw)
        # Missing, duplicate and already-derived constructor hooks fail closed.
        anchor = b'  config_ = std::move(config);\n'
        for malformed in (constructor.replace(anchor, b'') + execute,
                          constructor + anchor + execute):
            with self.subTest(source=malformed), self.assertRaises(ValueError):
                extend_native_import_source(dict(base, **{
                    'StarlingMonkey/runtime/engine.cpp': malformed}), native)
        with self.assertRaises(ValueError):
            extend_native_import_source(derived, native)

if __name__ == '__main__': unittest.main()
