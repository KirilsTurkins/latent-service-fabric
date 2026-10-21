"""Bounded scanner format controls; XML fixtures are not compiler/guest proof."""
import copy
from pathlib import Path
import tempfile
import unittest

from tools.dev_workflow.common import digest, encode
from tools.dotnet_guest import reachability as r


def queries():
    return {'schemaVersion': 'lsf.dotnet.compiler-queries.v1', 'sourceRevision': r.SOURCE,
        'initializersExecuted': False, 'omittedMethods': 0, 'queries': [
            {'id': 'a' * 64, 'assemblyDigest': digest(b'assembly'), 'signatureDigest': digest(b'signature'),
             'symbol': 'Outside.Initializer..cctor', 'mangledName': 'Outside_Initializer___cctor',
             'kind': 'initialization', 'declaration': 'ordinary', 'rootAnchor': True},
            {'id': 'b' * 64, 'assemblyDigest': digest(b'assembly'), 'signatureDigest': digest(b'other'),
             'symbol': 'Outside.Worker.Callback', 'mangledName': 'Outside_Worker__Callback',
             'kind': 'method', 'declaration': 'ordinary', 'rootAnchor': False},
            {'id': 'c' * 64, 'assemblyDigest': digest(b'assembly'), 'signatureDigest': digest(b'generic'),
             'symbol': 'Outside.Generic.Callback', 'mangledName': None,
             'kind': 'method', 'declaration': 'ordinary', 'rootAnchor': False}]}


PROPERTIES = (b'<Properties><Property Id="Label" Label="Label" DataType="String"/>'
              b'<Property Id="Reason" Label="Reason" DataType="String"/></Properties>')
GRAPH = (b'<DirectedGraph xmlns="http://schemas.microsoft.com/vs/2009/dgml"><Nodes>'
         b'<Node Id="0" Label="Selected exports"/>'
         b'<Node Id="1" Label="Outside_Initializer___cctor"/>'
         b'</Nodes><Links><Link Source="0" Target="1" Reason="initializer"/></Links>'
         + PROPERTIES + b'</DirectedGraph>')


