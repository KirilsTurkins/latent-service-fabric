"""Outside ordinary clock library/data, captured through normal npm authoring."""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
from tools.phase2_operator_process import require
from tools.rust_capsule_project import digest, inventory, read_file, snapshot
from tools.typescript_guest.project import create
from tools.typescript_guest.runtime_profile import CLOCK_PROFILE

TEXT = 'clock|Gr\u00fc\u00dfe'
BINARY = bytes((0, 255, 65, 128))
LIBRARY = r"""import {text, bytes} from 'outside-clock-data';
let calls = 0;
export function clockCase(mode) {
  if (++calls !== 1) throw new Error('clock-state-reused');
  if (text !== 'clock|Gr\u00fc\u00dfe' || bytes.length !== 4 || bytes[0] !== 0 ||
      bytes[1] !== 255 || bytes[2] !== 65 || bytes[3] !== 128) throw new Error('clock-data-changed');
  if (mode === 'wall') {
    const wall = Date.now(), constructed = new Date().valueOf(), formatted = Date('ignored');
    if (!Number.isInteger(wall) || wall <= 0 || wall > 8640000000000000 ||
        !Number.isInteger(constructed) || constructed <= 0 || constructed > 8640000000000000 ||
        typeof formatted !== 'string' || formatted.length === 0) throw new Error('clock-wall-shape');
  } else if (mode === 'explicit') {
    if (new Date(0).toISOString() !== '1970-01-01T00:00:00.000Z' ||
        Date.UTC(1970,0,1) !== 0 || Date.parse('1970-01-01T00:00:00.000Z') !== 0 ||
        !Number.isNaN(new Date(undefined).valueOf())) throw new Error('clock-explicit-date');
  } else if (mode === 'monotonic' || mode === 'fresh') {
    const first = performance.now(), second = performance.now(), epoch = performance.timeOrigin;
    if (first !== 0 || !Number.isFinite(second) || second < first || !Number.isInteger(epoch) ||
        epoch <= 0 || epoch > 8640000000000000) throw new Error('clock-performance-shape');
  } else if (mode === 'repeated') {
    let previous = performance.now();
    for (let index=0; index<33; index++) {
      const now = performance.now();
      if (!Number.isFinite(now) || now < previous || Date.now() <= 0) throw new Error('clock-repeat');
      previous = now;
    }
  } else if (mode === 'trap') {
    Date.now(); performance.now(); throw new Error('ordinary-clock-fixture-trap');
  } else if (mode === 'fuel') {
    Date.now(); while (true) {}
  } else if (mode !== 'entry') throw new Error('clock-mode');
  return 'clock:'+mode+'|'+text+'|binary=00ff4180|fresh=1';
}
"""


