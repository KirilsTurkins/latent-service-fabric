"""Assemble an unpublished PR 703 candidate from exact reviewed revisions."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

BASE = '711c5773eab56487270b95d395bb6e4879394ea7'
HEAD = 'aaa4191436ef07e5a8739f411f63a1a85f99701f'
SECURITY = '7aa1ae07c7ceed1c6ab32b6cdeb5b46ba31f750e'
OUT = Path(os.environ['RUNNER_TEMP']) / '703-evidence'
OUT.mkdir(exist_ok=True)

def git(*args, check=True):
    return subprocess.run(['git', *args], check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

def refresh_native():
    path = Path('.github/security/inventory.json')
    text = path.read_text()
    row = next(row for row in json.loads(text)['manifests'] if row['path'] == 'tools/native-fixture/Cargo.toml')
    sha = hashlib.sha256(Path(row['path']).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
    assert text.count(row['manifest_sha256']) == 1
    path.write_text(text.replace(row['manifest_sha256'], sha))
    git('add', str(path))

git('config', 'user.name', 'LSF CI validation')
git('config', 'user.email', 'lsf-ci@users.noreply.github.com')
git('checkout', '--detach', HEAD)
result = git('merge', '--no-commit', '--no-ff', BASE, check=False)
print(result.stdout)
if result.returncode:
    assert git('diff', '--name-only', '--diff-filter=U').stdout.strip() == '.github/security/inventory.json'
    git('checkout', '--theirs', '.github/security/inventory.json')
refresh_native()
git('commit', '-m', 'Merge development into PR 703 preserving serde_json 1.0.151')
result = git('cherry-pick', '--no-commit', SECURITY, check=False)
print(result.stdout)
# Development has replaced the release-only post-install patcher with an
# authenticated, pre-execution derived archive. Keep that architecture intact.
changed = git('diff', '--name-only', SECURITY + '^', SECURITY).stdout.splitlines()
restored = [p for p in changed if p.startswith('website/') or p in {
    '.github/workflows/ci.yml', '.github/workflows/docs-pages.yml', '.github/workflows/docs-site.yml',
    'docs/development/website.md', 'docs/development/website-versions.md',
    'docs/development/workflow-action-pins.md', 'tools/ci/commands.json'}]
for name in restored:
    if name == 'tools/ci/commands.json':
        name = 'tools/ci/history/commands-v1.json'
    existed = git('cat-file', '-e', 'HEAD:' + name, check=False).returncode == 0
    if existed:
        git('restore', '--source=HEAD', '--staged', '--worktree', '--', name)
    else:
        git('rm', '-f', '--ignore-unmatch', '--', name)
# Keep every unrelated updated inventory entry; only the actual native manifest
# digest is reconciled after the Rust minimum changes.
name = '.github/security/inventory.json'
text = Path(name).read_text()
import re
text = re.sub(r'^<<<<<<< .*\n(.*?)^=======\n.*?^>>>>>>> .*\n', r'\1', text, flags=re.M | re.S)
assert '<<<<<<<' not in text
Path(name).write_text(text)
refresh_native()
workflow = Path('.github/workflows/ci.yml')
text = workflow.read_text()
assert 'rustup toolchain install 1.94.1 --profile minimal --no-self-update' in text
text = text.replace('rustup toolchain install 1.94.1 --profile minimal --no-self-update',
                    'rustup toolchain install 1.95.0 --profile minimal --no-self-update')
text = text.replace('Rust MSRV 1.94.1', 'Rust MSRV 1.95.0')
workflow.write_text(text)
git('add', str(workflow))
conflicts = git('diff', '--name-only', '--diff-filter=U').stdout
if conflicts:
    (OUT / 'conflicts.txt').write_text(conflicts)
    (OUT / 'conflicts.diff').write_text(git('diff', '--cc').stdout)
    print(conflicts)
    raise SystemExit(1)
# Preserve the historical CI snapshot byte-for-byte. Current obligations will
# be extended in ownership-local fragments after source review.
assert git('diff', 'HEAD', '--', 'tools/ci/history/commands-v1.json').stdout == ''
print(git('diff', '--stat', BASE).stdout)
git('commit', '-m', 'Port Wasmtime 48.0.3 security fixes while preserving development tooling')
(OUT / 'candidate.diff').write_text(git('diff', '--binary', BASE).stdout)
(OUT / 'candidate-tree.txt').write_text(git('ls-tree', '-r', 'HEAD').stdout)
with (OUT / 'source.tar.gz').open('wb') as archive:
    subprocess.run(['git', 'archive', '--format=tar.gz', 'HEAD'], check=True, stdout=archive)
print('CANDIDATE', git('rev-parse', 'HEAD').stdout.strip())
print('ARCHIVE_BYTES', (OUT / 'source.tar.gz').stat().st_size)
