// lsf-example-begin: capsule
using System;
using System.Buffers.Binary;
using Lsf.Guest;
using ServiceWorld;
using Raw = ServiceWorld.wit.Imports.latent.state.IKeyValueImports;
namespace ServiceWorld.wit.Exports.examples.transactionalAggregate;

public class ApiExportsImpl : IApiExports
{
    private static readonly byte[] Key = [97,103,103,114,101,103,97,116,101,47,99,111,117,110,116];
    private const string Media = "application/vnd.lsf.aggregate-v1";
    private static ulong? Count(Raw.VersionedValue? value) {
        if (!value.HasValue) return 0;
        var payload = value.Value.value;
        if (payload.mediaType != Media || payload.metadata.Count != 0 || payload.bytes.Length != 8) return null;
        return BinaryPrimitives.ReadUInt64LittleEndian(payload.bytes);
    }
    public static Result<IApiExports.Aggregate, IApiExports.BusinessError> Update(IApiExports.UpdateRequest request) {
        using var command = State.AcquireCommand().AsOk;
        var old = Count(command.Get(Key).AsOk);
        if (!old.HasValue) return Result<IApiExports.Aggregate, IApiExports.BusinessError>.Err(IApiExports.BusinessError.MALFORMED_STATE);
        if (ulong.MaxValue - old.Value < request.delta) return Result<IApiExports.Aggregate, IApiExports.BusinessError>.Err(IApiExports.BusinessError.OVERFLOW);
        var next = old.Value + request.delta;
        byte[] bytes = new byte[8]; BinaryPrimitives.WriteUInt64LittleEndian(bytes, next);
        var payload = new Raw.Value(bytes, Media, []);
        _ = command.Put(Key, payload).AsOk;
        _ = new Intent("approved-event", "event", payload).Stage(command).AsOk;
        if (request.reject) return Result<IApiExports.Aggregate, IApiExports.BusinessError>.Err(IApiExports.BusinessError.REJECTED);
        var version = command.Get(Key).AsOk!.Value.version;
        return Result<IApiExports.Aggregate, IApiExports.BusinessError>.Ok(new(next, version));
    }
    public static Result<IApiExports.Aggregate, IApiExports.BusinessError> Query() {
        using var query = State.AcquireQuery().AsOk;
        var count = Count(query.Get(Key).AsOk);
        return count.HasValue
            ? Result<IApiExports.Aggregate, IApiExports.BusinessError>.Ok(new(count.Value, query.Info().AsOk.version))
            : Result<IApiExports.Aggregate, IApiExports.BusinessError>.Err(IApiExports.BusinessError.MALFORMED_STATE);
    }
    public static Result<IApiExports.ScanResult, IApiExports.BusinessError> Scan(byte[] prefix, uint limit, byte[]? cursor) {
        using var query = State.AcquireQuery().AsOk;
        using var page = query.Scan(prefix, limit, cursor).AsOk;
        var info = page.Info().AsOk; uint count = 0;
        while (page.Next().AsOk.HasValue) count++;
        if (count != info.entryCount) throw new InvalidOperationException("page count mismatch");
        return Result<IApiExports.ScanResult, IApiExports.BusinessError>.Ok(new(count, info.encodedBytes, info.view.version, info.nextCursor));
    }
}
// lsf-example-end: capsule
