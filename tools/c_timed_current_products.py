"""Authenticate same-checkout native products for the existing C timer owner.

This is a separate consumer of the source-bound host-codec producer. It never
modifies the frozen historical reader or treats a successful build as a guest
qualification.
"""
from __future__ import annotations

import ast
import hashlib
import math
from pathlib import Path
import re
import subprocess

from tools import qualify_host_codec_native as producer
from tools.java_replay_materials import git_source_identity
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity, source_identity
from tools.rust_capsule_project import ROOT, checked_path, read_file, read_json

HISTORICAL = 'b606b1402961593dd918722a66fe293bfab9b319'
SOURCE = 'tools/qualify_host_codec_native.py'
PRODUCTS = {'latent': 'latent', 'latentd': 'latentd',
    'examples/package': 'package', 'examples/capsule_contracts': 'capsule_contracts',
    'examples/capsule_authoring': 'capsule_authoring'}


def _git(*args):
    result = subprocess.check_output(['git', *args], cwd=ROOT, timeout=60)
    require(len(result) <= 4 * 1024**2, 'c-timed-current-git-output-bound')
    return result


def _literal(raw, name):
    matches = [statement.value for statement in ast.parse(raw).body
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name) and statement.targets[0].id == name]
    require(len(matches) == 1, 'c-timed-current-one-original-declaration')
    return ast.literal_eval(matches[0])


def historical_coverage(materials):
    """Prove the replacement still selects all 177 original native cases."""
    raw = _git('show', HISTORICAL + ':' + SOURCE)
    require(0 < len(raw) <= 128 * 1024, 'c-timed-current-historical-source-bound')
    old_controls = _literal(raw, 'CONTROLS')
    old_recipe = _literal(raw, 'RECIPE')
    current = {stage: (package, needle, cases) for stage, package, needle, cases in producer.CONTROLS}
    require(len(current) == len(producer.CONTROLS), 'c-timed-current-unique-stages')
    old_names = []
    for stage, package, needle, cases in old_controls:
        require(stage in current and current[stage][:2] == (package, needle)
            and set(cases) <= set(current[stage][2]), 'c-timed-current-historical-control-missing')
        old_names.extend(cases)
    require(len(old_names) == len(set(old_names)) == 177, 'c-timed-current-historical-control-count')
    old_materials = set(old_recipe)
    for directory in ('wit', 'schemas', 'examples/echo-contract/wit', 'api/proto'):
        old_materials.update(_git('ls-tree', '-r', '--name-only', HISTORICAL, '--', directory)
                             .decode('utf-8').splitlines())
    require(len(old_materials) == 148 and old_materials <= set(materials),
            'c-timed-current-historical-material-missing')
    return {'controls': len(old_names), 'materials': len(old_materials)}


def current_source():
    head = _git('rev-parse', 'HEAD').decode('ascii').strip()
    require(re.fullmatch('[0-9a-f]{40}', head) is not None, 'c-timed-current-head')
    require(not _git('status', '--porcelain=v1', '--untracked-files=all'), 'c-timed-current-clean-checkout')
    native = source_identity(ROOT)
    require(native == git_source_identity(head), 'c-timed-current-native-source-must-be-byte-exact')
    return head, native



