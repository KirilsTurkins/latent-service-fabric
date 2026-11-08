#!/usr/bin/env python3
"""One current-source signed ordinary C once interleaving; not full #744."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import tomllib

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import c_capsule_build, c_capsule_project
from tools import c_thread_runtime_fixture as fixture, c_thread_runtime_node as owner
from tools.build_observation import build_environment
from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import require, stopped_record
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity, source_identity
from tools.phase3_resource_os import Probe
from tools.qualify_c_thread_runtime import build_evidence, materials
from tools.qualify_java_server_lifecycle import ordinary_tuple
from tools.qualify_java_server_lifecycle_suite import native as build_native
from tools.qualify_resource_tenants import stop_observation_peer
from tools.rust_capsule_build import Commands
from tools.rust_capsule_node import RecordingClient, configure as configure_base, delete_all, deploy, sample
from tools.rust_capsule_project import ROOT, fresh, inventory, read_file, read_json, snapshot, write_json
from tools.sdk_provider_scenario import start_provider

SELF = 'tools/qualify_c_once_runtime.py'
SOURCE = 'tools/fixtures/c-once-runtime/main.c'
WORKFLOW = '.github/workflows/c-once-runtime.yml'
WORLD = fixture.FIXTURE + 'world.wit'


def witness(value):
    require(type(value) is str and len(value) <= 160, 'c-once-bounded-witness')
    parts = value.split(':')
    require(len(parts) == 9 and parts[0] == 'once', 'c-once-witness-shape')
    numbers = parts[1:]
    require(all(item.isascii() and item.isdigit() and len(item) <= 20 and str(int(item)) == item
                for item in numbers), 'c-once-witness-numbers')
    initialized, completed, waits, parked, tasks, results, native, memory = map(int, numbers)
    require((initialized, completed, waits, parked, tasks, results, native) == (1, 2, 3, 3, 4, 3, 8)
            and 0 < memory <= 32 * 1024**2, 'c-once-exact-live-owners')
    return {'initializations': initialized, 'callersCompleted': completed, 'waits': waits,
        'parkedTasks': parked, 'tasks': tasks, 'results': results, 'nativeOwners': native,
        'nativeMemoryBytes': memory, 'observedBy': 'ordinary-third-child-before-release',
        'canonicalPollPendingClaimed': False, 'automaticCpuFairnessClaimed': False}


def prepare(directory):
    project = c_capsule_project.create(directory, 'greeting', name='c-thread-runtime',
                                        threading_profile=fixture.PROFILE)
    (project / 'src/main.c').write_bytes(read_file(ROOT / SOURCE, 65536))
    (project / 'wit/world.wit').write_bytes(read_file(ROOT / WORLD, 65536))
    config = json.loads(read_file(project / 'capsule-project.json'))
    config['world'] = fixture.WORLD
    config['limits'].update(cpuFuel=1_000_000_000, memoryBytes=32 * 1024 * 1024,
                            wallTimeLimitMillis=5000, logBytes=0)
    (project / 'capsule-project.json').write_bytes(
        (json.dumps(config, sort_keys=True, indent=2) + '\n').encode())
    c_capsule_project.validate(snapshot(project))
    return project


def inputs(capture=None):
    rows = materials()
    for name in (SELF, SOURCE, WORKFLOW, WORLD, 'tools/qualify_java_server_lifecycle.py',
                 'tools/qualify_java_server_lifecycle_suite.py', 'tools/toolchain.toml',
                 'tools/requirements.lock', 'tools/tests/test_c_once_runtime.py'):
        rows[name] = file_identity(ROOT / name, 4 * 1024**2)
    require(len(rows) <= 256 and sum(row['bytes'] for row in rows.values()) <= 16 * 1024**2,
            'c-once-source-input-bound')
    if capture is not None:
        for name, expected in rows.items():
            destination = capture / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(read_file(ROOT / name, 4 * 1024**2))
            require(file_identity(destination, 4 * 1024**2) == expected, 'c-once-captured-source-mismatch')
    return dict(sorted(rows.items()))


def invoke(client, probe, target, output, activation):
    revision = owner.selected_revision(client, target)
    process = owner.start_call(client, target, owner.SERVICE, 'greet', ['once'], activation)
    failed = False
    try:
        row = owner.finish_call(client, process)
        write_json(output / ('invocation-' + activation + '.json'), row)
        response = row['response']
        require(row['processReaped'] is True and row['exitCode'] == 0
                and response['outcomeKnown'] is True and response['requestDispatched'] is True
                and response['data']['resolvedRevision'] == revision
                and type(row['decoded']) is list and len(row['decoded']) == 1
                and set(row['decoded'][0]) == {'ok'}, 'c-once-current-success')
        consumed = response['data']['consumption']
        require(0 < owner.integer(consumed['cpuFuel']) <= 1_000_000_000
                and 0 < owner.integer(consumed['peakMemoryBytes']) <= 32 * 1024**2
                and all(owner.integer(consumed[name]) == 0 for name in
                    ('outboundRequests', 'stateReadBytes', 'stateWriteBytes', 'blobReadBytes',
                     'blobWriteBytes', 'logBytes', 'effectCount', 'childCalls')),
                'c-once-original-envelope-and-no-other-authority')
        checked = witness(row['decoded'][0]['ok'])
        observed = owner.retire(client, probe, target, output, activation)
        require(observed['physicalOwnersAfter'] == 0 and observed['activeProviderCountersAfter'] == 0,
                'c-once-post-call-counters')
        return {'activation': activation, 'witness': checked,
                'postCall': {'nodeInventoryAndQuotasIdle': True, 'activeProviderCountersAfter': 0,
                             'osSampleCaptured': True, 'kernelNativeFinalFreeProved': False}}
    except BaseException:
        failed = True
        try:
            owner.retain_partial(process, output, activation)
        except BaseException:
            pass
        raise
    finally:
        owner.close_call(process, primary_failure=failed)


def run_node(artifact, native, output, deadline):
    output = fresh(output)
    component = file_identity(artifact / 'component.wasm', 8 * 1024**2)
    before = {name: file_identity(path) for name, path in native.items()}
    commands = Commands(ROOT, fresh(output / 'commands'), build_environment(output),
                        deadline_seconds=300, command_seconds=60)
    commands.deadline = min(commands.deadline, deadline)
    record = {'schemaVersion': 'latent.c.once.node.v1', 'status': 'incomplete',
              'component': component, 'native': before, 'full744Qualified': False}
    stage, failed = 'sign', False
    try:
        signed = output / 'signed'
        commands.run('sign', native['capsule_authoring'], 'demo-sign', signed, artifact)
        releases = read_json(signed / 'release-set.json')['releases']
        require(len(releases) == 1 and releases[0]['componentDigest'] == component['sha256'],
                'c-once-one-exact-signed-component')
        with owned_cancellation() as cancellation, tempfile.TemporaryDirectory(prefix='lsf-c-once-') as temporary, \
                owner.owned_cleanup(record) as cleanup:
            work = Path(temporary)
            for name in ('client', 'node', 'peer'):
                (work / name).mkdir(mode=0o700)
            client = RecordingClient(native['latent'], work / 'client', cancellation,
                min(commands.deadline, time.monotonic() + 240), evidence=output / 'controls')
            peer, port = start_provider(client, work / 'peer', maximum_seconds=240)
            cleanup.callback(peer.close)
            config, settings = configure_base(work / 'node', signed, port, language='c')
            owner.configure(settings, read_json(artifact / 'capsule.json'))
            config.write_bytes((json.dumps(settings, sort_keys=True, separators=(',', ':')) + '\n').encode())
            stage = 'start-current-node'
            node = connect(client, native['latentd'], work / 'node', config, 'examples', 0)
            cleanup.callback(node.close)
            record['startup'] = node.startup_record
            probe = Probe(node, before['latentd'])
            source = signed / owner.SERVICE
            published = client.call('release', 'publish-package', source / 'package',
                '--evidence', source / 'evidence/index.json', '--operation-id', 'c-once-publish',
                '--expected-generation', '0')
            require(published['outcomeKnown'] is True and published['data']['release']['digest'] == component['sha256'],
                    'c-once-signed-component-admission')
            publication = published['data']['operation']['publication']['id']
            target = deploy(client, source / 'deployment.json', publication)
            require(target['grants'] == [], 'c-once-no-default-authority')
            grants = owner.install(client, node, target)
            target = deploy(client, source / 'deployment.json', publication,
                            generation=str(target['generation']), grants=grants)
            stage = 'two-signed-once-activations'
            record['cases'] = [invoke(client, probe, target, output, 'c-once-' + label)
                               for label in ('initial', 'fresh')]
            delete_all(client, [target['name']])
            record['afterDeletes'] = sample(client, probe, 'c-once-after-deletes', 0)
            stop(client, node)
            record['nodeShutdown'] = stopped_record(node)
            record['peerShutdown'] = stop_observation_peer(peer)
            cancellation.check()
        require(before == {name: file_identity(path) for name, path in native.items()}
                and component == file_identity(artifact / 'component.wasm', 8 * 1024**2)
                and client.calls <= 384 and time.monotonic() < commands.deadline,
                'c-once-final-native-component-and-deadline')
        record.update(status='passed', cliCalls=client.calls, commands=commands.records)
        write_json(output / 'qualified.json', record)
        return record
    except BaseException:
        failed = True
        record.update(status='failed', stage=stage, qualification=False)
        raise
    finally:
        if failed:
            try:
                write_json(output / 'FAILED.json', record)
            except BaseException:
                pass


def qualify(args):
    require(sys.platform == 'linux' and sys.version_info >= (3, 13) and os.geteuid() != 0,
            'c-once-unprivileged-linux-owner')
    stamp = os.environ.get('LSF_C_ONCE_STARTED_NS', '')
    require(stamp.isascii() and stamp.isdigit() and len(stamp) <= 20, 'c-once-setup-clock')
    elapsed = (time.time_ns() - int(stamp)) / 1_000_000_000
    require(0 <= elapsed < 1315, 'c-once-parent-clock')
    destination = args.output.absolute()
    require(destination != ROOT and ROOT not in destination.parents and destination not in ROOT.parents,
            'c-once-output-outside-checkout')
    output = fresh(destination)
    commands = Commands(ROOT, output, build_environment(output), deadline_seconds=1320, command_seconds=900)
    commands.deadline = time.monotonic() + 1315 - elapsed
    commands.environment.update(CARGO_TARGET_DIR=os.environ.get('CARGO_TARGET_DIR', str(ROOT / 'target')),
        CARGO_BUILD_JOBS='2', CARGO_INCREMENTAL='0', CARGO_PROFILE_DEV_DEBUG='0', CARGO_PROFILE_TEST_DEBUG='0')
    result = {'schemaVersion': 'latent.c.once.qualification.v1', 'status': 'incomplete',
              'full744Qualified': False, 'publisherAuthenticated': False, 'releasePublished': False,
              'limits': {'parentSeconds': 1320, 'commandSeconds': 900, 'cleanupReserveSeconds': 5,
                         'jobs': 2, 'components': 1, 'activations': 2, 'clientCalls': 384}}
    stage = 'source'
    try:
        source = source_identity(ROOT)
        head = commands.run('source-head', 'git', 'rev-parse', 'HEAD', 'HEAD^{tree}').decode().splitlines()
        require(len(head) == 2 and all(re.fullmatch(r'[0-9a-f]{40}', v) for v in head), 'c-once-source-head-tree')
        commands.run('source-clean', 'git', 'diff', '--exit-code', 'HEAD', '--')
        helpers = inputs(output / 'owner-inputs')
        result['source'] = {'head': head[0], 'tree': head[1], 'native': source, 'helpers': helpers}
        stage = 'fresh-native-products'
        build_root = output / 'native-build'; build_root.mkdir(mode=0o700)
        directory, receipt = build_native(commands, build_root, tomllib.loads(read_file(ROOT / 'tools/toolchain.toml').decode()))
        native = {n: directory / n for n in ('latent', 'latentd', 'package', 'capsule_contracts', 'capsule_authoring')}
        result['nativeTuple'] = ordinary_tuple(receipt, native)
        require((result['nativeTuple']['sourceHead'], result['nativeTuple']['sourceTree']) == tuple(head),
                'c-once-native-source-matches-consumer')
        stage = 'fresh-ordinary-component'
        sdk = inventory(c_capsule_project.sdk_inputs(ROOT, threading=True))
        project = prepare(output / 'project')
        original = inventory(snapshot(project))
        installed = {n: getattr(args, n.replace('-', '_')).resolve(strict=True)
                     for n in ('zig', 'wit-bindgen', 'wasm-tools')}
        tools = {n: file_identity(p, 512 * 1024**2) for n, p in installed.items()}
        artifact = output / 'build'
        c_capsule_build.build(project, artifact, native['capsule_contracts'], native['package'],
            'https://github.com/KirilsTurkins/latent-service-fabric', installed=installed, _deadline=commands.deadline)
        result['build'] = build_evidence(artifact, original)
        stage = 'signed-once-witnesses'
        result['node'] = run_node(artifact, native, output / 'node', commands.deadline)
        require(result['node']['status'] == 'passed' and len(result['node']['cases']) == 2,
                'c-once-two-signed-outcomes')
        require(helpers == inputs() and source_identity(ROOT) == source
                and sdk == inventory(c_capsule_project.sdk_inputs(ROOT, threading=True))
                and original == inventory(snapshot(project)) and result['nativeTuple'] == ordinary_tuple(receipt, native)
                and tools == {n: file_identity(p, 512 * 1024**2) for n, p in installed.items()},
                'c-once-all-actual-inputs-still-exact')
        commands.run('source-still-clean', 'git', 'diff', '--exit-code', 'HEAD', '--')
        require(time.monotonic() < commands.deadline, 'c-once-parent-deadline')
        result.update(status='passed', tools=tools, commands=commands.records)
        write_json(output / 'qualified.json', result)
        return result
    except BaseException:
        result.update(status='failed', stage=stage, commands=commands.records)
        write_json(output / 'FAILED.json', result)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('zig', 'wit-bindgen', 'wasm-tools', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    qualify(parser.parse_args())
