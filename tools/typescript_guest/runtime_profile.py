"""Source-bound TypeScript runtime selection, independent of API qualification.

Ordinary-value compilation keeps its original selection. The native Promise
candidate adds only the maintained activation interface, never a capability or
an implied browser/Node environment. Build success certifies no API behavior.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath
import re

SYNC_PROFILE = 'spidermonkey-public-sync-v1'
ASYNC_PROFILE = 'spidermonkey-activation-promises-v1'
ACTIVATION_INTERFACE = 'latent:runtime/activation@0.1.0'
SELECTED_WORLD = 'lsf:typescript-activation/selected@1.0.0'
ENGINE_SCHEMA = 'latent.typescript.native-engine-input.v1'
WORLD = re.compile(r'^[a-z][a-z0-9-]*:[a-z][a-z0-9-]*/[a-z][a-z0-9-]*@[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$')
DIGEST = re.compile(r'^sha256:[0-9a-f]{64}$')
SOURCE_PINS = {
    'componentizeTree': '4b8d6eb465b5cded6b97c67aaf6fdaa8b62001e2',
    'starlingCommit': '9dda8ba7fcda2e17c6795d402f0478cf4c1f7f37',
    'firefoxCommit': '9dab3d6f643e926a340c391ea30968e940390dec',
    'publicSpiderMonkeyArchiveDigest': 'sha256:c57dc83d93dc04198882b44fea49cd3cb01e0b267bf99fae3b058cb158da684b',
    'publicSDK30ArchiveDigest': 'sha256:0507679dff16814b74516cd969a9b16d2ced1347388024bc7966264648c78bfb',
}


def digest(raw: bytes) -> str:
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def selected_profile(project: dict, graph: dict | None = None) -> str:
    """A captured explicit selection, never package-name or Host-ABI inference."""
    explicit = project.get('runtimeProfile')
    captured = graph.get('selection', {}).get('runtimeProfile') if graph is not None else None
    if 'runtimeProfile' in project and explicit not in (SYNC_PROFILE, ASYNC_PROFILE):
        raise ValueError('unsupported-typescript-runtime-profile')
    if graph is not None and 'runtimeProfile' in graph.get('selection', {}) and captured not in (SYNC_PROFILE, ASYNC_PROFILE):
        raise ValueError('unsupported-captured-typescript-runtime-profile')
    if explicit is not None and captured is not None and explicit != captured:
        raise ValueError('typescript-runtime-profile-capture-mismatch')
    return explicit or captured or SYNC_PROFILE


def selection(profile: str) -> dict:
    if profile not in (SYNC_PROFILE, ASYNC_PROFILE):
        raise ValueError('unsupported-typescript-runtime-profile')
    return {'profile': profile, 'ownerIssue': 745, 'qualification': 'unknown',
            'apiSupport': 'not-evaluated', 'authority': 'none'}


def check_application_bindings(original_graph: dict, world: str) -> None:
    """The native activation ABI is engine-owned, never a JavaScript adapter.

    The compiler may project ordinary application imports/exports through its
    established stackful ABI. It must not synthesize a second synchronous copy
    of the selected engine's real async-lower readiness imports.
    """
    if ACTIVATION_INTERFACE in public_graph(original_graph, world)['imports']:
        raise ValueError('typescript-engine-owned-activation-interface-not-an-application-module')


def validate_engine(value: dict, core: bytes, sdk_inputs: dict[str, bytes], runtime_wit: bytes) -> dict:
    """Bind an explicitly supplied compiler input; no publisher trust is inferred."""
    expected = {'schemaVersion', 'profile', 'coreDigest', 'coreBytes', 'sdkInputs',
                'runtimeWitDigest', 'upstream', 'sourceDerivationDigest', 'buildReceiptDigest',
                'qualification', 'apiSupport', 'inputTrust'}
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError('typescript-native-engine-input-schema')
    if value['schemaVersion'] != ENGINE_SCHEMA or value['profile'] != ASYNC_PROFILE:
        raise ValueError('typescript-native-engine-input-version')
    if value['upstream'] != SOURCE_PINS:
        raise ValueError('typescript-native-engine-upstream-mismatch')
    if core[:8] != b'\x00asm\x01\x00\x00\x00' or not 8 < len(core) <= 64*1024*1024:
        raise ValueError('typescript-native-engine-core-required')
    if type(value['coreBytes']) is not int or value['coreBytes'] != len(core) or value['coreDigest'] != digest(core):
        raise ValueError('typescript-native-engine-core-identity')
    if value['runtimeWitDigest'] != digest(runtime_wit):
        raise ValueError('typescript-native-engine-runtime-wit-mismatch')
    rows = [{'path': name, 'digest': digest(raw), 'size': len(raw)}
            for name, raw in sorted(sdk_inputs.items())]
    if value['sdkInputs'] != rows or not rows or len(rows) > 64:
        raise ValueError('typescript-native-engine-sdk-source-mismatch')
    for row in rows:
        path = PurePosixPath(row['path'])
        if path.is_absolute() or '..' in path.parts or str(path) != row['path']:
            raise ValueError('typescript-native-engine-sdk-path')
    for key in ('sourceDerivationDigest', 'buildReceiptDigest'):
        if not isinstance(value[key], str) or not DIGEST.fullmatch(value[key]):
            raise ValueError('typescript-native-engine-source-material-required')
    if (value['qualification'], value['apiSupport'], value['inputTrust']) != (
            'unknown', 'not-evaluated', 'operator-asserted'):
        raise ValueError('typescript-native-engine-input-cannot-certify-api')
    return value


def world_id(graph: dict, world: dict) -> str:
    package = graph['packages'][world['package']]['name']
    base, separator, version = package.rpartition('@')
    if not separator:
        raise ValueError('typescript-runtime-world-version-required')
    return base+'/'+world['name']+'@'+version


def find_world(graph: dict, identity: str) -> dict:
    matches = [world for world in graph['worlds'] if world_id(graph, world) == identity]
    if len(matches) != 1:
        raise ValueError('typescript-runtime-exact-world-required')
    return matches[0]


def interface_id(graph: dict, index: int) -> str:
    interface = graph['interfaces'][index]
    package = graph['packages'][interface['package']]['name']
    base, separator, version = package.rpartition('@')
    if not separator or not interface['name']:
        raise ValueError('typescript-runtime-versioned-interface-required')
    return base+'/'+interface['name']+'@'+version


def public_graph(graph: dict, identity: str, *, _component_root: bool = False) -> dict:
    """Compare actual parser graphs across relocated numeric IDs.

    Every function kind, parameter/result, resource ownership and type body is
    retained. Unknown parser shapes fail closed rather than become a name-only
    or count-only public-contract comparison.
    """
    def without_docs(value):
        if isinstance(value, dict):
            return {key: without_docs(item) for key, item in value.items() if key != 'docs'}
        if isinstance(value, list):
            return [without_docs(item) for item in value]
        return value

    graph = without_docs(graph)
    visiting = set()
    memo = {}

    def type_ref(value):
        if value is None or isinstance(value, str):
            return value
        if type(value) is not int or not 0 <= value < len(graph['types']):
            raise ValueError('typescript-runtime-unknown-type-reference')
        if value in memo:
            return memo[value]
        if value in visiting:
            raise ValueError('typescript-runtime-recursive-type-unsupported')
        visiting.add(value)
        item = graph['types'][value]
        owner = item.get('owner')
        owner_name = None
        if owner is not None:
            if set(owner) == {'interface'}:
                owner_name = interface_id(graph, owner['interface'])
            elif set(owner) == {'world'}:
                owner_name = world_id(graph, graph['worlds'][owner['world']])
            else:
                raise ValueError('typescript-runtime-unknown-type-owner')
        body = {'name': item['name'], 'owner': owner_name, 'kind': kind(item['kind'])}
        # Hash each complete normalized body once. Child references bind their
        # complete bodies too, without exponentially expanding a shared DAG.
        result = {'typeDigest': digest(json.dumps(body, sort_keys=True, separators=(',', ':')).encode())}
        memo[value] = result
        visiting.remove(value)
        return result

    def kind(value):
        if isinstance(value, str) or type(value) is int:
            return type_ref(value)
        if not isinstance(value, dict) or len(value) != 1:
            raise ValueError('typescript-runtime-unknown-type-kind')
        name, body = next(iter(value.items()))
        if name in ('list', 'option', 'type', 'future', 'stream'):
            return {name: type_ref(body)}
        if name == 'result' and set(body) == {'ok', 'err'}:
            return {name: {key: type_ref(body[key]) for key in ('ok', 'err')}}
        if name == 'tuple' and set(body) == {'types'}:
            return {name: {'types': [type_ref(item) for item in body['types']]}}
        if name == 'record' and set(body) == {'fields'}:
            return {name: {'fields': [{'name': field['name'], 'type': type_ref(field['type'])}
                                      for field in body['fields']]}}
        if name == 'variant' and set(body) == {'cases'}:
            return {name: {'cases': [{'name': case['name'], 'type': type_ref(case['type'])}
                                     for case in body['cases']]}}
        if name == 'handle' and len(body) == 1 and set(body) <= {'own', 'borrow'}:
            return {name: {key: type_ref(item) for key, item in body.items()}}
        if name in ('flags', 'enum', 'resource'):
            # These bodies contain declarations rather than numeric type IDs.
            if not isinstance(body, (list, dict)):
                raise ValueError('typescript-runtime-unknown-declaration-kind')
            return {name: body}
        raise ValueError('typescript-runtime-unsupported-type-kind:'+name)

    def function(value):
        tag = value['kind']
        if isinstance(tag, dict):
            if len(tag) != 1 or not set(tag) <= {'method', 'static', 'constructor', 'async-method', 'async-static'}:
                raise ValueError('typescript-runtime-unknown-function-kind')
            tag = {key: type_ref(item) for key, item in tag.items()}
        elif tag not in ('freestanding', 'async-freestanding'):
            raise ValueError('typescript-runtime-unknown-function-kind')
        return {'name': value['name'], 'kind': tag,
                'params': [{'name': item['name'], 'type': type_ref(item['type'])} for item in value['params']],
                'result': type_ref(value['result'])}

    def items(values):
        result = {}
        for name, item in values.items():
            if set(item) == {'interface'}:
                index = item['interface']['id']
                interface = graph['interfaces'][index]
                key = interface_id(graph, index)
                body = {'types': {key: type_ref(value) for key, value in interface['types'].items()},
                        'functions': {key: function(value) for key, value in interface['functions'].items()}}
            elif set(item) == {'function'}:
                key, body = name, function(item['function'])
            elif set(item) == {'type'}:
                key, body = name, type_ref(item['type'])
            else:
                raise ValueError('typescript-runtime-unknown-world-item')
            if key in result:
                raise ValueError('typescript-runtime-duplicate-world-item')
            result[key] = body
        return result

    if _component_root:
        roots = [item for item in graph['worlds'] if item['name'] == 'root'
                 and graph['packages'][item['package']]['name'] == 'root:component']
        if len(roots) != 1 or len(graph['worlds']) != 1:
            raise ValueError('typescript-runtime-exact-parser-component-root-required')
        world = roots[0]
    else:
        world = find_world(graph, identity)
    return {direction: items(world[direction]) for direction in ('imports', 'exports')}


def public_component_graph(graph: dict) -> dict:
    """Read only the parser's exact synthetic root, not a versioned app world.

    All imported/exported interfaces and their complete type bodies still use
    their authoritative package versions. This wrapper is decoder metadata;
    it cannot become a selectable application or runtime contract identity.
    """
    return public_graph(graph, '', _component_root=True)


def derive_world(canonical_original: bytes, original_graph: dict, world: str,
                 activation_wit: bytes) -> dict[str, bytes]:
    if not WORLD.fullmatch(world) or world.startswith('lsf:typescript-activation/'):
        raise ValueError('typescript-runtime-world-identity')
    find_world(original_graph, world)
    if not canonical_original or not activation_wit:
        raise ValueError('typescript-runtime-original-wit-required')
    root = (f'package lsf:typescript-activation@1.0.0;\n\nworld selected {{\n'
            f'    include {world};\n    import {ACTIVATION_INTERFACE};\n}}\n').encode()
    files = {'world.wit': root, 'deps/application/package.wit': canonical_original}
    # If the original already supplies this interface, final parser-graph
    # validation still binds it to the actual maintained source ABI.
    original = public_graph(original_graph, world)
    if ACTIVATION_INTERFACE not in original['imports']:
        files['deps/activation/package.wit'] = activation_wit
    return files


def check_derived_world(original: dict, derived: dict, activation: dict, world: str) -> dict:
    before = public_graph(original, world)
    after = public_graph(derived, SELECTED_WORLD)
    if after['exports'] != before['exports']:
        raise ValueError('typescript-runtime-public-exports-changed')
    expected = dict(before['imports'])
    activation_world = next(world_id(activation, item) for item in activation['worlds'])
    supplied = public_graph(activation, activation_world)['imports']
    if set(supplied) != {ACTIVATION_INTERFACE}:
        raise ValueError('typescript-runtime-exact-activation-interface-required')
    if ACTIVATION_INTERFACE in expected and expected[ACTIVATION_INTERFACE] != supplied[ACTIVATION_INTERFACE]:
        raise ValueError('typescript-runtime-shadowed-activation-interface')
    expected.update(supplied)
    if after['imports'] != expected:
        raise ValueError('typescript-runtime-import-contract-changed')
    encoded = json.dumps(before, sort_keys=True, separators=(',', ':')).encode()
    return {'profile': ASYNC_PROFILE, 'originalWorld': world, 'selectedWorld': SELECTED_WORLD,
            'publicContractDigest': digest(encoded), 'activationInterface': ACTIVATION_INTERFACE,
            'publicExportsAndOriginalImportsPreserved': True, 'qualification': 'unknown',
            'apiSupport': 'not-evaluated', 'authority': 'none'}
