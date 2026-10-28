"""Closed NORMAL experiment plus separately selected auxiliary Join-cause build."""
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


def stage_probe_sources(compiled, output, binding, *, compiler_returned, expected_sources=PROBE_SOURCES, retain_actual=False):
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
        'reportTruncated': len(names) > 64, 'expectedSources': expected_sources,
        'compilerReturned': compiler_returned, 'captureComplete': False})
    # Compiler.compile's pinned successful return is compiled/component.wasm.
    # This is retained before any capture closure/shape check can lose it.
    if compiler_returned:
        component = read_file(compiled/'component.wasm', 64*1024**2)
        (output/'component.wasm').write_bytes(component)
    write_json(output/'probe-generated-bindings.json', binding)
    destination = output/'probe-inputs'; destination.mkdir()
    total, records = 0, {}
    selected_names = expected_sources
    if retain_actual:
        raw_directory=output/'probe-raw-inputs'
        raw_sources=list(raw_directory.glob('*.cs')) if raw_directory.is_dir() else []
        require(len(raw_sources)<=64,'managed-stage-raw-final-source-count')
        total=sum(len(read_file(p,1024**2)) for p in raw_sources)
        require(total<=4*1024**2,'managed-stage-raw-final-source-bytes')
        require(len(names)<=64 and all(len(n)<=256 and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]*\.cs',n) is not None for n in names),
            'managed-stage-actual-generated-name-bound')
        selected_names = names
    for name in selected_names:
        if name not in outputs:
            continue
        raw = read_file(compiled/'generated'/name, 1024**2); total += len(raw)
        require(total <= 4*1024**2 and hashlib.sha256(raw).hexdigest() == outputs[name],
            'root-return-generated-source-identity')
        (destination/name).write_bytes(raw)
        records[name] = file_identity(destination/name, 1024**2)
    require(tuple(names) == expected_sources, 'root-return-generated-source-shape')
    return names, records


def retain_probe_inputs(compiled, output, binding, compiler, *, _join_cause=False, _stage=False):
    """Data-only capture inside original build owner, BEFORE its cleanup."""
    outputs = binding['outputs']
    expected = MANAGED_STAGE_SOURCES if _stage else PROBE_SOURCES
    names, records = stage_probe_sources(compiled, output, binding, compiler_returned=True, expected_sources=expected, retain_actual=_stage)
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
    if _stage:
        require(compiler.stage_port is not None, 'managed-stage-selected-corelib-required')
        selected['managed-stage-System.Private.CoreLib.dll'] = compiler.stage_port.final_for(compiler.filesystem_port)
    total = 0
    for name, path in selected.items():
        raw = read_file(path, 8*1024**2); total += len(raw)
        require(total <= 32*1024**2 and raw.startswith(b'MZ'), 'root-return-pre-aot-assembly-bound')
        (destination/name).write_bytes(raw)
        records[name] = file_identity(destination/name, 8*1024**2)
    receipt = {'formatVersion': 1, 'completeActualGeneratedSources': names,
        'files': records, 'diagnosticRewritePerformed': False, 'normalCompilationCount': 1,
        'actualIlcRoot': file_identity(destination/'application.dll', 8*1024**2)}
    if _join_cause:
        receipt.update(diagnosticRewritePerformed=True, normalCompilationCount=0, auxiliaryCompilationCount=1)
    write_json(output/'probe-inputs.json', receipt)


def retain_probe_failure(compiled, output, *, _join_cause=False):
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
        'compilerSucceeded': False, 'actualAotBindingConfirmed': False, 'diagnosticRewritePerformed': _join_cause})


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
            write_json(output/f"node-progress-{len(record['cases']):02d}.json", record)
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



def retain_join_cause_inputs(compiled, output, binding, compiler):
    """Capture the distinct auxiliary identity; never label it NORMAL or drained."""
    from tools.dotnet_guest.async_exports import (JOIN_CAUSE_FILE, JOIN_CAUSE_NORMAL,
        JOIN_CAUSE_SELECTED, JOIN_CAUSE_NORMAL_SHA256)
    selected = read_file(compiled/'generated'/JOIN_CAUSE_FILE, 1024**2)
    text = selected.decode('utf-8')
    require(text.count(JOIN_CAUSE_SELECTED) == 1, 'root-return-auxiliary-selected-shape')
    normal = text.replace(JOIN_CAUSE_SELECTED, JOIN_CAUSE_NORMAL).encode('utf-8')
    require(hashlib.sha256(normal).hexdigest() == JOIN_CAUSE_NORMAL_SHA256,
        'root-return-auxiliary-normal-source-inverse')
    expected = {'profile': 'dotnet-ac7-join-cause-auxiliary-v1', 'source': JOIN_CAUSE_FILE,
        'normalSha256': JOIN_CAUSE_NORMAL_SHA256,
        'selectedSha256': hashlib.sha256(selected).hexdigest(), 'taskReturnOperand': 'int',
        'diagnosticWords': [0x4A430001, 0x4A430002, 0x4A430003],
        'physicalRetirementQualified': False, 'originalTrapQualified': False}
    require(binding.get('developmentJoinCause') == expected, 'root-return-auxiliary-binding-receipt')
    retain_probe_inputs(compiled, output, binding, compiler, _join_cause=True)
    write_json(output/'join-cause-auxiliary.json', expected)


def retain_join_cause_failure(compiled, output):
    retain_probe_failure(compiled, output, _join_cause=True)


def build_join_cause_variant(project, output, native, tools, parent_deadline, command_owner=None):
    """Explicit test-only variant. A future reviewed owner must sign/admit it."""
    require(snapshot(project) == snapshot(fixture(output.parent/'paired-normal-project')),
        'root-return-auxiliary-exact-normal-fixture')
    return build(project, output, native['examples/capsule_contracts'], native['examples/package'],
        'https://github.com/KirilsTurkins/latent-service-fabric', tools=tools, offline=True,
        _deadline=parent_deadline,
        _root_return_capture=(retain_join_cause_inputs, retain_join_cause_failure), _root_join_cause=True,
        _root_return_commands=command_owner)


JOIN_BRANCH = 'test/sdk-dotnet-join-cause-20261027'
JOIN_CASE = 'dotnet_join_cause_borrows_one_word_before_unchanged_native_finalization'
JOIN_UNIT_PREFIX = 'development_trap_observer::join_cause_tests::'
JOIN_UNIT_CASES = tuple(JOIN_UNIT_PREFIX + name for name in (
    'scalar_observer_is_closed_single_claim_and_never_replaces_first',
    'failed_call_lift_wrong_digest_shape_and_nonword_are_never_causes',
    'three_words_have_distinct_causes_without_any_frame_or_result_owner'))


class JoinCauseCommands(Commands):
    """One programme's shared16MiB diagnostics and original absolute clock."""
    def __init__(self, root, output, environment, shared, deadline):
        super().__init__(root, output, environment, deadline_seconds=1320, command_seconds=600)
        self.shared, self.original_deadline = shared, deadline
        self.deadline = min(self.deadline, deadline-5)

    def run(self, stage, *command):
        from tools.build_process import run_bounded_result
        remaining = 16*1024**2-self.shared['bytes']
        require(remaining > 0 and len(self.shared['records']) < 128, 'join-cause-command-retention-bound')
        timeout = min(self.command_seconds, self.deadline-time.monotonic(),
                      self.original_deadline-5-time.monotonic())
        require(timeout > 0, 'join-cause-original-deadline')
        start = time.monotonic()
        result = run_bounded_result([str(x) for x in command], cwd=self.root, env=self.environment,
            timeout_seconds=timeout, max_output_bytes=min(4*1024**2, remaining))
        self.shared['bytes'] += len(result.stdout)+len(result.stderr)
        logs = {}
        for channel in ('stdout', 'stderr'):
            path = self.output/'logs'/f'{len(self.records):02d}-{stage}.{channel}.txt'
            with path.open('xb') as stream: stream.write(getattr(result, channel))
            logs[channel] = str(path)
        row = {'stage': stage, 'argv': [str(x) for x in command], 'cwd': str(self.root),
            'exitCode': result.returncode, 'seconds': time.monotonic()-start, 'logs': logs,
            'completedOwnedProcess': True}
        self.records.append(row); self.shared['records'].append(row)
        require(result.returncode == 0, 'join-cause-command-nonzero')
        return result.stdout


def join_cause_observations(raw, components):
    require(type(raw) is bytes and len(raw) <= 4*1024**2, 'join-cause-native-output-bound')
    prefix = 'DOTNET_JOIN_CAUSE_AUX '
    lines = [s[len(prefix):] for s in raw.decode('utf-8').splitlines() if s.startswith(prefix)]
    require(len(lines) == 6 and all(len(s) <= 4096 for s in lines), 'join-cause-six-signed-observations')
    rows = [json.loads(s) for s in lines]
    expected = [(False, 8, 'quiescence'), (False, 9, 'originalFault'), (False, 10, 'unexpected'),
                (True, 8, 'quiescence'), (True, 9, 'originalFault'), (True, 10, 'unexpected')]
    for row, (auxiliary, mode, cause) in zip(rows, expected, strict=True):
        require(type(row) is dict and set(row) == {'component', 'mode', 'auxiliary', 'observation',
            'terminalOutcome', 'acceptedCauseEvidence', 'originalTrapQualified', 'physicalRetirementQualified'},
            'join-cause-closed-observation-fields')
        require(type(row['auxiliary']) is bool and row['auxiliary'] is auxiliary
            and type(row['mode']) is int and row['mode'] == mode
            and row['component'] == components[int(auxiliary)] and row['terminalOutcome'] == 'guest-trap'
            and row['acceptedCauseEvidence'] is (auxiliary and mode != 10)
            and row['originalTrapQualified'] is False and row['physicalRetirementQualified'] is False,
            'join-cause-paired-original-outcomes')
        if auxiliary:
            s = row['observation']
            require(type(s) is dict and set(s) == {'claims', 'invalid', 'cause'}
                and type(s['claims']) is int and s['claims'] == 1
                and s['invalid'] is False and s['cause'] == cause, 'join-cause-exact-single-scalar')
        else:
            require(row['observation'] is None, 'join-cause-normal-unarmed')
    return rows


