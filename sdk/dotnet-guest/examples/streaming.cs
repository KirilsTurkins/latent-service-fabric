using Lsf.Guest;
using Raw = ServiceWorld.wit.Imports.latent.http.IStreamingImports;
namespace ServiceWorld.wit.Exports.tests.streamingHttp;
public class ApiExportsImpl : IApiExports
{
    public static ulong Run(uint which, string text, ulong handle)
    {
        using var scope = new Scope();
        var opened = Streaming.Open(new Raw.Request(Raw.Method.POST, text, [], 4, "text/plain", null, 1000));
        if (!opened.IsOk) return opened.AsErr.Tag == Raw.HttpError.Tags.PermissionDenied
            ? 10UL : throw new System.InvalidOperationException("unexpected streaming error");
        var upload = scope.Own(opened.AsOk);
        if (which == 1) return 1;
        _ = Streaming.Write(upload, [100, 97, 116, 97]).AsOk;
        var response = Streaming.Finish(upload).AsOk;
        var body = scope.Own(response.Body);
        if (which == 2) return 2;
        var chunk = scope.Own(Streaming.Read(body, 4).AsOk ?? throw new System.InvalidOperationException("missing chunk"));
        if (which == 3) {
            body.Dispose();
            return (ulong)Streaming.ChunkBytes(chunk).AsOk.Length;
        }
        var bytes = Streaming.ChunkBytes(chunk).AsOk;
        if (Streaming.Read(body, 4).AsOk is not null) throw new System.InvalidOperationException("extra chunk");
        _ = Streaming.Trailers(body).AsOk;
        var again = Streaming.Trailers(body);
        if (again.IsOk || again.AsErr.Tag != Raw.HttpError.Tags.InvalidState) throw new System.InvalidOperationException("trailers replayed");
        return (ulong)bytes.Length;
    }
}
