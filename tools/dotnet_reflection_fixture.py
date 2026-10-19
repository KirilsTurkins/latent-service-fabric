"""Ordinary captured managed reflection, explicit trimming roots and AOT refusal."""
from __future__ import annotations

import io
from pathlib import Path
import secrets
import tempfile
import zipfile

from tools import application_dependencies as dependencies
from tools import dotnet_dependency_authoring as authoring
from tools.build_observation import build_environment
from tools.build_snapshot import canonical
from tools.dotnet_application_dependencies import declarations, resolve
from tools.dotnet_guest.compiler import Compiler
from tools.phase2_operator_process import require
from tools.rust_capsule_project import digest, read_file, snapshot
from tools.rust_capsule_build import Commands

DESCRIPTOR = 'reflection/roots.xml'
LOAD_INPUT = 'reflection/load-input.dll'
ROOTS = b'''<linker><assembly fullname="ReflectionInput"><type fullname="OutsideReflectionRoot"><method name="ReflectValue" /></type></assembly></linker>\n'''
LIBRARY = '''using System;
using System.Reflection;
public static class OutsideReflection {
 private static int calls;
 public static string Describe(string request, byte[] originalAssembly) {
  if (++calls != 1) throw new Exception("reflection activation state reused");
  if (request == "dynamic-caught") {
   try { Assembly.Load(originalAssembly); return "unexpected-load"; }
   catch (PlatformNotSupportedException) { return "dynamic-loading-unsupported"; }
  }
  if (request == "dynamic-uncaught") {
   Assembly.Load(originalAssembly); return "unexpected-load";
  }
  var fields = request.Split('|');
  if (fields.Length != 3) throw new ArgumentException("reflection request shape");
  var type = typeof(OutsideReflection).Assembly.GetType(fields[0], throwOnError: true)!;
  var method = type.GetMethod(fields[1], BindingFlags.Public | BindingFlags.Static)
   ?? throw new MissingMethodException();
  return (string)(method.Invoke(null, new object[] { fields[2] })
   ?? throw new Exception("reflected value absent"));
 }
}
public static class OutsideReflectionRoot {
 public static string ReflectValue(string text) { return "descriptor-reflected:" + text; }
}
'''
CASES = (('OutsideReflectionRoot|ReflectValue|first', 'descriptor-reflected:first'),
         ('dynamic-caught', 'dynamic-loading-unsupported'), ('dynamic-uncaught', None),
         ('OutsideReflectionRoot|ReflectValue|fresh', 'descriptor-reflected:fresh'))


BOUNDARY_ROOTS = ROOTS.replace(b'</assembly>', b'<type fullname="OutsideReflectionBoundary">'
    b'<method name="ByRefLikeValue" /></type></assembly>')
BOUNDARY_LIBRARY = LIBRARY + '''
public static class OutsideReflectionBoundary {
 private static int calls;
 private static int BoundaryBodyCalls;
 public static string Describe(string request, byte[] originalAssembly) {
  if (++calls != 1) throw new System.Exception("boundary activation state reused");
  if (request == "jit-caught") {
   if (System.Runtime.CompilerServices.RuntimeFeature.IsDynamicCodeSupported ||
       System.Runtime.CompilerServices.RuntimeFeature.IsDynamicCodeCompiled)
    throw new System.Exception("dynamic code unexpectedly supported");
   try {
    _ = new System.Reflection.Emit.DynamicMethod("OwnedUnsupportedJit", typeof(void), System.Type.EmptyTypes);
    return "unexpected-dynamic-code";
   } catch (System.PlatformNotSupportedException) { return "dynamic-code-unsupported"; }
  }
  if (request == "byref-like-caught") {
   var method = typeof(OutsideReflectionBoundary).GetMethod("ByRefLikeValue",
       System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Static)
       ?? throw new System.MissingMethodException();
   if (!method.ReturnType.IsByRefLike || BoundaryBodyCalls != 0)
    throw new System.Exception("wrong reflected boundary");
   try {
    method.Invoke(null, System.Array.Empty<object>());
    return "unexpected-byref-like-invoke";
   } catch (System.NotSupportedException) {
    if (BoundaryBodyCalls != 0) throw new System.Exception("unrepresentable method body executed");
    return "byref-like-invoke-unsupported";
   }
  }
  return OutsideReflection.Describe(request, originalAssembly);
 }
 public static System.ReadOnlySpan<int> ByRefLikeValue() {
  ++BoundaryBodyCalls;
  return System.ReadOnlySpan<int>.Empty;
 }
}
'''
BOUNDARY_CASES = CASES + (('jit-caught', 'dynamic-code-unsupported'),
    ('byref-like-caught', 'byref-like-invoke-unsupported'),
    ('OutsideReflectionRoot|ReflectValue|after-boundaries', 'descriptor-reflected:after-boundaries'))


