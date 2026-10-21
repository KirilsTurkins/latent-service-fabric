using Lsf.CompilerOwned;
using System.Text.Json;

internal static class TimerControl
{
    internal sealed class State { internal bool Scheduled; internal int Callbacks; }
    internal static readonly Queue<Action> Work = new();
    private static readonly Dictionary<ulong, int> Owners = new();
    private static readonly int[] Limits = [8, 1, 1, 8, 8, 2, 8, 1];
    private static ulong sequence = uint.MaxValue;
    private static bool closing;
    private static (ulong, ulong) context;
    private static int admissions;
    private static int Count(int kind) => Owners.Values.Count(value => value == kind);
    private static void Need(bool value)
    { if (!value) throw new InvalidOperationException("timer-control-assertion"); }
    private static void Refuses(Action action, string code)
    {
        try { action(); }
        catch (InvalidOperationException error) when (error.Message == code) { return; }
        throw new InvalidOperationException("timer-control-missing-refusal");
    }
    private static (ulong, ulong) Reserve(int kind, ulong generation, ulong id)
    {
        Need(0 <= kind && kind < Limits.Length);
        if ((generation, id) != (0UL, 0UL)) Need(generation == 19 && Owners.ContainsKey(id));
        if (closing) Need(generation == 19 && Owners.ContainsKey(id));
        if (Count(kind) >= Limits[kind]) throw new InvalidOperationException("control-ledger-capacity");
        admissions++; ulong key = checked(++sequence); Owners.Add(key, kind); return (19, key);
    }
    private static void Settle(ulong generation, ulong id)
    { Need(generation == 19 && id > uint.MaxValue && Owners.Remove(id)); }
    internal static void Step() { Need(Work.Count != 0); Work.Dequeue()(); }
    private static void Begin() => ManagedWorkRuntime.Install(Reserve, Settle,
        () => closing = true, (generation, id) => context = (generation, id));
    private static void Finish()
    {
        ManagedWorkRuntime.JoinAcceptedWork(); ManagedWorkRuntime.FinishedPhysicalDrain();
        Need(Owners.Count == 0 && context == (0UL, 0UL) && Work.Count == 0);
    }
    private static State Arm()
    {
        var item = new State(); ManagedWorkRuntime.TimerChanging(item);
        item.Scheduled = true; ManagedWorkRuntime.TimerChanged(item); return item;
    }
    private static void Disarm(State item)
    { item.Scheduled = false; ManagedWorkRuntime.TimerDeleted(item); }
    private static void Fire(State item, Action callback)
    {
        var previous = ManagedWorkRuntime.TimerEnter(item);
        try { item.Callbacks++; callback(); item.Callbacks--; }
        finally { ManagedWorkRuntime.TimerLeave(item, previous); }
    }
    private static void Run(string name)
    {
        if (name == "native-storage-refusal-rolls-back-root")
        {
            Limits[7] = 0; Refuses(Begin, "control-ledger-capacity");
            Need(Owners.Count == 0 && admissions == 1); return;
        }
        Begin();
        switch (name)
        {
            case "timer-admission-before-mutation-and-fresh": {
                Limits[5] = 1; var first = Arm(); var refused = new State(); int before = admissions;
                Refuses(() => ManagedWorkRuntime.TimerChanging(refused), "control-ledger-capacity");
                Need(!refused.Scheduled && Count(5) == 1 && admissions == before);
                Disarm(first); Need(Count(5) == 0);
                var fresh = Arm(); Need(Count(5) == 1); Disarm(fresh); Finish(); break;
            }
            case "change-reuses-original-owner": {
                Limits[5] = 1; var item = Arm(); int before = admissions;
                ManagedWorkRuntime.TimerChanging(item); ManagedWorkRuntime.TimerChanging(item);
                ManagedWorkRuntime.TimerChanged(item); Need(Count(5) == 1);
                ManagedWorkRuntime.TimerChanged(item); Need(admissions == before);
                Disarm(item); Finish(); break;
            }
            case "failed-change-rolls-back-unused-owner": {
                var item = new State(); ManagedWorkRuntime.TimerChanging(item);
                Need(Count(5) == 1); ManagedWorkRuntime.TimerChanged(item);
                Need(Count(5) == 0); Finish(); break;
            }
            case "one-shot-delete-is-not-callback-return": {
                var item = Arm(); ManagedWorkRuntime.TimerAccepted(item); Disarm(item);
                Need(Count(5) == 1); Fire(item, () => Need(Count(5) == 1 && context.Item2 != 0));
                Need(Count(5) == 0); Finish(); break;
            }
            case "multiple-queued-callbacks-retain-one-timer": {
                var item = Arm();
                for (int i = 0; i < 2; i++) { ManagedWorkRuntime.TimerAccepted(item); ManagedWorkRuntime.Enqueue(item); }
                Disarm(item); Need(Count(5) == 1 && Count(3) == 2 && Count(0) == 1);
                for (int i = 0; i < 2; i++) {
                    ManagedWorkRuntime.Dequeue(item); var previous = ManagedWorkRuntime.EnterDispatch(item);
                    try { Fire(item, () => Need(Count(5) == 1)); }
                    finally { ManagedWorkRuntime.Exit(previous); ManagedWorkRuntime.CallbackCompleted(item); }
                    Need(Count(5) == (i == 0 ? 1 : 0));
                }
                Finish(); break;
            }
            case "disposed-queued-callback-retires-after-cancelled-fire": {
                var item = Arm(); ManagedWorkRuntime.TimerAccepted(item); Disarm(item);
                Need(Count(5) == 1); var previous = ManagedWorkRuntime.TimerEnter(item);
                ManagedWorkRuntime.TimerLeave(item, previous); Need(Count(5) == 0); Finish(); break;
            }
            case "callback-required-task-survives-return": {
                var item = Arm(); var actual = new TaskCompletionSource<int>();
                ManagedWorkRuntime.TimerAccepted(item); Disarm(item);
                Fire(item, () => ManagedWorkRuntime.CreatedAsync(actual.Task));
                Need(Count(5) == 1 && !actual.Task.IsCompleted);
                Work.Enqueue(() => actual.SetResult(7)); Finish(); break;
            }
            case "live-timer-descendant-during-closing": {
                var item = Arm();
                Work.Enqueue(() => {
                    Need(closing); ManagedWorkRuntime.TimerAccepted(item); Disarm(item);
                    Fire(item, () => {
                        var actual = new TaskCompletionSource<int>(); ManagedWorkRuntime.CreatedAsync(actual.Task);
                        var child = new TaskCompletionSource<int>(); ManagedWorkRuntime.Schedule(child.Task);
                        Need(Count(0) == 2 && Count(5) == 1);
                        Work.Enqueue(() => { child.SetResult(4); ManagedWorkRuntime.Completed(child.Task); actual.SetResult(9); });
                    });
                    Need(Count(5) == 1);
                }); Finish(); break;
            }
            case "callback-throw-never-refunds-original-running-owner": {
                var item = Arm(); ManagedWorkRuntime.TimerAccepted(item); Disarm(item);
                var original = new ArgumentException("synthetic-public-timer-control");
                try { Fire(item, () => throw original); }
                catch (ArgumentException error) { Need(ReferenceEquals(error, original)); }
                Need(item.Callbacks == 1 && Count(5) == 1);
                Refuses(ManagedWorkRuntime.JoinAcceptedWork, "managed-work-unproven-quiescence");
                Refuses(ManagedWorkRuntime.FinishedPhysicalDrain, "managed-work-finalization-timers"); break;
            }
            case "timer-structural-bound-before-ledger": {
                Limits[5] = 32; var items = Enumerable.Range(0, 32).Select(_ => Arm()).ToArray();
                int before = admissions; Refuses(() => Arm(), "managed-timer-record-limit");
                Need(admissions == before && Count(5) == 32);
                foreach (var item in items) Disarm(item); Finish(); break;
            }
            default: throw new InvalidOperationException("unknown-timer-control");
        }
    }
    private static void Main(string[] args)
    {
        Need(args.Length == 1); Run(args[0]);
        Console.WriteLine(JsonSerializer.Serialize(new { control = args[0], passed = true,
            registryCore = "production-source", nativeLedger = "explicit-test-port",
            timerProducerState = "explicit-test-port", actualClrTasks = true, guestQualified = false }));
    }
}
