"""Bounded API implementation references on the ordinary six-owner path.

An identified implementation is not API qualification or library eligibility.
Compiler facts, installed providers, grants, execution and retirement remain
separate. Historical/unmapped inputs stay unknown, never safe or unsupported.
"""
from __future__ import annotations

from pathlib import Path

from tools import guest_compatibility as compatibility
from tools import guest_compatibility_context as context
from tools import guest_emitted_code
from tools.dev_workflow.common import decode, digest, encode, members, require, sha
from tools.rust_capsule_project import canonical, read_file, write_json

SCHEMA = 'lsf.guest.api-analysis.v1'
NAME = 'compatibility-api-analysis.json'
MAX_BYTES, MAX_APIS = 65536, 64
OWNERS = {'c': 744, 'rust': 743, 'go': 742, 'java': 741, 'dotnet': 746, 'typescript': 745}
# Fixed STANDARD API keys refer to original compiler-owned material names.
# They are neither application package names nor an admission allowlist.
RULES = {
    'c': (
        ('c.fopen.valid-mode', ('c-closed-filesystem-libc-0', 'c-closed-filesystem-libc-1', 'c-closed-filesystem-stdio-v1'), None),
        ('c.tmpfile', ('c-closed-filesystem-stdio-v1',), None)),
    'rust': (
        ('rust.std.io.stdout', ('rust-standard-runtime', 'selected-standard-runtime'), None),
        ('rust.std.fs.File.open', ('rust-compiler-inputs', 'selected-standard-runtime'), None),
        ('rust.std.thread.Builder.spawn', ('rust-compiler-inputs', 'selected-standard-runtime'), None)),
    'go': (
        ('go.runtime.goroutine', ('go-runtime-transformations', 'selected-standard-runtime'),
            tuple('go-component-activation-v' + str(n) for n in range(1, 8))),
        ('go.time.Timer', ('go-runtime-transformations', 'selected-standard-runtime'),
            tuple('go-component-activation-v' + str(n) for n in range(3, 8))),
        ('go.os.Open', ('go-runtime-transformations', 'selected-standard-runtime'), None)),
    'java': (
        ('java.io.File.valid-path', ('generated-bindings',), None),),
    'dotnet': (
        ('dotnet.System.IO.File.Open.valid-arguments', ('dotnet-closed-filesystem-v1',), None),
        ('dotnet.System.IO.Path.GetTempFileName', ('dotnet-closed-filesystem-v1',), None)),
    'typescript': (
        ('javascript.Promise.then', ('selected-standard-runtime', 'selected-runtime-original'),
            ('spidermonkey-activation-promises-v1', 'spidermonkey-activation-promises-clocks-v1',
             'spidermonkey-activation-promises-clocks-imports-v1')),
        ('javascript.setTimeout', ('selected-standard-runtime', 'selected-runtime-original'),
            ('spidermonkey-activation-promises-clocks-v1', 'spidermonkey-activation-promises-clocks-imports-v1')),
        ('node.Buffer', (*context.BUFFER_MATERIALS,), None),
        ('node.net.Socket', (*context.NET_MATERIALS,), None)),
}
COMPILER_FILES = {
    'compiler-call-edges': ('compatibility-compiler-edges.json', 65536),
    'compiler-method-reachability': ('compatibility-compiler-methods.json', 65536),
}
OWNER_FILES = {
    'go-runtime-transformations': ('go-runtime-transformations.json', 4 * 1024 * 1024),
    'rust-compiler-inputs': ('rust-compiler-inputs.json', 8 * 1024 * 1024),
    'rust-standard-runtime': ('rust-standard-runtime.json', 4 * 1024 * 1024),
}


def material(value, name):
    rows = [row for row in value['materials'] if row['name'] == name]
    require(len(rows) <= 1, 'api-analysis-ambiguous-material')
    return rows[0] if rows else None


def original_materials(raw, report):
    """Independent normal owner's actual record, not the projected context."""
    value = decode(raw, 1024 * 1024)
    require(type(value) is dict and value.get('formatVersion') == 1
            and value.get('componentDigest') == report['componentDigest']
            and type(value.get('source')) is dict and value['source'].get('snapshotDigest') == report['sourceDigest']
            and type(value.get('materials')) is list and len(value['materials']) <= 64,
            'api-analysis-original-build-owner')
    rows = {}
    for row in value['materials']:
        members(row, {'name', 'digest', 'size'})
        compatibility.token(row['name']); sha(row['digest'])
        require(row['name'] not in rows and type(row['size']) is int and 0 <= row['size'] < 2**64,
                'api-analysis-original-material')
        rows[row['name']] = row
    return rows


