"""Normal published Polly/Core capture with ordinary default retry/timer factories."""
from pathlib import Path
from tools import application_dependencies as inputs
from tools import dotnet_dependency_authoring as authoring
from tools.build_observation import build_environment
from tools.dotnet_application_dependencies import resolve
from tools.dotnet_guest.compiler import Compiler
from tools.dotnet_guest.project import create
from tools.dotnet_task_runtime_fixture import declare
from tools.phase2_operator_process import require
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import digest

PACKAGE = 'Polly'
VERSION = '8.6.3'
CHECKPOINTS = ('builder', 'options', 'predicate', 'type-name', 'context', 'required', 'int-range', 'time-range', 'validate', 'add', 'build')
CASES = tuple('diagnostic-' + name for name in CHECKPOINTS) + ('legacy', 'modern', 'error', 'cancel')
VALUES = {'legacy': (3, 2, 41), 'modern': (3, 2, 43), 'error': (2, 1, 47), 'cancel': (1, 1, 53)}
VALUES.update({ 'diagnostic-' + name: (0, 0, 0) for name in CHECKPOINTS })
SOURCE = r'''using System;
using System.Threading;
using System.Threading.Tasks;
using Polly;
using Polly.Retry;
public static class PublishedTasks {
    public static string Stage { get; private set; } = "entry";
    private static int calls;
    public static string Run(string mode) {
        Stage = "guards";
        if (++calls != 1) throw new Exception("published request state leaked");
        if (SynchronizationContext.Current != null) throw new Exception("custom context installed");
        int attempts = 0, callbacks = 0;
        var gate = new TaskCompletionSource<int>(TaskCreationOptions.RunContinuationsAsynchronously);
        var original = new InvalidOperationException("ordinary-published-task-error");
        int value;
        switch (mode) {
        case "legacy": {
            Stage = "legacy-create";
            var policy = Policy.Handle<InvalidOperationException>().WaitAndRetryAsync(2,
                _ => TimeSpan.FromMilliseconds(1), (_, _, _, _) => ++callbacks);
            var pending = policy.ExecuteAsync(() => ++attempts < 3
                ? Task.FromException<int>(original) : gate.Task);
            Incomplete(pending); gate.SetResult(41); value = pending.GetAwaiter().GetResult();
            if (value != 41 || attempts != 3 || callbacks != 2) throw new Exception("legacy retry changed");
            break;
        }
        case "diagnostic-builder":
        case "diagnostic-options":
        case "diagnostic-predicate":
        case "diagnostic-type-name":
        case "diagnostic-context":
        case "diagnostic-required":
        case "diagnostic-int-range":
        case "diagnostic-time-range":
        case "diagnostic-validate":
        case "diagnostic-add":
        case "diagnostic-build":
        case "modern": {
            Stage = "modern-create";
            var builder = new ResiliencePipelineBuilder<int>();
            if (mode == "diagnostic-builder") return Checkpoint(mode);
            var options = new RetryStrategyOptions<int>();
            if (mode == "diagnostic-options") return Checkpoint(mode);
            var predicate = new PredicateBuilder<int>().Handle<InvalidOperationException>();
            if (mode == "diagnostic-predicate") return Checkpoint(mode);
            options = new RetryStrategyOptions<int> {
                MaxRetryAttempts = 2, Delay = TimeSpan.FromMilliseconds(1),
                BackoffType = DelayBackoffType.Constant, UseJitter = false,
                ShouldHandle = predicate,
                OnRetry = _ => { ++callbacks; return ValueTask.CompletedTask; }
            };
            if (mode == "diagnostic-type-name") {
                var type = options.GetType();
                if (!type.IsGenericType || type.Name.Length == 0 || type.GetGenericArguments()[0].Name.Length == 0) throw new Exception("type metadata");
                return Checkpoint(mode);
            }
            if (mode == "diagnostic-context") {
                var context = new System.ComponentModel.DataAnnotations.ValidationContext(options);
                if (context.DisplayName.Length == 0) throw new Exception("validation context");
                return Checkpoint(mode);
            }
            if (mode == "diagnostic-required") {
                if (!new System.ComponentModel.DataAnnotations.RequiredAttribute().IsValid(predicate)) throw new Exception("required");
                return Checkpoint(mode);
            }
            if (mode == "diagnostic-int-range") {
                if (!new System.ComponentModel.DataAnnotations.RangeAttribute(1,100).IsValid(2)) throw new Exception("integer range");
                return Checkpoint(mode);
            }
            if (mode == "diagnostic-time-range") {
                if (!new System.ComponentModel.DataAnnotations.RangeAttribute(typeof(TimeSpan),"00:00:00","1.00:00:00").IsValid(TimeSpan.FromMilliseconds(1))) throw new Exception("time range");
                return Checkpoint(mode);
            }
            if (mode == "diagnostic-validate") {
                if (!System.ComponentModel.DataAnnotations.Validator.TryValidateObject(options,
                    new System.ComponentModel.DataAnnotations.ValidationContext(options),
                    new System.Collections.Generic.List<System.ComponentModel.DataAnnotations.ValidationResult>(),true)) throw new Exception("validation");
                return Checkpoint(mode);
            }
            builder.AddRetry(options);
            if (mode == "diagnostic-add") return Checkpoint(mode);
            var pipeline = builder.Build();
            if (mode == "diagnostic-build") return Checkpoint(mode);
            Stage = "modern-execute";
            var pending = pipeline.ExecuteAsync(_ => ++attempts < 3
                ? ValueTask.FromException<int>(original) : new ValueTask<int>(gate.Task));
            Stage = "modern-pending";
            if (pending.IsCompleted) throw new Exception("modern pending work skipped");
            gate.SetResult(43); Stage = "modern-join"; value = pending.AsTask().GetAwaiter().GetResult();
            if (value != 43 || attempts != 3 || callbacks != 2) throw new Exception("modern retry changed");
            break;
        }
        case "error": {
            Stage = "error-create";
            var policy = Policy.Handle<InvalidOperationException>().WaitAndRetryAsync(1,
                _ => TimeSpan.FromMilliseconds(1), (_, _, _, _) => ++callbacks);
            var pending = policy.ExecuteAsync<int>(() => { ++attempts; return Task.FromException<int>(original); });
            try { pending.GetAwaiter().GetResult(); throw new Exception("error swallowed"); }
            catch (InvalidOperationException error) when (ReferenceEquals(error, original)) { }
            if (attempts != 2 || callbacks != 1) throw new Exception("error retry count changed");
            value = 47; break;
        }
        case "cancel": {
            Stage = "cancel-create";
            using var cancellation = new CancellationTokenSource();
            var policy = Policy.Handle<InvalidOperationException>().WaitAndRetryAsync(2,
                _ => TimeSpan.FromMilliseconds(10000), (_, _, _, _) => ++callbacks);
            var pending = policy.ExecuteAsync<int>(_ => { ++attempts; return Task.FromException<int>(original); }, cancellation.Token);
            Incomplete(pending); cancellation.Cancel();
            try { pending.GetAwaiter().GetResult(); throw new Exception("cancel ignored"); }
            catch (OperationCanceledException error) when (error.CancellationToken == cancellation.Token) { }
            if (attempts != 1 || callbacks != 1) throw new Exception("work retried after cancel");
            value = 53; break;
        }
        default: throw new Exception("unknown published task case");
        }
        return "published-tasks:" + mode + "|attempts=" + attempts + "|callbacks=" + callbacks + "|value=" + value;
    }
    private static string Checkpoint(string mode) => "published-tasks:" + mode + "|attempts=0|callbacks=0|value=0";
    private static void Incomplete(Task pending) {
        if (pending.IsCompleted) throw new Exception("pending work skipped");
    }
}
'''


