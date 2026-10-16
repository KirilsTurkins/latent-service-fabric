"""Compiler-private root retirement edge, consumed before final admission.

Original public WIT remains immutable. The actual encoder must reconstruct its
complete graph after removing only the exact private addition from the selected
canonical source. This is a compiler implementation edge, never a host grant.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

IDENTITY = 'latent:dotnet-retirement/owner@0.1.0'
PACKAGE = 'latent:dotnet-retirement@0.1.0'
PROFILE = 'dotnet-owned-retirement-v1'
PRIVATE = '''
package latent:dotnet-retirement@0.1.0 {
  interface owner {
    drain: async func();
  }
}
'''
MAX_TEXT = 4*1024*1024


def without_private(text: str) -> str:
    """Strip only the exact canonical private package and one world import."""
    package = re.compile(r'(?m)^package latent:dotnet-retirement@0\.1\.0 \{\s*'
        r'interface owner \{\s*drain: async func\(\);\s*\}\s*\}\s*')
    imports = re.compile(r'(?m)^[ \t]+import latent:dotnet-retirement/owner@0\.1\.0;\n')
    if len(package.findall(text)) != 1 or len(imports.findall(text)) != 1:
        raise ValueError('dotnet-retirement-private-source-shape')
    restored = package.sub('', imports.sub('', text))
    if 'latent:dotnet-retirement' in restored:
        raise ValueError('dotnet-retirement-private-source-remainder')
    return restored


def private_import(graph: dict) -> bool:
    from tools.dotnet_guest.internal_io import interface_name
    identifiers = {item['interface']['id']
        for world in graph['worlds'] for item in world['imports'].values()
        if 'interface' in item and interface_name(graph, item['interface']['id']) == IDENTITY}
    if not identifiers:
        return False
    if len(identifiers) != 1:
        raise ValueError('dotnet-retirement-private-interface-shape')
    interface = graph['interfaces'][next(iter(identifiers))]
    if interface['types']:
        raise ValueError('dotnet-retirement-private-interface-shape')
    row = interface['functions']
    if (set(row) != {'drain'} or row['drain']['kind'] != 'async-freestanding'
            or row['drain']['params'] != [] or row['drain'].get('result') is not None):
        raise ValueError('dotnet-retirement-private-import-shape')
    return True


def prepare(compiler, source: Path, world: str, output: Path, declared: list[str]):
    from tools.dotnet_guest import async_exports, runtime
    from tools.dotnet_guest_bindings import contract_graph, selected_world_metadata, stackful_projection
    from tools.rust_capsule_project import digest, read_file, write_json
    if runtime.ACTIVATION not in declared:
        return source, None
    original = compiler.run('retirement-public-wit', compiler.wasm, 'component', 'wit', source, '--no-docs').decode()
    if len(original.encode()) > MAX_TEXT or 'latent:dotnet-retirement' in original:
        raise ValueError('dotnet-retirement-reserved-source-or-size')
    original_graph = compiler.run('retirement-public-graph', compiler.wasm, 'component', 'wit', source, '--json')
    if len(original_graph) > MAX_TEXT:
        raise ValueError('dotnet-retirement-original-graph-byte-limit')
    graph = contract_graph(json.loads(original_graph))
    _projected, _graph, count = async_exports.projection(original, graph, world, stackful_projection)
    if not count:
        return source, None
    selected = selected_world_metadata(original, graph, world)
    openings = list(re.finditer(r'(?m)^world (%?[A-Za-z][A-Za-z0-9-]*) \{', selected))
    if len(openings) != 1:
        raise ValueError('dotnet-retirement-selected-world-count')
    output.mkdir()
    public = output/'original.wit'
    public.write_text(selected, encoding='utf-8', newline='\n')
    opening = openings[0].end()
    private = output/'selected.wit'
    private.write_text(selected[:opening]+'\n  import '+IDENTITY+';'+selected[opening:]+PRIVATE, encoding='utf-8', newline='\n')
    canonical = compiler.run('retirement-private-canonical', compiler.wasm, 'component', 'wit', private, '--no-docs').decode()
    if len(canonical.encode()) > MAX_TEXT:
        raise ValueError('dotnet-retirement-canonical-byte-limit')
    restored = output/'restored.wit'
    restored.write_text(without_private(canonical), encoding='utf-8', newline='\n')
    empty = output/'empty-core.wasm'
    empty.write_bytes(b'\0asm\x01\0\0\0')
    graphs = []
    for name, candidate in (('public', public), ('restored', restored), ('private', private)):
        embedded = output/(name+'.wasm')
        compiler.run('retirement-'+name+'-embed', compiler.wasm, 'component', 'embed', candidate, empty,
            '--world', world, '-o', embedded)
        raw = compiler.run('retirement-'+name+'-graph', compiler.wasm, 'component', 'wit', embedded, '--json')
        if len(raw) > MAX_TEXT:
            raise ValueError('dotnet-retirement-graph-byte-limit')
        graphs.append(contract_graph(json.loads(raw)))
    if graphs[0] != graphs[1] or not private_import(graphs[2]):
        raise ValueError('dotnet-retirement-public-contract-changed')
    if (read_file(public) != selected.encode() or
            compiler.run('retirement-public-recheck', compiler.wasm, 'component', 'wit', source, '--no-docs').decode() != original):
        raise ValueError('dotnet-retirement-original-source-changed')
    record = {'profile':PROFILE, 'privateImport':IDENTITY, 'publicGraphUnchanged':True,
        'originalDigest':digest(selected.encode()), 'selectedDigest':digest(read_file(private)),
        'authority':'none', 'qualification':'unknown', 'signedExecution':'not-run'}
    write_json(compiler.commands.output/'retirement-port.json', record)
    return private, record