def join_native_examples(raw, target):
    require(len(raw) <= 4*1024**2, 'join-cause-cargo-inventory-bound')
    found, finished = {}, False
    for line in raw.splitlines():
        require(len(line) <= 1024**2 and not finished, 'join-cause-cargo-inventory-shape')
        item = json.loads(line)
        if item.get('reason') == 'build-finished':
            require(item.get('success') is True, 'join-cause-native-build-failed'); finished = True
        elif item.get('reason') == 'compiler-artifact':
            if Path(item['manifest_path']).resolve() != (ROOT/'crates/latent-packaging/Cargo.toml').resolve(): continue
            name = item['target']['name']
            if item['target']['kind'] != ['example'] or name not in ('capsule_contracts', 'package'): continue
            path = Path(item['executable']).resolve(strict=True)
            require(item['profile']['test'] is False and name not in found
                and path.is_relative_to((target/'debug/examples').resolve())
                and Path(item['target']['src_path']).resolve() == (ROOT/'crates/latent-packaging/examples'/f'{name}.rs').resolve(),
                'join-cause-exact-native-example')
            found[name] = path
    require(finished and set(found) == {'capsule_contracts', 'package'}, 'join-cause-two-current-examples')
    return {'examples/'+k: v for k, v in found.items()}


def join_public_admission(output):
    """Same4095-file/64MiB-file/128MiB union; no native binary or key export."""
    public = output/'public'; public.mkdir(mode=0o700)
    paths = list(output.glob('*.json'))+list((output/'commands/logs').glob('*.txt'))
    for name in ('dotnet-root-return-normal', 'dotnet-root-return-join-cause'):
        folder = output/name
        paths.extend(folder.glob('*.json'))
        paths.extend(p for p in (folder/'logs').glob('*.txt') if p.is_file())
        paths.extend(p for p in (folder/'probe-inputs').glob('*') if p.is_file())
        if (folder/'component.wasm').exists(): paths.append(folder/'component.wasm')
    require(len(paths) == len(set(paths)) <= 4095, 'join-cause-public-count')
    total, rows = 0, []
    for path in sorted(paths):
        require(time.monotonic() < float(os.environ['LSF_ROOT_RETURN_DEADLINE']), 'join-cause-public-deadline')
        require(not path.is_symlink(), 'join-cause-public-symlink')
        identity = file_identity(path, 64*1024**2); total += identity['bytes']
        require(total <= PUBLIC_BYTES, 'join-cause-public-union')
        data = read_file(path, 64*1024**2); require(digest(data) == identity['sha256'], 'join-cause-public-source-changed')
        name = path.relative_to(output).as_posix(); destination = public/name; destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('xb') as stream: stream.write(data)
        rows.append({'path': name, **identity})
    write_json(public/'ADMISSION.json', {'formatVersion': 1, 'files': rows, 'bytes': total,
        'maximumBytes': PUBLIC_BYTES, 'productExecutionPermission': False})


def qualify_join_cause(output, tools, source_commit):
    from tools import ci_rust_artifacts as artifacts
    from tools.build_observation import resolve_tools, file_identity as tool_identity
    import tomllib
    require(os.environ.get('GITHUB_EVENT_NAME') == 'push'
        and os.environ.get('GITHUB_REF') == 'refs/heads/'+JOIN_BRANCH, 'join-cause-closed-push-branch')
    require(sys.platform == 'linux' and sys.version_info >= (3, 13), 'join-cause-linux-python313')
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents, 'join-cause-output-ownership')
    output = fresh(output); deadline = float(os.environ['LSF_ROOT_RETURN_DEADLINE'])
    require(math.isfinite(deadline) and time.monotonic() < deadline <= time.monotonic()+1320, 'join-cause-one-original-deadline')
    shared = {'bytes': 0, 'records': []}; environment = build_environment(output)
    environment.update(CARGO_TARGET_DIR=str(ROOT/'target'), CARGO_INCREMENTAL='0', CARGO_BUILD_JOBS='2',
        CARGO_PROFILE_DEV_DEBUG='0', CARGO_PROFILE_TEST_DEBUG='0', CARGO_PROFILE_DEV_DEBUG_ASSERTIONS='true',
        CARGO_PROFILE_TEST_DEBUG_ASSERTIONS='true', CARGO_PROFILE_DEV_OVERFLOW_CHECKS='true',
        CARGO_PROFILE_TEST_OVERFLOW_CHECKS='true', RUSTUP_TOOLCHAIN='1.97.1', RUSTUP_AUTO_INSTALL='0')
    commands = JoinCauseCommands(ROOT, fresh(output/'commands'), environment, shared, deadline)
    record = {'schemaVersion': 'latent.dotnet.join-cause.auxiliary.v1', 'status': 'in-progress',
        'fullAC7Qualified': False, 'physicalRetirementQualified': False, 'originalTrapQualified': False,
        'nativeAccountingComplete': False, 'reusedDatedNativeFive': False, 'runtimePolicyChanged': False,
        'hermetic': False, 'implicitCompilerInputsAttested': False,
        'limits': {'absoluteSeconds': 1320, 'cleanupReserveSeconds': 5, 'commandSeconds': 600,
            'commandCount': 128, 'diagnosticBytes': 16*1024**2, 'publicBytes': PUBLIC_BYTES,
            'sourceFiles': 8992, 'sourceRawBytes': 75*1024**2, 'sourceArchiveBytes': 82*1024**2},
        'ownerCaps': OWNER_CAPS, 'signedCalls': 6, 'observerUnitCases': list(JOIN_UNIT_CASES)}
    try:
        require(re.fullmatch(r'[0-9a-f]{40}', source_commit), 'join-cause-explicit-source-commit')
        require(subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, timeout=15).decode().strip() == source_commit
            and not subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, timeout=15), 'join-cause-clean-current-source')
        before = source_map(); write_json(output/'current-git-inputs.json', before); record['sourceCommit'] = source_commit
        pins = tomllib.loads(read_file(ROOT/'tools/toolchain.toml', 128*1024).decode())
        native_tools, identities = resolve_tools(pins, ROOT, environment, _deadline=commands.deadline)
        record['toolIdentities'] = identities; environment['RUSTC'] = str(native_tools['rustc'])
        target = ROOT/'target'
        commands.run('build-current-frontends', native_tools['cargo'], '--config', '.cargo/managed-guest.toml',
            'build', '--locked', '-p', 'latent-packaging', '--example', 'capsule_contracts', '--example', 'package',
            '--message-format=json')
        native = join_native_examples(read_file(commands.output/'logs/00-build-current-frontends.stdout.txt', 4*1024**2), target)
        record['nativeFrontends'] = {k: file_identity(v, 512*1024**2) for k, v in native.items()}
        commands.run('build-current-dev-test-host', native_tools['cargo'], '--config', '.cargo/managed-guest.toml',
            'test', '--locked', '-p', 'latent-wasmtime', '--features', 'development-test-host',
            '--lib', '--test', 'local_service', '--no-run', '--message-format=json')
        inventory_path = commands.output/'logs/01-build-current-dev-test-host.stdout.txt'
        suites = (artifacts.Suite('crates/latent-wasmtime/Cargo.toml', 'latent_wasmtime', 'src/lib.rs',
                    JOIN_UNIT_PREFIX, frozenset(JOIN_UNIT_CASES), False, kind='lib'),
                  artifacts.Suite('crates/latent-wasmtime/Cargo.toml', 'local_service', 'tests/local_service.rs',
                    JOIN_CASE, frozenset({JOIN_CASE}), True, kind='test'))
        owners = [artifacts.read_inventory(inventory_path, ROOT, s, target=target) for s in suites]
        record['testExecutables'] = [file_identity(a.executable, 512*1024**2) for a in owners]
        def command_owner(root, folder, env): return JoinCauseCommands(root, folder, env, shared, deadline)
        components = []
        for name, auxiliary in (('dotnet-root-return-normal', False), ('dotnet-root-return-join-cause', True)):
            project = fixture(output/(name+'-project')); captured = inventory(snapshot(project))
            if components: require(captured == first_capture, 'join-cause-normal-auxiliary-source-pair')
            else: first_capture = captured
            if auxiliary:
                artifact = build_join_cause_variant(project, output/name, native, tools, deadline, command_owner)
            else:
                artifact = build(project, output/name, native['examples/capsule_contracts'], native['examples/package'],
                    'https://github.com/KirilsTurkins/latent-service-fabric', tools=tools, offline=True,
                    _deadline=deadline, _root_return_capture=(retain_probe_inputs, retain_probe_failure),
                    _root_return_commands=command_owner)
            require(read_file(artifact/'source-inputs.json') == captured, 'join-cause-built-source-inputs')
            components.append(file_identity(artifact/'component.wasm', 64*1024**2)['sha256'])
        require(components[0] != components[1], 'join-cause-distinct-components')
        record['components'] = components
        def library_probe(argv, *, cwd, env, timeout, maximum):
            require(argv == ['rustc', '--print', 'target-libdir'] and cwd == ROOT and timeout == 30 and maximum == 4096,
                'join-cause-library-probe-owner')
            commands.command_seconds = 25; commands.environment = env
            value = commands.run('rust-library-path', native_tools['rustc'], *argv[1:]); require(len(value) <= maximum, 'join-cause-library-probe-bound')
            return 0, value
        for ordinal, (suite, owner) in enumerate(zip(suites, owners, strict=True)):
            commands.environment = artifacts.cargo_environment(ROOT, owner, environment, target=target, execute=library_probe)
            commands.environment.update(LSF_GUEST_SDK_LANGUAGE='dotnet', LSF_GUEST_CAPSULES=str(output))
            commands.command_seconds = 25
            selection = (suite.filter, '--exact', '--ignored') if ordinal else (suite.filter,)
            listed = commands.run('list-'+str(ordinal), owner.executable, *selection, '--list')
            require(len(listed) <= 65536, 'join-cause-list-bound'); artifacts.validate_listing(listed, suite)
            commands.command_seconds = 300 if ordinal else 30
            raw = commands.run('execute-'+str(ordinal), owner.executable, *selection, '--show-output', '--test-threads=1')
            passed = 1 if ordinal else 3
            require(re.search(rf'^test result: ok\. {passed} passed; 0 failed; 0 ignored; 0 measured; [0-9]+ filtered out; finished in [0-9.]+s$',
                raw.decode(), re.M), 'join-cause-exact-native-test-result')
            if ordinal: record['observations'] = join_cause_observations(raw, components)
        require(source_map() == before and not subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, timeout=15),
            'join-cause-source-after')
        require(components == [file_identity(output/name/'component.wasm', 64*1024**2)['sha256']
            for name in ('dotnet-root-return-normal', 'dotnet-root-return-join-cause')]
            and identities == [tool_identity(path, name) for name, path in sorted(native_tools.items())],
            'join-cause-components-tools-after')
        require(record['testExecutables'] == [file_identity(a.executable, 512*1024**2) for a in owners]
            and record['nativeFrontends'] == {k: file_identity(v, 512*1024**2) for k, v in native.items()},
            'join-cause-native-products-after')
        record.update(status='passed', sourceBeforeEqualsAfter=True, diagnosticBytes=shared['bytes'],
            commandCount=len(shared['records']))
        write_json(output/'qualified.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', errorCategory=type(error).__name__)
        write_json(output/'FAILED.json', record)
        raise
    finally:
        write_json(output/'commands.json', shared['records'])
        try: join_public_admission(output)
        except BaseException:
            if record['status'] == 'passed': raise