def validate_compiler_findings(value):
    members(value, {'rows', 'omitted'})
    require(type(value['rows']) is list and len(value['rows']) <= 64
            and type(value['omitted']) is int and 0 <= value['omitted'] <= 96, 'api-analysis-finding-bound')
    seen = set()
    for row in value['rows']:
        require(type(row) is dict and type(row.get('kind')) is str
                and row['kind'] in {'compiler-call-edge', 'compiler-method'}, 'api-analysis-finding-kind')
        common = {'kind', 'queryIdentity', 'state', 'scope', 'observationIdentity',
                  'apiReachability', 'apiBehavior', 'execution'}
        require((row.get('apiReachability'), row.get('apiBehavior'), row.get('execution')) ==
                ('unknown', 'unqualified', 'not-observed'), 'api-analysis-finding-not-runtime-proof')
        identity = row['queryIdentity']
        require(type(identity) is str and len(identity) == 64 and all(c in '0123456789abcdef' for c in identity)
                and (row['kind'], identity) not in seen, 'api-analysis-finding-identity')
        seen.add((row['kind'], identity))
        if row['observationIdentity'] is not None: sha(row['observationIdentity'])
        if row['kind'] == 'compiler-call-edge':
            members(row, common | {'sourceIdentity', 'rootIdentity', 'targetIdentity', 'rootMapping'})
            for key in ('sourceIdentity', 'rootIdentity', 'targetIdentity'): sha(row[key])
            require(type(row['state']) is str and row['state'] in
                    {'observed-direct-edge', 'edge-not-observed', 'unknown'}
                    and row['scope'] == 'exact-selected-compiler-call-edge', 'api-analysis-finding-edge')
            root = members(row['rootMapping'], {'state', 'phases', 'scope', 'apiElimination'})
            require(type(root['state']) is str and root['state'] in {'unmapped-or-ambiguous',
                'potential-root-path', 'closed-core-no-root-path', 'dynamic-unknown'}
                and type(root['phases']) is list
                and all(type(phase) is str and phase in {'invocation', 'initialization', 'callbacks'} for phase in root['phases'])
                and root['phases'] == sorted(set(root['phases']))
                and bool(root['phases']) == (root['state'] == 'potential-root-path')
                and root['scope'] == 'exact-emitted-name-conservative-core-roots'
                and root['apiElimination'] == 'not-established', 'api-analysis-finding-root')
        else:
            members(row, common | {'standardApi', 'implementationDigest', 'bodyDigest', 'inputOperands',
                'unresolvedInputReferences', 'omittedInputOperands'})
            require(type(row['state']) is str and row['state'] in {'unknown', 'dependency-method-retained',
                'dependency-method-not-retained', 'scanner-and-codegen-retained', 'scanner-and-codegen-not-retained'}
                and row['scope'] == 'exact-selected-method-retention', 'api-analysis-finding-method')
            require(type(row['inputOperands']) is list
                and all(type(item) is str and item in {'call', 'callvirt', 'newobj', 'ldftn', 'ldvirtftn'}
                        for item in row['inputOperands'])
                and row['inputOperands'] == sorted(set(row['inputOperands'])), 'api-analysis-finding-operands')
            if row['standardApi'] is None:
                require(all(row[key] is None for key in ('implementationDigest', 'bodyDigest',
                    'unresolvedInputReferences', 'omittedInputOperands')) and row['inputOperands'] == [],
                    'api-analysis-finding-unmapped-api')
            else:
                require(row['standardApi'] == 'dotnet.System.IO.Path.GetTempFileName', 'api-analysis-finding-api')
                for key in ('implementationDigest', 'bodyDigest'): sha(row[key])
                for key, maximum in (('unresolvedInputReferences', 8 * 1024 * 1024), ('omittedInputOperands', 65536)):
                    require(type(row[key]) is int and 0 <= row[key] <= maximum, 'api-analysis-finding-reference-count')
    return value


def emitted_root_join(component, symbols):
    """Exact emitted identities only; never suffix/demangled-name guessing.

    Core exports conservatively include component adapters. A known direct
    path is therefore only a potential path, and absence cannot eliminate an
    API. Missing/duplicate labels and dynamic dispatch remain explicit.
    """
    names = set(symbols)
    require(len(names) <= 64 and all(type(name) is str for name in names), 'api-analysis-root-query-bound')
    found = {name: [] for name in names}
    if len(component) <= guest_emitted_code.MAX_ANALYSIS_BYTES:
        try:
            modules = guest_emitted_code.graphs(component, guest_emitted_code.Budget())
            for ordinal, module in enumerate(modules):
                for index, label in module['labels'].items():
                    if label in found:
                        found[label].append((ordinal, index, module))
        except guest_emitted_code.UnknownEncoding:
            found = {name: [] for name in names}
    result = {}
    for name, matches in found.items():
        phases, state = [], 'unmapped-or-ambiguous'
        if len(matches) == 1:
            _, index, module = matches[0]
            phases = sorted(module['reachable'].get(index, ()))
            state = 'potential-root-path' if phases else 'closed-core-no-root-path' if module['closed'] else 'dynamic-unknown'
        result[name] = {'state': state, 'phases': phases,
            'scope': 'exact-emitted-name-conservative-core-roots', 'apiElimination': 'not-established'}
    return result


