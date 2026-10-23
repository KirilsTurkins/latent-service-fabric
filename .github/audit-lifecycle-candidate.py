"""Temporary exact-source formatter and immutable blob publisher; no ref writes."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

ROOT = 'crates/latent-audit/src/durable/store/lifecycle'
RUST = ['crates/latent-audit/src/durable.rs', 'crates/latent-audit/src/durable/store.rs',
        'crates/latent-audit/src/durable/store/io.rs', 'crates/latent-audit/src/durable/store/query.rs',
        ROOT + '.rs', *[ROOT + '/' + name + '.rs' for name in ['model', 'storage', 'rollover', 'transfer', 'tests']]]
ALLOWED = set(RUST) | {'tools/ci/suites.json'}


def replace(name, before, after):
    path = Path(name)
    text = path.read_text()
    if after in text:
        return
    if text.count(before) != 1:
        raise SystemExit('candidate-context-mismatch:' + name + ':' + before[:70])
    path.write_text(text.replace(before, after))


def prepare():
    subprocess.run(['rustup', 'run', '1.97.1', 'rustfmt', '--edition', '2021', '--config', 'skip_children=true', *RUST], check=True)


def publish():
    changed = set(subprocess.check_output(['git', 'diff', '--name-only'], text=True).splitlines())
    if not changed <= ALLOWED:
        raise SystemExit('unexpected-candidate-change:' + repr(sorted(changed - ALLOWED)))
    receipt = {'source': os.environ['GITHUB_SHA'], 'files': {}}
    for name in sorted(changed):
        raw = Path(name).read_bytes()
        if len(raw) > 2 * 1024 * 1024:
            raise SystemExit('candidate-byte-bound')
        body = json.dumps({'content': base64.b64encode(raw).decode(), 'encoding': 'base64'}).encode()
        request = urllib.request.Request('https://api.github.com/repos/KirilsTurkins/latent-service-fabric/git/blobs', data=body,
            headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'], 'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(request, timeout=30) as response:
            receipt['files'][name] = json.load(response)['sha']
    Path(os.environ['RUNNER_TEMP'], 'audit-candidates.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print('AUDIT_CANDIDATES=' + json.dumps(receipt, sort_keys=True))


if __name__ == '__main__':
    if sys.argv[1:] == ['prepare']:
        prepare()
    elif sys.argv[1:] == ['publish']:
        publish()
    else:
        raise SystemExit('explicit-candidate-operation-required')
