// lsf-example-begin: capsule
package dev.latent.app;

import dev.latent.generated.Bindings;
import dev.latent.guest.*;
import java.util.List;

public final class Capsule implements Bindings.Exports {
    private static final byte[] KEY = {97,103,103,114,101,103,97,116,101,47,99,111,117,110,116};
    private static final boolean WRITE_V2 = false;
    private static final String MEDIA = AggregateCodec.mediaType(WRITE_V2);
    private static Long count(Option<Bindings.LatentStateKeyValueVersionedValue> value) {
        if (!value.isSome()) return 0L;
        var payload = value.value().value();
        if (!payload.metadata().isEmpty()) return null;
        return AggregateCodec.decode(payload.mediaType(), payload.bytes(), true);
    }
    @Override public Result<Bindings.ExamplesTransactionalAggregateApiAggregate, Bindings.ExamplesTransactionalAggregateApiBusinessError>
    update(Bindings.ExamplesTransactionalAggregateApiUpdateRequest request) {
        try (var command = State.acquireCommand().value()) {
            var stored = command.get(KEY).value();
            var old = count(stored);
            if (old == null) return Result.err(Bindings.ExamplesTransactionalAggregateApiBusinessError.MalformedState);
            long next = old + request.delta();
            if (Long.compareUnsigned(next, old) < 0) return Result.err(Bindings.ExamplesTransactionalAggregateApiBusinessError.Overflow);
            var viewVersion = command.info().value().view().version();
            var keyVersion = stored.isSome() ? Option.some(stored.value().version()) : Option.<byte[]>none();
            byte[] bytes = AggregateCodec.encode(next, WRITE_V2);
            var payload = new Bindings.LatentStateKeyValueValue(bytes, MEDIA, List.of());
            command.put(KEY, payload).value();
            var effectPayload = new Bindings.LatentStateKeyValueValue(
                new byte[]{106,97,118,97,45,97,103,103,114,101,103,97,116,101,45,112,117,116,45,111,110,99,101,45,118,49,0}, "application/octet-stream", List.of());
            new Intent("qualified-http", "http", effectPayload).stage(command).value();
            if (request.reject()) return Result.err(Bindings.ExamplesTransactionalAggregateApiBusinessError.Rejected);
            return Result.ok(new Bindings.ExamplesTransactionalAggregateApiAggregate(new Unsigned64(next), viewVersion, keyVersion));
        }
    }
    @Override public Result<Bindings.ExamplesTransactionalAggregateApiAggregate, Bindings.ExamplesTransactionalAggregateApiBusinessError> query() {
        try (var query = State.acquireQuery().value()) {
            var stored = query.get(KEY).value();
            var count = count(stored);
            if (count == null) return Result.err(Bindings.ExamplesTransactionalAggregateApiBusinessError.MalformedState);
            var keyVersion = stored.isSome() ? Option.some(stored.value().version()) : Option.<byte[]>none();
            return Result.ok(new Bindings.ExamplesTransactionalAggregateApiAggregate(new Unsigned64(count), query.info().value().version(), keyVersion));
        }
    }
    @Override public Result<Bindings.ExamplesTransactionalAggregateApiScanResult, Bindings.ExamplesTransactionalAggregateApiBusinessError>
    scan(byte[] prefix, Long limit, Option<byte[]> cursor) {
        try (var query = State.acquireQuery().value(); var page = query.scan(prefix, limit, cursor).value()) {
            var info = page.info().value(); long count = 0;
            while (page.next().value().isSome()) count++;
            if (count != info.entryCount()) throw new IllegalStateException("page count mismatch");
            return Result.ok(new Bindings.ExamplesTransactionalAggregateApiScanResult(count, info.encodedBytes(), info.view().version(), info.nextCursor()));
        }
    }
}
// lsf-example-end: capsule
