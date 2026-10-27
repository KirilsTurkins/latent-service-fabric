"""Closed NORMAL root-return experiment; no runtime or diagnostic bridge rewrite."""
from __future__ import annotations

from contextlib import ExitStack
import copy
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import shlex
import sys
import stat
import struct
import subprocess
import tempfile
import time
import zipfile

from tools.build_observation import build_environment
from tools.build_process_signals import owned_cancellation
from tools.dotnet_guest.build import build
from tools.dotnet_guest.project import create
from tools.dotnet_guest.runtime import ACTIVATION, CLOCK, RANDOM, WALL
from tools.dotnet_task_runtime_probe import OPERATIONS, configure as task_configuration
from tools.java_http_release_preparation import prepare as prepare_release
from tools.java_http_tenant_node import cleanup_owner
from tools.phase2_operator_process import require, stopped_record
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.phase3_resource_profile import digest as model_digest
from tools.qualify_resource_tenants import client_for_foreign, signed_inputs
from tools.qualify_rust_capsules import inputs
from tools.qualify_sdk_scratch import _prepared_with_inputs
from tools.resource_tenant_node import (FOREIGN_TOKEN, SUBJECTS, TENANTS,
    provider_idle, require_denied_before_guest, scoped_deployment)
from tools.rust_capsule_build import Commands
from tools.rust_capsule_node import (RecordingClient, call, configure, delete_all,
    deploy, sample, selected_revision)
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, read_json, snapshot, write_json

DATA = 'sdk/dotnet-guest/tests/fixtures/root-return/'
DATA_FILES = ('Library.cs', 'world.wit', 'Main-insertion.cs.fragment')
OWNER_CAPS = {'tasks': 8, 'executors': 2, 'queuedWork': 8, 'waits': 16,
              'timers': 8, 'results': 8, 'nativeOwners': 8}
PREREQUISITE = {'run': 40494544599, 'artifact': 12731925685,
    'head': '3f1fca4f05e053d59fb690144a887712e6eff29c',
    'checkout': '13319fe76225d59c5720b1384db20d192cfec5c4',
    'tree': 'd16aa65ad72f5e81334a032691e80be86677df8a',
    'bytes': 76670714, 'sha256': 'eab2202cc3522f225624a771bc446c26af3a422ae201abae0784bb3c38a0582e'}
OLD_BUILD = {'bytes': 18189, 'sha256': 'sha256:d5bb6a74b7a9cdd0c5a6e96a0bb32b6a37c0162027538f526936ef8160eeceed'}
BRANCH = 'test/sdk-dotnet-root-return-20261027'
STEPS = (('examples', 1, 'node-stop-pending'), ('foreign', 2, 'node-stop-drain'),
    ('examples', 3, 'ac7-handled-fault'), ('foreign', 4, 'ac7-handled-cancel'),
    ('examples', 5, 'ac7-settled-idle'), ('foreign', 6, 'ac7-fresh-b-first'),
    ('examples', 8, 'ac7-opaque-unattributed'), ('foreign', 6, 'ac7-fresh-b-after-opaque'),
    ('examples', 9, 'ac7-fault-unattributed'), ('foreign', 6, 'ac7-fresh-b-after-fault'),
    ('examples', 6, 'ac7-fresh-a-final'))
PROFILES = ((CLOCK, 'clockMonotonic', 'activation-monotonic-v1', ['now-nanos'], 'clock'),
    (WALL, 'clockWall', 'activation-wall-v1', ['now-unix-millis'], 'clock'),
    (RANDOM, 'random', 'system-random-v1', ['bytes'], 'random'),
    (ACTIVATION, 'activationRuntime', None, OPERATIONS, 'clock'))
PUBLIC_BYTES = 128 * 1024**2
PROBE_SOURCES = (
    'LsfManagedWorkRoot.g.cs',
    'Service.cs',
    'ServiceWorld.wit.Exports.examples.greeting.ApiExportsInterop.cs',
    'ServiceWorld.wit.Exports.examples.greeting.IApiExports.cs',
    'ServiceWorld.wit.Imports.latent.clock.IMonotonicImports.cs',
    'ServiceWorld.wit.Imports.latent.clock.IWallImports.cs',
    'ServiceWorld.wit.Imports.latent.clock.MonotonicImportsInterop.cs',
    'ServiceWorld.wit.Imports.latent.clock.WallImportsInterop.cs',
    'ServiceWorld.wit.Imports.latent.dotnetManagedWork.IOwnerImports.cs',
    'ServiceWorld.wit.Imports.latent.dotnetManagedWork.OwnerImportsInterop.cs',
    'ServiceWorld.wit.Imports.latent.dotnetRetirement.IOwnerImports.cs',
    'ServiceWorld.wit.Imports.latent.dotnetRetirement.OwnerImportsInterop.cs',
    'ServiceWorld.wit.Imports.latent.random.IRandomImports.cs',
    'ServiceWorld.wit.Imports.latent.random.RandomImportsInterop.cs',
    'ServiceWorld.wit.Imports.latent.runtime.ActivationImportsInterop.cs',
    'ServiceWorld.wit.Imports.latent.runtime.IActivationImports.cs',
    'ServiceWorld_wasm_import_linkage_attribute.cs',
)


