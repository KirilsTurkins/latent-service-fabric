"""Normally captured outside NuGet library using default managed work queues."""
from pathlib import Path
import io
import shutil
import zipfile

from tools import dotnet_dependency_authoring as authoring
from tools.application_dependencies import LOCK
from tools.build_observation import build_environment
from tools.build_snapshot import digest
from tools.dotnet_application_dependencies import resolve
from tools.dotnet_guest.compiler import Compiler
from tools.dotnet_guest.project import create
from tools.dotnet_guest import entropy_grants
from tools.dotnet_guest.runtime import ACTIVATION, WALL
from tools.phase2_operator_process import require
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, snapshot

PACKAGE = 'Outside.Standard.Tasks'
CASES = ('run', 'when-all', 'thread-pool', 'scheduler', 'error', 'cancel',
         'context', 'suppressed-context', 'delay', 'cancel-after', 'nested', 'monitor',
         'timer-periodic-context', 'timer-change', 'timer-dispose', 'timer-self-dispose-drain')
LIBRARY_SOURCE = r'''using System;
using System.Threading;
using System.Threading.Tasks;
namespace OutsideTasks;
public static class Library {
    public static string Stage { get; private set; } = "entry";
    private static int calls;
    private static readonly AsyncLocal<string?> local = new();
    public static string Run(string mode) {
        Stage = "guards";
        if (++calls != 1) throw new Exception("managed request state leaked");
        if (SynchronizationContext.Current != null) throw new Exception("custom context installed");
        Stage = "gate-create";
        var gate = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        Task<int> pending;
        int result;
        switch (mode) {
        case "run":
            Stage = "run-submit";
            pending = Task.Run(async () => { await gate.Task; return 7; });
            Stage = "run-pending";
            Incomplete(pending); gate.SetResult(true);
            Stage = "run-join";
            result = pending.GetAwaiter().GetResult();
            Stage = "run-joined";
            if (result != 7) throw new Exception("Task.Run result changed");
            break;
        case "when-all":
            var first = Task.Run(async () => { await gate.Task; return 3; });
            var second = Task.Run(async () => { await gate.Task; return 5; });
            var all = Task.WhenAll(first, second); Incomplete(all); gate.SetResult(true);
            var values = all.GetAwaiter().GetResult();
            if (values.Length != 2 || values[0] != 3 || values[1] != 5)
                throw new Exception("WhenAll ordering changed");
            break;
        case "thread-pool":
            var queued = new TaskCompletionSource<int>(TaskCreationOptions.RunContinuationsAsynchronously);
            if (!ThreadPool.QueueUserWorkItem(_ => queued.SetResult(11)))
                throw new Exception("ThreadPool rejected ordinary work");
            if (queued.Task.GetAwaiter().GetResult() != 11) throw new Exception("queued work lost");
            break;
        case "scheduler":
            pending = Task.Factory.StartNew(() => 13, CancellationToken.None,
                TaskCreationOptions.DenyChildAttach, TaskScheduler.Default);
            if (pending.GetAwaiter().GetResult() != 13) throw new Exception("default scheduler lost work");
            break;
        case "error":
            pending = Task.Run<int>(async () => { await gate.Task; throw new InvalidOperationException("original-task-error"); });
            Incomplete(pending); gate.SetResult(true);
            try { pending.GetAwaiter().GetResult(); throw new Exception("task error swallowed"); }
            catch (InvalidOperationException error) when (error.Message == "original-task-error") { }
            break;
        case "cancel":
            using (var cancelled = new CancellationTokenSource()) {
                cancelled.Cancel(); bool ran = false;
                var task = Task.Run(() => { ran = true; }, cancelled.Token);
                try { task.GetAwaiter().GetResult(); throw new Exception("cancel ignored"); }
                catch (OperationCanceledException error) {
                    if (ran || error.CancellationToken != cancelled.Token) throw new Exception("cancel identity changed");
                }
            }
            break;
        case "context":
            local.Value = "parent";
            pending = Task.Run(async () => {
                if (local.Value != "parent") throw new Exception("ExecutionContext was not captured");
                local.Value = "child"; await gate.Task; await Task.Delay(1);
                if (local.Value != "child") throw new Exception("continuation context was lost");
                return 17;
            });
            Incomplete(pending); gate.SetResult(true);
            if (pending.GetAwaiter().GetResult() != 17 || local.Value != "parent")
                throw new Exception("child context leaked into caller");
            break;
        case "suppressed-context":
            local.Value = "parent";
            using (ExecutionContext.SuppressFlow()) {
                pending = Task.Run(() => { if (local.Value != null) throw new Exception("suppressed context flowed"); return 19; });
            }
            if (pending.GetAwaiter().GetResult() != 19 || local.Value != "parent" || ExecutionContext.IsFlowSuppressed())
                throw new Exception("suppression scope leaked");
            break;
        case "delay":
            pending = Task.Run(async () => { await gate.Task; await Task.Delay(1); return 23; });
            Incomplete(pending); gate.SetResult(true);
            if (pending.GetAwaiter().GetResult() != 23) throw new Exception("timer continuation lost");
            break;
        case "cancel-after":
            using (var deadline = new CancellationTokenSource()) {
                var waiting = Task.Delay(10000, deadline.Token); Incomplete(waiting);
                deadline.CancelAfter(1);
                try { waiting.GetAwaiter().GetResult(); throw new Exception("deadline ignored"); }
                catch (OperationCanceledException error) {
                    if (error.CancellationToken != deadline.Token) throw new Exception("deadline token changed");
                }
            }
            break;
        case "nested":
            pending = Task.Run(() => Task.Run(() => 29).GetAwaiter().GetResult());
            if (pending.GetAwaiter().GetResult() != 29) throw new Exception("nested queue did not progress");
            break;
        case "monitor":
            object sync = new();
            pending = Task.Run(() => { lock (sync) { lock (sync) { return 31; } } });
            if (pending.GetAwaiter().GetResult() != 31) throw new Exception("reentrant monitor changed");
            break;
        case "timer-periodic-context": {
            Stage = "periodic-create";
            local.Value = "timer-captured";
            var ticks = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            int count = 0;
            Timer? timer = null;
            timer = new Timer(_ => {
                try {
                    Stage = "periodic-callback";
                    if (local.Value != "timer-captured") throw new InvalidOperationException("timer context lost");
                    local.Value = "timer-callback";
                    if (++count >= 3) { timer!.Change(Timeout.Infinite, Timeout.Infinite); ticks.TrySetResult(true); }
                } catch (Exception error) { ticks.TrySetException(error); }
            }, null, Timeout.Infinite, Timeout.Infinite);
            try {
                local.Value = "timer-caller";
                Incomplete(ticks.Task); timer.Change(1, 1);
                Stage = "periodic-join"; ticks.Task.GetAwaiter().GetResult();
                timer.DisposeAsync().AsTask().GetAwaiter().GetResult();
                int retired = count;
                Task.Delay(3).GetAwaiter().GetResult();
                if (retired < 3 || count != retired || local.Value != "timer-caller")
                    throw new InvalidOperationException("periodic disposal or caller context changed");
            } finally { timer.Dispose(); }
            break;
        }
        case "timer-change": {
            Stage = "change-create";
            int count = 0;
            var next = new TaskCompletionSource<int>(TaskCreationOptions.RunContinuationsAsynchronously);
            using var timer = new Timer(_ => next.TrySetResult(++count), null, Timeout.Infinite, Timeout.Infinite);
            Task.Run(() => { if (count != 0) throw new InvalidOperationException("disabled timer fired"); })
                .GetAwaiter().GetResult();
            timer.Change(10000, Timeout.Infinite);
            timer.Change(1, Timeout.Infinite);
            Stage = "change-first";
            if (next.Task.GetAwaiter().GetResult() != 1) throw new InvalidOperationException("changed due time lost");
            next = new TaskCompletionSource<int>(TaskCreationOptions.RunContinuationsAsynchronously);
            Incomplete(next.Task); timer.Change(1, Timeout.Infinite);
            Stage = "change-second";
            if (next.Task.GetAwaiter().GetResult() != 2) throw new InvalidOperationException("timer reset lost");
            timer.DisposeAsync().AsTask().GetAwaiter().GetResult();
            Task.Delay(3).GetAwaiter().GetResult();
            if (count != 2) throw new InvalidOperationException("retired reset fired again");
            break;
        }
        case "timer-dispose": {
            Stage = "dispose-create";
            int count = 0;
            var timer = new Timer(_ => ++count, null, 10000, Timeout.Infinite);
            timer.Dispose(); timer.Dispose();
            Task.Delay(3).GetAwaiter().GetResult();
            if (count != 0) throw new InvalidOperationException("disposed timer fired");
            if (timer.Change(0, Timeout.Infinite)) throw new InvalidOperationException("disposed timer accepted reset");
            timer.DisposeAsync().AsTask().GetAwaiter().GetResult();
            break;
        }
        case "timer-self-dispose-drain": {
            Stage = "self-dispose-create";
            var completion = new TaskCompletionSource<Task>(TaskCreationOptions.RunContinuationsAsynchronously);
            Timer? timer = null;
            timer = new Timer(_ => {
                try {
                    Stage = "self-dispose-callback";
                    var disposal = timer!.DisposeAsync();
                    if (disposal.IsCompleted) throw new InvalidOperationException("live timer callback marked retired");
                    completion.SetResult(disposal.AsTask());
                } catch (Exception error) { completion.TrySetException(error); }
            }, null, Timeout.Infinite, Timeout.Infinite);
            try {
                Incomplete(completion.Task); timer.Change(1, Timeout.Infinite);
                Stage = "self-dispose-join";
                completion.Task.GetAwaiter().GetResult().GetAwaiter().GetResult();
                timer.Dispose();
            } finally { timer.Dispose(); }
            break;
        }
        default: throw new Exception("unknown finite managed task case");
        }
        if (SynchronizationContext.Current != null) throw new Exception("custom context escaped");
        return "ordinary-tasks:" + mode + "|fresh=1";
    }
    private static void Incomplete(Task value) {
        if (value.IsCompleted) throw new Exception("pending task was fabricated as complete");
    }
}
'''


