"""Exact finite WASI HTTP surface; emitted imports never supply authority."""
from __future__ import annotations

from tools.rust_capsule_project import ROOT, digest, read_file, read_json, snapshot

PROFILE = 'rust-wasi-http-0.2.12-v1'
CLOCK = 'latent:clock/monotonic@0.1.0'
HTTP = 'latent:http/streaming@0.3.0'
ACTIVATION = 'latent:runtime/activation@0.1.0'
RETIREMENT = 'latent:rust-http-retirement/owner@0.1.0'
AUTHORITY = frozenset({CLOCK, HTTP, ACTIVATION})
EXTERNAL = frozenset('wasi:' + name + '@0.2.12' for name in (
    'clocks/monotonic-clock', 'http/outgoing-handler', 'http/types',
    'io/error', 'io/poll', 'io/streams'))
ASYNC = {
    'wasi:io/poll@0.2.12': frozenset({'poll', '[method]pollable.block'}),
    'wasi:io/streams@0.2.12': frozenset({
        '[method]input-stream.blocking-read', '[method]input-stream.blocking-skip',
        '[method]output-stream.blocking-write-and-flush', '[method]output-stream.blocking-flush',
        '[method]output-stream.blocking-write-zeroes-and-flush', '[method]output-stream.blocking-splice'}),
}


def names(graph: dict, direction: str, world: str | None = None) -> dict:
    """Read only actual interface references from one selected encoder world."""
    worlds = graph.get('worlds')
    if not isinstance(worlds, list) or len(worlds) > 128:
        raise ValueError('rust-http-world-bound')
    chosen = [row for row in worlds if world is None or row.get('name') == world]
    if len(chosen) != 1:
        raise ValueError('rust-http-selected-world-count')
    result = {}
    for row in chosen[0][direction].values():
        if set(row) != {'interface'}:
            raise ValueError('rust-http-interface-only-surface')
        interface = graph['interfaces'][row['interface']['id']]
        package = graph['packages'][interface['package']]['name']
        base, separator, version = package.partition('@')
        name = base + '/' + interface['name'] + (separator + version if separator else '')
        if name in result:
            raise ValueError('rust-http-duplicate-interface')
        result[name] = interface
    return result


def select(declared: list[str], emitted: list[str]) -> bool:
    """A compatible ordinary client requires three explicit source declarations.

    Missing authority is a build diagnostic. Admission still independently checks
    providers, endpoint policy and grants. No emitted WASI or private interface
    becomes a source capability or is matched to another version.
    """
    if len(declared) > 128 or len(emitted) > 128:
        raise ValueError('rust-http-interface-count')
    if len(set(declared)) != len(declared) or len(set(emitted)) != len(emitted):
        raise ValueError('rust-http-duplicate-interface')
    if any(name.startswith(('wasi:', 'latent:rust-http-retirement/')) for name in declared):
        raise ValueError('rust-http-ambient-or-private-source-import')
    wasi = {name for name in emitted if name.startswith('wasi:')}
    if not wasi:
        return False
    if wasi != EXTERNAL:
        raise ValueError('rust-http-unsupported-external-graph:' + ','.join(sorted(wasi ^ EXTERNAL)))
    if not AUTHORITY <= set(declared):
        raise ValueError('rust-http-requires-explicit-http-activation-monotonic')
    unknown = set(emitted) - EXTERNAL - set(declared) - {RETIREMENT}
    if unknown:
        raise ValueError('rust-http-undeclared-emitted-import:' + ','.join(sorted(unknown)))
    return True


def selected_io(original: bytes) -> bytes:
    """Compiler-owned internal calling conventions, with every other byte intact.

    The macro's async Rust selection does not alter embedded WIT metadata. The
    paired adapter must declare those same eight async types before encoding.
    Applications retain the original nominal public graph and core bytes.
    """
    names = sorted(name.rsplit('.', 1)[-1] for group in ASYNC.values() for name in group)
    if len(names) != len(set(names)) or len(names) != 8:
        raise ValueError('rust-http-selected-io-function-set')
    result = original
    for name in names:
        before = (name + ': func(').encode()
        if original.count(before) != 1:
            raise ValueError('rust-http-selected-io-original-preimage')
        result = result.replace(before, (name + ': async func(').encode())
    return result