def source_map():
    """Actual current Git files, including real SDK fixturedata; no logical rows."""
    raw = subprocess.check_output(['git', 'ls-files', '--stage', '-z'], cwd=ROOT, timeout=15)
    require(len(raw) <= 4*1024**2, 'root-return-git-index-bound')
    rows = []
    for item in raw.split(b'\0'):
        if not item:
            continue
        header, path = item.split(b'\t', 1)
        mode, blob, stage = header.decode('ascii').split()
        require(mode in ('100644', '100755') and stage == '0', 'root-return-git-mode-stage')
        name = path.decode('utf-8')
        require(not name.startswith('/') and '..' not in PurePosixPath(name).parts, 'root-return-git-path')
        rows.append({'path': name, 'mode': mode, 'gitBlob': blob})
    require(0 < len(rows) <= 16384 and len({r['path'] for r in rows}) == len(rows), 'root-return-git-count')
    require(all(DATA+name in {r['path'] for r in rows} for name in DATA_FILES), 'root-return-real-fixture-git-inputs')
    return rows


def extract_prerequisite(archive, output, deadline):
    require(file_identity(archive, PREREQUISITE['bytes']) == {
        'bytes': PREREQUISITE['bytes'], 'sha256': 'sha256:'+PREREQUISITE['sha256']}, 'root-return-official-prerequisite')
    # Bound central metadata BEFORE ZipFile allocates its entry objects.
    with archive.open('rb') as stream:
        stream.seek(max(0, PREREQUISITE['bytes']-65557)); tail = stream.read(65557)
    offset = tail.rfind(b'PK\x05\x06')
    require(offset >= 0 and len(tail)-offset >= 22, 'root-return-prerequisite-eocd')
    end = struct.unpack_from('<4s4H2LH', tail, offset)
    require(end[1:3] == (0, 0) and end[3] == end[4] and 0 < end[4] <= 4096
        and end[5] <= 4*1024**2 and len(tail)-offset == 22+end[7], 'root-return-prerequisite-central-bound')
    selected, total, seen = [], 0, set()
    with zipfile.ZipFile(archive) as source:
        members = source.infolist()
        require(len(members) == end[4], 'root-return-prerequisite-count')
        for item in members:
            require(time.monotonic() < deadline, 'root-return-original-deadline')
            path = PurePosixPath(item.filename)
            require(item.filename and not path.is_absolute() and not any(x in ('', '.', '..') for x in path.parts)
                and '\\' not in item.filename and ':' not in item.filename and len(item.filename.encode()) <= 512,
                'root-return-prerequisite-path')
            key = item.filename.rstrip('/').casefold()
            mode = item.external_attr >> 16
            require(key not in seen and not stat.S_ISLNK(mode) and stat.S_IFMT(mode) in (0, stat.S_IFREG, stat.S_IFDIR)
                and not item.flag_bits & 1 and item.compress_type in (0, 8), 'root-return-prerequisite-type')
            seen.add(key)
            require(0 <= item.file_size <= 192*1024**2, 'root-return-prerequisite-file-bound')
            total += item.file_size
            require(total <= 512*1024**2, 'root-return-prerequisite-expanded-bound')
            selected.append((item, path))
        output.mkdir(mode=0o700)
        for item, path in selected:
            require(time.monotonic() < deadline, 'root-return-original-deadline')
            target = output.joinpath(*path.parts)
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open(item) as stream:
                raw = stream.read(item.file_size+1)
            require(len(raw) == item.file_size, 'root-return-prerequisite-crc-size')
            with target.open('xb') as stream:
                stream.write(raw)
    return {'official': PREREQUISITE, 'members': len(selected), 'expandedBytes': total}