JOIN_REPLAY = {'artifact': 12759125468, 'run': 40557689997, 'job': 122378040399,
    'producer': '86d97b84310819f096e406a722423e27b0e793c6', 'bytes': 15120874,
    'sha256': 'sha256:f542e7493f4b212edc17c06d94a2f2e0a913670b1480a7e062fbeb535091f714',
    'members': 377, 'expandedBytes': 50623729}
JOIN_REPLAY_COMPONENTS = (
    'sha256:e97e968aad905f6c27a31c0a16da15533a3f6a42b0deba2e290c04c881cbd28c',
    'sha256:891cd60bf016c21637630aadb4e13796b131f9c7b0a3985edcbb91f23fabdc25')
JOIN_REPLAY_WIT = {
    'wit/deps/activation-runtime/package.wit': 'wit/platform/activation-runtime/package.wit',
    'wit/deps/clock/package.wit': 'wit/platform/clock/package.wit',
    'wit/deps/random/package.wit': 'wit/platform/random/package.wit',
    'wit/world.wit': DATA+'world.wit'}
JOIN_REPLAY_FIXTURE_TRANSLATION = {
    'path': 'crates/latent-wasmtime/tests/local_service/fixture.rs', 'mode': '100644',
    'producerGitBlob': 'a19dbcdef71bb2147e426753b67bb5b3eebbcb99',
    'currentGitBlob': '4d4e2ee16abca8713acefaee82a657816c90e795'}
JOIN_TASK_RETURN_CASE = 'dotnet_join_cause_canonical_task_return_witness_preserves_original_failure'
# Filled from the reviewed concrete source freeze; never discover/authorize a
# changed native source at execution time. Guest/compiler inputs stay original.
JOIN_TASK_RETURN_TRANSLATIONS = {
    "crates/latent-wasmtime/Cargo.toml": {
        "path": "crates/latent-wasmtime/Cargo.toml",
        "mode": "100644",
        "producerGitBlob": "4449762d4ec62401201e339060fee3edbd673318",
        "currentGitBlob": "1d157ea092c6a214b03f02e0bc0cdfeeec801209"
    },
    "crates/latent-wasmtime/src/backend.rs": {
        "path": "crates/latent-wasmtime/src/backend.rs",
        "mode": "100644",
        "producerGitBlob": "53415e204b998a397f0499cb346750cbd0cff6b0",
        "currentGitBlob": "eada5ec00a63fd2390c0065a8c49133a7c83d111"
    },
    "crates/latent-wasmtime/src/development_trap_observer.rs": {
        "path": "crates/latent-wasmtime/src/development_trap_observer.rs",
        "mode": "100644",
        "producerGitBlob": "48ea7fb574727cd58580fb21270b42e64996721a",
        "currentGitBlob": "5a3b1558199a9c5090cd516aeee07ad6870a5c53"
    },
    "crates/latent-wasmtime/src/lib.rs": {
        "path": "crates/latent-wasmtime/src/lib.rs",
        "mode": "100644",
        "producerGitBlob": "19361ecabfd630bbc91c51f3d51aa70e337646d2",
        "currentGitBlob": "3d27f8fd14c8e2ee3711f66298d4a070add43f53"
    },
    "crates/latent-wasmtime/src/values/memory.rs": {
        "path": "crates/latent-wasmtime/src/values/memory.rs",
        "mode": "100644",
        "producerGitBlob": "17c1a6186a5d114a8188c460b0e13ccfed15778e",
        "currentGitBlob": "4469f84f7ec4a0fec46bf2122905a6edd1d2c453"
    },
    "crates/latent-wasmtime/tests/local_service.rs": {
        "path": "crates/latent-wasmtime/tests/local_service.rs",
        "mode": "100644",
        "producerGitBlob": "aacae1406d37ba1db950851f74facd4eaf45b17c",
        "currentGitBlob": "73cf596dd58d84e8322fe53b62404656d2303b1a"
    },
    "crates/vendor/wasmtime/Cargo.toml": {
        "path": "crates/vendor/wasmtime/Cargo.toml",
        "mode": "100644",
        "producerGitBlob": "8638a4d81998f74aa2b499f066f5321ace6fb73c",
        "currentGitBlob": "af1622f6b2a056cc680e4f00ca849622700acca5"
    },
    "crates/vendor/wasmtime/README.latent.md": {
        "path": "crates/vendor/wasmtime/README.latent.md",
        "mode": "100644",
        "producerGitBlob": "fb99e211e750f106d52aecef9778389a4e76c597",
        "currentGitBlob": "3b8c8a5b53304635fa4ca10e23658c1379e49785"
    },
    "crates/vendor/wasmtime/UPSTREAM.latent.json": {
        "path": "crates/vendor/wasmtime/UPSTREAM.latent.json",
        "mode": "100644",
        "producerGitBlob": "a82f0bd7bde7c6b1a2ae88cd8e9a4b0b24803301",
        "currentGitBlob": "5a76bff5036e1e88f8f88449a36544e6c8490991"
    },
    "crates/vendor/wasmtime/latent-dynamic-memory.patch": {
        "path": "crates/vendor/wasmtime/latent-dynamic-memory.patch",
        "mode": "100644",
        "producerGitBlob": "19928c6dc8132246e9d91400e85c753f1556a863",
        "currentGitBlob": "6f3b2ca1010c64dea66b0d6f47609b705efa0ec3"
    },
    "crates/vendor/wasmtime/src/runtime/component/concurrent/func.rs": {
        "path": "crates/vendor/wasmtime/src/runtime/component/concurrent/func.rs",
        "mode": "100644",
        "producerGitBlob": "8a2f1103e409d9d4f344a7e28141ce207de39fe2",
        "currentGitBlob": "d61a920bbbc23ac361e84ae9130f0ecf3a38e7a8"
    },
    "crates/vendor/wasmtime/src/runtime/component/dynamic_memory.rs": {
        "path": "crates/vendor/wasmtime/src/runtime/component/dynamic_memory.rs",
        "mode": "100644",
        "producerGitBlob": "877b2ae231095305770eaab11c6784e85cfc9674",
        "currentGitBlob": "c4bceb96e7384c66f17af07915914ae9879ca64d"
    },
    "crates/vendor/wasmtime/src/runtime/component/mod.rs": {
        "path": "crates/vendor/wasmtime/src/runtime/component/mod.rs",
        "mode": "100644",
        "producerGitBlob": "8116c8190b40dcdcff36e7eda59c7ce3680937cc",
        "currentGitBlob": "7ff5c6eecc37b2b5662bacf3abe180e66c7fa344"
    },
    "tools/host_codec_wasmtime.py": {
        "path": "tools/host_codec_wasmtime.py",
        "mode": "100644",
        "producerGitBlob": "57dae86dcb443c3529e43a0f6e7ba26eb86da666",
        "currentGitBlob": "79acdd745c2a7618f4bf5f0c4a02d6679ddf52d1"
    },
    "tools/tests/test_host_codec_wasmtime.py": {
        "path": "tools/tests/test_host_codec_wasmtime.py",
        "mode": "100644",
        "producerGitBlob": "d3be3827a28b5e4f47bdda255c9f011329e62f22",
        "currentGitBlob": "6914fc9169fba13e493340936696c32c6560b60a"
    },
    "crates/latent-capabilities/src/broker/session.rs": {
        "path": "crates/latent-capabilities/src/broker/session.rs",
        "mode": "100644",
        "producerGitBlob": "b4377314d6214cacbdb9b3c721631a1e1213f397",
        "currentGitBlob": "7054a5f4e9e7b2930529fb187d8f1a08498d5699"
    },
    "crates/latent-wasmtime/src/host/capabilities.rs": {
        "path": "crates/latent-wasmtime/src/host/capabilities.rs",
        "mode": "100644",
        "producerGitBlob": "c6fef438439c7a42cad2aa680a2f4ce30b2075be",
        "currentGitBlob": "37f942b3a918d20aec392f95650e7ce184b5eb35"
    },
    "crates/latent-wasmtime/src/values.rs": {
        "path": "crates/latent-wasmtime/src/values.rs",
        "mode": "100644",
        "producerGitBlob": "3181ff92a4d21fb368e4f054dbaa68ce58d62fff",
        "currentGitBlob": "a327503cae1e7fb8b4aa249cb2bf42c2a01c6f0a"
    },
    "crates/latent-wasmtime/src/host/runtime.rs": {
        "path": "crates/latent-wasmtime/src/host/runtime.rs",
        "mode": "100644",
        "producerGitBlob": "9fbba6c1eb8bcf080254eea1ea3d149fcfce20e6",
        "currentGitBlob": "a8c3e75eeb015488b59874c9a6baaec76b9a3d39"
    }
}


