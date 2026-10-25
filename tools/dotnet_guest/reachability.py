"""Bounded private NativeAOT scanner graph queries; no raw graph publication.

The pinned compiler creates scanner labels with NativeAotNameMangler. Query
labels are supplied by the passive exact-metadata tool, never substring/regex
guesses. Presence is compiler reachability, not runtime execution or API support.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
import re
import shlex
import xml.etree.ElementTree as XML

from tools.dev_workflow.common import digest, encode, integer, members, require, sha
from tools.rust_capsule_project import inventory, read_file, snapshot, write_json

SOURCE = '8449ba666dd991e495d8363d9852f18eb86a1aa1'
MAX_GRAPH_BYTES = 32 * 1024 * 1024
MAX_NODES = 131072
MAX_LINKS = 524288
MAX_PUBLIC_BYTES = 65536
NS = '{http://schemas.microsoft.com/vs/2009/dgml}'
FAILURE_CODES = frozenset({
    'compiler-method-managed-input', 'compiler-method-managed-input-count',
    'compiler-method-observer-input-changed', 'compiler-method-owned-tool-source',
    'compiler-method-response-bytes', 'compiler-method-response-count', 'compiler-method-response-selection',
    'compiler-method-scanner-count', 'compiler-method-scanner-location',
    'compiler-scanner-complete-graph', 'compiler-scanner-input-bound-or-declaration',
    'compiler-scanner-link-shape', 'compiler-scanner-malformed-xml', 'compiler-scanner-node-bound',
    'compiler-scanner-node-shape', 'compiler-scanner-property-shape', 'compiler-scanner-public-bound',
    'compiler-scanner-query-anchor', 'compiler-scanner-query-fields', 'compiler-scanner-query-id',
    'compiler-scanner-query-name', 'compiler-scanner-query-schema', 'compiler-scanner-root',
    'compiler-scanner-root-mapping-anchor-unavailable', 'compiler-scanner-section-order-or-attributes',
    'compiler-scanner-unexpected-text', 'compiler-scanner-unknown-element', 'compiler-scanner-work-bound',
    'compiler-scanner-xml-depth',
    'compiler-method-codegen-selection', 'compiler-method-codegen-location',
    'compiler-method-CoreLib-response-binding', 'compiler-method-reference-input-root',
})


def unavailable(value=None):
    """Project only inspected static refusal codes; never exception messages."""
    code = None
    if type(value) is ValueError and len(value.args) == 1:
        code = value.args[0]
    elif type(value) is dict and set(value) == {'schemaVersion', 'status', 'authority', 'reason', 'observerFailure'} \
            and value.get('schemaVersion') == 'lsf.guest.compatibility.failure.v1' \
            and value.get('status') == 'unavailable' and value.get('authority') == 'none':
        if value.get('reason') == 'compiler-method-observation-unavailable-or-stale':
            code = value.get('observerFailure')
    return {'schemaVersion': 'lsf.guest.compatibility.failure.v1', 'status': 'unavailable',
        'authority': 'none', 'reason': 'compiler-method-observation-unavailable-or-stale',
        'observerFailure': code if type(code) is str and code in FAILURE_CODES else 'unknown'}


def scanner(raw: bytes, queries: dict) -> dict:
    try:
        return _scanner(raw, queries)
    except XML.ParseError:
        raise ValueError('compiler-scanner-malformed-xml') from None


def _scanner(raw: bytes, queries: dict) -> dict:
    require(len(raw) <= MAX_GRAPH_BYTES and b'<!' not in raw and b'\0' not in raw,
            'compiler-scanner-input-bound-or-declaration')
    require(queries.get('schemaVersion') == 'lsf.dotnet.compiler-queries.v1'
            and queries.get('sourceRevision') == SOURCE and queries.get('initializersExecuted') is False
            and type(queries.get('queries')) is list and len(queries['queries']) <= 64,
            'compiler-scanner-query-schema')
    selected, seen_queries, names = {}, set(), set()
    for row in queries['queries']:
        require(type(row) is dict and set(row) == {'id', 'assemblyDigest', 'signatureDigest', 'symbol',
                'mangledName', 'kind', 'declaration', 'rootAnchor'}, 'compiler-scanner-query-fields')
        require(type(row['id']) is str and re.fullmatch('[0-9a-f]{64}', row['id']) is not None
                and row['id'] not in seen_queries, 'compiler-scanner-query-id')
        seen_queries.add(row['id']); sha(row['assemblyDigest']); sha(row['signatureDigest'])
        name = row['mangledName']
        require(name is None or (type(name) is str and re.fullmatch('[A-Za-z0-9_]{1,4096}', name) is not None
                and name not in names), 'compiler-scanner-query-name')
        if name is not None: names.add(name)
        require(type(row['rootAnchor']) is bool and (not row['rootAnchor'] or name is not None),
                'compiler-scanner-query-anchor')
        selected[row['id']] = False
    nodes, links, root, stack, sections, properties, count = set(), [], None, [], [], [], 0
    # Parse the WHOLE bounded graph. A prefix or truncated XML is never proof
    # of absence, even when all interesting names occur in that prefix.
    for event, item in XML.iterparse(io.BytesIO(raw), events=('start', 'end')):
        if event == 'start':
            stack.append(item.tag)
            require(len(stack) <= 4, 'compiler-scanner-xml-depth')
            if root is None:
                root = item.tag
                require(root == NS + 'DirectedGraph' and not item.attrib, 'compiler-scanner-root')
            elif len(stack) == 2:
                require(len(sections) < 3 and item.tag == NS + ('Nodes', 'Links', 'Properties')[len(sections)]
                        and not item.attrib, 'compiler-scanner-section-order-or-attributes')
                sections.append(item.tag)
            continue
        require((item.text is None or not item.text.strip()) and (item.tail is None or not item.tail.strip()),
                'compiler-scanner-unexpected-text')
        if item.tag == NS + 'Node':
            require(stack == [root, NS + 'Nodes', NS + 'Node'] and set(item.attrib) == {'Id', 'Label'},
                    'compiler-scanner-node-shape')
            identity, label = item.attrib['Id'], item.attrib['Label']
            require(identity not in nodes and re.fullmatch('[0-9]{1,10}', identity) is not None
                    and len(label) <= 16384 and len(nodes) < MAX_NODES, 'compiler-scanner-node-bound')
            nodes.add(identity)
            for row in queries['queries']:
                if row['mangledName'] is not None and row['mangledName'] == label:
                    selected[row['id']] = True
        elif item.tag == NS + 'Link':
            require(stack == [root, NS + 'Links', NS + 'Link']
                    and {'Source', 'Target'} <= item.attrib.keys()
                    and item.attrib.keys() <= {'Source', 'Target', 'Reason', 'Stroke'}
                    and ('Stroke' not in item.attrib or item.attrib['Stroke'] in {'#FF0000', '#0000FF'}
                        or item.attrib['Stroke'] == '#00FF00' and item.attrib.get('Reason') in {'Primary', 'Secondary'})
                    and len(item.attrib.get('Reason', '')) <= 16384
                    and len(links) < MAX_LINKS, 'compiler-scanner-link-shape')
            links.append((item.attrib['Source'], item.attrib['Target']))
        elif item.tag == NS + 'Property':
            require(stack == [root, NS + 'Properties', NS + 'Property'] and len(properties) < 2
                    and item.attrib == {'Id': ('Label', 'Reason')[len(properties)],
                        'Label': ('Label', 'Reason')[len(properties)], 'DataType': 'String'},
                    'compiler-scanner-property-shape')
            properties.append(item.attrib['Id'])
        elif item.tag not in {root, NS + 'Nodes', NS + 'Links', NS + 'Properties', NS + 'Property'}:
            raise ValueError('compiler-scanner-unknown-element')
        count += 1; require(count <= MAX_NODES + MAX_LINKS + 32, 'compiler-scanner-work-bound')
        item.clear(); stack.pop()
    require(root is not None and not stack and nodes and len(sections) == 3 and properties == ['Label', 'Reason']
            and all(a in nodes and b in nodes for a, b in links), 'compiler-scanner-complete-graph')
    anchors = sum(row['rootAnchor'] and selected[row['id']] for row in queries['queries'])
    require(anchors > 0, 'compiler-scanner-root-mapping-anchor-unavailable')
    methods = []
    for row in queries['queries']:
        symbol = row['symbol']
        safe = type(symbol) is str and re.fullmatch('[A-Za-z0-9_.]{1,192}', symbol) is not None
        methods.append({key: row[key] for key in ('id', 'assemblyDigest', 'signatureDigest', 'kind', 'declaration', 'rootAnchor')} | {
            'symbol': symbol if safe else 'method-' + row['id'], 'symbolRedacted': not safe,
            'state': 'unknown' if row['mangledName'] is None else 'linked' if selected[row['id']] else 'not-retained',
            'apiClassification': 'unknown'})
    result = {'schemaVersion': 'lsf.dotnet.compiler-methods.v1', 'compilerSource': SOURCE,
        'scannerDigest': digest(raw), 'queryDigest': digest(encode(queries)),
        'nodesInspected': len(nodes), 'linksInspected': len(links), 'methods': methods,
        'mappingAnchorCount': anchors, 'retentionScope': 'il-scanner-analysis-only',
        'omittedMethods': integer(queries['omittedMethods'], 0, 262144),
        'analysisCompleteness': 'selected-exact-nongeneric-method-queries',
        'rootScope': 'compiler-selected-entries-initializers-and-callbacks',
        'reflection': 'compiler-modeled-only', 'initializersExecuted': False,
        'runtimeExecution': 'not-observed', 'workerDrain': 'unproven', 'apiSupport': 'unknown', 'authority': 'none'}
    result['identity'] = digest(encode(result))
    require(len(encode(result)) <= MAX_PUBLIC_BYTES, 'compiler-scanner-public-bound')
    return result


def response_inputs(project: Path, package_cache: Path, selection: dict | None) -> tuple[Path, bytes, Path, list[Path]]:
    """Select actual ILC arguments and captured assets, never guessed symbols."""
    project = project.resolve(strict=True)

    def actual_path(value: str) -> Path:
        # The pinned MSBuild Exec runs in the project directory. Intermediate
        # ILC arguments can be relative to it, independent of this reader's cwd.
        path = Path(value)
        return (path if path.is_absolute() else project / path).resolve(strict=True)

    files = list((project / 'obj').rglob('*.rsp'))
    require(len(files) <= 64, 'compiler-method-response-count')
    matched, total = [], 0
    for path in files:
        raw = read_file(path, 1024 * 1024); total += len(raw)
        require(total <= 4 * 1024 * 1024, 'compiler-method-response-bytes')
        args = [value for line in raw.decode('utf-8-sig').splitlines() for value in shlex.split(line)]
        graphs = [value[len('--scandgmllog:'):] for value in args if value.startswith('--scandgmllog:')]
        if not graphs: continue
        require(len(graphs) == 1, 'compiler-method-scanner-count')
        graph = actual_path(graphs[0])
        require(graph.is_relative_to(project), 'compiler-method-scanner-location')
        roots = [actual_path(value) for value in args
                 if not value.startswith('-') and value.endswith('.dll')]
        require(len(roots) == 1 and roots[0].is_relative_to(project),
                'compiler-method-managed-input')
        allowed = set()
        if selection is not None:
            for package in selection['originalPackages']:
                for target in package['targets'].values():
                    for kind in ('compile', 'runtime', 'runtimeTargets'):
                        for name in target.get(kind, {}):
                            if name.endswith('.dll'):
                                allowed.add((package_cache / package['id'] / name).resolve(strict=True))
        references = [actual_path(value[3:]) for value in args if value.startswith('-r:')]
        assemblies = [roots[0], *(value for value in references if value in allowed)]
        require(len(assemblies) == len(set(assemblies)) and len(assemblies) <= 512,
                'compiler-method-managed-input-count')
        matched.append((path, raw, graph, assemblies))
    require(len(matched) == 1, 'compiler-method-response-selection')
    return matched[0]


def codegen_input(project: Path, response: bytes) -> Path:
    """The SAME actual ILC response selects its completed compilation graph."""
    require(type(response) is bytes and len(response) <= 1024 * 1024, 'compiler-method-response-bytes')
    args = [value for line in response.decode('utf-8-sig').splitlines() for value in shlex.split(line)]
    paths = [value[len('--dgmllog:'):] for value in args if value.startswith('--dgmllog:')]
    require(len(paths) == 1, 'compiler-method-codegen-selection')
    selected = Path(paths[0])
    selected = (selected if selected.is_absolute() else project / selected).resolve(strict=True)
    require(selected.is_relative_to(project.resolve(strict=True)), 'compiler-method-codegen-location')
    return selected


def compiled_methods(raw, queries):
    """Reuse the whole bounded pinned DGML grammar, not an absent-wrapper scan."""
    observed = scanner(raw, queries)
    value = {'schemaVersion': 'lsf.dotnet.compiled-methods.v1', 'graphDigest': observed['scannerDigest'],
        'queryDigest': observed['queryDigest'], 'nodesInspected': observed['nodesInspected'],
        'linksInspected': observed['linksInspected'], 'mappingAnchorCount': observed['mappingAnchorCount'],
        'methods': [{'id': row['id'], 'state': {'linked': 'codegen-node-observed',
            'not-retained': 'codegen-node-not-observed', 'unknown': 'unknown'}[row['state']]}
            for row in observed['methods']],
        'scope': 'completed-ILC-compilation-dependency-graph', 'apiElimination': 'not-established',
        'runtimeExecution': 'not-observed', 'authority': 'none'}
    value['identity'] = digest(encode(value))
    return value


def cil_inputs(compiler, project, response, application_assemblies):
    """Actual ILC references + original closed-port CoreLib, never a new resolver."""
    port = compiler.filesystem_port
    port.recheck()
    args = [value for line in response.decode('utf-8-sig').splitlines() for value in shlex.split(line)]
    references = []
    for value in args:
        if not value.startswith('-r:'): continue
        path = Path(value[3:])
        selected = (path if path.is_absolute() else project / path).resolve(strict=True)
        require(selected.is_relative_to(compiler.package_cache.resolve(strict=True))
                or selected.is_relative_to(project.parent.resolve(strict=True)) or selected in application_assemblies,
                'compiler-method-reference-input-root')
        references.append(selected)
    corelib = port.assembly.resolve(strict=True)
    require(references.count(corelib) == 1 and [path for path in references if path.name == 'System.Private.CoreLib.dll'] == [corelib],
            'compiler-method-CoreLib-response-binding')
    selected = list(dict.fromkeys([*application_assemblies, corelib, *references]))
    require(len(selected) <= 512, 'compiler-method-managed-input-count')
    require(digest(read_file(corelib, 8 * 1024 * 1024)) == port.identity['digest'],
            'compiler-method-CoreLib-response-binding')
    return selected, len(application_assemblies), port.identity['digest']


def cil_observation(value, corelib, methods):
    """Reduce actual passive CIL operands/selected forwarding; never execute IL."""
    members(value, {'schemaVersion', 'corelibDigest', 'scope', 'forwarding', 'indirectDispatch',
        'apiSupport', 'runtimeExecution', 'edges', 'apiBodies', 'unknownReferences', 'omittedEdges',
        'bodiesInspected', 'bodyBytesInspected'})
    require((value['schemaVersion'], value['corelibDigest'], value['scope'], value['forwarding'],
        value['indirectDispatch'], value['apiSupport'], value['runtimeExecution']) ==
        ('lsf.dotnet.cil-references.v1', sha(corelib), 'captured-input-call-operands',
        'exact-selected-ILC-assembly-identities', 'unknown', 'unknown', 'not-observed'),
        'compiler-cil-scope')
    for key, maximum in (('unknownReferences', 8 * 1024 * 1024), ('omittedEdges', 65536),
                         ('bodiesInspected', 262144), ('bodyBytesInspected', 8 * 1024 * 1024)):
        require(type(value[key]) is int and 0 <= value[key] <= maximum, 'compiler-cil-count')
    require(type(value['edges']) is list and len(value['edges']) <= 64
            and type(value['apiBodies']) is list and len(value['apiBodies']) <= 1, 'compiler-cil-row-limit')
    seen = set()
    for edge in value['edges']:
        members(edge, {'sourceId', 'bodyDigest', 'offset', 'operation', 'targetId',
                       'targetAssemblyDigest', 'targetSignatureDigest'})
        for key in ('sourceId', 'targetId'):
            require(type(edge[key]) is str and re.fullmatch('[0-9a-f]{64}', edge[key]), 'compiler-cil-method-id')
        for key in ('bodyDigest', 'targetAssemblyDigest', 'targetSignatureDigest'): sha(edge[key])
        require(type(edge['offset']) is int and 0 <= edge['offset'] < 262144
                and type(edge['operation']) is str and edge['operation'] in {'call', 'callvirt', 'newobj', 'ldftn', 'ldvirtftn'}
                and (edge['sourceId'], edge['offset']) not in seen, 'compiler-cil-operand')
        seen.add((edge['sourceId'], edge['offset']))
    for api in value['apiBodies']:
        members(api, {'api', 'id', 'assemblyDigest', 'signatureDigest', 'bodyDigest', 'metadataToken'})
        require(api['api'] == 'System.IO.Path.GetTempFileName' and api['assemblyDigest'] == corelib
                and api['signatureDigest'] == digest(bytes((0, 0, 14)))
                and type(api['metadataToken']) is int and 0x06000001 <= api['metadataToken'] <= 0x06ffffff
                and api['id'] == digest((corelib + ':' + str(api['metadataToken'])).encode())[7:],
                'compiler-cil-api-identity')
        sha(api['bodyDigest'])
        mapped = [row for row in methods if row['id'] == api['id']]
        require(not mapped or len(mapped) == 1 and mapped[0]['assemblyDigest'] == corelib
                and mapped[0]['signatureDigest'] == api['signatureDigest'], 'compiler-cil-api-query-identity')
    # Keep public 64KiB report limit unchanged. Metadata/graph counts retain
    # omissions rather than silently turning unretained operands into absence.
    reduced = {key: item for key, item in value.items() if key != 'edges'}
    reduced['edges'] = value['edges'][:16]
    reduced['omittedEdges'] += max(0, len(value['edges']) - 16)
    reduced['identity'] = digest(encode(reduced))
    return reduced


def collect(compiler, project: Path, output: Path, selection: dict | None) -> dict:
    """Observe successful normal ILC; the raw scanner graph stays temporary."""
    response, response_raw, graph, application_assemblies = response_inputs(project, compiler.package_cache, selection)
    assemblies, source_count, corelib_digest = cil_inputs(compiler, project, response_raw, application_assemblies)
    graph_raw = read_file(graph, MAX_GRAPH_BYTES)
    codegen = codegen_input(project, response_raw)
    codegen_raw = read_file(codegen, MAX_GRAPH_BYTES)
    before = [digest(read_file(path, 16 * 1024 * 1024)) for path in assemblies]
    source = compiler.sdk / 'tools/compiler-metadata'; original = snapshot(source)
    require(set(original) == {'CompilerMetadata.csproj', 'Program.cs', 'CilReferences.cs', 'LICENSE.MIT'}, 'compiler-method-owned-tool-source')
    # Paths, metadata query labels and the graph are private compiler inputs.
    # Here output is the compiler's existing private TemporaryDirectory, not
    # build()'s retained output. Its original scope owns helper/manifest cleanup.
    directory = output / 'compiler-method-observer'; directory.mkdir()
    for name, body in original.items(): (directory / name).write_bytes(body)
    config = directory / 'nuget.config'
    config.write_bytes(b'<configuration><packageSources><clear /></packageSources></configuration>\n')
    manifest = directory / 'assemblies.json'; write_json(manifest, [str(path) for path in assemblies])
    result = directory / 'methods.json'
    compiler.run('compiler-metadata-build', compiler.dotnet, 'build', directory / 'CompilerMetadata.csproj',
        '-c', 'Release', '--output', directory / 'bin', '--artifacts-path', directory / 'artifacts',
        '-p:RestoreConfigFile=' + str(config), '-p:NuGetAudit=false', '-p:UseAppHost=false', '-nodeReuse:false',
        '-p:UseSharedCompilation=false', '-p:ImportDirectoryBuildProps=false', '-p:ImportDirectoryBuildTargets=false')
    tool = directory / 'bin/CompilerMetadata.dll'; tool_bytes = read_file(tool, 4 * 1024 * 1024)
    compiler.run('compiler-metadata-read', compiler.dotnet, tool, manifest, result, corelib_digest, str(source_count))
    queries = json.loads(read_file(result, MAX_PUBLIC_BYTES))
    require(queries['assemblies'] == before and before == [digest(read_file(path, 16 * 1024 * 1024)) for path in assemblies]
            and read_file(response, 1024 * 1024) == response_raw and read_file(graph, MAX_GRAPH_BYTES) == graph_raw
            and read_file(codegen, MAX_GRAPH_BYTES) == codegen_raw
            and snapshot(source) == original and all(read_file(directory / name) == body for name, body in original.items())
            and read_file(tool, 4 * 1024 * 1024) == tool_bytes, 'compiler-method-observer-input-changed')
    value = scanner(graph_raw, queries)
    value['compiledMethods'] = compiled_methods(codegen_raw, queries)
    value['cilReferences'] = cil_observation(queries.get('cilReferences'), corelib_digest, value['methods'])
    value.update(responseDigest=digest(response_raw), metadataToolSourceDigest=digest(inventory(original)),
                 metadataToolDigest=digest(tool_bytes))
    return value


def validate(value: dict, *, source=None, component=None, compiler=None, recipe=None, graph=...):
    members(value, {'schemaVersion', 'compilerSource', 'scannerDigest', 'queryDigest', 'nodesInspected',
        'linksInspected', 'methods', 'omittedMethods', 'mappingAnchorCount', 'retentionScope', 'analysisCompleteness', 'rootScope', 'reflection',
        'initializersExecuted', 'runtimeExecution', 'workerDrain', 'apiSupport', 'authority', 'identity',
        'responseDigest', 'metadataToolSourceDigest', 'metadataToolDigest', 'sourceDigest', 'componentDigest',
        'compilerDigest', 'recipeDigest', 'graphDigest'}, {'compiledMethods', 'cilReferences'})
    require((value['schemaVersion'], value['compilerSource'], value['analysisCompleteness'],
        value['rootScope'], value['reflection'], value['runtimeExecution'], value['workerDrain'],
        value['apiSupport'], value['authority'], value['retentionScope']) == ('lsf.dotnet.compiler-methods.v1', SOURCE,
        'selected-exact-nongeneric-method-queries', 'compiler-selected-entries-initializers-and-callbacks',
        'compiler-modeled-only', 'not-observed', 'unproven', 'unknown', 'none', 'il-scanner-analysis-only')
        and value['initializersExecuted'] is False, 'compiler-method-cannot-certify-api-or-execution')
    for name in ('scannerDigest', 'queryDigest', 'responseDigest', 'metadataToolSourceDigest', 'metadataToolDigest',
                 'sourceDigest', 'componentDigest', 'compilerDigest', 'recipeDigest', 'identity'): sha(value[name])
    if value['graphDigest'] is not None: sha(value['graphDigest'])
    integer(value['nodesInspected'], 1, MAX_NODES); integer(value['linksInspected'], 0, MAX_LINKS)
    integer(value['omittedMethods'], 0, 262144)
    integer(value['mappingAnchorCount'], 1, 64)
    require(type(value['methods']) is list and len(value['methods']) <= 64, 'compiler-method-public-count')
    seen = set()
    for row in value['methods']:
        members(row, {'id', 'assemblyDigest', 'signatureDigest', 'kind', 'declaration', 'symbol',
            'symbolRedacted', 'state', 'apiClassification', 'rootAnchor'})
        require(type(row['id']) is str and re.fullmatch('[a-f0-9]{64}', row['id']) is not None
                and row['id'] not in seen, 'compiler-method-public-id')
        seen.add(row['id']); sha(row['assemblyDigest']); sha(row['signatureDigest'])
        require(row['kind'] in {'initialization', 'constructor', 'method'}
            and row['declaration'] in {'pinvoke', 'ordinary'} and row['state'] in {'linked', 'not-retained', 'unknown'}
            and row['apiClassification'] == 'unknown' and type(row['symbolRedacted']) is bool
            and type(row['rootAnchor']) is bool
            and type(row['symbol']) is str and re.fullmatch('[A-Za-z0-9_.-]{1,192}', row['symbol']) is not None,
            'compiler-method-public-row')
    require(value['mappingAnchorCount'] == sum(row['rootAnchor'] and row['state'] == 'linked'
            for row in value['methods']), 'compiler-method-root-mapping-anchor-count')
    if 'compiledMethods' in value:
        compiled = members(value['compiledMethods'], {'schemaVersion', 'graphDigest', 'queryDigest',
            'nodesInspected', 'linksInspected', 'mappingAnchorCount', 'methods', 'scope', 'apiElimination',
            'runtimeExecution', 'authority', 'identity'})
        require((compiled['schemaVersion'], compiled['scope'], compiled['apiElimination'],
            compiled['runtimeExecution'], compiled['authority']) == ('lsf.dotnet.compiled-methods.v1',
            'completed-ILC-compilation-dependency-graph', 'not-established', 'not-observed', 'none')
            and compiled['queryDigest'] == value['queryDigest'], 'compiler-method-codegen-scope')
        sha(compiled['graphDigest']); sha(compiled['identity'])
        integer(compiled['nodesInspected'], 1, MAX_NODES); integer(compiled['linksInspected'], 0, MAX_LINKS)
        integer(compiled['mappingAnchorCount'], 1, 64)
        require(type(compiled['methods']) is list and len(compiled['methods']) == len(value['methods']),
                'compiler-method-codegen-query-count')
        for actual, original in zip(compiled['methods'], value['methods']):
            members(actual, {'id', 'state'})
            require(actual['id'] == original['id'] and type(actual['state']) is str
                    and actual['state'] in {'codegen-node-observed', 'codegen-node-not-observed', 'unknown'}
                    and (original['state'] != 'unknown' or actual['state'] == 'unknown'),
                    'compiler-method-codegen-query-identity')
        require(compiled['mappingAnchorCount'] == sum(original['rootAnchor'] and actual['state'] == 'codegen-node-observed'
                for original, actual in zip(value['methods'], compiled['methods']))
            and compiled['identity'] == digest(encode({key: item for key, item in compiled.items() if key != 'identity'})),
            'compiler-method-codegen-identity')
    if 'cilReferences' in value:
        cil = value['cilReferences']
        members(cil, {'schemaVersion', 'corelibDigest', 'scope', 'forwarding', 'indirectDispatch', 'apiSupport',
            'runtimeExecution', 'edges', 'apiBodies', 'unknownReferences', 'omittedEdges', 'bodiesInspected',
            'bodyBytesInspected', 'identity'})
        require(type(cil['edges']) is list and len(cil['edges']) <= 16
                and cil_observation({key: item for key, item in cil.items() if key != 'identity'},
                    cil['corelibDigest'], value['methods']) == cil, 'compiler-cil-public-identity')
    require(len(encode(value)) <= MAX_PUBLIC_BYTES
            and value['identity'] == digest(encode({k: v for k, v in value.items() if k != 'identity'})),
            'compiler-method-public-identity-or-size')
    for expected, name in ((source, 'sourceDigest'), (component, 'componentDigest'),
                           (compiler, 'compilerDigest'), (recipe, 'recipeDigest')):
        if expected is not None: require(value[name] == expected, 'compiler-method-stale-' + name)
    if graph is not ...: require(value['graphDigest'] == graph, 'compiler-method-stale-graph')
    return value


def bind(value: dict, *, source: str, component: str, compiler: str, recipe: str, graph: str | None) -> dict:
    for identity in (source, component, compiler, recipe, graph):
        if identity is not None: sha(identity)
    value = {key: item for key, item in value.items() if key != 'identity'} | {
        'sourceDigest': source, 'componentDigest': component, 'compilerDigest': compiler,
        'recipeDigest': recipe, 'graphDigest': graph}
    value['identity'] = digest(encode(value))
    require(len(encode(value)) <= MAX_PUBLIC_BYTES, 'compiler-method-bound-report-size')
    return validate(value, source=source, component=component, compiler=compiler, recipe=recipe, graph=graph)