def compiler_findings(records, component):
    """Join actual owner facts, without turning names or CIL into execution.

    In particular a virtual CIL operand denotes a declaration, not its runtime
    implementation. A codegen omission is exact method retention only, even
    when the scanner agrees: inlining/reflection/API behavior stay separate.
    """
    rows = []
    call_edges = records.get('compiler-call-edges')
    if call_edges is not None:
        def emitted_name(query):
            return query['emittedRoot']['symbol'] if query.get('emittedRoot') is not None else query['root']
        roots = emitted_root_join(component, [emitted_name(query) for query in call_edges['queries']])
        for query in call_edges['queries']:
            observed = query.get('observation')
            rows.append({'kind': 'compiler-call-edge', 'queryIdentity': query['id'],
                'sourceIdentity': query['sourceIdentity'], 'rootIdentity': digest(query['root'].encode()),
                'targetIdentity': digest(query['compilerTarget'].encode()),
                'state': observed['state'] if observed is not None else 'unknown',
                'observationIdentity': observed['identity'] if observed is not None else None,
                'rootMapping': roots[emitted_name(query)], 'scope': 'exact-selected-compiler-call-edge',
                'apiReachability': 'unknown', 'apiBehavior': 'unqualified', 'execution': 'not-observed'})
    methods = records.get('compiler-method-reachability')
    if methods is not None:
        compiled = {row['id']: row['state'] for row in methods.get('compiledMethods', {}).get('methods', [])}
        cil = methods.get('cilReferences')
        api_ids = {row['id']: row for row in cil['apiBodies']} if cil is not None else {}
        for method in methods['methods']:
            if len(rows) == 64: break
            state = 'unknown'
            if 'compiledMethods' not in methods:
                state = 'dependency-method-retained' if method['state'] == 'linked' else \
                    'dependency-method-not-retained' if method['state'] == 'not-retained' else 'unknown'
            elif method['state'] == 'linked' and compiled.get(method['id']) == 'codegen-node-observed':
                state = 'scanner-and-codegen-retained'
            elif method['state'] == 'not-retained' and compiled.get(method['id']) == 'codegen-node-not-observed':
                state = 'scanner-and-codegen-not-retained'
            api = api_ids.get(method['id'])
            references = [edge for edge in cil['edges'] if edge['targetId'] == method['id']] if api is not None else []
            rows.append({'kind': 'compiler-method', 'queryIdentity': method['id'],
                'state': state, 'scope': 'exact-selected-method-retention',
                'observationIdentity': methods['identity'],
                'standardApi': 'dotnet.' + api['api'] if api is not None else None,
                'implementationDigest': api['assemblyDigest'] if api is not None else None,
                'bodyDigest': api['bodyDigest'] if api is not None else None,
                'inputOperands': sorted(set(edge['operation'] for edge in references)),
                'unresolvedInputReferences': cil['unknownReferences'] if api is not None else None,
                'omittedInputOperands': cil['omittedEdges'] if api is not None else None,
                'apiReachability': 'unknown', 'apiBehavior': 'unqualified', 'execution': 'not-observed'})
    total = (len(call_edges['queries']) if call_edges is not None else 0) + \
        (len(methods['methods']) if methods is not None else 0)
    return {'rows': rows, 'omitted': total - len(rows)}


