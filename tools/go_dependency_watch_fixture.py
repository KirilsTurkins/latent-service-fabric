"""Original external Go module revisions for the normal signed watch programme."""
import hashlib
import json
from pathlib import Path
import shutil

PRIMARY = 'outside.example.test/watch-primary'
CHILD = 'outside.example.test/watch-child'
PRIMARY_SOURCE = ('package primary\nimport (_ "embed"; child "' + CHILD + '")\n'
    '//go:embed badge.txt\nvar resource string\n'
    'func Answer() uint32 {return child.Add(3)}\nfunc Resource() string {return resource}\n').encode()
RESOURCE = b'captured watch data'


def digest(raw: bytes) -> str:
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def revision(number: int) -> dict:
    if number not in (1, 2):
        raise ValueError('unknown owned watch fixture revision')
    version, increment = ('v0.1.0', 39) if number == 1 else ('v0.1.1', 40)
    return {'primary': {'go.mod': ('module ' + PRIMARY + '\n\ngo 1.27.2\n\nrequire ' + CHILD + ' ' + version +
        '\nreplace ' + CHILD + ' => ../child\n').encode(),
        'primary.go': PRIMARY_SOURCE, 'badge.txt': RESOURCE},
        'child': {'go.mod': ('module ' + CHILD + '\n\ngo 1.27.2\n').encode(),
            'child.go': ('package child\nfunc Add(value uint32) uint32 {return value+' + str(increment) + '}\n').encode()}}


def restore_revision(inputs: dict, number: int) -> None:
    root = Path(inputs['root'])
    if root.is_symlink() or root.resolve(strict=True) != Path(inputs['ownedRoot']):
        raise ValueError('owned Go watch input root changed')
    for name, files in revision(number).items():
        directory = root / name
        if directory.exists() or directory.is_symlink():
            raise ValueError('choose fresh owned Go watch module roots')
        directory.mkdir(mode=0o700)
        for relative, raw in files.items():
            path = directory / relative; path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
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
        raise ValueError('unknown owned Go watch module')
    root = Path(inputs['root']); directory = root / name
    if (root.is_symlink() or root.resolve(strict=True) != Path(inputs['ownedRoot']) or directory.is_symlink()
            or directory.resolve(strict=True).parent != root.resolve(strict=True)):
        raise ValueError('owned Go watch removal escaped its original root')
    shutil.rmtree(directory)


def application_source(*, removed=False) -> str:
    imports = '' if removed else '    "strconv"\n    primary "' + PRIMARY + '"\n'
    body = '"removed/"+name' if removed else 'strconv.Itoa(int(primary.Answer()))+"/"+name+"/"+primary.Resource()'
    return '''package export_examples_greeting_api
import (
    "strings"
    wit "go.bytecodealliance.org/pkg/wit/types"
''' + imports + ''')
var calls uint32
func Greet(name string) wit.Result[string,string] {
    if calls != 0 {return wit.Err[string,string]("activation-state-reused")}
    calls++
    name = strings.TrimSpace(name)
    if len(name)==0 || len(name)>100 {return wit.Err[string,string]("invalid-watch-input")}
    return wit.Ok[string,string](''' + body + ''')
}
'''