def join_replay_extract(archive, output, deadline):
    """Authenticate the fixed failed attempt before restoring its real packages."""
    require(file_identity(archive, JOIN_REPLAY['bytes']) ==
        {'bytes': JOIN_REPLAY['bytes'], 'sha256': JOIN_REPLAY['sha256']}, 'join-replay-official-archive')
    with archive.open('rb') as stream:
        stream.seek(-22, 2); end = struct.unpack('<4s4H2LH', stream.read(22))
        require(end[:5] == (b'PK\x05\x06', 0, 0, 377, 377) and end[7] == 0
            and end[5] <= 4*1024**2 and end[6]+end[5]+22 == JOIN_REPLAY['bytes'],
            'join-replay-bounded-central-directory')
        with zipfile.ZipFile(archive) as source:
            members = source.infolist()
            require(len(members) == 377 and source.start_dir == end[6], 'join-replay-fixed-member-count')
            seen, ranges, total = set(), [], 0
            for item in members:
                require(time.monotonic() < deadline-5, 'join-replay-original-deadline')
                path = PurePosixPath(item.filename); mode = item.external_attr >> 16
                require(item.filename and not path.is_absolute() and path.as_posix() == item.filename
                    and not any(v in ('', '.', '..') for v in path.parts)
                    and '\\' not in item.filename and ':' not in item.filename
                    and len(item.filename.encode()) <= 512 and not item.is_dir()
                    and stat.S_IFMT(mode) in (0, stat.S_IFREG) and not item.extra and not item.comment
                    and item.compress_type == 8 and item.flag_bits == 8,
                    'join-replay-native-closed-zip-shape')
                key = item.filename.casefold()
                require(key not in seen and not any(key.startswith(v+'/') or v.startswith(key+'/')
                    for v in seen), 'join-replay-unique-path-prefix')
                seen.add(key); total += item.file_size
                require(0 <= item.file_size <= 64*1024**2 and total <= PUBLIC_BYTES
                    and item.compress_size > 0 and item.file_size <= item.compress_size*4096,
                    'join-replay-member-expansion-bound')
                stream.seek(item.header_offset); header = stream.read(30)
                require(len(header) == 30, 'join-replay-local-header-bound')
                local = struct.unpack('<4s5H3L2H', header)
                require(local[0] == b'PK\x03\x04' and local[2:4] == (8, 8)
                    and local[6:9] == (0, 0, 0) and local[10] == 0
                    and 0 < local[9] <= 512, 'join-replay-local-header-shape')
                require(stream.read(local[9]) == item.filename.encode('ascii'), 'join-replay-local-central-name')
                finish = item.header_offset+30+local[9]+item.compress_size
                require(finish+16 <= end[6], 'join-replay-local-range')
                stream.seek(finish)
                require(struct.unpack('<4s3L', stream.read(16)) ==
                    (b'PK\x07\x08', item.CRC, item.compress_size, item.file_size),
                    'join-replay-local-central-descriptor')
                ranges.append((item.header_offset, finish+16))
            ranges.sort()
            require(total == JOIN_REPLAY['expandedBytes'] and ranges[0][0] == 0
                and all(a[1] == b[0] for a, b in zip(ranges, ranges[1:]))
                and ranges[-1][1] == end[6], 'join-replay-disjoint-complete-local-ranges')
            require(source.getinfo('ADMISSION.json').file_size <= 128*1024, 'join-replay-admission-byte-bound')
            admission = json.loads(source.read('ADMISSION.json'))
            require(set(admission) == {'formatVersion', 'files', 'bytes', 'maximumBytes', 'productExecutionPermission'}
                and admission['formatVersion'] == 1 and admission['maximumBytes'] == PUBLIC_BYTES
                and admission['productExecutionPermission'] is False and len(admission['files']) == 376,
                'join-replay-original-admission')
            declared = {}
            for row in admission['files']:
                require(set(row) == {'path', 'bytes', 'sha256'} and row['path'] not in declared
                    and type(row['bytes']) is int and 0 <= row['bytes'] <= 64*1024**2
                    and re.fullmatch(r'sha256:[0-9a-f]{64}', row['sha256']), 'join-replay-admission-row')
                declared[row['path']] = row
            require(set(declared) == {i.filename for i in members}-{'ADMISSION.json'}
                and sum(v['bytes'] for v in declared.values()) == admission['bytes'],
                'join-replay-no-omitted-original-payload')
            for item in members:
                require(time.monotonic() < deadline-5, 'join-replay-extraction-deadline')
                with source.open(item) as body: raw = body.read(item.file_size+1)
                require(len(raw) == item.file_size, 'join-replay-crc-size')
                if item.filename != 'ADMISSION.json':
                    require(declared[item.filename] == {'path': item.filename,
                        'bytes': len(raw), 'sha256': digest(raw)}, 'join-replay-original-entry-digest')
                target = output/item.filename; target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as destination: destination.write(raw)
    return admission


def join_replay_packages(original, output, current, deadline, *, task_return_witness=False):
    producer = read_json(original/'current-git-inputs.json', 4*1024**2)
    old = {r['path']: r for r in producer}; now = {r['path']: r for r in current}
    require(len(old) == len(producer) and len(now) == len(current), 'join-replay-unique-git-inputs')
    def protected(path):
        return ((path.startswith(('crates/', 'apps/')) and path.endswith(('.rs', '.toml')))
            or path in ('Cargo.toml', 'Cargo.lock', 'rust-toolchain.toml', 'tools/toolchain.toml')
            or path.startswith(('.cargo/', 'tools/dotnet_guest/', DATA))
            or path in ('tools/dotnet_guest_bindings.py', 'tools/dotnet_task_runtime_probe.py'))
    excluded = 'crates/latent-wasmtime/tests/local_service.rs'
    protected_paths = {p for p in old.keys() | now.keys() if protected(p) and p != excluded}
    translation = JOIN_REPLAY_FIXTURE_TRANSLATION
    require(translation['path'] in protected_paths, 'join-replay-explicit-fixture-source')
    translations = {translation['path']: translation}
    if task_return_witness:
        require(JOIN_TASK_RETURN_TRANSLATIONS, 'join-task-return-reviewed-native-source-freeze')
        translations.update(JOIN_TASK_RETURN_TRANSLATIONS)
        protected_paths.update(translations)
    for path in protected_paths:
        require(path in old and path in now, 'join-replay-protected-source-set')
        if path in translations:
            reviewed = translations[path]
            require(old[path] == {'path': path, 'mode': reviewed['mode'],
                'gitBlob': reviewed['producerGitBlob']}
                and now[path] == {'path': path, 'mode': reviewed['mode'],
                    'gitBlob': reviewed['currentGitBlob']},
                'join-replay-reviewed-native-translation' if task_return_witness
                else 'join-replay-reviewed-fixture-translation')
        else:
            require(old[path] == now[path], 'join-replay-original-component-and-observer-implementation')
    restored, components = [], []
    inputs = [read_json(original/name/'source-inputs.json', 1024**2)
        for name in ('dotnet-root-return-normal', 'dotnet-root-return-join-cause')]
    for index, name in enumerate(('dotnet-root-return-normal', 'dotnet-root-return-join-cause')):
        folder = original/name; files = list(folder.rglob('*'))
        require(sum(p.is_file() for p in files) == (178, 179)[index], 'join-replay-complete-variant-tree')
        shutil.copytree(folder, output/name)
        for relative, git_path in JOIN_REPLAY_WIT.items():
            require(time.monotonic() < deadline-5, 'join-replay-restore-deadline')
            raw = read_file(ROOT/git_path, 4096)
            identity = {'size': len(raw), 'digest': digest(raw)}
            blob = hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
            require(all(v[relative] == identity for v in inputs)
                and old[git_path] == now[git_path] and old[git_path]['gitBlob'] == blob,
                'join-replay-exact-original-wit-body')
            target = output/name/relative; target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as destination: destination.write(raw)
            restored.append({'variant': name, 'path': relative, 'gitInput': now[git_path], **identity})
        package = read_json(output/name/'package-source.json', 65536)
        require(package['entrypoint'] == 'component.wasm' and len(package['layers']) == 9,
            'join-replay-original-package-shape')
        for layer in package['layers']:
            path = PurePosixPath(layer['source'])
            require(not path.is_absolute() and path.as_posix() == layer['source']
                and not any(v in ('', '.', '..') for v in path.parts)
                and (output/name/path).is_file(), 'join-replay-complete-package-layers')
        identity = file_identity(output/name/'component.wasm', 64*1024**2)
        require(identity['sha256'] == JOIN_REPLAY_COMPONENTS[index], 'join-replay-original-component')
        marker = read_json(output/name/'BUILD-COMPLETE.json', 65536)
        require(marker['packageAssembled'] is True and marker['componentDigest'] == identity['sha256']
            and marker['observationDigest'] == digest(read_file(output/name/'build-observation.json', 65536))
            and marker['sourceDigest'] == digest(read_file(output/name/'source-inputs.json', 1024**2)),
            'join-replay-original-build-receipt')
        components.append(identity['sha256'])
    provenance = {'originalProducer': JOIN_REPLAY['producer'], 'protectedGitPaths': len(protected_paths),
        'reviewedNativeHarnessTranslation': translation,
        'restoredOriginalWitBodies': restored, 'components': components,
        'datedObserverUnitsPassed': list(JOIN_UNIT_CASES), 'observerUnitsExecutedAgain': False}
    if task_return_witness:
        provenance.pop('observerUnitsExecutedAgain')
        provenance.update(reviewedNativeEngineTranslations=translations,
            datedObserverUnitsUsedAsCurrentCoverage=False,
            currentObserverUnitResults='current-observer-controls.json')
    return provenance


def join_replay_variant_map(output):
    rows = []
    for name, count in (('dotnet-root-return-normal', 182), ('dotnet-root-return-join-cause', 183)):
        files = [p for p in (output/name).rglob('*') if p.is_file()]
        require(len(files) == count and all(not p.is_symlink() for p in files), 'join-replay-variant-count-type')
        rows.extend({'path': p.relative_to(output).as_posix(), **file_identity(p, 64*1024**2)}
            for p in sorted(files))
    return rows