def dotnet_retention_pair(negative, positive, before, after, root_path):
    """Actual fixed API-callee differential, not absence of a wrapper name.

    Both complete original ILC graphs and the selected CoreLib/CIL identities
    are mandatory. The positive method-group operand makes this exact API
    addressable. This finite pair says nothing about arbitrary reflection,
    other overloads, other libraries, runtime safety or physical retirement.
    """
    from tools.dotnet_guest import reachability
    from tools.rust_capsule_project import inventory
    for value in (negative, positive): reachability.validate(value)
    require(all(negative[key] == positive[key] for key in
        ('compilerDigest', 'recipeDigest', 'graphDigest'))
        and negative['componentDigest'] != positive['componentDigest'], 'api-analysis-dotnet-pair-owner')
    require(type(before) is dict and type(after) is dict and set(before) == set(after)
        and len(before) <= 32768 and root_path in before and type(root_path) is str
        and all(type(raw) is bytes for raw in (*before.values(), *after.values())), 'api-analysis-dotnet-pair-inputs')
    old, new = b'if (false) { // lsf-api-root-edge', b'if (true) { // lsf-api-root-edge'
    require(len(before[root_path]) <= 4 * 1024 * 1024 and before[root_path].count(old) == 1
        and after[root_path] == before[root_path].replace(old, new, 1)
        and all(before[path] == after[path] for path in before if path != root_path)
        and negative['sourceDigest'] == digest(inventory(before))
        and positive['sourceDigest'] == digest(inventory(after)), 'api-analysis-dotnet-pair-only-root-edge')
    left, right = negative.get('cilReferences'), positive.get('cilReferences')
    require(left is not None and right is not None and left['apiBodies'] == right['apiBodies']
        and len(left['apiBodies']) == 1 and left['corelibDigest'] == right['corelibDigest'],
        'api-analysis-dotnet-pair-actual-api-body')
    api = right['apiBodies'][0]
    def retained(value, identity, expected):
        methods = [row for row in value['methods'] if row['id'] == identity]
        codegen = [row for row in value.get('compiledMethods', {}).get('methods', []) if row['id'] == identity]
        return len(methods) == len(codegen) == 1 and methods[0]['state'] == (
            'linked' if expected else 'not-retained') and codegen[0]['state'] == (
            'codegen-node-observed' if expected else 'codegen-node-not-observed')
    require(retained(negative, api['id'], False) and retained(positive, api['id'], True),
        'api-analysis-dotnet-pair-actual-callee-retention')
    refs = [edge for edge in right['edges'] if edge['targetId'] == api['id'] and edge['operation'] == 'ldftn'
        and edge['targetAssemblyDigest'] == api['assemblyDigest']
        and edge['targetSignatureDigest'] == api['signatureDigest']]
    require(len(refs) == 1 and refs[0] in left['edges']
        and retained(negative, refs[0]['sourceId'], False) and retained(positive, refs[0]['sourceId'], True),
        'api-analysis-dotnet-pair-addressable-input-source')
    value = {'schemaVersion': 'lsf.dotnet.api-retention-pair.v1', 'api': 'dotnet.' + api['api'],
        'scope': 'one-controlled-api-callee-retention-differential',
        'negativeObservation': negative['identity'], 'positiveObservation': positive['identity'],
        'sourceBefore': negative['sourceDigest'], 'sourceAfter': positive['sourceDigest'],
        'graphDigest': positive['graphDigest'], 'compilerDigest': positive['compilerDigest'],
        'recipeDigest': positive['recipeDigest'], 'corelibDigest': api['assemblyDigest'],
        'apiMethodIdentity': api['id'], 'apiBodyDigest': api['bodyDigest'],
        'inputMethodIdentity': refs[0]['sourceId'], 'inputBodyDigest': refs[0]['bodyDigest'],
        'libraryInputsUnchanged': True, 'apiGlobalElimination': 'unknown',
        'runtimeExecution': 'not-observed', 'physicalRetirement': 'unproven', 'authority': 'none'}
    value['identity'] = digest(encode(value))
    return value