def native_process_compatibility():
    """Exact dated prerequisite identity only; CURRENT execution stays adaptive.

    The reviewed current Windows backoff specializes to the same fixed10ms
    sleep/deadline behavior on this Linux-only programme. No source is replaced.
    """
    raw = read_file(ROOT/'tools/build_process.py', 16384)
    current = {'bytes': 9432, 'sha256': 'sha256:3e7f5965d8334ea86e5154fa7fa733d2aa99a994c579e59554ab6a7c3549a93a'}
    original = {'bytes': 9214, 'sha256': 'sha256:3e462a970e23c127a4e6f0964744d31fad763ed4e9f73fb309e3349db3670497'}
    require({'bytes': len(raw), 'sha256': digest(raw)} == current, 'root-return-current-adaptive-source')
    initialization = b'    idle_seconds = 0.0001 if os.name == "nt" else 0.01\n'
    adaptive = (b'            time.sleep(min(idle_seconds, max(0, deadline - time.monotonic())))\n'
        b'            if os.name == "nt":\n'
        b'                idle_seconds = min(idle_seconds * 2, 0.01)\n'
        b'        elif os.name == "nt":\n'
        b'            idle_seconds = 0.0001\n')
    previous = b'            time.sleep(min(0.01, max(0, deadline - time.monotonic())))\n'
    require(raw.count(initialization) == raw.count(adaptive) == 1, 'root-return-adaptive-exact-blocks')
    inverse = raw.replace(initialization, b'', 1).replace(adaptive, previous, 1)
    require({'bytes': len(inverse), 'sha256': digest(inverse)} == original, 'root-return-adaptive-whole-inverse')
    return original, {'current': current, 'datedPrerequisite': original,
        'wholeSourceSpecializationInverse': True, 'actualExecutionUsesCurrentSource': True,
        'scope': 'Linux fixed10ms sleep/deadline behavior; not a new Windows qualification'}


def original_native(directory):
    """Current core is unchanged; date the reused host, not a new host build."""
    current = inputs('dotnet')
    expected = copy.deepcopy(current)
    rows = [row for row in current['sdk']['files'] if not row['path'].startswith('tests/fixtures/root-return/')]
    require(len(current['sdk']['files'])-len(rows) == len(DATA_FILES), 'root-return-native-sdk-only-data-delta')
    expected['sdk'] = {'files': rows, 'filesDigest': model_digest(rows), 'bytes': sum(r['bytes'] for r in rows)}
    expected['helpers']['dotnet_guest/build.py'] = OLD_BUILD
    dated_process, process_compatibility = native_process_compatibility()
    require(current['helpers']['build_process.py'] == process_compatibility['current'], 'root-return-current-process-input-map')
    expected['helpers']['build_process.py'] = dated_process
    native, _companions, original = _prepared_with_inputs(directory, 'dotnet', expected)
    require(read_json(directory/'source-inputs.json', 16*1024**2) == expected, 'root-return-dated-native-inputs')
    for binary in native.values():
        binary.chmod(0o700)  # ONLY the five receipt-authenticated products.
    return native, {'official': PREREQUISITE, 'authenticated': original,
        'sourceComposition': {'current': current, 'original': expected,
            'onlyChanges': [DATA+name for name in DATA_FILES]+['tools/dotnet_guest/build.py', 'tools/build_process.py'],
            'processCompatibility': process_compatibility},
        'nativeBuildsPerformed': 0}


def fixture(output):
    project = create(output, 'greeting')
    before = (project/'src/Main.cs').read_bytes()
    fragment = read_file(ROOT/(DATA+'Main-insertion.cs.fragment'), 4096)
    marker = b'public class ApiExportsImpl : IApiExports\n{\n'
    require(before.count(marker) == 1, 'root-return-original-main')
    after = before.replace(marker, marker+fragment+b'\n', 1)
    require(after.replace(fragment+b'\n', b'', 1) == before, 'root-return-original-greet-inverse')
    (project/'src/Main.cs').write_bytes(after)
    (project/'src/RootReturn.cs').write_bytes(read_file(ROOT/(DATA+'Library.cs'), 16384))
    (project/'wit/world.wit').write_bytes(read_file(ROOT/(DATA+'world.wit'), 4096))
    for package in ('activation-runtime', 'random'):
        for name, raw in snapshot(ROOT/'wit/platform'/package).items():
            target = project/'wit/deps'/package/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
    return project


