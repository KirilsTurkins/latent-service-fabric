using System;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using Activation = ServiceWorld.wit.Imports.latent.runtime.IActivationImports;

namespace ServiceWorld.wit.Exports.examples.dotnetStandardHttp;

public class ApiExportsImpl : IApiExports
{
    private static int calls;
    private static readonly AsyncLocal<string?> context = new();
    public static string Run(uint mode, string endpoint)
    {
        Need(++calls == 1 && context.Value is null && SynchronizationContext.Current is null);
        context.Value = "capacity-root";
        return "1:" + RunAsync(mode, endpoint).GetAwaiter().GetResult();
    }
    private static void Need(bool value)
    { if (!value) throw new InvalidOperationException("managed-capacity-assertion"); }
    private static Activation.Observation Observe()
    { var value = Activation.Observe(); Need(value.IsOk); return value.AsOk; }
    private static bool Refusal(Exception error) => error is InvalidOperationException
        { Message: "managed-work-admission-refused" }
        || error is TaskSchedulerException { InnerException: InvalidOperationException
            { Message: "managed-work-admission-refused" } };
    private static async Task<string> RunAsync(uint mode, string endpoint)
    {
        switch (mode) {
        case 0: return await Tasks();
        case 1: return await Queue();
        case 2: return await Timers();
        case 3: return await Periodic();
        case 4: return await Disposed();
        case 5: Accepted(endpoint); return "closing-timer:accepted";
        case 6: return NativeLedger();
        case 7: return await Fresh();
        default: throw new ArgumentOutOfRangeException(nameof(mode));
        }
    }
    private static async Task<string> Tasks()
    {
        var before = Observe(); Need(before.tasks == 1 && before.queuedWork == 0);
        var sources = new TaskCompletionSource<int>[7]; var tasks = new Task<int>[7]; int finished = 0;
        for (int i = 0; i < 7; i++) {
            sources[i] = new TaskCompletionSource<int>();
            tasks[i] = sources[i].Task.ContinueWith(task => {
                try { Need(context.Value == "capacity-root"); return task.GetAwaiter().GetResult() + 1; }
                finally { finished++; }
            }, CancellationToken.None, TaskContinuationOptions.None, TaskScheduler.Default);
            Need(Observe().tasks == i + 2 && Observe().queuedWork == 0);
        }
        bool refused = false;
        try { _ = new TaskCompletionSource<int>().Task.ContinueWith(_ => 0); }
        catch (Exception error) when (Refusal(error)) { refused = true; }
        Need(refused && Observe().tasks == 8 && Observe().admissionFailures == before.admissionFailures + 1);
        for (int i = 0; i < 7; i++) { sources[i].SetResult(i); Need(await tasks[i] == i + 1); }
        Need(finished == 7);
        var fresh = Task.Run(() => { Need(context.Value == "capacity-root"); return 17; });
        Need(await fresh == 17 && context.Value == "capacity-root");
        return "tasks:7:refused:7-finally:fresh";
    }
    private static async Task<string> Queue()
    {
        var before = Observe(); var done = new TaskCompletionSource<int>(); int finished = 0;
        WaitCallback callback = _ => {
            try { Need(context.Value == "capacity-root"); }
            finally { if (++finished == 2) done.SetResult(2); }
        };
        Need(ThreadPool.QueueUserWorkItem(callback) && ThreadPool.QueueUserWorkItem(callback));
        Need(Observe().queuedWork == 2 && Observe().tasks == 3);
        bool refused = false;
        try { _ = ThreadPool.QueueUserWorkItem(callback); }
        catch (Exception error) when (Refusal(error)) { refused = true; }
        Need(refused && Observe().queuedWork == 2 && Observe().tasks == 3
            && Observe().admissionFailures == before.admissionFailures + 1);
        Need(await done.Task == 2 && finished == 2);
        var fresh = new TaskCompletionSource<int>();
        Need(ThreadPool.QueueUserWorkItem(_ => fresh.SetResult(19)));
        Need(await fresh.Task == 19 && context.Value == "capacity-root");
        return "queue:2:refused:rollback:2-finally:fresh";
    }
    private static async Task<string> Timers()
    {
        var items = new Timer[8]; var births = new uint[8]; var drops = new uint[8]; int count = 0;
        var initial = Observe(); Need(initial.timers == 0); uint last = 0;
        try {
            while (Observe().timers < 8 && count < items.Length) {
                uint before = Observe().timers;
                items[count] = new Timer(_ => throw new InvalidOperationException("held timer fired"),
                    null, 30000, Timeout.Infinite);
                uint after = Observe().timers;
                Need(after == before + 1 || (count == 0 && after == before + 2));
                births[count++] = after; last = after;
            }
            Need(count >= 7 && count <= 8 && last == 8);
            ulong failures = Observe().admissionFailures; bool refused = false;
            try { using var denied = new Timer(_ => { }, null, 30000, Timeout.Infinite); }
            catch (Exception error) when (Refusal(error)) { refused = true; }
            Need(refused && Observe().timers == 8 && Observe().admissionFailures == failures + 1);
            Need(items[0].Change(30000, Timeout.Infinite) && Observe().timers == 8);
        }
        finally {
            for (int i = 0; i < count; i++) {
                uint before = Observe().timers; items[i].Dispose(); uint after = Observe().timers;
                Need(after + 1 == before || (i == count - 1 && after + 2 == before)); drops[i] = after;
            }
        }
        await FreshTimer();
        return "timers:" + count + ":" + string.Join(',', births.AsSpan(0, count).ToArray())
            + ":" + string.Join(',', drops.AsSpan(0, count).ToArray()) + ":refused:reused:fresh";
    }
    private static async Task FreshTimer()
    {
        var done = new TaskCompletionSource<int>(); int fired = 0;
        using var timer = new Timer(_ => {
            Need(context.Value == "capacity-root" && Observe().timers >= 1);
            done.SetResult(++fired);
        }, null, 1, Timeout.Infinite);
        Need(await done.Task == 1 && fired == 1 && context.Value == "capacity-root");
        await timer.DisposeAsync();
    }
    private static async Task<string> Periodic()
    {
        var done = new TaskCompletionSource<int>(); int fired = 0;
        using var actual = new Timer(_ => {
            Need(context.Value == "capacity-root" && Observe().timers >= 1);
            if (++fired == 2) done.SetResult(2);
        }, null, 1, 100);
        Need(await done.Task == 2); actual.Change(Timeout.Infinite, Timeout.Infinite);
        await actual.DisposeAsync(); Need(fired == 2); await FreshTimer();
        return "periodic:2:context:disposed:fresh";
    }
    private static async Task<string> Disposed()
    {
        int fired = 0; var timer = new Timer(_ => fired++, null, 0, Timeout.Infinite);
        await timer.DisposeAsync(); await Task.Yield(); Need(fired == 0);
        await FreshTimer(); return "disposed-before-dispatch:0:fresh";
    }
    private static void Accepted(string endpoint)
    {
        Timer? held = null;
        held = new Timer(_ => { _ = Required(); }, null, 1, Timeout.Infinite);
        async Task Required() {
            Need(context.Value == "capacity-root" && Observe().timers >= 1);
            await Task.Yield();
            Need(Observe().phase == Activation.Phase.CLOSING);
            Need(await Task.Run(() => context.Value == "capacity-root") && context.Value == "capacity-root");
            try { await Task.Yield(); }
            finally {
                using var client = new HttpClient();
                using var marker = await client.PostAsync(endpoint + "/conformance/echo",
                    new StringContent("capacity:closing-timer-finally"));
                Need(marker.IsSuccessStatusCode); await marker.Content.ReadAsByteArrayAsync();
                await held!.DisposeAsync();
            }
        }
    }
    private static string NativeLedger()
    {
        var before = Observe(); Need(before.nativeOwners == 1);
        var first = Activation.Register(Activation.OwnerKind.NATIVE, null); Need(first.IsOk);
        try {
            Need(Observe().nativeOwners == 2);
            var refused = Activation.Register(Activation.OwnerKind.NATIVE, null);
            Need(!refused.IsOk && refused.AsErr == Activation.Error.RESOURCE_EXHAUSTED
                && Observe().nativeOwners == 2 && Observe().admissionFailures == before.admissionFailures + 1);
        }
        finally { Need(Activation.Settle(first.AsOk).IsOk); }
        var fresh = Activation.Register(Activation.OwnerKind.NATIVE, null); Need(fresh.IsOk);
        Need(Activation.Settle(fresh.AsOk).IsOk && Observe().nativeOwners == 1);
        return "native-ledger:2:typed-refusal:settled:fresh";
    }
    private static async Task<string> Fresh()
    {
        Need(Observe().nativeOwners == 1 && Observe().tasks == 1);
        Need(await Task.Run(() => context.Value == "capacity-root"));
        var done = new TaskCompletionSource<int>(); Need(ThreadPool.QueueUserWorkItem(_ => done.SetResult(23)));
        Need(await done.Task == 23); await FreshTimer();
        return "fresh:task:queue:timer:native-table";
    }
}