def qualify_join_cause_replay(output, archive, source_commit, *, task_return_witness=False):
    """Reuse actual components with an explicit old or TaskReturn-stage owner."""
    from tools import ci_rust_artifacts as artifacts
    from tools.build_observation import resolve_tools, file_identity as tool_identity
    import tomllib
    require(type(task_return_witness) is bool, 'join-task-return-closed-mode')
    require(os.environ.get('GITHUB_EVENT_NAME') == 'push'
        and os.environ.get('GITHUB_REF') == 'refs/heads/'+JOIN_BRANCH, 'join-replay-closed-push')
    require(sys.platform == 'linux' and sys.version_info >= (3, 13), 'join-replay-platform')
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
        'join-replay-output-ownership')
    output = fresh(output); deadline = float(os.environ['LSF_ROOT_RETURN_DEADLINE'])
    require(math.isfinite(deadline) and time.monotonic() < deadline <= time.monotonic()+1320,
        'join-replay-one-original-clock')
    shared = {'bytes': 0, 'records': []}; environment = build_environment(output)
    environment.update(CARGO_TARGET_DIR=str(ROOT/'target'), CARGO_INCREMENTAL='0', CARGO_BUILD_JOBS='2',
        CARGO_PROFILE_DEV_DEBUG='0', CARGO_PROFILE_TEST_DEBUG='0', CARGO_PROFILE_DEV_DEBUG_ASSERTIONS='true',
        CARGO_PROFILE_TEST_DEBUG_ASSERTIONS='true', CARGO_PROFILE_DEV_OVERFLOW_CHECKS='true',
        CARGO_PROFILE_TEST_OVERFLOW_CHECKS='true', RUSTUP_TOOLCHAIN='1.97.1', RUSTUP_AUTO_INSTALL='0')
    commands = JoinCauseCommands(ROOT, fresh(output/'commands'), environment, shared, deadline)
    record = {'schemaVersion': 'latent.dotnet.join-cause.replay.v1', 'status': 'in-progress',
        'originalArtifact': JOIN_REPLAY, 'signedCalls': 6, 'observerUnitsExecutedAgain': False,
        'fullAC7Qualified': False, 'physicalRetirementQualified': False, 'originalTrapQualified': False,
        'nativeAccountingComplete': False, 'runtimePolicyChanged': False, 'ownerCaps': OWNER_CAPS}
    original = output/'original-attempt'; original.mkdir()
    if task_return_witness:
        record.update(schemaVersion='latent.dotnet.canonical-task-return.replay.v1',
            plannedSignedCalls=record.pop('signedCalls'),
            stage='canonicalTaskReturnBeforeScopeExit', oldPostCallProgrammeQualified=False,
            currentObserverUnitCases=list(JOIN_UNIT_CASES))
    try:
        require(re.fullmatch(r'[0-9a-f]{40}', source_commit), 'join-replay-source-commit')
        require(subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, timeout=15).decode().strip() == source_commit
            and not subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, timeout=15),
            'join-replay-clean-source')
        before = source_map(); write_json(output/'current-git-inputs.json', before)
        admission = join_replay_extract(archive, original, deadline)
        record['originalAdmission'] = {'files': len(admission['files']), 'bytes': admission['bytes']}
        record['provenance'] = join_replay_packages(original, output, before, deadline,
            task_return_witness=task_return_witness)
        variants_before = join_replay_variant_map(output)
        expected_variants = {r['path']: r for r in admission['files'] if r['path'].startswith(
            ('dotnet-root-return-normal/', 'dotnet-root-return-join-cause/'))}
        require(len(expected_variants) == 357, 'join-replay-original-variant-set')
        for row in record['provenance']['restoredOriginalWitBodies']:
            name = row['variant']+'/'+row['path']
            require(name not in expected_variants, 'join-replay-only-missing-wit')
            expected_variants[name] = {'path': name, 'bytes': row['size'], 'sha256': row['digest']}
        require(len(expected_variants) == len(variants_before) and all(
            expected_variants.get(r['path']) == r for r in variants_before), 'join-replay-staged-exact-payloads')
        record['provenance']['retainedVariantIdentities'] = variants_before
        write_json(output/'replay-provenance.json', record['provenance'])
        pins = tomllib.loads(read_file(ROOT/'tools/toolchain.toml', 128*1024).decode())
        native_tools, identities = resolve_tools(pins, ROOT, environment, _deadline=commands.deadline)
        record['toolIdentities'] = identities; environment['RUSTC'] = str(native_tools['rustc'])
        if task_return_witness:
            from tools import host_codec_wasmtime
            record['nativeSourceCohort'] = host_codec_wasmtime.verify(ROOT)
            commands.run('build-current-local-service', native_tools['cargo'], '--config', '.cargo/managed-guest.toml',
                'test', '--locked', '-p', 'latent-wasmtime', '--features', 'development-test-host',
                '--lib', '--test', 'local_service', '--no-run', '--message-format=json')
        else:
            commands.run('build-current-local-service', native_tools['cargo'], '--config', '.cargo/managed-guest.toml',
                'test', '--locked', '-p', 'latent-wasmtime', '--features', 'development-test-host',
                '--test', 'local_service', '--no-run', '--message-format=json')
        selected_case = JOIN_TASK_RETURN_CASE if task_return_witness else JOIN_CASE
        suite = artifacts.Suite('crates/latent-wasmtime/Cargo.toml', 'local_service', 'tests/local_service.rs',
            selected_case, frozenset({selected_case}), True, kind='test')
        owner = artifacts.read_inventory(commands.output/'logs/00-build-current-local-service.stdout.txt',
            ROOT, suite, target=ROOT/'target')
        executable_before = file_identity(owner.executable, 512*1024**2)
        def library_probe(argv, *, cwd, env, timeout, maximum):
            require(argv == ['rustc', '--print', 'target-libdir'] and cwd == ROOT and timeout == 30 and maximum == 4096,
                'join-replay-library-probe')
            commands.command_seconds = 25; commands.environment = env
            value = commands.run('rust-library-path', native_tools['rustc'], *argv[1:])
            require(len(value) <= maximum, 'join-replay-library-bound')
            return 0, value
        if task_return_witness:
            unit_suite = artifacts.Suite('crates/latent-wasmtime/Cargo.toml', 'latent_wasmtime',
                'src/lib.rs', JOIN_UNIT_PREFIX, frozenset(JOIN_UNIT_CASES), False, kind='lib')
            unit_owner = artifacts.read_inventory(commands.output/'logs/00-build-current-local-service.stdout.txt',
                ROOT, unit_suite, target=ROOT/'target')
            unit_before = file_identity(unit_owner.executable, 512*1024**2)
            commands.environment = artifacts.cargo_environment(ROOT, unit_owner, environment,
                target=ROOT/'target', execute=library_probe)
            commands.command_seconds = 25
            unit_listed = commands.run('list-current-observer-controls', unit_owner.executable,
                JOIN_UNIT_PREFIX, '--list')
            require(len(unit_listed) <= 65536, 'join-task-return-unit-list-bound')
            artifacts.validate_listing(unit_listed, unit_suite)
            commands.command_seconds = 30
            unit_raw = commands.run('execute-current-observer-controls', unit_owner.executable,
                JOIN_UNIT_PREFIX, '--show-output', '--test-threads=1')
            require(re.search(r'^test result: ok\. 3 passed; 0 failed; 0 ignored; 0 measured; [0-9]+ filtered out; finished in [0-9.]+s$',
                unit_raw.decode(), re.M), 'join-task-return-current-unit-result')
            require(file_identity(unit_owner.executable, 512*1024**2) == unit_before,
                'join-task-return-unit-executable-after')
            record.update(currentObserverUnitsPassed=True, currentUnitExecutable=unit_before,
                observerUnitsExecutedAgain=True)
            write_json(output/'current-observer-controls.json', {'sourceCommit': source_commit,
                'cases': list(JOIN_UNIT_CASES), 'currentSourcePassed': True,
                'priorDatedUnitsRetagged': False, 'executable': unit_before})
        commands.environment = artifacts.cargo_environment(ROOT, owner, environment,
            target=ROOT/'target', execute=library_probe)
        commands.environment.update(LSF_GUEST_SDK_LANGUAGE='dotnet', LSF_GUEST_CAPSULES=str(output))
        commands.command_seconds = 25
        selection = (selected_case, '--exact', '--ignored')
        listed = commands.run('list-signed', owner.executable, *selection, '--list')
        require(len(listed) <= 65536, 'join-replay-list-bound'); artifacts.validate_listing(listed, suite)
        commands.command_seconds = 300
        raw = commands.run('execute-signed', owner.executable, *selection, '--show-output', '--test-threads=1')
        require(re.search(r'^test result: ok\. 1 passed; 0 failed; 0 ignored; 0 measured; [0-9]+ filtered out; finished in [0-9.]+s$',
            raw.decode(), re.M), 'join-replay-exact-native-result')
        record['observations'] = (join_task_return_observations(raw, JOIN_REPLAY_COMPONENTS)
            if task_return_witness else join_cause_observations(raw, JOIN_REPLAY_COMPONENTS))
        if task_return_witness:
            record['executedSignedCalls'] = len(record['observations'])
        require(source_map() == before and not subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, timeout=15)
            and executable_before == file_identity(owner.executable, 512*1024**2)
            and identities == [tool_identity(path, name) for name, path in sorted(native_tools.items())]
            and file_identity(archive, JOIN_REPLAY['bytes']) ==
                {'bytes': JOIN_REPLAY['bytes'], 'sha256': JOIN_REPLAY['sha256']}
            and join_replay_variant_map(output) == variants_before
            and list(JOIN_REPLAY_COMPONENTS) == [file_identity(output/name/'component.wasm', 64*1024**2)['sha256']
                for name in ('dotnet-root-return-normal', 'dotnet-root-return-join-cause')],
            'join-replay-current-code-products-after')
        if task_return_witness:
            require(file_identity(unit_owner.executable, 512*1024**2) == unit_before,
                'join-task-return-unit-product-final')
        record.update(status='passed', sourceCommit=source_commit, sourceBeforeEqualsAfter=True,
            testExecutable=executable_before, commandCount=len(shared['records']), diagnosticBytes=shared['bytes'])
        write_json(output/'qualified.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', errorCategory=type(error).__name__)
        write_json(output/'FAILED.json', record)
        raise
    finally:
        write_json(output/'commands.json', shared['records'])
        # Retain the complete authenticated prior trees, restored WIT and old
        # failed attempt as dated input, alongside this attempt's own results.
        public = output/'public'; public.mkdir()
        paths = [p for p in output.rglob('*') if p.is_file() and public not in p.parents]
        require(len(paths) <= 4095, 'join-replay-public-count')
        total, rows = 0, []
        for path in sorted(paths):
            require(time.monotonic() < deadline and not path.is_symlink(), 'join-replay-public-clock-type')
            identity = file_identity(path, 64*1024**2); total += identity['bytes']
            require(total <= PUBLIC_BYTES, 'join-replay-public-union')
            name = path.relative_to(output).as_posix(); target = public/name; target.parent.mkdir(parents=True, exist_ok=True)
            raw = read_file(path, 64*1024**2); require(digest(raw) == identity['sha256'], 'join-replay-public-source-after')
            with target.open('xb') as stream: stream.write(raw)
            rows.append({'path': name, **identity})
        write_json(public/'ADMISSION.json', {'formatVersion': 1, 'files': rows, 'bytes': total,
            'maximumBytes': PUBLIC_BYTES, 'productExecutionPermission': False})


