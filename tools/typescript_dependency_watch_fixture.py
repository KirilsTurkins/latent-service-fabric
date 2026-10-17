"""Original external ESM package revisions for normal signed dependency watch."""
import hashlib
import json
from pathlib import Path
import shutil

PRIMARY = 'outside-watch-primary'
CHILD = 'outside-watch-child'
RESOURCE = b'captured watch data'
PRIMARY_SOURCE = b'''import { add } from 'outside-watch-child';
import badge from './badge.txt';
export function answer() { return add(3); }
export function resource() { return badge; }
'''


def digest(raw: bytes) -> str:
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def revision(number: int) -> dict:
    if number not in (1, 2):
        raise ValueError('unknown owned watch fixture revision')
    version, increment = ('1.0.0', 39) if number == 1 else ('1.0.1', 40)
    common = {'version': version, 'type': 'module', 'license': 'Apache-2.0',
        'exports': {'types': './index.d.ts', 'import': './index.mjs', 'default': './index.mjs'},
        'scripts': {'prepare': 'node forbidden.cjs'}}
    primary = {**common, 'name': PRIMARY, 'dependencies': {CHILD: 'file:../child-v' + str(number)}}
    child = {**common, 'name': CHILD}
    return {'primary': {'package.json': (json.dumps(primary, sort_keys=True) + '\n').encode(),
        'index.mjs': PRIMARY_SOURCE, 'badge.txt': RESOURCE,
        'index.d.ts': b'export function answer(): number;\nexport function resource(): string;\n',
        'forbidden.cjs': b'throw new Error("implicit package hooks must not execute");\n'},
        'child': {'package.json': (json.dumps(child, sort_keys=True) + '\n').encode(),
            'index.mjs': ('export function add(value) { return value + ' + str(increment) + '; }\n').encode(),
            'index.d.ts': b'export function add(value: number): number;\n',
            'forbidden.cjs': b'throw new Error("implicit transitive package hooks must not execute");\n'}}


def restore_revision(inputs: dict, number: int) -> None:
    root = Path(inputs['root'])
    if root.is_symlink() or root.resolve(strict=True) != Path(inputs['ownedRoot']):
        raise ValueError('owned TypeScript watch input root changed')
    files_by_package = revision(number)
    if any(Path(inputs[name]).exists() or Path(inputs[name]).is_symlink() for name in ('primary', 'child')):
        raise ValueError('choose fresh owned TypeScript watch package roots')
    for name, files in files_by_package.items():
        directory = root / (name + '-v' + str(number))
        if directory.exists() or directory.is_symlink():
            raise ValueError('choose fresh owned TypeScript watch package roots')
        directory.mkdir(mode=0o700)
        inputs[name] = str(directory)
        for relative, raw in files.items():
            path = directory / relative
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.write_bytes(raw)


def create(application: Path) -> dict:
    root = application.parent / 'outside-watch-inputs'
    root.mkdir(mode=0o700)
    records = {}
    for number in (1, 2):
        for name, files in revision(number).items():
            encoded = json.dumps({relative: digest(raw) for relative, raw in sorted(files.items())},
                sort_keys=True, separators=(',', ':')).encode()
            records[name + '-v' + str(number)] = digest(encoded)
    result = {'root': str(root), 'ownedRoot': str(root.resolve(strict=True)),
        'primary': str(root / 'primary'), 'child': str(root / 'child'), 'inputDigests': records}
    restore_revision(result, 1)
    return result


def remove_original(inputs: dict, name: str) -> None:
    if name not in {'primary', 'child'}:
        raise ValueError('unknown owned TypeScript watch package')
    root = Path(inputs['root'])
    directory = Path(inputs[name])
    if (root.is_symlink() or root.resolve(strict=True) != Path(inputs['ownedRoot']) or directory.is_symlink()
            or directory.name not in {name + '-v1', name + '-v2'}
            or directory.resolve(strict=True).parent != root.resolve(strict=True)):
        raise ValueError('owned TypeScript watch removal escaped its original root')
    shutil.rmtree(directory)


def application_source(*, removed=False) -> str:
    dependency = '' if removed else "import { answer, resource } from 'outside-watch-primary';\n"
    result = '`removed/${clean}`' if removed else '`${answer()}/${clean}/${resource()}`'
    return dependency + '''import type * as Contract from '../generated/interfaces/examples-greeting-api.js';
import { trim, utf8Length } from '../vendor/lsf/sdk/typescript-guest/runtime/text.js';
let calls = 0;
export const api: typeof Contract = {
  greet(name) {
    if (calls++ !== 0) throw 'activation-state-reused';
    const clean = trim(name);
    if (!clean || utf8Length(clean) > 100) throw 'invalid-watch-input';
    return ''' + result + ''';
  },
};
'''
