"""Produce immutable host expectations from reviewed authentic compiler objects.

Generation is not authority: the complete original source/compiler/artifact
provenance must be independently verified and reviewed before these generated
files can enter the host source. Arbitrary embedded guest objects never select
or replace this catalogue. Full bodies and all actual referents are retained.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json

from tools import rust_thread_object_graph as graph

ROOT_EXPORTS = (
    '__lsf_rust_pool_request', '__lsf_rust_pool_prepare', '__lsf_rust_pool_commit',
    '__lsf_rust_pool_abort_setup', '__lsf_rust_owned_thread_entry',
    '__lsf_rust_root_bootstrap', '__lsf_rust_root_finish', '__lsf_rust_root_reap')
ADDITIONAL_ROOT_SYMBOLS = (
    '_RNvMs1_NtCsffIcXob95CF_16futures_executor15lsf_thread_poolNtB5_4Pool12admit_future',
    '_RNvMs1_NtCsffIcXob95CF_16futures_executor11thread_poolNtB5_10ThreadPool14spawn_admitted',
    '_RNvMs1_NtCsffIcXob95CF_16futures_executor11thread_poolNtB5_10ThreadPool3new')


def reviewed_roots(manifest: dict) -> None:
    """Require all public lifecycle roots and the three private ThreadPool roots."""
    nodes = {row['id']: row for row in manifest['nodes']}
    actual = {(row['export'], nodes.get(row['node'], {}).get('originalSymbol'))
              for row in manifest['roots']}
    expected = ({(name, name) for name in ROOT_EXPORTS}
                | {(None, name) for name in ADDITIONAL_ROOT_SYMBOLS})
    graph.require(len(manifest['roots']) == len(actual) == len(expected) == 11
                  and actual == expected, 'rust-host-catalogue-reviewed-roots')


def catalogue(core: bytes, libraries: tuple[graph.Library, ...], observation: dict,
              root_exports: tuple[str, ...], additional_roots: tuple[tuple[str, str], ...],
              origin: dict) -> tuple[bytes, dict]:
    graph.require(observation['coreDigest'] == graph.digest(core)
                  and not observation['failures'] and not observation['unresolvedReferents']
                  and not observation['instructionDecodeFailures'], 'rust-host-catalogue-open-observation')
    graph.require(0 < len(libraries) <= graph.MAX_LIBRARIES
                  and sum(len(item.content) for item in libraries) <= graph.MAX_LIBRARIES_BYTES,
                  'rust-host-catalogue-library-bound')
    objects, nodes, local, global_nodes = {}, {}, defaultdict(list), defaultdict(list)

    def locator(row):
        return ((0, row['index']) if row['kind'] == 0 else
                (1, row['segment'], row['offset'], row['size']))

    for library in libraries:
        library.checked()
        for name, raw in graph.archive(library.content):
            label = library.label + '/' + name
            graph.require(label not in objects and len(objects) < graph.MAX_OBJECTS,
                          'rust-host-catalogue-object-bound')
            members, _ = graph.object_nodes(raw, label)
            sections = graph.sections(raw)
            signatures, _, _ = graph.code(raw)
            types = graph.types(raw)
            objects[label] = (sections, signatures, types)
            for node in members:
                key = (label, node['symbolIndex'])
                graph.require(key not in nodes and len(nodes) < graph.MAX_NODES,
                              'rust-host-catalogue-node-bound')
                nodes[key] = node
                local[(label, locator(node))].append(node)
                if not node['flags'] & 2:
                    global_nodes[(node['kind'], node['name'])].append(node)

    selected = {(row['object'], row['symbolIndex']) for row in observation['matchedBindings']
                if row['bodyMatched']}
    graph.require(len(selected) == len(observation['matchedBindings']) and selected <= set(nodes),
                  'rust-host-catalogue-all-bindings-verified')
    ordered = sorted(selected)
    identifiers = {key: index for index, key in enumerate(ordered)}

    def node_id(node):
        key = (node['object'], node['symbolIndex'])
        graph.require(key in identifiers, 'rust-host-catalogue-original-referent-omitted')
        return identifiers[key]

    def resolve(source, target):
        if target['defined']:
            aliases = local[(source['object'], locator(target))]
            identities = {(row['bodySection'], row['bodyStart'], row['bodyEnd'], row['bodyDigest'],
                           json.dumps(row['relocations'], sort_keys=True)) for row in aliases}
            graph.require(len(identities) <= 1, 'rust-host-catalogue-inconsistent-alias')
            return aliases[:1]
        return global_nodes[(target['kind'], target['name'])]

    rows, image = [], bytearray()
    for key in ordered:
        node = nodes[key]
        sections, signatures, types = objects[node['object']]
        body = sections[node['bodySection']][1][node['bodyStart']:node['bodyEnd']]
        graph.require(hashlib.sha256(body).hexdigest() == node['bodyDigest'],
                      'rust-host-catalogue-original-body-digest')
        refs = []
        for relocation in node['relocations']:
            kind, target = relocation['kind'], relocation['target']
            if kind == 6:
                referent = {'type': types[relocation['index']]}
            elif kind in (7, 20):
                referent = {'export': {'kind': 3 if kind == 7 else 1, 'name': target['name']}}
            else:
                graph.require(kind in (0, 1, 2, 3, 4, 5), 'rust-host-catalogue-relocation-kind')
                candidates = resolve(node, target)
                if candidates:
                    graph.require(len(candidates) == 1, 'rust-host-catalogue-ambiguous-referent')
                    referent = {'node': node_id(candidates[0])}
                elif (target['kind'] == 0 and 'import' in target and not any(
                        target['name'].endswith('___rustc' + suffix) for suffix in graph.COMPILER_SHIMS)):
                    referent = {'import': {'module': target['import'][0], 'name': target['import'][1],
                                           'signature': signatures[target['index']]}}
                elif target['kind'] == 1 and target['name'] in ('__heap_base', '__heap_end'):
                    referent = {'heap': target['name']}
                else:
                    shims = [(suffix, spec) for suffix, spec in graph.COMPILER_SHIMS.items()
                             if target['kind'] == 0 and target['name'].endswith('___rustc' + suffix)]
                    graph.require(len(shims) == 1, 'rust-host-catalogue-unresolved-original-referent')
                    suffix, (delegate, arity) = shims[0]
                    callee = None
                    if delegate is not None:
                        name = target['name'][:-len(suffix)] + delegate
                        candidates = global_nodes[(0, name)]
                        graph.require(len(candidates) == 1, 'rust-host-catalogue-original-shim-target')
                        callee = node_id(candidates[0])
                    referent = {'shim': {'arity': arity, 'delegate': callee,
                                         'signature': signatures[target['index']]}}
            refs.append({'offset': relocation['offset'], 'extent': relocation['extent'],
                         'kind': kind, 'addend': relocation['addend'], 'referent': referent})
        begin = len(image)
        image.extend(body)
        rows.append({'id': identifiers[key], 'object': key[0], 'originalSymbolIndex': key[1],
                     'originalSymbol': node['name'], 'kind': node['kind'],
                     'signature': signatures[node['index']] if node['kind'] == 0 else ((), ()),
                     'bodyOffset': begin, 'bodyBytes': len(body), 'references': refs})
    roots = []
    for name in root_exports:
        candidates = global_nodes[(0, name)]
        graph.require(len(candidates) == 1, 'rust-host-catalogue-export-root')
        roots.append({'node': node_id(candidates[0]), 'export': name})
    for library, name in additional_roots:
        candidates = [node for node in nodes.values() if node['kind'] == 0
                      and node['object'].startswith(library + '/') and node['name'] == name]
        graph.require(len(candidates) == 1, 'rust-host-catalogue-additional-root')
        roots.append({'node': node_id(candidates[0]), 'export': None})
    graph.require(len(image) <= graph.MAX_CORE_BYTES and len(roots) <= 64,
                  'rust-host-catalogue-body-image-or-root-bound')
    manifest = {'schemaVersion': 'latent.rust.trusted-original-catalogue.v1',
                'origin': origin, 'originalBodyImageDigest': graph.digest(bytes(image)),
                'originalBodyImageBytes': len(image), 'nodes': rows, 'roots': roots,
                'libraries': [{'label': item.label, 'digest': item.expected_digest,
                               'bytes': len(item.content)} for item in libraries],
                'generationGrantsAuthority': False, 'runtimeQualified': False}
    return bytes(image), manifest


def rust_records(image: bytes, manifest: dict) -> bytes:
    """Emit borrowed immutable typed records; no runtime JSON/global cache."""
    reviewed_roots(manifest)
    graph.require(manifest['originalBodyImageDigest'] == graph.digest(image)
                  and len(manifest['nodes']) == 1221
                  and sum(len(row['references']) for row in manifest['nodes']) == 5245,
                  'rust-host-catalogue-reviewed-membership')

    def quoted(value):
        graph.require(isinstance(value, str) and not any(ord(char) < 32 for char in value),
                      'rust-host-catalogue-source-string')
        return json.dumps(value, ensure_ascii=False)

    def signature(value):
        return ('Signature { params: &[' + ','.join(str(part) for part in value[0]) +
                '], results: &[' + ','.join(str(part) for part in value[1]) + '] }')

    def target(value):
        if 'node' in value:
            return 'Target::Definition(' + str(value['node']) + ')'
        if 'type' in value:
            return 'Target::Type(' + signature(value['type']) + ')'
        if 'export' in value:
            row = value['export']
            return 'Target::Export { kind: ' + str(row['kind']) + ', name: ' + quoted(row['name']) + ' }'
        if 'import' in value:
            row = value['import']
            return ('Target::Import { module: ' + quoted(row['module']) + ', name: ' +
                    quoted(row['name']) + ', signature: ' + signature(row['signature']) + ' }')
        if 'heap' in value:
            return 'Target::Heap { end: ' + str(value['heap'] == '__heap_end').lower() + ' }'
        row = value['shim']
        delegate = 'None' if row['delegate'] is None else 'Some(' + str(row['delegate']) + ')'
        return ('Target::Shim { arity: ' + str(row['arity']) + ', delegate: ' + delegate +
                ', signature: ' + signature(row['signature']) + ' }')

    lines = [
        '// Generated from authentic original compiler objects; see reviewed origin manifest.',
        '// Full bodies are borrowed from the immutable original image, never supplied by a guest.',
        'use super::{Node, Reference, Root, Signature, Target};',
        'pub(super) static BODIES: &[u8] = include_bytes!("rust_catalogue/original-body-image.bin");',
        'pub(super) const ORIGIN_HEAD: &str = ' + quoted(manifest['origin']['head']) + ';',
        'pub(super) const ORIGIN_RECIPE: &str = ' + quoted(manifest['origin']['sourceRecipeDigest']) + ';',
        'pub(super) const BODY_DIGEST: &str = ' + quoted(manifest['originalBodyImageDigest']) + ';',
        'pub(super) static ROOTS: &[Root] = &[',
    ]
    for row in manifest['roots']:
        export = 'None' if row['export'] is None else 'Some(' + quoted(row['export']) + ')'
        lines.append('Root { node: ' + str(row['node']) + ', export: ' + export + ' },')
    lines.extend(['];', 'pub(super) static NODES: &[Node] = &['])
    for row in manifest['nodes']:
        lines.append('Node { kind: ' + str(row['kind']) + ', signature: ' + signature(row['signature']) +
                     ', name: ' + quoted(row['originalSymbol']) + ', start: ' + str(row['bodyOffset']) +
                     ', size: ' + str(row['bodyBytes']) + ', references: &[')
        for ref in row['references']:
            lines.append('Reference { offset: ' + str(ref['offset']) + ', extent: ' + str(ref['extent']) +
                         ', kind: ' + str(ref['kind']) + ', addend: ' + str(ref['addend']) +
                         ', target: ' + target(ref['referent']) + ' },')
        lines.append('] },')
    lines.extend(['];', ''])
    source = '\n'.join(lines).encode()
    graph.require(len(source) <= 4 * 1024 * 1024, 'rust-host-catalogue-source-byte-bound')
    return source


def normal_component_envelope(derived: bytes, component: bytes) -> dict[str, bytes]:
    """Retain the exact finite normal graph, with only its main core replaced.

    These are host-owned review inputs, not a guest-selectable proof. The
    production verifier still recomputes every main-core byte from the original
    source catalogue and admits only this specific WIT/import/encoder shape.
    """
    graph.require(component[:8] == b'\0asm\x0d\0\x01\0'
                  and len(component) <= 2 * 1024 * 1024,
                  'rust-host-normal-component-envelope')
    reader = graph.Reader(component[8:])
    rows = []
    while reader.p < len(reader.raw):
        graph.require(len(rows) < 256, 'rust-host-normal-component-section-bound')
        start = reader.p
        kind = reader.byte()
        payload = reader.blob(reader.number())
        rows.append((kind, payload, reader.raw[start:reader.p]))
    graph.require(len(rows) <= 256 and sum(kind == 1 for kind, _, _ in rows) == 3,
                  'rust-host-normal-component-three-cores')
    main_index = next(index for index, row in enumerate(rows) if row[0] == 1)
    main = rows[main_index][1]
    def core_parts(raw):
        graph.require(raw[:8] == b'\0asm\x01\0\0\0' and len(raw) <= 1024 * 1024,
                      'rust-host-normal-core-byte-bound-or-version')
        reader = graph.Reader(raw[8:])
        parts = []
        while reader.p < len(reader.raw):
            graph.require(len(parts) < 512, 'rust-host-normal-core-section-bound')
            kind = reader.byte()
            parts.append((kind, reader.blob(reader.number())))
        return parts

    source_sections = core_parts(derived)
    main_sections = iter(core_parts(main))
    source_producers = None
    encoded_producers = None
    metadata = None
    for kind, payload in source_sections:
        name = graph.Reader(payload).name() if kind == 0 else None
        if name and name.startswith('component-type:'):
            graph.require(metadata is None and len(payload) <= 16 * 1024,
                          'rust-host-one-consumed-original-wit')
            metadata = payload
            continue
        encoded = next(main_sections, None)
        graph.require(encoded is not None and encoded[0] == kind,
                      'rust-host-normal-main-section-order')
        if name == 'producers':
            graph.require(source_producers is None and len(payload) <= 4096
                          and len(encoded[1]) <= 4096,
                          'rust-host-one-normal-producer-merge')
            source_producers = payload
            encoded_producers = encoded[1]
        else:
            graph.require(encoded[1] == payload, 'rust-host-normal-main-byte-preservation')
    graph.require(next(main_sections, None) is None and metadata is not None
                  and source_producers is not None and encoded_producers is not None,
                  'rust-host-normal-main-complete')
    shell = bytearray(component[:8])
    for index, (_, _, whole) in enumerate(rows):
        shell.extend(b'\x01\x00' if index == main_index else whole)
    graph.require(len(shell) <= 16 * 1024, 'rust-host-normal-shell-byte-bound')
    return {'normal-component-shell.bin': bytes(shell),
            'original-wit-metadata.bin': metadata,
            'original-producers.bin': source_producers,
            'encoded-producers.bin': encoded_producers}