def join_task_return_observations(raw, components):
    """A distinct stage witness; never reinterpret the failed post-call oracle."""
    require(type(raw) is bytes and len(raw) <= 4*1024**2, 'task-return-native-output-bound')
    prefix = 'DOTNET_JOIN_TASK_RETURN '
    lines = [s[len(prefix):] for s in raw.decode('utf-8').splitlines() if s.startswith(prefix)]
    require(len(lines) == 6 and all(len(s) <= 4096 for s in lines), 'task-return-six-paired-rows')
    rows = [json.loads(s) for s in lines]
    rejections = {'claimRepeated', 'componentMismatch', 'contractMismatch', 'exportMismatch',
        'callFailed', 'liftFailed', 'wrongShape', 'unknownWord', 'duplicateCapture',
        'sessionUnavailable', 'sessionClosed', 'nativeDuplicateReturn', 'nativeInvalidReturn'}
    expected = [(False, 8, 'quiescence'), (False, 9, 'originalFault'), (False, 10, 'unexpected'),
                (True, 8, 'quiescence'), (True, 9, 'originalFault'), (True, 10, 'unexpected')]
    for row, (auxiliary, mode, cause) in zip(rows, expected, strict=True):
        require(type(row) is dict and set(row) == {'component', 'mode', 'auxiliary', 'stage',
            'taskReturnWitness', 'postCallObservation', 'rejection', 'terminalOutcome',
            'outerInvocationSucceeded', 'canonicalTaskReturnCauseEvidence',
            'oldPostCallProgrammeQualified', 'originalTrapQualified', 'physicalRetirementQualified'},
            'task-return-closed-row')
        require(type(row['auxiliary']) is bool and row['auxiliary'] is auxiliary
            and type(row['mode']) is int and row['mode'] == mode
            and row['component'] == components[int(auxiliary)]
            and row['stage'] == 'canonicalTaskReturnBeforeScopeExit'
            and row['terminalOutcome'] == 'guest-trap' and row['outerInvocationSucceeded'] is False
            and row['canonicalTaskReturnCauseEvidence'] is (auxiliary and mode != 10)
            and row['oldPostCallProgrammeQualified'] is False
            and row['originalTrapQualified'] is False and row['physicalRetirementQualified'] is False,
            'task-return-distinct-failed-outer-contract')
        if auxiliary:
            witness, post = row['taskReturnWitness'], row['postCallObservation']
            require(type(witness) is dict and set(witness) == {'claims', 'invalid', 'cause'}
                and type(witness['claims']) is int and witness['claims'] == 1
                and witness['invalid'] is False and witness['cause'] == cause,
                'task-return-one-typed-known-cause')
            require(type(post) is dict and set(post) == {'claims', 'invalid', 'cause'}
                and type(post['claims']) is int and post['claims'] == 1
                and type(post['invalid']) is bool and post['cause'] in (None, cause)
                and (row['rejection'] is None or type(row['rejection']) is str
                     and row['rejection'] in rejections),
                'task-return-retain-original-post-call-disposition')
            require(post['invalid'] or post['cause'] == cause, 'task-return-no-old-model-laundering')
            require((row['rejection'] is not None) if post['invalid'] else row['rejection'] is None,
                'task-return-explicit-original-refusal')
        else:
            require(row['taskReturnWitness'] is None and row['postCallObservation'] is None
                and row['rejection'] is None, 'task-return-normal-unarmed')
    return rows


# New programme: diagnostic-only guest checkpoints. Historical modes stay selected separately.
MANAGED_STAGE_BRANCH = 'test/sdk-dotnet-managed-stage-20261028'
MANAGED_STAGE_SOURCES = tuple(sorted((*PROBE_SOURCES,
    'ServiceWorld.wit.Imports.latent.developmentDotnetStage.IStageImports.cs',
    'ServiceWorld.wit.Imports.latent.developmentDotnetStage.StageImportsInterop.cs')))
MANAGED_STAGE_DATED = {'originalPair': JOIN_REPLAY, 'normalComponent': JOIN_REPLAY_COMPONENTS[0],
    'auxiliaryComponent': JOIN_REPLAY_COMPONENTS[1], 'notInvokedAgain': True, 'notRebuiltAgain': True,
    'failedWitnessHead': '26e968e398e1530d63a0fef9f950768ab7668c2c',
    'failedWitnessRun': 40603456909, 'failedWitnessArtifact': 12780256386,
    'failedWitnessArtifactSHA256': '6aa9f627d86f4b30e2cc093f9fe423c55eec7199d41eefd429dd9d9f30935247'}


def managed_stage_fixture(output, source_inputs, deadline):
    from tools.dotnet_guest.managed_work import stage_library
    project = fixture(output)
    vendor = project/'vendor/lsf'
    for name, row in source_inputs.items():
        require(time.monotonic() < deadline-5, 'managed-stage-fixture-original-clock')
        raw = read_file(ROOT/name,4*1024**2)
        require(digest(raw) == row['digest'] and len(raw) == row['size'], 'managed-stage-current-source-copy')
        path = vendor/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(raw)
    lock = read_json(project/'sdk-lock.json'); lock['sdk'] = json.loads(inventory(snapshot(vendor)))
    (project/'sdk-lock.json').write_bytes(json.dumps(lock,indent=2).encode()+b'\n')
    original = read_file(project/'src/RootReturn.cs',16384)
    selected, receipt = stage_library(original.decode())
    (project/'src/RootReturn.cs').write_text(selected,encoding='utf-8',newline='\n')
    captured = snapshot(project)
    require(len(captured) <= 4096 and sum(map(len,captured.values())) <= 32*1024**2
        and all(len(b) <= 4*1024**2 for b in captured.values()), 'managed-stage-original-project-source-caps')
    return project, receipt


def retain_managed_stage_inputs(compiled, output, binding, compiler):
    from tools.dotnet_guest.managed_work import STAGE_PROFILE
    retain_managed_stage_raw(compiled,output)
    require(binding.get('developmentManagedStage',{}).get('profile') == STAGE_PROFILE
        and binding['developmentManagedStage']['originalAuxiliaryInverseExact'] is True,
        'managed-stage-actual-generated-profile')
    retain_probe_inputs(compiled,output,binding,compiler,_join_cause=True,_stage=True)
    # Retain the exact response contents and selected CoreLib chain, not only hashes.
    destination=output/'probe-inputs'
    total=0
    for index,path in enumerate(sorted((compiled/'project/obj').rglob('*.rsp'))):
        require(index < 64,'managed-stage-retained-response-count')
        raw=read_file(path,1024**2);total+=len(raw)
        require(total<=4*1024**2,'managed-stage-retained-response-total')
        (destination/f'actual-{index:02d}.rsp').write_bytes(raw)
    for name in ('RootReturn.cs','Main.cs'):
        (destination/('application-'+name)).write_bytes(read_file(compiled/'project/src'/name,1024**2))
    for name in ('Capsule.csproj','global.json','packages.lock.json','nuget.config','component.wit'):
        (destination/('actual-'+name)).write_bytes(read_file(compiled/'project'/name,1024**2))
    canonical=read_json(output/'managed-stage-overlay-inputs/canonical-corelib-inputs.json')
    for row in canonical.values():
        if type(row) is dict:
            from tools.build_observation import file_identity as material_identity
            require(material_identity(output/row['retainedPath'],row['identity']['name'],8*1024**2)==row['identity'],
                'managed-stage-canonical-full-corelib-inputs')
    write_json(output/'managed-stage-generated.json', {'profile':STAGE_PROFILE,
        'bindings':binding['developmentManagedStage'], 'completeSources':MANAGED_STAGE_SOURCES,
        'actualAotSucceeded':True, 'originalSixCallsQualified':False, 'originalCauseQualified':False})


def retain_managed_stage_failure(compiled, output):
    retain_managed_stage_raw(compiled,output)
    path=compiled/'generated/bindings.json'
    if not path.is_file(): return
    binding=read_json(path,4*1024**2)
    names,records=stage_probe_sources(compiled,output,binding,compiler_returned=False,
        expected_sources=MANAGED_STAGE_SOURCES,retain_actual=True)
    write_json(output/'probe-inputs.json',{'formatVersion':1,'files':records,'completeActualGeneratedSources':names,
        'compilerSucceeded':False,'actualAotBindingConfirmed':False,'diagnosticOnly':True})


def managed_stage_acquire(output, commands, native_tools, deadline):
    from tools import install_guest_bindgen
    from tools.dotnet_capsule import _managed_stage_tar_visit, _managed_stage_file_identity
    from tools.dotnet_guest import composer
    acquisition=fresh(output/'acquisition'); acquisitions={}
    urls=(('wasi-sdk.tar.gz','https://github.com/WebAssembly/wasi-sdk/releases/download/wasi-sdk-29/wasi-sdk-29.0-x86_64-linux.tar.gz',
        256*1024**2,'87d1d1a2879d139cdc624b968efad3d4a97b8078cdff95e63ac88ecafd1a0171'),
        ('wit-bindgen.tar.gz',install_guest_bindgen.URL,install_guest_bindgen.MAX_ARCHIVE,install_guest_bindgen.ARCHIVE_SHA256),
        ('wac',composer.URL,composer.SIZE,composer.DIGEST.removeprefix('sha256:')))
    for name,url,bound,expected in urls:
        path=acquisition/name
        commands.command_seconds=180
        commands.run('download-'+name,'curl','--fail','--location','--max-time','180','--max-filesize',str(bound),url,'--output',path)
        observed=_managed_stage_file_identity(path,name,bound,deadline)
        row={'bytes':observed['size'],'sha256':observed['digest']}
        require(row['sha256']=='sha256:'+expected and (name!='wac' or row['bytes']==composer.SIZE),
            'managed-stage-fixed-tool-acquisition')
        acquisitions[name]={'url':url,**row}
    pin={'kind':'wasi-sdk','url':urls[0][1],'hashAlgorithm':'sha256','digest':urls[0][3],
        'size':acquisitions['wasi-sdk.tar.gz']['bytes'],'expectedTopDirectory':'wasi-sdk-29.0-x86_64-linux'}
    plan,_=_managed_stage_tar_visit(acquisition/'wasi-sdk.tar.gz',pin,deadline=deadline)
    unpacked=acquisition/'wasi-owned'
    _managed_stage_tar_visit(acquisition/'wasi-sdk.tar.gz',pin,deadline=deadline,destination=unpacked,expected=plan)
    binary=install_guest_bindgen.binary(read_file(acquisition/'wit-bindgen.tar.gz',install_guest_bindgen.MAX_ARCHIVE))
    bindgen=acquisition/'wit-bindgen';bindgen.write_bytes(binary);bindgen.chmod(0o755)
    (acquisition/'wac').chmod(0o755)
    tools={name:native_tools[name] for name in ('dotnet','wasm-tools','cargo','rustc')}
    tools['wit-bindgen']=bindgen
    write_json(output/'tool-acquisitions.json',{'inputs':acquisitions,'extractionFiles':plan['entryCount'],'extractionBytes':plan['expandedBytes'],
        'originalDeadline':deadline,'newDeadlineCreated':False})
    return unpacked/'wasi-sdk-29.0-x86_64-linux',acquisition/'wac',tools