def expected(mode):
    require(mode in CASES, 'dotnet-published-task-case')
    attempts, callbacks, value = VALUES[mode]
    return f'published-tasks:{mode}|attempts={attempts}|callbacks={callbacks}|value={value}'


def application(output):
    app = create(output, 'greeting')
    declare(app)
    path = app / 'src/Main.cs'
    before = path.read_text(encoding='utf-8')
    marker = '    public static Result<string, string> Greet(string name)\n    {'
    require(before.count(marker) == 1, 'dotnet-published-task-greeting-preimage')
    path.write_text(before.replace(marker, marker + r'''
        if (name.StartsWith("published:", System.StringComparison.Ordinal)) {
            try { return Result<string, string>.Ok(global::PublishedTasks.Run(name.Substring(10))); }
            catch (System.Exception error) {
                string kind = error switch {
                    System.PlatformNotSupportedException => "unsupported",
                    System.InvalidOperationException => "invalid-operation",
                    System.OperationCanceledException => "cancelled",
                    System.AggregateException => "aggregate",
                    System.TimeoutException => "timeout",
                    _ => "unknown"
                };
                return Result<string, string>.Err("published-task-failure:" + global::PublishedTasks.Stage + ":" + kind);
            }
        }
'''), encoding='utf-8', newline='\n')
    (app / 'src/PublishedTasks.cs').write_text(SOURCE, encoding='utf-8', newline='\n')
    authoring.edit(app, 'add', identity=PACKAGE, version=VERSION)
    return app