def committed_materials(head, materials):
    """Compare each selected owner input with its exact committed blob bytes."""
    require(re.fullmatch('[0-9a-f]{40}', head) is not None and type(materials) is dict
        and 0 < len(materials) <= 512, 'c-timed-current-material-inventory')
    require(all(type(row) is dict and set(row) == {'sha256', 'bytes'}
        and type(row['bytes']) is int and 0 <= row['bytes'] <= 4 * 1024**2
        and type(row['sha256']) is str and re.fullmatch('sha256:[0-9a-f]{64}', row['sha256'])
        for row in materials.values())
        and sum(row['bytes'] for row in materials.values()) <= 16 * 1024**2,
        'c-timed-current-material-bounds')
    entries = {}
    for item in _git('ls-tree', '-rz', head, '--', *sorted(materials)).split(b'\0'):
        if not item:
            continue
        metadata, name = item.split(b'\t', 1)
        mode, kind, oid = metadata.decode('ascii').split()
        name = name.decode('utf-8')
        require(name not in entries and mode in ('100644', '100755') and kind == 'blob'
                and re.fullmatch('[0-9a-f]{40}', oid) is not None,
                'c-timed-current-committed-material-type')
        entries[name] = oid
    require(set(entries) == set(materials), 'c-timed-current-committed-material-paths')
    for name, expected in materials.items():
        path = checked_path(ROOT / name)
        require(path.is_relative_to(ROOT) and path != ROOT, 'c-timed-current-material-path')
        data = read_file(path, 4 * 1024**2)
        identity = {'bytes': len(data), 'sha256': 'sha256:' + hashlib.sha256(data).hexdigest()}
        oid = hashlib.sha1(b'blob ' + str(len(data)).encode('ascii') + b'\0' + data).hexdigest()
        require(identity == expected and oid == entries[name], 'c-timed-current-material-byte-exact')


def _scope():
    tree = ast.parse((ROOT / SOURCE).read_bytes())
    functions = [item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == 'qualify']
    require(len(functions) == 1, 'c-timed-current-producer-function')
    scopes = []
    for node in ast.walk(functions[0]):
        if isinstance(node, ast.Assign) and any(isinstance(x, ast.Name) and x.id == 'record' for x in node.targets):
            require(isinstance(node.value, ast.Dict), 'c-timed-current-record-shape')
            for key, value in zip(node.value.keys, node.value.values, strict=True):
                if isinstance(key, ast.Constant) and key.value == 'scope':
                    scopes.append(ast.literal_eval(value))
    require(len(scopes) == 1 and type(scopes[0]) is str, 'c-timed-current-one-producer-scope')
    return scopes[0]