def stage_probe_sources(compiled, output, binding, *, compiler_returned):
    """Bounded diagnostic FIRST; retain valid known inputs before strict closure."""
    outputs = binding['outputs']
    names = sorted(name for name in outputs if name.endswith('.cs'))
    details = []
    for name in names[:64]:
        safe = len(name) <= 256 and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]*\.cs', name) is not None
        source = compiled/'generated'/name if safe else None
        size = source.lstat().st_size if source is not None and source.exists() else None
        details.append({'name': name[:256], 'bytes': size, 'safeFlatName': safe})
    write_json(output/'probe-capture-inventory.json', {'formatVersion': 1,
        'outputCount': len(outputs), 'csharpCount': len(names), 'reported': details,
        'reportTruncated': len(names) > 64, 'expectedSources': PROBE_SOURCES,
        'compilerReturned': compiler_returned, 'captureComplete': False})
    # Compiler.compile's pinned successful return is compiled/component.wasm.
    # This is retained before any capture closure/shape check can lose it.
    if compiler_returned:
        component = read_file(compiled/'component.wasm', 64*1024**2)
        (output/'component.wasm').write_bytes(component)
    write_json(output/'probe-generated-bindings.json', binding)
    destination = output/'probe-inputs'; destination.mkdir()
    total, records = 0, {}
    for name in PROBE_SOURCES:
        if name not in outputs:
            continue
        raw = read_file(compiled/'generated'/name, 1024**2); total += len(raw)
        require(total <= 4*1024**2 and hashlib.sha256(raw).hexdigest() == outputs[name],
            'root-return-generated-source-identity')
        (destination/name).write_bytes(raw)
        records[name] = file_identity(destination/name, 1024**2)
    require(tuple(names) == PROBE_SOURCES, 'root-return-generated-source-shape')
    return names, records


def retain_probe_inputs(compiled, output, binding, compiler):
    """Data-only capture inside original build owner, BEFORE its cleanup."""
    outputs = binding['outputs']
    names, records = stage_probe_sources(compiled, output, binding, compiler_returned=True)
    actual = list((compiled/'project/obj').rglob('bindings.json'))
    require(len(actual) == 1 and read_json(actual[0])['outputs'] == outputs, 'root-return-actual-bindings')
    destination = output/'probe-inputs'
    total, found = 0, 0
    for name in names:
        raw = read_file(actual[0].parent/name, 1024**2)
        total += len(raw)
        require(total <= 4*1024**2 and hashlib.sha256(raw).hexdigest() == outputs[name]
            and raw == read_file(compiled/'generated'/name, 1024**2), 'root-return-generated-source-identity')
        found += b'public static unsafe int wasmExportProbe(' in raw
    require(found == 1, 'root-return-complete-actual-probe-helper')
    # Use the ACTUAL ILC response root, not an assumed output directory.
    responses = list((compiled/'project/obj').rglob('*.rsp'))
    require(0 < len(responses) <= 64, 'root-return-ilc-response-count')
    roots, response_bytes, selected_responses = set(), 0, 0
    for path in responses:
        raw = read_file(path, 1024**2); response_bytes += len(raw)
        require(response_bytes <= 4*1024**2, 'root-return-ilc-response-total')
        args = [value for line in raw.decode('utf-8-sig').splitlines() for value in shlex.split(line)]
        if not any(value.startswith('-r:') and Path(value[3:]).name == 'System.Private.CoreLib.dll' for value in args):
            continue
        selected_responses += 1
        for value in args:
            candidate = Path(value)
            if not value.startswith('-') and candidate.suffix == '.dll':
                candidate = (candidate if candidate.is_absolute() else compiled/'project'/candidate).resolve(strict=True)
                require(candidate.is_relative_to((compiled/'project').resolve()), 'root-return-ilc-root-origin')
                roots.add(candidate)
    require(selected_responses == 1 and len(roots) == 1, 'root-return-unique-actual-ilc-root')
    require(compiler.task_wait_port is not None and compiler.filesystem_port is not None, 'root-return-normal-managed-ports')
    selected = {'application.dll': roots.pop(), 'original-System.Private.CoreLib.dll': compiler.task_wait_port.original}
    selected['task-System.Private.CoreLib.dll'] = compiler.task_wait_port.assembly
    selected['final-System.Private.CoreLib.dll'] = compiler.filesystem_port.final_for(compiler.task_wait_port)
    total = 0
    for name, path in selected.items():
        raw = read_file(path, 8*1024**2); total += len(raw)
        require(total <= 32*1024**2 and raw.startswith(b'MZ'), 'root-return-pre-aot-assembly-bound')
        (destination/name).write_bytes(raw)
        records[name] = file_identity(destination/name, 8*1024**2)
    write_json(output/'probe-inputs.json', {'formatVersion': 1, 'completeActualGeneratedSources': names,
        'files': records, 'diagnosticRewritePerformed': False, 'normalCompilationCount': 1,
        'actualIlcRoot': file_identity(destination/'application.dll', 8*1024**2)})


