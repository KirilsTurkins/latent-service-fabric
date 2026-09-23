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
        return value.Use(bytes => (ulong)bytes.Length);
    }
}
