"""Compare one source-identical diagnostic fixture on baseline and fixed CoreLibs."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_observation import build_environment
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_dotnet_poll_prefetch import common_installation, package_hash_snapshot
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import checked_path, digest, fresh, inventory, read_json, snapshot, write_json

FIXTURE = 'tools/fixtures/dotnet-poll-prefetch/Library.cs'
FIX_PATHS = frozenset(('sdk/dotnet-guest/tools/http-errors/AggregateTaskWait.cs',
    'tools/dotnet_guest/aggregate_task_wait.py', 'tools/dotnet_guest/task_wait.py',
    'tools/tests/test_dotnet_aggregate_task_wait.py', 'tools/tests/test_dotnet_managed_work.py'))
SOURCE = 'sha256:29e4bd3f70bfb0e0ea00fb2511e28ee9832b56caf9ddb5cd60906fe3bcaad735'
PACKAGE_HASH_SOURCE = 'sdk/dotnet-guest/tools/package-hash'
PACKAGE_HASH_GENERATED = frozenset(('PackageHash.dll', 'PackageHash.pdb'))
PACKAGE_HASH_REQUIRED = frozenset(('PackageHash.dll', 'PackageHash.deps.json', 'PackageHash.runtimeconfig.json'))


def snapshot_identity(files):
    return {'sha256': digest(inventory(files)), 'files': len(files), 'bytes': sum(map(len, files.values()))}


def share_package_hash(baseline, fixed, baseline_tools, fixed_tools, record):
    """Select the baseline's authenticated tool output for both isolated variants."""
    record.update(status='incomplete', stage='source')
    baseline, fixed, baseline_tools, fixed_tools = (checked_path(Path(path))
        for path in (baseline, fixed, baseline_tools, fixed_tools))
    require(all(left != right and left not in right.parents and right not in left.parents
        for index, left in enumerate((baseline, fixed, baseline_tools, fixed_tools))
        for right in (baseline, fixed, baseline_tools, fixed_tools)[index + 1:]),
        'poll-prefetch-pair-package-hash-separated-inputs')
    sources = {'baselineCheckout': snapshot(baseline / PACKAGE_HASH_SOURCE),
        'fixedCheckout': snapshot(fixed / PACKAGE_HASH_SOURCE),
        'baselineInstalled': snapshot(baseline_tools / 'package-hash-source'),
        'fixedInstalled': snapshot(fixed_tools / 'package-hash-source')}
    record['sources'] = {name: snapshot_identity(files) for name, files in sources.items()}
    source = sources['baselineCheckout']
    require(bool(source) and all(value == source for value in sources.values()),
        'poll-prefetch-pair-package-hash-exact-source')
    record['stage'] = 'output-preconditions'
    old = package_hash_snapshot(baseline_tools / 'package-hash')
    new = package_hash_snapshot(fixed_tools / 'package-hash')
    record['before'] = {'baseline': snapshot_identity(old), 'fixed': snapshot_identity(new)}
    require(PACKAGE_HASH_REQUIRED <= old.keys() and old.keys() == new.keys()
        and all(old[name] == new[name] for name in old if name not in PACKAGE_HASH_GENERATED),
        'poll-prefetch-pair-package-hash-dependencies')
    differences = sorted(name for name in old if old[name] != new[name])
    record['selectedBaselineOutputs'] = {name: {'baseline': {'sha256': digest(old[name]), 'bytes': len(old[name])},
        'fixedBefore': {'sha256': digest(new[name]), 'bytes': len(new[name])}} for name in differences}
    require(package_hash_snapshot(baseline_tools / 'package-hash') == old
        and package_hash_snapshot(fixed_tools / 'package-hash') == new,
        'poll-prefetch-pair-package-hash-unchanged-before-selection')
    record['stage'] = 'select-baseline-generated-outputs'
    for name in differences:
        path = fixed_tools / 'package-hash' / name
        before = path.lstat()
        fd = os.open(path, os.O_RDWR | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(fd, 'r+b') as target:
            opened = os.fstat(target.fileno())
            require(stat.S_ISREG(opened.st_mode) and
                (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) ==
                (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns),
                'poll-prefetch-pair-package-hash-regular-output')
            require(target.read() == new[name], 'poll-prefetch-pair-package-hash-output-unchanged')
            target.seek(0); target.write(old[name]); target.truncate(); target.flush()
    record['stage'] = 'verify-shared-output'
    final = package_hash_snapshot(fixed_tools / 'package-hash')
    record['after'] = {'baseline': snapshot_identity(package_hash_snapshot(baseline_tools / 'package-hash')),
        'fixed': snapshot_identity(final)}
    require(final == old and package_hash_snapshot(baseline_tools / 'package-hash') == old
        and all(snapshot(path) == source for path in (baseline / PACKAGE_HASH_SOURCE,
            fixed / PACKAGE_HASH_SOURCE, baseline_tools / 'package-hash-source', fixed_tools / 'package-hash-source')),
        'poll-prefetch-pair-package-hash-shared-output-and-source')
    record.update(status='passed', stage='complete')


def failed_variant_cleaned(path):
    # Only a known, reaped mismatch followed by the normal retirement and
    # clean shutdown can authorize a second independent observation.
    try:
        value = read_json(Path(path) / 'node/FAILED.json')
        attempt, = value['attempts']
        return (value['schemaVersion'] == 'latent.dotnet.poll-prefetch.node.v1'
            and value['status'] == 'failed' and value['stage'] == 'one-actual-prefetch-observation'
            and value['resultMatched'] is False
            and attempt['invocation']['processReaped'] is True
            and attempt['invocation']['response']['outcomeKnown'] is True
            and isinstance(value['retirement']['provider'], dict)
            and isinstance(value['retirement']['physical'], dict)
            and isinstance(value['afterDeletes'], dict)
            and value['nodeShutdown']['reaped'] is True and value['nodeShutdown']['record']['clean'] is True
            and value['peerShutdown']['reaped'] is True and value['peerShutdown']['closed'] is True
            and value['peerShutdown']['exitCode'] == 0)
    except (OSError, ValueError, TypeError, KeyError):
        return False


def pair(baseline, fixed, native, baseline_tools, fixed_tools, output, *, expected_base, expected_head):
    require(sys.platform == 'linux' and sys.version_info >= (3, 13), 'poll-prefetch-pair-linux-python313')
    require(type(expected_head) is str and re.fullmatch(r'[0-9a-f]{40}', expected_head)
        and type(expected_base) is str and re.fullmatch(r'[0-9a-f]{40}', expected_base),
        'poll-prefetch-pair-exact-commit-identities')
    baseline, fixed, native, baseline_tools, fixed_tools = (Path(path).resolve(strict=True)
        for path in (baseline, fixed, native, baseline_tools, fixed_tools))
    require(baseline != fixed and baseline not in fixed.parents and fixed not in baseline.parents,
        'poll-prefetch-pair-separate-checkouts')
    require(baseline_tools != fixed_tools and baseline_tools not in fixed_tools.parents
        and fixed_tools not in baseline_tools.parents, 'poll-prefetch-pair-separate-installations')
    def git(root, *args):
        return subprocess.check_output(['git', *args], cwd=root, timeout=30).decode().strip()
    first, second = git(baseline, 'rev-parse', 'HEAD'), git(fixed, 'rev-parse', 'HEAD')
    require(second == expected_head and git(fixed, 'rev-parse', 'HEAD^') == first
        and git(baseline, 'rev-parse', 'HEAD^') == expected_base
        and Path(git(baseline, 'rev-parse', '--show-toplevel')).resolve() == baseline
        and Path(git(fixed, 'rev-parse', '--show-toplevel')).resolve() == fixed
        and not git(baseline, 'status', '--porcelain') and not git(fixed, 'status', '--porcelain'),
        'poll-prefetch-pair-exact-clean-parent-checkouts')
    changed = frozenset(git(fixed, 'diff', '--no-renames', '--name-only', first, second).splitlines())
    require(changed == FIX_PATHS and file_identity(baseline / FIXTURE) == file_identity(fixed / FIXTURE),
        'poll-prefetch-pair-only-reviewed-fix-and-identical-fixture')
    output = Path(output).absolute()
    require(all(output != path and output not in path.parents and path not in output.parents
        for path in (baseline, fixed, native, baseline_tools, fixed_tools)), 'poll-prefetch-pair-separated-output')
    output = fresh(output)
    commands = Commands(fixed, fresh(output / 'pair-commands'), build_environment(output),
        deadline_seconds=3000, command_seconds=1400)
    record = {'schemaVersion': 'latent.dotnet.poll-prefetch.pair.v1', 'status': 'incomplete',
        'base': expected_base, 'baseline': first, 'fixed': second, 'changedPaths': sorted(changed),
        'fixture': file_identity(fixed / FIXTURE),
        'changedInputs': {name: {'baseline': file_identity(baseline / name),
            'fixed': file_identity(fixed / name)} for name in sorted(changed)}, 'diagnosticOnly': True,
        'ordinaryRuntimeQualified': False, 'fullTicketQualification': False, 'attempts': []}
    try:
        baseline_common = common_installation(baseline_tools)
        fixed_common = common_installation(fixed_tools)
        record['commonInstallationsBefore'] = {'baseline': baseline_common, 'fixed': fixed_common}
        generated = {'package-hash/PackageHash.dll', 'package-hash-tree'}
        require({name: value for name, value in baseline_common.items() if name not in generated} ==
            {name: value for name, value in fixed_common.items() if name not in generated},
            'poll-prefetch-pair-shared-installation-drift')
        record['packageHashSynchronization'] = {}
        share_package_hash(baseline, fixed, baseline_tools, fixed_tools, record['packageHashSynchronization'])
        baseline_common = common_installation(baseline_tools)
        fixed_common = common_installation(fixed_tools)
        record['commonInstallations'] = {'baseline': baseline_common, 'fixed': fixed_common}
        require(baseline_common == fixed_common, 'poll-prefetch-pair-shared-installation-drift')
        for variant, root, commit, selected_tools in (('baseline', baseline, first, baseline_tools),
                ('fixed', fixed, second, fixed_tools)):
            attempt = {'variant': variant, 'source': commit, 'status': 'started'}
            record['attempts'].append(attempt); write_json(output / ('attempt-' + variant + '.json'), attempt)
            try:
                commands.run(variant, sys.executable, '-B', root / 'tools/qualify_dotnet_poll_prefetch.py',
                    '--native', native, '--tools', selected_tools, '--output', output / variant,
                    '--variant', variant, '--expected-head', commit)
                attempt['status'] = 'passed'
            except Exception as error:
                attempt.update(status='failed', errorCategory=type(error).__name__)
            write_json(output / ('result-' + variant + '.json'), attempt)
            if variant == 'baseline' and attempt['status'] == 'failed':
                require(failed_variant_cleaned(output / variant), 'poll-prefetch-pair-baseline-cleanup-required')
        require(all(x['status'] == 'passed' for x in record['attempts']), 'poll-prefetch-pair-variant-failed')
        before, after = (read_json(output / name / 'qualified.json') for name in ('baseline', 'fixed'))
        require(before['fixture'] == after['fixture'] == record['fixture']
            and before['nativeProducts'] == after['nativeProducts']
            and before['nativeSource'] == after['nativeSource']
            and before['runtimeInputs'] == after['runtimeInputs']
            and before['commonInstallation'] == after['commonInstallation'], 'poll-prefetch-pair-identical-inputs')
        old, new = before['freshBuild']['taskWaitPort'], after['freshBuild']['taskWaitPort']
        require(old['frameworkInput']['digest'] == new['frameworkInput']['digest'] == SOURCE
            and old['aggregateTaskWait']['patch'] == 'latent.dotnet.wait-all.v2'
            and new['aggregateTaskWait']['patch'] == 'latent.dotnet.wait-all.v3'
            and old['derived']['digest'] != new['derived']['digest']
            and before['result'] == 'prefetch-observed:driver-before-sibling'
            and after['result'] == 'prefetch-observed:sibling-before-driver',
            'poll-prefetch-pair-exact-corelibs-and-observations')
        require(not git(baseline, 'status', '--porcelain') and not git(fixed, 'status', '--porcelain')
            and git(baseline, 'rev-parse', 'HEAD') == first and git(fixed, 'rev-parse', 'HEAD') == second
            and file_identity(baseline / FIXTURE) == file_identity(fixed / FIXTURE) == record['fixture']
            and time.monotonic() < commands.deadline, 'poll-prefetch-pair-final-source-and-deadline')
        record.update(status='passed', installations={name: row['installation'] for name, row in
            (('baseline', before), ('fixed', after))},
            variantReceipts={name: file_identity(output / name / 'qualified.json')
            for name in ('baseline', 'fixed')}, commands=commands.records)
        write_json(output / 'qualified.json', record); return record
    except BaseException as error:
        selection = record.get('packageHashSynchronization')
        if selection is not None and selection.get('status') != 'passed':
            selection.update(status='failed', errorCategory=type(error).__name__)
        record.update(status='failed', errorCategory=type(error).__name__, commands=commands.records)
        write_json(output / 'FAILED.json', record); raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline', 'fixed', 'native', 'baseline-tools', 'fixed-tools', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--expected-base', required=True)
    parser.add_argument('--expected-head', required=True)
    args = parser.parse_args()
    print(pair(args.baseline, args.fixed, args.native, args.baseline_tools, args.fixed_tools, args.output,
        expected_base=args.expected_base, expected_head=args.expected_head)['status'])
