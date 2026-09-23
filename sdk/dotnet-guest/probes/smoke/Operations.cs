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

    // Only statically visible reflection metadata is supported by this trimmed
    // profile. This does not opt arbitrary reflection or dynamic code into it.
    public static uint Profile()
    {
        if (System.Runtime.CompilerServices.RuntimeFeature.IsDynamicCodeSupported ||
            System.Runtime.CompilerServices.RuntimeFeature.IsDynamicCodeCompiled)
            throw new System.InvalidOperationException("dynamic code enabled");
        var method = typeof(OperationsExportsImpl).GetMethod(nameof(Wide), new[] { typeof(ulong) });
        if (method?.ReturnType != typeof(ulong))
            throw new System.InvalidOperationException("rooted reflection metadata missing");
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