def retain_probe_failure(compiled, output):
    """Keep bounded actual generator bytes if a later compiler phase fails.

    These are independently generated inputs, NOT a successful AOT product or
    confirmed actual AOT source when that later binding check never ran.
    """
    receipt = compiled/'generated/bindings.json'
    if not receipt.is_file():
        return
    binding = read_json(receipt, 4*1024**2)
    _names, records = stage_probe_sources(compiled, output, binding, compiler_returned=False)
    write_json(output/'probe-inputs.json', {'formatVersion': 1, 'files': records,
        'compilerSucceeded': False, 'actualAotBindingConfirmed': False, 'diagnosticRewritePerformed': False})


def node_configuration(work, releases):
    path, value = configure(work, releases, 9, runtime_grants=True, language='dotnet')
    task_configuration(value)
    require(value['providers']['activationRuntime']['limits'] == OWNER_CAPS
        and value['cells'][0]['capacity'] == 1 and value['cells'][0]['queueCapacity'] == 2,
        'root-return-original-owner-profile')
    providers = value['providers']; providers['scalarAliases'] = []
    for contract, name, _profile, _operations, _kind in PROFILES:
        original = providers[name]['identity']
        matches = [r for r in providers['bindings'] if r['contract'] == contract
            and r['consumerService'] == 'examples/my-greeting']
        require(len(matches) == 1, 'root-return-one-original-provider-binding')
        binding = matches[0]; binding['consumerService'] = 'my-greeting'
        foreign = {**original, 'id': original['id']+'-foreign', 'tenant': 'foreign', 'service': 'foreign-'+name.lower()}
        providers['scalarAliases'].append({'source': original['id'], 'identity': foreign})
        providers['bindings'].append({**binding, 'name': binding['name']+'-foreign', 'tenant': 'foreign',
            'providerService': foreign['service'], 'providerBinding': foreign['id']+'-installed'})
    require(len(providers['bindings']) == 13 and len(providers['scalarAliases']) == 4, 'root-return-no-binding-cap-growth')
    value['credentials'].append({'token': FOREIGN_TOKEN, 'subject': SUBJECTS['foreign'], 'tenant': 'foreign', 'role': 'operator'})
    path.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')
    return path, value


def grants(client, node, settings, publication, source, target, tenant):
    selected = []
    for contract, name, profile, operations, kind in PROFILES:
        identity = settings['providers'][name]['identity']
        if tenant == 'foreign':
            identity, = [r['identity'] for r in settings['providers']['scalarAliases'] if r['source'] == identity['id']]
        row, = [r for r in node.startup_record['providers'] if r['id'] == identity['id']]
        require(row['tenant'] == tenant and row['service'] == identity['service']
            and row['capability'] == contract and row['configurationEpoch'] == '1'
            and (profile is None or row['profile'] == profile), 'root-return-actual-installed-provider')
        binding_id = identity['id']+'-installed'; policy_id = identity['id']+'-allow'
        binding = client.directory/(binding_id+'.json')
        write_json(binding, {'formatVersion': 1, 'tenant': tenant, 'capability': contract,
            'providerProfile': row['profile'], 'configurationDigest': row['configurationDigest'],
            'configurationEpoch': 1, 'restriction': {'operations': operations}})
        response = client.call('policy', '--kind', 'provider-binding', 'apply', '--id', binding_id, '--file', binding,
            '--operation-id', 'install-'+binding_id, '--expected-generation', '0')
        require(response['outcomeKnown'] is True and response['category'] == 'success', 'root-return-binding-success')
        policy = client.directory/(policy_id+'.json')
        write_json(policy, {'formatVersion': 1, 'tenant': tenant, 'rules': [{'id': 'root-return', 'effect': 'allow',
            'principals': [{'kind': 'administrator', 'subject': SUBJECTS[tenant]}],
            'services': ['my-greeting'], 'publications': [publication], 'capability': contract,
            'operations': operations, 'resources': {'kind': kind}, 'ceiling': {'operations': 16 if kind == 'random' else 4096,
                'inputBytes': 8 if kind == 'random' else 0, 'outputBytes': 4096 if kind == 'random' else 32768, 'wallTimeMillis': 5000}}]})
        response = client.call('policy', 'apply', '--id', policy_id, '--file', policy,
            '--operation-id', 'allow-'+policy_id, '--expected-generation', '0')
        require(response['outcomeKnown'] is True and response['category'] == 'success', 'root-return-policy-success')
        selected.append({'capability': contract, 'policy': policy_id})
    return deploy(client, source, publication, generation=str(target['generation']), grants=selected)


