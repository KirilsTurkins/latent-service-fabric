"""Prepared ordinary pending-Promise inputs; execution/retirement is a separate gate."""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import sys
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.phase2_operator_process import require
from tools.rust_capsule_project import ROOT, digest, inventory, read_file, snapshot
from tools.typescript_guest.project import create
from tools.typescript_guest.runtime_profile import CLOCK_PROFILE

WORLD = b'''package examples:typescript-runtime-retirement@1.0.0;
interface ordinary { run: async func(mode: u32) -> u32; }
world service { export ordinary; }
'''
MAIN = b'''import type * as Contract from '../generated/interfaces/examples-typescript-runtime-retirement-ordinary.js';
import {lifecycle} from 'outside-promise-retirement';
export const ordinary: typeof Contract = {
  async run(mode) { return await lifecycle(mode); },
};
'''
LIBRARY = b'''let calls = 0;
export async function lifecycle(mode) {
  if (++calls !== 1) throw new Error('retirement-module-state-reused');
  if (mode === 0) {
    return await new Promise(resolve => { setTimeout(() => resolve(42), 3600000); });
  }
  if (mode === 1) return 42;
  if (mode === 2) {
    setTimeout(() => { throw new Error('retirement-cancelled-timer-fired'); }, 3600000);
    throw new Error('retirement-root-trap-with-accepted-timer');
  }
  if (mode === 3) {
    const timer = setTimeout(() => { throw new Error('retirement-cleared-timer-fired'); }, 3600000);
    clearTimeout(timer);
    return await Promise.resolve(42);
  }
  if (mode === 4) {
    setTimeout(() => { throw new Error('retirement-accepted-callback-must-not-disappear'); }, 0);
    return 42;
  }
  throw new Error('retirement-mode');
}
'''


def project(directory):
    app = create(directory, 'greeting', 'typescript-runtime-retirement', runtime_profile=CLOCK_PROFILE)
    descriptor = json.loads(read_file(app/'capsule-project.json'))
    descriptor.update(world='examples:typescript-runtime-retirement/service@1.0.0',
                      service='examples/typescript-runtime-retirement')
    (app/'capsule-project.json').write_bytes((json.dumps(descriptor, indent=2)+'\n').encode())
    (app/'wit/world.wit').write_bytes(WORLD)
    (app/'src/main.ts').write_bytes(MAIN)
    return app


def capture(app, outside):
    from tools import typescript_dependency_authoring as authoring
    from tools.application_dependencies import verify_inputs
    from tools.npm_lock_authoring import create_lock
    from tools.typescript_application_dependencies import resolve
    require(outside.parent.resolve(strict=True) == app.parent.resolve(strict=True)
            and outside.parent.resolve(strict=True) != ROOT and ROOT not in outside.parents,
            'typescript-retirement-owned-outside-source')
    outside.mkdir(mode=0o700)
    (outside/'package.json').write_bytes((json.dumps({'name': 'outside-promise-retirement', 'version': '1.0.0',
        'type': 'module', 'license': 'Apache-2.0',
        'exports': {'types': './index.d.ts', 'import': './index.mjs'}}, indent=2)+'\n').encode())
    (outside/'index.mjs').write_bytes(LIBRARY)
    (outside/'index.d.ts').write_bytes(b'export function lifecycle(mode: number): Promise<number>;\n')
    sdk = read_file(app/'sdk-lock.json')
    authoring.edit(app, 'add', identity='outside-promise-retirement', local=outside)
    node = Path(shutil.which('node') or 'missing-node')
    npm = node.parent/'node_modules/npm/bin/npm-cli.js' if os.name == 'nt' else Path(shutil.which('npm') or 'missing-npm').resolve()
    native = create_lock(app, node=node, npm=npm)
    candidate = app/'target/retirement-dependencies.candidate.json'
    candidate.parent.mkdir(exist_ok=True)
    resolve(app, candidate, node=node, npm=npm)
    authoring.review(app, candidate, digest(read_file(candidate)))
    accepted = verify_inputs(app, 'typescript')
    require(accepted is not None and accepted.lock['selection']['runtimeProfile'] == CLOCK_PROFILE,
            'typescript-retirement-reviewed-profile')
    require(not outside.is_symlink() and outside.resolve(strict=True).parent == app.parent.resolve(strict=True),
            'typescript-retirement-source-removal-scope')
    shutil.rmtree(outside)
    require(verify_inputs(app, 'typescript').lock == accepted.lock and read_file(app/'sdk-lock.json') == sdk,
            'typescript-retirement-offline-or-sdk-changed')
    return {'source': digest(inventory(snapshot(app))), 'library': digest(LIBRARY), 'nativeLock': native,
        'acceptedLock': digest(read_file(app/'latent.dependencies.lock.json')), 'outsideOriginalRemoved': True,
        'publishedLibrary': False, 'compilerExecuted': False, 'signedRetirement': 'pending',
        'operations': ['pending-root', 'fresh', 'root-trap-with-timer', 'clear-before-fire', 'accepted-callback-error']}


def compile_fixture(output, tools, contracts, packager, engine, envelope):
    from tools.rust_capsule_project import fresh, write_json
    from tools.typescript_guest.build import build
    output = fresh(output)
    app = project(output/'project')
    captured = capture(app, output/'outside-original')
    write_json(output/'capture.json', captured)
    before = inventory(snapshot(app))
    result = build(app, output/'typescript-runtime-retirement', contracts, packager,
        'https://github.com/KirilsTurkins/latent-service-fabric', tools=tools,
        runtime_engine=engine, runtime_engine_receipt=envelope)
    require(inventory(snapshot(app)) == before and read_file(result/'source-inputs.json') == before,
            'typescript-retirement-compiled-source-changed')
    return result


def compile_inputs(output, tools, contracts, packager, engine, envelope):
    """Build genuine caller/callee observations for the existing signed test fixture."""
    from tools.typescript_guest.build import build
    caller = compile_fixture(output, tools, contracts, packager, engine, envelope)
    callee = create(output/'project-callee', 'greeting', 'typescript-runtime-callee')
    descriptor = json.loads(read_file(callee/'capsule-project.json'))
    descriptor.update(world='examples:typescript-runtime-callee/service@1.0.0',
                      service='examples/typescript-runtime-callee')
    (callee/'capsule-project.json').write_bytes((json.dumps(descriptor, indent=2)+'\n').encode())
    (callee/'wit/world.wit').write_bytes(b'''package examples:typescript-runtime-callee@1.0.0;
interface api { run: func(mode: u32) -> u32; }
world service { export api; }
''')
    (callee/'src/main.ts').write_bytes(b'''import type * as Contract from '../generated/interfaces/examples-typescript-runtime-callee-api.js';
export const api: typeof Contract = { run(_mode) { return 42; } };
''')
    # The unrelated fixture companion uses the ordinary synchronous compiler,
    # never a reconstructed observation relabelled from another application.
    companion = build(callee, output/'typescript-service-callee', contracts, packager,
        'https://github.com/KirilsTurkins/latent-service-fabric', tools=tools)
    return {'caller': caller, 'callee': companion}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('output', 'tools', 'contracts', 'packager', 'engine', 'envelope'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    compiled = compile_inputs(args.output, args.tools, args.contracts, args.packager, args.engine, args.envelope)
    print(json.dumps({name: str(path) for name, path in compiled.items()}))
