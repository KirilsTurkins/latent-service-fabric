"""Explicit nonqualifying observation of the immutable normal v3 .NET guest.

Only the existing development-test-host integration executable is built. The
original component, CoreLib, compiler observation and package inputs are never
rewritten or rebuilt. No additional CLI, feature or environment selector exists.
"""
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import re
import stat
import sys
import struct
import time
import zipfile

from tools import ci_rust_artifacts as artifacts
from tools.build_observation import build_environment
from tools.dotnet_root_return import (JoinCauseCommands, join_public_admission,
                                     source_map, OWNER_CAPS)
from tools.phase2_operator_process import require
from tools.rust_capsule_project import ROOT, fresh, read_file, write_json

ORIGINAL = {'run': 41191304300, 'job': 124508472972, 'artifact': 13038749267,
    'source': '1a8aa9a00e8e7c52fb8cc913b0da8aaa003d9b98', 'bytes': 8155138,
    'sha256': '23af068f95a0fc554c16cf4c7c058273146c6ec7f1e2d0e2c06120f56b2cb1bb',
    'members': 395, 'admittedBytes': 29061478,
    'admissionSha256': '7eeadc24363a2d970fe38db80d439b3d906c45e93be075d380c9ea8bd1131430'}
COMPONENT = 'sha256:9c20e7025c9a2672ee256d93fb51efd631b609064953a11dc2491a94639552af'
CASE = 'dotnet_original_v3_fault_and_quiescence_use_bounded_numeric_observation'
CONTROL = 'development_trap_observer::tests::actual_backtrace_is_bounded_numeric_and_does_not_retain_runtime_owners'
BUDGET = {'cpuFuel': 1000000000, 'memoryBytes': 134217728, 'wallTimeLimitMillis': 120000,
    'childCalls': 0, 'outboundRequests': 0, 'stateReadBytes': 0, 'stateWriteBytes': 0,
    'blobReadBytes': 0, 'blobWriteBytes': 0, 'logBytes': 0, 'effectCount': 0}
# Exact fourteen retained package inputs; WIT restores only from the same
# authenticated original artifact, never from the current repository.
PACKAGE = {'capsule.json': {'retainedSource': 'build/capsule.json', 'bytes': 1387, 'sha256': 'sha256:91a482b9599db19105db186a0aa71a85f7b394e766d46636b415c77e8ada024d'}, 'compatibility-report.json': {'retainedSource': 'build/compatibility-report.json', 'bytes': 1254, 'sha256': 'sha256:55932c6c18671dd35d4f357e388e187bd19b528a534d17b028055454b368accb'}, 'component.wasm': {'retainedSource': 'build/component.wasm', 'bytes': 2476558, 'sha256': 'sha256:9c20e7025c9a2672ee256d93fb51efd631b609064953a11dc2491a94639552af'}, 'contracts.json': {'retainedSource': 'build/contracts.json', 'bytes': 902, 'sha256': 'sha256:d87882a6ad7fb199776006e155b9ca7d7e36443c81f57abb9040dd29a717681e'}, 'package-source.json': {'retainedSource': 'build/package-source.json', 'bytes': 1650, 'sha256': 'sha256:10e9d6ad331cda8213a26994878970328f3d595f20d412b789599f3c0a91dadd'}, 'wit-lock.json': {'retainedSource': 'build/wit-lock.json', 'bytes': 924, 'sha256': 'sha256:e0bd8e53cf1b884a7348c6bea70d582218890b3c4a8bdee04b31d9cf2e91b96f'}, 'wit/deps/activation-runtime/package.wit': {'retainedSource': 'project/wit/deps/activation-runtime/package.wit', 'bytes': 2539, 'sha256': 'sha256:0855e3524edbe15a5d174a825df6034ef41cd87f1330e2fba884ea6e2c58e946'}, 'wit/deps/clock/package.wit': {'retainedSource': 'project/wit/deps/clock/package.wit', 'bytes': 139, 'sha256': 'sha256:a009ecd4ad23d581523fe97b66327ebe352ac27c9c72d4e09ecc9bb003c466ea'}, 'wit/deps/random/package.wit': {'retainedSource': 'project/wit/deps/random/package.wit', 'bytes': 272, 'sha256': 'sha256:c8ceca00269182f27c785fe17bd42eb4776bcde96828e5b5f2786aa15dbedc60'}, 'wit/world.wit': {'retainedSource': 'project/wit/world.wit', 'bytes': 345, 'sha256': 'sha256:7bc0cb3dc5134250cc0dcae3c850f3bdb6d9f28114be6b6246472d7c6466e737'}, 'BUILD-COMPLETE.json': {'retainedSource': 'build/BUILD-COMPLETE.json', 'bytes': 44295, 'sha256': 'sha256:e5a2234d5a8c1fafe4d4abb30c33d59e5dab0fa8383c2a4c203dd00d86521ebe'}, 'source-inputs.json': {'retainedSource': 'build/source-inputs.json', 'bytes': 24034, 'sha256': 'sha256:352c36056922652bece5dd9804a50ef7675c6ac61c5a9810b781535ab4ff32f4'}, 'build-observation.json': {'retainedSource': 'build/build-observation.json', 'bytes': 8146, 'sha256': 'sha256:a561a89b8b2ff6b0dccd810514be210e38ebd14ca25d996f2f153abc3d39d57e'}, 'package-inputs.json': {'retainedSource': 'build/package-inputs.json', 'bytes': 1201, 'sha256': 'sha256:ff48598edcf53543be926d2287e945dcf9601935c9927631e740ada180b7158f'}}


