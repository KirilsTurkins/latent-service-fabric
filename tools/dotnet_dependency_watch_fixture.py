"""Reviewed outside NuGet library revisions for normal delivered signed watch."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import zipfile

PRIMARY = 'Outside.Watch.Library'
RESOURCE = b'captured watch data'


def digest(raw: bytes) -> str:
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def version(number: int) -> str:
    if number not in (1, 2):
        raise ValueError('unknown owned watch library revision')
    return '1.0.0' if number == 1 else '1.0.1'


def library_source() -> str:
    return '''namespace DeveloperInput;
public static class LibraryPrefix {
    private static string Resource(string name) {
        using var input = typeof(LibraryPrefix).Assembly.GetManifestResourceStream(name)
            ?? throw new System.Exception("captured watch resource missing");
        using var reader = new System.IO.StreamReader(input, System.Text.Encoding.UTF8);
        return reader.ReadToEnd();
    }
    public static string Read() => Resource("developer.marker");
    public static string Badge() => Resource("developer.badge");
}
'''


def package(number: int, assembly: bytes) -> bytes:
    value = io.BytesIO()
    with zipfile.ZipFile(value, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(PRIMARY + '.nuspec', '<package><metadata><id>' + PRIMARY + '</id><version>' +
            version(number) + '</version><authors>SDK qualification</authors><description>Outside watch input</description></metadata></package>')
        archive.writestr('lib/net10.0/Library.dll', assembly)
    return value.getvalue()


def verify_compiler_copy(original: Path, captured: Path, expected: dict) -> None:
    from tools.build_observation import file_identity
    if (file_identity(original, 'delivered-dotnet') != expected
            or file_identity(captured, 'delivered-dotnet') != expected):
        raise ValueError('delivered library compiler identity changed')


def prepare(app: Path, output: Path, tools: Path, dotnet: Path, sdk_bin: Path, recipe: Path) -> None:
    if output.exists():
        raise ValueError('fresh library preparation required')
    output.mkdir(mode=0o700)
    sys.path.insert(0, str(recipe))
    from tools.build_observation import build_environment, file_identity
    from tools.dotnet_guest.compiler import Compiler
    from tools.dotnet_guest.entropy_grants import declare
    from tools.rust_capsule_build import Commands
    declare(app)
    compiler_identity = file_identity(dotnet, 'delivered-dotnet')
    records = []
    for number in (1, 2):
        root = output / ('v' + str(number)); root.mkdir(mode=0o700)
        library, evidence = root / 'library', root / 'evidence'
        library.mkdir(); evidence.mkdir()
        (library / 'Library.cs').write_text(library_source(), encoding='utf-8')
        (library / 'marker.txt').write_text('42' if number == 1 else '43', encoding='ascii')
        (library / 'badge.txt').write_bytes(RESOURCE)
        (library / 'Library.csproj').write_text('''<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>
<TargetFramework>net10.0</TargetFramework><OutputType>Library</OutputType><Nullable>enable</Nullable>
<UseSharedCompilation>false</UseSharedCompilation><ImportDirectoryBuildProps>false</ImportDirectoryBuildProps>
<ImportDirectoryBuildTargets>false</ImportDirectoryBuildTargets></PropertyGroup><ItemGroup>
<EmbeddedResource Include="marker.txt" LogicalName="developer.marker" />
<EmbeddedResource Include="badge.txt" LogicalName="developer.badge" /></ItemGroup></Project>''', encoding='utf-8')
        (library / 'nuget.config').write_text('<configuration><packageSources><clear /></packageSources></configuration>', encoding='utf-8')
        (library / 'global.json').write_bytes((app / 'global.json').read_bytes())
        environment = build_environment(root)
        environment['PATH'] = str(dotnet.parent) + os.pathsep + str(sdk_bin) + os.pathsep + os.defpath
        commands = Commands(library, evidence, environment)
        compiler = Compiler(tools, commands, app / 'vendor/lsf', offline=True, captured=True)
        verify_compiler_copy(dotnet, compiler.dotnet, compiler_identity)
        compiler.run('reviewed-library-build', compiler.dotnet, 'build', library / 'Library.csproj', '-c', 'Release',
            '-p:RestoreConfigFile=' + str(library / 'nuget.config'), '-p:NuGetAudit=false', '-nodeReuse:false',
            '-p:UseSharedCompilation=false', '-p:ImportDirectoryBuildProps=false', '-p:ImportDirectoryBuildTargets=false')
        compiler.check_unchanged()
        verify_compiler_copy(dotnet, compiler.dotnet, compiler_identity)
        assembly = (library / 'bin/Release/net10.0/Library.dll').read_bytes()
        raw = package(number, assembly)
        location = root / (PRIMARY.lower() + '.' + version(number) + '.nupkg')
        location.write_bytes(raw)
        records.append({'revision': number, 'path': str(location), 'digest': digest(raw),
            'assembly': digest(assembly), 'source': digest(library_source().encode()), 'resource': digest(RESOURCE),
            'commands': commands.records})
    (output / 'preparation.json').write_text(json.dumps({'root': str(output.resolve()), 'packages': records}), encoding='utf-8')


def owned(inputs: dict) -> Path:
    root = Path(inputs['root'])
    if root.is_symlink() or root.resolve(strict=True) != Path(inputs['ownedRoot']):
        raise ValueError('owned .NET watch input root changed')
    return root


def restore_revision(inputs: dict, number: int) -> None:
    selected = version(number)
    root = owned(inputs); feed = root / 'feed'
    if feed.exists() or feed.is_symlink():
        raise ValueError('choose a fresh owned .NET watch feed')
    feed.mkdir(mode=0o700)
    (feed / (PRIMARY.lower() + '.' + selected + '.nupkg')).write_bytes(inputs['packages'][number])


def create(application: Path, prepared: dict) -> dict:
    preparation = Path(prepared['root'])
    if preparation.is_symlink() or preparation.resolve(strict=True) != application.parent.resolve() / 'library-preparation':
        raise ValueError('owned library preparation root changed')
    if len(prepared['packages']) != 2 or {row['revision'] for row in prepared['packages']} != {1, 2}:
        raise ValueError('two exact prepared library revisions required')
    packages, identities = {}, {}
    for row in prepared['packages']:
        location = Path(row['path'])
        if location.is_symlink() or not location.resolve(strict=True).is_relative_to(preparation.resolve(strict=True)):
            raise ValueError('prepared library archive escaped source owner')
        if not location.is_file() or location.stat().st_size > 1024 * 1024:
            raise ValueError('prepared library archive byte bound')
        with location.open('rb') as stream:
            raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024 or digest(raw) != row['digest']:
            raise ValueError('prepared library archive identity changed')
        packages[row['revision']] = raw
        identities['library-v' + str(row['revision'])] = row['digest']
    root = application.parent / 'outside-watch-inputs'; root.mkdir(mode=0o700)
    result = {'root': str(root), 'ownedRoot': str(root.resolve(strict=True)), 'feed': str(root / 'feed'),
        'inputDigests': identities, 'packages': packages}
    # Only our verified preparation root is removed; reviewed archive bytes stay
    # in this finite fixture owner until the explicit later source revision.
    shutil.rmtree(preparation)
    restore_revision(result, 1)
    return result


def remove_original(inputs: dict) -> None:
    root = owned(inputs); feed = root / 'feed'
    if feed.is_symlink() or feed.resolve(strict=True).parent != root.resolve(strict=True):
        raise ValueError('owned .NET feed removal escaped original root')
    shutil.rmtree(feed)


def application_source(*, removed=False) -> str:
    body = '"removed/" + clean' if removed else 'DeveloperInput.LibraryPrefix.Read() + "/" + clean + "/" + DeveloperInput.LibraryPrefix.Badge()'
    return '''using ServiceWorld;
using Lsf.Guest;
namespace ServiceWorld.wit.Exports.examples.greeting;
public class ApiExportsImpl : IApiExports {
    private static uint calls;
    public static Result<string,string> Greet(string name) {
        if (calls++ != 0) return Result<string,string>.Err("activation-state-reused");
        string clean = Text.Trim(name);
        if (clean.Length == 0 || Text.Utf8Length(clean)>100) return Result<string,string>.Err("invalid-watch-input");
        return Result<string,string>.Ok(''' + body + ''');
    }
}
'''


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ('app', 'output', 'tools', 'dotnet', 'sdk-bin', 'recipe'):
        parser.add_argument('--' + argument, required=True, type=Path)
    args = parser.parse_args()
    prepare(args.app.resolve(strict=True), args.output.absolute(), args.tools.resolve(strict=True),
        args.dotnet.resolve(strict=True), args.sdk_bin.resolve(strict=True), args.recipe.resolve(strict=True))