def create(report, selected, emitted, *, build_observation, component, compiler_records=None, owner_records=None):
    compatibility.validate(report); context.validate(selected, report=report)
    original_materials(build_observation, report)
    runtime = selected['standardRuntime'].get('profile', 'not-observed')
    recipe = material(selected, 'build-recipe')
    recipe_digest = recipe['digest'] if recipe is not None else None
    guest_emitted_code.validate(emitted, source=report['sourceDigest'], component=report['componentDigest'],
        runtime=runtime, host=report['runtimeProfile'], recipe=recipe_digest)
    compiler_records = {} if compiler_records is None else compiler_records
    owner_records = {} if owner_records is None else owner_records
    require(type(compiler_records) is dict and set(compiler_records) <= COMPILER_FILES.keys(), 'api-analysis-compiler-records')
    require(type(owner_records) is dict and set(owner_records) <= {'java-closed-filesystem'}, 'api-analysis-owner-records')
    require(type(component) is bytes and digest(component) == report['componentDigest'], 'api-analysis-detached-final-component')
    compiler = []
    for name, observed in sorted(compiler_records.items()):
        bound = material(selected, name)
        require(bound is not None and type(observed) is dict and observed.get('sourceDigest') == report['sourceDigest']
                and observed.get('componentDigest') == report['componentDigest']
                and observed.get('recipeDigest') == recipe_digest, 'api-analysis-detached-compiler-record')
        if selected['language'] == 'dotnet' and 'cilReferences' in observed:
            port = material(selected, 'dotnet-closed-filesystem-v1')
            require(port is not None and observed['cilReferences']['corelibDigest'] == port['digest'],
                    'api-analysis-detached-CoreLib')
        compiler.append({'name': name, 'materialDigest': bound['digest'],
                         'observationIdentity': sha(observed['identity'])})
    rows = []
    for api, names, profiles in RULES[selected['language']]:
        refs = [material(selected, name) for name in names]
        if selected['language'] == 'rust':
            prepared = material(selected, 'rust-standard-runtime')
            if prepared is not None and all(ref is None or ref['name'] != prepared['name'] for ref in refs):
                refs.append(prepared)
        identified = bool(names) and all(row is not None for row in refs) and recipe is not None
        if profiles is not None and runtime not in profiles: identified = False
        if selected['language'] == 'java' and 'java-closed-filesystem' not in owner_records: identified = False
        if api == 'node.Buffer' and context.buffer_module(selected) is None: identified = False
        if api == 'node.net.Socket' and context.net_module(selected) is None: identified = False
        # Complete metadata/reference binding identifies selected inputs only;
        # it never turns a material's NAME into implementation qualification.
        rows.append({'api': api, 'state': 'selected-implementation-unqualified' if identified else 'implementation-unmapped',
            'implementationMaterials': refs if identified else [], 'ownerIssue': OWNERS[selected['language']],
            'runtimeProfile': runtime, 'hostAbiProfile': report['runtimeProfile'],
            'recipeDigest': recipe_digest, 'sourceDigest': report['sourceDigest'], 'componentDigest': report['componentDigest'],
            'apiReachability': 'unknown', 'apiBehavior': 'unqualified', 'initializationExecution': 'not-observed',
            'physicalRetirement': 'unproven', 'authority': 'none'})
    value = {'schemaVersion': SCHEMA, 'language': selected['language'],
        'state': 'observed',
        'sourceDigest': report['sourceDigest'], 'componentDigest': report['componentDigest'],
        'reportIdentity': report['identity'], 'contextIdentity': selected['identity'],
        'buildObservationDigest': digest(build_observation),
        'recipeDigest': recipe_digest, 'hostAbiProfile': report['runtimeProfile'], 'runtimeProfile': runtime,
        'rootObservationIdentity': emitted['identity'], 'rootScope': emitted['rootScope'],
        'selectedExportMapping': emitted['selectedExportMapping'], 'rootAnalysisReasons': emitted['analysisReasons'],
        'omittedRootFindings': emitted['omittedFindings'], 'compilerObservations': compiler,
        'ownerObservations': {name: digest(encode(row)) for name, row in sorted(owner_records.items())},
        'compilerFindings': compiler_findings(compiler_records, component),
        'apis': rows, 'omittedApis': 0, 'uncataloguedApis': 'unknown', 'libraryEligibility': 'not-evaluated',
        'providerInstallation': 'not-evaluated', 'grants': 'not-evaluated', 'authority': 'none'}
    require(len(rows) <= MAX_APIS, 'api-analysis-row-limit')
    value['identity'] = digest(encode(value))
    require(len(encode(value)) <= MAX_BYTES, 'api-analysis-byte-limit')
    return validate(value)


def unavailable(report, selected):
    compatibility.validate(report); context.validate(selected, report=report)
    value = {'schemaVersion': SCHEMA, 'state': 'unavailable', 'language': report['language'],
        'sourceDigest': report['sourceDigest'], 'componentDigest': report['componentDigest'],
        'reportIdentity': report['identity'], 'contextIdentity': selected['identity'],
        'reason': 'bound-analysis-input-unavailable-or-stale', 'libraryEligibility': 'not-evaluated', 'authority': 'none'}
    value['identity'] = digest(encode(value))
    return value