def object_pairs(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, 'dotnet-original-duplicate-json-field')
        value[key] = item
    return value


def decode(raw):
    return json.loads(raw, object_pairs_hook=object_pairs)


def identity(raw):
    return {'bytes': len(raw), 'sha256': 'sha256:'+hashlib.sha256(raw).hexdigest()}


def restore(archive, destination, deadline):
    raw = read_file(archive, ORIGINAL['bytes'])
    require(len(raw) == ORIGINAL['bytes'] and hashlib.sha256(raw).hexdigest() == ORIGINAL['sha256'],
        'dotnet-original-official-archive')
    end = struct.unpack('<4s4H2LH', raw[-22:])
    require(end[:5] == (b'PK\x05\x06', 0, 0, ORIGINAL['members'], ORIGINAL['members'])
        and end[7] == 0 and end[5] <= 4*1024**2 and end[6]+end[5]+22 == len(raw),
        'dotnet-original-central-bound')
    payloads, spellings, expanded = {}, set(), 0
    with zipfile.ZipFile(archive) as source:
        require(len(source.infolist()) == ORIGINAL['members'] and source.start_dir == end[6],
            'dotnet-original-exact-member-count')
        for member in source.infolist():
            require(time.monotonic() < deadline, 'dotnet-original-archive-deadline')
            name = member.filename; path = PurePosixPath(name); key = name.casefold()
            require(name and len(name.encode()) <= 512 and path.as_posix() == name
                and not path.is_absolute() and not any(p in ('', '.', '..') for p in path.parts)
                and '\\' not in name and ':' not in name and not member.is_dir()
                and stat.S_IFMT(member.external_attr >> 16) in (0, stat.S_IFREG)
                and not member.flag_bits & 1 and member.compress_type == 8
                and key not in spellings and not any(key.startswith(v+'/') or v.startswith(key+'/')
                    for v in spellings), 'dotnet-original-closed-regular-path')
            spellings.add(key); expanded += member.file_size
            require(0 <= member.file_size <= 64*1024**2 and expanded <= 128*1024**2,
                'dotnet-original-expansion-bound')
            payloads[name] = source.read(member)  # validates every original CRC
    admission = payloads.pop('ADMISSION.json')
    require(hashlib.sha256(admission).hexdigest() == ORIGINAL['admissionSha256'],
        'dotnet-original-admission-identity')
    index = decode(admission)
    require(set(index) == {'formatVersion', 'files', 'bytes', 'maximumBytes', 'productExecutionPermission'}
        and index['formatVersion'] == 1 and index['productExecutionPermission'] is False
        and index['maximumBytes'] == 128*1024**2 and index['bytes'] == ORIGINAL['admittedBytes']
        and len(index['files']) == ORIGINAL['members']-1, 'dotnet-original-admission-fields')
    admitted = {}
    for row in index['files']:
        require(set(row) == {'path', 'sha256', 'bytes'} and row['path'] not in admitted,
            'dotnet-original-admission-row')
        admitted[row['path']] = {k: row[k] for k in ('bytes', 'sha256')}
    require(set(admitted) == set(payloads) and sum(len(b) for b in payloads.values()) == ORIGINAL['admittedBytes']
        and all(identity(b) == admitted[n] for n, b in payloads.items()), 'dotnet-original-all-payload-identities')
    qualified = decode(payloads['qualified.json'])
    require(qualified['status'] == 'passed' and qualified['sourceCommit'] == ORIGINAL['source']
        and qualified['invocations'] == 15 and qualified['sourceBeforeEqualsAfter'] is True
        and qualified['normalComponent'] == {'bytes': 2476558, 'sha256': COMPONENT}
        and all(qualified[k] is False for k in ('full746Qualified', 'fullAC7Qualified',
            'originalFaultCauseQualified', 'opaqueCauseQualified', 'nativeAccountingComplete')),
        'dotnet-original-immutable-normal-result')
    # Actual route generation10, shared by the original mode8/9 results.
    route = decode(payloads['examples-controls/050.json'])
    deployed = route['data']['deployment']['manifest']['spec']
    require(route['outcomeKnown'] is True and route['data']['routeGeneration'] == '10'
        and deployed['resources'] == BUDGET and deployed['release'] == COMPONENT,
        'dotnet-original-effective-request-budget')
    for mode, activation in ((9, 'ac7-fault-unattributed'), (8, 'ac7-opaque-unattributed')):
        case = decode(payloads['examples-controls/'+activation+'.json'])
        resolved = case['response']['data']['resolvedRevision']
        require(case['exitCode'] == 4 and case['processReaped'] is True
            and case['response']['outcomeKnown'] is True and case['response']['error']['code'] == 'guest-trap'
            and resolved['releaseDigest'] == COMPONENT and resolved['routeGeneration'] == '10'
            and resolved['publicationId'] == deployed['publication'], 'dotnet-original-result-route-binding')
    require(len(PACKAGE) == 14, 'dotnet-original-fourteen-inputs')
    for name, row in PACKAGE.items():
        require(identity(payloads[row['retainedSource']]) == {k: row[k] for k in ('bytes', 'sha256')},
            'dotnet-original-package-input')
    destination = fresh(destination)
    for name, row in PACKAGE.items():
        target = destination/name; target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as sink: sink.write(payloads[row['retainedSource']])
    return {'origin': ORIGINAL, 'component': COMPONENT, 'packageInputs': PACKAGE,
        'originalEffectiveRequestBudget': BUDGET, 'allOriginalMembersAndCrcsVerified': True,
        'guestCompilerCorelibRebuilt': False}


