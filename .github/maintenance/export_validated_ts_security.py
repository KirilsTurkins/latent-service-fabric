#!/usr/bin/env python3
"""Recover the scanned tree and export objects; never move any branch ref."""
from __future__ import annotations
import base64
import time

# Reuse the already reviewed bounded Git/artifact/JSON helpers, not its driver.
from pathlib import Path
helper = Path('.github/maintenance/finish_ts_security.py').read_text()
marker = "if sys.argv[1]=='prepare':\n"
assert helper.count(marker) == 1
exec(compile(helper.split(marker, 1)[0], 'security_export_helpers.py', 'exec'))

ARTIFACT = 14108124796
ARTIFACT_SHA = '0b0e2ef4ed7499f9e481f3254f92609c768d367700f0bcd3aeed49605860ed4e'
SCANNED_REVISION = '6540c0b5acb7b4c25633a04590485b9c1305b731'
known_blobs = set()
last_write = 0.0


def git_api(kind, value):
    global last_write
    # Stay below secondary write-rate limits, including small blob uploads.
    time.sleep(max(0.0, 0.45 - (time.monotonic() - last_write)))
    last_write = time.monotonic()
    result = subprocess.run(
        ['gh', 'api', '--method', 'POST', REPO + '/git/' + kind, '--input', '-'],
        input=json.dumps(value).encode(), stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, timeout=120)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace'))
    return json.loads(result.stdout)


def upload_blob(data, expected):
    if expected in known_blobs:
        return
    assert hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() == expected
    response = git_api('blobs', {'content': base64.b64encode(data).decode(), 'encoding': 'base64'})
    assert response['sha'] == expected
    known_blobs.add(expected)


def export_candidate(cwd, number, baseline):
    branch, expected_head = HEADS[number]
    base_tree = run(['git', 'rev-parse', baseline + '^{tree}'], cwd=cwd, capture=True)
    expected_tree = run(['git', 'rev-parse', 'HEAD^{tree}'], cwd=cwd, capture=True)
    assert not run(['git', 'status', '--porcelain', '--untracked-files=normal'], cwd=cwd, capture=True)
    names = run(['git', 'diff', '--no-renames', '--name-only', baseline, 'HEAD'], cwd=cwd, capture=True).splitlines()
    rows = []
    payloads = {}
    for name in names:
        record = run(['git', 'ls-tree', 'HEAD', '--', name], cwd=cwd, capture=True)
        if not record:
            rows.append({'path': name, 'mode': '100644', 'type': 'blob', 'sha': None})
            continue
        mode, kind, sha = record.split()[:3]
        assert kind == 'blob'
        data = raw(['git', 'show', 'HEAD:' + name], cwd)
        assert hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() == sha
        rows.append({'path': name, 'mode': mode, 'type': 'blob', 'sha': sha})
        payloads[sha] = data
    if number == 1852:
        # The runner may write ordinary content. Workflow-path tree writes are
        # deliberately left to the separately authorized connected account.
        ordinary = [row for row in rows if not row['path'].startswith('.github/workflows/')]
        content_rows = []
        for row in ordinary:
            item = dict(row)
            if item['sha'] is not None:
                item['content'] = payloads[item.pop('sha')].decode('utf-8')
            content_rows.append(item)
        try:
            result = git_api('trees', {'base_tree': base_tree, 'tree': content_rows})
        except RuntimeError as error:
            if 'HTTP 403' not in str(error):
                raise
            print('Runner tree write refused; export all blobs for connected-account tree creation.', flush=True)
        else:
            base_tree = result['sha']
            known_blobs.update(row['sha'] for row in ordinary if row['sha'] is not None)
            rows = [row for row in rows if row['path'].startswith('.github/workflows/')]
    for index, row in enumerate(rows, 1):
        if row['sha'] is not None:
            upload_blob(payloads[row['sha']], row['sha'])
        if index % 25 == 0:
            print(number, 'authenticated objects', index, '/', len(rows), flush=True)
    result = {
        'pr': number, 'branch': branch, 'expectedHead': expected_head,
        'tree': expected_tree, 'baseTree': base_tree, 'treeElements': rows,
        'testedLocalCommit': run(['git', 'rev-parse', 'HEAD'], cwd=cwd, capture=True),
        'additionalParentPr': None if number == 1852 else 1852,
        'validatedArtifact': {'id': ARTIFACT, 'sha256': ARTIFACT_SHA,
                              'sourceRevision': SCANNED_REVISION},
        'runtimeQualification': 'not claimed; Store regression is a separate required workflow step',
    }
    write_json(OUT / (str(number) + '-objects.json'), result)
    (OUT / (str(number) + '.patch')).write_bytes(raw(['git', 'diff', '--binary', expected_head, 'HEAD'], cwd))
    print('Exported candidate', number, expected_tree, len(rows), 'tree entries', flush=True)
    return result


