"""Passive captured-class queries for TeaVM's completed dependency analysis.

This does not load application classes in the build host, run initializers or
certify runtime behavior. Unknown or omitted compiler observations stay unknown.
"""
from __future__ import annotations

import re
from pathlib import Path
import zipfile

from tools.dev_workflow.common import digest, encode, integer, members, require, sha
from tools.rust_capsule_project import read_file

MAX_QUERIES = 64
MAX_INDEX = 65536
MAX_CLASS = 16 * 1024 * 1024
MAX_CLASSES = 65536
MAX_METHODS = 262144
MAX_INPUT_BYTES = 64 * 1024 * 1024
RESOURCE = 'META-INF/latent/compatibility-methods.tsv'
MARKER = 'LSF_COMPILER_REACHABILITY_V1:'
CLASS = re.compile(r'[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*')
METHOD = re.compile(r'(?:[A-Za-z_$][A-Za-z0-9_$]*|<init>|<clinit>)')


def class_methods(raw: bytes) -> tuple[str, list[dict]]:
    """Read JVM metadata only; bytecode and annotation contents remain private."""
    require(10 <= len(raw) <= MAX_CLASS and raw[:4] == b'\xca\xfe\xba\xbe',
            'compiler-reachability-class-header')
    at = 8

    def take(size):
        nonlocal at
        require(type(size) is int and 0 <= size <= len(raw) - at,
                'compiler-reachability-class-truncated')
        value = raw[at:at + size]; at += size
        return value

    def number(size): return int.from_bytes(take(size), 'big')

    strings, classes, index, count = {}, {}, 1, number(2)
    while index < count:
        tag = number(1)
        if tag == 1:
            strings[index] = take(number(2))
        elif tag == 7:
            classes[index] = number(2)
        elif tag in {3, 4, 9, 10, 11, 12, 17, 18}: take(4)
        elif tag in {5, 6}: take(8); index += 1
        elif tag in {8, 16, 19, 20}: take(2)
        elif tag == 15: take(3)
        else: raise ValueError('compiler-reachability-class-constant')
        index += 1

    def text(index):
        value = strings.get(index)
        require(value is not None, 'compiler-reachability-class-string')
        return value.decode('utf-8')

    def attributes():
        names = []
        for _ in range(number(2)):
            names.append(text(number(2))); take(number(4))
        return names

    number(2)
    owner = text(classes.get(number(2))).replace('/', '.')
    require(CLASS.fullmatch(owner) is not None, 'compiler-reachability-class-name')
    number(2); take(number(2) * 2)
    for _ in range(number(2)):
        take(6); attributes()
    methods = []
    for _ in range(number(2)):
        flags, name, descriptor = number(2), text(number(2)), text(number(2))
        names = attributes()
        require(METHOD.fullmatch(name) is not None and 1 <= len(descriptor) <= 4096
                and descriptor.startswith('(') and not any(c in descriptor for c in '\t\n\r\0'),
                'compiler-reachability-method-descriptor')
        annotated = any('Annotations' in item for item in names)
        methods.append({'method': name + descriptor, 'native': bool(flags & 0x100),
                        'nativeWithoutAnnotations': bool(flags & 0x100) and not annotated,
                        'kind': 'initialization' if name == '<clinit>' else
                                'constructor' if name == '<init>' else 'method'})
    attributes()
    require(at == len(raw), 'compiler-reachability-class-tail')
    return owner, methods