def observations(raw):
    require(type(raw) is bytes and len(raw) <= 4*1024**2, 'dotnet-original-output-bound')
    events = []
    for line in raw.splitlines():
        if not line.startswith(b'DOTNET_ORIGINAL_V3_'): continue
        require(len(line) <= 8256 and len(events) < 4, 'dotnet-original-event-bound')
        prefix, separator, data = line.partition(b' ')
        require(separator and prefix in (b'DOTNET_ORIGINAL_V3_TRAP', b'DOTNET_ORIGINAL_V3_IDLE'),
            'dotnet-original-event-prefix')
        events.append((prefix, decode(data)))
    require(len(events) == 4, 'dotnet-original-two-traps-two-idles')
    for ordinal, mode in enumerate((9, 8)):
        prefix, row = events[ordinal*2]
        require(prefix == b'DOTNET_ORIGINAL_V3_TRAP'
            and set(row) == {'mode', 'component', 'observation', 'runtimeQualification',
                'originalFaultCauseQualified', 'opaqueCauseQualified', 'fullAC7Qualified', 'full746Qualified'}
            and type(row['mode']) is int and row['mode'] == mode and row['component'] == COMPONENT
            and all(row[k] is False for k in ('runtimeQualification', 'originalFaultCauseQualified',
                'opaqueCauseQualified', 'fullAC7Qualified', 'full746Qualified')), 'dotnet-original-closed-trap-row')
        s = row['observation']
        require(type(s) is dict and set(s) == {'observedErrors', 'ambiguous', 'trapKind', 'missingBacktrace',
            'mayBeTruncated', 'observedFrames', 'engineFrameCap', 'frames'}
            and type(s['observedErrors']) is int and s['observedErrors'] == 1 and s['ambiguous'] is False
            and s['trapKind'] == 'unreachable-code' and s['missingBacktrace'] is False
            and type(s['observedFrames']) is int and 1 <= s['observedFrames'] <= 16
            and type(s['engineFrameCap']) is int and s['engineFrameCap'] == 16
            and s['mayBeTruncated'] is (s['observedFrames'] == 16)
            and type(s['frames']) is list and len(s['frames']) == 16, 'dotnet-original-numeric-snapshot')
        modules = set()
        for position, frame in enumerate(s['frames']):
            if position >= s['observedFrames']:
                require(frame is None, 'dotnet-original-frame-tail'); continue
            require(type(frame) is dict and set(frame) == {'module', 'function', 'moduleOffset', 'functionOffset'}
                and type(frame['module']) is int and 0 <= frame['module'] <= len(modules) < 16
                and type(frame['function']) is int and 0 <= frame['function'] < 2**32
                and all(type(frame[k]) is int and 0 <= frame[k] < 2**32
                    for k in ('moduleOffset', 'functionOffset')), 'dotnet-original-numeric-frame')
            modules.add(frame['module'])
        prefix, idle = events[ordinal*2+1]
        require(prefix == b'DOTNET_ORIGINAL_V3_IDLE' and set(idle) == {'mode', 'newStores', 'liveStores',
            'liveInstances', 'activeActivations', 'reservedFuel', 'reservedMemory', 'cpuFuel',
            'peakMemoryBytes', 'physicalRetirementQualified', 'nativeAccountingComplete'}
            and type(idle['mode']) is int and idle['mode'] == mode and type(idle['newStores']) is int
            and idle['newStores'] == 1 and all(type(idle[k]) is int and idle[k] == 0 for k in
                ('liveStores', 'liveInstances', 'activeActivations', 'reservedFuel', 'reservedMemory'))
            and type(idle['cpuFuel']) is int and 0 < idle['cpuFuel'] <= BUDGET['cpuFuel']
            and type(idle['peakMemoryBytes']) is int and 0 < idle['peakMemoryBytes'] <= BUDGET['memoryBytes']
            and idle['physicalRetirementQualified'] is False and idle['nativeAccountingComplete'] is False,
            'dotnet-original-exact-idle')
    return [{'kind': prefix.decode(), 'observation': row} for prefix, row in events]


