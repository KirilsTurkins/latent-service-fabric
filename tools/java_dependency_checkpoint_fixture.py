"""Normal captured Commons Lang bytecode and bounded reference/compiler controls."""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import tomllib
import time
from types import SimpleNamespace

from tools.application_dependencies import prepare, verify_inputs
from tools.java_application_dependencies import classpath
from tools.java_capsule_project import create, validate
from tools.java_dependency_authoring import edit, review
from tools.java_dependency_resolution import resolve
from tools.java_guest.compiler import source_module
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_java_fibers import locked_model_classpath
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, read_json, snapshot, write_json

COORDINATE = 'org.apache.commons:commons-lang3:3.14.0'
JAR = 'sha256:7b96bf3ee68949abb5bc465559ac270e0551596fa34523fddf890ec418dde13c'
LIBRARY = 'org.apache.commons.lang3.concurrent.AtomicSafeInitializer'
SOURCE = 'tools/fixtures/java-dependency-checkpoints/Capsule.java'
REFERENCE = 'tools/fixtures/java-dependency-checkpoints/Main.java'
CONTROL = 'sdk/java-guest/fibers/conformance/compiler/DependencyCheckpointControl.java'
ACTIVATION = 'latent:runtime/activation@0.1.0'
CLOCKS = ('latent:clock/monotonic@0.1.0', 'latent:clock/wall@0.1.0')
EXPECTED = {'fresh': 'checkpoint|fresh=1', **{mode:
    'checkpoint|'+mode+'=42|initializations=1|locals=root:child|error=retained|fresh=1'
    for mode in ('dependency', 'monitor')}}


def project(directory: Path) -> Path:
    app = create(directory, 'greeting')
    source = read_file(ROOT/SOURCE)
    (app/'src/dev/latent/app/Capsule.java').write_bytes(source)
    wit = read_file(app/'wit/world.wit')
    require(wit.count(b'world service {') == wit.count(b'greet: func(') == 1,
        'java-checkpoint-original-greeting-world')
    wit = wit.replace(b'world service {', b'world service {\n    import '+ACTIVATION.encode()+b';', 1)
    wit = wit.replace(b'greet: func(', b'greet: async func(', 1)
    (app/'wit/world.wit').write_bytes(wit)
    target = app/'wit/deps/activation-runtime/package.wit'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(read_file(app/'vendor/lsf/wit/platform/activation-runtime/package.wit'))
    lock = read_json(app/'sdk-lock.json')
    lock['template'] = {'name':'java-dependency-checkpoints','sourceDigest':digest(source),'witDigest':digest(wit)}
    (app/'sdk-lock.json').write_bytes((json.dumps(lock,sort_keys=True,separators=(',',':'))+'\n').encode())
    edit(app, 'add', coordinate=COORDINATE)
    validate(snapshot(app))
    return app


def capture(directory: Path, *, gradle='gradle'):
    directory.mkdir()
    app = project(directory/'application')
    sdk = read_file(app/'sdk-lock.json')
    candidate = directory/'candidate.json'
    lock = resolve(app, candidate, gradle=gradle)
    artifacts = [row for row in lock['artifacts'] if row['role']=='application'
        and row['metadata'].get('assetType')!='maven-resolution-metadata']
    require({row['id']:row['original']['digest'] for row in artifacts}=={COORDINATE:JAR},
        'java-checkpoint-exact-original-published-jar')
    review(app, candidate, digest(read_file(candidate)))
    accepted = verify_inputs(app, 'java')
    require(accepted is not None and read_file(app/'sdk-lock.json')==sdk,
        'java-checkpoint-captured-closure-and-sdk')
    work, receipts = fresh(directory/'offline-inputs'), fresh(directory/'receipts')
    closure = prepare(app, work, receipts, 'java')
    jars, selected = classpath(closure, directory/'selected-jars')
    require(len(jars)==1 and len(selected['artifacts'])==1
        and selected['artifacts'][0]['originalDigest']==JAR,
        'java-checkpoint-single-selected-dependency')
    original = work/artifacts[0]['mount']
    require(digest(read_file(original,64*1024**2))==JAR,'java-checkpoint-retained-original-jar')
    closure.check_unchanged()
    report = {'coordinate':COORDINATE,'originalDigest':JAR,'selected':selected,
        'capturedInputIdentity':accepted.identity,'projectInventory':digest(inventory(snapshot(app))),
        'candidateDigest':digest(read_file(candidate)), 'applicationExecutorInjected':False,
        'applicationYieldInserted':False,'librarySourceModified':False}
    write_json(receipts/'capture.json',report)
    return app, jars[0], original, report


