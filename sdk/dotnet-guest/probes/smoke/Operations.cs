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
}
