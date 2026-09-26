using System.Text;
using Lsf.Guest;
using Raw = ServiceWorld.wit.Imports.latent.http.IClientImports;
namespace ServiceWorld.wit.Exports.tests.http;
public class ApiExportsImpl : IApiExports
{
    public static ulong Run(uint which, string text, ulong handle)
    {
        var result = Http.Send(new Raw.Request(which == 0 ? Raw.Method.GET : which == 1 ? Raw.Method.HEAD : Raw.Method.POST,
            text, [], Encoding.UTF8.GetBytes("payload"),
            "text/plain", null, 1000));
        if (!result.IsOk) return result.AsErr.Tag switch {
            Raw.HttpError.Tags.PermissionDenied => 10,
            Raw.HttpError.Tags.Uncertain => 11,
            _ => throw new System.InvalidOperationException("unexpected HTTP result") };
        var value = result.AsOk;
        return value.status + 1000UL * (ulong)(value.body?.Length ?? 0);
    }
}