def validate(value):
    require(type(value) is dict and value.get('schemaVersion') == SCHEMA
            and type(value.get('state')) is str and value['state'] in {'observed', 'unavailable'},
            'api-analysis-schema-or-state')
    basic = {'schemaVersion', 'state', 'language', 'sourceDigest', 'componentDigest', 'reportIdentity',
             'contextIdentity', 'libraryEligibility', 'authority', 'identity'}
    if value['state'] == 'unavailable':
        members(value, basic | {'reason'})
        require(value['reason'] == 'bound-analysis-input-unavailable-or-stale', 'api-analysis-unavailable-reason')
    else:
        members(value, basic | {'buildObservationDigest', 'recipeDigest', 'hostAbiProfile', 'runtimeProfile', 'rootObservationIdentity',
            'rootScope', 'selectedExportMapping', 'rootAnalysisReasons', 'omittedRootFindings', 'compilerObservations',
            'ownerObservations', 'compilerFindings', 'apis', 'omittedApis', 'uncataloguedApis', 'providerInstallation', 'grants'})
        require(value['uncataloguedApis'] == 'unknown' and value['providerInstallation'] == value['grants'] == 'not-evaluated'
                and value['rootScope'] == 'all-core-exports-starts-addressable-callbacks'
                and value['selectedExportMapping'] == 'conservative-superset', 'api-analysis-scope')
        for key in ('hostAbiProfile', 'runtimeProfile'): compatibility.token(value[key])
        if value['recipeDigest'] is not None: sha(value['recipeDigest'])
        sha(value['rootObservationIdentity'])
        sha(value['buildObservationDigest'])
        require(type(value['rootAnalysisReasons']) is list and len(value['rootAnalysisReasons']) <= len(guest_emitted_code.REASONS)
                and all(type(item) is str and item in guest_emitted_code.REASONS for item in value['rootAnalysisReasons']),
                'api-analysis-root-reasons')
        require(type(value['omittedRootFindings']) is int and 0 <= value['omittedRootFindings'] <= 2**64 - 1
                and value['omittedApis'] == 0 and type(value['omittedApis']) is int, 'api-analysis-omissions')
        require(type(value['compilerObservations']) is list and len(value['compilerObservations']) <= 2,
                'api-analysis-compiler-count')
        for row in value['compilerObservations']:
            members(row, {'name', 'materialDigest', 'observationIdentity'})
            require(type(row['name']) is str and row['name'] in COMPILER_FILES, 'api-analysis-compiler-name')
            sha(row['materialDigest']); sha(row['observationIdentity'])
        require(type(value['ownerObservations']) is dict and set(value['ownerObservations']) <= {'java-closed-filesystem'},
                'api-analysis-owner-observations')
        for identity in value['ownerObservations'].values(): sha(identity)
        validate_compiler_findings(value['compilerFindings'])
        require(type(value['language']) is str and value['language'] in RULES and type(value['apis']) is list
                and [row.get('api') if type(row) is dict else None for row in value['apis']] ==
                    [api for api, _, _ in RULES[value['language']]], 'api-analysis-api-keys')
        for row in value['apis']:
            members(row, {'api', 'state', 'implementationMaterials', 'ownerIssue', 'runtimeProfile', 'hostAbiProfile',
                'recipeDigest', 'sourceDigest', 'componentDigest', 'apiReachability', 'apiBehavior',
                'initializationExecution', 'physicalRetirement', 'authority'})
            require(type(row['state']) is str and row['state'] in {'implementation-unmapped', 'selected-implementation-unqualified'}
                    and (row['apiReachability'], row['apiBehavior'], row['initializationExecution'], row['physicalRetirement'],
                        row['authority']) == ('unknown', 'unqualified', 'not-observed', 'unproven', 'none')
                    and row['ownerIssue'] == OWNERS[value['language']], 'api-analysis-api-cannot-certify-behavior')
            require(type(row['implementationMaterials']) is list and len(row['implementationMaterials']) <= 8
                    and bool(row['implementationMaterials']) == (row['state'] == 'selected-implementation-unqualified'),
                    'api-analysis-api-materials')
            for ref in row['implementationMaterials']: context.validate_material(ref)
            require(all(row[key] == value[key] for key in
                ('runtimeProfile', 'hostAbiProfile', 'recipeDigest', 'sourceDigest', 'componentDigest')), 'api-analysis-api-binding')
    require(type(value['language']) is str and value['language'] in RULES
            and value['libraryEligibility'] == 'not-evaluated' and value['authority'] == 'none', 'api-analysis-language-or-authority')
    for key in ('sourceDigest', 'componentDigest', 'reportIdentity', 'contextIdentity', 'identity'): sha(value[key])
    require(len(encode(value)) <= MAX_BYTES
            and value['identity'] == digest(encode({key: item for key, item in value.items() if key != 'identity'})),
            'api-analysis-identity')
    return value


