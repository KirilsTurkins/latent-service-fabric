package dev.latent.app;
import dev.latent.generated.Bindings;
import dev.latent.guest.Result;

// lsf-example-begin: capsule
public final class Capsule implements Bindings.Exports {
    public Result<Long, String> quote(Long items, Boolean express) {
        if (items < 1 || items > 100) return Result.err("Choose between 1 and 100 items.");
        return Result.ok((express ? 1200L : 500L) + items * 75L);
    }
}
// lsf-example-end: capsule
