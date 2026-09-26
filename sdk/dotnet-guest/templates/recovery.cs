using System;
using System.Threading.Tasks;
namespace ServiceWorld.wit.Exports.examples.recovery;

public class ApiExportsImpl : IApiExports
{
    private static uint calls;
    private static TaskCompletionSource<uint>? pending;
    private static byte[][]? retained;
    public static uint Run(uint which)
    {
        pending = new TaskCompletionSource<uint>();
        if (which == 1) throw new InvalidOperationException("deliberate guest failure");
        if (which == 2) {
            retained = new byte[32][];
            for (int index = 0; index < retained.Length; ++index) retained[index] = new byte[16 * 1024 * 1024];
            return (uint)retained.Length;
        }
        if (which == 3) while (true) { /* Host fuel, epoch and cancellation remain active. */ }
        return Task.FromResult(++calls).GetAwaiter().GetResult();
    }
}
