using Lsf.Guest;
using Raw = ServiceWorld.wit.Imports.latent.random.IRandomImports;
namespace ServiceWorld.wit.Exports.tests.random;
public class ApiExportsImpl : IApiExports
{
    public static ulong Run(uint which, string text, ulong handle)
    {
        if (which == 1) { _ = Random.U64().AsOk; return 8; }
        var result = Random.Bytes(which == 2 ? uint.MaxValue : 32);
        if (!result.IsOk && result.AsErr.Tag == Raw.RandomError.Tags.InvalidLength) return 10;
        return (ulong)result.AsOk.Length;
    }
}
