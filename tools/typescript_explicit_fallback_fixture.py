"""Captured transitive callback with an explicit ordinary-language fallback."""
from pathlib import Path
import json
import os
import shutil

from tools.phase2_operator_process import require
from tools.rust_capsule_project import digest, inventory, read_file, snapshot
from tools.typescript_guest.project import create

CASES = (('catch', 7, 42), ('catch', 11, 62), ('uncaught', 13, None), ('catch', 19, 102))
REFUSAL = 'unsupported:standard-clock-without-approved-profile'
CALLBACK = '''export class DefaultClock {
  read() { return Date.now(); }
  alternate(seed) { return seed * 5 + 7; }
}
'''
LIBRARY = '''import {DefaultClock} from 'outside-fallback-callback';
let calls = 0;
export function fallbackCase(value) {
  if (++calls !== 1) throw new Error('fallback-state-reused');
  const match = /^(catch|uncaught):([0-9]{1,4})$/.exec(value);
  if (!match) throw new Error('fallback-input');
  const seed = Number(match[2]);
  if (!Number.isSafeInteger(seed) || seed > 1000) throw new Error('fallback-seed');
  const clock = new DefaultClock();
  if (match[1] === 'uncaught') {
    clock.read();
    throw new Error('fallback-unexpected-clock-success');
  }
  try {
    clock.read();
  } catch (error) {
    if (!(error instanceof Error) || error.message !== 'unsupported:standard-clock-without-approved-profile') throw error;
    const alternate = clock.alternate(seed);
    return `fallback|typescript|unsupported|seed=${seed}|alternate=${alternate}|fresh=1`;
  }
  throw new Error('fallback-unexpected-clock-success');
}
'''


def expected(seed, alternate):
    require(type(seed) is type(alternate) is int and 0 <= seed <= 1000
        and alternate == seed * 5 + 7, 'typescript-fallback-finite-expectation')
    return [{'ok': f'fallback|typescript|unsupported|seed={seed}|alternate={alternate}|fresh=1'}]


def project(directory: Path, outside: Path):
    from tools import typescript_dependency_authoring as authoring
    from tools.application_dependencies import verify_inputs
    from tools.npm_lock_authoring import create_lock
    from tools.typescript_application_dependencies import resolve
    app = create(directory, 'greeting')
    original_sdk = read_file(app / 'sdk-lock.json')
    original_project = read_file(app / 'capsule-project.json')
    original_world = read_file(app / 'wit/world.wit')
    source = app / 'src/main.ts'
    before = read_file(source)
    anchor = b'  greet(name) {'
    require(before.count(anchor) == 1, 'typescript-fallback-original-template')
    source.write_bytes(b"import {fallbackCase} from 'outside-fallback-library';\n" + before.replace(
        anchor, anchor + b"\n    if (name.startsWith('fallback:')) return fallbackCase(name.slice(9));", 1))
    outside.mkdir(mode=0o700)
    library, callback = outside / 'library', outside / 'callback'
    library.mkdir(); callback.mkdir()
    for path, name, code, declarations, dependencies in (
        (callback, 'outside-fallback-callback', CALLBACK,
            'export class DefaultClock { read(): number; alternate(seed: number): number; }\n', {}),
        (library, 'outside-fallback-library', LIBRARY,
            'export function fallbackCase(value: string): string;\n',
            {'outside-fallback-callback': 'file:' + str(callback.resolve())})):
        (path / 'package.json').write_bytes((json.dumps({'name': name, 'version': '1.0.0',
            'type': 'module', 'license': 'Apache-2.0',
            'exports': {'types': './index.d.ts', 'import': './index.mjs'},
            'dependencies': dependencies}, indent=2) + '\n').encode())
        (path / 'index.mjs').write_bytes(code.encode())
        (path / 'index.d.ts').write_bytes(declarations.encode())
    authoring.edit(app, 'add', identity='outside-fallback-library', local=library)
    node = Path(shutil.which('node') or 'missing-node')
    npm = node.parent / 'node_modules/npm/bin/npm-cli.js' if os.name == 'nt' else Path(shutil.which('npm') or 'missing-npm').resolve()
    native_lock = create_lock(app, node=node, npm=npm)
    candidate = app / 'target/fallback-dependencies.candidate.json'
    candidate.parent.mkdir(exist_ok=True)
    resolve(app, candidate, node=node, npm=npm)
    authoring.review(app, candidate, digest(read_file(candidate)))
    verified = verify_inputs(app, 'typescript')
    graph = json.loads(read_file(app / 'npm-resolved.lock.json'))
    selected = {row['location'] for row in graph['nodes'] if row['selected']}
    require({'node_modules/outside-fallback-library', 'node_modules/outside-fallback-callback'} <= selected,
        'typescript-fallback-transitive-callback-capture')
    require(outside.resolve(strict=True) == library.resolve(strict=True).parent == callback.resolve(strict=True).parent
        and not any(path.is_symlink() for path in (outside, library, callback)), 'typescript-fallback-owned-source-removal')
    shutil.rmtree(outside)
    require(verify_inputs(app, 'typescript').lock == verified.lock and read_file(app / 'sdk-lock.json') == original_sdk
        and read_file(app / 'capsule-project.json') == original_project and read_file(app / 'wit/world.wit') == original_world,
        'typescript-fallback-offline-closure-and-unchanged-sdk')
    return app, {'language': 'typescript', 'sourceDigest': digest(inventory(snapshot(app))),
        'nativeLock': native_lock, 'capturedLock': digest(read_file(app / 'latent.dependencies.lock.json')),
        'library': digest(LIBRARY.encode()), 'callback': digest(CALLBACK.encode()),
        'outsideOriginals': 'removed-before-compiler', 'explicitApplicationFallback': True,
        'clockProfileEnabled': False, 'grantsAdded': False,
        'compilerExecuted': False, 'signedQualification': 'pending'}
