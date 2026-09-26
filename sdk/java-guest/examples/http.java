package dev.latent.app;
import dev.latent.generated.Bindings;
import dev.latent.generated.Bindings.*;
import dev.latent.guest.*;
import java.nio.charset.StandardCharsets;
import java.util.List;

public final class Capsule implements Bindings.Exports {
    public Unsigned64 run(Long which, String text, Unsigned64 handle) {
        var method = which == 0 ? LatentHttpClientMethod.Get : which == 1 ? LatentHttpClientMethod.Head : LatentHttpClientMethod.Post;
        var result = LatentHttpClient.send(new LatentHttpClientRequest(method, text, List.of(),
            Option.some("payload".getBytes(StandardCharsets.UTF_8)), Option.some("text/plain"),
            Option.none(), Option.some(new Unsigned64(1000))));
        if (!result.isError()) return new Unsigned64(result.value().status() + 1000L * result.value().body().length);
        return new Unsigned64(switch (result.error().tag()) {
            case 2 -> 10; case 12 -> 11; default -> throw new IllegalStateException("unexpected HTTP error");
        });
    }
}