def queries(classes: Path, jars: tuple[Path, ...], *, application_classes: set[str] | None = None) -> tuple[bytes, dict]:
    """Select finite method queries over actual compiled/captured class bytes."""
    selected, seen, total, method_count, class_count = [], set(), 0, 0, 0

    def observe(name, raw, package):
        nonlocal total, method_count, class_count
        total += len(raw); class_count += 1
        require(total <= MAX_INPUT_BYTES and class_count <= MAX_CLASSES,
                'compiler-reachability-input-bound')
        owner, methods = class_methods(raw)
        require(name == owner.replace('.', '/') + '.class' and owner not in seen,
                'compiler-reachability-ambiguous-class')
        seen.add(owner)
        source = digest(raw)
        for method in methods:
            method_count += 1
            require(method_count <= MAX_METHODS, 'compiler-reachability-method-bound')
            identity = digest(encode({'classDigest': source, 'owner': owner, 'method': method['method']}))
            selected.append({**method, 'id': identity.removeprefix('sha256:'),
                             'owner': owner, 'classDigest': source, 'packageDigest': package})
            # Keep memory bounded independently of total captured methods.
            selected.sort(key=lambda row: (not row['nativeWithoutAnnotations'],
                {'initialization': 0, 'constructor': 1, 'method': 2}[row['kind']], row['owner'], row['method']))
            del selected[MAX_QUERIES:]

    paths = sorted(classes.rglob('*.class'))
    require(len(paths) <= MAX_CLASSES, 'compiler-reachability-input-bound')
    for path in paths:
        require(not path.is_symlink(), 'compiler-reachability-class-link')
        if application_classes is not None and path.relative_to(classes).with_suffix('').as_posix().replace('/', '.') not in application_classes:
            continue
        observe(path.relative_to(classes).as_posix(), read_file(path, MAX_CLASS), None)
    for jar in jars:
        body = read_file(jar, MAX_INPUT_BYTES)
        package = digest(body)
        with zipfile.ZipFile(jar) as archive:
            infos = archive.infolist()
            require(len(infos) <= MAX_CLASSES, 'compiler-reachability-jar-bound')
            names = set()
            for info in infos:
                if not info.filename.endswith('.class') or info.filename.startswith('META-INF/'):
                    continue
                require(info.filename not in names and 0 < info.file_size <= MAX_CLASS
                        and info.compress_size <= MAX_INPUT_BYTES, 'compiler-reachability-jar-member')
                names.add(info.filename)
                observe(info.filename, archive.read(info), package)
    payload = ''.join(row['id'] + '\t' + row['owner'] + '\t' + row['method'] + '\n' for row in selected).encode()
    require(len(payload) <= MAX_INDEX, 'compiler-reachability-index-bound')
    return payload, {'schemaVersion': 'lsf.java.compiler-queries.v1', 'queries': selected,
        'omittedMethods': method_count - len(selected), 'classesInspected': class_count,
        'classBytesInspected': total, 'indexDigest': digest(payload), 'initializersExecuted': False}


def observation(log: str, index: dict) -> dict:
    """Accept exactly one completed compiler projection, never a source scan."""
    lines = [line[len(MARKER):] for line in log.splitlines() if line.startswith(MARKER)]
    require(len(lines) == 1, 'compiler-reachability-marker-count')
    raw = lines[0]
    require(len(raw) <= MAX_INDEX and raw.startswith('complete;'), 'compiler-reachability-marker')
    fields = raw[len('complete;'):].split(',') if raw != 'complete;' else []
    states = {}
    for item in fields:
        identity, separator, state = item.partition('=')
        require(separator and re.fullmatch('[a-f0-9]{64}', identity) is not None
                and state in {'linked', 'not-retained', 'unknown'} and identity not in states,
                'compiler-reachability-marker-row')
        states[identity] = state
    require(set(states) == {row['id'] for row in index['queries']}, 'compiler-reachability-query-mismatch')
    return {**{key: value for key, value in index.items() if key != 'queries'},
            'schemaVersion': 'lsf.java.compiler-methods.v1',
            'compiler': 'teavm-c-0.15.0', 'analysisCompleteness': 'selected-method-queries',
            'methods': [{**row, 'state': states[row['id']]} for row in index['queries']],
            'runtimeExecution': 'not-observed', 'reflection': 'compiler-modeled-only',
            'retentionScope': 'dependency-analysis-only',
            'workerDrain': 'unproven', 'authority': 'none'}