def validate_assets(root=ROOT):
    """Authenticate the complete original WIT files, not reconstructed extracts."""
    directory = root / 'sdk/wasi-http-runtime'
    if digest(read_file(directory / 'upstream-source.json', 32768)) != 'sha256:bb3622c15a1a922135cce945d1f87877289a9920ff585f60c9b7cfe2419c3212':
        raise ValueError('rust-http-original-manifest-drift')
    manifest = read_json(directory / 'upstream-source.json', 32768)
    expected = manifest['installedOriginalFiles']
    if len(expected) != 12 or manifest['sha256'] != 'b67efb37e106e55ce722a510d6b5f9c17f083e5fc79afc2badeb12cc313d9487':
        raise ValueError('rust-http-original-source-envelope')
    original = manifest['selectedOriginalFiles']
    if len(original) != 12 or manifest['archiveBytes'] != 135311 or manifest['archiveMembers'] != 28:
        raise ValueError('rust-http-original-archive-envelope')
    actual = {}
    for name, row in original.items():
        if name == 'wit/deps/io.wit':
            path = 'upstream/' + name
        elif name.startswith('wit/deps/'):
            path = name
        elif name in {'Cargo.toml', 'Cargo.toml.orig', 'LICENSE-APACHE', 'LICENSE-MIT', 'wit/wasi-crate.wit'}:
            path = 'upstream/' + name
        else:
            raise ValueError('rust-http-original-path')
        body = read_file(directory / path, 1024 * 1024)
        identity = {'sha256': digest(body), 'bytes': len(body)}
        if identity != {'sha256': 'sha256:' + row['sha256'], 'bytes': row['bytes']}:
            raise ValueError('rust-http-original-byte-drift:' + path)
        actual[path] = identity
    if actual != expected:
        raise ValueError('rust-http-original-installation-drift')
    upstream = snapshot(directory / 'upstream')
    if {'upstream/' + name for name in upstream} != {name for name in actual if name.startswith('upstream/')}:
        raise ValueError('rust-http-original-upstream-extra-input')
    original_io = read_file(directory / 'upstream/wit/deps/io.wit', 1024 * 1024)
    if read_file(directory / 'wit/deps/io.wit', 1024 * 1024) != selected_io(original_io):
        raise ValueError('rust-http-selected-io-projection-drift')
    return actual


def shape(graph, value, *, type_index=False, depth=0, work=None):
    """Compare complete nominal types without mistaking encoder IDs for ABI.

    Options and tuple members carry type references too. The original closed
    .NET comparator is unchanged; this profile handles the complete WASI graph.
    """
    work = [65536] if work is None else work
    work[0] -= 1
    if depth > 64 or work[0] < 0:
        raise ValueError('rust-http-type-depth-or-work-bound')
    def nested(child, referenced=False):
        return shape(graph, child, type_index=referenced, depth=depth+1, work=work)
    if type_index and type(value) is int:
        if not 0 <= value < len(graph['types']):
            raise ValueError('rust-http-type-reference-bound')
        row = graph['types'][value]
        owner = row.get('owner')
        nominal = None
        if owner and 'interface' in owner:
            from tools.dotnet_guest.internal_io import interface_name
            nominal = interface_name(graph, owner['interface'])
        return {'name': row['name'], 'owner': nominal, 'kind': nested(row['kind'])}
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            if key in {'docs', 'stability'}:
                continue
            if key == 'kind' and isinstance(child, dict) and set(child) in ({'method'}, {'async-method'}):
                result[key] = {'method': nested(next(iter(child.values())), True)}
            elif key == 'kind' and child in ('freestanding', 'async-freestanding'):
                result[key] = 'freestanding'
            else:
                result[key] = nested(child, key in {'type', 'types', 'result', 'borrow',
                    'own', 'list', 'option', 'ok', 'err', 'future', 'stream',
                    'constructor', 'static', 'async-static'})
        return result
    if isinstance(value, list):
        return [nested(child, type_index) for child in value]
    return value