def managed_stage_observations(stdout, stderr, component):
    """Diagnostic transport completion is not original-fault or retirement evidence."""
    require(type(stdout) is bytes and type(stderr) is bytes and len(stdout)+len(stderr)<=4*1024**2,
        'managed-stage-output-bound')
    records=[json.loads(line.removeprefix('DOTNET_MANAGED_STAGE_CALL ')) for line in stdout.decode().splitlines()
        if line.startswith('DOTNET_MANAGED_STAGE_CALL ')]
    require(len(records)==2,'managed-stage-exact-two-diagnostic-calls')
    for row,mode,outcome in zip(records,(3,9),('succeeded','guest-trap'),strict=True):
        require(set(row)=={'profile','component','mode','terminalOutcome','claims','originalCauseQualified',
            'originalSixCallsQualified','fullAc7Qualified','physicalRetirementQualified','nativeAccountingQualified'}
            and row['profile']=='dotnet-managed-stage-diagnostic-v2' and row['component']==component
            and type(row['mode']) is int and row['mode']==mode and row['terminalOutcome']==outcome
            and type(row['claims']) is int and row['claims']==1
            and all(row[key] is False for key in ('originalCauseQualified','originalSixCallsQualified',
                'fullAc7Qualified','physicalRetirementQualified','nativeAccountingQualified')), 'managed-stage-closed-call-row')
    events={0:[],1:[]};summary={};overflow=set();seen={0:0,1:0}
    catch_mask=sum(1<<stage for stage in (19,20,21))
    for line in stderr.decode().splitlines():
        if line.startswith(('DOTNET_MANAGED_STAGE ', 'DOTNET_MANAGED_STAGE_OVERFLOW ', 'DOTNET_MANAGED_STAGE_SUMMARY ')):
            require(len(line.encode())+1<=256,'managed-stage-native-line-bound')
        if line.startswith('DOTNET_MANAGED_STAGE '):
            row=json.loads(line.removeprefix('DOTNET_MANAGED_STAGE '))
            require(set(row)=={'slot','sequence','stage','guard'} and all(type(v) is int for v in row.values()),
                'managed-stage-closed-event')
            slot=row['slot'];require(slot in events and slot not in summary and len(events[slot])<16,
                'managed-stage-event-slot-count')
            require(row['sequence']==len(events[slot])+1 and 1<=row['stage']<=22
                and row['guard']==(row['stage'] if 10<=row['stage']<=16 else 0),'managed-stage-event-sequence-kind')
            stage=row['stage']
            if stage==22:
                require(not seen[slot]&(1<<22),'managed-stage-callback-return-once')
            elif 19<=stage<=21:
                require(seen[slot]&(1<<22) and not seen[slot]&catch_mask,
                    'managed-stage-one-catch-after-callback-return')
            seen[slot]|=1<<stage
            events[slot].append(row)
        elif line.startswith('DOTNET_MANAGED_STAGE_OVERFLOW '):
            row=json.loads(line.removeprefix('DOTNET_MANAGED_STAGE_OVERFLOW '))
            require(set(row)=={'slot'} and type(row['slot']) is int and row['slot'] in events
                and row['slot'] not in overflow,'managed-stage-overflow-once');overflow.add(row['slot'])
        elif line.startswith('DOTNET_MANAGED_STAGE_SUMMARY '):
            row=json.loads(line.removeprefix('DOTNET_MANAGED_STAGE_SUMMARY '));slot=row.get('slot')
            require(set(row)=={'slot','attempts','overflow','transportFailed','inconclusive'} and type(slot) is int
                and slot in events and slot not in summary and type(row['attempts']) is int
                and all(type(row[k]) is bool for k in ('overflow','transportFailed','inconclusive')),
                'managed-stage-closed-summary')
            summary[slot]=row
    require(set(summary)=={0,1},'managed-stage-two-final-summaries')
    for slot,row in summary.items():
        require(0<=row['attempts']<=17 and row['overflow'] is (slot in overflow)
            and (row['attempts']==17 if row['overflow'] else row['attempts']==len(events[slot])),
            'managed-stage-summary-count')
        require(row['attempts']>0 and not row['overflow'] and not row['transportFailed'] and not row['inconclusive'],
            'managed-stage-missing-overflow-or-gap-inconclusive')
        require(events[slot][0]['stage']==1,'managed-stage-selected-promise-first')
        require(seen[slot]&(1<<22),'managed-stage-callback-return-required')
    return {'calls':records,'events':events,'summary':summary,'diagnosticOnly':True,
        'originalCauseQualified':False,'originalSixCallsQualified':False,'fullAC7Qualified':False}


def managed_stage_public(output, deadline):
    """Fixed fresh evidence only; old component pair is referenced, never reexported."""
    public=output/'public';public.mkdir();rows=[];total=0;assembly_total=0;csharp_total=0
    paths=list(output.glob('*.json'))+list((output/'commands/logs').glob('*.txt'))
    folder=output/'dotnet-root-return-managed-stage'
    paths+=list(folder.glob('*.json'))+list((folder/'logs').glob('*.txt'))
    paths+=list((folder/'probe-inputs').glob('*'))+list((folder/'probe-raw-inputs').glob('*'))+list((folder/'managed-stage-overlay-inputs').glob('*'))
    for relative in ('package','wit'):
        for path in (folder/relative).rglob('*'):
            require(not path.is_symlink(),'managed-stage-public-no-links')
            if path.is_dir():continue
            require(path.is_file(),'managed-stage-public-regular-input')
            paths.append(path);require(len(paths)<=4095,'managed-stage-public-count')
    paths+=list(folder.glob('*.wasm'))+list(folder.glob('*.wac'))
    require(len(paths)==len(set(paths))<=4095,'managed-stage-public-count')
    for path in sorted(paths):
        require(time.monotonic()<deadline and path.is_file() and not path.is_symlink(),'managed-stage-public-clock-kind')
        identity=file_identity(path,64*1024**2);total+=identity['bytes'];require(total<=PUBLIC_BYTES,'managed-stage-public-union')
        if path.suffix.lower()=='.cs':
            csharp_total+=identity['bytes']
            require(identity['bytes']<=1024**2 and csharp_total<=4*1024**2,'managed-stage-all-retained-csharp-caps')
        if path.suffix.lower()=='.dll':
            assembly_total+=identity['bytes']
            require(identity['bytes']<=8*1024**2 and assembly_total<=32*1024**2,'managed-stage-all-retained-assembly-caps')
        name=path.relative_to(output).as_posix();target=public/name;target.parent.mkdir(parents=True,exist_ok=True)
        raw=read_file(path,64*1024**2);require(digest(raw)==identity['sha256'],'managed-stage-public-source-fence')
        with target.open('xb') as stream:stream.write(raw)
        rows.append({'path':name,**identity})
    write_json(public/'ADMISSION.json',{'formatVersion':1,'files':rows,'bytes':total,
        'maximumBytes':PUBLIC_BYTES,'productExecutionPermission':False})


