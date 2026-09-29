"""Reconcile the tested PR fix with the observed development head; export objects only."""
from __future__ import annotations
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

ROOT = Path(sys.argv[2]).resolve()
sys.path.insert(0, str(ROOT))
HEAD = '1a994134e870071f7bdf10f647bd9b46f29b58b8'
BASE = 'a991d11acb98ebc17cc47d879f5237ac4618bcc9'
COMMON = '10dc4c35fea30a4b67afc1e111054f75167b6166'
REPO = 'KirilsTurkins/latent-service-fabric'


def git(*args, text=True):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=text)


def merge():
    assert git('rev-parse', 'HEAD').strip() == HEAD
    assert git('merge-base', HEAD, BASE).strip() == COMMON
    result = subprocess.run(['git', '-c', 'user.name=LSF repair qualification', '-c',
                             'user.email=41898282+github-actions[bot]@users.noreply.github.com',
                             'merge', '--no-commit', '--no-ff', BASE], cwd=ROOT)
    conflicts = set(git('diff', '--name-only', '--diff-filter=U').splitlines())
    allowed = {'tools/ci/commands.json', '.github/workflows/ci.yml',
               'docs/development/workflow-action-pins.md', 'Cargo.lock',
               'crates/latent-wasmtime/Cargo.toml'}
    assert not (conflicts - allowed), ('unexpected merge conflict', conflicts)
    assert result.returncode == 0 or (result.returncode == 1 and conflicts)
    print('Observed conflicts:', sorted(conflicts), flush=True)
    # Retain all of development's newer action pins, adding only the tested MSRV change.
    for name in ('.github/workflows/ci.yml', 'docs/development/workflow-action-pins.md'):
        content = git('show', BASE + ':' + name)
        assert '1.94.1' in content
        assert '9376cdc5a5e25b16da71af47712785cf06b0d6d4' in content
        content = content.replace('1.94.1', '1.95.0').replace(
            '9376cdc5a5e25b16da71af47712785cf06b0d6d4', '46817827a5bfabe028bf34e1cce71fd40e2ff697')
        (ROOT / name).write_text(content)
    # The authoritative after-map starts at current development, not the older PR snapshot.
    name = 'tools/ci/commands.json'
    (ROOT / name).write_text(git('show', BASE + ':' + name))
    if 'Cargo.lock' in conflicts:
        (ROOT / 'Cargo.lock').write_text(git('show', HEAD + ':Cargo.lock'))
    if 'crates/latent-wasmtime/Cargo.toml' in conflicts:
        name = 'crates/latent-wasmtime/Cargo.toml'
        content = git('show', BASE + ':' + name)
        assert 'wit-parser = { version = "=0.252.0"' in content
        (ROOT / name).write_text(content.replace('wit-parser = { version = "=0.252.0"',
                                                'wit-parser = { version = "=0.259.0"'))
    for name in conflicts:
        git('add', '--', name)
    assert not git('diff', '--name-only', '--diff-filter=U').strip()


def inventory():
    from tools import ci_coverage as coverage
    path = ROOT / 'tools/ci/commands.json'
    data = json.loads(path.read_text())
    actual = coverage.commands(ROOT)
    assert actual == data['after'], 'the reconciliation must not change required commands'
    owners = coverage.delegated_owners(ROOT, actual)
    allowed = {'tools/build_s3_fixture.py', 'tools/build_dev_guest_tools.py', 'tools/ci_fast.py',
               'tools/phase3_security.py', 'tools/run_security_profile_workflow.py'}
    for name in set(owners) | set(data['delegatedOwners']):
        if owners.get(name) != data['delegatedOwners'].get(name):
            assert name in allowed, ('unexpected owner drift', name)
    data['delegatedOwners'] = owners
    cases = coverage.python_cases(ROOT)
    allowed_tests = {'tools/tests/test_s3_fixture_builder.py', 'tools/tests/test_dev_tools.py',
                     'tools/tests/test_native_loader_boundary.py'}
    for name in set(cases) | set(data['pythonCases']):
        if cases.get(name) != data['pythonCases'].get(name):
            assert name in allowed_tests, ('unexpected Python case drift', name)
    data['pythonCases'] = cases
    data['pythonTestModules'] = sorted(cases)
    data['workflowIdentities'] = coverage.workflow_identities(ROOT)
    path.write_text(json.dumps(data, indent=2) + '\n')
    coverage.validate(ROOT, path)
    # All runtime implementation bytes tested in the preceding job remain exact.
    tested = json.loads((Path(sys.argv[3]) / 'files.json').read_text())
    allowed_changes = {'Cargo.lock', 'tools/rust_capsule.lock', '.github/workflows/ci.yml',
                       'docs/development/workflow-action-pins.md', 'tools/ci/commands.json'}
    for name, expected in tested.items():
        if name not in allowed_changes:
            assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected, name
    print('Current development coverage preserved; tested runtime implementation unchanged.', flush=True)


def export():
    destination = Path(sys.argv[3]).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    git('add', '-A')
    git('diff', '--cached', '--check')
    allowed = set(git('diff', '--name-only', COMMON, HEAD).splitlines())
    changed = git('diff', '--cached', '--name-only', BASE).splitlines()
    assert changed and set(changed) <= allowed, ('unexpected scope', set(changed) - allowed)
    known = set()
    for revision in (HEAD, BASE):
        for line in git('ls-tree', '-r', revision).splitlines():
            meta, _ = line.split('\t', 1)
            mode, kind, sha = meta.split()
            if kind == 'blob':
                known.add(sha)
    index = {}
    for line in git('ls-files', '--stage').splitlines():
        meta, name = line.split('\t', 1)
        mode, sha, stage = meta.split()
        assert stage == '0'
        index[name] = (mode, sha)
    rows, hashes = [], {}
    for name in changed:
        mode, sha = index[name]
        path = ROOT / name
        assert mode in {'100644', '100755'} and path.is_file() and not path.is_symlink()
        raw = path.read_bytes()
        assert hashlib.sha1(f'blob {len(raw)}\0'.encode() + raw).hexdigest() == sha
        if sha not in known:
            # Upload only content-addressed file objects. No branch or workflow is
            # updated with the runner token; the authorized connector owns that write.
            body = json.dumps({'encoding': 'base64', 'content': base64.b64encode(raw).decode()}).encode()
            request = urllib.request.Request(f'https://api.github.com/repos/{REPO}/git/blobs',
                data=body, method='POST', headers={
                    'Accept': 'application/vnd.github+json',
                    'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
                    'Content-Type': 'application/json', 'User-Agent': 'lsf-pr700-qualification'})
            with urllib.request.urlopen(request, timeout=30) as response:
                observed = json.load(response)
            assert observed['sha'] == sha
            print('Uploaded content-addressed object:', name, sha, flush=True)
        rows.append({'path': name, 'mode': mode, 'type': 'blob', 'sha': sha})
        hashes[name] = hashlib.sha256(raw).hexdigest()
    evidence = {'baseTree': git('rev-parse', BASE + '^{tree}').strip(),
                'expectedTree': git('write-tree').strip(), 'parents': [HEAD, BASE],
                'treeElements': rows, 'files': hashes}
    (destination / 'git-elements.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps({'baseTree': evidence['baseTree'], 'expectedTree': evidence['expectedTree'],
                      'parents': evidence['parents'], 'changedFiles': len(rows)}), flush=True)


{'merge': merge, 'inventory': inventory, 'export': export}[sys.argv[1]]()
