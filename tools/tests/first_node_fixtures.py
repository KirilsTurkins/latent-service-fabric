"""Synthetic subprocesses for guide orchestration tests, never runtime evidence."""
import hashlib
import json
from pathlib import Path
import sys

NODE = r'''
import json, signal, sys, time
from pathlib import Path
args = sys.argv[1:]
config = Path(args[args.index('--config') + 1])
node = json.loads(config.read_text())
if args[0] == 'check-config':
    if node.get('formatVersion') != 1:
        sys.stderr.write('latentd: configuration: invalid-argument\n')
        sys.exit(2)
    print('synthetic configuration only')
    sys.exit(0)
root = config.parent.parent
case = (root / 'case').read_text() if (root / 'case').exists() else ''
config.parent.joinpath('data').mkdir(exist_ok=True)
(root / 'online').write_text('yes')
print(json.dumps({'schemaVersion':'latent.standalone.status.v1', 'event':'started',
                  'nodeId':node['nodeId'], 'endpoint':'127.0.0.1:12345'}), flush=True)
def stop(*_):
    (root / 'online').unlink(missing_ok=True)
    print(json.dumps({'schemaVersion':'latent.standalone.status.v1', 'event':'stopped',
                      'clean':case != 'unclean', 'report':{'clean':case != 'unclean'}}), flush=True)
    sys.exit(0)
signal.signal(signal.SIGTERM, stop)
while True: time.sleep(0.01)
'''

CLI = r'''
import base64, json, sys
from pathlib import Path
root = Path.cwd().parent
args = sys.argv[1:]
args.remove('--output'); args.remove('json')
config = None
if '--config' in args:
    offset = args.index('--config'); config = Path(args[offset + 1]); del args[offset:offset + 2]
    offset = args.index('--profile'); del args[offset:offset + 2]
with (root / 'calls').open('a') as stream: stream.write(json.dumps(args) + '\n')
category, code, data = 'success', 0, {}
known, dispatched = True, config is not None
case = (root / 'case').read_text() if (root / 'case').exists() else ''
if args[0] == 'validate':
    document = json.loads(Path(args[2]).read_text())
    if document.get('notACapsule'): category, code = 'local-error', 2
elif args[:2] == ['node', 'get']:
    if not (root / 'online').exists(): category, code, known = 'transport-failure', 5, False
    else:
        token = json.loads(config.read_text())['profiles'][0]['token']
        original = json.loads(root.joinpath('node/node.json').read_text())['credentials'][0]['token']
        if token != original: category, code = 'platform-failure', 4
        else: data = {'inventory':{'health':{'ready':True}}}
elif args[:2] == ['release', 'publish']:
    path = Path(args[args.index('--manifest') + 1]); digest = json.loads(path.read_text())['component']['digest']
    data = {'release':{'digest':digest}}
    (root / 'release').write_text(json.dumps(data['release']))
elif args[:2] == ['release', 'get']:
    data = {'release': json.loads((root / 'release').read_text())}
elif args[:2] == ['deployment', 'apply']:
    (root / 'deployment').write_text('1'); data = {'deployment':{'generation':'1'}}
elif args[:2] == ['deployment', 'get']:
    if (root / 'deployment').exists(): data = {'deployment':{'generation':'1'}}
    else: category, code = 'not-found', 6
elif args[:2] == ['deployment', 'delete']:
    (root / 'deployment').unlink()
elif args[:2] == ['activation', 'get']:
    data = {'terminalState':'completed'}
elif args[0] == 'invoke':
    identifier = args[args.index('--activation-id') + 1]
    data = {'activationId': identifier}
    if identifier == 'first-node-empty': category, code = 'declared-error', 3
    elif case == 'invoke-failed': category, code, known = 'transport-failure', 5, False
    else:
        raw = b'[{"ok":"hello"}]'
        data['payload'] = {'encoding':'base64', 'mediaType':'application/vnd.latent.wit-values.v1+json',
                           'data':base64.b64encode(raw).decode(), 'byteLength':str(len(raw))}
    if case == 'wrong-identity': data['activationId'] = 'not-the-requested-id'
print(json.dumps({'schemaVersion':'latent.cli.result.v1', 'category':category, 'data':data,
                  'error':None, 'outcomeKnown':known, 'requestDispatched':dispatched}))
sys.exit(code)
'''


def executable(directory: Path, name: str, body: str) -> Path:
    path = directory / name
    path.write_text(f'#!{sys.executable} -S\n' + body, encoding='utf-8')
    path.chmod(0o700)
    return path


def echo(directory: Path) -> dict:
    directory.mkdir()
    component = b'synthetic component bytes, never executed as WebAssembly'
    digest = 'sha256:' + hashlib.sha256(component).hexdigest()
    documents = {
        'capsule.json': {'component': {'digest': digest}},
        'contracts.json': {'synthetic': True},
        'deployment.json': {'metadata': {'name':'echo-production', 'tenant':'examples'},
                            'spec': {'service':'examples/echo', 'release':digest}},
        'input.json': ['hello'],
    }
    for name, document in documents.items():
        (directory / name).write_text(json.dumps(document), encoding='utf-8')
    (directory / 'echo-capsule.wasm').write_bytes(component)
    return documents