def qualify_managed_stage(output, source_commit):
    from tools import ci_rust_artifacts as artifacts
    from tools.dotnet_capsule import (managed_stage_source_inputs, install_managed_stage_diagnostic,
        verify_managed_stage_tools, acquire_managed_stage_tools)
    from tools.dotnet_guest.managed_work import STAGE_CASE, STAGE_PROFILE
    from tools import host_codec_wasmtime
    require(os.environ.get('GITHUB_EVENT_NAME')=='push' and os.environ.get('GITHUB_REF')=='refs/heads/'+MANAGED_STAGE_BRANCH,
        'managed-stage-closed-qualification-only-branch')
    require(sys.platform=='linux' and sys.version_info>=(3,13),'managed-stage-linux-python313')
    require(output!=ROOT and ROOT not in output.parents and output not in ROOT.parents,'managed-stage-output-owned')
    output=fresh(output);deadline=float(os.environ['LSF_ROOT_RETURN_DEADLINE'])
    require(math.isfinite(deadline) and time.monotonic()<deadline<=time.monotonic()+1320,'managed-stage-one-original-deadline')
    shared={'bytes':0,'records':[]};environment=build_environment(output)
    environment.update(CARGO_TARGET_DIR=str(ROOT/'target'),CARGO_INCREMENTAL='0',CARGO_BUILD_JOBS='2',
        CARGO_PROFILE_DEV_DEBUG='0',CARGO_PROFILE_TEST_DEBUG='0',CARGO_PROFILE_DEV_DEBUG_ASSERTIONS='true',
        CARGO_PROFILE_TEST_DEBUG_ASSERTIONS='true',CARGO_PROFILE_DEV_OVERFLOW_CHECKS='true',
        CARGO_PROFILE_TEST_OVERFLOW_CHECKS='true',RUSTUP_TOOLCHAIN='1.97.1',RUSTUP_AUTO_INSTALL='0')
    commands=JoinCauseCommands(ROOT,fresh(output/'commands'),environment,shared,deadline)
    record={'profile':STAGE_PROFILE,'status':'in-progress','plannedSignedCalls':2,'freshAuxiliaryAotBuilds':1,
        'normalAotBuilds':0,'oldEvidence':MANAGED_STAGE_DATED,'ownerCaps':OWNER_CAPS,
        'nativeCacheRestored':False,'nativeColdBuildCommandCapSeconds':600,
        'originalSixCallsQualified':False,'originalCauseQualified':False,'fullAC7Qualified':False,
        'nativeAccountingQualified':False,'physicalRetirementQualified':False}
    try:
        require(re.fullmatch('[0-9a-f]{40}',source_commit) and subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,timeout=15).decode().strip()==source_commit
            and not subprocess.check_output(['git','-c','core.fsmonitor=false','status','--porcelain'],cwd=ROOT,timeout=15),'managed-stage-clean-source')
        before=source_map();write_json(output/'current-git-inputs.json',before)
        closure=managed_stage_source_inputs(ROOT,deadline=deadline)
        write_json(output/'acquisition-source-inputs.json',closure)
        # Fixed official archives and four authenticated component installers share this owner.
        curl=Path(shutil.which('curl',path=environment['PATH']) or 'missing-curl').resolve(strict=True)
        bash=Path(shutil.which('bash',path=environment['PATH']) or 'missing-bash').resolve(strict=True)
        fixed=acquire_managed_stage_tools(output/'fixed-tools',commands,deadline=deadline,curl=curl,sh=bash)
        native_tools=fixed['tools']
        environment['RUSTC']=str(native_tools['rustc'])
        environment['PATH']=os.pathsep.join(dict.fromkeys([*(str(p.parent) for p in native_tools.values()),environment['PATH']]))
        environment['DOTNET_ROOT']=str(native_tools['dotnet'].parent)
        for key,name in (('receipt','fixed-tool-acquisition.json'),('sourcePins','fixed-tool-pins.json')):
            (output/name).write_bytes(read_file(fixed[key],64*1024**2))
        wasi,composer,tool_paths=managed_stage_acquire(output,commands,native_tools,deadline)
        commands.command_seconds=600
        tools=install_managed_stage_diagnostic(output/'private-tools',wasi,commands,deadline=deadline,
            source_inputs=closure,composer_source=composer,tool_paths=tool_paths)
        # Native host and packaging frontends are current-source development targets, not old Native5.
        record['nativeCohort']=host_codec_wasmtime.verify(ROOT)
        native_raw=commands.run('build-managed-stage-frontends',native_tools['cargo'],'--config','.cargo/managed-guest.toml',
            'build','--locked','-p','latent-packaging','--features','development-test-host',
            '--example','capsule_contracts','--example','package','--message-format=json')
        native=join_native_examples(native_raw,ROOT/'target')
        inventory_index=len(commands.records)
        commands.run('build-managed-stage-host',native_tools['cargo'],'--config','.cargo/managed-guest.toml',
            'test','--locked','-p','latent-wasmtime','--features','development-test-host','--lib','--test','local_service','--no-run','--message-format=json')
        native_inventory=commands.output/'logs'/f'{inventory_index:02d}-build-managed-stage-host.stdout.txt'
        suites=(artifacts.Suite('crates/latent-wasmtime/Cargo.toml','latent_wasmtime','src/lib.rs',JOIN_UNIT_PREFIX,
            frozenset(JOIN_UNIT_CASES),False,kind='lib'),artifacts.Suite('crates/latent-wasmtime/Cargo.toml','local_service',
            'tests/local_service.rs',STAGE_CASE,frozenset({STAGE_CASE}),True,kind='test'))
        owners=[artifacts.read_inventory(native_inventory,ROOT,s,target=ROOT/'target') for s in suites]
        products={str(p):file_identity(p,512*1024**2) for p in (*native.values(),*(o.executable for o in owners))}
        project,selection=managed_stage_fixture(output/'private-project',closure,deadline)
        record['selection']=selection;captured=inventory(snapshot(project));(output/'project-inputs.json').write_bytes(captured)
        def command_owner(root,folder,env):
            env['PATH']=os.pathsep.join(dict.fromkeys([*(str(p.parent) for p in tool_paths.values()),env['PATH']]))
            env['DOTNET_ROOT']=str(tool_paths['dotnet'].parent)
            return JoinCauseCommands(root,folder,env,shared,deadline)
        artifact=build(project,output/'dotnet-root-return-managed-stage',native['examples/capsule_contracts'],native['examples/package'],
            'https://github.com/KirilsTurkins/latent-service-fabric',tools=tools,offline=True,_deadline=deadline,
            _root_return_capture=(retain_managed_stage_inputs,retain_managed_stage_failure),_root_join_cause=True,
            _root_return_commands=command_owner,_development_managed_stage=True,_managed_stage_validator=verify_managed_stage_tools)
        require(read_file(artifact/'source-inputs.json')==captured,'managed-stage-actual-project-inputs')
        component=file_identity(artifact/'component.wasm',64*1024**2)['sha256'];record['component']=component
        def library_probe(argv,*,cwd,env,timeout,maximum):
            require(argv==['rustc','--print','target-libdir'] and cwd==ROOT and timeout==30 and maximum==4096,
                'managed-stage-native-library-probe')
            commands.command_seconds=25;commands.environment=env
            raw=commands.run('rust-library-path',native_tools['rustc'],*argv[1:]);require(len(raw)<=maximum,'managed-stage-native-library-path')
            return 0,raw
        for ordinal,(suite,owner) in enumerate(zip(suites,owners,strict=True)):
            commands.environment=artifacts.cargo_environment(ROOT,owner,environment,target=ROOT/'target',execute=library_probe)
            commands.command_seconds=25
            args=[suite.filter]+(['--exact','--ignored'] if ordinal else [])
            listing=commands.run('list-managed-stage-'+str(ordinal),owner.executable,*args,'--list')
            require(len(listing)<=65536,'managed-stage-native-list-bound');artifacts.validate_listing(listing,suite)
            commands.command_seconds=300 if ordinal else 30
            if ordinal:
                commands.environment.update(LSF_GUEST_SDK_LANGUAGE='dotnet',LSF_GUEST_CAPSULES=str(output),
                    LSF_DOTNET_MANAGED_STAGE_COMPONENT=component)
            raw=commands.run('execute-managed-stage-'+str(ordinal),owner.executable,*args,'--show-output','--test-threads=1')
            count=1 if ordinal else 3
            require(re.search(r'^test result: ok\. '+str(count)+r' passed; 0 failed; 0 ignored; 0 measured; [0-9]+ filtered out; finished in [0-9.]+s$',raw.decode(),re.M),
                'managed-stage-current-native-result')
            if ordinal:
                stderr=read_file(commands.output/'logs'/f'{len(commands.records)-1:02d}-execute-managed-stage-1.stderr.txt',4*1024**2)
                record['observations']=managed_stage_observations(raw,stderr,component)
        require(source_map()==before and inventory(snapshot(project))==captured
            and closure==managed_stage_source_inputs(ROOT,deadline=deadline)
            and all(file_identity(Path(path),512*1024**2)==row for path,row in products.items())
            and file_identity(artifact/'component.wasm',64*1024**2)['sha256']==component,'managed-stage-source-products-after')
        remaining=deadline-5-time.monotonic();require(remaining>0,'managed-stage-final-source-clock')
        require(not subprocess.check_output(['git','-c','core.fsmonitor=false','status','--porcelain'],cwd=ROOT,
            timeout=min(15,remaining)),'managed-stage-final-clean-source')
        record.update(status='diagnostic-completed',executedSignedCalls=2,sourceCommit=source_commit,
            commandCount=len(shared['records']),diagnosticBytes=shared['bytes'])
        write_json(output/'qualified.json',record);return record
    except BaseException as error:
        record.update(status='failed',errorCategory=type(error).__name__);write_json(output/'FAILED.json',record);raise
    finally:
        write_json(output/'commands.json',shared['records'])
        for name in ('MANAGED-STAGE-INSTALL.json','managed-stage-source-inputs.json','runtime-inputs.json','wasi-sdk.json'):
            path=output/'private-tools'/name
            if path.is_file():(output/('private-'+name)).write_bytes(read_file(path,64*1024**2))
        managed_stage_public(output,deadline)


def retain_managed_stage_raw(compiled, output):
    """Failure-safe raw generated evidence, including before bindings.json exists."""
    component=compiled/'component.wasm'
    if component.is_file():
        (output/'component.wasm').write_bytes(read_file(component,64*1024**2))
    roots=[]
    independent=compiled/'generated-managed-stage-raw'
    if independent.exists():roots.append(independent)
    obj=compiled/'project/obj'
    if obj.is_dir():
        for path in obj.rglob('*-managed-stage-raw'):
            require(len(roots)<4,'managed-stage-raw-origin-count');roots.append(path)
    if not roots:return
    destination=output/'probe-raw-inputs';destination.mkdir()
    canonical=None;origins=[]
    for root in sorted(roots):
        require(not root.is_symlink() and root.is_dir(),'managed-stage-raw-origin-kind')
        raw=read_file(root/'raw-inventory.json',128*1024);manifest=json.loads(raw)
        require(type(manifest) is dict and set(manifest)=={'profile','phase','actualNames','totalBytes','files',
            'expectedFinalNames','expectedFinalNamesAreNotRawCount'}
            and manifest['profile']=='dotnet-managed-stage-diagnostic-v2'
            and manifest['phase']=='before-auxiliary-stage-projection','managed-stage-raw-origin-manifest')
        names=manifest['actualNames']
        require(type(names) is list and len(names)<=64 and names==sorted(set(names))
            and len({n.casefold() for n in names})==len(names)
            and all(type(n) is str and len(n)<=256 and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]*\.cs',n) is not None for n in names)
            and set(manifest['files'])==set(names)
            and {p.name for p in root.iterdir()}=={*names,'raw-inventory.json'},'managed-stage-raw-origin-closed-names')
        require(canonical is None or canonical==manifest,'managed-stage-raw-independent-actual-drift')
        total=0
        for name in names:
            body=read_file(root/name,1024**2);total+=len(body)
            require(total<=4*1024**2 and manifest['files'][name]=={'bytes':len(body),'sha256':hashlib.sha256(body).hexdigest()},
                'managed-stage-raw-origin-body')
            if canonical is None:
                with (destination/name).open('xb') as stream:stream.write(body)
        require(type(manifest['totalBytes']) is int and manifest['totalBytes']==total,'managed-stage-raw-origin-total')
        origins.append({'path':root.relative_to(compiled).as_posix(),'manifestDigest':digest(raw),'sourceBytes':total,
            'sameCompleteSourceSet':True})
        if canonical is None:
            canonical=manifest;(destination/'raw-inventory.json').write_bytes(raw)
    write_json(output/'managed-stage-raw-origins.json',{'origins':origins,'completeActualRawSources':canonical['actualNames'],
        'phase':'before-auxiliary-stage-projection','actualAotBindingConfirmed':False,
        'successRequiresSeparateActualBindingReceipt':True,'originalCauseQualified':False})