class ScannerMethods(unittest.TestCase):
    def test_actual_response_paths_select_only_original_captured_transitive_references(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); project = root / 'project'; (project / 'obj').mkdir(parents=True)
            assembly = project / 'obj/Entry.dll'; assembly.write_bytes(b'model managed input')
            graph = project / 'obj/Entry.scan.dgml.xml'; graph.write_bytes(GRAPH)
            cache = root / 'packages'; selected = cache / 'outside/1.0/lib.dll'; selected.parent.mkdir(parents=True)
            selected.write_bytes(b'model captured reference')
            platform = root / 'platform.dll'; platform.write_bytes(b'model platform reference')
            rsp = project / 'obj/Entry.rsp'
            raw = ('"' + str(assembly).replace('\\', '/') + '"\n--scandgmllog:"' + str(graph).replace('\\', '/')
                   + '"\n-r:"' + str(selected).replace('\\', '/') + '"\n-r:"'
                   + str(platform).replace('\\', '/') + '"\n').encode()
            rsp.write_bytes(raw)
            selection = {'originalPackages': [{'id': 'outside/1.0', 'targets': {'net10.0': {'runtime': {'lib.dll': {}}}}}]}
            self.assertEqual(r.response_inputs(project, cache, selection), (rsp, raw, graph, [assembly, selected]))
            # Neither a platform reference nor merely mentioned source text
            # becomes an application-query identity.
            self.assertEqual(r.response_inputs(project, cache, None)[3], [assembly])
            relative = raw.replace(str(assembly).replace('\\', '/').encode(), b'obj/Entry.dll')
            relative = relative.replace(str(graph).replace('\\', '/').encode(), b'obj/Entry.scan.dgml.xml')
            rsp.write_bytes(relative)
            self.assertEqual(r.response_inputs(project, cache, selection), (rsp, relative, graph, [assembly, selected]))
            outside = root / 'outside.scan.dgml.xml'; outside.write_bytes(GRAPH)
            rsp.write_bytes(raw.replace(str(graph).replace('\\', '/').encode(), str(outside).replace('\\', '/').encode()))
            with self.assertRaisesRegex(ValueError, 'scanner-location'): r.response_inputs(project, cache, selection)
            rsp.write_bytes(raw); (project / 'obj/duplicate.rsp').write_bytes(raw)
            with self.assertRaisesRegex(ValueError, 'response-selection'): r.response_inputs(project, cache, selection)

    def test_public_binding_preserves_unknown_and_rejects_rehashed_execution_or_stale_inputs(self):
        value = r.scanner(GRAPH, queries())
        value.update({name: digest(name.encode()) for name in ('responseDigest', 'metadataToolSourceDigest', 'metadataToolDigest')})
        identities = {name: digest(name.encode()) for name in ('source', 'component', 'compiler', 'recipe', 'graph')}
        bound = r.bind(value, **identities)
        for name in identities:
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'stale'):
                r.validate(bound, **{name: digest(b'changed')})
        changed = copy.deepcopy(bound); changed['runtimeExecution'] = 'executed'
        changed['identity'] = digest(encode({k: v for k, v in changed.items() if k != 'identity'}))
        with self.assertRaisesRegex(ValueError, 'cannot-certify'): r.validate(changed)

    def test_exact_compiler_label_presence_absence_and_unmapped_generic_stay_separate(self):
        value = r.scanner(GRAPH, queries())
        self.assertEqual([row['state'] for row in value['methods']], ['linked', 'not-retained', 'unknown'])
        self.assertTrue(all(row['apiClassification'] == 'unknown' for row in value['methods']))
        self.assertEqual((value['runtimeExecution'], value['initializersExecuted'], value['workerDrain']),
                         ('not-observed', False, 'unproven'))
        self.assertNotIn('unsupported-eliminated', encode(value).decode())

    def test_whole_graph_must_parse_after_matching_query_no_prefix_or_dangling_edge_proof(self):
        for raw in (GRAPH[:-1], GRAPH.replace(b'Target="1"', b'Target="99"'),
                    GRAPH.replace(PROPERTIES, b'<Unknown/>'),
                    GRAPH.replace(b'Id="1"', b'Id="0"')):
            with self.subTest(raw=raw[-80:]), self.assertRaises(ValueError): r.scanner(raw, queries())

    def test_names_are_exact_and_not_substrings_or_source_text_scans(self):
        with self.assertRaisesRegex(ValueError, 'root-mapping-anchor'):
            r.scanner(GRAPH.replace(b'Outside_Initializer___cctor', b'prefix_Outside_Initializer___cctor'), queries())
        changed = queries(); changed['queries'][1]['mangledName'] = changed['queries'][0]['mangledName']
        with self.assertRaisesRegex(ValueError, 'query-name'): r.scanner(GRAPH, changed)

    def test_missing_anchor_cannot_certify_whole_graph_absence_and_writer_shape_is_exact(self):
        changed = queries(); changed['queries'][0]['rootAnchor'] = False
        with self.assertRaisesRegex(ValueError, 'root-mapping-anchor'): r.scanner(GRAPH, changed)
        for raw in (GRAPH.replace(b'<DirectedGraph ', b'<DirectedGraph GraphDirection="LeftToRight" '),
                    GRAPH.replace(b'<Nodes>', b'<Nodes Style="unknown">'),
                    GRAPH.replace(PROPERTIES, b'<Categories/>'+PROPERTIES),
                    GRAPH.replace(b'DataType="String"', b'DataType="Unknown"'),
                    GRAPH.replace(PROPERTIES, b'<Properties/>'),
                    GRAPH.replace(b'</Links>', b'<Styles/></Links>')):
            with self.subTest(raw=raw[-180:]), self.assertRaises(ValueError): r.scanner(raw, queries())

    def test_exact_pinned_writer_source_vocabulary_is_covered_without_styles_or_categories(self):
        import re
        source = (Path(__file__).parent/'fixtures/nativeaot-dgml-writer-8449.cs').read_bytes()
        self.assertEqual(digest(source), 'sha256:6c7a69965b1d031a3584f652a732e9d405ef4a86d2570b99495792f71f6b33c8')
        self.assertEqual(set(re.findall(rb'WriteStartElement\("([A-Za-z]+)"', source)),
            {b'DirectedGraph', b'Nodes', b'Links', b'Properties', b'Property', b'Node', b'Link'})
        self.assertEqual(set(re.findall(rb'WriteAttributeString\("([A-Za-z]+)"', source)),
            {b'Id', b'Label', b'DataType', b'Source', b'Target', b'Reason', b'Stroke'})
        self.assertEqual(set(re.findall(rb'"Stroke", "(#[A-F0-9]+)"', source)),
                         {b'#FF0000', b'#00FF00', b'#0000FF'})
        self.assertEqual(r.scanner(GRAPH, queries())['mappingAnchorCount'], 1)

    def test_actual_pinned_writer_conditional_edges_and_closed_failure_projection(self):
        # Actual DgmlWriter.cs output with explicit dependency-interface model
        # seams. This is a writer/parser control, not ILC or guest evidence.
        raw = (Path(__file__).parent/'fixtures/nativeaot-dgml-conditional-8449.xml').read_bytes()
        self.assertEqual(digest(raw), 'sha256:c0f9a7609860fcd38048e6d618be5fd072b70825cca287652223b230bb41b248')
        value = r.scanner(raw, queries())
        self.assertEqual((value['nodesInspected'], value['linksInspected'], value['mappingAnchorCount']), (5, 5, 1))
        self.assertEqual([row['state'] for row in value['methods']], ['linked', 'not-retained', 'unknown'])
        for changed in (raw.replace(b'#00FF00', b'#123456'),
                        raw.replace(b'Reason="Primary"', b'Reason="unrecognized"'),
                        raw.replace(b'#0000FF', b'#0000ff')):
            with self.subTest(changed=changed[-200:]), self.assertRaisesRegex(ValueError, 'compiler-scanner-link-shape'):
                r.scanner(changed, queries())
        failure = r.unavailable(ValueError('compiler-scanner-link-shape'))
        self.assertEqual(failure['observerFailure'], 'compiler-scanner-link-shape')
        self.assertEqual(r.unavailable(failure), failure)
        for error in (ValueError('private/path/secret'), ValueError('compiler-scanner-link-shape', 'private'),
                      RuntimeError('compiler-scanner-link-shape'),
                      failure | {'authority': 'compiler'}, failure | {'reason': 'private'},
                      failure | {'status': 'passed'}, failure | {'schemaVersion': 'other'},
                      failure | {'extra': 'private'}, failure | {'observerFailure': 'private'}):
            with self.subTest(error=type(error).__name__):
                projected = r.unavailable(error)
                self.assertEqual(projected['observerFailure'], 'unknown')
                self.assertNotIn('private', encode(projected).decode())
        self.assertEqual(r.unavailable()['observerFailure'], 'unknown')

    def test_private_node_labels_and_xml_entities_are_never_public(self):
        raw = GRAPH.replace(b'Selected exports', b'C:/private/secret source')
        self.assertNotIn('private', encode(r.scanner(raw, queries())).decode())
        with self.assertRaises(ValueError): r.scanner(b'<!DOCTYPE x [<!ENTITY secret "private">]>' + raw, queries())
        with self.assertRaises(ValueError): r.scanner(b'x' * (r.MAX_GRAPH_BYTES + 1), queries())

    def test_source_or_metadata_query_tamper_is_not_accepted_as_compiler_evidence(self):
        for change in ({'sourceRevision': 'f' * 40}, {'initializersExecuted': True},
                       {'schemaVersion': 'unbound.v1'}):
            value = queries(); value.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError): r.scanner(GRAPH, value)
        value = queries(); value['queries'][0]['assemblyDigest'] = 'not-a-digest'
        with self.assertRaises(ValueError): r.scanner(GRAPH, value)


if __name__ == '__main__': unittest.main()
