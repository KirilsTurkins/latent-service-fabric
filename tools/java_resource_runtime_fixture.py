"""Ordinary two-JAR resources retained through the maintained Java timer profile."""
from pathlib import Path
import re
import shutil

from tools import application_dependencies as inputs
from tools.build_snapshot import canonical
from tools.java_application_dependencies import deterministic_jar
from tools.java_capsule_project import create, validate
from tools.java_dependency_authoring import edit, review
from tools.java_dependency_resolution import resolve
from tools.phase2_operator_process import require
from tools.rust_capsule_project import ROOT, digest, inventory, read_file, read_json, snapshot

EXAMPLE = 'examples/java-resource-runtime'
PARENT = 'outside-resource-runtime/2026.10.20'
CHILD = 'outside-resource-runtime-data/2026.10.20'
CLASSES = ('outside/resourceruntime/Library', 'outside/resourceruntimedata/Data')
DATA = {'outside/resourceruntimedata/utf8.txt': 'Gr\u00fc\u00dfe\0\u96ea\n'.encode(),
        'outside/resourceruntimedata/binary.bin': bytes((0, 255, 128, 65, 13, 10)),
        'outside/resourceruntimedata/empty.bin': b''}
MATERIALS = tuple(EXAMPLE+'/'+name for name in ('Capsule.java', 'parent/Library.java', 'child/Data.java'))
CAPABILITIES = ('latent:clock/monotonic@0.1.0', 'latent:clock/wall@0.1.0',
                'latent:random/random@0.1.0', 'latent:log/log@0.1.0',
                'latent:runtime/activation@0.1.0')
EXPECTED = {'parallel': 'resource-runtime|parallel=255:255|callbacks=2|logs=accepted:sticky-error|fresh=1',
            'fresh': 'resource-runtime|fresh=00ff80410d0a|empty=0|fresh=1',
            'clear': 'resource-runtime|clear=00ff80410d0a|empty=0|fresh=1',
            'callback-error':'resource-runtime|callback-error=IllegalStateException|fresh=1'}


def compiled_classes(directory):
    # javac's ordinary anonymous/member classes contain '$'; these are bounded
    # binary outputs, not portable application source paths.
    expected = tuple(re.compile(re.escape(name)+r'(?:\$[A-Za-z0-9_]+)*\.class\Z') for name in CLASSES)
    directories = {'outside', 'outside/resourceruntime', 'outside/resourceruntimedata'}
    pending = [directory]; files = {}; total = entries = 0
    while pending:
        for path in pending.pop().iterdir():
            entries += 1
            require(entries <= 64 and not path.is_symlink(), 'java-resource-runtime-class-bound-or-link')
            name = path.relative_to(directory).as_posix()
            if path.is_dir():
                require(name in directories, 'java-resource-runtime-foreign-class-directory')
                pending.append(path)
            else:
                require(any(pattern.fullmatch(name) for pattern in expected), 'java-resource-runtime-foreign-class')
                raw = read_file(path, 1024*1024); total += len(raw)
                require(total <= 4*1024*1024, 'java-resource-runtime-class-byte-bound')
                files[name] = raw
    require(all(name+'.class' in files for name in CLASSES), 'java-resource-runtime-original-classes-required')
    return dict(sorted(files.items()))


def project(directory):
    app = create(directory, 'greeting')
    source = read_file(ROOT/MATERIALS[0])
    (app/'src/dev/latent/app/Capsule.java').write_bytes(source)
    wit = read_file(app/'wit/world.wit')
    require(wit.count(b'world service {') == 1, 'java-resource-runtime-original-world')
    require(wit.count(b'greet: func(') == 1, 'java-resource-runtime-original-entry-signature')
    wit = wit.replace(b'greet: func(', b'greet: async func(', 1)
    extra = ''.join('    import '+name+';\n' for name in CAPABILITIES[2:]).encode()
    wit = wit.replace(b'world service {', b'world service {\n'+extra, 1)
    (app/'wit/world.wit').write_bytes(wit)
    for folder in ('random', 'log', 'activation-runtime'):
        path = app/'wit/deps'/folder/'package.wit'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(read_file(app/'vendor/lsf/wit/platform'/folder/'package.wit'))
    descriptor = read_json(app/'capsule-project.json')
    descriptor['limits']['logBytes'] = 256
    (app/'capsule-project.json').write_bytes(canonical(descriptor)+b'\n')
    lock = read_json(app/'sdk-lock.json')
    lock['template'] = {'name': 'java-resource-runtime', 'sourceDigest': digest(source), 'witDigest': digest(wit)}
    (app/'sdk-lock.json').write_bytes(canonical(lock)+b'\n')
    validate(snapshot(app))
    return app


