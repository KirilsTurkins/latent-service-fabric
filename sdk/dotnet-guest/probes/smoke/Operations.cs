namespace ProbeWorld.wit.exports.example.dotnetprobe;

// A compiler qualification probe, not an external RPC client.
public class OperationsImpl : IOperations
{
    private static uint calls;

    public static string Echo(string value) => value;

    public static ulong Wide(ulong value) => value;

    public static uint Next() => ++calls;
}