def bind(observed: dict, *, source: str, component: str, compiler: str,
         recipe: str, graph: str | None) -> dict:
    """Bind successful compiler observations without changing the v1 report."""
    for identity in (source, component, compiler, recipe, graph):
        if identity is not None: sha(identity)
    require(observed.get('schemaVersion') == 'lsf.java.compiler-methods.v1'
            and len(observed['methods']) <= MAX_QUERIES, 'compiler-reachability-observation')
    methods = []
    for row in observed['methods']:
        # Descriptor contents are needed for exact compiler queries but are not
        # public source text. The class/method byte identities remain linked.
        symbol = row['owner'] + '.' + row['method'].split('(', 1)[0]
        safe = re.fullmatch(r'[A-Za-z0-9_.]+', symbol) is not None and len(symbol) <= 192
        methods.append({key: row[key] for key in ('id', 'classDigest', 'packageDigest', 'kind', 'state')} | {
            'symbol': symbol if safe else 'method-' + row['id'],
            'symbolRedacted': not safe, 'signatureDigest': digest(row['method'].encode()),
            'declaration': 'native' if row['native'] else 'ordinary',
            'apiClassification': 'unknown'})
    value = {key: item for key, item in observed.items() if key != 'methods'} | {
        'sourceDigest': source, 'componentDigest': component, 'compilerDigest': compiler,
        'recipeDigest': recipe, 'graphDigest': graph, 'methods': methods,
        'rootScope': 'compiler-selected-entries-initializers-and-callbacks',
        'apiSupport': 'unknown', 'eliminationScope': 'exact-method-only'}
    value['identity'] = digest(encode(value))
    return validate(value, source=source, component=component, compiler=compiler, recipe=recipe, graph=graph)


def validate(value: dict, *, source=None, component=None, compiler=None, recipe=None, graph=...):
    members(value, {'schemaVersion', 'omittedMethods', 'classesInspected', 'classBytesInspected',
        'indexDigest', 'initializersExecuted', 'compiler', 'analysisCompleteness', 'methods',
        'runtimeExecution', 'reflection', 'retentionScope', 'workerDrain', 'authority', 'sourceDigest', 'componentDigest',
        'compilerDigest', 'recipeDigest', 'graphDigest', 'rootScope', 'apiSupport', 'eliminationScope', 'identity'})
    require((value['schemaVersion'], value['compiler'], value['analysisCompleteness'],
        value['runtimeExecution'], value['reflection'], value['workerDrain'], value['authority'],
        value['rootScope'], value['apiSupport'], value['eliminationScope'], value['initializersExecuted'], value['retentionScope']) ==
        ('lsf.java.compiler-methods.v1', 'teavm-c-0.15.0', 'selected-method-queries',
         'not-observed', 'compiler-modeled-only', 'unproven', 'none',
         'compiler-selected-entries-initializers-and-callbacks', 'unknown', 'exact-method-only', False,
         'dependency-analysis-only')
        and value['initializersExecuted'] is False,
        'compiler-reachability-cannot-certify-api-or-execution')
    for name in ('indexDigest', 'sourceDigest', 'componentDigest', 'compilerDigest', 'recipeDigest', 'identity'):
        sha(value[name])
    if value['graphDigest'] is not None: sha(value['graphDigest'])
    integer(value['omittedMethods'], 0, MAX_METHODS)
    integer(value['classesInspected'], 0, MAX_CLASSES)
    integer(value['classBytesInspected'], 0, MAX_INPUT_BYTES)
    require(type(value['methods']) is list and len(value['methods']) <= MAX_QUERIES,
            'compiler-reachability-public-count')
    seen = set()
    for row in value['methods']:
        members(row, {'id', 'classDigest', 'packageDigest', 'kind', 'state', 'symbol',
            'symbolRedacted', 'signatureDigest', 'declaration', 'apiClassification'})
        require(type(row['id']) is str and re.fullmatch('[a-f0-9]{64}', row['id']) is not None
                and row['id'] not in seen, 'compiler-reachability-public-method-id')
        seen.add(row['id'])
        sha(row['classDigest']); sha(row['signatureDigest'])
        if row['packageDigest'] is not None: sha(row['packageDigest'])
        require(row['state'] in {'linked', 'not-retained', 'unknown'}
            and row['kind'] in {'initialization', 'constructor', 'method'}
            and row['declaration'] in {'native', 'ordinary'} and row['apiClassification'] == 'unknown'
            and type(row['symbolRedacted']) is bool and type(row['symbol']) is str
            and re.fullmatch('[A-Za-z0-9_.-]{1,192}', row['symbol']) is not None,
            'compiler-reachability-public-method')
    require(len(encode(value)) <= MAX_INDEX
            and value['identity'] == digest(encode({k: v for k, v in value.items() if k != 'identity'})),
            'compiler-reachability-public-identity-or-size')
    for expected, name in ((source, 'sourceDigest'), (component, 'componentDigest'),
                           (compiler, 'compilerDigest'), (recipe, 'recipeDigest')):
        if expected is not None: require(expected == value[name], 'compiler-reachability-stale-' + name)
    if graph is not ...: require(graph == value['graphDigest'], 'compiler-reachability-stale-graph')
    return value
