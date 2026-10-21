using System;
using System.Threading.Tasks;
using OutsideDiagnosticsData;

namespace OutsideDiagnostics;

// Original default Task admission/context/continuations; no injected scheduler.
public sealed class Library
{
    private static int calls;
    public Library() { _ = new Core(); }
    private static int Callback() => Core.Fallback();
    private static int FailingCallback() { Core.Uncaught(); return 0; }
    public string Run(string mode)
    {
        if (++calls != 1) throw new InvalidOperationException("diagnostics-activation-state-leaked");
        if (mode is "init" or "fresh")
            return "diagnostics|" + mode + "|" + Core.State(2) + "|fallback=42|fresh=1";
        if (mode == "init-trap")
        {
            Core.InitializationFailure();
            throw new InvalidOperationException("diagnostics-initializer-returned");
        }
        if (mode == "callback-trap")
        {
            _ = Task.Run(FailingCallback).GetAwaiter().GetResult();
            throw new InvalidOperationException("diagnostics-callback-returned");
        }
        if (mode != "callback") throw new ArgumentException("diagnostics-unknown-mode");
        int answer = Task.Run(Callback).GetAwaiter().GetResult();
        if (answer != 42) throw new InvalidOperationException("diagnostics-callback-answer");
        return "diagnostics|callback|" + Core.State(3) + "|fallback=42|joined=1|fresh=1";
    }
}
