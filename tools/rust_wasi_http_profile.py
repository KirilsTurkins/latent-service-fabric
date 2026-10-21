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


def validate_adapter(reference: dict, actual: dict):
    """Compare every type/function against original whole WIT and private edge.

    Async is allowed on exactly the selected internal blocking operations and
    drain. Resource owners, signatures, error variants and all unused members
    remain part of the comparison; matching interface labels alone is weaker.
    """
    from tools.dotnet_guest.internal_io import shape
    for direction, expected_names in (('imports', AUTHORITY), ('exports', EXTERNAL | {RETIREMENT})):
        expected = names(reference, direction, 'client')
        observed = names(actual, direction)
        if set(expected) != expected_names or set(observed) != expected_names:
            raise ValueError('rust-http-adapter-exact-interface-set')
        for identity in expected_names:
            before, after = expected[identity], observed[identity]
            if before['types'].keys() != after['types'].keys() or before['functions'].keys() != after['functions'].keys():
                raise ValueError('rust-http-adapter-exact-type-or-function-set')
            for name, index in before['types'].items():
                if shape(reference, index, type_index=True) != shape(actual, after['types'][name], type_index=True):
                    raise ValueError('rust-http-adapter-original-type-drift:' + identity + '#' + name)
            for name, function in before['functions'].items():
                candidate = after['functions'][name]
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
        'wholeOriginalTypesCompared': True, 'exactCallingConventions': True}
