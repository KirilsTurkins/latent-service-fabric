"""Temporary exact-tree transport; never included in the PR source tree."""
import base64
import hashlib
import json
import lzma
import os
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.request

TREE = '3b8a117aa71094f07202b3313900d947ce2c6f32'
BASE = '711c5773eab56487270b95d395bb6e4879394ea7'
ROOT = Path(__file__).resolve().parent

def git(*args):
    return subprocess.check_output(['git', *args])

def assemble():
    raw = lzma.decompress(base64.b64decode((ROOT / 'pr703-replay.b64').read_text().strip(), validate=True))
    assert len(raw) == 38736
    assert hashlib.sha256(raw).hexdigest() == '6afcbaca36c23604eeddcef540a8ebe1ec12a6ae885c11ebdea639964492f064'
    data = json.loads(raw)
    assert data['b'] == BASE and data['t'] == TREE and len(data['f']) == 85
    assert git('rev-parse', 'HEAD').decode().strip() == BASE
    elements, paths, new = [], set(), []
    for name, mode, source, edits in data['f']:
        path = Path(name)
        assert not path.is_absolute() and not {'..', '.git'} & set(path.parts) and name not in paths
        assert mode in {'100644', '100755'}
        assert not any(p.is_symlink() for p in [path, *path.parents])
        paths.add(name)
        lines = git('cat-file', 'blob', source).decode().splitlines(keepends=True) if source else []
        for start, end, replacement in reversed(edits):
            assert 0 <= start <= end <= len(lines)
            lines[start:end] = replacement.splitlines(keepends=True)
        content = ''.join(lines)
        raw = content.encode()
        sha = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        path.chmod(0o755 if mode == '100755' else 0o644)
        elements.append({'path': name, 'mode': mode, 'type': 'blob', 'sha': sha})
        if sha != source:
            new.append({'sha': sha, 'content': content})
    subprocess.run(['git', 'add', '--', *sorted(paths)], check=True)
    subprocess.run(['git', 'diff', '--cached', '--check'], check=True)
    assert git('write-tree').decode().strip() == TREE
    request = {'tree': TREE, 'base_tree': git('rev-parse', 'HEAD^{tree}').decode().strip(), 'elements': elements, 'blobs': new}
    Path(os.environ['RUNNER_TEMP'], 'candidate-objects.json').write_text(json.dumps(request))
    print('Verified complete tree:', TREE, 'new blobs:', len(new))

def store_blobs():
    data = json.loads(Path(os.environ['RUNNER_TEMP'], 'candidate-objects.json').read_text())
    assert data['tree'] == TREE and len(data['elements']) == 85 and len(data['blobs']) <= 40
    # Blobs have no path and update no ref. Workflow/tree authorization is left
    # to the separately authorized connector; this token never updates a branch.
    for blob in data['blobs']:
        payload = json.dumps({'content': blob['content'], 'encoding': 'utf-8'}).encode()
        req = urllib.request.Request('https://api.github.com/repos/KirilsTurkins/latent-service-fabric/git/blobs', data=payload, method='POST', headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'], 'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json', 'X-GitHub-Api-Version': '2022-11-28'})
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                result = json.load(response)
        except urllib.error.HTTPError as error:
            print(error.code, error.read(2048).decode())
            raise
        assert result['sha'] == blob['sha']
        print('Stored blob:', result['sha'])
    print('Verified source blobs stored; no branch or workflow was updated.')

if __name__ == '__main__':
    if sys.argv[1:] == ['--store-blobs']:
        store_blobs()
    elif not sys.argv[1:]:
        assemble()
    else:
        raise SystemExit('unexpected arguments')
