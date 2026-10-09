from pathlib import Path
import hashlib, json, os, shutil, stat, subprocess, sys, tarfile, time

SOURCE = '37b48cd8e485a826cd87e23aea184d99c17e4731'
PRODUCER = '761172002e4a4d02102f8c757235b888fe4859e1'
ARCHIVE = 'sha256:37e7225616c22665f39b2c50348be402cafb5cf087189eac77bef73ed70721c9'
POLICY = 'sha256:ce36420661807326255232c0542f334045af5a637a157ad3c99b7e77328ffcba'
work = Path('/work/java709-four-fresh-37b48cd8-r2')
work.mkdir(mode=0o700)
out = Path('/output')
source = work / 'source'
private_home = work / 'home'
private_home.mkdir(mode=0o700)
assert os.geteuid() == 23001 and sys.version_info[:3] == (3, 13, 5)
os.environ.update(HOME=str(private_home), PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')
started = time.monotonic()
commands = []
record = {'schemaVersion': 'latent.java.composition-diagnostic-compiler-process.v1',
    'sourceCommit': SOURCE, 'originalToolProducer': PRODUCER,
    'originalToolArchive': ARCHIVE, 'originalToolPolicy': POLICY,
    'compilerOnly': True, 'historicalNodeApprovalReused': False,
    'signedNodeExecutionQualified': False, 'compiled': False, 'componentExportAvailable': False}

def save():
    record['seconds'] = round(time.monotonic() - started, 6)
    (out / 'compiler-process-receipt.json').write_text(json.dumps(record, indent=2) + '\n')

def check():
    assert time.monotonic() - started < 4500, 'private compiler controller deadline exceeded'

def run(stage, args, cwd=None, timeout=180):
    check()
    mark = time.monotonic()
    try:
        result = subprocess.run(args, cwd=cwd, capture_output=True, timeout=timeout)
        stdout, stderr, code = result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired as error:
        stdout, stderr, code = error.stdout or b'', error.stderr or b'', f'timeout-{timeout}s'
    for suffix, raw in [('stdout', stdout), ('stderr', stderr)]:
        (out / (stage + '.' + suffix + '.txt')).write_bytes(raw)
    commands.append({'stage': stage, 'command': args, 'exitCode': code,
        'seconds': round(time.monotonic() - mark, 6), 'timeoutSeconds': timeout,
        'stdoutBytes': len(stdout), 'stderrBytes': len(stderr)})
    (out / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
    assert len(stdout) + len(stderr) <= 16 * 1024 * 1024
    assert code == 0, (stage, stderr.decode(errors='replace')[-2400:])

def identity(path):
    info = path.lstat()
    assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and not path.is_symlink(), str(path)
    raw = path.read_bytes()
    return {'bytes': len(raw), 'sha256': 'sha256:' + hashlib.sha256(raw).hexdigest()}

def export_capture(capture):
    retained = []
    total = 0
    for item in sorted(capture.rglob('*')):
        if item.is_dir(): continue
        check()
        info = identity(item)
        total += info['bytes']
        assert len(retained) < 8192 and total <= 134217728
        retained.append({'path': item.relative_to(capture).as_posix(), **info})
    (out / 'retained-capture-inventory.json').write_text(json.dumps({'files': retained,
        'totalBytes': total, 'excludedCaptureFiles': [], 'sourceCommit': SOURCE}, indent=2) + '\n')
    with tarfile.open(out / 'complete-compiler-capture.tar.gz', 'w:gz') as archive:
        for row in retained:
            archive.add(capture / row['path'], arcname='composition/' + row['path'], recursive=False)
    assert (out / 'complete-compiler-capture.tar.gz').stat().st_size <= 64 * 1024**2
    record.update(componentExportAvailable=True, completeCaptureFiles=len(retained), completeCaptureBytes=total,
                  completeCaptureArchive=identity(out / 'complete-compiler-capture.tar.gz'))


try:
    source_input = json.loads(Path('/controller/frozen-private-source-inputs.json').read_bytes())
    pack_record = json.loads(Path('/controller/actual-source-private-pack-receipt.json').read_bytes())
    assert source_input['sourceCommit'] == SOURCE == pack_record['sourceCommit']
    assert identity(Path('/inputs/fresh-37b48cd8-private-source.pack')) == pack_record['pack']
    packed = Path('/inputs/fresh-37b48cd8-private-source.pack').read_bytes()
    run('source-init', ['git', 'init', '--initial-branch=frozen', str(source)])
    (source / '.git/shallow').write_text(SOURCE + '\n')
    indexed = subprocess.run(['git', 'index-pack', '--stdin'], cwd=source,
                             input=packed, capture_output=True, timeout=180)
    (out / 'source-index.stdout.txt').write_bytes(indexed.stdout)
    (out / 'source-index.stderr.txt').write_bytes(indexed.stderr)
    assert indexed.returncode == 0
    del packed
    objects = set(subprocess.check_output(['git', 'cat-file', '--batch-all-objects',
                  '--batch-check=%(objectname)'], cwd=source).decode().splitlines())
    assert objects == set(source_input['selectedObjectIds'])
    run('source-origin', ['git', 'remote', 'add', 'origin',
                         'https://github.com/KirilsTurkins/latent-service-fabric.git'], source)
    run('source-sparse-init', ['git', 'sparse-checkout', 'init', '--no-cone'], source)
    patterns = ['/*'] + ['!/' + path for path in source_input['excludedHistoricalBenchmarkData']]
    selected = subprocess.run(['git', 'sparse-checkout', 'set', '--no-cone', '--stdin'],
        cwd=source, input=('\n'.join(patterns) + '\n').encode(), capture_output=True, timeout=180)
    (out / 'source-sparse.stdout.txt').write_bytes(selected.stdout)
    (out / 'source-sparse.stderr.txt').write_bytes(selected.stderr)
    assert selected.returncode == 0
    run('source-checkout', ['git', 'checkout', '--detach', SOURCE], source)
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source).decode().strip() == SOURCE
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=source).decode().strip() == source_input['sourceTree']
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=source)
    verified = []
    for row in source_input['selectedTrackedRows']:
        path = source / row['path']
        info = identity(path)
        raw = path.read_bytes()
        assert hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == row['object']
        assert info['bytes'] == row['bytes']
        verified.append({'path': row['path'], 'gitBlob': row['object'], **info})
    assert sum(row['bytes'] for row in verified) == source_input['selectedTrackedBytes'] <= 128 * 1024**2
    (out / 'verified-original-tracked-source.json').write_text(json.dumps({
        'sourceCommit': SOURCE, 'sourceTree': source_input['sourceTree'],
        'shallowBoundary': SOURCE, 'syntheticCommits': False, 'actualObjectSetMatches': True,
        'excludedHistoricalBenchmarkData': source_input['excludedHistoricalBenchmarkData'],
        'scope': 'compiler source only; no benchmark or runtime CI claim', 'files': verified}, indent=2) + '\n')
    record['privateOriginalSource'] = {'sourceTree': source_input['sourceTree'],
        'shallowBoundary': SOURCE, 'syntheticCommits': False, 'actualObjectSetMatches': True,
        'trackedBytes': source_input['selectedTrackedBytes'], 'originalGitMutated': False}
    save()
    run('ensurepip', [sys.executable, '-m', 'ensurepip', '--user'])
    run('python-requirements', [sys.executable, '-m', 'pip', 'install', '--user',
                              '--retries', '0', '-r', 'tools/requirements.lock'], source)
    os.chdir(source)
    sys.path.insert(0, str(source))
    sys.path.insert(0, str(private_home / '.local/lib/python3.13/site-packages'))
    run('original-producer-owned-material-extraction', [sys.executable, '-B', '/controller/extract-original-compiler-materials.py'], timeout=300)
    from tools.java_guest.compiler import tool_inventory as compiler_inventory
    from tools.java_http_composition.build import compile_pair
    from tools.java_http_composition.native_inputs import compiler as verify_compiler
    roots = {name: work / 'managed' / name for name in ('jdk', 'gradle', 'wasi-sdk')}
    original = compiler_inventory(roots)
    assert len(original) == 2902802 and hashlib.sha256(original).hexdigest() == '46190f6e208fc5a0046522f2783adcc0752a7bc762db7a8b507e198fd064883b'
    (out / 'original-compiler-inputs.json').write_bytes(original)
    handoff = json.loads((out / 'original-compiler-material-owner-handoff.json').read_bytes())
    assert handoff['originalProducer'] == PRODUCER and handoff['originalBundleInstalledAsCurrentProfile'] is False
    tools = {'identity': handoff['originalGuestToolInventory']}
    descriptor = {'hostAbi': handoff['originalHostAbi']}
    os.environ['JAVA_HOME'] = str(roots['jdk'])
    os.environ['PATH'] = ':'.join([str(roots['jdk'] / 'bin'), str(roots['gradle'] / 'bin'), str(work / 'bundle/sdk/bin'), os.environ['PATH']])
    helper_association = json.loads(Path('/controller/compiler-native-helper-association.json').read_bytes())
    for name, expected in helper_association['files'].items():
        assert identity(Path('/native-tools') / name) == expected
        target = work / name
        shutil.copyfile(Path('/native-tools') / name, target)
        target.chmod(0o700)
        assert identity(target) == expected
    record.update(compilerClosure={'bytes': len(original), 'sha256': 'sha256:' + hashlib.sha256(original).hexdigest()},
        compilerNativeHelpers=helper_association, guestToolInventoryDigest=tools['identity'],
        bundleHostAbi=descriptor['hostAbi'], originalPerBuildDeadlineSeconds=900)
    save()
    runtime = source / 'sdk/java-guest/runtime/dev/latent/guest'
    classes = work / 'ownership-classes'
    classes.mkdir(mode=0o700)
    # The exact original maintained qualification command, including its fixed closure.
    run('reviewed-sdk-ownership-compile', [str(roots['jdk'] / 'bin/javac'), '-d', str(classes),
        str(source / 'sdk/java-guest/tests/Ownership.java'),
        str(source / 'sdk/java-guest/tests/ResponseValidation.java'),
        *[str(runtime / (name + '.java')) for name in
          ('Handle', 'SensitiveBytes', 'Unsigned64', 'BufferedWebResponseValidator')]], timeout=180)
    run('reviewed-sdk-ownership-state-machines', [str(roots['jdk'] / 'bin/java'),
        '-cp', str(classes), 'dev.latent.guest.Ownership'], timeout=180)
    record['originalOwnershipAndResponseValidationJvmCasesPassed'] = True
    save()
    capture = work / 'composition'
    capture.mkdir(mode=0o700)
    print('Authenticated fresh source and compiler tools; compiling domain, context-required, adapter, adapter-next', flush=True)
    selected = compile_pair(capture, roots['wasi-sdk'],
                            {'examples/capsule_contracts': work / 'capsule_contracts', 'examples/package': work / 'package'}, diagnostics=True)
    assert set(selected) == {'domain', 'context-required', 'adapter', 'adapter-next'}
    assert compiler_inventory(roots) == original
    for name in ('domain', 'context-required', 'adapter', 'adapter-next'):
        completed = json.loads((capture / 'builds' / name / 'BUILD-COMPLETE.json').read_bytes())
        assert completed['packageAssembled'] is True
        assert len(completed['commands']) == 26 and all(row['exitCode'] == 0 for row in completed['commands'])
        observation = json.loads((capture / 'builds' / name / 'build-observation.json').read_bytes())
        material = next(row for row in observation['materials'] if row['name'] == 'packager')
        assert material == {'name': 'packager', 'digest': helper_association['files']['package']['sha256'],
                            'size': helper_association['files']['package']['bytes']}
    observed = verify_compiler(capture / 'builds')
    assert observed['sourceObserved'] is True and observed['hermetic'] is False
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=source)
    record.update(compiled=True, originalSourceUnchanged=True, compiledInputs=observed)
    save()
    export_capture(capture)
except BaseException as error:
    record['failedReason'] = str(error)
    record['failedException'] = type(error).__name__
    try:
        for name in ('memory.events', 'memory.peak'):
            path = Path('/sys/fs/cgroup') / name
            if path.is_file():
                raw = path.read_bytes()
                assert len(raw) <= 4096
                (out / ('failure-cgroup-' + name + '.txt')).write_bytes(raw)
        failed_capture = work / 'composition'
        if failed_capture.is_dir():
            export_capture(failed_capture)
            record['failedAttemptCaptureExported'] = True
    except BaseException as export_error:
        record['failureExportError'] = str(export_error)
    raise
finally:
    save()
print(json.dumps(record), flush=True)
