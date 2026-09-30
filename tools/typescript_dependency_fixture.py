"""Real npm/resource qualification fixture, separate from application routing."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile

from tools.application_dependencies import LOCK
from tools.build_observation import build_environment
from tools.build_process import run_bounded
from tools.build_snapshot import canonical, digest
from tools.typescript_application_dependencies import resolve


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
    (project / 'package.json').write_text(json.dumps({'name': 'qualification-application', 'version': '1.0.0',
        'private': True, 'type': 'module', 'dependencies': {'outside-qualification-module':
            'file:' + os.path.relpath(library, project).replace('\\', '/')}}, indent=2) + '\n', encoding='utf-8')
    node = Path(shutil.which('node') or 'missing-node')
    npm = (node.parent / 'node_modules/npm/bin/npm-cli.js' if os.name == 'nt' else Path(shutil.which('npm') or 'missing-npm').resolve())
    with tempfile.TemporaryDirectory(prefix='lsf-npm-fixture-lock-') as temporary:
        temporary = Path(temporary)
        environment = build_environment(temporary)
        environment.update(HOME=str(temporary / 'home'), USERPROFILE=str(temporary / 'home'),
            NPM_CONFIG_CACHE=str(temporary / 'cache'), NPM_CONFIG_USERCONFIG=str(temporary / 'empty.npmrc'),
            NPM_CONFIG_GLOBALCONFIG=str(temporary / 'global-empty.npmrc'), NPM_CONFIG_IGNORE_SCRIPTS='true')
        (temporary / 'empty.npmrc').write_bytes(b'')
        (temporary / 'global-empty.npmrc').write_bytes(b'')
        run_bounded([str(node), str(npm), 'install', '--package-lock-only', '--ignore-scripts', '--install-links=true',
            '--bin-links=false', '--no-audit', '--no-fund'], project, environment, 120, 1024 * 1024)
    candidate = project / 'target/qualification.candidate.json'
    candidate.parent.mkdir()
    lock = resolve(project, candidate, node=node, npm=npm)
    (project / LOCK).write_bytes(canonical(lock) + b'\n')
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
            'nativeGraphDigest': digest((project / 'npm-resolved.lock.json').read_bytes()), 'ignoredScripts': ['prepare']}