def inputs(output: Path, report, selected):
    """Only fixed, already-bound output names; no path from a report is run/read."""
    context.validate(selected, report=report)
    runtime = selected['standardRuntime'].get('profile', 'not-observed')
    recipe = material(selected, 'build-recipe')
    build_raw = read_file(output / 'build-observation.json', 1024 * 1024)
    originals = original_materials(build_raw, report)
    def original(name, expected=None):
        row = originals.get(name)
        require(row is not None and (expected is None or row['digest'] == expected), 'api-analysis-detached-original-material')
        return row
    require(digest(read_file(output / 'component.wasm', 64 * 1024 * 1024)) == report['componentDigest']
            and digest(read_file(output / 'source-inputs.json', 8 * 1024 * 1024)) == report['sourceDigest'],
            'api-analysis-stale-component-or-source')
    if recipe is not None:
        original('build-recipe', recipe['digest'])
        require(digest(read_file(output / 'recipe-inputs.json', 8 * 1024 * 1024)) == recipe['digest'],
                'api-analysis-stale-recipe')
    owner = selected['standardRuntime']
    original_runtime = None
    if owner['state'] == 'selected-unqualified':
        name = owner.get('receiptName', 'runtime-profile.json')
        maximum = 65536 if name == 'standard-runtime-selection.json' else 4 * 1024 * 1024
        runtime_raw = read_file(output / name, maximum)
        observed_name = ('standard-runtime-selection' if name == 'standard-runtime-selection.json' else
            'java-runtime-profile' if selected['language'] == 'java' and 'java-runtime-profile' in originals else 'runtime-profile')
        original(observed_name, owner['receiptDigest'])
        require(digest(runtime_raw) == owner['receiptDigest'],
                'api-analysis-stale-runtime-owner')
        original_runtime = decode(runtime_raw, maximum)
        require(type(original_runtime) is dict and original_runtime.get('profile') == owner['profile'], 'api-analysis-runtime-profile')
        if name == 'standard-runtime-selection.json':
            from tools import guest_runtime_receipts
            guest_runtime_receipts.validate(original_runtime, source=report['sourceDigest'],
                component=report['componentDigest'], language=selected['language'], profile=owner['profile'])
            require(original_runtime['toolAndCompilerInputs'] == guest_runtime_receipts.material_inputs(
                [row for key, row in originals.items() if key != 'standard-runtime-selection']),
                'api-analysis-runtime-owner-materials')
    expected_refs = {}
    if original_runtime is not None:
        if owner.get('receiptName') == 'standard-runtime-selection.json':
            expected_refs['selected-runtime-original'] = context.material('runtime', 'selected-runtime-original',
                original_runtime['originalRuntimeInputsDigest'], profile=owner['profile'])
        expected_refs['selected-standard-runtime'] = context.material('runtime', 'selected-standard-runtime',
            owner['receiptDigest'], profile=owner['profile'])
    patch = material(selected, 'automatic-compiler-patches')
    if patch is not None:
        original('automatic-compiler-patches', patch['digest'])
        patch_raw = read_file(output / 'compiler-patches.json', 4 * 1024 * 1024)
        require(digest(patch_raw) == patch['digest'],
                'api-analysis-stale-patch-owner')
        patches = decode(patch_raw, 4 * 1024 * 1024)
        require(type(patches) is dict and patches.get('formatVersion') == 1
                and type(patches.get('patches')) is list and len(patches['patches']) <= 64,
                'api-analysis-patch-shape')
        for item in patches['patches']:
            require(type(item) is dict, 'api-analysis-patch-shape')
            if item.get('name') != 'dotnet-closed-filesystem-v1': continue
            require(recipe is not None and {'name', 'profile', 'selection', 'original', 'selected'} <= item.keys()
                    and type(item['original']) is dict and 'digest' in item['original']
                    and type(item['selected']) is dict and 'digest' in item['selected'], 'api-analysis-patch-recipe')
            transform = digest(encode({'recipeDigest': recipe['digest'], 'name': item['name'],
                                      'profile': item['profile'], 'selection': item['selection']}))
            expected = context.material('patch', item['name'], item['selected']['digest'], profile=item['profile'],
                original=item['original']['digest'], transformation=transform)
            require(material(selected, item['name']) == expected, 'api-analysis-detached-patch-reference')
            expected_refs[item['name']] = expected
    relevant = {name for _, names, _ in RULES[selected['language']] for name in names}
    if selected['language'] == 'rust': relevant.add('rust-standard-runtime')
    for name in relevant - set(expected_refs):
        ref = material(selected, name)
        if ref is None or selected['language'] == 'typescript' and name in {*context.BUFFER_MATERIALS, *context.NET_MATERIALS}:
            continue
        original(name, ref['digest'])
        require(ref == context.material('compiler', name, originals[name]['digest']),
                'api-analysis-detached-original-reference')
    for name, expected in expected_refs.items():
        ref = material(selected, name)
        require(ref is None or ref == expected, 'api-analysis-detached-runtime-reference')
    for material_name, (filename, maximum) in OWNER_FILES.items():
        bound = material(selected, material_name)
        if bound is not None:
            original(material_name, bound['digest'])
            require(digest(read_file(output / filename, maximum)) == bound['digest'], 'api-analysis-stale-implementation-owner')
    emitted = guest_emitted_code.read(read_file(output / 'compatibility-reachability.json', MAX_BYTES),
        source=report['sourceDigest'], component=report['componentDigest'], runtime=runtime,
        host=report['runtimeProfile'], recipe=recipe['digest'] if recipe is not None else None)
    compiler, owner = {}, {}
    for name, (filename, maximum) in COMPILER_FILES.items():
        bound = material(selected, name)
        exists = (output / filename).exists() or (output / filename).is_symlink()
        require((bound is not None) == exists, 'api-analysis-detached-compiler-material')
        if bound is None: continue
        original(name, bound['digest'])
        raw = read_file(output / filename, maximum)
        require(digest(raw) == bound['digest'], 'api-analysis-stale-compiler-material')
        observed = decode(raw, maximum)
        if name == 'compiler-call-edges':
            from tools import guest_compiler_capture
            guest_compiler_capture.validate(observed)
        elif selected['language'] == 'java':
            from tools.java_guest import reachability
            reachability.validate(observed)
        elif selected['language'] == 'dotnet':
            from tools.dotnet_guest import reachability
            reachability.validate(observed)
        else:
            raise ValueError('api-analysis-method-owner-language')
        compiler[name] = observed
    if selected['language'] == 'java':
        bound = material(selected, 'generated-bindings')
        if bound is not None:
            original('generated-bindings', bound['digest'])
            raw = read_file(output / 'bindings.json', 4 * 1024 * 1024)
            require(digest(raw) == bound['digest'], 'api-analysis-stale-java-bindings')
            binding = decode(raw, 4 * 1024 * 1024)
            if 'closedFilesystem' in binding:
                port = binding['closedFilesystem']
                from tools.java_guest import filesystem
                require(type(port) is dict and port.get('profile') == filesystem.PROFILE
                        and port.get('originalArtifacts') == list(filesystem.PREIMAGES)
                        and port.get('owner') == 'org.teavm.backend.c.runtime.fs.CFileSystem'
                        and port.get('refusedMethods') == ['getUserDir', 'getFile']
                        and port.get('publicIoWrappersReplaced') is False
                        and port.get('componentExecutionQualifiedByThisRecord') is False,
                        'api-analysis-java-owner-record')
                sha(port['sourceDigest'])
                source_raw = read_file(output / 'source-inputs.json', 8 * 1024 * 1024)
                require(digest(source_raw) == report['sourceDigest'], 'api-analysis-stale-java-source-inventory')
                source = decode(source_raw, 8 * 1024 * 1024)
                name = 'vendor/lsf/sdk/java-guest/' + filesystem.SOURCE
                require(type(source) is dict and type(source.get(name)) is dict
                        and source[name].get('digest') == port['sourceDigest'],
                        'api-analysis-detached-java-owner-source')
                owner['java-closed-filesystem'] = port
    if selected['language'] == 'typescript':
        from tools.guest_compatibility_context_build import typescript_buffer_materials, typescript_net_materials
        recipe_raw = read_file(output / 'recipe-inputs.json', 8 * 1024 * 1024)
        source_raw = read_file(output / 'source-inputs.json', 8 * 1024 * 1024)
        for group, receipt, reconstruct in ((context.buffer_module(selected), 'typescript-buffer-selection.json', typescript_buffer_materials),
                (context.net_module(selected), 'typescript-net-selection.json', typescript_net_materials)):
            if group is None: continue
            first = context.BUFFER_MATERIALS[0] if receipt == 'typescript-buffer-selection.json' else context.NET_MATERIALS[0]
            raw = read_file(output / receipt, 65536)
            original(first, digest(raw))
            for ref in reconstruct(raw, recipe_raw, source_raw):
                require(material(selected, ref['name']) == ref, 'api-analysis-detached-module-reference')
    return emitted, compiler, owner, build_raw, read_file(output / 'component.wasm', 64 * 1024 * 1024)


