"""Explicit, one-shot Windows copy/replay after successful Linux packaging.

Never execute this preparation until the parent confirms Linux package success
and the separately owned Docker dependency is populated. No input is deleted.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import time

MAIN = Path('C:/Users/turkins/Desktop/latent-fabric')
NOTES = MAIN / 'target/phase1-extension'
REPORT = MAIN / 'benchmarks/optimization/kubernetes-comparison/2026-09-11-container-linux-8b0441f'
DEPS = Path('C:/Users/turkins/Desktop/latent-fabric-phase1/target/phase1/measurement-python-deps')
CONTAINER = '64536d1cd190483798c77dbd6a164ffc03195335ab9bbe50583517603614f961'
PACKAGE = '/work/kubernetes-package-01'
ANALYSIS = '/work/full-validation-02/report'
VALIDATOR_REF = '10d50e61c5632ea2361a16dffc3b4819987f4dc4'
MEASURED_REF = '8b0441fb5b052c7b103f55a4f2ab2e72b5a4add5'
LIMIT = 600 * 1024**2
RESERVE = 8 * 1024**2  # Bounded replay log, receipts and subsequent report prose.
CHUNK = 64 * 1024
LOG_LIMIT = 4 * 1024**2
TABLES = ('phase_rows', 'phase_comparisons', 'resource_points', 'resource_comparisons', 'idle_windows',
    'idle_window_comparisons', 'lifecycle_owners', 'lifecycle_cohorts', 'lifecycle_comparisons',
    'client_resource_points', 'client_intervals', 'client_cpu_comparisons', 'platform_comparisons',
    'node_resource_points', 'node_resource_intervals', 'cpu_limit_cohorts')

# The remote program only reads fixed verifier files. Its copy mode emits at
# most the predeclared bytes, preserves failure, and never executes evidence.
REMOTE = r'''
import hashlib,json,os,re,stat,sys
from pathlib import Path
CHUNK=65536
package=Path('/work/kubernetes-package-01'); report=Path('/work/full-validation-02/report')
def ordinary(path):
    for parent in (path,*path.parents):
        assert not parent.is_symlink(), 'remote-symlink'
    value=path.stat(); assert stat.S_ISREG(value.st_mode), 'remote-nonregular'
    return value
def identity(path, maximum):
    before=ordinary(path); assert before.st_size<=maximum
    total=0; digest=hashlib.sha256()
    with path.open('rb') as stream:
        while chunk:=stream.read(CHUNK):
            total+=len(chunk); assert total<=maximum; digest.update(chunk)
    after=ordinary(path)
    assert (before.st_size,before.st_mtime_ns,before.st_ino)==(after.st_size,after.st_mtime_ns,after.st_ino)
    assert total==before.st_size
    return {'bytes':str(total),'sha256':'sha256:'+digest.hexdigest()}
def load(path, maximum):
    assert ordinary(path).st_size<=maximum
    return json.loads(path.read_bytes())
if sys.argv[1]=='copy':
    source=Path(sys.argv[2]); expected=int(sys.argv[3]); checksum=sys.argv[4]
    assert source.parent in (package,report) and re.fullmatch(r'[A-Za-z0-9_.-]+',source.name)
    before=ordinary(source); assert before.st_size==expected and expected<=50000000
    remaining=expected; digest=hashlib.sha256()
    with source.open('rb') as stream:
        while remaining:
            chunk=stream.read(min(CHUNK,remaining)); assert chunk, 'copy-truncated'
            digest.update(chunk); sys.stdout.buffer.write(chunk); remaining-=len(chunk)
        assert stream.read(1)==b'', 'copy-source-grew'
    sys.stdout.buffer.flush()
    after=ordinary(source)
    assert (before.st_size,before.st_mtime_ns,before.st_ino)==(after.st_size,after.st_mtime_ns,after.st_ino)
    assert 'sha256:'+digest.hexdigest()==checksum, 'copy-source-changed'
else:
    receipt_path=Path(sys.argv[2]); validator_ref=sys.argv[3]; measured_ref=sys.argv[4]
    tables=json.loads(sys.argv[5])
    assert receipt_path.parent==Path('/work') and re.fullmatch(r'kubernetes-publication-[a-z-]+-[0-9]{2}\.json',receipt_path.name)
    receipt=load(receipt_path,4*1024**2)
    assert receipt['status']=='packaged-and-replayed' and receipt['failure'] is None
    assert receipt['package']==str(package) and receipt['validator_source']['commit']==validator_ref
    assert receipt['validator_source']['clean'] is True
    manifest=load(package/'raw-evidence.manifest.json',4*1024**2)
    assert manifest==receipt['manifest'] and manifest['schema']=='latent.phase1.archive-manifest.v1'
    assert 0<len(manifest['files'])<=8000 and int(manifest['total_bytes'])<=1024**3
    parts=load(package/'raw-evidence.parts.json',8192)
    assert parts['schema']=='latent.phase1.archive-parts.v1' and parts['archive']==manifest['archive']
    assert parts['archive']['path']=='raw-evidence.tar.gz' and 0<int(parts['archive']['bytes'])<=198000000
    assert 2<=len(parts['parts'])<=4
    names={'aggregate.json','raw-evidence.manifest.json','raw-evidence.parts.json','raw-evidence.tar.gz.sha256'}
    logical=hashlib.sha256(); total=0
    for index,part in enumerate(parts['parts'],1):
        assert part['path']==f'raw-evidence.tar.gz.part-{index:04d}' and 0<int(part['bytes'])<=50000000
        assert identity(package/part['path'],50000000)=={key:part[key] for key in ('bytes','sha256')}
        names.add(part['path'])
        with (package/part['path']).open('rb') as stream:
            while chunk:=stream.read(CHUNK): logical.update(chunk); total+=len(chunk)
    assert total==int(parts['archive']['bytes']) and 'sha256:'+logical.hexdigest()==parts['archive']['sha256']
    assert {path.name for path in package.iterdir()}==names
    assert (package/'raw-evidence.tar.gz.sha256').read_bytes()==(parts['archive']['sha256'][7:]+'  raw-evidence.tar.gz\n').encode()
    report_names={'aggregate.json','docker-aggregate.json','manifest.json',*(name.replace('_','-')+'.csv' for name in tables)}
    assert {path.name for path in report.iterdir()}==report_names
    package_files={name:identity(package/name,50000000) for name in sorted(names)}
    report_files={name:identity(report/name,8*1024**2) for name in sorted(report_names)}
    assert package_files['aggregate.json']==report_files['aggregate.json']
    summary=load(package/'aggregate.json',8*1024**2)
    assert summary['schema']=='latent.optimization.kubernetes-aggregate.v1' and summary['status']=='complete'
    assert summary['profile']=='full' and summary['source']['commit']==measured_ref and summary['source']['clean'] is True
    assert summary['logical_offers']=='9926' and summary['validated_pairs']==7 and summary['acceptance_qualified'] is True
    table_manifest=load(report/'manifest.json',8*1024**2)
    assert table_manifest['schema']=='latent.optimization.kubernetes-aggregate-files.v1'
    assert table_manifest['profile']=='full' and table_manifest['suite_sha256']==summary['suite_sha256']
    assert {row['path'] for row in table_manifest['files']}==report_names-{'manifest.json'}
    assert len(table_manifest['files'])==len(report_names)-1
    for row in table_manifest['files']:
        assert report_files[row['path']]=={key:row[key] for key in ('bytes','sha256')}
    print(json.dumps({'package':package_files,'reports':report_files,'archive':manifest['archive'],
        'member_count':len(manifest['files']),'expanded_bytes':manifest['total_bytes'],
        'linux_receipt':{'path':str(receipt_path),**identity(receipt_path,4*1024**2)},
        'linux_validator_source':receipt['validator_source'],'suite_sha256':summary['suite_sha256']},sort_keys=True))
'''


def require(condition, message):
    if not condition:
        raise ValueError(message)


def now():
    return datetime.now(timezone.utc).isoformat()


def ordinary(path, directory=False):
    value = path.lstat()
    require(not stat.S_ISLNK(value.st_mode) and not getattr(value, 'st_file_attributes', 0) & 0x400,
            'symlink-or-reparse:' + str(path))
    require(stat.S_ISDIR(value.st_mode) if directory else stat.S_ISREG(value.st_mode), 'nonordinary:' + str(path))
    return value


def safe_parent(path):
    for parent in (*reversed(path.parents), path):
        if parent.exists() or parent.is_symlink():
            ordinary(parent, directory=True)


def identity(path, maximum=256 * 1024**2):
    before = ordinary(path)
    require(before.st_size <= maximum, 'file-bound:' + str(path))
    digest, total = hashlib.sha256(), 0
    with path.open('rb') as stream:
        while chunk := stream.read(CHUNK):
            total += len(chunk)
            require(total <= maximum, 'file-growth-bound')
            digest.update(chunk)
    after = ordinary(path)
    require((before.st_size, before.st_mtime_ns, before.st_ino) ==
            (after.st_size, after.st_mtime_ns, after.st_ino) and total == before.st_size, 'file-changed')
    return {'bytes': str(total), 'sha256': 'sha256:' + digest.hexdigest()}


def benchmarks_bytes():
    total, count, pending = 0, 0, [MAIN / 'benchmarks']
    while pending:
        directory = pending.pop()
        ordinary(directory, directory=True)
        for path in directory.iterdir():
            count += 1
            require(count <= 50000, 'benchmarks-entry-bound')
            information = path.lstat()
            if stat.S_ISDIR(information.st_mode):
                ordinary(path, directory=True)
                pending.append(path)
            else:
                total += ordinary(path).st_size
            require(total <= LIMIT, 'benchmarks-already-over-600MiB')
    return total


def git(*arguments):
    result = subprocess.run(['git', '-C', str(MAIN), *arguments], capture_output=True, timeout=30)
    require(result.returncode == 0 and len(result.stdout) <= 1024**2, 'git-source-check-failed')
    return result.stdout.decode().strip()


def source(expected):
    require(re.fullmatch(r'[0-9a-f]{40}', expected), 'exact-validator-ref')
    # Report/retention commits may advance HEAD while the installed tool closure
    # remains identical. Record both identities instead of relabelling source.
    git('diff', '--exit-code', expected, '--', 'tools', 'Cargo.lock')
    require(not git('status', '--porcelain=v1', '--untracked-files=all', '--', 'tools'), 'dirty-validator-tools')
    return {'commit': git('rev-parse', 'HEAD'), 'tree': git('rev-parse', 'HEAD^{tree}'),
            'validator_reference': expected, 'validator_reference_tree': git('rev-parse', expected + '^{tree}'),
            'tool_closure_matches_reference': True,
            'entrypoint': identity(MAIN / 'tools/validate_phase1_archive.py', 1024**2)}


def write_new(path, value):
    encoded = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
    require(len(encoded) <= 1024**2, 'receipt-bound')
    with path.open('xb') as stream:
        stream.write(encoded)


def remote(docker, mode, arguments, commands, destination=None):
    command = [str(docker), 'exec', '-i', CONTAINER, 'python3', '-', mode, *arguments]
    row = {'command': command, 'started_utc': now(), 'started_nanos': str(time.monotonic_ns()),
           'exit_code': None, 'remote_program_sha256': 'sha256:' + hashlib.sha256(REMOTE.encode()).hexdigest()}
    commands.append(row)
    try:
        if destination is None:
            result = subprocess.run(command, input=REMOTE.encode(), capture_output=True, timeout=300)
            require(len(result.stdout) <= 128 * 1024, 'remote-inventory-output-bound')
            row['stdout'] = result.stdout.decode('utf-8')
        else:
            with destination.open('xb') as stream:
                result = subprocess.run(command, input=REMOTE.encode(), stdout=stream, stderr=subprocess.PIPE, timeout=300)
        row['exit_code'] = result.returncode
        require(len(result.stderr) <= 65536, 'remote-stderr-bound')
        row['stderr'] = result.stderr.decode('utf-8', errors='replace')
        require(result.returncode == 0 and not result.stderr, 'remote-command-not-clean')
        return json.loads(result.stdout) if destination is None else None
    finally:
        row['finished_nanos'] = str(time.monotonic_ns())
        row['finished_utc'] = now()


def replay(package, dependency, validation, record):
    command = [sys.executable, str(MAIN / 'tools/validate_phase1_archive.py'), str(package),
               '--docker-package', str(dependency)]
    log = validation / 'windows-replay.log'
    record.update(command=command, started_utc=now(), started_nanos=str(time.monotonic_ns()),
                  exit_code=None, process_id=None, reaped=False, output_closed=False, timed_out=False)
    environment = dict(os.environ, PYTHONPATH=os.pathsep.join((str(DEPS), str(MAIN))), PYTHONDONTWRITEBYTECODE='1')
    began = time.monotonic()
    child = None
    try:
        with log.open('xb') as stream:
            child = subprocess.Popen(command, cwd=MAIN, env=environment, stdin=subprocess.DEVNULL,
                                     stdout=stream, stderr=subprocess.STDOUT)
            record['process_id'] = child.pid
            while child.poll() is None:
                require(log.stat().st_size <= LOG_LIMIT, 'windows-replay-log-bound')
                if time.monotonic() - began >= 3600:
                    record['timed_out'] = True
                    raise TimeoutError('windows-replay-3600s-bound')
                time.sleep(0.25)
            record['exit_code'] = child.wait()
            record['reaped'] = True
        record['output_closed'] = True
        record['log'] = {'path': 'windows-replay.log', **identity(log, LOG_LIMIT)}
        require(record['exit_code'] == 0, 'windows-archive-replay-failed')
    finally:
        if child is not None and child.poll() is None:
            child.kill()
            record['exit_code'] = child.wait(timeout=30)
            record['reaped'] = True
        record['finished_nanos'] = str(time.monotonic_ns())
        record['finished_utc'] = now()
        record['elapsed_nanos'] = str(time.monotonic_ns() - int(record['started_nanos']))
        if log.exists():
            record['output_closed'] = True
            record['log'] = {'path': 'windows-replay.log', **identity(log, LOG_LIMIT + CHUNK)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--linux-package-receipt', required=True,
                        help='Successful /work/kubernetes-publication-package-NN.json from the Linux packager')
    parser.add_argument('--validator-ref', default=VALIDATOR_REF)
    parser.add_argument('--docker-package', type=Path, default=NOTES / 'issue112-docker-replay-dependency-01')
    args = parser.parse_args()
    require(sys.platform == 'win32', 'windows-only')
    require(Path(__file__).resolve().parent == NOTES.resolve(), 'helper-location')
    require(re.fullmatch(r'/work/kubernetes-publication-[a-z-]+-[0-9]{2}\.json', args.linux_package_receipt), 'linux-receipt-scope')
    require(not REPORT.exists() and not REPORT.is_symlink(), 'fresh-public-report-required')
    for path in (MAIN, NOTES, REPORT.parent, DEPS, args.docker_package):
        safe_parent(path)
    require(DEPS.is_dir() and args.docker_package.is_dir(), 'dependency-not-ready')
    receipt_path = NOTES / 'issue112-windows-publication-01.json'
    require(not receipt_path.exists(), 'fresh-support-receipt-required')
    docker = shutil.which('docker')
    require(docker is not None, 'docker-cli-required')
    record = {'schema': 'latent.optimization.kubernetes-windows-publication.v1', 'status': 'incomplete',
              'failure': None, 'started_utc': now(), 'started_nanos': str(time.monotonic_ns()),
              'source': source(args.validator_ref), 'helper': identity(Path(__file__), 128 * 1024),
              'linux_container_id': CONTAINER, 'linux_package': PACKAGE, 'linux_report': ANALYSIS,
              'public_report': str(REPORT), 'docker_dependency': str(args.docker_package), 'commands': [], 'copies': []}
    windows = {'schema': 'latent.optimization.kubernetes-windows-archive-replay.v1', 'status': 'not-started',
               'qualified_campaign_claim': False, 'source': record['source'], 'failure': None}
    code = 1
    try:
        sys.path.insert(0, str(MAIN))
        from tools import validate_phase1_archive as archive
        dependency = archive.load_manifest(args.docker_package)
        require(dependency['archive']['sha256'] ==
                'sha256:b51441c7d23eb9569f77d00026533e9a5395c7732b1109b38cfbc3defeca43fd', 'wrong-original-Docker-dependency')
        # Validate part bytes without the expensive semantic replay, which the
        # required Windows archive CLI performs once below.
        with archive.archive_input(args.docker_package, dependency):
            pass
        inventory = remote(docker, 'inspect', [args.linux_package_receipt, args.validator_ref, MEASURED_REF,
                           json.dumps(TABLES)], record['commands'])
        record['linux_inventory'] = inventory
        selected = [(PACKAGE + '/' + name, name, row) for name, row in inventory['package'].items()]
        selected.extend((ANALYSIS + '/' + name, 'tables.manifest.json' if name == 'manifest.json' else name, row)
                        for name, row in inventory['reports'].items() if name != 'aggregate.json')
        require(len({name for _, name, _ in selected}) == len(selected), 'duplicate-public-destination')
        before = benchmarks_bytes()
        addition = sum(int(row['bytes']) for _, _, row in selected)
        record.update(benchmarks_bytes_before=str(before), selected_bytes=str(addition), reserve_bytes=str(RESERVE),
                      benchmarks_limit_bytes=str(LIMIT))
        require(before + addition + RESERVE <= LIMIT, 'entire-benchmarks-600MiB-preflight')
        require(shutil.disk_usage(MAIN).free >= 4 * 1024**3 + addition, 'windows-replay-disk-headroom')
        REPORT.mkdir(parents=True)
        validation = REPORT / 'validation'
        validation.mkdir()
        for source_path, name, expected in selected:
            remote(docker, 'copy', [source_path, expected['bytes'], expected['sha256']], record['commands'], REPORT / name)
            require(identity(REPORT / name) == expected, 'linux-public-copy-hash')
            record['copies'].append({'source': source_path, 'path': name, **expected})
        with (REPORT / '.gitattributes').open('xb') as stream:
            stream.write(b'* -text\n')
        with (validation / 'windows-publication.py').open('xb') as stream:
            stream.write(Path(__file__).read_bytes())
        require(identity(validation / 'windows-publication.py') == record['helper'], 'published-helper-hash')
        windows.update(status='running', package_inventory=inventory['package'], suite_sha256=inventory['suite_sha256'],
                       linux_package_receipt=inventory['linux_receipt'], docker_archive=dependency['archive'])
        replay(REPORT, args.docker_package, validation, windows)
        for _, name, expected in selected:
            require(identity(REPORT / name) == expected, 'published-input-changed-during-replay')
        after = remote(docker, 'inspect', [args.linux_package_receipt, args.validator_ref, MEASURED_REF,
                       json.dumps(TABLES)], record['commands'])
        require(after == inventory, 'linux-package-or-table-changed')
        require(source(args.validator_ref) == record['source'], 'installed-validator-source-changed')
        require(identity(Path(__file__), 128 * 1024) == record['helper'], 'publication-helper-changed')
        record['benchmarks_bytes_after'] = str(benchmarks_bytes())
        windows.update(status='passed', package_unchanged=True, linux_public_bytes_identical=True)
        record['status'] = 'copied-and-Windows-replayed'
        code = 0
    except BaseException as error:
        failure = {'type': type(error).__name__, 'reason': str(error)[:4096]}
        record.update(status='failed-all-originals-and-partial-copies-retained', failure=failure)
        windows.update(status='failed' if windows['status'] != 'not-started' else 'not-started', failure=failure)
    finally:
        record['finished_utc'], record['finished_nanos'] = now(), str(time.monotonic_ns())
        if (REPORT / 'validation').is_dir():
            write_new(REPORT / 'validation/windows-replay.json', windows)
            record['windows_receipt'] = identity(REPORT / 'validation/windows-replay.json', 1024**2)
        write_new(receipt_path, record)
        # This support receipt excludes itself and contains only input/receipt
        # identities, so publishing the same exact bytes creates no hash cycle.
        if (REPORT / 'validation').is_dir():
            with (REPORT / 'validation/windows-publication.json').open('xb') as stream:
                stream.write(receipt_path.read_bytes())
        print(json.dumps({'status': record['status'], 'receipt': str(receipt_path), 'failure': record['failure']}))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
