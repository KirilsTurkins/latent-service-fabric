"""Finite outside dependencies for compiler/init/callback diagnostics.

Capture uses normal reviewed dependency authoring. No application class or
assembly is loaded/executed on the build host and no runtime is injected.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
import re
import shutil
import zipfile

from tools import application_dependencies as inputs
from tools.build_snapshot import canonical
from tools.phase2_operator_process import require
from tools.rust_capsule_project import ROOT, digest, inventory, read_file, snapshot

SOURCE = 'tools/fixtures/compatibility-'
JAVA_IDS = ('outside-diagnostics-library/2026.10.21', 'outside-diagnostics-data/2026.10.21')
DOTNET_IDS = ('Outside.Diagnostics.Library', 'Outside.Diagnostics.Data')
JAVA_CLASSES = ('outside/diagnostics/Library', 'outside/diagnosticsdata/Core')
JAVA_EDGE = b'private static void selectedCompilerEdge() { }'
JAVA_REACHED = b'private static void selectedCompilerEdge() { outside.diagnosticsdata.Core.opaqueNative(); }'
CLOCK = 'latent:clock/monotonic@0.1.0'
WALL = 'latent:clock/wall@0.1.0'
RANDOM = 'latent:random/random@0.1.0'
ACTIVATION = 'latent:runtime/activation@0.1.0'
DECLARATIONS = {'java': (CLOCK, WALL, ACTIVATION), 'dotnet': (CLOCK, WALL, RANDOM, ACTIVATION)}


def project(language: str, directory: Path):
    require(language in {'java', 'dotnet'}, 'compiler-diagnostics-language')
    if language == 'java':
        from tools.java_capsule_project import create, validate
        app = create(directory, 'greeting')
        source, target = 'Capsule.java', 'src/dev/latent/app/Capsule.java'
    else:
        from tools.dotnet_guest.project import create, validate
        app = create(directory, 'greeting')
        source, target = 'Main.cs', 'src/Main.cs'
    body = read_file(ROOT/(SOURCE+language)/source)
    (app/target).write_bytes(body)
    path = app/'wit/world.wit'; wit = read_file(path)
    require(wit.count(b'greet: func(') == wit.count(b'world service {') == 1,
            'compiler-diagnostics-original-entry-world')
    wit = wit.replace(b'greet: func(', b'greet: async func(', 1).replace(b'world service {',
        b'world service {\n    import latent:runtime/activation@0.1.0;', 1)
    if language == 'dotnet':
        # These explicit declarations select the maintained managed Task port;
        # Task.Run must not silently fall back to the legacy untracked profile.
        wit = wit.replace(b'world service {', b'world service {\n    import '+WALL.encode()
            +b';\n    import '+RANDOM.encode()+b';', 1)
        for owner in ('clock', 'random'):
            for name, raw in snapshot(ROOT/'wit/platform'/owner).items():
                target = app/'wit/deps'/owner/name
                target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
    path.write_bytes(wit)
    target_wit = app/'wit/deps/activation-runtime/package.wit'; target_wit.parent.mkdir(parents=True)
    target_wit.write_bytes(read_file(app/'vendor/lsf/wit/platform/activation-runtime/package.wit'))
    lock = json.loads(read_file(app/'sdk-lock.json'))
    lock['template'] = {'name': 'compiler-diagnostics-'+language,
        'sourceDigest': digest(body), 'witDigest': digest(wit)}
    (app/'sdk-lock.json').write_bytes(canonical(lock)+b'\n')
    validate(snapshot(app))
    return app


def counterfactual_java(app: Path):
    """The captured JARs stay identical; add exactly one root reachability edge."""
    path = app/'src/dev/latent/app/Capsule.java'; original = read_file(path)
    require(original == read_file(ROOT/(SOURCE+'java')/'Capsule.java')
        and original.count(JAVA_EDGE) == 1, 'compiler-diagnostics-exact-counterfactual-root')
    accepted = inputs.verify_inputs(app, 'java')
    require(accepted is not None, 'compiler-diagnostics-counterfactual-reviewed-closure')
    path.write_bytes(original.replace(JAVA_EDGE, JAVA_REACHED, 1))
    require(inputs.verify_inputs(app, 'java').identity == accepted.identity,
        'compiler-diagnostics-counterfactual-library-identity')
    return {'sourceBefore': digest(original), 'sourceAfter': digest(read_file(path)),
        'capturedInputIdentity': accepted.identity, 'onlyRootEdgeAdded': True,
        'libraryBytesChanged': False, 'compilerFailureObserved': False}


def java_capture(app: Path, directory: Path, commands):
    from tools.java_application_dependencies import deterministic_jar
    from tools.java_dependency_authoring import edit, review
    from tools.java_dependency_resolution import resolve
    parent = directory.parent.resolve(strict=True)
    directory.mkdir(); sources = directory/'sources'; sources.mkdir()
    classes = directory/'classes'; classes.mkdir()
    source_files = {name: read_file(ROOT/(SOURCE+'java')/name) for name in ('Core.java', 'Library.java')}
    for name, body in source_files.items(): (sources/name).write_bytes(body)
    commands.run('outside-diagnostic-library-javac', 'javac', '--release', '25', '-proc:none',
        '-encoding', 'UTF-8', '-d', classes, sources/'Core.java', sources/'Library.java')
    require(snapshot(sources) == source_files, 'compiler-diagnostics-original-java-source-changed')
    compiled = {}; total = entries = 0
    for path in classes.rglob('*'):
        entries += 1
        require(entries <= 128 and not path.is_symlink(), 'compiler-diagnostics-original-java-class-link-or-count')
        if path.is_dir(): continue
        name = path.relative_to(classes).as_posix()
        require(len(compiled) < 64 and any(re.fullmatch(re.escape(owner)+r'(?:\$[A-Za-z0-9_]+)*\.class', name)
            for owner in JAVA_CLASSES), 'compiler-diagnostics-original-java-class-closure')
        raw = read_file(path, 1024*1024); total += len(raw)
        require(total <= 4*1024*1024, 'compiler-diagnostics-original-java-class-bound')
        compiled[name] = raw
    require(all(name+'.class' in compiled for name in JAVA_CLASSES), 'compiler-diagnostics-original-java-classes')
    identities = {}; sdk = read_file(app/'sdk-lock.json')
    for identity, owner in reversed(tuple(zip(JAVA_IDS, JAVA_CLASSES))):
        jar = directory/(identity.split('/')[0]+'.jar')
        jar.write_bytes(deterministic_jar({name: body for name,body in compiled.items() if name.startswith(owner)}))
        identities[identity] = {'digest': digest(read_file(jar)), 'size': jar.stat().st_size}
        edit(app, 'add-local', local_id=identity, jar=jar,
            dependencies=(JAVA_IDS[1],) if identity == JAVA_IDS[0] else ())
    candidate = directory/'candidate.json'; lock = resolve(app, candidate)
    rows = {row['id']: row for row in lock['artifacts']}
    require(set(rows) == set(JAVA_IDS) and all(rows[key]['original'] == value for key,value in identities.items())
        and rows[JAVA_IDS[0]]['dependencies'] == [JAVA_IDS[1]] and not lock['executableInputs'],
        'compiler-diagnostics-original-transitive-java-closure')
    review(app, candidate, digest(read_file(candidate)))
    accepted = inputs.verify_inputs(app, 'java')
    require(accepted is not None and read_file(app/'sdk-lock.json') == sdk,
        'compiler-diagnostics-reviewed-java-sdk-unchanged')
    remove_originals(directory, parent)
    require(inputs.verify_inputs(app, 'java').identity == accepted.identity,
        'compiler-diagnostics-offline-java-closure')
    return {'originalJars': identities, 'capturedInputIdentity': accepted.identity,
        'originalSource': digest(inventory(source_files)), 'applicationTransportInjected': False,
        'applicationSchedulerInjected': False, 'catalogueEligibilityCheck': False, 'originalInputsRemoved': True}


def remove_originals(directory: Path, expected_parent: Path):
    require(not directory.is_symlink() and directory.resolve(strict=True).parent == expected_parent
        and directory.resolve(strict=True) == directory.absolute() and directory != ROOT
        and ROOT not in directory.parents and directory not in ROOT.parents,
        'compiler-diagnostics-owned-original-directory')
    shutil.rmtree(directory)
    require(not directory.exists(), 'compiler-diagnostics-original-inputs-not-removed')


def dotnet_sources(directory: Path, *, sources: dict[str, bytes] | None = None):
    """Framework-only library projects; their CIL is captured, never host-loaded."""
    directory.mkdir(); child = directory/'child'; child.mkdir()
    if sources is not None:
        require(type(sources) is dict and set(sources) == {'Core.cs', 'Library.cs'}
            and all(type(raw) is bytes and 0 < len(raw) <= 65536 for raw in sources.values()),
            'compiler-diagnostics-fixed-library-source-bound')
    for name, folder in (('Core.cs', child), ('Library.cs', directory)):
        (folder/name).write_bytes(read_file(ROOT/(SOURCE+'dotnet')/name) if sources is None else sources[name])
    common = ('<TargetFramework>net10.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings>'
        '<Nullable>enable</Nullable><EnableDefaultCompileItems>false</EnableDefaultCompileItems>')
    (child/'Data.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'+common
        +'<AssemblyName>'+DOTNET_IDS[1]+'</AssemblyName></PropertyGroup><ItemGroup>'
        '<Compile Include="Core.cs" /></ItemGroup></Project>\n', encoding='utf-8')
    (directory/'Library.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'+common
        +'<AssemblyName>'+DOTNET_IDS[0]+'</AssemblyName></PropertyGroup><ItemGroup>'
        '<Compile Include="Library.cs" /><ProjectReference Include="child/Data.csproj" />'
        '</ItemGroup></Project>\n', encoding='utf-8')
    (directory/'nuget.config').write_bytes(b'<configuration><packageSources><clear /></packageSources></configuration>\n')
    return directory


def dotnet_package(identity: str, assembly: bytes):
    stream = io.BytesIO()
    child = ('<dependencies><group targetFramework="net10.0"><dependency id="'+DOTNET_IDS[1]
        +'" version="[1.0.0]" /></group></dependencies>') if identity == DOTNET_IDS[0] else ''
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(identity+'.nuspec', '<package><metadata><id>'+identity
            +'</id><version>1.0.0</version><authors>SDK diagnostics</authors>'
            '<description>Ordinary transitive constructor and callback</description>'+child+'</metadata></package>')
        archive.writestr('lib/net10.0/'+identity+'.dll', assembly)
    return stream.getvalue()


def dotnet_capture(app: Path, directory: Path, tools: Path, *, deadline: float,
                   sources: dict[str, bytes] | None = None):
    from tools import dotnet_dependency_authoring as authoring
    from tools.dotnet_application_dependencies import resolve
    from tools.dotnet_guest.compiler import Compiler
    from tools.build_observation import build_environment
    from tools.rust_capsule_build import Commands
    import time
    parent = directory.parent.resolve(strict=True)
    directory.mkdir(); library = dotnet_sources(directory/'library', sources=sources)
    (library/'global.json').write_bytes(read_file(app/'global.json'))
    feed = directory/'feed'; feed.mkdir(); evidence = directory/'evidence'; evidence.mkdir()
    original = snapshot(library); sdk = read_file(app/'sdk-lock.json')
    remaining = int(min(900, deadline-time.monotonic()))
    require(remaining >= 120, 'compiler-diagnostics-original-capture-deadline')
    commands = Commands(library, evidence, build_environment(directory),
        deadline_seconds=remaining, command_seconds=120)
    # This finite capture already has an admitted parent. Distribution setup
    # and its loader probes cannot renew the original900s compilation phase.
    compiler_deadline = min(deadline, commands.deadline)
    commands.deadline = compiler_deadline - 5
    commands._parent_deadline = compiler_deadline
    compiler = Compiler(tools, commands, app/'vendor/lsf', offline=True, captured=True)
    compiler.run('outside-diagnostic-library', compiler.dotnet, 'build', library/'Library.csproj', '-c', 'Release',
        '-p:RestoreConfigFile='+str(library/'nuget.config'), '-p:NuGetAudit=false', '-nodeReuse:false',
        '-p:UseSharedCompilation=false', '-p:ImportDirectoryBuildProps=false', '-p:ImportDirectoryBuildTargets=false')
    compiler.check_unchanged()
    require(all(read_file(library/name) == raw for name,raw in original.items()),
        'compiler-diagnostics-original-dotnet-source-changed')
    identities = {}
    for identity, folder in ((DOTNET_IDS[0], library), (DOTNET_IDS[1], library/'child')):
        assembly = read_file(folder/'bin/Release/net10.0'/(identity+'.dll'), 4*1024*1024)
        raw = dotnet_package(identity, assembly)
        (feed/(identity.lower()+'.1.0.0.nupkg')).write_bytes(raw)
        identities[identity] = {'assembly': digest(assembly), 'package': digest(raw)}
    authoring.edit(app, 'add', identity=DOTNET_IDS[0], version='1.0.0')
    candidate = directory/'candidate.json'
    # The selected closure is exactly2 non-SDK packages: version10, restore600,
    # two native content-hash helpers30 each, and original5s cleanup per child.
    require(deadline - time.monotonic() > 700, 'compiler-diagnostics-original-resolver-capture-reserve')
    lock = resolve(app, candidate, dotnet=compiler.dotnet, tools=tools,
        policy={'sources': [{'name': 'outside', 'path': str(feed), 'patterns': list(DOTNET_IDS)}]})
    rows = {row['metadata']['package']: row for row in lock['artifacts']
        if row['metadata'].get('package') in {name.lower() for name in DOTNET_IDS}}
    require(set(rows) == {name.lower() for name in DOTNET_IDS}
        and rows[DOTNET_IDS[1].lower()]['id'] in rows[DOTNET_IDS[0].lower()]['dependencies']
        and all(row['role'] != 'build-tool' for row in lock['artifacts'])
        and all(rows[name.lower()]['original']['digest'] == identity['package'] for name,identity in identities.items()),
        'compiler-diagnostics-original-transitive-dotnet-closure')
    authoring.review(app, candidate, digest(read_file(candidate)))
    accepted = inputs.verify_inputs(app, 'dotnet')
    require(accepted is not None and read_file(app/'sdk-lock.json') == sdk
        and all(read_file(library/name) == raw for name,raw in original.items()),
        'compiler-diagnostics-reviewed-dotnet-sdk-and-source-unchanged')
    remove_originals(directory, parent)
    require(inputs.verify_inputs(app, 'dotnet').identity == accepted.identity,
        'compiler-diagnostics-offline-dotnet-closure')
    return {'originalPackages': identities, 'capturedInputIdentity': accepted.identity,
        'originalSource': digest(inventory(original)), 'applicationSchedulerInjected': False,
        'applicationTransportInjected': False, 'catalogueEligibilityCheck': False, 'originalInputsRemoved': True}
