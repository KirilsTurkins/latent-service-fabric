"""Real npm/resource qualification fixture, separate from application routing."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil

from tools.build_snapshot import digest
from tools.typescript_application_dependencies import resolve
from tools.typescript_dependency_authoring import review


def install(project: Path, outside: Path) -> dict:
    outside.mkdir(mode=0o700)
    library = outside / 'developer-owned-library'
    library.mkdir()
    declaration = {'name': 'outside-qualification-module', 'version': '1.0.0', 'type': 'module', 'license': 'Apache-2.0',
        'exports': {'types': './index.d.ts', 'import': './esm.mjs', 'require': './cjs.cjs'},
        'scripts': {'prepare': 'node forbidden-prepare.cjs'},
        'dependencies': {'@jridgewell/trace-mapping': '0.3.31'}}
    (library / 'package.json').write_text(json.dumps(declaration, indent=2) + '\n', encoding='utf-8')
    (library / 'forbidden-prepare.cjs').write_text('throw new Error("package lifecycle scripts must not run implicitly");\n', encoding='ascii')
    (library / 'index.d.ts').write_text('export function prefix(): string;\n', encoding='ascii')
    (library / 'greeting.json').write_text(json.dumps({'version': 3, 'names': ['Hello, '],
        'sources': ['immutable-\u00e9.txt'], 'mappings': 'AAAAA'}, ensure_ascii=False) + '\n', encoding='utf-8')
    resource = b'Hello, '
    (library / 'greeting.txt').write_bytes(resource)
    (library / 'greeting.bin').write_bytes(resource)
    (library / 'cjs.cjs').write_text('''const { TraceMap, originalPositionFor } = require('@jridgewell/trace-mapping');
const data = require('./greeting.json');
exports.prefix = () => {
    const result = originalPositionFor(new TraceMap(data), {line: 1, column: 0});
    if (result.source !== 'immutable-\\u00e9.txt') throw new Error('captured UTF-8 resource changed');
    return result.name;
};
''', encoding='ascii')
    (library / 'esm.mjs').write_text('''import { prefix as compute } from './cjs.cjs';
import text from './greeting.txt';
import bytes from './greeting.bin';
export function prefix() {
    const result = compute();
    if (text !== result || bytes.byteLength !== result.length || bytes[0] !== 72 || bytes[6] !== 32)
        throw new Error('captured text/binary resource changed');
    return result;
}
''', encoding='ascii')
    from tools import typescript_dependency_authoring as authoring
    from tools.npm_lock_authoring import create_lock
    authoring.edit(project, 'add', identity='outside-qualification-module', local=library)
    node = Path(shutil.which('node') or 'missing-node')
    npm = (node.parent / 'node_modules/npm/bin/npm-cli.js' if os.name == 'nt' else Path(shutil.which('npm') or 'missing-npm').resolve())
    native_lock = create_lock(project, node=node, npm=npm)
    candidate = project / 'target/qualification.candidate.json'
    candidate.parent.mkdir(exist_ok=True)
    lock = resolve(project, candidate, node=node, npm=npm)
    review(project, candidate, digest(candidate.read_bytes()))
    reviewed_source = (project / 'package.json').read_bytes()
    accepted = (project / 'latent.dependencies.lock.json').read_bytes()
    changes = []
    from tools.application_dependency_store import DependencyError
    for operation in ('update', 'remove'):
        try:
            authoring.edit(project, operation, identity='outside-qualification-module',
                           version='2.0.0' if operation == 'update' else None)
            try:
                authoring.status(project)
            except DependencyError as error:
                if str(error) != 'dependency-native-lock-drift':
                    raise
            else:
                raise ValueError('changed npm declaration reused the accepted graph')
            if (project / 'latent.dependencies.lock.json').read_bytes() != accepted:
                raise ValueError('npm editing replaced the accepted dependency lock')
            changes.append({'operation': operation, 'staleGraphRejected': True, 'acceptedLockPreserved': True})
        finally:
            (project / 'package.json').write_bytes(reviewed_source)
        if authoring.status(project)['status'] != 'verified':
            raise ValueError('exact reviewed npm declaration restoration did not revive the graph')
    graph = json.loads((project / 'npm-resolved.lock.json').read_bytes())
    selected = {row['location'] for row in graph['nodes'] if row['selected']}
    if not {'node_modules/@jridgewell/trace-mapping', 'node_modules/@jridgewell/resolve-uri',
            'node_modules/@jridgewell/sourcemap-codec', 'node_modules/outside-qualification-module'} <= selected:
        raise ValueError('native npm graph did not capture required application/transitive packages')
    source = project / 'src/main.ts'
    before = source.read_bytes()
    after = b'import { prefix } from "outside-qualification-module";\n' + before
    after = after.replace(b'`Hello, ${clean}!`', b'`${prefix()}${clean}!`')
    if after == before or b'`Hello, ${clean}!`' in after:
        raise ValueError('TypeScript dependency qualification source hook changed')
    source.write_bytes(after)
    if library.resolve(strict=True).parent != outside.resolve(strict=True):
        raise ValueError('qualification cleanup escaped its owned directory')
    shutil.rmtree(library)
    return {'formatVersion': 1, 'thirdParty': '@jridgewell/trace-mapping/0.3.31',
            'transitives': ['@jridgewell/resolve-uri', '@jridgewell/sourcemap-codec'],
            'developerOwned': 'outside-qualification-module/1.0.0', 'resourceDigest': digest(resource),
            'sourceDigest': digest(after), 'offlineOriginals': 'unavailable-after-capture',
            'nativeGraphDigest': digest((project / 'npm-resolved.lock.json').read_bytes()), 'ignoredScripts': ['prepare'],
            'authoringWorkflow': {'commands': ['add', 'lock', 'resolve', 'review-lock', 'dependencies'],
                'nativeLock': native_lock, 'declarationChanges': changes, 'exactReviewedSourceRestored': True}}
