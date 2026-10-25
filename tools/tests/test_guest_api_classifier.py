"""Real reader/byte joins on controlled syntax, not compiler qualification."""
import copy
from pathlib import Path
import tempfile
import unittest

from tools import guest_api_analysis as api
from tools import guest_compiler_capture as capture
from tools.dev_workflow.common import digest
from tools.dotnet_guest import reachability as managed
from tools.rust_capsule_project import inventory
from tools.tests.test_dotnet_compiler_reachability import PROPERTIES
from tools.tests.test_guest_emitted_code import core, section


ROOT = b'int gate(void) { if (0) { /* lsf-api-root-edge */ outside_denied(); } return 7; }\n'
IR = b'define i32 @gate() {\nentry:\n ret i32 7\n}\n'
CORELIB = digest(b'controlled original selected CoreLib')
TOKEN = 0x06000123
API_ID = digest((CORELIB + ':' + str(TOKEN)).encode())[7:]
LIBRARY_ID = 'b' * 64


def method_pair(before, after, *, operand='ldftn'):
    signature = digest(bytes((0, 0, 14)))
    queries = {'schemaVersion': 'lsf.dotnet.compiler-queries.v1', 'sourceRevision': managed.SOURCE,
        'initializersExecuted': False, 'omittedMethods': 0, 'queries': [
            {'id': 'a' * 64, 'assemblyDigest': digest(b'entry'), 'signatureDigest': digest(b'entry signature'),
             'symbol': 'Entry.Run', 'mangledName': 'Entry__Run', 'kind': 'method',
             'declaration': 'ordinary', 'rootAnchor': True},
            {'id': LIBRARY_ID, 'assemblyDigest': digest(b'identical library'), 'signatureDigest': signature,
             'symbol': 'Outside.Probe', 'mangledName': 'Outside__Probe', 'kind': 'method',
             'declaration': 'ordinary', 'rootAnchor': False},
            {'id': API_ID, 'assemblyDigest': CORELIB, 'signatureDigest': signature,
             'symbol': 'System.IO.Path.GetTempFileName', 'mangledName': 'System_Private_CoreLib_System_IO_Path__GetTempFileName',
             'kind': 'method', 'declaration': 'ordinary', 'rootAnchor': False}]}
    prefix = b'<DirectedGraph xmlns="http://schemas.microsoft.com/vs/2009/dgml"><Nodes>'
    nodes = b'<Node Id="0" Label="Entry__Run"/>'
    extra = (b'<Node Id="1" Label="Outside__Probe"/>'
             b'<Node Id="2" Label="System_Private_CoreLib_System_IO_Path__GetTempFileName"/>')
    cil = {'schemaVersion': 'lsf.dotnet.cil-references.v1', 'corelibDigest': CORELIB,
        'scope': 'captured-input-call-operands', 'forwarding': 'exact-selected-ILC-assembly-identities',
        'indirectDispatch': 'unknown', 'apiSupport': 'unknown', 'runtimeExecution': 'not-observed',
        'unknownReferences': 1, 'omittedEdges': 0, 'bodiesInspected': 2, 'bodyBytesInspected': 100,
        'edges': [{'sourceId': LIBRARY_ID, 'bodyDigest': digest(b'original library IL body'), 'offset': 4,
            'operation': operand, 'targetId': API_ID, 'targetAssemblyDigest': CORELIB,
            'targetSignatureDigest': signature}],
        'apiBodies': [{'api': 'System.IO.Path.GetTempFileName', 'id': API_ID, 'assemblyDigest': CORELIB,
            'signatureDigest': signature, 'bodyDigest': digest(b'original API IL body'), 'metadataToken': TOKEN}]}
    result = []
    for selected, files in ((False, before), (True, after)):
        raw = prefix + nodes + (extra if selected else b'') + b'</Nodes><Links></Links>' + PROPERTIES + b'</DirectedGraph>'
        value = managed.scanner(raw, queries)
        value['compiledMethods'] = managed.compiled_methods(raw, queries)
        value['cilReferences'] = managed.cil_observation(cil, CORELIB, value['methods'])
        value.update({name: digest(name.encode()) for name in ('responseDigest', 'metadataToolSourceDigest', 'metadataToolDigest')})
        result.append(managed.bind(value, source=digest(inventory(files)), component=digest(str(selected).encode()),
            compiler=digest(b'compiler'), recipe=digest(b'recipe'), graph=digest(b'identical library graph')))
    return result