def qualify(archive, output, revision):
    require(os.environ.get('GITHUB_EVENT_NAME') in ('push', 'workflow_dispatch')
        and os.environ.get('GITHUB_REF') == 'refs/heads/diag/dotnet-original-v3-trap-20261031'
        and os.environ.get('GITHUB_REPOSITORY') == 'KirilsTurkins/latent-service-fabric',
        'dotnet-original-explicit-owned-diagnostic-branch')
    require(sys.platform == 'linux' and sys.version_info >= (3, 13), 'dotnet-original-linux-python313')
    require(re.fullmatch(r'[0-9a-f]{40}', revision) is not None, 'dotnet-original-source-revision')
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
        'dotnet-original-external-output')
    output = fresh(output); deadline = float(os.environ['LSF_ROOT_RETURN_DEADLINE'])
    require(time.monotonic() < deadline <= time.monotonic()+1320, 'dotnet-original-one-deadline')
    environment = build_environment(output)
    environment.update(CARGO_TARGET_DIR=str(ROOT/'target'), CARGO_INCREMENTAL='0', CARGO_BUILD_JOBS='2',
        CARGO_PROFILE_DEV_DEBUG='0', CARGO_PROFILE_TEST_DEBUG='0', CARGO_PROFILE_DEV_DEBUG_ASSERTIONS='true',
        CARGO_PROFILE_TEST_DEBUG_ASSERTIONS='true', CARGO_PROFILE_DEV_OVERFLOW_CHECKS='true',
        CARGO_PROFILE_TEST_OVERFLOW_CHECKS='true', RUSTUP_TOOLCHAIN='1.97.1', RUSTUP_AUTO_INSTALL='0')
    shared = {'bytes': 0, 'records': []}
    commands = JoinCauseCommands(ROOT, fresh(output/'commands'), environment, shared, deadline)
    record = {'schemaVersion': 'latent.dotnet.original-v3-numeric-observation.v1', 'status': 'incomplete',
        'runtimeQualification': False, 'full746Qualified': False, 'fullAC7Qualified': False,
        'originalFaultCauseQualified': False, 'opaqueCauseQualified': False,
        'physicalRetirementQualified': False, 'nativeAccountingComplete': False,
        'guestCompilerCorelibRebuilt': False, 'auxiliaryRewritePerformed': False,
        'normal15OutcomeReceiptChanged': False, 'sourceRevision': revision, 'ownerCaps': OWNER_CAPS,
        'hermetic': False, 'implicitCompilerInputsAttested': False,
        'diagnosticIoMayPerturbTimingAndTerminalObservation': True,
        'limits': {'absoluteSeconds': 1320, 'commandSeconds': 600, 'cleanupReserveSeconds': 5,
            'jobs': 2, 'commandCount': 128, 'diagnosticBytes': 16*1024**2, 'publicBytes': 128*1024**2}}
    try:
        require(commands.run('source-revision', 'git', 'rev-parse', 'HEAD').decode().strip() == revision
            and not commands.run('source-clean', 'git', 'status', '--porcelain'), 'dotnet-original-clean-source')
        before = source_map(); write_json(output/'current-git-inputs.json', before)
        record['original'] = restore(archive, output/'dotnet-root-return-normal', commands.deadline)
        from tools.phase3_resource_identity import file_identity
        native = {}
        for name in ('rustc', 'cargo'):
            raw = commands.run(name+'-path', 'rustup', 'which', '--toolchain', '1.97.1', name)
            require(len(raw) <= 4096, 'dotnet-original-tool-path-bound')
            path = Path(raw.decode().strip())
            require(path.is_absolute() and path.is_file() and not path.is_symlink(),
                'dotnet-original-tool-regular-path')
            native[name] = path.resolve(strict=True)
            require(commands.run(name+'-version', native[name], '--version').decode().startswith(name+' 1.97.1 ('),
                'dotnet-original-tool-pin')
        tool_identities = {n: file_identity(p, 512*1024**2) for n, p in native.items()}
        record['buildToolIdentities'] = tool_identities
        environment['RUSTC'] = str(native['rustc'])
        commands.run('only-current-diagnostic-host-build', native['cargo'], '--config', '.cargo/managed-guest.toml',
            'test', '--locked', '-p', 'latent-wasmtime', '--features', 'development-test-host',
            '--lib', '--test', 'local_service', '--no-run', '--message-format=json')
        suites = (artifacts.Suite('crates/latent-wasmtime/Cargo.toml', 'latent_wasmtime', 'src/lib.rs',
            CONTROL, frozenset({CONTROL}), False, kind='lib'),
            artifacts.Suite('crates/latent-wasmtime/Cargo.toml', 'local_service', 'tests/local_service.rs',
            CASE, frozenset({CASE}), True, kind='test'))
        inventory = Path(next(row['logs']['stdout'] for row in shared['records']
            if row['stage'] == 'only-current-diagnostic-host-build'))
        owners = [artifacts.read_inventory(inventory, ROOT, suite, target=ROOT/'target') for suite in suites]
        def library_probe(argv, *, cwd, env, timeout, maximum):
            require(argv == ['rustc', '--print', 'target-libdir'] and cwd == ROOT and timeout == 30 and maximum == 4096,
                'dotnet-original-library-probe')
            commands.environment = env; commands.command_seconds = 25
            raw = commands.run('rust-library-path', native['rustc'], *argv[1:])
            require(len(raw) <= maximum, 'dotnet-original-library-path-bound'); return 0, raw
        record['executables'] = []
        executable_identities = {}
        for ordinal, (suite, owner) in enumerate(zip(suites, owners, strict=True)):
            from tools.phase3_resource_identity import file_identity
            executable_identities[owner.executable] = file_identity(owner.executable, 512*1024**2)
            record['executables'].append(executable_identities[owner.executable])
            commands.environment = artifacts.cargo_environment(ROOT, owner, environment,
                target=ROOT/'target', execute=library_probe)
            commands.environment.update(LSF_GUEST_SDK_LANGUAGE='dotnet', LSF_GUEST_CAPSULES=str(output))
            selection = (suite.filter, '--exact', '--ignored') if ordinal else (suite.filter, '--exact')
            commands.command_seconds = 25
            listed = commands.run('list-'+str(ordinal), owner.executable, *selection, '--list')
            artifacts.validate_listing(listed, suite)
            commands.command_seconds = 300 if ordinal else 60
            raw = commands.run('execute-'+str(ordinal), owner.executable, *selection, '--show-output', '--test-threads=1')
            require(re.search(rb'^test result: ok\. 1 passed; 0 failed; 0 ignored; 0 measured; [0-9]+ filtered out; finished in [0-9.]+s$',
                raw, re.M), 'dotnet-original-exact-test-result')
            if ordinal: record['observations'] = observations(raw)
        commands.environment = environment
        require(source_map() == before
            and not commands.run('source-clean-after', 'git', 'status', '--porcelain')
            and tool_identities == {n: file_identity(p, 512*1024**2) for n, p in native.items()}
            and all(file_identity(p, 512*1024**2) == v for p, v in executable_identities.items())
            and identity(read_file(archive, ORIGINAL['bytes'])) ==
                {'bytes': ORIGINAL['bytes'], 'sha256': 'sha256:'+ORIGINAL['sha256']},
            'dotnet-original-source-tools-executables-archive-after')
        require(all(identity(read_file(output/'dotnet-root-return-normal'/n, 64*1024**2)) ==
            {k: row[k] for k in ('bytes', 'sha256')} for n, row in PACKAGE.items()), 'dotnet-original-package-after')
        record.update(status='captured-nonqualifying', sourceBeforeEqualsAfter=True)
        return record
    except BaseException:
        record['status'] = 'failed'; raise
    finally:
        record.update(commandCount=len(shared['records']), diagnosticBytes=shared['bytes'])
        write_json(output/'observation-result.json', record)
        write_json(output/'commands.json', shared['records'])
        join_public_admission(output)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--source-commit', required=True)
    args = parser.parse_args(argv)
    qualify(args.archive.resolve(strict=True), args.output.resolve(), args.source_commit)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
