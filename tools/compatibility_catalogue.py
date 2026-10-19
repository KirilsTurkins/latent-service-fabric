"""Read optional, evidence-bound compatibility observations without granting authority."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat

from tools.dev_workflow.common import decode, encode

SCHEMA = 'lsf.compatibility.catalogue.v1'
MAX_BYTES = 1024 * 1024
MAX_DOCUMENTS = 64
MAX_ENTRIES = 256
STATUSES = frozenset({'tested-default-path', 'supported-ordinary-configuration',
    'optional-adapter-assisted', 'known-incompatible', 'untested'})
DIMENSIONS = frozenset({'source', 'component', 'graph', 'configuration', 'compiler',
    'engine', 'runtime', 'backend', 'automaticPatches', 'wit'})
LANGUAGES = frozenset({'c', 'rust', 'typescript', 'go', 'java', 'dotnet'})
DIGEST = re.compile(r'sha256:[0-9a-f]{64}\Z')


def require(condition, reason):
    if not condition:
        raise ValueError('catalogue-' + reason)


def digest(value):
    return 'sha256:' + hashlib.sha256(value).hexdigest()


def identity(value):
    return digest(encode(value))


def fields(value, expected):
    require(isinstance(value, dict) and set(value) == set(expected), 'fields')


def text(value, maximum=512):
    require(isinstance(value, str) and 0 < len(value) <= maximum
            and not any(ord(c) < 32 or ord(c) == 127 for c in value), 'text')


def strings(value, maximum=32):
    require(isinstance(value, list) and 0 < len(value) <= maximum, 'strings')
    for item in value:
        text(item)
    require(len(set(value)) == len(value), 'duplicate-text')


def pointer(document, selected):
    require(isinstance(selected, str) and len(selected) <= 512
            and (selected == '' or selected.startswith('/')), 'pointer')
    for item in selected.split('/')[1:] if selected else []:
        require(not re.search(r'~(?![01])', item), 'pointer-escape')
        name = item.replace('~1', '/').replace('~0', '~')
        if isinstance(document, list):
            require(bool(re.fullmatch(r'0|[1-9][0-9]*', name)), 'pointer-index')
            require(int(name) < len(document), 'pointer-index')
            document = document[int(name)]
        else:
            require(isinstance(document, dict) and name in document, 'pointer-member')
            document = document[name]
    return document


def reference(value, documents):
    fields(value, {'document', 'pointer', 'valueDigest'})
    require(value['document'] in documents and DIGEST.fullmatch(value['valueDigest']), 'reference')
    selected = pointer(documents[value['document']], value['pointer'])
    require(identity(selected) == value['valueDigest'], 'reference-drift')
    return selected


def document(root, value):
    fields(value, {'path', 'sha256', 'bytes', 'origin'})
    name = value['path'];text(name)
    relative = PurePosixPath(name)
    require(not relative.is_absolute() and str(relative) == name and '\\' not in name
            and ':' not in name and all(p not in {'.', '..'} for p in relative.parts), 'document-path')
    current = root
    for part in relative.parts:
        current /= part
        require(not current.is_symlink(), 'document-link')
    info = current.stat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and isinstance(value['bytes'], int) and not isinstance(value['bytes'], bool)
            and 0 < value['bytes'] == info.st_size <= MAX_BYTES, 'document-bound')
    with current.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    require(len(raw) == value['bytes'], 'document-read-bound')
    require(DIGEST.fullmatch(value['sha256']) and digest(raw) == value['sha256'], 'document-drift')
    fields(value['origin'], {'source', 'run', 'job', 'artifact', 'member'})
    origin = value['origin']
    require(isinstance(origin['source'], str) and re.fullmatch(r'[0-9a-f]{40}', origin['source']), 'origin-source')
    for kind in ('run', 'job', 'artifact'):
        require(type(origin[kind]) is int and origin[kind] > 0, 'origin-id')
    text(origin['member'])
    return decode(raw, MAX_BYTES)


def validate(value, root):
    fields(value, {'schemaVersion', 'authority', 'packageEligibility', 'documents', 'entries'})
    require(value['schemaVersion'] == SCHEMA and value['authority'] == 'none'
            and value['packageEligibility'] == 'independent-of-catalogue', 'authority')
    require(isinstance(value['documents'], dict) and len(value['documents']) <= MAX_DOCUMENTS, 'documents')
    documents = {}
    for name, record in value['documents'].items():
        require(bool(re.fullmatch(r'[a-z][a-z0-9-]{0,63}', name)), 'document-name')
        documents[name] = document(root, record)
    require(isinstance(value['entries'], list) and len(value['entries']) <= MAX_ENTRIES, 'entries')
    seen = set()
    for entry in value['entries']:
        fields(entry, {'identity', 'documentsIdentity', 'language', 'package', 'status', 'surface', 'construction',
                       'packageBindings', 'bindings', 'evidence', 'limitations'})
        require(entry['language'] in LANGUAGES and entry['status'] in STATUSES, 'classification')
        require(entry['identity'] == identity({k: v for k, v in entry.items() if k != 'identity'})
                and entry['identity'] not in seen, 'entry-identity')
        seen.add(entry['identity'])
        require(entry['documentsIdentity'] == identity(value['documents']), 'document-provenance-drift')
        fields(entry['package'], {'coordinate', 'version', 'artifactDigest'})
        text(entry['package']['coordinate']);text(entry['package']['version'], 128)
        require(bool(DIGEST.fullmatch(entry['package']['artifactDigest'])), 'package-digest')
        fields(entry['packageBindings'], entry['package'])
        for name, selected in entry['packageBindings'].items():
            require(reference(selected, documents) == entry['package'][name], 'package-binding')
        text(entry['surface']);strings(entry['limitations'])
        require(entry['construction'] in {'ordinary-default', 'ordinary-configuration',
                'injected-adapter', 'not-executed'}, 'construction')
        fields(entry['bindings'], DIMENSIONS)
        for selected in entry['bindings'].values():
            reference(selected, documents)
        proof = entry['evidence']
        fields(proof, {'kind', 'result', 'source', 'component', 'claims'})
        require(proof['kind'] in {'actual-component', 'native-reference', 'compiler', 'not-run'}, 'evidence-kind')
        result = reference(proof['result'], documents)
        strings(proof['claims'])
        observed_source = reference(proof['source'], documents)
        observed_component = reference(proof['component'], documents)
        if proof['kind'] == 'actual-component':
            require(isinstance(observed_source, str) and bool(DIGEST.fullmatch(observed_source))
                    and isinstance(observed_component, str) and bool(DIGEST.fullmatch(observed_component))
                    and observed_source == reference(entry['bindings']['source'], documents)
                    and observed_component == reference(entry['bindings']['component'], documents),
                    'execution-source-component')
        if entry['status'] == 'tested-default-path':
            require(entry['construction'] == 'ordinary-default' and proof['kind'] == 'actual-component'
                    and result == 'passed', 'default-path-evidence')
        if entry['status'] == 'supported-ordinary-configuration':
            require(entry['construction'] == 'ordinary-configuration'
                    and proof['kind'] in {'actual-component', 'compiler'}
                    and result in {'passed', 'observed'}, 'configuration-evidence')
        if entry['status'] == 'optional-adapter-assisted':
            require(entry['construction'] == 'injected-adapter', 'adapter-classification')
        if entry['status'] == 'untested':
            require(proof['kind'] == 'not-run', 'untested-evidence')
        if entry['status'] == 'known-incompatible':
            require(proof['kind'] in {'actual-component', 'compiler'}
                    and result in {'failed', 'unsupported', 'blocked'}, 'incompatible-evidence')
    return value


def markdown(value):
    lines = ['# Library compatibility observations', '',
        'This versioned catalogue records finite historical observations. It grants no',
        'authority and does not control dependency resolution, builds or admission.',
        'An absent entry means untested. Entries do not certify a package or transfer',
        'results to another graph, configuration, compiler, engine, runtime or backend.', '',
        '| Language | Package | Status | Exercised surface |',
        '| --- | --- | --- | --- |']
    escape = lambda text: text.replace('\\', '\\\\').replace('|', '\\|').replace('`', '\\`').replace('<', '&lt;').replace('>', '&gt;')
    for row in value['entries']:
        lines.append('| ' + ' | '.join(escape(item) for item in
            (row['language'], row['package']['coordinate'], row['status'], row['surface'])) + ' |')
    for row in value['entries']:
        lines += ['', '## ' + escape(row['package']['coordinate']), '',
                  'Entry identity: `' + row['identity'] + '`.', '', 'Observed:']
        lines += ['- ' + escape(item) for item in row['evidence']['claims']]
        lines += ['', 'Limits:']
        lines += ['- ' + escape(item) for item in row['limitations']]
    lines += ['', 'The adjacent JSON retains each bound value and its exact public receipt',
              'document, JSON pointer, digest and original workflow/artifact identity.',
              'The reader verifies retained bytes and bindings; it does not authenticate',
              'a new execution or turn a receipt label into independent qualification.', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('catalogue', type=Path)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    selected = args.catalogue.resolve()
    with selected.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    value = validate(decode(raw, MAX_BYTES), selected.parent)
    print(json.dumps(value, indent=2) if args.json else markdown(value), end='\n' if args.json else '')


if __name__ == '__main__':
    main()