class ApiRootClassifier(unittest.TestCase):
    def test_exact_emitted_roots_preserve_init_callbacks_dynamic_and_ambiguous_names(self):
        # The real byte parser supplies the paths; no caller boolean says a
        # root executed. A duplicate name across core modules is not guessed.
        raw = core([b'\xd2\x02\x1a\x0b', b'\x01\x0b'], start=2, names={1: 'entry', 2: 'gate'})
        joined = api.emitted_root_join(raw, ['gate', 'missing'])
        self.assertEqual(joined['gate']['state'], 'potential-root-path')
        self.assertEqual(joined['gate']['phases'], ['callbacks', 'initialization'])
        self.assertEqual(joined['missing']['state'], 'unmapped-or-ambiguous')
        component = b'\0asm\x0d\0\x01\0' + section(1, raw) + section(1, raw)
        self.assertEqual(api.emitted_root_join(component, ['gate'])['gate']['state'], 'unmapped-or-ambiguous')
        dynamic = core([b'\x41\x00\x11\x00\x00\x0b', b'\x01\x0b'], table=True, names={2: 'gate'})
        joined = api.emitted_root_join(dynamic, ['gate'])['gate']
        self.assertEqual(joined['state'], 'potential-root-path')
        self.assertEqual(joined['phases'], ['callbacks'])
        self.assertEqual(joined['apiElimination'], 'not-established')

    def test_complete_local_edge_absence_and_emitted_root_do_not_certify_global_api_elimination(self):
        files = {'src/main.c': ROOT}
        raw = core([b'\x01\x0b'], names={1: 'gate'})
        with tempfile.TemporaryDirectory() as directory:
            owner = capture.Capture(files, 'c')
            owner.retain(owner.queries[0]['id'], IR)
            observed = owner.finish(Path(directory), files, raw, digest(b'recipe'), digest(b'compiler'), digest(b'graph'))
            findings = api.compiler_findings({'compiler-call-edges': observed}, raw)
            api.validate_compiler_findings(findings)
            row = findings['rows'][0]
            self.assertEqual(row['state'], 'edge-not-observed')
            self.assertEqual(row['rootMapping']['state'], 'potential-root-path')
            self.assertEqual((row['apiReachability'], row['apiBehavior'], row['execution']),
                             ('unknown', 'unqualified', 'not-observed'))
            changed = copy.deepcopy(findings); changed['rows'][0]['rootMapping']['phases'] = [[]]
            with self.assertRaises(ValueError): api.validate_compiler_findings(changed)

    def test_actual_callee_dgml_join_distinguishes_virtual_operand_and_selected_implementation(self):
        before = {'src/Capsule.cs': b'if (false) { // lsf-api-root-edge\nProbe();\n}', 'library.cs': b'original library'}
        after = dict(before); after['src/Capsule.cs'] = before['src/Capsule.cs'].replace(b'false', b'true')
        for operand in ('ldftn', 'callvirt'):
            with self.subTest(operand=operand):
                negative, positive = method_pair(before, after, operand=operand)
                findings = api.compiler_findings({'compiler-method-reachability': positive}, b'\0asm\x01\0\0\0')
                api.validate_compiler_findings(findings)
                row = next(row for row in findings['rows'] if row['standardApi'] is not None)
                self.assertEqual(row['state'], 'scanner-and-codegen-retained')
                self.assertEqual(row['implementationDigest'], CORELIB)
                self.assertEqual(row['inputOperands'], [operand])
                self.assertEqual(row['apiReachability'], 'unknown')
                if operand == 'ldftn':
                    pair = api.dotnet_retention_pair(negative, positive, before, after, 'src/Capsule.cs')
                    self.assertEqual(pair['apiMethodIdentity'], API_ID)
                    self.assertEqual(pair['scope'], 'one-controlled-api-callee-retention-differential')
                else:
                    with self.assertRaisesRegex(ValueError, 'addressable-input-source'):
                        api.dotnet_retention_pair(negative, positive, before, after, 'src/Capsule.cs')

    def test_api_pair_refuses_changed_library_body_and_scanner_codegen_disagreement(self):
        before = {'src/Capsule.cs': b'if (false) { // lsf-api-root-edge\nProbe();\n}', 'library.cs': b'original library'}
        after = dict(before); after['src/Capsule.cs'] = before['src/Capsule.cs'].replace(b'false', b'true')
        negative, positive = method_pair(before, after)
        api.dotnet_retention_pair(negative, positive, before, after, 'src/Capsule.cs')
        changed = dict(after, **{'library.cs': b'changed library'})
        with self.assertRaisesRegex(ValueError, 'only-root-edge'):
            api.dotnet_retention_pair(negative, positive, before, changed, 'src/Capsule.cs')
        _, disagreement = method_pair(before, after)
        # A valid pair of separately observed graphs may disagree. That must
        # fail the mandatory pair rather than becoming elimination evidence.
        disagreement['compiledMethods'] = copy.deepcopy(negative['compiledMethods'])
        from tools.dev_workflow.common import encode
        disagreement['identity'] = digest(encode({key: val for key, val in disagreement.items() if key != 'identity'}))
        with self.assertRaisesRegex(ValueError, 'actual-callee-retention'):
            api.dotnet_retention_pair(negative, disagreement, before, after, 'src/Capsule.cs')


if __name__ == '__main__': unittest.main()
