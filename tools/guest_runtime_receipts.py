"""Owner-selected infrastructure receipts; selection never certifies arbitrary APIs."""
from __future__ import annotations

from pathlib import Path

from tools import guest_compatibility as compatibility
from tools.dev_workflow.common import decode, digest, encode, integer, members, require, sha
from tools.rust_capsule_project import inventory, read_file, write_json

SCHEMA = 'latent.guest.runtime-selection.v1'
MAX_BYTES = 65536
OWNER_ISSUES = {'rust': 743, 'go': 742, 'c': 744, 'typescript': 745}
PROFILES = {'rust': 'wasm32-unknown-unknown-panic-abort-v1', 'go': 'go-component-async-v1',
            'c': 'closed-synchronous-v1', 'typescript': 'spidermonkey-public-sync-v1'}
PREFIXES = {
    'rust': ('vendor/lsf/crates/latent-guest/', 'vendor/lsf/crates/latent-component-bindings/'),
    'go': ('vendor/lsf/sdk/go-guest/',),
    'c': ('vendor/lsf/sdk/c-guest/',),
    'typescript': ('vendor/lsf/sdk/typescript-guest/',),
}


def captured_inputs(language: str, files: dict[str, bytes], source_inputs: bytes):
    require(language in PREFIXES, 'runtime-selection-language')
    require(source_inputs == inventory(files), 'runtime-selection-detached-source-inventory')
    original = {name: raw for name, raw in files.items() if name.startswith(PREFIXES[language])}
    require(original and len(original) <= 4096, 'runtime-selection-original-source-required')
    # This is explicitly the captured WIT inventory. The bound owner recipe
    # selects the concrete packages and world; this does not claim reachability.
    bindings = {name: raw for name, raw in files.items()
                if name.endswith('.wit') and (name.startswith('wit/') or name.startswith('vendor/lsf/wit/'))}
    require(bindings and len(bindings) <= 4096, 'runtime-selection-binding-preimage-required')
    raw_graph = files.get('latent.dependencies.lock.json')
    graph = decode(raw_graph, 8 * 1024 * 1024) if raw_graph is not None else None
    require(graph is None or isinstance(graph, dict), 'runtime-selection-graph-object')
    return original, bindings, graph


def material_inputs(materials: list[dict]):
    require(isinstance(materials, list) and len(materials) <= 63, 'runtime-selection-material-limit')
    inputs = []
    for row in materials:
        members(row, {'name', 'digest', 'size'})
        compatibility.token(row['name']); sha(row['digest']); integer(row['size'], 0, 2**64 - 1)
        require(row['name'] != 'standard-runtime-selection', 'runtime-selection-recursive-input')
        inputs.append({'name': row['name'], 'digest': row['digest']})
    require(len({row['name'] for row in inputs}) == len(inputs), 'runtime-selection-duplicate-input')
    return sorted(inputs, key=lambda row: row['name'])


def emit(output: Path, language: str, profile: str, files: dict[str, bytes], source_inputs: bytes,
         component: bytes, materials: list[dict], *, graph: dict | None, binding_digest: str,
         configuration: dict) -> dict:
    compatibility.token(profile)
    original, binding_inputs, captured_graph = captured_inputs(language, files, source_inputs)
    require(graph == captured_graph, 'runtime-selection-stale-graph')
    original_identity = digest(inventory(original))
    binding_preimage = digest(inventory(binding_inputs))
    inputs = material_inputs(materials)
    recipes = [row for row in inputs if row['name'] == 'build-recipe']
    require(len(recipes) == 1, 'runtime-selection-transformer-recipe-required')
    sha(binding_digest)
    # The owner has already executed its maintained binding generation and
    # rechecked the captured originals. The result digest is the actual output,
    # never a hand-authored application patch or an assumed API implementation.
    require(isinstance(configuration, dict) and len(encode(configuration)) <= MAX_BYTES,
            'runtime-selection-configuration-limit')
    transform = {'name': 'maintained-sdk-binding-generation', 'inputScope': 'captured-wit-inventory',
                 'originalDigest': binding_preimage,
                 'resultDigest': binding_digest, 'transformerDigest': recipes[0]['digest'],
                 'configurationDigest': digest(encode(configuration))}
    value = {'schemaVersion': SCHEMA, 'language': language, 'profile': profile,
             'sourceDigest': digest(source_inputs), 'componentDigest': digest(component),
             'graphDigest': digest(encode(graph)) if graph is not None else None,
             'graphState': 'captured' if graph is not None else 'absent',
             'originalRuntimeInputsDigest': original_identity, 'originalRuntimeInputCount': len(original),
             'originalRuntimeInputsScope': 'captured-sdk-inputs',
             'bindingInputsDigest': binding_preimage,
             'toolAndCompilerInputs': inputs,
             'transformations': [transform], 'ownerIssue': OWNER_ISSUES[language],
             'qualification': 'unknown', 'apiSupport': 'not-evaluated', 'authority': 'none'}
    value['identity'] = digest(encode(value))
    validate(value, source=digest(source_inputs), component=digest(component),
             language=language, original=original_identity, profile=profile, graph=graph,
             binding_preimage=binding_preimage, result=binding_digest, materials=materials,
             configuration=configuration)
    write_json(output / 'standard-runtime-selection.json', value)
    raw = read_file(output / 'standard-runtime-selection.json', MAX_BYTES)
    # BuildMaterial is deliberately the existing signed closed three-field
    # shape. Rich role/selection data belongs only to this bounded sidecar.
    return {'name': 'standard-runtime-selection', 'digest': digest(raw), 'size': len(raw)}


