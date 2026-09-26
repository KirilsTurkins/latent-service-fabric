package dev.latent.app;
import dev.latent.generated.Bindings;
import dev.latent.generated.Bindings.*;
import dev.latent.guest.*;
import java.nio.charset.StandardCharsets;
import java.util.List;

public final class Capsule implements Bindings.Exports {
    public Unsigned64 run(Long which, String text, Unsigned64 handle) {
        var event = new LatentEventsPublisherEvent(text, Option.none(), "payload".getBytes(StandardCharsets.UTF_8),
            "text/plain", List.of(), "guest-sdk-" + handle.toString());
        var result = LatentEventsPublisher.publish(event);
        if (!result.isError()) {
            var receipt = result.value();
            if (receipt.eventId().isEmpty() || receipt.streamName().isEmpty()) throw new IllegalStateException("missing publication receipt");
            return receipt.sequence();
        }
        // Uncertain publication is a terminal declared outcome, never retried.
        return new Unsigned64(switch (result.error().tag()) {
            case 2 -> 10; case 7 -> 11; default -> throw new IllegalStateException("unexpected publication error");
        });
    }
}
