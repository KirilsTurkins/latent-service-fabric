using ProbeWorld;
namespace ProbeWorld.wit.Exports.example.dotnetprobe;

// A compiler qualification probe, not an external RPC client.
public class OperationsExportsImpl : IOperationsExports
{
    private static uint calls;

    public static string Echo(string value) => value;

    public static ulong Wide(ulong value) => value;

    public static Result<IOperationsExports.Packet, string> Mirror(IOperationsExports.Packet value) =>
        value.text.Length == 0
            ? Result<IOperationsExports.Packet, string>.Err("empty\0text 世界")
            : Result<IOperationsExports.Packet, string>.Ok(value);

    public static uint Next() => ++calls;

    // Member lookup needs runtime hash-seed entropy in this compiler profile.
    // The separate negative probe proves it cannot acquire ambient authority.
    public static uint Reflection()
    {
        var method = typeof(OperationsExportsImpl).GetMethod(nameof(Wide), new[] { typeof(ulong) });
        return method?.ReturnType == typeof(ulong) ? 1U : 0U;
    }

    // These library operations are qualified independently of unsupported
    // reflection, dynamic code, threading or a persistent CLR event loop.
    public static uint Profile()
    {
        if (System.Runtime.CompilerServices.RuntimeFeature.IsDynamicCodeSupported ||
            System.Runtime.CompilerServices.RuntimeFeature.IsDynamicCodeCompiled)
            throw new System.InvalidOperationException("dynamic code enabled");
        const string text = "library\0世界 🚚";
        if (System.Text.Encoding.UTF8.GetString(System.Text.Encoding.UTF8.GetBytes(text)) != text)
            throw new System.InvalidOperationException("UTF-8 library mismatch");
        var completed = System.Threading.Tasks.Task.FromResult(17U);
        var uncompleted = new System.Threading.Tasks.TaskCompletionSource<uint>();
        if (completed.GetAwaiter().GetResult() != 17 || uncompleted.Task.IsCompleted)
            throw new System.InvalidOperationException("activation-local task mismatch");
        System.GC.Collect();
        System.GC.KeepAlive(uncompleted);
        return 17;
    }
}