def select(project: Path, *, boundaries: bool = False) -> None:
    """Add literal descriptor bytes to the ordinary reviewed application project."""
    require(type(boundaries) is bool, 'reflection-boundaries-boolean')
    roots = BOUNDARY_ROOTS if boundaries else ROOTS
    path = project / 'Capsule.csproj'
    before = read_file(path)
    require(before.count(b'</Project>') == 1 and b'TrimmerRootDescriptor' not in before,
            'reflection-original-project-required')
    target = project / DESCRIPTOR
    target.parent.mkdir(mode=0o700)
    with target.open('xb') as stream:
        stream.write(roots)
    path.write_bytes(before.replace(b'</Project>',
        b'<ItemGroup><TrimmerRootDescriptor Include="reflection/roots.xml" /></ItemGroup></Project>'))
    source = project / 'src/Main.cs'
    raw = read_file(source)
    hook = b'$"Hello, {clean}!"'
    require(raw.count(hook) == 1, 'reflection-original-greeting-required')
    changed = raw.replace(hook,
        b'clean.StartsWith("reflection:", System.StringComparison.Ordinal) '
        b'? Reflect(clean.Substring(11)) : $"Hello, {clean}!"')
    helper = b'''
    private static string Reflect(string request) {
        using var stream = typeof(ApiExportsImpl).Assembly.GetManifestResourceStream("reflection.dynamic-input")
            ?? throw new System.Exception("captured dynamic assembly absent");
        using var output = new System.IO.MemoryStream();
        stream.CopyTo(output);
        return OutsideReflection.Describe(request, output.ToArray());
    }
'''
    if boundaries:
        helper = helper.replace(b'OutsideReflection.Describe', b'OutsideReflectionBoundary.Describe')
    position = changed.rfind(b'}')
    source.write_bytes(changed[:position] + helper + changed[position:])
    selected = declarations(snapshot(project))
    require(selected['trimmingDescriptors'] == [{'attributes': {'Include': DESCRIPTOR}, 'active': True,
            'digest': digest(roots), 'size': len(roots)}], 'reflection-descriptor-not-selected')


def captured_package(lock, identity, version, package):
    rows = lock['artifacts']
    require(len(rows) == 1 and rows[0]['id'] == identity.lower() + '/' + version
            and rows[0]['role'] == 'application' and not rows[0]['dependencies']
            and rows[0]['original'] == {'digest': digest(package), 'size': len(package)}
            and not lock['executableInputs'], 'reflection-exact-local-graph-required')
    return rows[0]


