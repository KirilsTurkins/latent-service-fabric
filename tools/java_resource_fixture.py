"""Ordinary transitive JAR resources captured before removing their originals."""
from pathlib import Path
import shutil

from tools import application_dependencies as inputs
from tools.java_application_dependencies import deterministic_jar
from tools.java_capsule_project import create
from tools.java_dependency_authoring import edit, review
from tools.java_dependency_resolution import resolve
from tools.phase2_operator_process import require
from tools.rust_capsule_project import ROOT, digest, inventory, read_file, read_json, snapshot

EXAMPLE = 'examples/java-resource-conformance'
PARENT = 'outside-resource-parent/2026.10.20'
CHILD = 'outside-resource-child/2026.10.20'
DATA = {'outside/resourcechild/utf8.txt': 'Gr\u00fc\u00dfe\0\u96ea\n'.encode(),
        'outside/resourcechild/binary.bin': bytes((0, 255, 128, 65, 13, 10)),
        'outside/resourcechild/empty.bin': b''}
EXPECTED = {'text': 'resource|text=Gr\u00fc\u00dfe\0\u96ea\n|fresh=1',
    'binary': 'resource|binary=00ff80410d0a|fresh=1', 'empty': 'resource|empty=0|fresh=1',
    'missing': 'resource|missing=null|fresh=1',
    'independent': 'resource|independent=2,2|close=other-readable|fresh=1',
    'null': 'resource|null=null-pointer|fresh=1', 'unicode':'resource|unicode=\u96ea|fresh=1'}
APPLICATION_RESOURCE = {'unicode/\u96ea.txt':'\u96ea'.encode()}
MATERIALS = tuple(EXAMPLE+'/'+name for name in ('Capsule.java', 'parent/Library.java', 'child/Data.java'))


def project(directory):
    app = create(directory, 'greeting')
    source = read_file(ROOT/EXAMPLE/'Capsule.java')
    (app/'src/dev/latent/app/Capsule.java').write_bytes(source)
    lock = read_json(app/'sdk-lock.json')
    lock['template'].update(name='java-resource-conformance', sourceDigest=digest(source))
    from tools.build_snapshot import canonical
    (app/'sdk-lock.json').write_bytes(canonical(lock)+b'\n')
    from tools import guest_resources
    (app/'resources').mkdir()
    (app/'resources/utf8-name.txt').write_bytes(APPLICATION_RESOURCE['unicode/\u96ea.txt'])
    (app/guest_resources.MANIFEST).write_bytes(canonical({'schemaVersion':guest_resources.PROFILE,
        'resources':[{'path':'unicode/\u96ea.txt','source':'resources/utf8-name.txt','mediaType':'text/plain'}]})+b'\n')
    return app


def capture(directory: Path, commands):
    app = project(directory/'application')
    original = directory/'outside-originals'; original.mkdir()
    classes = original/'classes'; classes.mkdir()
    sources = original/'sources'; sources.mkdir()
    for name in ('parent/Library.java','child/Data.java'):
        target = sources/name; target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(read_file(ROOT/EXAMPLE/name))
    commands.run('outside-resource-javac', 'javac', '--release', '25', '-proc:none', '-encoding', 'UTF-8',
        '-d', classes, sources/'parent/Library.java', sources/'child/Data.java')
    child = original/'child.jar'; parent = original/'parent.jar'
    child.write_bytes(deterministic_jar({**DATA,
        'outside/resourcechild/Data.class': read_file(classes/'outside/resourcechild/Data.class')}))
    parent.write_bytes(deterministic_jar({'outside/resources/Library.class': read_file(classes/'outside/resources/Library.class')}))
    sdk = read_file(app/'sdk-lock.json')
    original_jars = {CHILD: {'digest':digest(read_file(child)), 'size':child.stat().st_size},
                     PARENT: {'digest':digest(read_file(parent)), 'size':parent.stat().st_size}}
    edit(app, 'add-local', local_id=CHILD, jar=child)
    edit(app, 'add-local', local_id=PARENT, jar=parent, dependencies=(CHILD,))
    candidate = directory/'candidate.json'
    lock = resolve(app, candidate)
    selected = {row['id']:row for row in lock['artifacts']}
    require(all(selected[name]['original'] == identity for name,identity in original_jars.items()),
            'java-resource-actual-jar-identities')
    require(CHILD in selected[PARENT]['dependencies'], 'java-resource-transitive-edge')
    children = [row for row in lock['artifacts'] if row['role'] == 'resource']
    require({row['metadata']['path']:row['original'] for row in children} ==
        {name:{'digest':digest(data),'size':len(data)} for name,data in DATA.items()}
        and all(row['metadata']['jar'] == CHILD for row in children), 'java-resource-transitive-exact-data')
    review(app, candidate, digest(read_file(candidate)))
    verified = inputs.verify_inputs(app, 'java')
    require(verified is not None and read_file(app/'sdk-lock.json') == sdk, 'java-resource-reviewed-closure')
    shutil.rmtree(original)
    require(not original.exists(), 'java-resource-original-inputs-removed')
    return app, {'originalJars':original_jars, 'parent':PARENT, 'child':CHILD,
        'capturedInputIdentity':verified.identity, 'resources':{name:{'digest':digest(data),'size':len(data)} for name,data in DATA.items()},
        'sourceInventory':digest(inventory(snapshot(app))), 'originalInputsRemoved':True,
        'catalogueRegistration':False, 'applicationBridgeInjected':False}
