"""Ordinary transitive resources retained across runtime-owned timer callbacks.

File construction and native dependency capture are separate from compilation
and signed execution. Promise concurrency here means interleaved logical tasks,
not native threads. The selected console is synchronous and has no flush queue.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil

from tools.phase2_operator_process import require
from tools.rust_capsule_project import ROOT, digest, inventory, read_file, snapshot
from tools.typescript_guest.project import create
from tools.typescript_guest.runtime_profile import IMPORT_PROFILE

PACKAGES = ('outside-resource-runtime-library', 'outside-resource-runtime-data')
DATA = {'text.txt': 'Gr\u00fc\u00dfe\0\u96ea\n'.encode(),
        'binary.bin': bytes((0, 255, 128, 65, 13, 10)), 'empty.bin': b''}
WORLD = b'''package examples:resource-runtime@1.0.0;
interface api { run: async func(mode: string) -> string; }
world service { import latent:log/log@0.1.0; export api; }
'''
MAIN = b'''import type * as Contract from '../generated/interfaces/examples-resource-runtime-api.js';
import {resourceRuntime} from 'outside-resource-runtime-library';
export const api: typeof Contract = { async run(mode) { return await resourceRuntime(mode); } };
'''
RESOURCE = b'''import text from './text.txt';
import bytes from './binary.bin';
import empty from './empty.bin';
export function openedCopy() {
  if (text !== 'Gr\\u00fc\\u00dfe\\0\\u96ea\\n' || !(bytes instanceof Uint8Array) ||
      bytes.length !== 6 || bytes.some((value, index) => value !== [0,255,128,65,13,10][index]) ||
      !(empty instanceof Uint8Array) || empty.length !== 0) throw new Error('resource-runtime-data-changed');
  return {text, bytes: bytes.slice(), empty: empty.slice()};
}
'''
LIBRARY = b'''import {openedCopy} from 'outside-resource-runtime-data';
let calls = 0;
const hex = bytes => Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('');
export async function resourceRuntime(mode) {
  if (++calls !== 1) throw new Error('resource-runtime-state-survived-retirement');
  const first = openedCopy(), second = openedCopy();
  first.bytes[0] = 42;
  if (second.bytes[0] !== 0 || openedCopy().bytes[0] !== 0) throw new Error('resource-runtime-copy-shared');
  if (mode === 'parallel') {
    let callbacks = 0;
    const readLater = (label, resource) => new Promise(resolve => setTimeout(() => {
      ++callbacks;
      console.info('resource-callback:' + label);
      resolve(label + ':' + hex(resource.bytes));
    }, 10));
    const values = await Promise.all([readLater('first', first), readLater('second', second)]);
    if (callbacks !== 2 || first.text !== second.text || first.empty.length !== 0 || second.empty.length !== 0)
      throw new Error('resource-runtime-callbacks-or-text-changed');
    return 'resource-runtime|parallel=' + values.join('+') + '|callbacks=2|fresh=1';
  }
  if (mode === 'pending') {
    return await new Promise(resolve => {
      setTimeout(() => {
        console.error('resource-late-callback-must-not-run');
        resolve(hex(first.bytes));
      }, 3600000);
      console.info('resource-pending:timer-accepted');
    });
  }
  if (mode === 'trap') {
    setTimeout(() => { console.error(hex(first.bytes)); throw new Error('resource-late-trap-timer'); }, 3600000);
    await Promise.resolve();
    throw new Error('resource-runtime-root-trap');
  }
  if (mode === 'callback-error') {
    return await new Promise(() => setTimeout(() => {
      console.info('resource-callback:error:' + hex(second.bytes));
      throw new Error('resource-runtime-callback-trap');
    }, 10));
  }
  if (mode === 'clear') {
    const timer = setTimeout(() => { throw new Error('resource-runtime-cleared-callback'); }, 3600000);
    clearTimeout(timer);
    await Promise.resolve();
  } else if (mode !== 'fresh') throw new Error('resource-runtime-mode');
  console.info('resource-fresh:ordinary');
  return 'resource-runtime|' + mode + '=00ff80410d0a|empty=0|fresh=1';
}
'''
EXPECTED = {
    'parallel': 'resource-runtime|parallel=first:2aff80410d0a+second:00ff80410d0a|callbacks=2|fresh=1',
    'fresh': 'resource-runtime|fresh=00ff80410d0a|empty=0|fresh=1',
    'clear': 'resource-runtime|clear=00ff80410d0a|empty=0|fresh=1',
}


def project(directory: Path, outside: Path):
    require(outside.parent.resolve(strict=True) == directory.parent.resolve(strict=True)
            and outside.parent.resolve(strict=True) != ROOT and ROOT not in outside.parents,
            'resource-runtime-independent-outside-project')
    app = create(directory, 'greeting', 'my-greeting', runtime_profile=IMPORT_PROFILE)
    config = json.loads(read_file(app/'capsule-project.json'))
    config.update(world='examples:resource-runtime/service@1.0.0')
    config['limits']['logBytes'] = 16384
    (app/'capsule-project.json').write_bytes((json.dumps(config, indent=2)+'\n').encode())
    (app/'wit/world.wit').write_bytes(WORLD)
    (app/'src/main.ts').write_bytes(MAIN)
    log = app/'wit/deps/log';log.mkdir(parents=True)
    (log/'package.wit').write_bytes(read_file(ROOT/'wit/platform/log/package.wit'))
    lock = json.loads(read_file(app/'sdk-lock.json'))
    lock['template'].update(sourceDigest=digest(MAIN), witDigest=digest(WORLD))
    (app/'sdk-lock.json').write_bytes((json.dumps(lock, indent=2)+'\n').encode())
    outside.mkdir(mode=0o700)
    library, data = outside/'library', outside/'data'
    for path, name in ((library, PACKAGES[0]), (data, PACKAGES[1])):
        path.mkdir()
        package = {'name': name, 'version': '1.0.0', 'type': 'module', 'license': 'Apache-2.0',
                   'exports': {'types': './index.d.ts', 'import': './index.mjs'}}
        if path == library:package['dependencies'] = {PACKAGES[1]: 'file:'+str(data.resolve())}
        (path/'package.json').write_bytes((json.dumps(package, indent=2)+'\n').encode())
    (library/'index.mjs').write_bytes(LIBRARY)
    (library/'index.d.ts').write_bytes(b'export function resourceRuntime(mode: string): Promise<string>;\n')
    (data/'index.mjs').write_bytes(RESOURCE)
    (data/'index.d.ts').write_bytes(b'export function openedCopy(): {text: string; bytes: Uint8Array; empty: Uint8Array};\n')
    for name, raw in DATA.items():(data/name).write_bytes(raw)
    return app, {'source': digest(inventory(snapshot(app))), 'outside': digest(inventory(snapshot(outside))),
                 'sdkLock': digest(read_file(app/'sdk-lock.json')), 'packages': list(PACKAGES),
                 'runtimeProfile': IMPORT_PROFILE, 'nativeThreadsQualified': False,
                 'pendingFlushQualified': False, 'signedExecution': 'pending'}


def capture(app: Path, outside: Path):
    from tools import typescript_dependency_authoring as authoring
    from tools.application_dependencies import verify_inputs
    from tools.npm_lock_authoring import create_lock
    from tools.typescript_application_dependencies import resolve
    before = read_file(app/'sdk-lock.json')
    library, data = outside/'library', outside/'data'
    authoring.edit(app, 'add', identity=PACKAGES[0], local=library)
    node = Path(shutil.which('node') or 'missing-node')
    npm = (node.parent/'node_modules/npm/bin/npm-cli.js' if os.name == 'nt' else
           Path(shutil.which('npm') or 'missing-npm').resolve())
    native = create_lock(app, node=node, npm=npm)
    candidate = app/'target/resource-runtime.candidate.json';candidate.parent.mkdir(exist_ok=True)
    resolve(app, candidate, node=node, npm=npm)
    authoring.review(app, candidate, digest(read_file(candidate)))
    verified = verify_inputs(app, 'typescript')
    graph = json.loads(read_file(app/'npm-resolved.lock.json'))
    selected = {row['location'] for row in graph['nodes'] if row['selected']}
    require(verified is not None and verified.lock['selection']['runtimeProfile'] == IMPORT_PROFILE
            and {'node_modules/'+name for name in PACKAGES} <= selected,
            'resource-runtime-captured-transitive-profile')
    root = outside.resolve(strict=True)
    require(not outside.is_symlink() and all(not path.is_symlink()
            and path.resolve(strict=True).parent == root for path in (library, data)),
            'resource-runtime-owned-original-removal')
    for path in (library, data):shutil.rmtree(path)
    require(verify_inputs(app, 'typescript').identity == verified.identity
            and read_file(app/'sdk-lock.json') == before, 'resource-runtime-offline-closure-unchanged')
    return {'nativeLock': native, 'acceptedLock': digest(read_file(app/'latent.dependencies.lock.json')),
            'outsideOriginalRemoved': True, 'catalogueRegistration': False, 'applicationResourceBridge': False,
            'signedExecution': 'pending'}
