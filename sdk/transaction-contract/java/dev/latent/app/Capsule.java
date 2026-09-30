package dev.latent.app;

import dev.latent.generated.Bindings;
import dev.latent.guest.Option;
import dev.latent.guest.Unsigned64;
import java.util.List;

/** Actual compiler input. The host engine and executable SDK gate are separate. */
public final class Capsule implements Bindings.Exports {
    @Override public Unsigned64 run(Long mode) {
        if (mode == 0) {
            try (var view = Bindings.LatentStateKeyValue.acquireQuery().value()) {
                var identity = Bindings.LatentStateKeyValue.queryInfo(view).value();
                var value = Bindings.LatentStateKeyValue.getQuery(view, new byte[]{107}).value();
                try (var page = Bindings.LatentStateKeyValue.scanQuery(view, new byte[0], 1L, Option.none()).value()) {
                    var bounds = Bindings.LatentStateKeyValue.describePage(page).value();
                    var item = Bindings.LatentStateKeyValue.pageNext(page).value();
                    return Unsigned64.bits(identity.version().length + bounds.entryCount()
                        + (value.isSome() ? 1 : 0) + (item.isSome() ? 1 : 0));
                }
            }
        }
        try (var transaction = Bindings.LatentStateKeyValue.acquireCommand().value()) {
            var identity = Bindings.LatentStateKeyValue.info(transaction).value();
            var existing = Bindings.LatentStateKeyValue.get(transaction, new byte[]{107}).value();
            var value = new Bindings.LatentStateKeyValueValue(new byte[0], "application/octet-stream", List.of());
            Bindings.LatentStateKeyValue.put(transaction, new byte[]{107}, value).value();
            Bindings.LatentStateKeyValue.delete(transaction, new byte[]{107}).value();
            try (var page = Bindings.LatentStateKeyValue.scan(transaction, new byte[0], 1L, Option.none()).value()) {
                var bounds = Bindings.LatentStateKeyValue.describePage(page).value();
                var item = Bindings.LatentStateKeyValue.pageNext(page).value();
                var intent = new Bindings.LatentIntentsStagingIntent("approved-mail", "send", value,
                    Option.some(Unsigned64.bits(-1L)));
                var staged = Bindings.LatentIntentsStaging.stage(transaction, intent).value();
                return Unsigned64.bits(staged.sequence() + bounds.entryCount() + identity.commandId().length()
                    + (existing.isSome() ? 1 : 0) + (item.isSome() ? 1 : 0));
            }
        }
    }
}