def capture(directory: Path, commands, *, late_completion=False):
    require(type(late_completion) is bool, 'java-resource-late-selector')
    app = project(directory/'application')
    original = directory/'outside-originals'; original.mkdir()
    classes = original/'classes'; classes.mkdir()
    sources = original/'sources'; sources.mkdir()
    originals = {}
    for name in ('parent/Library.java', 'child/Data.java'):
        target = sources/name; target.parent.mkdir(parents=True, exist_ok=True)
        selected = ('tools/fixtures/java-resource-late/Library.java'
            if late_completion and name == 'parent/Library.java' else EXAMPLE+'/'+name)
        raw = read_file(ROOT/selected); target.write_bytes(raw)
        originals[name] = raw
    commands.run('outside-resource-runtime-javac', 'javac', '--release', '25', '-proc:none', '-encoding', 'UTF-8',
        '-d', classes, sources/'parent/Library.java', sources/'child/Data.java')
    require(all(read_file(sources/name) == raw for name,raw in originals.items()),
            'java-resource-runtime-original-library-source-changed')
    # Retain every ordinary nested TimerTask/state class emitted by javac.
    compiled = compiled_classes(classes)
    child = original/'child.jar'; parent = original/'parent.jar'
    child.write_bytes(deterministic_jar({**DATA,
        **{name:raw for name,raw in compiled.items() if name.startswith(CLASSES[1])}}))
    parent.write_bytes(deterministic_jar({name:raw for name,raw in compiled.items() if name.startswith(CLASSES[0])}))
    sdk = read_file(app/'sdk-lock.json')
    identities = {key:{'digest':digest(read_file(path)), 'size':path.stat().st_size}
                  for key,path in ((CHILD,child),(PARENT,parent))}
    edit(app, 'add-local', local_id=CHILD, jar=child)
    edit(app, 'add-local', local_id=PARENT, jar=parent, dependencies=(CHILD,))
    candidate = directory/'candidate.json'; lock = resolve(app, candidate)
    selected = {row['id']:row for row in lock['artifacts']}
    require(all(selected[key]['original'] == value for key,value in identities.items())
        and CHILD in selected[PARENT]['dependencies'], 'java-resource-runtime-transitive-jar-identity')
    resources = [row for row in lock['artifacts'] if row['role'] == 'resource']
    require({row['metadata']['path']:row['original'] for row in resources} ==
        {name:{'digest':digest(raw),'size':len(raw)} for name,raw in DATA.items()}
        and all(row['metadata']['jar'] == CHILD for row in resources), 'java-resource-runtime-exact-resources')
    require(not lock['executableInputs'], 'java-resource-runtime-no-processor-or-executable')
    review(app, candidate, digest(read_file(candidate)))
    accepted = inputs.verify_inputs(app, 'java')
    require(accepted is not None and read_file(app/'sdk-lock.json') == sdk,
            'java-resource-runtime-reviewed-closure')
    shutil.rmtree(original)
    require(not original.exists(), 'java-resource-runtime-original-inputs-not-removed')
    return app, {'originalJars':identities, 'parent':PARENT, 'child':CHILD,
        'capturedInputIdentity':accepted.identity, 'sourceInventory':digest(inventory(snapshot(app))),
        'resources':{name:{'digest':digest(raw),'size':len(raw)} for name,raw in DATA.items()},
        'originalInputsRemoved':True, 'applicationSchedulerInjected':False,
        'applicationTransportInjected':False, 'catalogueRegistration':False}
