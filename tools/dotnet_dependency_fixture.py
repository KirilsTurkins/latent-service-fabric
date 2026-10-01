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


def install(project: Path, outside: Path, tools: Path, *, identity='Outside.Qualification.Library') -> dict:
    package_name(identity)
    outside.mkdir(mode=0o700)
    library, evidence, feed = (outside / name for name in ('developer-library', 'compiler-evidence', 'local-feed'))
    for root in (library, evidence, feed):
        root.mkdir()
    resource = b'Hello, '
    (library / 'prefix.txt').write_bytes(resource)
    (library / 'Library.cs').write_text('''namespace DeveloperInput;
public static class LibraryPrefix {
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
<ItemGroup><EmbeddedResource Include="prefix.txt" LogicalName="developer.prefix" /></ItemGroup>
</Project>''', encoding='utf-8')
    (library / 'nuget.config').write_text('<configuration><packageSources><clear /></packageSources></configuration>')
    (library / 'global.json').write_bytes((project / 'global.json').read_bytes())
    # This SDK-owned fixture builds only its reviewed pure managed library.
    # No application package, analyzer or target executes in this preparation.
    commands = Commands(project, evidence, build_environment(outside))
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
<dependencies><group targetFramework="net10.0"><dependency id="SmartFormat.Extensions.Newtonsoft.Json" version="[3.6.1]" /></group></dependencies>
</metadata></package>''')
        archive.writestr('lib/net10.0/Library.dll', assembly)
    (feed / (identity.lower() + '.1.0.0.nupkg')).write_bytes(original.getvalue())
    source = project / 'src/Main.cs'
    before = source.read_bytes()
    after = before.replace(b'$"Hello, {clean}!"', b'Prefix() + clean + "!"')
    if after == before:
        raise ValueError('C# dependency qualification source hook changed')
    helper = b'''
    private static string Prefix() {
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
    source.write_bytes(after[:index] + helper + after[index:])
    declaration = project / 'Capsule.csproj'
    declaration.write_bytes(declaration.read_bytes().replace(b'</Project>',
        ('<ItemGroup><PackageReference Include="' + identity + '" Version="[1.0.0]" />'
         '<PackageReference Include="SmartFormat.Extensions.Newtonsoft.Json" Version="[3.6.1]" /></ItemGroup></Project>').encode()))
    candidate = project / 'target/qualification.candidate.json'
    candidate.parent.mkdir()
    lock = resolve(project, candidate, dotnet=compiler.dotnet, tools=tools,
        policy={'sources': [{'name': 'developer', 'path': str(feed), 'patterns': [identity]}]})
    (project / LOCK).write_bytes(canonical(lock) + b'\n')
    selected = {row['metadata']['package'] for row in lock['artifacts']}
    if not {identity.lower(), 'smartformat.extensions.newtonsoft.json', 'smartformat', 'newtonsoft.json', 'zstring'} <= selected:
        raise ValueError('native NuGet qualification graph did not capture actual transitive/local packages')
    if library.resolve(strict=True).parent != outside.resolve(strict=True) or feed.resolve(strict=True).parent != outside.resolve(strict=True):
        raise ValueError('qualification cleanup escaped its owned dependency directory')
    shutil.rmtree(library)
    shutil.rmtree(feed)
    return {'formatVersion': 1, 'thirdParty': 'SmartFormat.Extensions.Newtonsoft.Json/3.6.1',
        'independentApplicationSelections': [identity + '/1.0.0', 'SmartFormat.Extensions.Newtonsoft.Json/3.6.1'],
        'transitives': ['SmartFormat', 'Newtonsoft.Json', 'ZString'], 'developerOwned': identity + '/1.0.0',
        'resourceDigest': digest(resource), 'managedAssemblyDigest': digest(assembly),
        'sourceDigest': digest(source.read_bytes()), 'offlineOriginals': 'unavailable-after-capture',
        'nativeGraphDigest': digest((project / 'nuget-resolved.lock.json').read_bytes()),
        'preparationCommands': commands.records}
