"""Capture ordinary transitive embedded data without application resource bridges."""
from __future__ import annotations
import json
from pathlib import Path
import shutil

from tools.application_dependencies import LOCK, verify_inputs
from tools.phase2_operator_process import require
from tools.rust_capsule_project import ROOT, digest, inventory, read_file, read_json, snapshot

LANGUAGES = ('go', 'rust', 'typescript')
EXAMPLE = 'examples/embedded-resource-conformance'
DATA = {'text.txt': 'Gr\u00fc\u00dfe\0\u96ea\n'.encode('utf-8'),
        'binary.bin': bytes((0,255,128,65,13,10)), 'empty.txt': b'', 'empty.bin': b''}
MATERIALS = tuple(EXAMPLE+'/'+name for name in ('go/library.go', 'go/data.go',
    'rust/library.rs', 'rust/data.rs', 'typescript/library.mjs', 'typescript/data.mjs'))
PACKAGES = {'go': ('outside.example.test/embedded-resource-library', 'outside.example.test/embedded-resource-data'),
    'rust': ('outside-embedded-resource-library', 'outside-embedded-resource-data'),
    'typescript': ('outside-embedded-resource-library', 'outside-embedded-resource-data')}
COMMON = {'text': 'resource|text=Gr\u00fc\u00dfe\0\u96ea\n|fresh=1',
          'binary': 'resource|binary=00ff80410d0a|fresh=1'}
EXPECTED = {
    'go': {**COMMON, 'empty': 'resource|empty=0+0|eof=1|fresh=1',
        'missing': 'resource|missing=not-exist|fresh=1',
        'independent': 'resource|independent=2,2|close=other-readable|fresh=1',
        'copies': 'resource|copies=independent|fresh=1'},
    'rust': {**COMMON, 'empty': 'resource|empty=0+0|eof=1|fresh=1',
        'independent': 'resource|independent=2,2|drop=other-readable|fresh=1'},
    'typescript': {**COMMON, 'empty': 'resource|empty=0+0|fresh=1',
        'copies': 'resource|copies=independent|fresh=1'}}


def source_project(language: str, directory: Path, outside: Path):
    """Pure file construction; native resolution remains a distinct later step."""
    require(language in LANGUAGES, 'embedded-resource-language')
    if language == 'go':
        from tools.go_capsule_project import create
    elif language == 'rust':
        from tools.rust_capsule_project import create
    else:
        from tools.typescript_guest.project import create
    app = create(directory, 'greeting')
    initial = snapshot(app)
    outside.mkdir(mode=0o700)
    parent, child = outside/'library', outside/'data'
    parent.mkdir(); child.mkdir()
    first, second = PACKAGES[language]
    if language == 'go':
        (parent/'go.mod').write_bytes(f'module {first}\n\ngo 1.27.2\nrequire {second} v0.0.0\n'.encode())
        (child/'go.mod').write_bytes(f'module {second}\n\ngo 1.27.2\n'.encode())
        for target, name in ((parent/'library.go','library.go'),(child/'data.go','data.go')):
            target.write_bytes(read_file(ROOT/EXAMPLE/'go'/name))
        name = 'src/main.go'; marker = b'func Greet(name string) wit.Result[string, string] {'
        original = initial[name]
        require(original.count(b'import (') == original.count(marker) == 1, 'embedded-resource-Go-template')
        updated = original.replace(b'import (', b'import (\n    resource "'+first.encode()+b'"', 1)
        updated = updated.replace(marker, marker+b'\n    if strings.HasPrefix(name, "resources:") { return wit.Ok[string, string](resource.Run(strings.TrimPrefix(name, "resources:"))) }', 1)
        asset_root = child
    elif language == 'rust':
        for target, package in ((parent, first),(child, second)):
            (target/'src').mkdir()
            manifest = f'[package]\nname="{package}"\nversion="0.1.0"\nedition="2021"\nlicense="Apache-2.0"\n'
            if target == parent: manifest += f'[dependencies]\n{second}={{path="../data"}}\n'
            (target/'Cargo.toml').write_bytes(manifest.encode())
        for target, item in ((parent/'src/lib.rs','library.rs'),(child/'src/lib.rs','data.rs')):
            target.write_bytes(read_file(ROOT/EXAMPLE/'rust'/item))
        name = 'src/lib.rs'; marker = b'    let name = name.trim();'
        original = initial[name]
        require(original.count(marker) == 1, 'embedded-resource-Rust-template')
        updated = original.replace(marker, b'    if let Some(mode) = name.strip_prefix("resources:") { return Ok(outside_embedded_resource_library::run(mode)); }\n'+marker, 1)
        asset_root = child/'src'
    else:
        for target, package in ((parent,first),(child,second)):
            manifest = {'name':package,'version':'1.0.0','type':'module','license':'Apache-2.0',
                'exports':{'types':'./index.d.ts','import':'./index.mjs'}}
            if target == parent: manifest['dependencies'] = {second:'file:'+str(child.resolve())}
            (target/'package.json').write_bytes((json.dumps(manifest,indent=2)+'\n').encode())
        for target, item in ((parent/'index.mjs','library.mjs'),(child/'index.mjs','data.mjs')):
            target.write_bytes(read_file(ROOT/EXAMPLE/'typescript'/item))
        (parent/'index.d.ts').write_bytes(b'export function resourceCase(mode: string): string;\n')
        (child/'index.d.ts').write_bytes(b'export function read(mode: string): string;\n')
        name = 'src/main.ts'; marker = b'  greet(name) {'
        original = initial[name]
        require(original.count(marker) == 1, 'embedded-resource-TypeScript-template')
        updated = b"import {resourceCase} from 'outside-embedded-resource-library';\n"+original.replace(marker,
            marker+b"\n    if (name.startsWith('resources:')) return resourceCase(name.slice(10));", 1)
        asset_root = child
    for asset, data in DATA.items(): (asset_root/asset).write_bytes(data)
    (app/name).write_bytes(updated)
    return app, {'language':language,'sourceFile':name,'originalSource':digest(original),
        'selectedSource':digest(updated),'sdkLock':digest(initial['sdk-lock.json']),
        'packages':list(PACKAGES[language]),'data':json.loads(inventory(DATA)),
        'outsideSource':json.loads(inventory(snapshot(outside)))}


