namespace ProbeWorld.wit.Exports.example.dotnetprobe;

// A compiler qualification probe, not an external RPC client.
public class OperationsExportsImpl : IOperationsExports
{
    private static uint calls;

    public static string Echo(string value) => value;

    public static ulong Wide(ulong value) => value;

    public static uint Next() => ++calls;
}
