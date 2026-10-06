// lsf-example-begin: order-draft
using System;
using System.Buffers.Binary;
using System.Text;
using Lsf.Guest;
using ServiceWorld;
using Raw = ServiceWorld.wit.Imports.latent.state.IKeyValueImports;
namespace ServiceWorld.wit.Exports.examples.orderDraft;

public class ApiExportsImpl : IApiExports
{
    private const string Media = "application/vnd.lsf.order-draft-v1";
    private static (byte[], byte[])? Keys(string id) {
        if (id.Length == 0 || id.Length > 32) return null;
        for (int i = 0; i < id.Length; i++) {
            char c = id[i];
            if (!(c >= 'a' && c <= 'z') && !(c >= '0' && c <= '9') && !(i > 0 && c == '-')) return null;
        }
        return (Encoding.UTF8.GetBytes("drafts/" + id + "/draft"), Encoding.UTF8.GetBytes("drafts/" + id + "/summary"));
    }
    private static (ulong revision, uint units)? Decode(Raw.VersionedValue? primary, Raw.VersionedValue? summary) {
        if (!primary.HasValue && !summary.HasValue) return (0, 0);
        if (!primary.HasValue || !summary.HasValue) return null;
        foreach (var value in new[] {primary.Value.value, summary.Value.value})
            if (value.mediaType != Media || value.metadata.Count != 0 || value.bytes.Length != 12) return null;
        var bytes = primary.Value.value.bytes;
        if (!bytes.AsSpan().SequenceEqual(summary.Value.value.bytes)) return null;
        ulong revision = BinaryPrimitives.ReadUInt64LittleEndian(bytes);
        uint units = BinaryPrimitives.ReadUInt32LittleEndian(bytes.AsSpan(8));
        return revision != 0 && units <= 10000 ? (revision, units) : null;
    }
    public static Result<IApiExports.Draft, IApiExports.BusinessError> Edit(IApiExports.EditRequest request) {
        var keys = Keys(request.draftId);
        if (!keys.HasValue) return Result<IApiExports.Draft, IApiExports.BusinessError>.Err(IApiExports.BusinessError.INVALID_DRAFT);
        if (request.units > 10000) return Result<IApiExports.Draft, IApiExports.BusinessError>.Err(IApiExports.BusinessError.INVALID_UNITS);
        using var command = State.AcquireCommand().AsOk;
        if (command.Info().AsOk.view.@namespace != "order-drafts-" + request.draftId)
            return Result<IApiExports.Draft, IApiExports.BusinessError>.Err(IApiExports.BusinessError.INVALID_DRAFT);
        var primary = command.Get(keys.Value.Item1).AsOk;
        var old = Decode(primary, command.Get(keys.Value.Item2).AsOk);
        if (!old.HasValue) return Result<IApiExports.Draft, IApiExports.BusinessError>.Err(IApiExports.BusinessError.MALFORMED_STATE);
        if (old.Value.revision != request.expectedRevision) return Result<IApiExports.Draft, IApiExports.BusinessError>.Err(IApiExports.BusinessError.STALE_EDIT);
        if (old.Value.revision == ulong.MaxValue) return Result<IApiExports.Draft, IApiExports.BusinessError>.Err(IApiExports.BusinessError.REVISION_OVERFLOW);
        ulong revision = old.Value.revision + 1;
        byte[] bytes = new byte[12]; BinaryPrimitives.WriteUInt64LittleEndian(bytes, revision);
        BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(8), request.units);
        var value = new Raw.Value(bytes, Media, []);
        _ = command.Put(keys.Value.Item1, value).AsOk; _ = command.Put(keys.Value.Item2, value).AsOk;
        byte[] eventBytes = Encoding.UTF8.GetBytes("draft-change-v1:" + request.draftId);
        var payload = new Raw.Value(eventBytes, "application/octet-stream", []);
        _ = new Intent("draft-change", "event", payload).Stage(command).AsOk;
        _ = new Intent("draft-http", "put-once", payload).Stage(command).AsOk;
        if (request.reject) return Result<IApiExports.Draft, IApiExports.BusinessError>.Err(IApiExports.BusinessError.REJECTED);
        return Result<IApiExports.Draft, IApiExports.BusinessError>.Ok(new(request.draftId, revision, request.units,
            command.Info().AsOk.view.version, primary.HasValue ? primary.Value.version : null));
    }
    public static Result<IApiExports.Draft, IApiExports.BusinessError> Query(string id) {
        var keys = Keys(id);
        if (!keys.HasValue) return Result<IApiExports.Draft, IApiExports.BusinessError>.Err(IApiExports.BusinessError.INVALID_DRAFT);
        using var query = State.AcquireQuery().AsOk;
        if (query.Info().AsOk.@namespace != "order-drafts-" + id)
            return Result<IApiExports.Draft, IApiExports.BusinessError>.Err(IApiExports.BusinessError.INVALID_DRAFT);
        var primary = query.Get(keys.Value.Item1).AsOk;
        var value = Decode(primary, query.Get(keys.Value.Item2).AsOk);
        return value.HasValue
            ? Result<IApiExports.Draft, IApiExports.BusinessError>.Ok(new(id, value.Value.revision, value.Value.units,
                query.Info().AsOk.version, primary.HasValue ? primary.Value.version : null))
            : Result<IApiExports.Draft, IApiExports.BusinessError>.Err(IApiExports.BusinessError.MALFORMED_STATE);
    }
}
// lsf-example-end: order-draft
