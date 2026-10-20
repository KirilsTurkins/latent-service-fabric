"""Captured ordinary finite Task.Wait calls; no application scheduler or pump."""
from pathlib import Path
import io
import shutil
import zipfile
from tools import dotnet_dependency_authoring as authoring
from tools.application_dependencies import LOCK
from tools.build_observation import build_environment
from tools.dotnet_application_dependencies import resolve
from tools.dotnet_guest.compiler import Compiler
from tools.dotnet_guest.project import create
from tools.dotnet_task_runtime_fixture import declare as declare_tasks
from tools.phase2_operator_process import require
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, digest, read_file, snapshot

PACKAGE='Outside.FiniteTaskWaits'
LIBRARY='tools/fixtures/dotnet-finite-task-waits/Library.cs'
LIBRARY_SOURCE=read_file(ROOT/LIBRARY).decode('utf-8')
EXPECTED={'completed-success-precancel': 'true', 'zero-incomplete-precancel': 'false-incomplete', 'invalid-timeout-before-complete': 'ArgumentOutOfRangeException:millisecondsTimeout', 'finite-success': 'true-original-task', 'finite-cancellable-success': 'true-original-task', 'timeout-false-then-fresh': 'false-then-true-original-token-live', 'infinite-cancel': 'OperationCanceledException:original-token;task-preserved', 'finite-cancel': 'OperationCanceledException:original-token;task-preserved', 'incomplete-precancel': 'OperationCanceledException:original-token', 'completed-fault-over-precancel': 'AggregateException:original-fault', 'pending-fault': 'AggregateException:original-fault', 'own-cancel-aggregate': 'AggregateException:original-task-token', 'own-cancel-wait-token-precedence': 'OperationCanceledException:original-wait-token', 'infinite-join-regression': 'true-original-infinite-join'}
CASES=tuple(EXPECTED)


def expected(mode):
    require(mode in EXPECTED, 'dotnet-finite-wait-unknown-case')
    return 'finite-task-wait:'+mode+'|'+EXPECTED[mode]


def prepare(output: Path, outside: Path, tools: Path):
    project = create(output, 'greeting')
    declare_tasks(project)
    outside.mkdir(mode=0o700)
    library, evidence, feed = (outside / name for name in ('library', 'evidence', 'feed'))
    for directory in (library, evidence, feed): directory.mkdir()
    (library / 'Library.cs').write_text(LIBRARY_SOURCE, encoding='utf-8', newline='\n')
    (library / 'Library.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
        '<TargetFramework>net10.0</TargetFramework><OutputType>Library</OutputType>'
        '<AssemblyName>' + PACKAGE + '</AssemblyName><Nullable>enable</Nullable>'
        '<UseSharedCompilation>false</UseSharedCompilation><ImportDirectoryBuildProps>false</ImportDirectoryBuildProps>'
        '<ImportDirectoryBuildTargets>false</ImportDirectoryBuildTargets></PropertyGroup></Project>', encoding='utf-8')
    (library / 'nuget.config').write_text('<configuration><packageSources><clear /></packageSources></configuration>')
    (library / 'global.json').write_bytes((project / 'global.json').read_bytes())
    originals = {name: digest(data) for name, data in snapshot(library).items()}
    commands = Commands(library, evidence, build_environment(outside))
    compiler = Compiler(tools, commands, project / 'vendor/lsf', offline=True, captured=True)
    compiler.run('outside-task-library', compiler.dotnet, 'build', library / 'Library.csproj', '-c', 'Release',
        '-p:RestoreConfigFile=' + str(library / 'nuget.config'), '-p:NuGetAudit=false', '-nodeReuse:false',
        '-p:UseSharedCompilation=false', '-p:ImportDirectoryBuildProps=false', '-p:ImportDirectoryBuildTargets=false')
    compiler.check_unchanged()
    assembly = (library / 'bin/Release/net10.0' / (PACKAGE + '.dll')).read_bytes()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(PACKAGE + '.nuspec', '<?xml version="1.0"?><package><metadata><id>' + PACKAGE
            + '</id><version>1.0.0</version><authors>SDK qualification</authors>'
            '<description>Outside ordinary managed Task library</description></metadata></package>')
        archive.writestr('lib/net10.0/' + PACKAGE + '.dll', assembly)
    package = buffer.getvalue()
    (feed / (PACKAGE.lower() + '.1.0.0.nupkg')).write_bytes(package)
    path = project / 'src/Main.cs'; before = path.read_text(encoding='utf-8')
    marker = '    public static Result<string, string> Greet(string name)\n    {'
    require(before.count(marker) == 1, 'dotnet-task-greeting-preimage')
    path.write_text(before.replace(marker, marker + r'''
        if (name.StartsWith("finite:", System.StringComparison.Ordinal)) {
            try { return Result<string, string>.Ok(OutsideFiniteWaits.Library.Run(name.Substring(7))); }
            catch (System.Exception error) {
                string kind = error switch {
                    System.PlatformNotSupportedException => "unsupported",
                    System.InvalidOperationException => "invalid-operation",
                    System.OperationCanceledException => "cancelled",
                    System.AggregateException => "aggregate",
                    System.TimeoutException => "timeout",
                    _ => "unknown"
                };
                return Result<string, string>.Err("finite-task-wait-failure:" + kind);
            }
        }
'''), encoding='utf-8', newline='\n')
    authoring.edit(project, 'add', identity=PACKAGE, version='1.0.0')
    candidate = project / 'target/task-candidate.json'; candidate.parent.mkdir(exist_ok=True)
    lock = resolve(project, candidate, dotnet=compiler.dotnet, tools=tools,
        policy={'sources': [{'name': 'outside', 'path': str(feed), 'patterns': [PACKAGE]}]})
    require(authoring.review(project, candidate, digest(candidate.read_bytes()))['status'] == 'reviewed'
            and authoring.status(project)['status'] == 'verified', 'dotnet-task-exact-native-review')
    require(PACKAGE.lower() in {row['metadata']['package'] for row in lock['artifacts']}
            and all(row['role'] != 'build-tool' for row in lock['artifacts']), 'dotnet-task-pure-capture')
    for directory in (library, feed):
        require(directory.resolve(strict=True).parent == outside.resolve(strict=True), 'dotnet-task-owned-cleanup')
        shutil.rmtree(directory)
    return project, {'schemaVersion': 'latent.dotnet.finite-task-waits.fixture.v1', 'originalFiles': originals,
        'assemblyDigest': digest(assembly), 'packageDigest': digest(package),
        'dependencyLock': digest((project / LOCK).read_bytes()),
        'originalLibraryAndFeedRemoved': not library.exists() and not feed.exists(),
        'applicationSchedulerReplacement': False, 'httpDeclaration': False,
        'entropyDeclaration': 'explicit-threadpool-selector-seed', 'cases': list(CASES), 'librarySourceDigest': digest(LIBRARY_SOURCE.encode())}
