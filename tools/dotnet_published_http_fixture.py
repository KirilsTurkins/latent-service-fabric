"""Ordinary published factories plus two outside, uncatalogued NuGet consumers."""
from __future__ import annotations

import io
import json
from pathlib import Path
import secrets
import shutil
import zipfile

from tools import application_dependencies as dependencies, dotnet_dependency_authoring as authoring
from tools.build_observation import build_environment
from tools.dotnet_application_dependencies import package_name, resolve
from tools.dotnet_guest.compiler import Compiler
from tools.dotnet_standard_http_project import project as standard_project
from tools.phase2_operator_process import require
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, digest, inventory, read_file

ROOT_SOURCE = 'tools/fixtures/dotnet-published-http/Main.cs'
PRIVATE_SOURCE = 'tools/fixtures/dotnet-published-http/Private.cs.in'
PACKAGES = {'Flurl.Http': '4.0.2', 'Refit': '16.4.0'}


def project(directory):
    app = standard_project(directory)
    source = read_file(ROOT / ROOT_SOURCE)
    (app / 'src/Main.cs').write_bytes(source)
    lock = json.loads(read_file(app / 'sdk-lock.json'))
    lock['template']['sourceDigest'] = digest(source)
    (app / 'sdk-lock.json').write_text(json.dumps(lock, indent=2)+'\n', encoding='utf8', newline='\n')
    return app


def archive(identity, assembly):
    package_name(identity)
    require(type(assembly) is bytes and 0 < len(assembly) <= 4*1024**2,
            'published-dotnet-private-assembly-bound')
    result = io.BytesIO()
    with zipfile.ZipFile(result, 'w', compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr(identity+'.nuspec', '<?xml version="1.0"?><package><metadata><id>'+identity+'</id>'
            '<version>1.0.0</version><authors>SDK qualification</authors>'
            '<description>Outside developer HTTP consumer</description></metadata></package>')
        package.writestr('lib/net10.0/'+identity+'.dll', assembly)
    return result.getvalue()


def install(app: Path, outside: Path, tools: Path):
    require(outside.parent.resolve(strict=True) == app.parent.resolve(strict=True)
            and not outside.exists() and ROOT != outside.parent
            and ROOT not in outside.parents, 'published-dotnet-outside-scope')
    outside.mkdir(mode=0o700)
    feed = outside/'feed'
    feed.mkdir(mode=0o700)
    original_sdk = read_file(app/'sdk-lock.json')
    nonce = secrets.token_hex(10)
    private = []
    for number, namespace in enumerate(('PrivateFirst', 'PrivateSecond')):
        identity = 'Outside.Http.'+nonce+'.'+('Alpha' if number == 0 else 'Delta')
        library = outside/('library-'+str(number))
        evidence = outside/('compiler-'+str(number))
        library.mkdir(mode=0o700); evidence.mkdir(mode=0o700)
        source = read_file(ROOT/PRIVATE_SOURCE).replace(b'@NAMESPACE@', namespace.encode('ascii'))
        require(b'@NAMESPACE@' not in source, 'published-dotnet-private-namespace')
        (library/'Worker.cs').write_bytes(source)
        (library/'Worker.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
            '<TargetFramework>net10.0</TargetFramework><OutputType>Library</OutputType>'
            '<Nullable>enable</Nullable><AssemblyName>'+identity+'</AssemblyName>'
            '<UseSharedCompilation>false</UseSharedCompilation>'
            '<ImportDirectoryBuildProps>false</ImportDirectoryBuildProps>'
            '<ImportDirectoryBuildTargets>false</ImportDirectoryBuildTargets>'
            '</PropertyGroup></Project>', encoding='utf8')
        (library/'global.json').write_bytes(read_file(app/'global.json'))
        configuration = library/'nuget.config'
        configuration.write_text('<configuration><packageSources><clear/></packageSources></configuration>', encoding='utf8')
        commands = Commands(library, evidence, build_environment(outside), deadline_seconds=120, command_seconds=90)
        compiler = Compiler(tools, commands, app/'vendor/lsf', offline=True, captured=True)
        compiler.run('outside-http-library', compiler.dotnet, 'build', library/'Worker.csproj', '-c', 'Release',
            '-p:RestoreConfigFile='+str(configuration), '-p:NuGetAudit=false', '-nodeReuse:false',
            '-p:UseSharedCompilation=false', '-p:ImportDirectoryBuildProps=false', '-p:ImportDirectoryBuildTargets=false')
        compiler.check_unchanged()
        assembly = read_file(library/'bin/Release/net10.0'/(identity+'.dll'), 4*1024**2)
        raw = archive(identity, assembly)
        (feed/(identity.lower()+'.1.0.0.nupkg')).write_bytes(raw)
        private.append({'identity':identity, 'version':'1.0.0', 'namespace':namespace,
            'source':digest(source), 'assembly':digest(assembly), 'archive':digest(raw),
            'preparationCommands':commands.records})
        authoring.edit(app, 'add', identity=identity, version='1.0.0')
    for name, version in PACKAGES.items():
        authoring.edit(app, 'add', identity=name, version=version)
    candidate = app/'target/published-http-candidate.json'
    candidate.parent.mkdir(exist_ok=True)
    resolved = resolve(app, candidate, dotnet=compiler.dotnet, tools=tools,
        policy={'sources':[{'name':'outside', 'path':str(feed), 'patterns':[row['identity'] for row in private]}]})
    reviewed = authoring.review(app, candidate, digest(read_file(candidate)))
    require(reviewed['status']=='reviewed' and authoring.status(app)['status']=='verified',
            'published-dotnet-normal-capture-review')
    selected = {row['metadata']['package']:row for row in resolved['artifacts']}
    require(all(name.lower() in selected and selected[name.lower()]['metadata']['version']==version
                for name, version in PACKAGES.items()), 'published-dotnet-original-client-versions')
    require(all(row['identity'].lower() in selected for row in private)
            and read_file(app/'sdk-lock.json')==original_sdk, 'published-dotnet-private-capture-or-sdk-drift')
    require(resolved['executableInputs'], 'published-dotnet-real-refit-generator-not-captured')
    accepted = dependencies.verify_inputs(app, 'dotnet').lock
    for path in (feed, outside/'library-0', outside/'library-1'):
        require(not path.is_symlink() and path.resolve(strict=True).parent==outside.resolve(strict=True),
                'published-dotnet-owned-removal')
        shutil.rmtree(path)
    require(dependencies.verify_inputs(app, 'dotnet').lock==accepted,
            'published-dotnet-source-removal-changed-capture')
    return {'schemaVersion':'latent.dotnet.published-http.capture.v1', 'packages':PACKAGES,
        'privateConsumers':private, 'originalSourcesRemoved':True, 'catalogueLookupRequired':False,
        'normalConstructors':['FlurlClient()', 'RestService.CreateHttpClient(endpoint, settings)',
            'RestService.ForGenerated<IDomainApi>(client, settings)', 'HttpClient()'],
        'applicationHandlerInjection':False, 'sourceInventory':digest(inventory(authoring.source_files(app))),
        'acceptedLock':digest(read_file(app/dependencies.LOCK)), 'generatorExecution':'pending-exact-isolated-build',
        'signedExecution':'pending'}