def emit(output, report, selected):
    try:
        emitted, compiler, owner, build_raw, component = inputs(output, report, selected)
        value = create(report, selected, emitted, build_observation=build_raw, component=component,
            compiler_records=compiler, owner_records=owner)
    except (ValueError, OSError):
        value = unavailable(report, selected)
    try: write_json(output / NAME, value)
    except OSError: pass  # No optional observation may replace the original build outcome.
    return value


def read(raw, output, report, selected):
    value = validate(decode(raw, MAX_BYTES))
    if value['state'] == 'unavailable':
        require(value == unavailable(report, selected), 'api-analysis-stale-unavailable-binding')
        return value
    emitted, compiler, owner, build_raw, component = inputs(output, report, selected)
    expected = create(report, selected, emitted, build_observation=build_raw, component=component,
        compiler_records=compiler, owner_records=owner)
    require(value == expected, 'api-analysis-stale-or-rehashed-evidence')
    return value


def present(value):
    validate(value)
    if value['state'] == 'unavailable':
        return 'API implementation analysis unavailable; compatibility, execution and retirement remain unknown.\n'
    lines = ['API implementation observations; no library eligibility, provider or grant decision.']
    for row in value['apis']:
        lines.append(f"{row['api']}: {row['state']}; owner #{row['ownerIssue']}; API reachability unknown; behavior unqualified.")
    for row in value['compilerFindings']['rows']:
        mapped = ('; ' + row['rootMapping']['state'] + ':' + ','.join(row['rootMapping']['phases'])) \
            if row['kind'] == 'compiler-call-edge' else ''
        lines.append(f"{row['kind']} {row['queryIdentity']}: {row['state']}{mapped}; scope {row['scope']}.")
    if value['compilerFindings']['omitted']:
        lines.append(f"Compiler findings omitted: {value['compilerFindings']['omitted']}; no absence inferred.")
    lines.append('Compiler call/method observations and conservative core roots remain separate from API behavior.')
    lines.append('Uncatalogued APIs remain unknown; initialization and physical retirement are not certified.')
    return '\n'.join(lines) + '\n'
