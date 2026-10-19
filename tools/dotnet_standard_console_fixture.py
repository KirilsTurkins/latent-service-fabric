"""Ordinary Console calls from a captured outside NuGet library and its child."""
from __future__ import annotations

import io
from pathlib import Path
import shutil
import zipfile

from tools import dotnet_dependency_authoring as authoring
from tools.application_dependencies import LOCK
from tools.build_observation import build_environment
from tools.build_snapshot import canonical, digest
from tools.dotnet_application_dependencies import resolve
from tools.dotnet_guest.compiler import Compiler
from tools.dotnet_guest.project import create
from tools.dotnet_guest.runtime import LOG
from tools.phase2_operator_process import require
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, read_json, snapshot

PARENT = 'Outside.Console.Library'
CHILD = 'Outside.Console.Resource'
RESOURCE = 'Gr\u00fc\u00dfe'.encode('utf-8')
CASES = ('initializer', 'formatted', 'stderr', 'utf8', 'invalid', 'incomplete', 'budget', 'empty')

CHILD_SOURCE = '''namespace OutsideConsole;
public static class Resource {
    public static string Read() {
        using var input = typeof(Resource).Assembly.GetManifestResourceStream("outside.message")
            ?? throw new System.Exception("outside resource missing");
        using var reader = new System.IO.StreamReader(input, System.Text.Encoding.UTF8);
        return reader.ReadToEnd();
    }
}
'''
LIBRARY_SOURCE = r'''namespace OutsideConsole;
public static class Library {
    private static readonly int Initialized = Initialize();
    private static int calls;
    private static int Initialize() {
        System.Console.Write("outside initializer: {0}", Resource.Read());
        System.Console.Out.Flush();
        return 1;
    }
    private static string MustFail(System.Action action) {
        try { action(); }
        catch (System.IO.IOException) { return "strict-io-error"; }
        throw new System.Exception("Console silently acknowledged rejected output");
    }
    public static string Run(string mode) {
        if (Initialized != 1 || ++calls != 1 || Resource.Read() != "Gr\u00fc\u00dfe")
            throw new System.Exception("outside initialization/resource/fresh state changed");
        switch (mode) {
        case "initializer": return "initialized-once:" + Resource.Read();
        case "formatted":
            System.Console.Write("outside dependency: {0} {1}", 42, Resource.Read());
            System.Console.WriteLine();
            System.Console.Out.Flush();
            return "formatted:" + Resource.Read();
        case "stderr":
            System.Console.Error.WriteLine("outside dependency error: {0}", Resource.Read());
            System.Console.Error.Flush();
            return "stderr:" + Resource.Read();
        case "utf8":
            using (var stream = System.Console.OpenStandardOutput()) {
                stream.Write(new byte[] { 0x47, 0x72 });
                stream.Write(new byte[] { 0xc3, 0xbc, 0xc3, 0x9f });
                stream.Write(new byte[] { 0x65 });
                stream.Flush();
            }
            return "utf8:" + Resource.Read();
        case "invalid":
            return MustFail(() => {
                using var stream = System.Console.OpenStandardOutput();
                stream.Write(new byte[] { 0xff });
            });
        case "incomplete":
            return MustFail(() => {
                using var stream = System.Console.OpenStandardOutput();
                stream.Write(new byte[] { 0xc3 });
                stream.Write(new byte[] { 0x20 });
                stream.Flush();
            });
        case "budget":
            return MustFail(() => {
                var text = new string('a', 256);
                for (int index = 0; index < 64; ++index) System.Console.Write(text);
                System.Console.Out.Flush();
            });
        case "empty":
            using (var stream = System.Console.OpenStandardOutput()) {
                stream.Write(System.Array.Empty<byte>()); stream.Flush();
            }
            return "empty-accepted";
        case "trap": throw new System.InvalidOperationException("outside requested trap");
        case "fuel": while (true) { calls++; }
        default: throw new System.Exception("unknown outside Console mode");
        }
    }
}
'''
EXPECTED = {
    'initializer': 'initialized-once:Gr\u00fc\u00dfe', 'formatted': 'formatted:Gr\u00fc\u00dfe',
    'stderr': 'stderr:Gr\u00fc\u00dfe', 'utf8': 'utf8:Gr\u00fc\u00dfe',
    'invalid': 'strict-io-error', 'incomplete': 'strict-io-error', 'budget': 'strict-io-error',
    'empty': 'empty-accepted',
}


def declare(project: Path) -> None:
    path = project / 'wit/world.wit'
    before = path.read_text(encoding='utf-8')
    require(before.count('world service {') == 1 and LOG not in before, 'dotnet-Console-world-preimage')
    path.write_text(before.replace('world service {', 'world service {\n    import ' + LOG + ';'),
                    encoding='utf-8', newline='\n')
    for name, data in snapshot(ROOT / 'wit/platform/log').items():
        destination = project / 'wit/deps/log' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('xb') as output: output.write(data)
    config = read_json(project / 'capsule-project.json')
    config['limits']['logBytes'] = 16384
    (project / 'capsule-project.json').write_bytes(canonical(config))


def pack(feed: Path, identity: str, assembly: bytes, *, child: bool) -> str:
    buffer = io.BytesIO()
    dependency = '' if child else ('<dependencies><group targetFramework="net10.0">'
        '<dependency id="' + CHILD + '" version="[1.0.0]" /></group></dependencies>')
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(identity + '.nuspec', '<?xml version="1.0"?><package><metadata><id>' + identity
            + '</id><version>1.0.0</version><authors>SDK qualification</authors>'
            + '<description>Outside immutable Console library</description>' + dependency + '</metadata></package>')
        archive.writestr('lib/net10.0/' + identity + '.dll', assembly)
    data = buffer.getvalue()
    (feed / (identity.lower() + '.1.0.0.nupkg')).write_bytes(data)
    return digest(data)


