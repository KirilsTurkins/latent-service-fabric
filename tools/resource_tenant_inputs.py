"""Authenticate a fresh normal native producer without relabeling guest builds."""
from __future__ import annotations
import re
from pathlib import Path

from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_sdk_scratch import PRODUCTS, package_identity
from tools.rust_capsule_project import read_json

PRODUCER_HEAD = 'a4f05f3f243889cc7ba7a0404bdc76afec32d3c2'
PRODUCER_RUN = 39400186766
REPOSITORY_ID = 1337591365
PRODUCER_ARTIFACT = 12255531553
PRODUCER_BYTES = 65925279
PRODUCER_DIGEST = 'sha256:0b5756327d92f45e59e65da2f9d059d6f7e464e59830e43761931c97c4391e8e'
PRODUCER_RECEIPT = {'sha256': 'sha256:f6022e637a01a4bf8740ae0f66c4cc3728c0bc45cca852d1746cff666ed16ad4', 'bytes': 3105}
PRODUCER_SOURCE = {'sha256': 'sha256:cb2d0d7b2a4948669f23461773caf96d9f651107fecb435c13b6ead59e9f3121', 'bytes': 1563}
COMPILER = 'rustc 1.97.1 (8bab26f4f 2026-07-14)'
MATERIALS = frozenset(('.github/workflows/sdk-native-products.yml','.cargo/managed-guest.toml',
    'tools/qualify_rust_capsules.py','tools/toolchain.toml','tools/rust_capsule_build.py',
    'tools/build_observation.py','tools/build_process.py','tools/build_process_linux.py'))
STAGES = ('rust-version','normal-host-build','closed-http-refusal-controls','neutral-resource-signing-controls')
LANGUAGES = ('c','rust','typescript','go','java','dotnet')


def identity(value):
    return type(value) is dict and set(value) == {'sha256','bytes'} and isinstance(value['sha256'],str) \
        and re.fullmatch(r'sha256:[0-9a-f]{64}',value['sha256']) is not None \
        and type(value['bytes']) is int and 0 < value['bytes'] <= 512*1024**2


def validate_producer(value):
    run = value.get('workflow_run',{})
    require(type(value.get('id')) is int and value['id'] == PRODUCER_ARTIFACT
        and value.get('name') == 'sdk-native-products-'+PRODUCER_HEAD
        and value.get('expired') is False
        and type(value.get('size_in_bytes')) is int and value['size_in_bytes'] == PRODUCER_BYTES
        and value.get('digest') == PRODUCER_DIGEST
        and run.get('id') == PRODUCER_RUN and run.get('head_sha') == PRODUCER_HEAD
        and run.get('repository_id') == run.get('head_repository_id') == REPOSITORY_ID,
        'resource-tenant-exact-native-producer')
    return {'artifact':value['id'],'artifactBytes':value['size_in_bytes'],'artifactDigest':value['digest'],
        'run':PRODUCER_RUN,'source':PRODUCER_HEAD,'normalProfile':'normal-managed-guest-default-features',
        'guestComponentsCompiled':False,'signedQualification':False}


def native_products(directory: Path, producer):
    observed = validate_producer(producer)
    require(file_identity(directory/'native-products.json') == PRODUCER_RECEIPT
        and file_identity(directory/'source-inputs.json') == PRODUCER_SOURCE,
        'resource-tenant-pinned-producer-documents')
    receipt = read_json(directory/'native-products.json',65536)
    source = read_json(directory/'source-inputs.json',65536)
    require(receipt.get('schemaVersion') == 'latent.sdk.native-products.v1'
        and receipt.get('status') == 'built' and receipt.get('sourceRevision') == PRODUCER_HEAD
        and receipt.get('profile') == observed['normalProfile']
        and receipt.get('signedQualification') is False and receipt.get('guestComponentsCompiled') is False
        and receipt.get('historicalReceiptRewritten') is False
        and receipt.get('compiler') == COMPILER
        and source == {'native':receipt.get('source'),'materials':receipt.get('materials')},
        'resource-tenant-native-receipt')
    native = receipt['source']
    require(type(native) is dict and set(native) == {'sha256','files','bytes','scope','hermetic','implicitCompilerInputs'}
        and re.fullmatch(r'sha256:[0-9a-f]{64}',native.get('sha256','')) is not None
        and type(native['files']) is int and 1 <= native['files'] <= 16384
        and type(native['bytes']) is int and 0 < native['bytes'] <= 512*1024**2
        and native['scope'] == 'explicit-apps-crates-rust-sdk-workloads-and-workspace-inputs'
        and native['hermetic'] is False and native['implicitCompilerInputs'] == 'not-attested'
        and type(receipt['materials']) is dict and set(receipt['materials']) == MATERIALS
        and all(identity(row) for row in receipt['materials'].values())
        and type(receipt.get('commands')) is list and len(receipt['commands']) == len(STAGES)
        and [row.get('stage') for row in receipt['commands']] == list(STAGES)
        and all(type(row.get('exitCode')) is int and row['exitCode'] == 0
            and type(row.get('seconds')) in (float,int) and 0 <= row['seconds'] <= 1320
            for row in receipt['commands']) and sum(row['seconds'] for row in receipt['commands']) <= 1320,
        'resource-tenant-native-source-or-controls')
    require(type(receipt.get('products')) is dict and set(receipt['products']) == set(PRODUCTS)
        and all(identity(row) for row in receipt['products'].values()),'resource-tenant-native-product-set')
    binaries = {name:directory/'native-binaries'/name.replace('/','-') for name in PRODUCTS}
    require({name:file_identity(path,512*1024**2) for name,path in binaries.items()} == receipt['products'],
        'resource-tenant-native-product-bytes')
    return binaries,{'producer':observed,'nativeSource':native,'materials':receipt['materials'],
        'products':receipt['products'],'receipt':file_identity(directory/'native-products.json'),
        'sourceInputs':file_identity(directory/'source-inputs.json'),
        'compiledCurrentConsumerSource':False,'nativeRebuiltByConsumer':False}


def original_build(directory: Path, language: str, expected):
    require(language in LANGUAGES,'resource-tenant-language')
    marker = read_json(directory/'BUILD-COMPLETE.json')
    files = package_identity(directory,marker)
    observation = read_json(directory/'build-observation.json')
    capsule = read_json(directory/'capsule.json')
    kind = 'c-guest' if language == 'c' else language+'-capsule'
    require(observation.get('buildType') == 'https://latent.dev/build/'+kind+'/v1'
        and marker['componentDigest'] == expected['component']['sha256']
        and files['component.wasm'] == expected['component']
        and file_identity(directory/'BUILD-COMPLETE.json') == expected['buildComplete']
        and file_identity(directory/'build-observation.json') == expected['buildObservation']
        and file_identity(directory/'source-inputs.json') == expected['sourceInputs']
        and capsule.get('metadata') == {'name':'examples/my-greeting','tenant':'examples'}
        and capsule['component']['world'] == 'examples:greeting/service@1.0.0'
        and capsule['exports'] == ['examples:greeting/api@1.0.0'],
        'resource-tenant-original-immutable-component-and-compile')
    return {'language':language,'originalBuild':marker,'component':files['component.wasm'],
        'buildObservation':file_identity(directory/'build-observation.json'),
        'sourceInputs':file_identity(directory/'source-inputs.json'),'packageInputs':files,
        'nativeGuestRecompiled':False,'historicalCompileRecordsRewritten':False}
