"""Outside NuGet library and real transitive code/resource qualification."""
from __future__ import annotations
import io
import json
from pathlib import Path
import shutil
import zipfile

from tools.application_dependencies import LOCK
from tools.build_observation import build_environment
from tools.build_snapshot import canonical, digest
from tools.dotnet_application_dependencies import resolve, package_name
from tools.dotnet_guest.compiler import Compiler
from tools.rust_capsule_build import Commands


def install(project: Path, outside: Path, tools: Path, *, identity='Outside.Qualification.Library', serialization='memorypack') -> dict:
    package_name(identity)
    if serialization == 'memorypack':
        dependency, version = 'MemoryPack.Core', '1.21.4'
        application = 'MemoryPack'
        transitive = ['MemoryPack.Core', 'MemoryPack.Generator']
    elif serialization == 'smartformat':
        dependency, version = 'SmartFormat.Extensions.Newtonsoft.Json', '3.6.1'
        application = dependency
        transitive = ['SmartFormat', 'Newtonsoft.Json', 'ZString']
    else:
        raise ValueError('unknown SDK qualification fixture')
    from tools.dotnet_guest.entropy_grants import declare
    declare(project)
    outside.mkdir(mode=0o700)
    library, evidence, feed = (outside / name for name in ('developer-library', 'compiler-evidence', 'local-feed'))
    for root in (library, evidence, feed):
        root.mkdir()
    resource = b'Hello, '
    (library / 'prefix.txt').write_bytes(resource)
    (library / 'message.txt').write_text('Gr\u00fc\u00dfe', encoding='utf-8')
    (library / 'data.bin').write_bytes(bytes((0, 255, 65, 128)))
    (library / 'Library.cs').write_text('''namespace DeveloperInput;
public static class LibraryPrefix {
    private static readonly string Initialization = Read();
    private static int calls;
    private static byte[][]? retained;
    private static byte[] ReadBytes(string name) {
        using var stream = typeof(LibraryPrefix).Assembly.GetManifestResourceStream(name)
            ?? throw new System.Exception("captured developer resource missing");
        using var output = new System.IO.MemoryStream();
        stream.CopyTo(output);
        return output.ToArray();
    }
    private static bool CatchAndFinally() {
        bool caught = false, finalized = false;
        try { throw new System.InvalidOperationException("ordinary captured library exception"); }
        catch (System.InvalidOperationException error) { caught = error.Message == "ordinary captured library exception"; }
        finally { finalized = true; }
        return caught && finalized;
    }
    public static void Exercise(string mode) {
        var message = System.Text.Encoding.UTF8.GetString(ReadBytes("developer.message"));
        var data = ReadBytes("developer.binary");
        if (calls != 0 || Initialization != "Hello, " || message != "Gr\\u00fc\\u00dfe" || data.Length != 4 ||
            data[0] != 0 || data[1] != 255 || data[2] != 65 || data[3] != 128 || !CatchAndFinally())
            throw new System.Exception("captured resources, initialization, finally or fresh state changed");
        calls++;
        if (mode == "exception") throw new System.InvalidOperationException("captured library requested failure");
        if (mode == "memory") {
            retained = new byte[32][];
            for (int index = 0; index < retained.Length; ++index) retained[index] = new byte[16 * 1024 * 1024];
            System.GC.KeepAlive(retained);
            throw new System.Exception("captured library allocation unexpectedly fit original budget");
        }
        if (mode == "spin") while (true) { calls++; }
    }
    public static string Read() {
        using var input = typeof(LibraryPrefix).Assembly.GetManifestResourceStream("developer.prefix")
            ?? throw new System.Exception("captured developer resource missing");
        using var reader = new System.IO.StreamReader(input, System.Text.Encoding.UTF8);
        return reader.ReadToEnd();
    }
}
''', encoding='utf-8')
    (library / 'Library.csproj').write_text('''<Project Sdk="Microsoft.NET.Sdk">
<PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Library</OutputType>
<Nullable>enable</Nullable><UseSharedCompilation>false</UseSharedCompilation>
<ImportDirectoryBuildProps>false</ImportDirectoryBuildProps><ImportDirectoryBuildTargets>false</ImportDirectoryBuildTargets></PropertyGroup>
<ItemGroup><EmbeddedResource Include="prefix.txt" LogicalName="developer.prefix" />
<EmbeddedResource Include="message.txt" LogicalName="developer.message" /><EmbeddedResource Include="data.bin" LogicalName="developer.binary" /></ItemGroup>
</Project>''', encoding='utf-8')
    (library / 'nuget.config').write_text('<configuration><packageSources><clear /></packageSources></configuration>')
    (library / 'global.json').write_bytes((project / 'global.json').read_bytes())
    # This SDK-owned fixture builds only its reviewed pure managed library.
    # No application package, analyzer or target executes in this preparation.
    # The maintained qualifier places application projects and this reviewed
    # library in sibling trees. Capture the library's owned preparation tree;
    # its build must not mount the application or the enclosing output root.
    commands = Commands(library, evidence, build_environment(outside))
    compiler = Compiler(tools, commands, project / 'vendor/lsf', offline=True, captured=True)
    compiler.run('developer-library-build', compiler.dotnet, 'build', library / 'Library.csproj', '-c', 'Release',
        '-p:RestoreConfigFile=' + str(library / 'nuget.config'), '-p:NuGetAudit=false', '-nodeReuse:false',
        '-p:UseSharedCompilation=false', '-p:ImportDirectoryBuildProps=false', '-p:ImportDirectoryBuildTargets=false')
    compiler.check_unchanged()
    assembly = (library / 'bin/Release/net10.0/Library.dll').read_bytes()
    original = io.BytesIO()
    with zipfile.ZipFile(original, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(identity + '.nuspec', '''<?xml version="1.0"?><package><metadata><id>''' + identity + '''</id>
<version>1.0.0</version><authors>SDK qualification</authors><description>Developer-owned immutable input</description>
<dependencies><group targetFramework="net10.0"><dependency id="''' + dependency + '''" version="[''' + version + ''']" /></group></dependencies>
</metadata></package>''')
        archive.writestr('lib/net10.0/Library.dll', assembly)
    (feed / (identity.lower() + '.1.0.0.nupkg')).write_bytes(original.getvalue())
    source = project / 'src/Main.cs'
    before = source.read_bytes()
    after = before.replace(b'$"Hello, {clean}!"', b'Prefix(clean) + clean + "!"')
    if after == before:
        raise ValueError('C# dependency qualification source hook changed')
    if serialization == 'memorypack':
        helper = b'''
    private static string Prefix(string mode) {
        DeveloperInput.LibraryPrefix.Exercise(mode);
        var resource = DeveloperInput.LibraryPrefix.Read();
        var encoded = MemoryPack.MemoryPackSerializer.Serialize(new CapturedPayload { Prefix = resource });
        var restored = MemoryPack.MemoryPackSerializer.Deserialize<CapturedPayload>(encoded)
            ?? throw new System.Exception("generated payload missing");
        if (restored.Prefix != resource || resource != "Hello, ")
            throw new System.Exception("generated serialization/resource result mismatch");
        return restored.Prefix;
    }
'''
    else:
        helper = b'''
    private static string Prefix(string mode) {
        DeveloperInput.LibraryPrefix.Exercise(mode);
        var input = Newtonsoft.Json.Linq.JObject.Parse("{\\"prefix\\":\\"Hello, \\"}");
        var parsed = (string?)input["prefix"];
        if (parsed != "Hello, ") throw new System.Exception("actual transitive JSON result mismatch");
        var formatter = new SmartFormat.SmartFormatter()
            .AddExtensions(new SmartFormat.Extensions.NewtonsoftJsonSource(), new SmartFormat.Extensions.DefaultSource())
            .AddExtensions(new SmartFormat.Extensions.DefaultFormatter());
        if (formatter.Format("{prefix}", input) != parsed) throw new System.Exception("actual third-party formatter result mismatch");
        if (Cysharp.Text.ZString.Concat("Hel", "lo, ") != parsed) throw new System.Exception("actual transitive text result mismatch");
        var resource = DeveloperInput.LibraryPrefix.Read();
        if (resource != parsed) throw new System.Exception("developer assembly resource result mismatch");
        return resource;
    }
'''
    index = after.rfind(b'}')
    after = after[:index] + helper + after[index:]
    if serialization == 'memorypack':
        after += b'''
[MemoryPack.MemoryPackable]
public partial class CapturedPayload {
    public string Prefix { get; set; } = "";
}
'''
    source.write_bytes(after)
    from tools import dotnet_dependency_authoring as authoring
    authoring.edit(project, 'add', identity=identity, version='1.0.0')
    authoring.edit(project, 'add', identity=application, version=version)
    candidate = project / 'target/qualification.candidate.json'
    candidate.parent.mkdir(exist_ok=True)
    lock = resolve(project, candidate, dotnet=compiler.dotnet, tools=tools,
        policy={'sources': [{'name': 'developer', 'path': str(feed), 'patterns': [identity]}]})
    reviewed = authoring.review(project, candidate, digest(candidate.read_bytes()))
    if reviewed['status'] != 'reviewed' or authoring.status(project)['status'] != 'verified':
        raise ValueError('normal NuGet exact review did not accept the captured graph')
    # Actual captured native graph: declaration edits must preserve the accepted
    # lock while making it unusable; only exact reviewed source restoration revives it.
    declaration = project / 'Capsule.csproj'
    reviewed_source, reviewed_lock = declaration.read_bytes(), (project / LOCK).read_bytes()
    controls = []
    from tools.application_dependency_store import DependencyError
    for operation, selected_version in (('update', '2.0.0'), ('remove', None)):
        try:
            authoring.edit(project, operation, identity=identity, version=selected_version)
            try:
                authoring.status(project)
            except DependencyError as error:
                if str(error) != 'dependency-native-lock-drift':
                    raise
            else:
                raise ValueError('changed NuGet declaration reused an accepted native graph')
            if (project / LOCK).read_bytes() != reviewed_lock:
                raise ValueError('NuGet dependency editing replaced the accepted lock')
            controls.append({'operation': operation, 'acceptedLockPreserved': True,
                'staleGraphRejected': True, 'compilerExecution': False})
        finally:
            declaration.write_bytes(reviewed_source)
        if authoring.status(project)['status'] != 'verified':
            raise ValueError('exact reviewed NuGet declarations did not restore verification')
    selected = {row['metadata']['package'] for row in lock['artifacts']}
    if not {identity.lower(), application.lower(), *(name.lower() for name in transitive)} <= selected:
        raise ValueError('native NuGet qualification graph did not capture actual transitive/local packages')
    if serialization == 'memorypack' and not any(row['role'] == 'build-tool'
            and row['metadata'].get('package') == 'memorypack.generator' for row in lock['artifacts']):
        raise ValueError('native NuGet selection did not capture the actual executable serializer generator')
    if library.resolve(strict=True).parent != outside.resolve(strict=True) or feed.resolve(strict=True).parent != outside.resolve(strict=True):
        raise ValueError('qualification cleanup escaped its owned dependency directory')
    shutil.rmtree(library)
    shutil.rmtree(feed)
    return {'formatVersion': 1, 'thirdParty': application + '/' + version,
        'independentApplicationSelections': [identity + '/1.0.0', application + '/' + version],
        'transitives': transitive, 'developerOwned': identity + '/1.0.0',
        'generatedSerialization': {'generator': 'MemoryPack.Generator/1.21.4', 'type': 'CapturedPayload',
            'ordinaryCalls': ['MemoryPackSerializer.Serialize', 'MemoryPackSerializer.Deserialize']} if serialization == 'memorypack' else None,
        'resourceDigest': digest(resource), 'managedAssemblyDigest': digest(assembly),
        'recoveryCases': ['exception', 'memory', 'spin', 'normal-catch-finally', 'resource-initialization', 'fresh-state'],
        'resourceDigests': {'message.txt': digest('Gr\u00fc\u00dfe'.encode()),
                            'data.bin': digest(bytes((0, 255, 65, 128)))},
        'declaredNoncryptoEntropy': 'latent:random/random@0.1.0',
        'sourceDigest': digest(source.read_bytes()), 'offlineOriginals': 'unavailable-after-capture',
        'nativeGraphDigest': digest((project / 'nuget-resolved.lock.json').read_bytes()),
        'preparationCommands': commands.records,
        'authoringWorkflow': {'commands': ['add', 'resolve', 'review-lock', 'dependencies'],
            'exactCandidateDigest': reviewed['candidateDigest'], 'declarationChanges': controls,
            'exactReviewedSourceRestored': True, 'acceptedLockDigest': digest(reviewed_lock)}}
