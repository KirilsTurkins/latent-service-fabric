"""Finite oracle/source controls; modeled CLI rows are not guest qualification."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import compiler_compatibility_node as node
from tools import compiler_compatibility_observation as observation
from tools.phase2_operator_process import WorkflowError
from tools.phase3_resource_profile import ACTIVE_COUNTERS
from tools.rust_capsule_project import ROOT, digest, read_file


def revision():
    return {'releaseDigest': digest(b'model-selected-component'), 'revisionId': 'model-revision'}


def result(language='java', mode='init'):
    failed = mode.endswith('-trap')
    suffix = ('|finally=1' if language == 'java' else '|joined=1') if mode == 'callback' else ''
    expected = 'diagnostics|'+mode+'|init=1|ctor=1|denied='+('3' if mode == 'callback' else '2') \
        +'|fallback=42'+suffix+'|fresh=1'
    return {'exitCode': 4 if failed else 0, 'processReaped': True,
        'decoded': None if failed else [{'ok': expected}], 'response': {'outcomeKnown': True,
            'error': {'code': 'guest-trap'} if failed else None, 'data': {'resolvedRevision': revision(),
                'consumption': {'cpuFuel': '1000', 'peakMemoryBytes': '1048576',
                    **{key: '0' for key in node.ZERO}}}}}


class CompilerExecution(unittest.TestCase):
    def test_exact_signed_runtime_outputs_and_traps_cannot_be_replaced_by_graph_or_unknown(self):
        for language in ('java', 'dotnet'):
            for mode, _label in node.CASES:
                row = result(language, mode)
                node.invocation(row, revision(), revision()['releaseDigest'], language, mode)
                for key, value in (('processReaped', False), ('decoded', [{'ok': 'graph-linked'}])):
                    changed = copy.deepcopy(row); changed[key] = value
                    with self.subTest(language=language, mode=mode, key=key), self.assertRaises(WorkflowError):
                        node.invocation(changed, revision(), revision()['releaseDigest'], language, mode)
                changed = copy.deepcopy(row); changed['response']['outcomeKnown'] = False
                with self.assertRaises(WorkflowError): node.invocation(changed, revision(), revision()['releaseDigest'], language, mode)
                changed = copy.deepcopy(row); changed['response']['data']['resolvedRevision']['revisionId'] = 'other'
                with self.assertRaises(WorkflowError): node.invocation(changed, revision(), revision()['releaseDigest'], language, mode)

    def test_budget_effect_and_boolean_observations_remain_strict(self):
        for key, value in (('cpuFuel', '1000000001'), ('peakMemoryBytes', '67108865'),
            ('outboundRequests', '1'), ('logBytes', '1'), ('childCalls', True), ('effectCount', '-1')):
            row = result(); row['response']['data']['consumption'][key] = value
            with self.subTest(key=key), self.assertRaises(WorkflowError):
                node.invocation(row, revision(), revision()['releaseDigest'], 'java', 'init')

    def test_provider_usage_requires_actual_list_unavailable_and_all_eighteen_unsigned_zero_counters(self):
        # Use an authenticated durable actual nodeUsage object from #681; no
        # private cache or assumed schema. This is a reader control only.
        actual = json.loads(read_file(ROOT/'docs/testing/evidence/java-resource-late-signed-2026-10-21.json', 2*1024**2))
        def usages(value):
            if type(value) is dict:
                if value.get('scope') == 'node' and set(ACTIVE_COUNTERS) <= value.get('counters', {}).keys(): yield value
                for child in value.values(): yield from usages(child)
            elif type(value) is list:
                for child in value: yield from usages(child)
        value = next(usages(actual)); self.assertEqual(value['unavailable'], [])
        def check(selected):
            client = SimpleNamespace(call=lambda *_args, **_kwargs: {'data': {'nextPageToken': None, 'nodeUsage': selected}})
            return node.idle(client, {'name': 'model'})
        self.assertEqual(check(value), value)
        for unavailable in (False, None, {}, ['broker_calls']):
            changed = copy.deepcopy(value); changed['unavailable'] = unavailable
            with self.subTest(unavailable=unavailable), self.assertRaises(WorkflowError): check(changed)
        for key, wrong in (('scope', 'tenant'), ('counters', {})):
            changed = copy.deepcopy(value); changed[key] = wrong
            with self.assertRaises(WorkflowError): check(changed)
        for wrong in (True, -1, '18446744073709551616', '1'):
            changed = copy.deepcopy(value); changed['counters'][ACTIVE_COUNTERS[0]] = wrong
            with self.assertRaises(WorkflowError): check(changed)

    def test_first_real_result_survives_oracle_failure_without_a_success_receipt(self):
        row = result(); row['decoded'] = [{'ok': 'wrong'}]
        class Pending:
            owner = SimpleNamespace(finished=True)
            buffers = (bytearray(b'modeled-public-CLI-row'), bytearray())
            def close(self): pass
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with patch.object(node, 'selected_revision', return_value=revision()), \
                    patch.object(node, 'start_call', return_value=Pending()), \
                    patch.object(node, 'finish_call', return_value=row), self.assertRaises(WorkflowError):
                node.programme(None, None, None, output, revision()['releaseDigest'], 'java')
            saved = json.loads((output/'programme-progress.json').read_bytes())
            self.assertEqual(saved['status'], 'failed'); self.assertEqual(saved['cases'], [])
            self.assertEqual(saved['attempts'][0]['invocation'], row)
            self.assertFalse((output/'programme.json').exists())
            self.assertTrue((output/'process-diagnostics-java-init.json').exists())

    def test_each_six_case_success_is_followed_by_physical_and_provider_retirement(self):
        class Pending:
            owner = SimpleNamespace(finished=True); buffers = (bytearray(), bytearray())
            def close(self): pass
        for language in ('java', 'dotnet'):
            with self.subTest(language=language), tempfile.TemporaryDirectory() as directory, \
                    patch.object(node, 'selected_revision', return_value=revision()), \
                    patch.object(node, 'start_call', side_effect=lambda *_args, **_kw: Pending()), \
                    patch.object(node, 'finish_call', side_effect=[result(language, mode) for mode, _ in node.CASES]), \
                    patch.object(node, 'idle', return_value={'model': 'provider-zero'}) as idle, \
                    patch.object(node, 'sample', return_value={'model': 'physical-zero'}) as sample:
                value = node.programme(None, None, None, Path(directory), revision()['releaseDigest'], language)
                self.assertEqual(len(value['cases']), 6); self.assertEqual(idle.call_count, 6); self.assertEqual(sample.call_count, 6)
                self.assertFalse(value['workerDrainQualified']); self.assertEqual(value['genericTrapApiCause'], 'unknown')

    def test_dotnet_exact_scanner_rows_cannot_certify_api_support_or_another_assembly(self):
        assembly = digest(b'model-original-captured-CIL')
        states = {'OutsideDiagnosticsData.Core..cctor': 'linked', 'OutsideDiagnosticsData.Core..ctor': 'linked',
            'OutsideDiagnosticsData.Core.Fallback': 'linked', 'OutsideDiagnosticsData.Core.Uncaught': 'linked',
            'OutsideDiagnosticsData.Core.DeadUnsupported': 'not-retained', 'OutsideDiagnostics.Library..ctor': 'linked',
            'OutsideDiagnostics.Library.Run': 'linked', 'OutsideDiagnostics.Library.Callback': 'linked',
            'OutsideDiagnostics.Library.FailingCallback': 'linked'}
        value = {'mappingAnchorCount': 1, 'methods': [{'symbol': symbol, 'state': state,
            'assemblyDigest': assembly, 'apiClassification': 'unknown'} for symbol, state in states.items()]}
        capture = {'originalPackages': {'model': {'assembly': assembly}}}
        self.assertEqual(observation.dotnet_queries(value, capture)['deadWrapperApiSupport'], 'unknown')
        for key, wrong in (('assemblyDigest', digest(b'other')), ('state', 'unknown'), ('apiClassification', 'supported')):
            changed = copy.deepcopy(value); changed['methods'][0][key] = wrong
            with self.subTest(key=key), self.assertRaises(WorkflowError): observation.dotnet_queries(changed, capture)

    def test_canonical_attribution_requires_actual_fallback_and_concrete_java_counterfactual(self):
        from tools.qualify_compiler_compatibility import execution_report
        component = revision()['releaseDigest']; package = digest(b'model-library')
        before = {'component': {'sha256': component}, 'documents': {name: {'sha256': digest(name.encode())}
            for name in ('source-inputs.json', 'compiler-inputs.json', 'runtime-profile.json')}}
        before['compilerQueries'] = {'scope': 'completed-dependency-map-exact-method-only', 'methods': [{
            'packageDigest': package, 'symbol': 'outside.diagnosticsdata.Core.opaqueNative',
            'declaration': 'native', 'state': 'not-retained', 'apiClassification': 'unknown'}]}
        for language in ('java', 'dotnet'):
            rows = [{'mode': mode, 'label': label, 'invocation': result(language, mode)} for mode, label in node.CASES]
            observed = {'status': 'passed', 'programme': {'status': 'passed', 'cases': rows}}
            capture = {'originalJars': {node.fixture.JAVA_IDS[1]: {'digest': package}},
                'originalPackages': {node.fixture.DOTNET_IDS[1]: {'package': package}}}
            counterfactual = {'compilerFailureObserved': True, 'onlyRootEdgeAdded': True,
                'libraryBytesChanged': False, 'libraryOriginalDigest': package}
            report = execution_report(language, before, capture, observed, counterfactual)
            classes = [row['classification'] for row in report['findings']]
            self.assertEqual(classes.count('unsupported-reached'), 2)
            self.assertEqual(classes.count('unsupported-eliminated'), int(language == 'java'))
            self.assertEqual(classes.count('unresolved-behavior'), 2 if language == 'java' else 3)
            self.assertIn('lifecycle-unproven', classes)
            self.assertEqual(report['authority'], 'none')
            changed = copy.deepcopy(observed); changed['programme']['cases'][0]['invocation']['decoded'] = [{'ok': 'linked'}]
            with self.assertRaises(WorkflowError): execution_report(language, before, capture, changed, counterfactual)
            if language == 'java':
                for key, wrong in (('compilerFailureObserved', False), ('libraryBytesChanged', True)):
                    changed = {**counterfactual, key: wrong}
                    with self.assertRaises(WorkflowError): execution_report(language, before, capture, observed, changed)
                for changed in ({**before, 'compilerQueries': {}},
                        {**before, 'compilerQueries': {**before['compilerQueries'], 'methods': [{
                            **before['compilerQueries']['methods'][0], 'state': 'linked'}]}},
                        {**before, 'compilerQueries': {**before['compilerQueries'], 'methods': [{
                            **before['compilerQueries']['methods'][0], 'packageDigest': digest(b'other')} ]}}):
                    with self.assertRaises(WorkflowError): execution_report(language, changed, capture, observed, counterfactual)


if __name__ == '__main__': unittest.main()