def positive_sequence(stderr):
    """Existing fixed producer only; parsing never creates qualification credit."""
    require(type(stderr) is bytes and len(stderr) <= 262144, 'root-return-observer-bytes')
    rows, seen, counts = [], set(), {'pending': 0, 'drain': 0}
    for line in stderr.splitlines():
        if not line.startswith(b'LSF-GO-NODE-STOP-TIMER-V1'):
            continue
        require(len(line) <= 128 and len(rows) < 15, 'root-return-observer-record-bound')
        parts = line.split(b'|')
        require(len(parts) == 7 and parts[0] == b'LSF-GO-NODE-STOP-TIMER-V1'
            and parts[1] in (b'pending', b'drain')
            and parts[2] in (b'start-accepted', b'next-entered', b'root-close', b'wait-pending')
            and all(re.fullmatch(rb'0|[1-9][0-9]?', p) for p in parts[3:]), 'root-return-observer-shape')
        sequence, tasks, waits, timers = map(int, parts[3:]); mode = parts[1].decode()
        counts[mode] += 1
        require(0 < sequence <= 15 and sequence not in seen and counts[mode] <= 8
            and tasks <= 8 and waits <= 16 and timers <= 8, 'root-return-observer-identity-limits')
        seen.add(sequence); rows.append({'mode': mode, 'event': parts[2].decode(), 'sequence': sequence,
            'tasks': tasks, 'waits': waits, 'timers': timers})
    for mode in counts:
        close, = [r for r in rows if r['mode'] == mode and r['event'] == 'root-close']
        require((close['tasks'] >= 2 if mode == 'pending' else close['timers'] >= 1)
            and any(r['mode'] == mode and r['event'] == 'wait-pending' and r['sequence'] > close['sequence']
                and r['waits'] > 0 for r in rows), 'root-return-real-close-before-pending')
    return sorted(rows, key=lambda r: r['sequence'])