def _commands(record, prepared):
    cargo = ['cargo', '--config', str(ROOT / '.cargo/managed-guest.toml')]
    expected = [('source-revision', ['git', 'rev-parse', 'HEAD']),
        ('rust-version', ['rustc', '--version']),
        ('normal-host-build', [*cargo, 'build', '--locked', '-p', 'latent', '-p', 'latentd', '--bins',
            '-p', 'latent-packaging', '--example', 'package', '--example', 'capsule_contracts',
            '-p', 'latent-policy', '--example', 'capsule_authoring'])]
    for stage, package, needle, cases in producer.CONTROLS:
        args = [*cargo, 'test', '--locked', '-p', package, '--lib', needle, '--']
        expected.extend(((stage + '-list', args + ['--list']),
                         (stage + '-run', args + ['--test-threads=1'])))
    rows = record['commands']
    require(type(rows) is list and len(rows) == len(expected) == 91, 'c-timed-current-all-commands')
    elapsed = total = 0
    for ordinal, (row, (stage, argv)) in enumerate(zip(rows, expected, strict=True)):
        require(type(row) is dict and set(row) == {'stage', 'exitCode', 'seconds', 'argv', 'logs'}
            and row['stage'] == stage and row['argv'] == argv
            and type(row['exitCode']) is int and row['exitCode'] == 0
            and type(row['seconds']) in (int, float) and math.isfinite(row['seconds'])
            and 0 <= row['seconds'] <= 1320 and type(row['logs']) is dict
            and set(row['logs']) == {'stdout', 'stderr'}, 'c-timed-current-command-shape')
        elapsed += row['seconds']
        captured = {}
        for stream in ('stdout', 'stderr'):
            path = f'logs/{ordinal:02d}-{stage}.{stream}.txt'
            logged = row['logs'][stream]
            require(type(logged) is dict and set(logged) == {'path', 'bytes', 'sha256'}
                and logged['path'] == path, 'c-timed-current-log-path')
            raw = read_file(prepared / path, 4 * 1024**2)
            observed = {'bytes': len(raw), 'sha256': 'sha256:' + hashlib.sha256(raw).hexdigest()}
            require({key: logged[key] for key in ('bytes', 'sha256')} == observed,
                    'c-timed-current-log-identity')
            total += observed['bytes']
            captured[stream] = raw
        if ordinal == 0:
            require(captured['stdout'].strip().decode('ascii') == record['sourceRevision'],
                    'c-timed-current-revision-log')
        elif ordinal == 1:
            require(captured['stdout'].strip().decode('ascii') == record['compiler'],
                    'c-timed-current-compiler-log')
        elif ordinal >= 3:
            cases = producer.CONTROLS[(ordinal - 3) // 2][3]
            if (ordinal - 3) % 2 == 0:
                producer.exact_list(captured['stdout'], cases)
            else:
                producer.exact_result(captured['stdout'], cases)
    require(elapsed <= 1320.001 and total <= 16 * 1024**2, 'c-timed-current-command-bounds')



def _products(prepared, products):
    require(type(products) is dict and set(products) == set(PRODUCTS),
            'c-timed-current-five-products')
    binaries, total = {}, 0
    for original, alias in PRODUCTS.items():
        path = prepared / 'native-binaries' / original.replace('/', '-')
        identity = file_identity(path, 512 * 1024**2)
        require(identity == products[original], 'c-timed-current-original-product-identity')
        total += identity['bytes']
        binaries[alias] = path
    require(total <= 512 * 1024**2, 'c-timed-current-all-products-byte-bound')
    return binaries


def native_evidence(prepared: Path):
    prepared = checked_path(prepared)
    require(prepared.is_dir(), 'c-timed-current-prepared-directory')
    head, native_source = current_source()
    inputs = producer.materials(ROOT)
    require(len(inputs) == 151, 'c-timed-current-exact-material-count')
    historical = historical_coverage(inputs)
    committed_materials(head, inputs)
    snapshot = read_json(prepared / 'source-inputs.json', 1024**2)
    record = read_json(prepared / 'native-products.json', 1024**2)
    fields = {'schemaVersion', 'status', 'sourceRevision', 'source', 'materials', 'compiler',
        'products', 'commands', 'controlCount', 'nativeCohort', 'wasmtimeAllocationCohort',
        'controls', 'profile', 'signedQualification', 'guestJavaScriptEngineCompiled',
        'guestSourceCompiled', 'historicalReceiptRewritten', 'scope'}
    controls = {stage: list(cases) for stage, _, _, cases in producer.CONTROLS}
    names = [case for _, _, _, cases in producer.CONTROLS for case in cases]
    require(type(record) is dict and set(record) == fields
        and record['schemaVersion'] == 'latent.host-codec.native-products.v1'
        and record['status'] == 'passed' and record['sourceRevision'] == head
        and record['source'] == native_source and record['materials'] == inputs
        and snapshot == {'native': native_source, 'materials': inputs}
        and record['profile'] == 'normal-managed-guest-default-features'
        and record['nativeCohort'] == producer.NATIVE_COHORT
        and record['wasmtimeAllocationCohort'] == producer.codec_wasmtime.COHORT
        and record['scope'] == _scope() and record['controls'] == controls
        and len(producer.CONTROLS) == len(controls) == 44
        and type(record['controlCount']) is int and record['controlCount'] == 250
        and len(names) == len(set(names)) == 250
        and record['signedQualification'] is False and record['guestJavaScriptEngineCompiled'] is False
        and record['guestSourceCompiled'] is False and record['historicalReceiptRewritten'] is False
        and type(record['compiler']) is str and re.fullmatch(r'rustc 1\.97\.1 \([^\r\n]{1,100}\)', record['compiler']),
        'c-timed-current-original-producer-receipt')
    _commands(record, prepared)
    binaries = _products(prepared, record['products'])
    proof = {'compiledSourceRevision': head, 'compiledNativeSource': native_source,
        'consumerNativeSource': native_source, 'compiledSourceByteExact': True,
        'auxiliaryMaterialsByteExact': len(inputs), 'historicalCoverage': historical,
        'currentControls': record['controlCount'], 'reviewedSourceChanges': []}
    before = {'sourceSnapshot': file_identity(prepared / 'source-inputs.json', 1024**2),
        'producerReceipt': file_identity(prepared / 'native-products.json', 1024**2),
        'products': record['products'], 'compiledSource': head}
    return before, proof, binaries
