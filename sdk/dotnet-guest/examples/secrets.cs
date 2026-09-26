using Lsf.Guest;
using Raw = ServiceWorld.wit.Imports.latent.secrets.IReaderImports;
namespace ServiceWorld.wit.Exports.tests.localSecrets;
public class ApiExportsImpl : IApiExports
{
    public static ulong Run(uint which, string text, ulong handle)
    {
        var result = Secrets.Read(text);
        if (!result.IsOk) return result.AsErr.Tag switch {
            Raw.SecretError.Tags.PermissionDenied => 10,
            Raw.SecretError.Tags.NotFound => 11,
            Raw.SecretError.Tags.Expired => 12,
            Raw.SecretError.Tags.Unavailable => 13,
            _ => throw new System.InvalidOperationException("unexpected secret result") };
        using var value = result.AsOk;
        var copy = value.Use(bytes => bytes.ToArray());
        var original = (byte[])copy.Clone();
        value.Dispose();
        value.Dispose();
        bool rejected = false;
        try { value.Use(bytes => bytes.Length); }
        catch (System.InvalidOperationException) { rejected = true; }
        if (!rejected) throw new System.InvalidOperationException("closed secret was borrowed");
        for (int index = 0; index < copy.Length; index++)
            if (copy[index] != original[index]) throw new System.InvalidOperationException("application copy changed");

        // Exercise the exact facade's zeroization under the actual NativeAOT
        // compiler while retaining an alias solely for this ownership probe.
        var owned = new byte[] { 0, 1, 127, 128, 255 };
        using var probe = new Secret(new Raw.SecretValue(owned, "application/octet-stream", null, null));
        probe.Dispose();
        for (int index = 0; index < owned.Length; index++)
            if (owned[index] != 0) throw new System.InvalidOperationException("owned secret bytes were not erased");
        return (ulong)copy.Length;
    }
}