for branch, expected in HEADS.values():
    current = run(['git', 'ls-remote', '--heads', 'origin', 'refs/heads/' + branch], cwd=ROOT, capture=True)
    assert current.split()[0] == expected, (branch, current)
    run(['git', 'fetch', '--no-tags', 'origin', expected], cwd=ROOT)
value = artifact(ARTIFACT, ARTIFACT_SHA)
assert value['security-integrated.status.txt'] == b''
for name in ('rustsec', 'dependencies', 'secrets', 'static'):
    scan = json.loads(value['parent-' + name + '.log'])
    assert scan['status'] == 'pass' and scan['finding_count'] == 0
    assert scan['source_revision'] == scan['control_revision'] == SCANNED_REVISION
    assert scan['source_worktree_clean'] and scan['control_worktree_clean']
    if name != 'secrets':
        assert scan['exception_count'] == 0
    (OUT / ('validated-parent-' + name + '.json')).write_bytes(value['parent-' + name + '.log'])
run(['git', 'worktree', 'add', '--detach', str(WORK), BASE], cwd=ROOT)
patch = TMP / 'validated-security.patch'
patch.write_bytes(value['security-integrated.patch'])
run(['git', 'apply', '--index', '--whitespace=error-all', str(patch)])
assert raw(['git', 'diff', '--cached', '--binary', BASE]) == patch.read_bytes(), 'reconstructed patch differs'
for name, expected in scan['policy_sha256'].items():
    assert digest((WORK / '.github/security' / name).read_bytes()) == expected, name
parent_local = commit('fix(security): recover the exact fully scanned runtime and action repair')
write_json(OUT / 'reconstruction.json', {
    'artifact': ARTIFACT, 'artifactSha256': ARTIFACT_SHA,
    'patchSha256': digest(patch.read_bytes()), 'scannedSourceRevision': SCANNED_REVISION,
    'reconstructedTree': run(['git', 'rev-parse', 'HEAD^{tree}'], capture=True),
    'patchByteIdentical': True, 'allFourScansPassed': True})
parent = export_candidate(WORK, 1852, BASE)

for number in (1931, 1934):
    branch, expected = HEADS[number]
    child = TMP / ('security-' + str(number))
    run(['git', 'worktree', 'add', '--detach', str(child), expected], cwd=ROOT)
    merged = run(['git', 'merge', '--no-ff', '--no-commit', parent_local], cwd=child, check=False)
    assert merged.returncode == 0 or merged.returncode == 1 and conflicts(child), 'merge did not complete'
    if number == 1931:
        path = 'crates/vendor/wasmtime/latent-dynamic-memory.patch'
        if path in conflicts(child):
            def pieces(data):
                sections = re.split(r'(?m)(?=^--- a/)', data.decode())
                assert sections[0] == ''
                return {section.splitlines()[0][6:]: section for section in sections[1:]}
            versions = [pieces(raw(['git', 'show', f':{i}:{path}'], child)) for i in (1, 2, 3)]
            (child / path).write_text(''.join(merge_json(*versions).values()))
            run(['git', 'add', path], cwd=child)
        for path in conflicts(child):
            if path.endswith('.json'):
                resolve_json(child, path)
            elif path == 'tools/host_codec_wasmtime.py':
                (child / path).write_bytes(raw(['git', 'show', expected + ':' + path], child))
                run(['git', 'add', path], cwd=child)
            else:
                raise AssertionError('Unreviewed ownership conflict: ' + path)
        path = child / 'tools/host_codec_wasmtime.py'
        text = path.read_text()
        node = next(n for n in ast.parse(text).body if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == 'RECORD_SHA256' for t in n.targets))
        previous = ast.literal_eval(node.value)
        assert text.count(previous) == 1
        text = text.replace(previous, digest((child / 'crates/vendor/wasmtime/UPSTREAM.latent.json').read_bytes()))
        node = next(n for n in ast.parse(text).body if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == 'POSTIMAGES' for t in n.targets))
        postimages = ast.literal_eval(node.value)
        for name in ('Cargo.lock', 'latent-dynamic-memory.patch'):
            postimages[name] = identity(child / 'crates/vendor/wasmtime' / name)
        lines = text.splitlines(True)
        lines[node.lineno - 1:node.end_lineno] = ['POSTIMAGES = ' + pprint.pformat(postimages, width=110, sort_dicts=False) + '\n']
        path.write_text(''.join(lines))
        run(['git', 'add', str(path)], cwd=child)
    assert not conflicts(child), (number, conflicts(child))
    commit('merge: preserve TypeScript ownership fixes with the scanned security repair', cwd=child)
    log_test(str(number) + '-source', ['python3', '-m', 'unittest', 'tools.tests.test_host_codec_wasmtime', '-v'], cwd=child)
    if number == 1934:
        log_test('1934-native', ['python3', '-m', 'unittest', 'tools.tests.test_typescript_event_ownership',
                               'tools.tests.test_typescript_abort_any_ownership',
                               'tools.tests.test_typescript_record_retirement', '-v'], cwd=child)
    export_candidate(child, number, parent_local)
