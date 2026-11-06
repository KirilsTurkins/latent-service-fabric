// lsf-example-begin: capsule
package dev.latent.app;

import dev.latent.generated.Bindings;
import dev.latent.guest.*;
import java.util.List;
import java.util.Arrays;
import java.nio.charset.StandardCharsets;

public final class Capsule implements Bindings.Exports {
    private static final byte[] UTF8_KEY = "aggregate/clé/🌍".getBytes(StandardCharsets.UTF_8);
    private static final byte[] ABSENT_KEY = "aggregate/absent/null".getBytes(StandardCharsets.UTF_8);
    private static final byte[] UTF8_VALUE = "[null,\"κλειδί / 値 / 🌍\"]".getBytes(StandardCharsets.UTF_8);
    private static int entries;
    private static void enter() { if (++entries != 1) throw new IllegalStateException("value-instance-reused"); }
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
        enter();
        try (var command = State.acquireCommand().value()) {
            var stored = command.get(KEY).value();
            var old = count(stored);
            if (old == null) return Result.err(Bindings.ExamplesTransactionalAggregateApiBusinessError.MalformedState);
            long next = request.delta() == 0xffff_fff0L ? Long.MIN_VALUE
                : request.delta() == 0xffff_fff1L ? -1L : old + request.delta();
            if (Long.compareUnsigned(next, old) < 0) return Result.err(Bindings.ExamplesTransactionalAggregateApiBusinessError.Overflow);
            var viewVersion = command.info().value().view().version();
            var keyVersion = stored.isSome() ? Option.some(stored.value().version()) : Option.<byte[]>none();
            byte[] bytes = new byte[8]; for (int i = 0; i < 8; i++) bytes[i] = (byte)(next >>> (8 * i));
            var payload = new Bindings.LatentStateKeyValueValue(bytes, MEDIA, List.of());
            command.put(KEY, payload).value();
            command.put(UTF8_KEY, new Bindings.LatentStateKeyValueValue(UTF8_VALUE, "application/json", List.of())).value();
            if (command.get(ABSENT_KEY).value().isSome()) throw new IllegalStateException("absent-command-value-changed");
            var effectPayload = new Bindings.LatentStateKeyValueValue(
                new byte[]{106,97,118,97,45,97,103,103,114,101,103,97,116,101,45,112,117,116,45,111,110,99,101,45,118,49,0}, "application/octet-stream", List.of());
            new Intent("qualified-http", "http", effectPayload).stage(command).value();
            if (request.reject()) return Result.err(Bindings.ExamplesTransactionalAggregateApiBusinessError.Rejected);
            return Result.ok(new Bindings.ExamplesTransactionalAggregateApiAggregate(new Unsigned64(next), viewVersion, keyVersion));
        }
    }
    @Override public Result<Bindings.ExamplesTransactionalAggregateApiAggregate, Bindings.ExamplesTransactionalAggregateApiBusinessError> query() {
        enter();
        try (var query = State.acquireQuery().value()) {
            var stored = query.get(KEY).value();
            var count = count(stored);
            var text = query.get(UTF8_KEY).value();
            if (stored.isSome()) {
                if (!text.isSome() || !text.value().value().mediaType().equals("application/json")
                    || !text.value().value().metadata().isEmpty()
                    || !Arrays.equals(text.value().value().bytes(), UTF8_VALUE))
                    throw new IllegalStateException("utf8-state-roundtrip-changed");
            } else if (text.isSome()) throw new IllegalStateException("uncommitted-utf8-value");
            if (query.get(ABSENT_KEY).value().isSome()) throw new IllegalStateException("absent-query-value-changed");
            if (count == null) return Result.err(Bindings.ExamplesTransactionalAggregateApiBusinessError.MalformedState);
            var keyVersion = stored.isSome() ? Option.some(stored.value().version()) : Option.<byte[]>none();
            return Result.ok(new Bindings.ExamplesTransactionalAggregateApiAggregate(new Unsigned64(count), query.info().value().version(), keyVersion));
        }
    }
    @Override public Result<Bindings.ExamplesTransactionalAggregateApiScanResult, Bindings.ExamplesTransactionalAggregateApiBusinessError>
    scan(byte[] prefix, Long limit, Option<byte[]> cursor) {
        enter();
        try (var query = State.acquireQuery().value(); var page = query.scan(prefix, limit, cursor).value()) {
            var info = page.info().value(); long count = 0;
            while (page.next().value().isSome()) count++;
            if (count != info.entryCount()) throw new IllegalStateException("page count mismatch");
            return Result.ok(new Bindings.ExamplesTransactionalAggregateApiScanResult(count, info.encodedBytes(), info.view().version(), info.nextCursor()));
        }
    }
}
// lsf-example-end: capsule