def validate(value, *, source=None, component=None, original=None, binding_preimage=None,
             profile=None, language=None, graph=..., result=None, materials=None, configuration=None):
    members(value, {'schemaVersion', 'language', 'profile', 'sourceDigest', 'componentDigest',
        'graphDigest', 'graphState', 'originalRuntimeInputsDigest', 'originalRuntimeInputCount',
        'originalRuntimeInputsScope', 'bindingInputsDigest',
        'toolAndCompilerInputs', 'transformations', 'ownerIssue', 'qualification', 'apiSupport', 'authority', 'identity'})
    require(value['schemaVersion'] == SCHEMA and value['language'] in OWNER_ISSUES, 'runtime-selection-version')
    compatibility.token(value['profile'])
    for name in ('sourceDigest', 'componentDigest', 'originalRuntimeInputsDigest', 'bindingInputsDigest', 'identity'):
        sha(value[name])
    require(value['graphState'] in {'captured', 'absent'} and
            (value['graphDigest'] is None) == (value['graphState'] == 'absent'), 'runtime-selection-graph-state')
    if value['graphDigest'] is not None: sha(value['graphDigest'])
    require(type(value['originalRuntimeInputCount']) is int and 1 <= value['originalRuntimeInputCount'] <= 4096,
            'runtime-selection-source-limit')
    # This scope covers the captured SDK source inputs. Compiler distributions,
    # sysroots and the transitive graph retain their separate material identities;
    # the SDK source digest is not an inventory of an entire standard library.
    require(value['originalRuntimeInputsScope'] == 'captured-sdk-inputs', 'runtime-selection-source-scope')
    inputs = value['toolAndCompilerInputs']
    require(isinstance(inputs, list) and len(inputs) <= 63, 'runtime-selection-material-limit')
    seen = set()
    for row in inputs:
        members(row, {'name', 'digest'}); compatibility.token(row['name']); sha(row['digest'])
        require(row['name'] not in seen, 'runtime-selection-duplicate-input'); seen.add(row['name'])
    require(isinstance(value['transformations'], list) and len(value['transformations']) == 1,
            'runtime-selection-transform-limit')
    transform = members(value['transformations'][0], {'name', 'inputScope', 'originalDigest', 'resultDigest', 'transformerDigest', 'configurationDigest'})
    require(transform['name'] == 'maintained-sdk-binding-generation'
            and transform['inputScope'] == 'captured-wit-inventory'
            and transform['originalDigest'] == value['bindingInputsDigest'], 'runtime-selection-transform-preimage')
    for name in ('originalDigest', 'resultDigest', 'transformerDigest', 'configurationDigest'): sha(transform[name])
    require(any(row['name'] == 'build-recipe' and row['digest'] == transform['transformerDigest'] for row in inputs),
            'runtime-selection-transformer-input')
    require((value['qualification'], value['apiSupport'], value['authority']) == ('unknown', 'not-evaluated', 'none')
            and value['ownerIssue'] == OWNER_ISSUES[value['language']], 'runtime-selection-cannot-certify-api')
    require(len(encode(value)) <= MAX_BYTES and digest(encode({key: item for key, item in value.items() if key != 'identity'})) == value['identity'],
            'runtime-selection-identity-or-size')
    for expected, actual, reason in ((source, value['sourceDigest'], 'source'), (component, value['componentDigest'], 'component'),
                                    (original, value['originalRuntimeInputsDigest'], 'runtime-preimage'), (profile, value['profile'], 'profile'),
                                    (binding_preimage, value['bindingInputsDigest'], 'binding-preimage'),
                                    (result, transform['resultDigest'], 'binding-result'), (language, value['language'], 'language')):
        if expected is not None: require(expected == actual, 'runtime-selection-stale-' + reason)
    if graph is not ...:
        require(value['graphDigest'] == (digest(encode(graph)) if graph is not None else None), 'runtime-selection-stale-graph')
    if materials is not None:
        require(inputs == material_inputs(materials), 'runtime-selection-stale-tool-or-recipe')
    if configuration is not None:
        require(transform['configurationDigest'] == digest(encode(configuration)), 'runtime-selection-stale-configuration')
    return value


def read(raw: bytes, **bindings):
    return validate(decode(raw, MAX_BYTES), **bindings)


def verify_build(value, language, files, source_inputs, component, materials):
    original, bindings, graph = captured_inputs(language, files, source_inputs)
    profile = graph.get('selection', {}).get('runtimeProfile', PROFILES[language]) if graph is not None else PROFILES[language]
    return validate(value, language=language, source=digest(source_inputs), component=digest(component),
                    original=digest(inventory(original)), binding_preimage=digest(inventory(bindings)),
                    profile=profile, graph=graph, materials=materials)