def verify_compiled_core(raw: bytes, cores: list[bytes]):
    """Certify encoder metadata processing while preserving every other byte."""
    from tools.dotnet_guest.internal_io import integer
    marker = 'component-type:wit-bindgen:0.62.0:latent:rust-http-runtime@0.1.0:client:encoded world'

    def string(data, position):
        size, position = integer(data, position)
        end = position + size
        if size > 4096 or end > len(data):
            raise ValueError('rust-http-core-metadata-string-bound')
        return data[position:end].decode('utf-8'), end

    def split(data):
        if len(data) > 64 * 1024 * 1024 or data[:8] != b'\0asm\x01\0\0\0':
            raise ValueError('rust-http-core-header-or-bound')
        position, kept, metadata = 8, [], {}
        count = 0
        while position < len(data):
            count += 1
            if count > 256:
                raise ValueError('rust-http-core-section-bound')
            start, kind = position, data[position]
            size, position = integer(data, position + 1)
            end = position + size
            if end > len(data):
                raise ValueError('rust-http-core-section-bound')
            if kind == 0:
                name, payload = string(data[:end], position)
                if name == 'producers' or name.startswith('component-type:'):
                    if name not in ('producers', marker) or name in metadata:
                        raise ValueError('rust-http-core-unknown-or-duplicate-metadata')
                    metadata[name] = data[payload:end]
                else:
                    kept.append(data[start:end])
            else:
                kept.append(data[start:end])
            position = end
        return kept, metadata

    def producers(data):
        count, position = integer(data, 0)
        if count > 8:
            raise ValueError('rust-http-core-producer-bound')
        fields = []
        for _ in range(count):
            name, position = string(data, position)
            size, position = integer(data, position)
            if size > 16:
                raise ValueError('rust-http-core-producer-bound')
            values = []
            for _ in range(size):
                key, position = string(data, position)
                value, position = string(data, position)
                values.append((key, value))
            fields.append((name, values))
        if position != len(data):
            raise ValueError('rust-http-core-producer-trailing')
        return fields

    if not 1 <= len(cores) <= 8:
        raise ValueError('rust-http-core-count')
    before, metadata = split(raw)
    if raw in cores:
        return {'originalCoreExact': True, 'originalSha256': digest(raw)}
    expected = [('language', [('Rust', '')]), ('processed-by', [
        ('rustc', '1.97.1 (8bab26f4f 2026-07-14)')])]
    if set(metadata) != {marker, 'producers'} or producers(metadata['producers']) != expected:
        raise ValueError('rust-http-core-original-metadata')
    expected[1][1].extend([('wit-component', '0.259.0'), ('wit-bindgen-rust', '0.62.0')])
    matches = []
    for core in cores:
        after, observed = split(core)
        if after == before and set(observed) == {'producers'} and producers(observed['producers']) == expected:
            matches.append(core)
    if len(matches) != 1:
        raise ValueError('rust-http-core-executable-or-metadata-drift')
    return {'originalCoreExact': False, 'originalSha256': digest(raw),
        'encodedSha256': digest(matches[0]), 'allNonEncoderMetadataSectionsExact': True,
        'onlyPinnedComponentMetadataProcessed': True}


def validate_adapter(reference: dict, actual: dict):
    """Compare every type/function against original whole WIT and private edge.

    Async is allowed on exactly the selected internal blocking operations and
    drain. Every exported member, resource and error remains exact. Unused
    host-import members may be eliminated by the linker; every emitted import
    still has its original complete signature/type and no unknown member.
    """
    for direction, expected_names in (('imports', AUTHORITY), ('exports', EXTERNAL | {RETIREMENT})):
        expected = names(reference, direction, 'client')
        observed = names(actual, direction)
        if set(expected) != expected_names or set(observed) != expected_names:
            raise ValueError('rust-http-adapter-exact-interface-set')
        for identity in expected_names:
            before, after = expected[identity], observed[identity]
            if direction == 'exports':
                if before['types'].keys() != after['types'].keys() or before['functions'].keys() != after['functions'].keys():
                    raise ValueError('rust-http-adapter-exact-type-or-function-set')
            elif (not after['functions'] or not after['types'].keys() <= before['types'].keys()
                    or not after['functions'].keys() <= before['functions'].keys()):
                raise ValueError('rust-http-adapter-unknown-or-empty-import-member')
            for name, index in after['types'].items():
                if shape(reference, before['types'][name], type_index=True) != shape(actual, index, type_index=True):
                    raise ValueError('rust-http-adapter-original-type-drift:' + identity + '#' + name)
            for name, candidate in after['functions'].items():
                function = before['functions'][name]
                if shape(reference, function) != shape(actual, candidate):
                    raise ValueError('rust-http-adapter-original-function-drift:' + identity + '#' + name)
                allowed = direction == 'exports' and (name in ASYNC.get(identity, ()) or identity == RETIREMENT and name == 'drain')
                kind = candidate['kind']
                asynchronous = kind == 'async-freestanding' or isinstance(kind, dict) and set(kind) == {'async-method'}
                original = function['kind']
                original_async = original == 'async-freestanding' or isinstance(original, dict) and set(original) == {'async-method'}
                if asynchronous != (allowed or original_async):
                    raise ValueError('rust-http-adapter-unreviewed-calling-convention:' + identity + '#' + name)
    return {'imports': sorted(AUTHORITY), 'exports': sorted(EXTERNAL | {RETIREMENT}),
        'wholeOriginalTypesCompared': True, 'exactCallingConventions': True,
        'wholeOriginalExportSurfaceCompared': True, 'emittedImportsAreExactSubsets': True}