def controls(commands, cache: Path, selected: Path, original: Path, output: Path):
    output.mkdir()
    sdk = ROOT/'sdk/java-guest'
    tooling, identities = locked_model_classpath(SimpleNamespace(sdk=sdk,directory=output,
        dependency_cache=cache/'files-2.1'),include_platform=True)
    pins = tomllib.loads(read_file(ROOT/'tools/toolchain.toml').decode())
    java,javac=(Path(shutil.which(name)).resolve(strict=True) for name in ('java','javac'))
    require(java.parent==javac.parent,'java-checkpoint-one-pinned-jdk')
    version=commands.run('checkpoint-reference-jdk-version',java,'--version').decode()
    source_module(sdk/'tools/feasibility.py').verify_version('java-version',version,pins['sdk']['java'])
    reference=output/'reference';reference.mkdir()
    sources=[ROOT/SOURCE,ROOT/REFERENCE,*[sdk/'runtime/dev/latent/guest'/name
        for name in ('Result.java','Unit.java')]]
    commands.run('checkpoint-reference-compile',javac,'--release','25','-proc:none','-encoding','UTF-8',
        '-cp',original,'-d',reference,*sources)
    observed=[]
    remaining=int(min(60,commands.deadline-time.monotonic()))
    require(remaining>=15,'java-checkpoint-original-reference-deadline')
    references=Commands(ROOT,fresh(output/'reference-commands'),commands.environment,
        deadline_seconds=remaining,command_seconds=15)
    try:
        for mode,expected in EXPECTED.items():
            value=references.run('checkpoint-reference-'+mode,java,'-Xmx256m','-cp',
                str(reference)+os.pathsep+str(original),'Main',mode).decode().strip()
            require(value==expected,'java-checkpoint-original-jdk-observable')
            observed.append({'mode':mode,'result':value})
    finally:
        write_json(output/'reference-commands.json',references.records)
    model=output/'model';model.mkdir()
    compiler_sources=sorted((sdk/'fibers/compiler/dev/latent/guest/runtime/compiler').glob('*.java'))
    compiler_sources.append(ROOT/CONTROL)
    before={p.relative_to(ROOT).as_posix():file_identity(p) for p in compiler_sources}
    commands.run('checkpoint-real-plugin-model-compile',javac,'--release','25','-proc:none',
        '-cp',tooling,'-d',model,*compiler_sources)
    value=commands.run('checkpoint-real-plugin-model',java,'-Xmx256m','-cp',
        os.pathsep.join((str(model),tooling,str(selected))),
        'dev.latent.guest.runtime.compiler.DependencyCheckpointControl').decode().strip()
    require(value=='DEPENDENCY_CHECKPOINT_CONTROL PASS actual-published-loop;original-instructions;'
        'unselected-negative;class-initializer-unmanaged-negatives','java-checkpoint-real-plugin-model')
    require(before=={p.relative_to(ROOT).as_posix():file_identity(p) for p in compiler_sources},
        'java-checkpoint-unchanged-model-source')
    report={'status':'reference-and-actual-plugin-model-passed','reference':observed,'referenceCommands':references.records,
        'pluginControl':value,'compilerSources':before,'lockedModelJars':identities,
        'originalJar':file_identity(original),'selectedJar':file_identity(selected),
        'jdk':{'java':file_identity(java),'javac':file_identity(javac),'version':version},
        'componentExecutionPerformed':False,'applicationInitializerExecutedByModelControl':False,
        'garbageCollectionObserved':False}
    write_json(output/'controls.json',report)
    return report
