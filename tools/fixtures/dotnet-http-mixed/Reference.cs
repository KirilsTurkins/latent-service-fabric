using System.Reflection;
using ServiceWorld.wit.Exports.examples.dotnetStandardHttp;

namespace ServiceWorld.wit.Exports.examples.dotnetStandardHttp {
    public interface IApiExports { }
}

// The CLR reference never calls Accepted; real phase observation is supplied
// only by the generated component binding in the signed owning campaign.
namespace ServiceWorld.wit.Imports.latent.runtime {
    public static class IActivationImports {
        public enum Phase { CLOSING }
        public struct Observation { public Phase phase; }
        public struct ObservationResult { public bool IsOk; public Observation AsOk; }
        public static ObservationResult Observe() => throw new PlatformNotSupportedException("component-only phase observation");
    }
}

public static class Reference {
    public static async Task Main() {
        var outer = typeof(ApiExportsImpl);
        var gated = outer.GetNestedType("GatedContent", BindingFlags.NonPublic)!;
        var gate = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        using var content = (HttpContent)Activator.CreateInstance(gated, gate.Task, 4096, 4096)!;
        using var output = new MemoryStream();
        var task = content.CopyToAsync(output);
        var entered = (TaskCompletionSource<bool>)gated.GetField("Entered")!.GetValue(content)!;
        await entered.Task;
        if (task.IsCompleted || output.Length != 4 || (bool)gated.GetField("Finished")!.GetValue(content)!)
            throw new InvalidOperationException("actual producer did not stop after first bytes");
        gate.SetResult(true); await task;
        if (output.Length != 4096 || !(bool)gated.GetField("Finished")!.GetValue(content)!)
            throw new InvalidOperationException("actual producer bytes or completion changed");
        output.WriteByte(42);
        var tracked = outer.GetNestedType("TrackedStream", BindingFlags.NonPublic)!;
        var source = (Stream)Activator.CreateInstance(tracked, new byte[4096], false)!;
        using (var owned = new StreamContent(source)) {
            if (owned.Headers.ContentLength != 4096 || (int)tracked.GetField("Disposals")!.GetValue(source)! != 0)
                throw new InvalidOperationException("actual StreamContent ownership or length changed");
        }
        if ((int)tracked.GetField("Disposals")!.GetValue(source)! != 1)
            throw new InvalidOperationException("actual StreamContent did not dispose its owned source exactly once");
        var logical = new TaskCompletionSource<int>(TaskCreationOptions.RunContinuationsAsynchronously);
        if (!logical.TrySetCanceled()) throw new InvalidOperationException("actual cancellation was refused");
        try { await logical.Task; throw new InvalidOperationException("actual cancellation was lost"); }
        catch (OperationCanceledException) { }
        if (logical.TrySetResult(4109) || !logical.Task.IsCanceled)
            throw new InvalidOperationException("late actual TaskCompletionSource overwrote cancellation");
        Console.WriteLine("managed-reference:incomplete-producer:4096:borrowed-output:owned-dispose:late-cancel-preserved");
    }
}
