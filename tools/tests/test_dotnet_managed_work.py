"""Closed selected bridge and actual metadata-receipt fences; no guest credit."""
import copy
import json
from pathlib import Path
import unittest

from tools.dotnet_guest import managed_work as work, retirement, runtime, task_wait
from tools.rust_capsule_project import ROOT, digest, write_json
from tools.tests import test_dotnet_task_wait as controls

FIXTURE = ROOT/'sdk/dotnet-guest/tests/fixtures/managed-work-rewrite.json'
DECLARED = [runtime.CLOCK, runtime.ACTIVATION, runtime.WALL, runtime.RANDOM]


def graph(direction='imports', *, managed=True):
    functions = {
        'reserve': {'name':'reserve', 'kind':'freestanding', 'params':[
            {'name':'kind','type':'u32'}, {'name':'parent-generation','type':'u64'},
            {'name':'parent-id','type':'u64'}], 'result':1},
        'settle': {'name':'settle', 'kind':'freestanding', 'params':[
            {'name':'generation','type':'u64'}, {'name':'id','type':'u64'}], 'result':2},
        'close': {'name':'close', 'kind':'freestanding', 'params':[], 'result':2},
        'context': {'name':'context', 'kind':'freestanding', 'params':[
            {'name':'generation','type':'u64'}, {'name':'id','type':'u64'}]},
    }
    value = {'packages':[{'name':work.PACKAGE},{'name':retirement.PACKAGE}],
        'interfaces':[{'name':'owner','types':{},'functions':functions,'package':0},
            {'name':'owner','types':{},'functions':{'drain':{'name':'drain','kind':'async-freestanding','params':[]}},'package':1}],
        'types':[{'name':None,'owner':None,'kind':{'tuple':{'types':['u64','u64']}}},
            {'name':None,'owner':None,'kind':{'result':{'ok':0,'err':'u32'}}},
            {'name':None,'owner':None,'kind':{'result':{'ok':None,'err':'u32'}}}],
        'worlds':[{'imports':{},'exports':{}}]}
    value['worlds'][0][direction][retirement.IDENTITY] = {'interface':{'id':1}}
    if managed:
        value['worlds'][0][direction][work.IDENTITY] = {'interface':{'id':0}}
    return value