def prepare(output: Path, outside: Path, tools: Path) -> tuple[Path, dict]:
    project = create(output, 'greeting')
    declare(project)
    outside.mkdir(mode=0o700)
    library, evidence, feed = (outside / name for name in ('library', 'evidence', 'feed'))
    for directory in (library, evidence, feed): directory.mkdir()
    child = library / 'child'; child.mkdir()
    (child / 'Resource.cs').write_text(CHILD_SOURCE, encoding='utf-8')
    (child / 'message.txt').write_bytes(RESOURCE)
    properties = ('<PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Library</OutputType>'
        '<Nullable>enable</Nullable><UseSharedCompilation>false</UseSharedCompilation>'
        '<ImportDirectoryBuildProps>false</ImportDirectoryBuildProps>'
        '<ImportDirectoryBuildTargets>false</ImportDirectoryBuildTargets></PropertyGroup>')
    (child / 'Child.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk">' + properties
        + '<PropertyGroup><AssemblyName>' + CHILD + '</AssemblyName></PropertyGroup><ItemGroup>'
        '<EmbeddedResource Include="message.txt" LogicalName="outside.message" /></ItemGroup></Project>')
    (library / 'Library.cs').write_text(LIBRARY_SOURCE, encoding='utf-8')
    (library / 'Library.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk">' + properties
        + '<PropertyGroup><AssemblyName>' + PARENT + '</AssemblyName></PropertyGroup><ItemGroup>'
        '<Compile Remove="child/**" /><ProjectReference Include="child/Child.csproj" /></ItemGroup></Project>')
    (library / 'nuget.config').write_text('<configuration><packageSources><clear /></packageSources></configuration>')
    (library / 'global.json').write_bytes((project / 'global.json').read_bytes())
    original = {name: digest(data) for name, data in snapshot(library).items()}
    # Only these reviewed SDK-owned pure managed sources execute in preparation.
    # Application dependencies still require the normal resolver and exact review.
    commands = Commands(library, evidence, build_environment(outside))
    compiler = Compiler(tools, commands, project / 'vendor/lsf', offline=True, captured=True)
    compiler.run('outside-Console-library', compiler.dotnet, 'build', library / 'Library.csproj', '-c', 'Release',
        '-p:RestoreConfigFile=' + str(library / 'nuget.config'), '-p:NuGetAudit=false', '-nodeReuse:false',
        '-p:UseSharedCompilation=false', '-p:ImportDirectoryBuildProps=false', '-p:ImportDirectoryBuildTargets=false')
    compiler.check_unchanged()
    assemblies = {identity: (directory / 'bin/Release/net10.0' / (identity + '.dll')).read_bytes()
                  for identity, directory in ((PARENT, library), (CHILD, child))}
    packages = {identity: pack(feed, identity, assembly, child=identity == CHILD)
                for identity, assembly in assemblies.items()}
    source = project / 'src/Main.cs'
    before = source.read_text(encoding='utf-8')
    opening = '    public static Result<string, string> Greet(string name)\n    {'
    require(before.count(opening) == 1, 'dotnet-Console-greeting-preimage')
    source.write_text(before.replace(opening, opening + '\n        if (name.StartsWith("console:", '
        'System.StringComparison.Ordinal))\n            return Result<string, string>.Ok('
        'OutsideConsole.Library.Run(name.Substring(8)));'), encoding='utf-8', newline='\n')
    authoring.edit(project, 'add', identity=PARENT, version='1.0.0')
    candidate = project / 'target/console-candidate.json'; candidate.parent.mkdir(exist_ok=True)
    lock = resolve(project, candidate, dotnet=compiler.dotnet, tools=tools,
        policy={'sources': [{'name': 'outside', 'path': str(feed), 'patterns': [PARENT, CHILD]}]})
    require(authoring.review(project, candidate, digest(candidate.read_bytes()))['status'] == 'reviewed'
            and authoring.status(project)['status'] == 'verified', 'dotnet-Console-exact-native-review')
    require({PARENT.lower(), CHILD.lower()} <= {row['metadata']['package'] for row in lock['artifacts']}
            and all(row['role'] != 'build-tool' for row in lock['artifacts']),
            'dotnet-Console-pure-transitive-capture')
    for directory in (library, feed):
        require(directory.resolve(strict=True).parent == outside.resolve(strict=True), 'dotnet-Console-owned-cleanup')
        shutil.rmtree(directory)
    return project, {'schemaVersion': 'latent.dotnet.Console.fixture.v1', 'originalFiles': original,
        'assemblies': {identity: digest(data) for identity, data in assemblies.items()},
        'packages': packages, 'dependencyLock': digest((project / LOCK).read_bytes()),
        'originalLibraryAndFeedRemoved': not library.exists() and not feed.exists(),
        'resourceDigest': digest(RESOURCE), 'declaredLog': LOG, 'ordinaryCalls': [
            'Console.Write', 'Console.WriteLine', 'Console.Error.WriteLine', 'Console.Out.Flush',
            'Console.OpenStandardOutput', 'Stream.Write', 'Stream.Flush'], 'cases': list(CASES)}