def verify_graph(language, lock, app):
    """Check that native selection retained both unseen packages and the edge."""
    first, second = PACKAGES[language]
    if language == 'typescript':
        graph = read_json(app/'npm-resolved.lock.json')
        selected = {row['location'] for row in graph['nodes'] if row['selected']}
        require({'node_modules/'+first,'node_modules/'+second} <= selected,
                'embedded-resource-transitive-npm-selection')
        return
    key = 'module' if language == 'go' else 'package'
    selected = [row for row in lock['artifacts']
        if row['metadata'].get(key) in {first,second} and row['role'] != 'build-tool']
    artifacts = {row['metadata'].get(key):row for row in selected}
    version = 'v0.0.0' if language == 'go' else '0.1.0'
    require(len(selected) == 2 and set(artifacts) == {first,second}
        and all(row['metadata'].get('version') == version for row in selected)
        and artifacts[second]['id'] in artifacts[first]['dependencies'],
            'embedded-resource-transitive-native-selection')
    require(all(row['metadata'].get('package') not in {first,second} or row['role'] != 'build-tool'
        for row in lock['artifacts']), 'embedded-resource-unexpected-outside-executable')


def capture(language, directory, outside, compiler):
    app, record = source_project(language,directory,outside)
    first, second = PACKAGES[language]
    parent, child = outside/'library', outside/'data'
    candidate = app/'target/resource-candidate.json'; candidate.parent.mkdir(exist_ok=True)
    if language == 'go':
        from tools import go_native_authoring as native, go_dependency_authoring as review
        from tools.go_application_dependencies import resolve
        for identity,path in ((first,parent),(second,child)):
            native.edit(app,'add',identity=identity,version='v0.0.0',local=path,go=compiler)
        native.create_lock(app,go=compiler)
        lock = resolve(app,candidate,go=compiler)
    elif language == 'rust':
        from tools import cargo_native_authoring as native, rust_dependency_authoring as review
        from tools.rust_application_dependencies import resolve
        native.author(app,'add',identity=first,version='0.1.0',local=parent,cargo=compiler)
        lock = resolve(app,candidate,cargo=compiler)
    else:
        from tools import typescript_dependency_authoring as review
        from tools.npm_lock_authoring import create_lock
        from tools.typescript_application_dependencies import resolve
        node, npm = compiler
        review.edit(app,'add',identity=first,local=parent)
        create_lock(app,node=node,npm=npm)
        lock = resolve(app,candidate,node=node,npm=npm)
    verify_graph(language,lock,app)
    accepted = read_file(candidate,16*1024**2)
    review.review(app,candidate,digest(accepted))
    verified = verify_inputs(app,language)
    require(verified is not None and read_file(app/LOCK,16*1024**2) == accepted
        and digest(read_file(app/'sdk-lock.json')) == record['sdkLock'], 'embedded-resource-exact-capture-review')
    root = outside.resolve(strict=True)
    require(not outside.is_symlink() and all(not path.is_symlink()
        and path.resolve(strict=True).parent == root for path in (parent,child)), 'embedded-resource-owned-originals')
    for path in (parent,child): shutil.rmtree(path)
    require(verify_inputs(app,language).identity == verified.identity, 'embedded-resource-offline-closure-changed')
    record.update(capturedInputIdentity=verified.identity, candidateDigest=digest(accepted),
        originalsRemoved=True,catalogueRegistration=False,applicationResourceBridge=False,
        applicationCompiledDuringCapture=False)
    return app,record
