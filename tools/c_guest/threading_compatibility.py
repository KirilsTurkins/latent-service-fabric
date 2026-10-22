"""A closed C runtime-profile supplement; preserve the original base inspection."""
from pathlib import Path
import struct

from tools import guest_compatibility_build as base
from tools.c_guest import threading
from tools.build_observation import file_identity
from tools.dev_workflow.common import require, digest, encode
from tools.rust_capsule_project import ROOT, read_file, read_json, write_json

NAME = 'c-threading-compatibility.json'
MEDIA = 'application/vnd.latent.c-threading.compatibility.v1+json'
PORT = 'latent:runtime-native/threads@0.1.0'
WIT = 'wit/platform/native-runtime/package.wit'
WIT_DIGEST = 'sha256:2433ec06c033be01474fd5bf3275c921622eb6720aac344f1307736d09325eb6'
WIT_BYTES = 633
RECIPE = ('tools/c_guest/threading_compatibility.py', WIT)


def inspect(commands, wasm, output, surface, *, profile, proof, transformer):
    require(type(profile) is str and profile == threading.PROFILE,
            'c-compatibility-exact-selected-profile')
    require(type(proof) is dict and set(proof) == {'originalCore', 'derivedCore', 'unboundComponent',
        'derivation', 'publicExport', 'finalComponent'}, 'c-compatibility-complete-proof-inputs')
    require(all(isinstance(proof[name], Path)
        for name in ('originalCore', 'derivedCore', 'unboundComponent', 'derivation', 'finalComponent')),
        'c-compatibility-owned-proof-paths')
    require(type(proof['publicExport']) is str and 0 < len(proof['publicExport'].encode()) <= 512
        and '#' in proof['publicExport']
        and surface['exports'] == [proof['publicExport'].rsplit('#', 1)[0]]
        and set(threading.IMPORTS) <= set(surface['imports']), 'c-compatibility-selected-surface')
    component = read_file(output / 'component.wasm', 8 * 1024 * 1024)
    require(read_file(proof['finalComponent'], 8 * 1024 * 1024) == component,
        'c-compatibility-exact-final-component')
    derivation = read_json(proof['derivation'], 65536)
    original = read_file(proof['originalCore'], 1024 * 1024)
    public_bytes = proof['publicExport'].encode()
    payload = b'LSFCPR01' + struct.pack('<III', 1, len(public_bytes), len(original)) + public_bytes + original
    require(len(payload) <= 1024 * 1024, 'c-compatibility-original-proof-payload-bound')
    require(set(derivation) == {'formatVersion', 'profile', 'publicExport', 'originalCoreDigest',
        'derivedCoreDigest', 'rootRecordBytes', 'canonicalComponentAuthenticated', 'standardRuntimeQualified'}
        and type(derivation['formatVersion']) is int and derivation['formatVersion'] == 1
        and derivation['profile'] == profile and derivation['publicExport'] == proof['publicExport']
        and derivation['originalCoreDigest'] == digest(original)
        and derivation['derivedCoreDigest'] == digest(read_file(proof['derivedCore'], 2 * 1024 * 1024))
        and type(derivation['rootRecordBytes']) is int and derivation['rootRecordBytes'] == 144
        and derivation['canonicalComponentAuthenticated'] is False
        and derivation['standardRuntimeQualified'] is False, 'c-compatibility-original-derivation')
    host_profile = base.declared_host_abi(surface)
    require(host_profile == 'lsf-host-abi-phase3-v5', 'c-compatibility-fixed-base-profile')
    try:
        base.inspect(commands, wasm, output, surface, host_abi_profile=host_profile)
    except ValueError as failure:
        if str(failure) != 'final-component-compatibility-failed; inspect compatibility-inspection.json':
            raise
    else:
        raise ValueError('c-compatibility-original-base-unknown-port-required')
    inspection = read_json(output / 'compatibility-inspection.json', 65536)
    host = base.host_manifest(host_profile)
    require(inspection['componentDigest'] == digest(component)
        and inspection['hostAbiProfile'] == host_profile
        and inspection['hostAbiDigest'] == digest(encode(host))
        and set(inspection['imports']) == set(surface['imports'])
        and len(inspection['imports']) == len(set(inspection['imports']))
        and inspection['findings'] == [
            {'classification': 'unknown-import', 'phase': 'link', 'evidence': 'final-component', 'operation': PORT},
            {'classification': 'unresolved-behavior', 'phase': 'invocation', 'evidence': 'not-evaluated'}],
        'c-compatibility-only-one-closed-supplemental-port')
    verified = output / 'c-threading-compatibility-verified.wasm'
    require(not verified.exists() and not verified.is_symlink(), 'c-compatibility-fresh-verification-output')
    commands.run('c-thread-compatibility-proof', transformer, '--c-thread-bind-v1',
        proof['originalCore'], proof['unboundComponent'], proof['publicExport'], verified)
    require(read_file(verified, 8 * 1024 * 1024) == component,
        'c-compatibility-full-recomputed-component-proof')
    wit = read_file(ROOT / WIT, 65536)
    require(len(wit) == WIT_BYTES and digest(wit) == WIT_DIGEST, 'c-compatibility-exact-native-port-wit')
    record = {'schemaVersion': 'latent.c.threading.compatibility-supplement.v1',
        'selectedCompilerRuntimeProfile': profile,
        'baseInspection': {'digest': digest(read_file(output / 'compatibility-inspection.json')), 'preserved': True},
        'baseHostAbiProfile': host_profile, 'baseHostAbiDigest': inspection['hostAbiDigest'],
        'componentDigest': digest(component), 'fullProofRecomputedByteExact': True,
        'embeddedFullProof': {'digest': digest(payload), 'bytes': len(payload)},
        'originalCoreDigest': digest(original),
        'derivedCoreDigest': derivation['derivedCoreDigest'],
        'derivationDigest': digest(read_file(proof['derivation'], 65536)),
        'publicExport': proof['publicExport'],
        'supplementalPort': {'interface': PORT, 'source': WIT, 'sourceDigest': digest(wit),
                            'sourceBytes': len(wit)},
        'verifier': file_identity(transformer, 'c-threading-transformer'),
        'status': 'source-profile-compatible-runtime-unqualified', 'authority': 'none',
        'independentNativeGrantRequired': True, 'hostProfileValidationRequired': True,
        'signedQualification': False, 'baseInspectionReclassified': False}
    write_json(output / NAME, record)
    return record
