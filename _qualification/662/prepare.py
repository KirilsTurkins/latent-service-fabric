"""Temporary exact-source qualification transport; creates blobs, never refs."""
from __future__ import annotations
import base64
import hashlib
import json
import lzma
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import urllib.request

ROOT = Path.cwd()
OUT = ROOT / 'target/publication-workbench'
PAYLOAD_HASH = '7340208ad276bdbbecc1fbd1349812afcbdc82713321b18ae75a8b2c053fda30'
BASE = '6f0e17cce2c7edeae10a65f06dd1db20d215c72a'
REPOSITORY = 'KirilsTurkins/latent-service-fabric'


def git(*args: str) -> str:
    return subprocess.check_output(['git', *args], text=True, timeout=30).strip()


def blob(data: bytes) -> str:
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def apply() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    parts = []
    for n in range(6):
        data = (ROOT / f'_qualification/662/part{n}.b64').read_bytes()
        assert len(data) <= 6001
        parts.append(data.strip())
    packed = base64.b64decode(b''.join(parts), validate=True)
    assert hashlib.sha256(packed).hexdigest() == PAYLOAD_HASH
    decoder = lzma.LZMADecompressor(memlimit=128 * 1024 * 1024)
    raw = decoder.decompress(packed, max_length=1024 * 1024)
    assert decoder.eof and not decoder.unused_data
    payload = json.loads(raw)
    assert set(payload) == {'base', 'patchSha256', 'files', 'patch'}
    assert payload['base'] == BASE
    subprocess.run(['git', 'merge-base', '--is-ancestor', BASE, 'HEAD'], check=True, timeout=30)
    assert len(payload['files']) == 43
    names = [row['path'] for row in payload['files']]
    assert names == sorted(set(names))
    for row in payload['files']:
        name = row['path']
        assert set(row) == {'path', 'before', 'after', 'mode'} and row['mode'] == '100644'
        assert not name.startswith('/') and '..' not in Path(name).parts
        assert name.startswith(('crates/', 'apps/latentd/', 'tools/', 'docs/reference/')) or name == '.github/workflows/ci.yml'
        path = ROOT / name
        assert not path.is_symlink()
        if row['before'] is None:
            assert not path.exists()
        else:
            assert git('rev-parse', f'HEAD:{name}') == row['before']
            assert blob(path.read_bytes()) == row['before']
    patch = payload.pop('patch').encode()
    assert hashlib.sha256(patch).hexdigest() == payload['patchSha256']
    patch_path = OUT / 'reviewed.patch'
    patch_path.write_bytes(patch)
    subprocess.run(['git', 'apply', '--check', str(patch_path)], check=True, timeout=30)
    subprocess.run(['git', 'apply', str(patch_path)], check=True, timeout=30)
    for row in payload['files']:
        assert blob((ROOT / row['path']).read_bytes()) == row['after'], row['path']
    additions = [row['path'] for row in payload['files'] if row['before'] is None]
    subprocess.run(['git', 'add', '--intent-to-add', '--', *additions], check=True, timeout=30)
    assert git('diff', '--name-only').splitlines() == names
    (OUT / 'source-commit.txt').write_text(git('rev-parse', 'HEAD') + '\n')
    (OUT / 'manifest.json').write_text(json.dumps(payload, indent=2) + '\n')
    with tarfile.open(OUT / 'reviewed-source.tar.gz', 'w:gz') as archive:
        for row in payload['files']:
            archive.add(ROOT / row['path'], arcname=row['path'], recursive=False)
    print(f'Verified {len(names)} exact source blobs; patch {payload["patchSha256"]}')


def publish() -> None:
    payload = json.loads((OUT / 'manifest.json').read_text())
    token = os.environ['GH_TOKEN']
    entries = []
    for row in payload['files']:
        data = (ROOT / row['path']).read_bytes()
        assert len(data) < 1024 * 1024 and blob(data) == row['after'], row['path']
        # Only content-addressed blobs are written; no branch or other ref update.
        request = urllib.request.Request(
            f'https://api.github.com/repos/{REPOSITORY}/git/blobs',
            data=json.dumps({'content': base64.b64encode(data).decode(), 'encoding': 'base64'}).encode(),
            headers={'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json',
                     'Content-Type': 'application/json', 'X-GitHub-Api-Version': '2022-11-28'},
            method='POST',
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
        assert result['sha'] == row['after'], row['path']
        entries.append({'path': row['path'], 'mode': row['mode'], 'type': 'blob', 'sha': result['sha']})
    (OUT / 'tree-entries.json').write_text(json.dumps(entries, indent=2) + '\n')
    print(f'Uploaded {len(entries)} verified blobs without updating a ref')


if __name__ == '__main__':
    assert len(sys.argv) == 2 and sys.argv[1] in {'apply', 'publish'}
    {'apply': apply, 'publish': publish}[sys.argv[1]]()
