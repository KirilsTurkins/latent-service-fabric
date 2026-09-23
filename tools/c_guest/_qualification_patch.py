"""One-use reviewed feature integration, removed before qualifying outputs."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]


def replace(name, old, new):
    path = ROOT / name
    text = path.read_text()
    assert text.count(old) == 1, (name, old)
    path.write_text(text.replace(old, new))


replace('tools/c_guest/project.py', 'import tomllib\n', 'import tomllib\nfrom urllib.parse import urlsplit\n')
replace('tools/c_guest/project.py', "{'formatVersion', 'name', 'version', 'world', 'sources', 'memoryBytes'}",
        "{'formatVersion', 'name', 'version', 'world', 'sources', 'memoryBytes', 'sourceRepository'}")
replace('tools/c_guest/project.py', "    memory = config['memoryBytes']", '''    repository = config['sourceRepository']
    if not isinstance(repository, str) or len(repository) > 2048 or any(c.isspace() or ord(c) < 32 for c in repository):
        raise ProjectError('invalid source repository URI')
    uri = urlsplit(repository)
    if uri.scheme != 'https' or not uri.hostname or uri.username or uri.password or uri.query or uri.fragment or uri.path in ('', '/'):
        raise ProjectError('use an explicit HTTPS source repository without credentials')
    memory = config['memoryBytes']''')
replace('tools/c_guest/project.py', "('recipe', ROOT / 'tools/c_guest')]",
        "('recipe', ROOT / 'tools/c_guest'), ('platform-wit', ROOT / 'wit/platform')]")
replace('tools/c_guest/project.py', "'examples/echo-contract/capsule.json', 'Cargo.toml'):",
        "'examples/echo-contract/capsule.json', 'tools/c_guest_authoring.py', 'Cargo.toml'):")
replace('tools/c_guest/project.py', "'repository': 'https://github.com/KirilsTurkins/latent-service-fabric',",
        "'repository': config['sourceRepository'],")
for path in (ROOT / 'sdk/c-guest/projects').glob('*/c-project.json'):
    value = json.loads(path.read_text())
    value['sourceRepository'] = 'https://github.com/KirilsTurkins/latent-service-fabric'
    path.write_text(json.dumps(value, indent=2) + '\n')
replace('tools/c_guest/compiler.py', '"-Wall", "-Wextra", "-Werror", "-mexec-model=reactor",',
        '"-Wall", "-Wextra", "-Werror", "-g0", "-Wl,--strip-debug", "-mexec-model=reactor",')
replace('tools/c_guest/bindings.py', '''    paths = sorted(source.rglob("*"))
    if any(path.is_symlink() for path in paths):
        raise ValueError("C source trees cannot contain symlinks")
    files = [path for path in paths if path.is_file() and path.suffix == suffix]''', '''    pending, files, seen = [source], [], 0
    while pending:
        directory = pending.pop()
        for path in directory.iterdir():
            seen += 1
            if seen > 1024 or path.is_symlink():
                raise ValueError("C source tree entry bound or symlink violation")
            if path.is_dir():
                pending.append(path)
            elif path.is_file() and path.suffix == suffix:
                files.append(path)
            elif not path.is_file():
                raise ValueError("C source trees require regular files")
    files.sort()''')
replace('tools/c_guest/qualify.py', 'from tools.c_guest.compiler import Compiler, SDK, safe_output',
        'from tools.c_guest.compiler import Compiler, SDK, ROOT, CAPABILITIES, safe_output')
replace('tools/c_guest/qualify.py', '    receipts = {}', '''    capabilities = {}
    for name in CAPABILITIES:
        profile = ROOT / 'tools/toolchain-smoke/examples' / ('guest_' + name)
        document = json.loads((profile / 'profile.json').read_text())
        _, capability_lock = generate(compiler.run, profile, document['world'], output / ('binding-' + name))
        capabilities[name] = capability_lock
    check_lock(SDK / 'capabilities.lock.json', {'formatVersion': 1, 'capabilities': capabilities}, update=update)
    receipts = {}''')
replace('tools/build_guest_capsules.py', '            destination = output / ("c-" + name)', '''            locks = json.loads((ROOT / "sdk/c-guest/capabilities.lock.json").read_text())
            if locks.get("formatVersion") != 1 or set(locks.get("capabilities", {})) != set(CAPABILITIES) or locks["capabilities"][name] != lock:
                raise ValueError("C capability binding drift: " + name)
            destination = output / ("c-" + name)''')
print('Applied source-repository identity, bounded WIT traversal and complete capability binding locks')
