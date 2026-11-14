#!/usr/bin/env python3
"""Replay two reviewed security-only deltas; export objects, never update refs."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

BASE = 'fa3c219ef8c202a00ef0c88968835ac727e8a075'
PARENT = '68bd53e20eeeae109f7816c8e81a1f959158a93b'
SECURITY = '9e633f701982ce3345e7ebba0519d48f624f4afd'
SELECTORS = '006a58adde2b4c5ed6a750d0c8e0775a3cbcb380'
REPO = 'KirilsTurkins/latent-service-fabric'
ROOT = Path(os.environ['GITHUB_WORKSPACE'])
TEMP = Path(os.environ['RUNNER_TEMP'])
WORK = TEMP / 'pr2026-security-work'
OUT = TEMP / 'pr2026-security-evidence'
OUT.mkdir(exist_ok=True)


def run(args, *, cwd=WORK, timeout=180, check=True):
    return subprocess.run(args, cwd=cwd, check=check, timeout=timeout,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def text(args, *, cwd=WORK):
    return run(args, cwd=cwd).stdout.decode().strip()


def save(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2) + '\n')


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'gitBlob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def changes(before, after):
    return set(text(['git', 'diff', '--name-only', before, after]).splitlines())


def logged(name, args, *, timeout=600):
    # Only the selected public source and source-free scanner diagnostics enter
    # these logs. Never serialize the process environment or authentication.
    with (OUT / name).open('wb') as output:
        result = subprocess.run(args, cwd=WORK, stdout=output, stderr=subprocess.STDOUT,
                                timeout=timeout, check=False)
    print(f'{name}: exit {result.returncode}', flush=True)
    if result.returncode:
        raise SystemExit(result.returncode)


def derive():
    assert os.environ['GITHUB_REPOSITORY'] == REPO
    run(['git', 'fetch', '--no-tags', '--depth=1', 'origin', BASE, PARENT, SECURITY, SELECTORS],
        cwd=ROOT, timeout=240)
    run(['git', 'worktree', 'add', '--detach', str(WORK), BASE], cwd=ROOT)
    # These workflows belong only to the donor's TypeScript feature branch.
    # They are absent on the PR head; do not introduce them just to update pins.
    excluded = ('.github/workflows/typescript-network-boundary.yml',
                '.github/workflows/typescript-runtime-controls.yml')
    for path in excluded:
        assert run(['git', 'cat-file', '-e', BASE + ':' + path], check=False).returncode != 0
    allowed = set()
    for old, new in [(PARENT, SECURITY), (SECURITY, SELECTORS)]:
        assert ('parent ' + old) in text(['git', 'cat-file', '-p', new]).splitlines()
        allowed.update(changes(old, new))
        patch = run(['git', 'diff', '--binary', '--full-index', old, new]).stdout
        assert len(patch) < 8 * 1024 * 1024
        patch_path = OUT / (new[:8] + '.patch')
        patch_path.write_bytes(patch)
        applied = run(['git', 'apply', '--3way', '--index',
                       *('--exclude=' + path for path in excluded), str(patch_path)], check=False)
        (OUT / (new[:8] + '-apply.log')).write_bytes(applied.stdout + applied.stderr)
        if applied.returncode:
            (OUT / 'conflicts.txt').write_bytes(run(['git', 'ls-files', '--unmerged']).stdout)
            (OUT / 'status.txt').write_bytes(run(['git', 'status', '--porcelain=v1']).stdout)
            (OUT / 'conflict-diff.txt').write_bytes(run(['git', 'diff', '--cc']).stdout)
            raise SystemExit('Security replay has conflicts; no automatic resolution or publication')
    paths = text(['git', 'diff', '--cached', '--name-only', BASE]).splitlines()
    assert paths and set(paths) <= allowed
    assert not any(path.startswith('.github/maintenance/') for path in paths)
    # Preserve every byte of the branch-specific repair, except the standalone
    # lock if one of these independently reviewed deltas also touches it.
    protected = ['tools/ci_suite_discovery.py', 'tools/tests/test_ci_suite_discovery.py',
                 'crates/latent-wasmtime/tests/local_service/zero_clock.rs',
                 'tools/tests/test_rust_standard_thread_profile.py',
                 'sdk/rust-standard-runtime/stack-transform/Cargo.lock']
    for path in protected:
        assert run(['git', 'show', BASE + ':' + path]).stdout == (WORK / path).read_bytes(), path
    # The only exceptions are exact reviewed non-secret findings. Each retained
    # source identity must still match this branch, not just the source branch.
    for name, key in [('security-false-positive-review-2026-11-14.json', 'unchangedSourceFiles'),
                      ('security-source-identity-review-2026-11-14.json', 'sourceIdentities')]:
        record = json.loads((WORK / 'docs/evidence' / name).read_text())
        for path, expected in record[key].items():
            actual = identity((WORK / path).read_bytes())
            assert all(actual[field] == expected[field] for field in ('bytes', 'sha256')), path
    exceptions = json.loads((WORK / '.github/security/exceptions.json').read_text())['exceptions']
    assert all(row['scanner'] == 'gitleaks' for row in exceptions)
    run(['git', 'diff', '--cached', '--check'])
    run(['git', '-c', 'user.name=github-actions[bot]',
         '-c', 'user.email=41898282+github-actions[bot]@users.noreply.github.com',
         'commit', '-m', 'fix(security): replay verified dependency repairs on PR 2026'])
    assert not text(['git', 'status', '--porcelain=v1', '--untracked-files=normal'])
    candidate = text(['git', 'rev-parse', 'HEAD'])
    tree = text(['git', 'rev-parse', 'HEAD^{tree}'])
    save('candidate.json', {'base': BASE, 'sourceCommits': [SECURITY, SELECTORS],
                           'localCommit': candidate, 'tree': tree, 'paths': paths, 'excludedAbsentWorkflows': excluded,
                           'run': int(os.environ['GITHUB_RUN_ID'])})
    run(['git', 'archive', '--format=tar.gz', '-o', str(OUT / 'changed-files.tar.gz'), 'HEAD', *paths])
    (OUT / 'candidate.patch').write_bytes(run(['git', 'diff', '--binary', '--full-index', BASE, 'HEAD']).stdout)


def validate():
    logged('python-dependencies.log', [sys.executable, '-m', 'pip', 'install', '--requirement', 'tools/requirements.lock'])
    logged('security-controls.log', [sys.executable, '-B', '-m', 'unittest', 'discover', '-s', 'tools/tests', '-p', 'test_security*.py'])
    logged('focused-controls.log', [sys.executable, '-B', '-m', 'unittest',
        'tools.tests.test_ci_suite_discovery', 'tools.tests.test_go_zero_clock',
        'tools.tests.test_rust_standard_thread_profile', 'tools.tests.test_host_codec_wasmtime',
        'tools.tests.test_native_loader_boundary', 'tools.tests.test_rust_scratch_replay',
        'tools.tests.test_java_scratch_wiring', 'tools.tests.test_go_smtp_tls_runtime'])
    logged('ci-contracts.log', [sys.executable, '-B', 'tools/ci_coverage.py', '--receipt', str(OUT / 'observed-inventory.json')])
    for tool in ('cargo-audit', 'gitleaks', 'zizmor'):
        logged('install-' + tool + '.log', [sys.executable, '-B', 'tools/security_install.py',
               '--tool', tool, '--destination', str(TEMP / 'security-tools')])
    for mode in ('rustsec', 'dependencies', 'secrets', 'static'):
        logged('security-' + mode + '.json', [sys.executable, '-B', 'tools/security_scan.py', mode,
               '--repo', str(WORK), '--tools', str(TEMP / 'security-tools'),
               '--scratch', str(TEMP / ('pr2026-scan-' + mode))], timeout=900)
    logged('security-canaries.json', [sys.executable, '-B', 'tools/security_selftest.py',
           '--tools', str(TEMP / 'security-tools'), '--scratch', str(TEMP / 'pr2026-canaries')], timeout=900)
    assert not text(['git', 'status', '--porcelain=v1', '--untracked-files=normal'])
    save('validation.json', {'status': 'passed', 'tree': text(['git', 'rev-parse', 'HEAD^{tree}']),
                            'scope': 'Source, contract, dependency, secret and scanner controls; not signed runtime qualification.'})


def publish_objects():
    candidate = json.loads((OUT / 'candidate.json').read_text())
    validation = json.loads((OUT / 'validation.json').read_text())
    assert candidate['base'] == BASE and validation['status'] == 'passed'
    assert candidate['tree'] == validation['tree'] == text(['git', 'rev-parse', 'HEAD^{tree}'])
    assert not text(['git', 'status', '--porcelain=v1', '--untracked-files=normal'])
    def api(endpoint, payload):
        # Request bytes are outside the artifact directory; no token or
        # environment is written. This deliberately never calls a refs API.
        request = TEMP / 'pr2026-git-object-request.json'
        request.write_text(json.dumps(payload))
        try:
            return json.loads(run(['gh', 'api', '--method', 'POST',
                                  f'repos/{REPO}/git/{endpoint}', '--input', str(request)]).stdout)
        finally:
            request.unlink(missing_ok=True)
    entries = []
    files = {}
    total = 0
    existing = set()
    for ref in (BASE, SECURITY, SELECTORS):
        for row in text(['git', 'ls-tree', '-r', ref]).splitlines():
            fields = row.split('\t', 1)[0].split()
            if fields[1] == 'blob':
                existing.add(fields[2])
    for path in candidate['paths']:
        target = WORK / path
        assert target.is_file() and not target.is_symlink(), path
        raw = target.read_bytes()
        total += len(raw)
        assert len(raw) <= 8 * 1024 * 1024 and total <= 32 * 1024 * 1024
        expected = identity(raw)
        sha = expected['gitBlob']
        if sha not in existing:
            sha = api('blobs', {'encoding': 'base64', 'content': base64.b64encode(raw).decode()})['sha']
        assert sha == expected['gitBlob']
        mode = text(['git', 'ls-files', '--stage', '--', path]).split()[0]
        entries.append({'path': path, 'mode': mode, 'type': 'blob', 'sha': sha})
        files[path] = expected
    tree = api('trees', {'base_tree': text(['git', 'rev-parse', BASE + '^{tree}']), 'tree': entries})['sha']
    assert tree == candidate['tree']
    save('published-objects.json', {'base': BASE, 'tree': tree, 'entries': entries, 'files': files,
                                   'run': int(os.environ['GITHUB_RUN_ID']), 'branchUpdated': False})
    print(json.dumps({'base': BASE, 'tree': tree, 'files': len(files), 'branchUpdated': False}))


if __name__ == '__main__':
    {'derive': derive, 'validate': validate, 'publish': publish_objects}[sys.argv[1]]()
