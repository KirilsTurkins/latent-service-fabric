package dev.latent.app;
import dev.latent.generated.Bindings;
import dev.latent.guest.Option;
import dev.latent.guest.Result;
import java.util.List;

// lsf-example-begin: capsule
public final class Capsule implements Bindings.Exports {
    public Result<Integer, Bindings.LatentHttpClientHttpError> check(String url) {
        var request = new Bindings.LatentHttpClientRequest(Bindings.LatentHttpClientMethod.Get,
            url, List.of(), Option.none(), Option.none(), Option.none(), Option.none());
        var response = Bindings.LatentHttpClient.send(request);
        if (response.isError()) return Result.err(response.error());
        // No automatic retries, URL policy shortcuts, or secret logging.
        return Result.ok(response.value().status());
    }
}
// lsf-example-end: capsule
