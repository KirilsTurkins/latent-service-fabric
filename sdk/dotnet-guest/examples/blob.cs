using Lsf.Guest;
using Raw = ServiceWorld.wit.Imports.latent.blob.IBlobImports;
namespace ServiceWorld.wit.Exports.tests.localBlobs;
public class ApiExportsImpl : IApiExports
{
    private static ulong Failure(Result<ulong, Raw.BlobError> result) => !result.IsOk ? result.AsErr.Tag switch {
        Raw.BlobError.Tags.InvalidState => 10UL,
        Raw.BlobError.Tags.PermissionDenied => 11UL,
        _ => throw new System.InvalidOperationException("unexpected blob result") }
        : throw new System.InvalidOperationException("stale blob handle succeeded");
    public static ulong Run(uint which, string text, ulong handle)
    {
        if (which == 4) return Failure(Raw.Write(handle, 0, []));
        using var scope = new Scope();
        var writer = scope.Own(Blob.Create("text/plain", which is 2 or 5 ? 0UL : 4UL).AsOk);
        if (which == 1) return 1;
        if (which == 5) return writer.Consume(value => value);
        if (which == 2) {
            var stale = writer.Borrow(value => value);
            _ = Blob.Close(writer).AsOk;
            return Failure(Raw.Write(stale, 0, []));
        }
        _ = Blob.Write(writer, 0, [100, 97, 116, 97]).AsOk;
        var reference = Blob.Seal(writer).AsOk;
        var reader = scope.Own(Blob.Open(reference).AsOk);
        var chunk = scope.Own(Blob.Read(reader, 0, 4).AsOk);
        _ = Blob.Close(reader).AsOk;
        if (which == 3) return 3;
        var bytes = Blob.ChunkBytes(chunk).AsOk;
        if (which == 6) {
            var again = Blob.ChunkBytes(chunk);
            if (!again.IsOk && again.AsErr.Tag == Raw.BlobError.Tags.InvalidState) return 10;
            throw new System.InvalidOperationException("materialized a chunk twice");
        }
        return (ulong)bytes.Length;
    }
}