def signed_node(native, artifact, output, commands, record):
    releases = output/'releases'
    commands.run('neutral-sign', native['examples/capsule_authoring'], 'demo-sign-neutral-resources', releases, artifact)
    component = file_identity(artifact/'component.wasm', 64*1024**2)['sha256']
    release = signed_inputs(releases, component)
    source = releases/release['name']
    # Neutral packaging must preserve compiler ancestry and component, not just its label.
    previous = read_json(artifact/'build-observation.json')
    derived = read_json(source/'build-observation.json')
    require(all(derived[key] == previous[key] for key in ('source', 'parameters', 'componentDigest', 'componentSize', 'buildType')),
        'root-return-neutral-original-compiler-ancestry')
    write_json(output/'neutral-build-observation.json', derived)
    write_json(output/'neutral-release-set.json', read_json(releases/'release-set.json'))
    materials = {r['name']: r for r in derived['materials']}
    require(len(materials) == len(derived['materials']) and all(materials.get(r['name']) == r
        for r in previous['materials'] if r['name'] != 'package-inputs')
        and materials.get('resource-original-build-observation') == {'name': 'resource-original-build-observation',
            'digest': digest(read_file(artifact/'build-observation.json')), 'size': len(read_file(artifact/'build-observation.json'))}
        and {'resource-neutral-package-source', 'resource-neutral-derivation'} <= materials.keys(), 'root-return-neutral-materials')
    with tempfile.TemporaryDirectory(prefix='lsf-root-return-') as temporary, owned_cancellation() as cancellation, ExitStack() as cleanup:
        work = Path(temporary)
        for name in ('node', 'examples'): (work/name).mkdir(mode=0o700)
        configuration, settings = node_configuration(work/'node', releases)
        first = RecordingClient(native['latent'], work/'examples', cancellation, commands.deadline,
            evidence=output/'examples-controls', invocation_timeout_millis=120000, control_timeout_millis=15000)
        first.environment['LSF_GO_NODE_STOP_TIMER_OBSERVER'] = '1'
        node = connect(first, native['latentd'], work/'node', configuration, 'examples', 1)
        cleanup_owner(cleanup, node, record, 'node')
        probe = Probe(node, file_identity(native['latentd'], 512*1024**2))
        clients = {'examples': first, 'foreign': client_for_foreign(first, node, work/'foreign', output/'foreign-controls')}
        targets, sources, publications = {}, {}, {}
        for tenant in TENANTS:
            client = clients[tenant]
            published = client.call('release', 'publish-package', source/'package', '--evidence', source/'evidence/index.json',
                '--operation-id', 'root-return-publish-'+tenant, '--expected-generation', '0')
            require(published['outcomeKnown'] is True and published['category'] == 'success'
                and published['data']['release']['digest'] == component, 'root-return-actual-publication')
            publication = published['data']['operation']['publication']['id']; publications[tenant] = publication
            prepare_release(client, publication, tenant, component, output)
            manifest = client.directory/'deployment.json'
            write_json(manifest, scoped_deployment(read_json(source/'deployment.json'), tenant))
            target = deploy(client, manifest, publication)
            sources[tenant] = manifest
            targets[tenant] = grants(client, node, settings, publication, manifest, target, tenant)
        require(publications['examples'] != publications['foreign'], 'root-return-distinct-tenant-publications')
        denials = []
        original = targets['examples']['grants']
        for ordinal, missing in enumerate((CLOCK, WALL, RANDOM, ACTIVATION)):
            target = targets['examples']
            target = deploy(first, sources['examples'], publications['examples'], generation=str(target['generation']),
                grants=[r for r in original if r['capability'] != missing])
            row = call(first, target, 'greeting', 'probe', [6], 'ac7-missing-grant-'+str(ordinal))
            require_denied_before_guest(row); denials.append({'missing': missing, 'invocation': row})
            targets['examples'] = target
        target = targets['examples']
        targets['examples'] = deploy(first, sources['examples'], publications['examples'], generation=str(target['generation']), grants=original)
        record['grantDenials'] = denials; record['cases'] = []
        for tenant, mode, activation in STEPS:
            client, target = clients[tenant], targets[tenant]
            pin = selected_revision(client, target)
            row = call(client, target, 'greeting', 'probe', [mode], activation)
            response = row['response']
            require(row['processReaped'] and response['outcomeKnown'] is True
                and response['data']['resolvedRevision'] == pin and pin['releaseDigest'] == component, 'root-return-exact-invocation')
            if mode in (8, 9):
                require(row['exitCode'] == 4 and response['error']['code'] == 'guest-trap', 'root-return-normal-negative-not-success')
            else:
                require(row['exitCode'] == 0 and row['decoded'] == [0xAC700000 | mode]
                    and response['category'] == 'success', 'root-return-normal-exact-success')
            usage = response['data']['consumption']
            require(0 < int(usage['cpuFuel']) <= target['budget']['cpuFuel']
                and 0 < int(usage['peakMemoryBytes']) <= target['budget']['memoryBytes']
                and all(int(usage[k]) == 0 for k in ('outboundRequests', 'effectCount', 'logBytes',
                    'stateReadBytes', 'stateWriteBytes', 'blobReadBytes', 'blobWriteBytes')), 'root-return-original-usage')
            record['cases'].append({'tenant': tenant, 'mode': mode, 'invocation': row,
                'originalCauseQualified': False if mode in (8, 9) else None,
                'physical': sample(first, probe, activation, 2), 'providerIdle': provider_idle(client, target)})
            write_json(output/'node-progress.json', record)
        for tenant in TENANTS: delete_all(clients[tenant], [targets[tenant]['name']])
        record['finalPhysical'] = sample(first, probe, 'after-two-tenants', 0)
        clients['foreign'].node = None
        stop(first, node)
        shutdown = stopped_record(node)
        require(shutdown['reaped'] is True and shutdown['record']['clean'] is True, 'root-return-physical-stop')
        stderr = bytes(node.buffers[1]); (output/'node.stderr.txt').write_bytes(stderr)
        record['observer'] = positive_sequence(stderr)
        record['nodeShutdown'] = shutdown
    require(len(record['cases']) == 11 and len(record['grantDenials']) == 4, 'root-return-finite-invocations')