def selected_project(directory: Path, outside: Path) -> tuple[Path, dict]:
    from tools import typescript_dependency_authoring as authoring
    from tools.npm_lock_authoring import create_lock
    from tools.typescript_application_dependencies import resolve
    from tools.application_dependencies import verify_inputs
    app = create(directory, 'greeting', runtime_profile=CLOCK_PROFILE)
    source = app/'src/main.ts'
    original = read_file(source)
    require(original.count(b'  greet(name) {') == 1, 'clock-original-template')
    source.write_bytes(b"import {clockCase} from 'outside-clock-library';\n" + original.replace(
        b'  greet(name) {', b"  greet(name) {\n    if (name.startsWith('clock:')) return clockCase(name.slice(6));", 1))
    outside.mkdir(mode=0o700)
    library, child = outside/'library', outside/'data'
    for path in (library, child):
        path.mkdir()
    declarations = [(library/'package.json', {
        'name': 'outside-clock-library', 'version': '1.0.0', 'type': 'module', 'license': 'Apache-2.0',
        'exports': {'types': './index.d.ts', 'import': './index.mjs'},
        'dependencies': {'outside-clock-data': 'file:'+str(child.resolve())}}),
        (child/'package.json', {'name': 'outside-clock-data', 'version': '1.0.0', 'type': 'module',
        'license': 'Apache-2.0', 'exports': {'types': './index.d.ts', 'import': './index.mjs'}})]
    for path, value in declarations:
        path.write_bytes((json.dumps(value, indent=2)+'\n').encode())
    (library/'index.mjs').write_bytes(LIBRARY.encode())
    (library/'index.d.ts').write_bytes(b'export function clockCase(mode: string): string;\n')
    (child/'index.mjs').write_bytes(b"import text from './clock.txt';import bytes from './clock.bin';export {text,bytes};\n")
    (child/'index.d.ts').write_bytes(b'export const text: string; export const bytes: Uint8Array;\n')
    (child/'clock.txt').write_bytes(TEXT.encode())
    (child/'clock.bin').write_bytes(BINARY)
    authoring.edit(app, 'add', identity='outside-clock-library', local=library)
    node = Path(shutil.which('node') or 'missing-node')
    npm = (node.parent/'node_modules/npm/bin/npm-cli.js' if os.name == 'nt' else
           Path(shutil.which('npm') or 'missing-npm').resolve())
    native = create_lock(app, node=node, npm=npm)
    candidate = app/'target/clock-dependencies.candidate.json'
    candidate.parent.mkdir(exist_ok=True)
    resolve(app, candidate, node=node, npm=npm)
    authoring.review(app, candidate, digest(read_file(candidate)))
    verified = verify_inputs(app, 'typescript')
    require(verified is not None and verified.lock['selection']['runtimeProfile'] == CLOCK_PROFILE,
            'clock-captured-profile')
    graph = json.loads(read_file(app/'npm-resolved.lock.json'))
    selected = {row['location'] for row in graph['nodes'] if row['selected']}
    require({'node_modules/outside-clock-library', 'node_modules/outside-clock-data'} <= selected,
            'clock-real-transitive-graph-required')
    original_sdk = read_file(app/'sdk-lock.json')
    require(outside.resolve(strict=True) == library.resolve(strict=True).parent == child.resolve(strict=True).parent
            and not outside.is_symlink() and not library.is_symlink() and not child.is_symlink(),
            'clock-owned-source-removal')
    shutil.rmtree(outside)
    require(verify_inputs(app, 'typescript').lock == verified.lock and read_file(app/'sdk-lock.json') == original_sdk,
            'clock-offline-closure-or-sdk-changed')
    return app, {'runtimeProfile': CLOCK_PROFILE, 'source': digest(inventory(snapshot(app))),
        'capturedLock': digest(read_file(app/'latent.dependencies.lock.json')), 'nativeLock': native,
        'library': digest(LIBRARY.encode()), 'text': digest(TEXT.encode()), 'binary': digest(BINARY),
        'outsideOriginals': 'removed-before-compiler', 'libraryClockAPI': 'unchanged-Date-and-performance',
        'compilerExecution': False, 'signedExecution': 'pending', 'publisherAuthenticated': False}


def closed_project(directory: Path) -> Path:
    app = create(directory, 'word-count')
    source = app/'src/main.ts'
    before = read_file(source)
    require(before.count(b'  count(text) {') == 1, 'clock-original-closed-template')
    source.write_bytes(before.replace(b'  count(text) {', b'''  count(text) {
    if (text === 'clock:explicit') {
      if (new Date(0).valueOf() !== 0 || Date.UTC(1970,0,1) !== 0 ||
          Date.parse('1970-01-01T00:00:00.000Z') !== 0 || !Number.isNaN(new Date(undefined as unknown as number).valueOf())) {
        throw new Error('closed-explicit-Date-changed');
      }
      return 681;
    }
    if (text.startsWith('clock:undeclared:')) {
      const observed = globalThis as unknown as {performance: {now(): number; readonly timeOrigin: number}};
      try {
        switch (text.slice(17)) {
          case 'now': Date.now(); break;
          case 'function': Date(); break;
          case 'function-args': (Date as unknown as (...ignored: unknown[]) => string)('ignored'); break;
          case 'construct': new Date(); break;
          case 'monotonic': observed.performance.now(); break;
          case 'origin': void observed.performance.timeOrigin; break;
          default: throw new Error('closed-clock-mode');
        }
      } catch (error) {
        if (error instanceof Error && error.message === 'unsupported:standard-clock-without-approved-profile') return 681;
        throw error;
      }
      throw new Error('undeclared-clock-returned-a-value');
    }''', 1))
    return app