def install(project: Path, outside: Path, tools: Path, *, boundaries: bool = False) -> dict:
    """Build one owned library, resolve/review normally, then remove its originals."""
    from tools.dotnet_guest.entropy_grants import declare
    require(type(boundaries) is bool, 'reflection-boundaries-boolean')
    roots, library_source = (BOUNDARY_ROOTS, BOUNDARY_LIBRARY) if boundaries else (ROOTS, LIBRARY)
    sdk = read_file(project / 'sdk-lock.json')
    declare(project)
    select(project, boundaries=boundaries)
    outside.mkdir(mode=0o700)
    with tempfile.TemporaryDirectory(prefix='reflection-originals-', dir=outside) as temporary:
        owned = Path(temporary)
        library, evidence, feed = (owned / name for name in ('library', 'evidence', 'feed'))
        for path in (library, evidence, feed):
            path.mkdir(mode=0o700)
        (library / 'Library.cs').write_text(library_source, encoding='utf-8')
        (library / 'Library.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
            '<TargetFramework>net10.0</TargetFramework><AssemblyName>ReflectionInput</AssemblyName>'
            '<OutputType>Library</OutputType><Nullable>enable</Nullable><UseSharedCompilation>false</UseSharedCompilation>'
            '<ImportDirectoryBuildProps>false</ImportDirectoryBuildProps>'
            '<ImportDirectoryBuildTargets>false</ImportDirectoryBuildTargets></PropertyGroup></Project>', encoding='utf-8')
        (library / 'global.json').write_bytes(read_file(project / 'global.json'))
        config = library / 'nuget.config'
        config.write_text('<configuration><packageSources><clear /></packageSources></configuration>')
        commands = Commands(library, evidence, build_environment(owned))
        compiler = Compiler(tools, commands, project / 'vendor/lsf', offline=True, captured=True)
        compiler.run('reflection-library', compiler.dotnet, 'build', library / 'Library.csproj', '-c', 'Release',
            '-p:RestoreConfigFile=' + str(config), '-p:NuGetAudit=false', '-nodeReuse:false',
            '-p:UseSharedCompilation=false', '-p:ImportDirectoryBuildProps=false', '-p:ImportDirectoryBuildTargets=false')
        compiler.check_unchanged()
        assembly = read_file(library / 'bin/Release/net10.0/ReflectionInput.dll')
        (project / LOAD_INPUT).write_bytes(assembly)
        declaration = project / 'Capsule.csproj'
        before = read_file(declaration)
        require(before.count(b'</Project>') == 1, 'reflection-original-project-required')
        declaration.write_bytes(before.replace(b'</Project>', b'<ItemGroup><EmbeddedResource '
            b'Include="reflection/load-input.dll" LogicalName="reflection.dynamic-input" /></ItemGroup></Project>'))
        identity, version = 'Outside.Reflection.' + secrets.token_hex(12), '0.3.7'
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name, raw in ((identity + '.nuspec', ('<package><metadata><id>' + identity + '</id><version>'
                    + version + '</version><authors>SDK fixture</authors><description>Ordinary reflection input</description>'
                    '</metadata></package>').encode()), ('lib/net10.0/ReflectionInput.dll', assembly)):
                archive.writestr(zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0)), raw)
        package = stream.getvalue()
        (feed / (identity.lower() + '.' + version + '.nupkg')).write_bytes(package)
        authoring.edit(project, 'add', identity=identity, version=version)
        candidate = owned / 'candidate.json'
        lock = resolve(project, candidate, dotnet=compiler.dotnet, tools=tools,
            policy={'sources': [{'name': 'reflection', 'path': str(feed), 'patterns': [identity]}]})
        row = captured_package(lock, identity, version, package)
        raw = read_file(candidate)
        authoring.review(project, candidate, digest(raw))
        require(authoring.status(project)['status'] == 'verified'
                and read_file(project / dependencies.LOCK) == raw
                and read_file(project / 'sdk-lock.json') == sdk, 'reflection-reviewed-source-required')
        compiler.check_unchanged()
        result = {'formatVersion': 1, 'package': identity.lower(), 'version': version,
            'original': row['original'], 'treeDigest': row['treeDigest'],
            'candidateDigest': digest(raw), 'sdkLockDigest': digest(sdk),
            'descriptor': {'digest': digest(roots), 'size': len(roots)},
            'dynamicAssembly': {'digest': digest(assembly), 'size': len(assembly)},
            'librarySourceDigest': digest(library_source.encode()), 'originalsRemovedBeforeBuild': True,
            'managedPreparation': {'compilerInputsDigest': digest(canonical(compiler.before)),
                'assembly': {'digest': digest(assembly), 'size': len(assembly)}, 'commandCount': len(commands.records)},
            'catalogueRegistration': False, 'executableInputs': []}
    require(not owned.exists(), 'reflection-originals-still-present')
    return result


def probe(client, target, ownership_probe, result, population, *, boundaries: bool = False):
    from tools.rust_capsule_node import assert_value, call, provider_idle, sample, selected_revision
    from tools.rust_dependency_recovery import failed
    require(type(boundaries) is bool, 'reflection-boundaries-boolean')
    cases = BOUNDARY_CASES if boundaries else CASES
    expected_revision = selected_revision(client, target)
    observations = []
    for ordinal, (mode, expected) in enumerate(cases):
        row = call(client, target, 'greeting', 'greet', ['reflection:' + mode], 'dotnet-reflection-' + str(ordinal))
        result['invocations'].append(row)
        if expected is None:
            failed(row, 'guest-trap', target['budget']['memoryBytes'])
        else:
            assert_value(client, row, [{'ok': expected}])
            require(row['processReaped'], 'reflection-client-not-reaped')
        require(row['response']['data'].get('resolvedRevision') == expected_revision,
                'reflection-selected-signed-revision')
        require(int(row['response']['data']['consumption']['outboundRequests']) == 0,
                'reflection-unexpected-outbound')
        result['samples'].append(sample(client, ownership_probe, 'dotnet-reflection-' + str(ordinal), population))
        result['providerIdle'].append(provider_idle(client))
        observations.append({'case': ordinal, 'outcome': 'terminal-trap' if expected is None else expected})
    key = 'dotnetReflectionBoundaries' if boundaries else 'dotnetReflection'
    result[key] = {'status': 'passed', 'cases': observations,
        'scope': 'descriptor-selected reflection, caught dynamic-load refusal, uncaught trap and fresh activation',
        'trapCause': 'not-inferred-from-generic-node-error', 'fullTicketQualification': False}
    if boundaries:
        result[key]['scope'] = 'original four reflection cases plus caught JIT and byref-like Invoke refusal and fresh activation'