def public_admission(output):
    """Only bounded public source/results; never signing keys or node credentials."""
    parent_deadline = float(os.environ['LSF_ROOT_RETURN_DEADLINE'])
    public = output/'public'; public.mkdir(mode=0o700)
    candidates = list(output.glob('*.json')) + list(output.glob('node.stderr.txt'))
    for folder in ('logs', 'examples-controls', 'foreign-controls', 'build/logs', 'build/probe-inputs',
                   'project/src', 'project/wit'):
        path = output/folder
        if path.exists(): candidates.extend(p for p in path.rglob('*') if p.is_file())
    candidates.extend((output/'build').glob('*.json'))
    candidates.extend(p for p in (output/'build/component.wasm', output/'project/Capsule.csproj',
        output/'project/global.json', output/'project/sdk-lock.json', output/'project/capsule-project.json') if p.exists())
    require(len(candidates) == len(set(candidates)) and len(candidates) <= 4095, 'root-return-public-file-count')
    rows, total = [], 0
    for path in sorted(candidates):
        require(time.monotonic() < parent_deadline, 'root-return-public-original-deadline')
        require(not path.is_symlink(), 'root-return-public-symlink')
        identity = file_identity(path, 64*1024**2)
        total += identity['bytes']; require(total <= PUBLIC_BYTES, 'root-return-public-union')
        name = path.relative_to(output).as_posix(); target = public/name
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = read_file(path, 64*1024**2)
        require(digest(raw) == identity['sha256'] and len(raw) == identity['bytes'], 'root-return-public-copy-identity')
        with target.open('xb') as stream: stream.write(raw)
        rows.append({'path': name, **identity})
    write_json(public/'ADMISSION.json', {'formatVersion': 1, 'files': rows, 'bytes': total,
        'maximumBytes': PUBLIC_BYTES, 'productExecutionPermission': False})


def qualify(output, tools, archive):
    require(sys.platform == 'linux' and sys.version_info >= (3, 13), 'root-return-linux-python313')
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents, 'root-return-output-ownership')
    output = fresh(output)
    parent_deadline = float(os.environ['LSF_ROOT_RETURN_DEADLINE'])
    require(math.isfinite(parent_deadline) and time.monotonic() < parent_deadline <= time.monotonic()+1320,
        'root-return-original-absolute-deadline')
    commands = Commands(ROOT, output, build_environment(output), deadline_seconds=1320, command_seconds=600)
    commands.deadline = parent_deadline-5  # One reserve, shared by every child phase.
    record = {'schemaVersion': 'latent.dotnet.root-return.normal.v1', 'status': 'in-progress',
        'full746Qualified': False, 'fullAC7Qualified': False, 'originalFaultCauseQualified': False,
        'opaqueCauseQualified': False, 'lateGenerationQualified': False, 'deadlineCancellationQualified': False,
        'nativeAccountingComplete': False, 'diagnosticRewritePerformed': False, 'nativeBuildCount': 0,
        'normalComponentBuildCount': 0, 'parentDeadlineMonotonic': parent_deadline, 'cleanupReserveSeconds': 5, 'ownerCaps': OWNER_CAPS, 'programme': list(STEPS)}
    stage = 'source-before'
    try:
        require(not subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, timeout=15), 'root-return-clean-source')
        before = source_map(); write_json(output/'current-git-inputs.json', before)
        with tempfile.TemporaryDirectory(prefix='lsf-root-return-prerequisite-') as temporary:
            directory = Path(temporary)/'normal'
            stage = 'official-prerequisite'
            record['prerequisiteArchive'] = extract_prerequisite(archive, directory, commands.deadline)
            native, original = original_native(directory); record['prerequisite'] = original
            project = fixture(output/'project')
            captured = inventory(snapshot(project)); (output/'project-inputs.json').write_bytes(captured)
            stage = 'one-normal-component-build'
            record['normalComponentBuildCount'] = 1
            artifact = build(project, output/'build', native['examples/capsule_contracts'], native['examples/package'],
                'https://github.com/KirilsTurkins/latent-service-fabric', tools=tools, offline=True,
                _deadline=parent_deadline, _root_return_capture=(retain_probe_inputs, retain_probe_failure))
            require(read_file(artifact/'source-inputs.json') == captured, 'root-return-normal-capture-identity')
            stage = 'signed-two-tenant-node'
            signed_node(native, artifact, output, commands, record)
            require(original_native(directory)[1] == original, 'root-return-native-prerequisite-changed')
        stage = 'source-after'
        require(source_map() == before and not subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, timeout=15),
            'root-return-current-source-changed')
        require(inventory(snapshot(project)) == captured, 'root-return-project-source-changed')
        record.update(status='passed', commands=commands.records, invocations=15,
            actualGeneratedProbe=file_identity(output/'build/probe-inputs.json', 1024**2),
            normalComponent=file_identity(output/'build/component.wasm', 64*1024**2))
        write_json(output/'qualified.json', record)
        public_admission(output)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__, commands=commands.records)
        write_json(output/'FAILED.json', record)
        try:
            public_admission(output)
        except BaseException:
            pass  # Preserve the original failure; absent ADMISSION cannot receive qualification.
        raise