class ManagedWorkContractTests(unittest.TestCase):
    def test_original_profiles_remain_explicit_and_managed_selection_is_boolean(self):
        imports = ['wasi:io/poll@0.2.6']
        self.assertEqual(runtime.select(DECLARED, imports), 'runtime')
        self.assertEqual(runtime.select(DECLARED, imports, managed_work=True), 'runtime-managed')
        self.assertEqual(runtime.select([*DECLARED,runtime.HTTP], sorted(runtime.WASI_HTTP_IMPORTS), managed_work=True), 'http-managed')
        for selection in (None, 0, 1, 'true'):
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                runtime.select(DECLARED, imports, managed_work=selection)

    def test_managed_selection_cannot_invent_missing_facets(self):
        for missing in DECLARED:
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                runtime.select([item for item in DECLARED if item != missing], [], managed_work=True)

    def test_private_contract_is_an_exact_pair_not_a_generic_linker_escape(self):
        consumer, primary = graph(), graph('exports')
        self.assertEqual(retirement.composition_edges(consumer, primary, True, True), (retirement.IDENTITY, work.IDENTITY))
        for selected, managed in ((False, True), (True, False), (1, True), (True, 1)):
            with self.subTest(selected=selected, managed=managed), self.assertRaises(ValueError):
                retirement.composition_edges(consumer, primary, selected, managed)
        with self.assertRaises(ValueError):
            retirement.composition_edges(consumer, graph('exports', managed=False), True, True)

    def test_old_private_pair_remains_unchanged(self):
        self.assertEqual(retirement.composition_edges(graph(managed=False), graph('exports',managed=False), True), (retirement.IDENTITY,))
        self.assertFalse(work.private_interface(graph(managed=False), 'imports'))

    def test_token_width_and_exact_parameter_identity_are_not_structural_guesses(self):
        for name, index, replacement in (('reserve',1,'u32'), ('reserve',2,'u32'), ('settle',0,'u32'), ('context',1,'string')):
            value = graph(); value['interfaces'][0]['functions'][name]['params'][index]['type'] = replacement
            with self.subTest(name=name,index=index), self.assertRaises(ValueError):
                work.private_interface(value, 'imports')

    def test_tuple_named_owner_and_extra_operation_are_refused(self):
        values = []
        value = graph(); value['types'][0]['kind']['tuple']['types'][1] = 'u32'; values.append(value)
        value = graph(); value['types'][0]['name'] = 'token'; values.append(value)
        value = graph(); value['types'][0]['owner'] = {'interface':0}; values.append(value)
        value = graph(); value['interfaces'][0]['types']['resource'] = 0; values.append(value)
        value = graph(); value['interfaces'][0]['functions']['bypass'] = copy.deepcopy(value['interfaces'][0]['functions']['close']); values.append(value)
        for index, value in enumerate(values):
            with self.subTest(index=index), self.assertRaises(ValueError):
                work.private_interface(value, 'imports')

    def test_changed_error_and_async_calling_convention_are_refused(self):
        value = graph(); value['types'][2]['kind']['result']['err'] = 'u64'
        with self.assertRaises(ValueError): work.private_interface(value, 'imports')
        value = graph(); value['interfaces'][0]['functions']['close']['kind'] = 'async-freestanding'
        with self.assertRaises(ValueError): work.private_interface(value, 'imports')

    def test_private_source_projection_is_closed_and_rejects_a_changed_preimage(self):
        text = 'package example:control;\nworld root {\n  import '+work.IDENTITY+';\n}\n'+work.PRIVATE
        self.assertNotIn(work.PACKAGE, work.without_private(text))
        for changed in (text.replace('parent-generation: u64','parent-generation: u32'), text+work.PRIVATE,
                        text.replace('close: func()', 'close: async func()')):
            with self.subTest(changed=changed[-30:]), self.assertRaises(ValueError):
                work.without_private(changed)

    def test_actual_metadata_receipt_requires_every_producer_and_unqualified_scope(self):
        value = json.loads(FIXTURE.read_text())
        task_wait.validate_receipt(value, finite=True, managed=True)
        self.assertFalse(value['managedAcceptedWork']['qualified'])
        self.assertEqual(len(value['managedAcceptedWork']['modifiedOriginalMethods']),18)
        self.assertEqual(value['unchangedOriginalMethods'],44723)
        for change in ('completion','queueAdmission','context','closing','taskIdentity','requiredContinuationIdentity'):
            changed = copy.deepcopy(value); changed['managedAcceptedWork'][change] = 'unproved'
            with self.subTest(change=change), self.assertRaises(ValueError):
                task_wait.validate_receipt(changed, finite=True, managed=True)

    def test_no_missing_or_cross_selected_old_receipt_claims_managed_support(self):
        value = json.loads(FIXTURE.read_text())
        for finite, managed in ((False, True), (True, False), (True, 1)):
            with self.subTest(finite=finite,managed=managed), self.assertRaises(ValueError):
                task_wait.validate_receipt(value, finite=finite, managed=managed)
        del value['managedAcceptedWork']['modifiedOriginalMethods'][next(iter(value['managedAcceptedWork']['modifiedOriginalMethods']))]
        with self.assertRaises(ValueError): task_wait.validate_receipt(value, finite=True, managed=True)

    def test_selected_port_binds_exact_new_corelib_and_all_required_facets(self):
        control = controls.TaskWaitPortTests(); control.setUp(); self.addCleanup(control.doCleanups)
        control.declared = DECLARED
        def run(stage, *arguments):
            self.assertEqual(arguments[2], '--managed-task-wait')
            arguments[-2].write_bytes(b'explicit-managed-tool-control')
            value = json.loads(FIXTURE.read_text()); value['outputDigest'] = digest(b'explicit-managed-tool-control')
            write_json(arguments[-1], value)
        control.run_tool = run
        port = control.prepare(managed=True); control.references(port)
        self.assertEqual(port.validated_helper_count(),77)
        self.assertEqual(port.finish(control.project,control.evidence)['selection']['requiredDeclarations'],sorted(DECLARED))

    def test_required_content_task_keeps_original_transport_error_channel(self):
        work.validate_http_rewrite(copy.deepcopy(work.HTTP_REWRITE))
        for key, changed in (('task','synthetic-completion'), ('error','ignored'), ('qualified', True), ('modifiedOriginalMethods',True)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                work.validate_http_rewrite({**work.HTTP_REWRITE,key:changed})


if __name__ == '__main__':
    unittest.main()