def expected(mode):
    require(mode in CASES, 'dotnet-task-unknown-case')
    return 'ordinary-tasks:' + mode + '|fresh=1'


def declare(project: Path):
    wit = project / 'wit/world.wit'
    source = wit.read_text(encoding='utf-8')
    require(source.count('greet: func(') == 1 and source.count('world service {') == 1,
            'dotnet-task-canonical-greeting')
    wit.write_text(source.replace('greet: func(', 'greet: async func(')
        .replace('world service {', 'world service {\n    import ' + ACTIVATION + ';\n    import ' + WALL + ';'), encoding='utf-8')
    for name, body in snapshot(ROOT / 'wit/platform/activation-runtime').items():
        target = project / 'wit/deps/activation-runtime' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream: stream.write(body)
    entropy_grants.declare(project)


def prepare(output: Path, outside: Path, tools: Path):
    project = create(output, 'greeting')
    declare(project)
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
        if (name.StartsWith("task:", System.StringComparison.Ordinal)) {
            try { return Result<string, string>.Ok(OutsideTasks.Library.Run(name.Substring(5))); }
            catch (System.Exception error) {
                string kind = error switch {
                    System.PlatformNotSupportedException => "unsupported",
                    System.InvalidOperationException => "invalid-operation",
                    System.OperationCanceledException => "cancelled",
                    System.AggregateException => "aggregate",
                    System.TimeoutException => "timeout",
                    _ => "unknown"
                };
                return Result<string, string>.Err("ordinary-task-failure:" + OutsideTasks.Library.Stage + ":" + kind);
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
    return project, {'schemaVersion': 'latent.dotnet.tasks.fixture.v1', 'originalFiles': originals,
        'assemblyDigest': digest(assembly), 'packageDigest': digest(package),
        'dependencyLock': digest((project / LOCK).read_bytes()),
        'originalLibraryAndFeedRemoved': not library.exists() and not feed.exists(),
        'applicationSchedulerReplacement': False, 'httpDeclaration': False,
        'entropyDeclaration': 'explicit-threadpool-selector-seed', 'cases': list(CASES)}
