// lsf-example-begin: capsule
package dev.latent.app;

import dev.latent.generated.Bindings;
import dev.latent.guest.*;
import java.util.List;

public final class Capsule implements Bindings.Exports {
    private static final byte[] KEY = {97,103,103,114,101,103,97,116,101,47,99,111,117,110,116};
    private static final String MEDIA = "application/vnd.lsf.aggregate-v1";
    private static Long count(Option<Bindings.LatentStateKeyValueVersionedValue> value) {
        if (!value.isSome()) return 0L;
        var payload = value.value().value();
        if (!payload.mediaType().equals(MEDIA) || !payload.metadata().isEmpty() || payload.bytes().length != 8) return null;
        long count = 0;
        for (int i = 0; i < 8; i++) count |= (payload.bytes()[i] & 255L) << (8 * i);
        return count;
    }
    @Override public Result<Bindings.ExamplesTransactionalAggregateApiAggregate, Bindings.ExamplesTransactionalAggregateApiBusinessError>
    update(Bindings.ExamplesTransactionalAggregateApiUpdateRequest request) {
        try (var command = State.acquireCommand().value()) {
            var old = count(command.get(KEY).value());
            if (old == null) return Result.err(Bindings.ExamplesTransactionalAggregateApiBusinessError.MalformedState);
            long next = old + request.delta();
            if (Long.compareUnsigned(next, old) < 0) return Result.err(Bindings.ExamplesTransactionalAggregateApiBusinessError.Overflow);
            byte[] bytes = new byte[8]; for (int i = 0; i < 8; i++) bytes[i] = (byte)(next >>> (8 * i));
            var payload = new Bindings.LatentStateKeyValueValue(bytes, MEDIA, List.of());
            command.put(KEY, payload).value();
            new Intent("approved-event", "event", payload).stage(command).value();
            if (request.reject()) return Result.err(Bindings.ExamplesTransactionalAggregateApiBusinessError.Rejected);
            var version = command.get(KEY).value().value().version();
            return Result.ok(new Bindings.ExamplesTransactionalAggregateApiAggregate(new Unsigned64(next), version));
        }
    }
    @Override public Result<Bindings.ExamplesTransactionalAggregateApiAggregate, Bindings.ExamplesTransactionalAggregateApiBusinessError> query() {
        try (var query = State.acquireQuery().value()) {
            var count = count(query.get(KEY).value());
            if (count == null) return Result.err(Bindings.ExamplesTransactionalAggregateApiBusinessError.MalformedState);
            return Result.ok(new Bindings.ExamplesTransactionalAggregateApiAggregate(new Unsigned64(count), query.info().value().version()));
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