def selected(lock):
    rows = {row['id']: row for row in lock['artifacts']}
    require(len(lock['artifacts']) == len(rows) == 2
            and set(rows) == {'polly/8.6.3', 'polly.core/8.6.3'}
            and all(row['role'] == 'application' and row['format'] == 'zip'
                    and row['metadata']['ecosystem'] == 'nuget'
                    and not row['metadata']['sdk'] and not row['metadata']['executableAssets']
                    for row in rows.values())
            and rows['polly/8.6.3']['dependencies'] == ['polly.core/8.6.3']
            and rows['polly.core/8.6.3']['dependencies'] == [],
            'dotnet-published-task-selected-graph')
    return rows


def prepare(output: Path, outside: Path, tools: Path):
    app = application(output)
    sdk = (app / 'sdk-lock.json').read_bytes()
    outside.mkdir(mode=0o700)
    (outside / 'capture-evidence').mkdir(mode=0o700)
    commands = Commands(app, outside / 'capture-evidence', build_environment(outside))
    compiler = Compiler(tools, commands, app / 'vendor/lsf', offline=True, captured=True)
    candidate = app / 'target/published-task-candidate.json'
    candidate.parent.mkdir(exist_ok=True)
    lock = resolve(app, candidate, dotnet=compiler.dotnet, tools=tools)
    rows = selected(lock)
    require(authoring.review(app, candidate, digest(candidate.read_bytes()))['status'] == 'reviewed'
            and authoring.status(app)['status'] == 'verified'
            and (app / 'sdk-lock.json').read_bytes() == sdk,
            'dotnet-published-task-exact-review')
    compiler.check_unchanged()
    require(selected(inputs.verify_inputs(app, 'dotnet').lock) == rows,
            'dotnet-published-task-accepted-graph')
    return app, {'schemaVersion': 'latent.dotnet.published-tasks.fixture.v1',
        'packages': {name: {'original': row['original'], 'dependencies': row['dependencies'],
                           'metadata': row['metadata']} for name, row in rows.items()},
        'sdkLockDigest': digest(sdk), 'sourceDigest': digest(SOURCE.encode()),
        'acceptedLockDigest': digest((app / inputs.LOCK).read_bytes()),
        'normalResolverWorkspaceEphemeral': True, 'applicationSchedulerReplacement': False,
        'httpDeclaration': False, 'cases': list(CASES)}
