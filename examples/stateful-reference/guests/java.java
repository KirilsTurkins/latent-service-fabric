// lsf-example-begin: order-draft
package dev.latent.app;

import dev.latent.generated.Bindings;
import dev.latent.guest.*;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.List;

public final class Capsule implements Bindings.Exports {
    private static final String MEDIA = "application/vnd.lsf.order-draft-v1";
    private static byte[][] keys(String id) {
        if (!id.matches("[a-z0-9][a-z0-9-]{0,31}")) return null;
        return new byte[][] {("drafts/" + id + "/draft").getBytes(StandardCharsets.UTF_8),
                             ("drafts/" + id + "/summary").getBytes(StandardCharsets.UTF_8)};
    }
    private static long[] decode(Option<Bindings.LatentStateKeyValueVersionedValue> primary,
                                 Option<Bindings.LatentStateKeyValueVersionedValue> summary) {
        if (!primary.isSome() && !summary.isSome()) return new long[] {0, 0};
        if (!primary.isSome() || !summary.isSome()) return null;
        var a = primary.value().value(); var b = summary.value().value();
        for (var value : List.of(a, b))
            if (!value.mediaType().equals(MEDIA) || !value.metadata().isEmpty() || value.bytes().length != 12) return null;
        if (!Arrays.equals(a.bytes(), b.bytes())) return null;
        long revision = 0, units = 0;
        for (int i = 0; i < 8; i++) revision |= (a.bytes()[i] & 255L) << (8 * i);
        for (int i = 0; i < 4; i++) units |= (a.bytes()[8 + i] & 255L) << (8 * i);
        return revision != 0 && units <= 10000 ? new long[] {revision, units} : null;
    }
    private static Option<byte[]> version(Option<Bindings.LatentStateKeyValueVersionedValue> value) {
        return value.isSome() ? Option.some(value.value().version()) : Option.none();
    }
    @Override public Result<Bindings.ExamplesOrderDraftApiDraft, Bindings.ExamplesOrderDraftApiBusinessError>
    edit(Bindings.ExamplesOrderDraftApiEditRequest request) {
        var keys = keys(request.draftId());
        if (keys == null) return Result.err(Bindings.ExamplesOrderDraftApiBusinessError.InvalidDraft);
        if (request.units() < 0 || request.units() > 10000) return Result.err(Bindings.ExamplesOrderDraftApiBusinessError.InvalidUnits);
        try (var command = State.acquireCommand().value()) {
            if (!command.info().value().view().namespace().equals("order-drafts-" + request.draftId()))
                return Result.err(Bindings.ExamplesOrderDraftApiBusinessError.InvalidDraft);
            var primary = command.get(keys[0]).value();
            var old = decode(primary, command.get(keys[1]).value());
            if (old == null) return Result.err(Bindings.ExamplesOrderDraftApiBusinessError.MalformedState);
            if (old[0] != request.expectedRevision().bits()) return Result.err(Bindings.ExamplesOrderDraftApiBusinessError.StaleEdit);
            if (old[0] == -1L) return Result.err(Bindings.ExamplesOrderDraftApiBusinessError.RevisionOverflow);
            long revision = old[0] + 1;
            byte[] bytes = new byte[12];
            for (int i = 0; i < 8; i++) bytes[i] = (byte)(revision >>> (8 * i));
            for (int i = 0; i < 4; i++) bytes[8 + i] = (byte)(request.units() >>> (8 * i));
            var value = new Bindings.LatentStateKeyValueValue(bytes, MEDIA, List.of());
            command.put(keys[0], value).value(); command.put(keys[1], value).value();
            byte[] id = request.draftId().getBytes(StandardCharsets.UTF_8);
            byte[] event = new byte[id.length + 13];
            System.arraycopy(id, 0, event, 0, id.length); System.arraycopy(bytes, 0, event, id.length + 1, 12);
            var payload = new Bindings.LatentStateKeyValueValue(event, MEDIA, List.of());
            new Intent("draft-change", "event", payload).stage(command).value();
            new Intent("draft-http", "put-once", payload).stage(command).value();
            if (request.reject()) return Result.err(Bindings.ExamplesOrderDraftApiBusinessError.Rejected);
            return Result.ok(new Bindings.ExamplesOrderDraftApiDraft(request.draftId(), new Unsigned64(revision), request.units(),
                command.info().value().view().version(), version(primary)));
        }
    }
    @Override public Result<Bindings.ExamplesOrderDraftApiDraft, Bindings.ExamplesOrderDraftApiBusinessError>
    query(String id) {
        var keys = keys(id);
        if (keys == null) return Result.err(Bindings.ExamplesOrderDraftApiBusinessError.InvalidDraft);
        try (var query = State.acquireQuery().value()) {
            if (!query.info().value().namespace().equals("order-drafts-" + id))
                return Result.err(Bindings.ExamplesOrderDraftApiBusinessError.InvalidDraft);
            var primary = query.get(keys[0]).value();
            var value = decode(primary, query.get(keys[1]).value());
            if (value == null) return Result.err(Bindings.ExamplesOrderDraftApiBusinessError.MalformedState);
            return Result.ok(new Bindings.ExamplesOrderDraftApiDraft(id, new Unsigned64(value[0]), value[1],
                query.info().value().version(), version(primary)));
        }
    }
}
// lsf-example-end: order-draft
