"""Exact captured callback and one-root-edge compiler counterfactual; no execution here."""
from pathlib import Path
import json
import os
import shutil

from tools.phase2_operator_process import require
from tools.rust_capsule_project import digest, inventory, read_file, snapshot
from tools.typescript_guest.project import create

CASES = (('catch', 7, 42), ('catch', 11, 62), ('uncaught', 13, None), ('catch', 19, 102))

CALLBACK = """class DefaultClock { read() { return Date.now(); } }
export function unsupportedClockCallback() { return new DefaultClock().read(); }
"""
LIBRARY = """export {unsupportedClockCallback} from 'outside-elimination-callback';
export function alternate(seed) { return seed * 5 + 7; }
"""
ROOT_EDGE = '  if (false) { // selected-root-clock-edge'
PROBE = r'''
let eliminationCalls = 0;
function eliminationCase(value: string) {
  if (++eliminationCalls !== 1) throw new Error('elimination-state-reused');
  const match = /^(catch|uncaught):([0-9]{1,4})$/.exec(value);
  if (!match) throw new Error('elimination-input');
  const seed = Number(match[2]);
  if (!Number.isSafeInteger(seed) || seed > 1000) throw new Error('elimination-seed');
  let refused = false;
  if (false) { // selected-root-clock-edge
    if (match[1] === 'uncaught') unsupportedClockCallback();
    try {
      unsupportedClockCallback();
      throw new Error('elimination-unexpected-clock-success');
    } catch (error) {
      if (!(error instanceof Error) || error.message !== 'unsupported:standard-clock-without-approved-profile') throw error;
      refused = true;
    }
  }
  if (match[1] === 'uncaught') throw new Error('elimination-terminal-after-unselected-edge');
  const result = alternate(seed);
  return `elimination|typescript|seed=${seed}|alternate=${result}|refused=${refused ? 1 : 0}|fresh=1`;
}
'''


def expected(seed, alternate, reached):
    require(type(reached) is bool and type(seed) is type(alternate) is int and 0 <= seed <= 1000
        and alternate == seed * 5 + 7, 'typescript-elimination-finite-expectation')
    return [{'ok': f'elimination|typescript|seed={seed}|alternate={alternate}|refused={int(reached)}|fresh=1'}]


def select_root_edge(app: Path):
    """Change only the root application's one constant edge; captured libraries stay exact."""
    before = snapshot(app)
    source = before['src/main.ts']
    old = ROOT_EDGE.encode()
    require(source.count(old) == 1, 'typescript-elimination-one-original-root-edge')
    selected = source.replace(old, old.replace(b'false', b'true'), 1)
    (app / 'src/main.ts').write_bytes(selected)
    after = snapshot(app)
    require(set(after) == set(before) and all(before[name] == after[name] for name in before if name != 'src/main.ts'),
        'typescript-elimination-only-root-edge-change')
    return {'oldRoot': digest(source), 'newRoot': digest(selected), 'libraryBytesChanged': False,
        'runtimeProfileOrGrantChanged': False, 'compilerExecuted': False}


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
    require(before.count(anchor) == 1, 'typescript-elimination-original-template')
    source.write_bytes(b"import {alternate, unsupportedClockCallback} from 'outside-elimination-library';\n" + PROBE.encode() + before.replace(
        anchor, anchor + b"\n    if (name.startsWith('elimination:')) return eliminationCase(name.slice(12));", 1))
    outside.mkdir(mode=0o700)
    library, callback = outside / 'library', outside / 'callback'
    library.mkdir(); callback.mkdir()
    for path, name, code, declarations, dependencies in (
        (callback, 'outside-elimination-callback', CALLBACK,
            'export function unsupportedClockCallback(): number;\n', {}),
        (library, 'outside-elimination-library', LIBRARY,
            'export function unsupportedClockCallback(): number; export function alternate(seed: number): number;\n',
            {'outside-elimination-callback': 'file:' + str(callback.resolve())})):
        (path / 'package.json').write_bytes((json.dumps({'name': name, 'version': '1.0.0',
            'type': 'module', 'license': 'Apache-2.0',
            'exports': {'types': './index.d.ts', 'import': './index.mjs'},
            'dependencies': dependencies}, indent=2) + '\n').encode())
        (path / 'index.mjs').write_bytes(code.encode())
        (path / 'index.d.ts').write_bytes(declarations.encode())
    authoring.edit(app, 'add', identity='outside-elimination-library', local=library)
    node = Path(shutil.which('node') or 'missing-node')
    npm = node.parent / 'node_modules/npm/bin/npm-cli.js' if os.name == 'nt' else Path(shutil.which('npm') or 'missing-npm').resolve()
    native_lock = create_lock(app, node=node, npm=npm)
    candidate = app / 'target/elimination-dependencies.candidate.json'
    candidate.parent.mkdir(exist_ok=True)
    resolve(app, candidate, node=node, npm=npm)
    authoring.review(app, candidate, digest(read_file(candidate)))
    verified = verify_inputs(app, 'typescript')
    graph = json.loads(read_file(app / 'npm-resolved.lock.json'))
    selected = {row['location'] for row in graph['nodes'] if row['selected']}
    require({'node_modules/outside-elimination-library', 'node_modules/outside-elimination-callback'} <= selected,
        'typescript-elimination-transitive-callback-capture')
    require(outside.resolve(strict=True) == library.resolve(strict=True).parent == callback.resolve(strict=True).parent
        and not any(path.is_symlink() for path in (outside, library, callback)), 'typescript-elimination-owned-source-removal')
    shutil.rmtree(outside)
    require(verify_inputs(app, 'typescript').lock == verified.lock and read_file(app / 'sdk-lock.json') == original_sdk
        and read_file(app / 'capsule-project.json') == original_project and read_file(app / 'wit/world.wit') == original_world,
        'typescript-elimination-offline-closure-and-unchanged-sdk')
    return app, {'language': 'typescript', 'sourceDigest': digest(inventory(snapshot(app))),
        'nativeLock': native_lock, 'capturedLock': digest(read_file(app / 'latent.dependencies.lock.json')),
        'library': digest(LIBRARY.encode()), 'callback': digest(CALLBACK.encode()),
        'outsideOriginals': 'removed-before-compiler', 'rootEdgeSelected': False,
        'clockProfileEnabled': False, 'grantsAdded': False,
        'compilerExecuted': False, 'signedQualification': 'pending'}
